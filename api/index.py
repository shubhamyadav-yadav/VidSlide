import base64
import io
import json
import os
import re
import ssl
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageChops, ImageFilter, ImageStat
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProcessURLRequest(BaseModel):
    url: str
    mode: str = "scene_change"
    sensitivity: str = "medium"
    interval: float = 5.0
    quality: str = "1080p"
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    sync: bool = True


def _parse_ts(ts: Optional[str]) -> float:
    if not ts:
        return 0.0
    parts = ts.strip().split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except Exception:
        return 0.0


def _extract_video_id(url: str) -> Optional[str]:
    m = re.search(r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/|\/live\/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def _candidate_ids(vid: str) -> list[str]:
    cands = [vid]
    if "l" in vid:
        cands.append(vid.replace("l", "I"))
    if "I" in vid:
        cands.append(vid.replace("I", "l"))
    return list(dict.fromkeys(cands))


def _fetch_bytes(url: str, timeout: int = 10) -> Optional[bytes]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read()
    except Exception:
        return None


def _dhash(gray_img: Image.Image) -> int:
    """Compute 64-bit difference perceptual hash using Pillow."""
    small = gray_img.resize((9, 8), Image.Resampling.BILINEAR)
    pixels = list(small.getdata())
    bits = 0
    for r in range(8):
        row_offset = r * 9
        for c in range(8):
            bits = (bits << 1) | (1 if pixels[row_offset + c] > pixels[row_offset + c + 1] else 0)
    return bits


def _hamming_dist(h1: int, h2: int) -> float:
    return bin(h1 ^ h2).count("1") / 64.0


def _compare_pil(g1: Image.Image, g2: Image.Image) -> dict:
    diff = ImageChops.difference(g1, g2)
    mean_diff = float(ImageStat.Stat(diff).mean[0])
    w, h = diff.size
    bw, bh = max(1, w // 4), max(1, h // 4)
    max_reg = 0.0
    for r in range(4):
        for c in range(4):
            box = (c * bw, r * bh, min(w, (c + 1) * bw), min(h, (r + 1) * bh))
            reg_mean = float(ImageStat.Stat(diff.crop(box)).mean[0])
            if reg_mean > max_reg:
                max_reg = reg_mean
    h_dist = _hamming_dist(_dhash(g1), _dhash(g2))
    return {"mean_diff": mean_diff, "max_region_diff": max_reg, "hash_dist": h_dist}


def _is_slide_change(metrics: dict, sensitivity: str) -> bool:
    configs = {
        "low": {"mean": 28, "region": 48, "hash": 0.22},
        "medium": {"mean": 14, "region": 28, "hash": 0.14},
        "high": {"mean": 7, "region": 16, "hash": 0.07},
    }
    cfg = configs.get(sensitivity.lower(), configs["medium"])
    return metrics["mean_diff"] > cfg["mean"] or (
        metrics["max_region_diff"] > cfg["region"] and metrics["hash_dist"] > cfg["hash"]
    )


def _fetch_storyboards(vid: str) -> Tuple[float, list[dict]]:
    profiles = [
        None,
        {"youtube": {"player_client": ["tv_embedded", "ios", "android", "mweb"]}},
    ]
    for cand in _candidate_ids(vid):
        target_url = f"https://www.youtube.com/watch?v={cand}"
        for ext_args in profiles:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "nocheckcertificate": True,
                "socket_timeout": 12,
                "noplaylist": True,
            }
            if ext_args:
                opts["extractor_args"] = ext_args
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)
                    if not info:
                        continue
                    duration = float(info.get("duration") or 0)
                    formats = info.get("formats") or []
                    sbs = [
                        f
                        for f in formats
                        if f.get("fragments") and ("sb" in str(f.get("format_id", "")) or f.get("ext") == "mhtml")
                    ]
                    if sbs:
                        sbs.sort(key=lambda f: (f.get("width") or 0) * (f.get("height") or 0), reverse=True)
                        best = sbs[0]
                        cols = int(best.get("columns") or 3)
                        rows = int(best.get("rows") or 3)
                        frags = best.get("fragments") or []
                        sheets = [
                            {
                                "url": fg["url"],
                                "cols": cols,
                                "rows": rows,
                                "duration": float(fg.get("duration") or (duration / max(1, len(frags)))),
                            }
                            for fg in frags
                            if fg.get("url")
                        ]
                        if sheets:
                            return duration, sheets
            except Exception as e:
                if "unavailable" in str(e).lower():
                    break
                continue

        piped_hosts = [
            "https://pipedapi.kavin.rocks",
            "https://api.piped.private.coffee",
            "https://pipedapi.tokhmi.xyz",
        ]
        for host in piped_hosts:
            raw = _fetch_bytes(f"{host}/streams/{cand}", timeout=7)
            if not raw:
                continue
            try:
                data = json.loads(raw.decode("utf-8"))
                duration = float(data.get("duration") or 0)
                previews = data.get("previewFrames") or []
                if previews:
                    previews.sort(key=lambda p: (p.get("frameWidth") or 0) * (p.get("frameHeight") or 0), reverse=True)
                    bp = previews[0]
                    cols = int(bp.get("framesPerPageX") or 3)
                    rows = int(bp.get("framesPerPageY") or 3)
                    dpf = float(bp.get("durationPerFrame") or 2000) / 1000.0
                    urls = bp.get("urls") or []
                    sheets = [{"url": u, "cols": cols, "rows": rows, "duration": cols * rows * dpf} for u in urls]
                    if sheets:
                        return duration, sheets
            except Exception:
                continue

    return 0.0, []


@app.get("/api/health")
async def health():
    return {"status": "healthy", "runtime": "vercel-python-pillow"}


@app.post("/api/process-url")
async def process_url(body: ProcessURLRequest):
    vid = _extract_video_id(body.url)
    if not vid:
        raise HTTPException(status_code=400, detail="Invalid YouTube video URL")

    st = _parse_ts(body.start_time)
    et = _parse_ts(body.end_time) if body.end_time else None

    duration, sheets = _fetch_storyboards(vid)
    raw_frames: list[Tuple[float, Image.Image]] = []

    if sheets:
        with ThreadPoolExecutor(max_workers=10) as pool:
            sheet_bytes = list(pool.map(lambda s: _fetch_bytes(s["url"], timeout=9), sheets))

        elapsed = 0.0
        for spec, b_data in zip(sheets, sheet_bytes):
            cols = max(1, spec["cols"])
            rows = max(1, spec["rows"])
            s_dur = spec["duration"]
            c_dur = s_dur / (cols * rows)
            if not b_data:
                elapsed += s_dur
                continue
            try:
                sheet_img = Image.open(io.BytesIO(b_data)).convert("RGB")
            except Exception:
                elapsed += s_dur
                continue
            sw, sh = sheet_img.size
            cw, ch = sw // cols, sh // rows
            for r in range(rows):
                for c in range(cols):
                    ts = elapsed + (r * cols + c) * c_dur
                    if duration > 0 and ts > duration:
                        break
                    cell = sheet_img.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch))
                    if ImageStat.Stat(cell).mean[0] < 4.0:
                        continue
                    raw_frames.append((ts, cell))
            elapsed += s_dur

    if not raw_frames:
        for cand in _candidate_ids(vid):
            names = [
                "maxresdefault.jpg",
                "maxres1.jpg",
                "maxres2.jpg",
                "maxres3.jpg",
                "sddefault.jpg",
                "sd1.jpg",
                "sd2.jpg",
                "sd3.jpg",
                "hqdefault.jpg",
                "hq1.jpg",
                "hq2.jpg",
                "hq3.jpg",
            ]
            urls = [f"https://i.ytimg.com/vi/{cand}/{n}" for n in names]
            with ThreadPoolExecutor(max_workers=6) as pool:
                b_list = list(pool.map(lambda u: _fetch_bytes(u, timeout=7), urls))
            step = max(12.0, (duration / 6.0) if duration > 0 else 15.0)
            cur_t = 0.0
            for raw_b in b_list:
                if not raw_b or len(raw_b) < 2500:
                    continue
                try:
                    im = Image.open(io.BytesIO(raw_b)).convert("RGB")
                    if im.size[1] >= 180:
                        raw_frames.append((cur_t, im))
                        cur_t += step
                except Exception:
                    continue
            if raw_frames:
                break

    if not raw_frames:
        raise HTTPException(status_code=400, detail="Could not retrieve video frames from YouTube.")

    filtered = [(t, im) for (t, im) in raw_frames if t >= st and (et is None or t <= et)]
    if not filtered:
        filtered = raw_frames

    frame_items = []
    frame_names = []
    saved_hashes: list[int] = []
    ref_gray: Optional[Image.Image] = None
    last_ts = -999.0

    for ts, img in filtered:
        small_gray = img.resize((160, 90), Image.Resampling.BILINEAR).convert("L")
        curr_h = _dhash(small_gray)

        keep = False
        if ref_gray is None:
            keep = True
        elif body.mode == "interval":
            if (ts - last_ts) >= max(1.0, body.interval):
                if not any(_hamming_dist(curr_h, h) < 0.06 for h in saved_hashes[-3:]):
                    keep = True
        else:
            metrics = _compare_pil(ref_gray, small_gray)
            if _is_slide_change(metrics, body.sensitivity):
                if not any(_hamming_dist(curr_h, h) < 0.08 for h in saved_hashes):
                    keep = True

        if keep and len(frame_items) < 40:
            enhanced = img.resize((960, 540), Image.Resampling.LANCZOS).filter(
                ImageFilter.UnsharpMask(radius=1.3, percent=130, threshold=2)
            )
            buf = io.BytesIO()
            enhanced.save(buf, format="JPEG", quality=82)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")

            hrs = int(ts // 3600)
            mins = int((ts % 3600) // 60)
            secs = int(ts % 60)
            fname = f"frame_{hrs:02d}h{mins:02d}m{secs:02d}s.jpg"
            t_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

            frame_names.append(fname)
            frame_items.append({"name": fname, "time": t_str, "url": f"data:image/jpeg;base64,{b64}"})
            saved_hashes.append(curr_h)
            ref_gray = small_gray
            last_ts = ts

    job_id = str(uuid.uuid4())
    return {
        "job_id": job_id,
        "status": "completed",
        "count": len(frame_items),
        "frames": frame_names,
        "frame_items": frame_items,
    }
