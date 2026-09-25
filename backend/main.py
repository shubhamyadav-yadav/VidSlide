import asyncio
import json
import os
import shutil
import tempfile
import uuid
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from security import (
    validate_youtube_url, validate_file_extension,
    sanitize_filename, safe_path_join, MAX_UPLOAD_SIZE, ALLOWED_EXTENSIONS
)
from extractor import (
    download_youtube_video, extract_frames_scene_change,
    extract_frames_interval, extract_frames_from_youtube_storyboard, create_zip
)
import base64
import cv2

TEMP_BASE_DIR = tempfile.mkdtemp()
IS_VERCEL = os.environ.get("VERCEL") == "1"

@asynccontextmanager
async def lifespan(app: FastAPI):
    global TEMP_BASE_DIR
    if not TEMP_BASE_DIR or not os.path.exists(TEMP_BASE_DIR):
        TEMP_BASE_DIR = tempfile.mkdtemp()
    yield
    if TEMP_BASE_DIR and os.path.exists(TEMP_BASE_DIR) and not IS_VERCEL:
        shutil.rmtree(TEMP_BASE_DIR, ignore_errors=True)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

cors_origins_env = os.environ.get("CORS_ORIGINS", "")
allowed_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
if cors_origins_env:
    allowed_origins.extend([origin.strip() for origin in cors_origins_env.split(",") if origin.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_private_network_access_headers(request: Request, call_next):
    if request.method == "OPTIONS":
        from fastapi.responses import Response
        resp = Response(status_code=204)
        resp.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        return resp
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response

jobs = {}
processing_semaphore = asyncio.Semaphore(3)

class ProcessURLRequest(BaseModel):
    url: str
    mode: str = "scene_change"
    sensitivity: str = "medium"
    interval: float = 5.0
    quality: str = "1080p"
    start_time: Optional[str] = None
    end_time: Optional[str] = None

def parse_timestamp(ts: str) -> float:
    if not ts:
        return 0.0
    parts = ts.split(':')
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return float(parts[0])

def sync_process_video(job_id, video_path_or_url, is_url, mode, sensitivity, interval, start_time, end_time, temp_dir, quality="1080p"):
    try:
        if is_url:
            jobs[job_id]["status"] = "downloading"

            def dl_cb(percent, frames, ts):
                jobs[job_id]["progress"] = percent
                jobs[job_id]["message"] = ts

            video_path = download_youtube_video(video_path_or_url, temp_dir, quality=quality, progress_callback=dl_cb)
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

        st = parse_timestamp(start_time) if start_time else 0.0
        et = parse_timestamp(end_time) if end_time else None

        if mode == "scene_change":
            frame_paths = extract_frames_scene_change(video_path, frames_dir, sensitivity, 1.5, st, et, progress_callback=ex_cb)
        else:
            frame_paths = extract_frames_interval(video_path, frames_dir, interval, st, et, progress_callback=ex_cb)

        frame_files = [os.path.basename(p) for p in frame_paths]
        jobs[job_id]["frames"] = frame_files
        jobs[job_id]["frames_found"] = len(frame_files)

        # Reclaim disk space by deleting raw video after extraction
        try:
            if video_path and os.path.exists(video_path):
                os.remove(video_path)
        except Exception:
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

    except Exception as e:
        import traceback
        traceback.print_exc()
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["message"] = str(e)

async def process_video_task(job_id, video_path_or_url, is_url, mode, sensitivity, interval, start_time, end_time, temp_dir, quality="1080p"):
    async with processing_semaphore:
        await asyncio.to_thread(
            sync_process_video, 
            job_id, video_path_or_url, is_url, mode, sensitivity, 
            interval, start_time, end_time, temp_dir, quality
        )

@app.post("/api/process-url")
@limiter.limit("10/minute")
async def process_url(request: Request, body: ProcessURLRequest):
    try:
        url = validate_youtube_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
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
    }
    
    asyncio.create_task(
        process_video_task(
            job_id, url, True, body.mode, body.sensitivity, 
            body.interval, body.start_time, body.end_time, temp_dir, body.quality
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
    end_time: Optional[str] = Form(None)
):
    try:
        validate_file_extension(file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    os.makedirs(TEMP_BASE_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    temp_dir = safe_path_join(TEMP_BASE_DIR, job_id)
    os.makedirs(temp_dir, exist_ok=True)
    
    file_name = sanitize_filename(file.filename)
    file_path = safe_path_join(temp_dir, file_name)
    
    size = 0
    with open(file_path, "wb") as f:
        while chunk := await file.read(8192):
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                os.remove(file_path)
                raise HTTPException(status_code=400, detail="File too large")
            f.write(chunk)
            
    jobs[job_id] = {
        "status": "pending",
        "progress": 0.0,
        "frames_found": 0,
        "frames": [],
        "current_timestamp": "",
        "message": "",
        "zip_path": None,
        "temp_dir": temp_dir,
    }
    
    asyncio.create_task(
        process_video_task(
            job_id, file_path, False, mode, sensitivity, 
            interval, start_time, end_time, temp_dir
        )
    )
    
    return {"job_id": job_id}

@app.get("/api/progress/{job_id}")
async def get_progress(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
        
    async def event_stream():
        while True:
            if job_id not in jobs:
                break
                
            job = jobs[job_id]
            light_job = {k: v for k, v in job.items() if k not in ("frame_items", "temp_dir")}
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
        }
    )

@app.get("/api/download/{job_id}")
async def download_zip(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
        
    job = jobs[job_id]
    if job["status"] != "completed" or not job["zip_path"]:
        raise HTTPException(status_code=400, detail="Job not completed yet")
        
    zip_path = job["zip_path"]
    if not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="ZIP file not found")
        
    return FileResponse(
        zip_path, 
        media_type="application/zip", 
        filename=f"frames_{job_id}.zip"
    )

@app.get("/api/frames/{job_id}")
async def get_job_frames(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    return {
        "job_id": job_id,
        "status": job["status"],
        "message": job.get("message", ""),
        "frames": job.get("frames", []),
        "frame_items": job.get("frame_items", []),
        "count": len(job.get("frames", []))
    }

@app.get("/api/frame/{job_id}/{frame_name}")
async def get_single_frame(job_id: str, frame_name: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
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
    if job_id in jobs:
        job = jobs[job_id]
        if job["temp_dir"] and os.path.exists(job["temp_dir"]):
            shutil.rmtree(job["temp_dir"])
        del jobs[job_id]
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Job not found")


@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/api/debug/jobs")
async def debug_jobs():
    return {jid: {k: v for k, v in j.items() if k not in ("temp_dir", "frame_items")} for jid, j in jobs.items()}


# Serve frontend static files in standalone/Docker production (skipped on Vercel Edge)
if not IS_VERCEL:
    frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
    if os.path.isdir(frontend_dist):
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

