import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from extractor import (
    create_zip,
    download_youtube_video,
    extract_frames_interval,
    extract_frames_scene_change,
)
from security import (
    MAX_UPLOAD_SIZE,
    parse_and_validate_timestamp,
    safe_path_join,
    sanitize_filename,
    validate_file_extension,
    validate_job_id,
    validate_video_magic_bytes,
    validate_youtube_url,
)

logger = logging.getLogger("vidslide")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TEMP_BASE_DIR = tempfile.mkdtemp(prefix="vidslide_")
IS_VERCEL = os.environ.get("VERCEL") == "1"
JOB_TTL_SECONDS = int(os.environ.get("JOB_TTL_SECONDS", 3600))
MAX_STORED_JOBS = 50


@asynccontextmanager
async def lifespan(app: FastAPI):
    global TEMP_BASE_DIR
    if not TEMP_BASE_DIR or not os.path.exists(TEMP_BASE_DIR):
        TEMP_BASE_DIR = tempfile.mkdtemp(prefix="vidslide_")
    yield
    if TEMP_BASE_DIR and os.path.exists(TEMP_BASE_DIR) and not IS_VERCEL:
        shutil.rmtree(TEMP_BASE_DIR, ignore_errors=True)


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="VidSlide API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if os.environ.get("ENV") == "production" else "/docs",
    redoc_url=None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "https://vid-slide.vercel.app",
]
cors_origins_env = os.environ.get("CORS_ORIGINS", "")
allowed_origins = list(DEFAULT_ALLOWED_ORIGINS)
if cors_origins_env:
    allowed_origins.extend(
        [origin.strip().rstrip("/") for origin in cors_origins_env.split(",") if origin.strip()]
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Authorization"],
)


def _is_allowed_origin(origin: str) -> bool:
    if not origin:
        return False
    clean = origin.rstrip("/")
    return clean in allowed_origins


@app.middleware("http")
async def security_and_pna_headers(request: Request, call_next):
    origin = request.headers.get("origin", "")
    if request.method == "OPTIONS":
        resp = Response(status_code=204)
        if _is_allowed_origin(origin):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept, Authorization"
            resp.headers["Access-Control-Allow-Private-Network"] = "true"
            resp.headers["Vary"] = "Origin"
        return resp

    response = await call_next(request)
    if _is_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Vary"] = "Origin"

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


jobs: dict[str, dict] = {}
processing_semaphore = asyncio.Semaphore(3)


def cleanup_expired_jobs() -> None:
    """Remove expired or excess completed jobs to prevent disk and memory exhaustion."""
    now = time.time()
    expired_ids = [
        jid
        for jid, j in list(jobs.items())
        if j.get("status") in ("completed", "failed")
        and (now - j.get("created_at", now)) > JOB_TTL_SECONDS
    ]
    for jid in expired_ids:
        job = jobs.pop(jid, None)
        if job and job.get("temp_dir") and os.path.exists(job["temp_dir"]):
            shutil.rmtree(job["temp_dir"], ignore_errors=True)

    if len(jobs) > MAX_STORED_JOBS:
        finished = sorted(
            [
                (jid, j.get("created_at", 0))
                for jid, j in jobs.items()
                if j.get("status") in ("completed", "failed")
            ],
            key=lambda item: item[1],
        )
        for jid, _ in finished[: max(0, len(jobs) - MAX_STORED_JOBS)]:
            job = jobs.pop(jid, None)
            if job and job.get("temp_dir") and os.path.exists(job["temp_dir"]):
                shutil.rmtree(job["temp_dir"], ignore_errors=True)


def sanitize_error_message(exc: Exception) -> str:
    """Return user-safe error messages without leaking internal paths or stack traces."""
    if isinstance(exc, ValueError):
        return str(exc)
    raw = str(exc)
    safe_keywords = (
        "unavailable",
        "private",
        "age-restricted",
        "live stream",
        "duration",
        "exceeds maximum",
        "timed out",
    )
    if any(k in raw.lower() for k in safe_keywords):
        # Strip any local filesystem paths if present
        return "Video could not be downloaded from YouTube. Please verify the video is public and not a live stream."
    return "An unexpected error occurred while processing the video. Please try another video or check the URL."


class ProcessURLRequest(BaseModel):
    url: str = Field(..., min_length=10, max_length=2048)
    mode: Literal["scene_change", "interval"] = "scene_change"
    sensitivity: Literal["low", "medium", "high"] = "medium"
    interval: float = Field(default=5.0, ge=0.5, le=3600.0)
    quality: Literal["1080p", "720p", "480p"] = "1080p"
    start_time: Optional[str] = Field(default=None, max_length=32)
    end_time: Optional[str] = Field(default=None, max_length=32)


def sync_process_video(
    job_id: str,
    video_path_or_url: str,
    is_url: bool,
    mode: str,
    sensitivity: str,
    interval: float,
    start_sec: float,
    end_sec: Optional[float],
    temp_dir: str,
    quality: str = "1080p",
):
    try:
        if is_url:
            jobs[job_id]["status"] = "downloading"

            def dl_cb(percent, frames, ts):
                jobs[job_id]["progress"] = percent
                jobs[job_id]["message"] = ts

            video_path = download_youtube_video(
                video_path_or_url, temp_dir, quality=quality, progress_callback=dl_cb
            )
        else:
            video_path = video_path_or_url

        jobs[job_id]["status"] = "extracting"
        jobs[job_id]["progress"] = 50.0 if is_url else 5.0
        jobs[job_id]["message"] = "Starting slide scene analysis..."
        frames_dir = safe_path_join(temp_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        def ex_cb(percent, frames, ts):
            if is_url:
                overall = 50.0 + (percent * 0.45)
            else:
                overall = percent * 0.95
            jobs[job_id]["progress"] = round(overall, 1)
            jobs[job_id]["frames_found"] = frames
            jobs[job_id]["current_timestamp"] = ts
            jobs[job_id]["message"] = f"Scanning frame at {ts} ({frames} slides found)"

        if mode == "scene_change":
            frame_paths = extract_frames_scene_change(
                video_path, frames_dir, sensitivity, 1.5, start_sec, end_sec, progress_callback=ex_cb
            )
        else:
            frame_paths = extract_frames_interval(
                video_path, frames_dir, interval, start_sec, end_sec, progress_callback=ex_cb
            )

        frame_files = [os.path.basename(p) for p in frame_paths]
        jobs[job_id]["frames"] = frame_files
        jobs[job_id]["frames_found"] = len(frame_files)

        try:
            if video_path and os.path.exists(video_path):
                os.remove(video_path)
        except OSError:
            pass

        jobs[job_id]["status"] = "packaging"
        jobs[job_id]["progress"] = 96.0
        jobs[job_id]["message"] = "Creating high-resolution ZIP archive..."
        zip_path = safe_path_join(temp_dir, f"{job_id}.zip")
        create_zip(frames_dir, zip_path)

        jobs[job_id]["zip_path"] = zip_path
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress"] = 100.0
        jobs[job_id]["message"] = f"Extraction completed! {len(frame_files)} slides ready."

    except Exception as exc:
        logger.exception("Video processing failed for job %s", job_id)
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["message"] = sanitize_error_message(exc)


async def process_video_task(
    job_id: str,
    video_path_or_url: str,
    is_url: bool,
    mode: str,
    sensitivity: str,
    interval: float,
    start_sec: float,
    end_sec: Optional[float],
    temp_dir: str,
    quality: str = "1080p",
):
    async with processing_semaphore:
        await asyncio.to_thread(
            sync_process_video,
            job_id,
            video_path_or_url,
            is_url,
            mode,
            sensitivity,
            interval,
            start_sec,
            end_sec,
            temp_dir,
            quality,
        )


def _get_validated_job(job_id: str) -> dict:
    try:
        clean_id = validate_job_id(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Job not found")
    if clean_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[clean_id]


@app.post("/api/process-url")
@limiter.limit("10/minute")
async def process_url(request: Request, body: ProcessURLRequest):
    try:
        url = validate_youtube_url(body.url)
        st = parse_and_validate_timestamp(body.start_time) or 0.0
        et = parse_and_validate_timestamp(body.end_time)
        if et is not None and et <= st:
            raise ValueError("end_time must be greater than start_time")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cleanup_expired_jobs()
    os.makedirs(TEMP_BASE_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    temp_dir = safe_path_join(TEMP_BASE_DIR, job_id)
    os.makedirs(temp_dir, exist_ok=True)

    jobs[job_id] = {
        "status": "pending",
        "progress": 0.0,
        "frames_found": 0,
        "frames": [],
        "current_timestamp": "",
        "message": "",
        "zip_path": None,
        "temp_dir": temp_dir,
        "created_at": time.time(),
    }

    asyncio.create_task(
        process_video_task(
            job_id,
            url,
            True,
            body.mode,
            body.sensitivity,
            body.interval,
            st,
            et,
            temp_dir,
            body.quality,
        )
    )

    return {"job_id": job_id}


@app.post("/api/upload")
@limiter.limit("10/minute")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("scene_change"),
    sensitivity: str = Form("medium"),
    interval: float = Form(5.0),
    start_time: Optional[str] = Form(None),
    end_time: Optional[str] = Form(None),
):
    if mode not in ("scene_change", "interval"):
        raise HTTPException(status_code=400, detail="Invalid extraction mode")
    if sensitivity.lower() not in ("low", "medium", "high"):
        raise HTTPException(status_code=400, detail="Invalid sensitivity level")
    if interval < 0.5 or interval > 3600.0:
        raise HTTPException(status_code=400, detail="Interval must be between 0.5 and 3600 seconds")

    try:
        validate_file_extension(file.filename or "")
        st = parse_and_validate_timestamp(start_time) or 0.0
        et = parse_and_validate_timestamp(end_time)
        if et is not None and et <= st:
            raise ValueError("end_time must be greater than start_time")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cleanup_expired_jobs()
    os.makedirs(TEMP_BASE_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    temp_dir = safe_path_join(TEMP_BASE_DIR, job_id)
    os.makedirs(temp_dir, exist_ok=True)

    file_name = sanitize_filename(file.filename or "upload.mp4")
    file_path = safe_path_join(temp_dir, file_name)

    size = 0
    header_checked = False
    try:
        with open(file_path, "wb") as f:
            while chunk := await file.read(8192):
                if not header_checked:
                    validate_video_magic_bytes(chunk)
                    header_checked = True
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE:
                    raise ValueError("File exceeds maximum allowed size of 500 MB")
                f.write(chunk)
        if not header_checked:
            raise ValueError("Uploaded file is empty")
    except ValueError as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(e))

    jobs[job_id] = {
        "status": "pending",
        "progress": 0.0,
        "frames_found": 0,
        "frames": [],
        "current_timestamp": "",
        "message": "",
        "zip_path": None,
        "temp_dir": temp_dir,
        "created_at": time.time(),
    }

    asyncio.create_task(
        process_video_task(
            job_id,
            file_path,
            False,
            mode,
            sensitivity.lower(),
            interval,
            st,
            et,
            temp_dir,
        )
    )

    return {"job_id": job_id}


@app.get("/api/progress/{job_id}")
async def get_progress(job_id: str):
    _get_validated_job(job_id)

    async def event_stream():
        while True:
            if job_id not in jobs:
                break

            job = jobs[job_id]
            light_job = {
                k: v
                for k, v in job.items()
                if k not in ("frame_items", "temp_dir", "zip_path", "created_at")
            }
            data = json.dumps(light_job)
            yield f"data: {data}\n\n"

            if job["status"] in ("completed", "failed"):
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/download/{job_id}")
async def download_zip(job_id: str):
    job = _get_validated_job(job_id)
    if job["status"] != "completed" or not job["zip_path"]:
        raise HTTPException(status_code=400, detail="Job not completed yet")

    zip_path = job["zip_path"]
    if not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="ZIP file not found")

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"frames_{job_id}.zip",
    )


@app.get("/api/frames/{job_id}")
async def get_job_frames(job_id: str):
    job = _get_validated_job(job_id)
    return {
        "job_id": job_id,
        "status": job["status"],
        "message": job.get("message", ""),
        "frames": job.get("frames", []),
        "count": len(job.get("frames", [])),
    }


@app.get("/api/frame/{job_id}/{frame_name}")
async def get_single_frame(job_id: str, frame_name: str):
    job = _get_validated_job(job_id)
    temp_dir = job.get("temp_dir")
    if not temp_dir or not os.path.exists(temp_dir):
        raise HTTPException(status_code=404, detail="Job workspace not found")

    safe_name = sanitize_filename(frame_name)
    frame_path = safe_path_join(temp_dir, "frames", safe_name)
    if not os.path.exists(frame_path):
        raise HTTPException(status_code=404, detail="Frame not found")

    return FileResponse(frame_path, media_type="image/png")


@app.post("/api/cleanup/{job_id}")
async def cleanup_job(job_id: str):
    job = _get_validated_job(job_id)
    if job.get("temp_dir") and os.path.exists(job["temp_dir"]):
        shutil.rmtree(job["temp_dir"], ignore_errors=True)
    jobs.pop(job_id, None)
    return {"status": "success"}


@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}


# Serve frontend static files in standalone/Docker production
if not IS_VERCEL:
    frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
    if os.path.isdir(frontend_dist):
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")


