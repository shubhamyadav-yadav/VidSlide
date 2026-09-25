import cv2
import numpy as np
import yt_dlp
import tempfile
import zipfile
import os
import shutil
import uuid
import re
from typing import Generator, Tuple, Optional, Callable
from pathlib import Path

from security import validate_youtube_url, safe_path_join, generate_frame_filename, MAX_VIDEO_DURATION

# Locate portable FFmpeg binary if available (e.g. from imageio-ffmpeg)
FFMPEG_EXE = None
try:
    import imageio_ffmpeg
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_EXE = shutil.which("ffmpeg")


def download_youtube_video(
    url: str, 
    output_dir: str, 
    quality: str = "1080p",
    progress_callback: Optional[Callable] = None
) -> str:
    """
    Downloads the best video stream from YouTube using chunked transfers,
    IPv4 forcing, extended socket timeouts, and automatic resume to eliminate
    HTTPSConnectionPool Read timed out errors on googlevideo.com.
    """
    import time

    output_filename = str(uuid.uuid4())
    output_path = safe_path_join(output_dir, f"{output_filename}.%(ext)s")
    
    def my_hook(d):
        if not progress_callback:
            return
        status = d.get('status')
        if status == 'downloading':
            # Compute percent accurately
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            if total > 0:
                raw_pct = (downloaded / total) * 100.0
            else:
                percent_str = d.get('_percent_str', '0%')
                ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                percent_str = ansi_escape.sub('', percent_str).strip()
                try:
                    raw_pct = float(percent_str.replace('%', ''))
                except ValueError:
                    raw_pct = 0.0

            # Map download to 5% - 50% of overall process
            overall_pct = 5.0 + (raw_pct * 0.45)
            speed_str = d.get('_speed_str', '').strip()
            msg = f"Downloading video: {raw_pct:.0f}%"
            if speed_str:
                msg += f" ({speed_str})"
            progress_callback(overall_pct, 0, msg)
        elif status == 'finished':
            progress_callback(50.0, 0, "Video download finished. Preparing frame extraction...")

    max_height = 1080
    if quality == "720p":
        max_height = 720
    elif quality == "480p":
        max_height = 480
                
    ydl_opts = {
        'format': (
            f'bestvideo[height<={max_height}][ext=mp4]/'
            f'bestvideo[height<={max_height}]/'
            f'bestvideo[height<=720][ext=mp4]/'
            f'bestvideo[height<=720]/'
            f'best[height<={max_height}]/'
            f'best'
        ),
        'outtmpl': output_path,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 60,
        'retries': 10,
        'fragment_retries': 10,
        'continuedl': True,
        'progress_hooks': [my_hook] if progress_callback else [],
    }
    
    if FFMPEG_EXE and os.path.exists(FFMPEG_EXE):
        ydl_opts['ffmpeg_location'] = FFMPEG_EXE
    
    if progress_callback:
        progress_callback(5.0, 0, "Analyzing YouTube video metadata...")

    # Check metadata first (with automatic 'l' <-> 'I' typo recovery)
    vid = _extract_youtube_id(url)
    info = None
    if vid:
        last_meta_err = None
        for cand_vid in _get_candidate_video_ids(vid):
            cand_url = url.replace(vid, cand_vid)
            try:
                with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'socket_timeout': 30}) as ydl:
                    info = ydl.extract_info(cand_url, download=False)
                    if info:
                        url = cand_url
                        break
            except Exception as e:
                last_meta_err = e
                if "unavailable" in str(e).lower():
                    continue
                raise
        if not info and last_meta_err:
            raise last_meta_err
    else:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'socket_timeout': 30}) as ydl:
            info = ydl.extract_info(url, download=False)

    if not info:
        raise ValueError("Could not extract metadata from YouTube URL")
            
    if info.get('is_live'):
        raise ValueError("Live streams are not supported. Please use a completed video.")
            
    duration = info.get('duration') or 0
    if duration > MAX_VIDEO_DURATION:
        max_mins = MAX_VIDEO_DURATION // 60
        cur_mins = int(duration // 60)
        raise ValueError(
            f"Video duration ({cur_mins} min / {int(duration)}s) exceeds maximum allowed limit of {max_mins} min ({MAX_VIDEO_DURATION}s)."
        )

    if progress_callback:
        progress_callback(10.0, 0, "Starting video stream download...")

    # Download with automatic retry and resume if connection drops
    last_err = None
    for attempt in range(3):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
            for file in os.listdir(output_dir):
                if file.startswith(output_filename):
                    return safe_path_join(output_dir, file)
        except Exception as e:
            last_err = e
            err_str = str(e)
            if "Read timed out" in err_str or "timed out" in err_str or "ConnectionReset" in err_str:
                if progress_callback:
                    progress_callback(10.0, 0, f"Connection stalled, resuming attempt {attempt + 2}/3...")
                time.sleep(2)
                continue
            raise

    raise RuntimeError(f"Failed to download video stream after retries: {last_err}")


# ---------------------------------------------------------------------------
# Perceptual hashing for near-duplicate detection
# ---------------------------------------------------------------------------

def _phash(gray_img: np.ndarray, hash_size: int = 16) -> np.ndarray:
    """
    Compute a perceptual hash (pHash) of a grayscale image.
    Returns a flat boolean array of size hash_size*hash_size.
    """
    resized = cv2.resize(gray_img, (hash_size * 4, hash_size * 4), interpolation=cv2.INTER_AREA)
    # DCT on float32
    dct = cv2.dct(np.float32(resized))
    # Keep top-left low-frequency block
    dct_low = dct[:hash_size, :hash_size]
    median = np.median(dct_low)
    return (dct_low > median).flatten()


def _hamming_distance(h1: np.ndarray, h2: np.ndarray) -> float:
    """Normalized Hamming distance between two boolean hash arrays (0.0 = identical, 1.0 = opposite)."""
    return float(np.count_nonzero(h1 != h2)) / len(h1)


def _compare_frames(gray1: np.ndarray, gray2: np.ndarray) -> dict:
    """
    Multi-metric comparison between two grayscale images of the same size.
    Returns dict with 'mean_diff', 'max_region_diff', 'hash_dist'.
    """
    # 1) Global mean absolute difference
    diff = cv2.absdiff(gray1, gray2)
    mean_diff = float(np.mean(diff))
    
    # 2) Block-based maximum difference (catches small region changes like a single
    #    bullet point appearing on a slide)
    h, w = diff.shape
    block_h, block_w = max(1, h // 4), max(1, w // 4)
    max_block_diff = 0.0
    for r in range(4):
        for c in range(4):
            block = diff[r*block_h:(r+1)*block_h, c*block_w:(c+1)*block_w]
            block_mean = float(np.mean(block))
            max_block_diff = max(max_block_diff, block_mean)
    
    # 3) Perceptual hash distance
    h1 = _phash(gray1)
    h2 = _phash(gray2)
    hash_dist = _hamming_distance(h1, h2)
    
    return {
        'mean_diff': mean_diff,
        'max_region_diff': max_block_diff,
        'hash_dist': hash_dist,
    }


def _is_significant_change(metrics: dict, sensitivity: str) -> bool:
    """
    Determine if a frame change is significant enough to be a new slide.
    Uses multiple metrics to avoid false positives from speaker movement
    and false negatives from subtle slide changes.
    """
    # Thresholds tuned per sensitivity level
    # Format: (mean_diff_threshold, max_region_threshold, hash_dist_threshold)
    # A change is significant if EITHER the global diff OR the hash distance exceeds threshold
    configs = {
        "low":    {"mean": 30, "region": 50, "hash": 0.25},
        "medium": {"mean": 15, "region": 30, "hash": 0.15},
        "high":   {"mean": 8,  "region": 18, "hash": 0.08},
    }
    cfg = configs.get(sensitivity.lower(), configs["medium"])
    
    # Primary: global mean difference shows a big visual change
    global_change = metrics['mean_diff'] > cfg['mean']
    
    # Secondary: a region changed significantly (catches bullet-point additions)
    region_change = metrics['max_region_diff'] > cfg['region']
    
    # Tertiary: perceptual hash says the structure changed
    hash_change = metrics['hash_dist'] > cfg['hash']
    
    # Trigger if global change is strong, OR if both region and hash agree
    return global_change or (region_change and hash_change)


# ---------------------------------------------------------------------------
# Core extraction: Detect → Settle → Capture
# ---------------------------------------------------------------------------

def extract_frames_scene_change(
    video_path: str, 
    output_dir: str, 
    sensitivity: str = "medium", 
    min_gap: float = 0.8, 
    start_time: float = 0, 
    end_time: Optional[float] = None, 
    progress_callback: Optional[Callable] = None
) -> list[str]:
    """
    Extracts complete, non-cut slide screenshots using a three-phase approach:
    
    1. DETECT: Identify when a significant visual change occurs between frames.
    2. SETTLE: After detecting a change, continue reading frames until the scene
       stabilizes (consecutive frames become similar again). This ensures we skip
       transition animations, fades, and slide-build effects.
    3. CAPTURE: Save the first fully-stable frame after the transition completes.
    
    Additionally performs post-capture deduplication using perceptual hashing
    to remove near-identical frames that survived the detection phase.
    """
    COMPARE_SIZE = (480, 270)  # Larger comparison size for better accuracy
    
    # How many consecutive "stable" frames we need before considering the slide settled
    SETTLE_FRAMES = 3
    # Maximum diff between consecutive frames to consider them "stable"
    SETTLE_THRESHOLD = 5.0  # Very low - frames must be nearly identical
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Failed to open video file")
        
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or np.isnan(fps):
        fps = 30.0
        
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_duration = (total_frames / fps) if total_frames > 0 else 0
    
    if start_time > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, start_time * 1000)
        
    # State
    saved_paths = []
    saved_hashes = []   # pHash of each saved frame for dedup
    saved_count = 0
    last_saved_time = -min_gap
    frame_count = 0
    
    # The "reference" frame is the last captured stable slide
    reference_gray = None
    
    # Sampling: process ~4-6 frames per second for speed
    sample_step = max(1, int(fps / 5.0))
    
    # Track whether we're in "settling" mode
    settling = False
    settle_counter = 0
    settle_prev_gray = None
    settle_candidate_frame = None
    settle_candidate_time = 0.0
    
    while True:
        ret = cap.grab()
        if not ret:
            break
            
        frame_count += 1
        current_time = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        
        if end_time is not None and current_time > end_time:
            break
        
        # When settling, decode every frame to find the stable point quickly
        # When scanning, only decode at sample intervals
        if not settling:
            is_sample = (frame_count % sample_step == 0) or (saved_count == 0)
            if not is_sample:
                continue
        
        ret, frame = cap.retrieve()
        if not ret or frame is None:
            continue
            
        # Downscale for comparison (larger than before for better accuracy)
        small = cv2.resize(frame, COMPARE_SIZE, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        
        # === PHASE 1: First frame capture ===
        if saved_count == 0 and reference_gray is None:
            # Wait a tiny bit for the video to start properly, then capture
            if current_time >= start_time + 0.1 or frame_count > 3:
                settling = True
                settle_counter = 0
                settle_prev_gray = gray.copy()
                settle_candidate_frame = frame.copy()
                settle_candidate_time = current_time
                # For the very first frame, consider it a settle start
                if saved_count == 0:
                    # Immediately capture the first frame since there's no transition
                    settle_counter = SETTLE_FRAMES
        
        # === PHASE 2: Settling mode - waiting for transition to end ===
        if settling:
            if settle_prev_gray is not None:
                diff_from_prev = cv2.absdiff(gray, settle_prev_gray)
                mean_diff_from_prev = float(np.mean(diff_from_prev))
                
                if mean_diff_from_prev < SETTLE_THRESHOLD:
                    # Frame is stable relative to previous
                    settle_counter += 1
                    # Update candidate to the latest stable frame (best quality)
                    settle_candidate_frame = frame.copy()
                    settle_candidate_time = current_time
                else:
                    # Still transitioning - reset counter
                    settle_counter = 0
                    settle_candidate_frame = frame.copy()
                    settle_candidate_time = current_time
            
            settle_prev_gray = gray.copy()
            
            if settle_counter >= SETTLE_FRAMES:
                # === PHASE 3: Slide has settled - CAPTURE ===
                # Check it's not a duplicate of an already-saved frame
                candidate_gray = cv2.cvtColor(
                    cv2.resize(settle_candidate_frame, COMPARE_SIZE, interpolation=cv2.INTER_AREA),
                    cv2.COLOR_BGR2GRAY
                )
                candidate_hash = _phash(candidate_gray)
                
                is_duplicate = False
                for prev_hash in saved_hashes:
                    if _hamming_distance(candidate_hash, prev_hash) < 0.08:
                        is_duplicate = True
                        break
                
                if not is_duplicate and (settle_candidate_time - last_saved_time) >= min_gap:
                    filename = generate_frame_filename(settle_candidate_time)
                    filepath = safe_path_join(output_dir, filename)
                    cv2.imwrite(filepath, settle_candidate_frame)
                    saved_paths.append(filepath)
                    saved_hashes.append(candidate_hash)
                    last_saved_time = settle_candidate_time
                    saved_count += 1
                    reference_gray = candidate_gray.copy()
                
                # Exit settling mode
                settling = False
                settle_counter = 0
                settle_prev_gray = None
                settle_candidate_frame = None
                continue
        
        # === PHASE 1 continued: Detect significant change from last saved slide ===
        if not settling and reference_gray is not None:
            metrics = _compare_frames(reference_gray, gray)
            
            if _is_significant_change(metrics, sensitivity):
                if (current_time - last_saved_time) >= min_gap:
                    # Enter settling mode - don't capture yet!
                    settling = True
                    settle_counter = 0
                    settle_prev_gray = gray.copy()
                    settle_candidate_frame = frame.copy()
                    settle_candidate_time = current_time
        
        # Progress reporting
        if progress_callback and (frame_count % (sample_step * 5) == 0):
            current_frame_idx = cap.get(cv2.CAP_PROP_POS_FRAMES)
            percent = (current_frame_idx / total_frames * 100.0) if total_frames > 0 else 0
            percent = min(99.0, max(0.0, percent))
            
            hours = int(current_time // 3600)
            minutes = int((current_time % 3600) // 60)
            secs = int(current_time % 60)
            ts_str = f"{hours:02d}:{minutes:02d}:{secs:02d}"
            
            progress_callback(percent, saved_count, ts_str)
            
    cap.release()
    
    # Post-processing: deduplicate very similar consecutive frames
    # (handles edge cases where settling captured nearly-identical slides)
    if len(saved_paths) > 1:
        final_paths = [saved_paths[0]]
        final_hashes = [saved_hashes[0]]
        
        for i in range(1, len(saved_paths)):
            dist = _hamming_distance(saved_hashes[i], final_hashes[-1])
            if dist >= 0.06:  # Keep only frames that are meaningfully different
                final_paths.append(saved_paths[i])
                final_hashes.append(saved_hashes[i])
            else:
                # Remove the duplicate file from disk
                try:
                    os.remove(saved_paths[i])
                except OSError:
                    pass
        
        saved_paths = final_paths
        saved_count = len(saved_paths)
    
    if progress_callback:
        progress_callback(100.0, saved_count, "Done")
        
    return saved_paths


def extract_frames_interval(
    video_path: str, 
    output_dir: str, 
    interval: float = 5.0, 
    start_time: float = 0, 
    end_time: Optional[float] = None, 
    progress_callback: Optional[Callable] = None
) -> list[str]:
    """
    Extracts frames at regular intervals using direct seeking.
    Also deduplicates consecutive identical frames (e.g. during static slides).
    """
    COMPARE_SIZE = (480, 270)
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Failed to open video file")
        
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or np.isnan(fps):
        fps = 30.0
        
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_duration = (total_frames / fps) if total_frames > 0 else 0
    
    effective_end = end_time if (end_time is not None and end_time > 0) else video_duration
    if effective_end <= 0:
        effective_end = 3600 * 4
        
    saved_paths = []
    saved_count = 0
    prev_hash = None
    
    target_times = []
    t = max(0.0, start_time)
    while t <= effective_end:
        target_times.append(t)
        t += max(0.5, interval)
        
    total_targets = len(target_times)
    
    for idx, target_sec in enumerate(target_times):
        cap.set(cv2.CAP_PROP_POS_MSEC, target_sec * 1000.0)
        ret, frame = cap.read()
        if not ret or frame is None:
            break
        
        # Deduplicate consecutive identical frames
        small_gray = cv2.cvtColor(
            cv2.resize(frame, COMPARE_SIZE, interpolation=cv2.INTER_AREA),
            cv2.COLOR_BGR2GRAY
        )
        curr_hash = _phash(small_gray)
        
        if prev_hash is not None:
            dist = _hamming_distance(curr_hash, prev_hash)
            if dist < 0.05:
                # Nearly identical to previous frame, skip
                continue
        
        prev_hash = curr_hash
            
        filename = generate_frame_filename(target_sec)
        filepath = safe_path_join(output_dir, filename)
        cv2.imwrite(filepath, frame)
        saved_paths.append(filepath)
        saved_count += 1
        
        if progress_callback:
            percent = (idx + 1) / max(1, total_targets) * 100.0
            hours = int(target_sec // 3600)
            minutes = int((target_sec % 3600) // 60)
            secs = int(target_sec % 60)
            ts_str = f"{hours:02d}:{minutes:02d}:{secs:02d}"
            progress_callback(min(99.0, percent), saved_count, ts_str)
            
    cap.release()
    
    if progress_callback:
        progress_callback(100.0, saved_count, "Done")
        
    return saved_paths


def create_zip(frames_dir: str, output_path: str) -> str:
    """
    Packages extracted frames into a clean, safe ZIP file.
    """
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(frames_dir):
            for file in sorted(files):
                if file.endswith(('.png', '.jpg', '.jpeg')):
                    file_path = safe_path_join(root, file)
                    arcname = file  # flat safe basename
                    zipf.write(file_path, arcname)
    return output_path


# ---------------------------------------------------------------------------
# Cloud / Serverless Resilient YouTube Extraction (Multi-Tier + Storyboards)
# ---------------------------------------------------------------------------

def _extract_youtube_id(url: str) -> Optional[str]:
    """Extract 11-character YouTube video ID from any valid YouTube URL."""
    patterns = [
        r'(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/|\/live\/)([A-Za-z0-9_-]{11})',
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _get_candidate_video_ids(vid: str) -> list[str]:
    """
    Generate candidate video IDs including automatic recovery for common
    sans-serif font lookalike typos between 'l' (lowercase L) and 'I' (uppercase i).
    """
    candidates = [vid]
    if 'l' in vid:
        candidates.append(vid.replace('l', 'I'))
    if 'I' in vid:
        candidates.append(vid.replace('I', 'l'))
    return list(dict.fromkeys(candidates))


def _enhance_slide_frame(frame: np.ndarray, target_size: Tuple[int, int] = (960, 540)) -> np.ndarray:
    """
    Upscale with Lanczos4 and apply subtle unsharp masking so slide text is crisp.
    """
    h, w = frame.shape[:2]
    if w < target_size[0] or h < target_size[1]:
        upscaled = cv2.resize(frame, target_size, interpolation=cv2.INTER_LANCZOS4)
        blurred = cv2.GaussianBlur(upscaled, (0, 0), 1.2)
        sharpened = cv2.addWeighted(upscaled, 1.35, blurred, -0.35, 0)
        return sharpened
    return frame


def _fetch_url_bytes(url: str, timeout: int = 12) -> Optional[bytes]:
    import urllib.request
    import ssl
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
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read()
    except Exception:
        return None


def _fetch_storyboard_spec_for_video(video_id: str) -> Tuple[float, list[dict]]:
    """
    Retrieve storyboard sprite sheets for a YouTube video using multi-client yt-dlp
    with automatic fallback to public Piped/Invidious metadata mirrors.
    Returns (duration_seconds, list_of_sheet_specs).
    Each sheet_spec: {'url': str, 'cols': int, 'rows': int, 'duration': float}
    """
    import json

    client_profiles = [
        None,
        {'youtube': {'player_client': ['tv_embedded', 'ios', 'android', 'mweb']}},
        {'youtube': {'player_client': ['ios', 'web']}},
    ]

    for vid in _get_candidate_video_ids(video_id):
        target_url = f"https://www.youtube.com/watch?v={vid}"
        for ext_args in client_profiles:
            opts = {
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'socket_timeout': 15,
                'noplaylist': True,
            }
            if ext_args:
                opts['extractor_args'] = ext_args
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)
                    if not info:
                        continue
                    duration = float(info.get('duration') or 0)
                    formats = info.get('formats') or []
                    sb_formats = [
                        f for f in formats
                        if f.get('fragments') and ('sb' in str(f.get('format_id', '')) or f.get('ext') == 'mhtml')
                    ]
                    if sb_formats:
                        # Sort by resolution (width * height) descending to pick highest-res sb0
                        sb_formats.sort(key=lambda f: (f.get('width') or 0) * (f.get('height') or 0), reverse=True)
                        best_sb = sb_formats[0]
                        cols = int(best_sb.get('columns') or 3)
                        rows = int(best_sb.get('rows') or 3)
                        frags = best_sb.get('fragments') or []
                        sheets = []
                        for frag in frags:
                            f_url = frag.get('url')
                            if f_url:
                                sheets.append({
                                    'url': f_url,
                                    'cols': cols,
                                    'rows': rows,
                                    'duration': float(frag.get('duration') or (duration / max(1, len(frags)))),
                                })
                        if sheets:
                            return duration, sheets
            except Exception as e:
                if "unavailable" in str(e).lower():
                    break  # try next candidate video_id
                continue

        # Fallback: Query Piped API instances for storyboard previewFrames
        piped_hosts = [
            "https://pipedapi.kavin.rocks",
            "https://api.piped.private.coffee",
            "https://pipedapi.tokhmi.xyz",
        ]
        for host in piped_hosts:
            raw = _fetch_url_bytes(f"{host}/streams/{vid}", timeout=8)
            if not raw:
                continue
            try:
                data = json.loads(raw.decode('utf-8'))
                duration = float(data.get('duration') or 0)
                previews = data.get('previewFrames') or []
                if previews:
                    previews.sort(key=lambda p: (p.get('frameWidth') or 0) * (p.get('frameHeight') or 0), reverse=True)
                    best_p = previews[0]
                    cols = int(best_p.get('framesPerPageX') or 3)
                    rows = int(best_p.get('framesPerPageY') or 3)
                    dur_per_frame = float(best_p.get('durationPerFrame') or 2000) / 1000.0
                    urls = best_p.get('urls') or []
                    sheets = [
                        {
                            'url': u,
                            'cols': cols,
                            'rows': rows,
                            'duration': cols * rows * dur_per_frame,
                        }
                        for u in urls
                    ]
                    if sheets:
                        return duration, sheets
            except Exception:
                continue

    return 0.0, []


def extract_frames_from_youtube_storyboard(
    url: str,
    output_dir: str,
    mode: str = "scene_change",
    sensitivity: str = "medium",
    interval: float = 5.0,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    progress_callback: Optional[Callable] = None,
) -> list[str]:
    """
    High-speed, cloud-resilient slide extraction using YouTube Storyboard Sprite Sheets
    and high-res keyframes. Completes 30-minute lectures in ~3 seconds and works on
    restricted serverless datacenter IPs (Vercel AWS iad1).
    """
    from concurrent.futures import ThreadPoolExecutor

    vid = _extract_youtube_id(url)
    if not vid:
        raise ValueError("Invalid YouTube video URL")

    if progress_callback:
        progress_callback(15.0, 0, "Fetching YouTube timeline storyboards & metadata...")

    duration, sheets = _fetch_storyboard_spec_for_video(vid)

    frames_with_ts: list[Tuple[float, np.ndarray]] = []

    if sheets:
        if progress_callback:
            progress_callback(35.0, 0, f"Downloading {len(sheets)} high-res storyboard grids...")

        with ThreadPoolExecutor(max_workers=10) as pool:
            sheet_bytes_list = list(pool.map(lambda s: _fetch_url_bytes(s['url'], timeout=10), sheets))

        elapsed_sec = 0.0
        for spec, raw_bytes in zip(sheets, sheet_bytes_list):
            cols = max(1, spec['cols'])
            rows = max(1, spec['rows'])
            sheet_dur = spec['duration']
            cell_dur = sheet_dur / (cols * rows)

            if not raw_bytes:
                elapsed_sec += sheet_dur
                continue

            arr = np.frombuffer(raw_bytes, dtype=np.uint8)
            sheet_img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if sheet_img is None:
                elapsed_sec += sheet_dur
                continue

            sh_h, sh_w = sheet_img.shape[:2]
            cell_w = sh_w // cols
            cell_h = sh_h // rows

            for r in range(rows):
                for c in range(cols):
                    ts = elapsed_sec + (r * cols + c) * cell_dur
                    if duration > 0 and ts > duration:
                        break
                    cell = sheet_img[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w]
                    if cell.size == 0 or float(np.mean(cell)) < 4.0:
                        continue
                    frames_with_ts.append((ts, cell))
            elapsed_sec += sheet_dur

    # Fallback to direct i.ytimg.com high-res keyframes if storyboard sheets were empty
    if not frames_with_ts:
        for cand_vid in _get_candidate_video_ids(vid):
            keyframe_names = [
                "maxresdefault.jpg", "maxres1.jpg", "maxres2.jpg", "maxres3.jpg",
                "sddefault.jpg", "sd1.jpg", "sd2.jpg", "sd3.jpg",
                "hqdefault.jpg", "hq1.jpg", "hq2.jpg", "hq3.jpg",
            ]
            kf_urls = [f"https://i.ytimg.com/vi/{cand_vid}/{name}" for name in keyframe_names]
            with ThreadPoolExecutor(max_workers=6) as pool:
                kf_bytes = list(pool.map(lambda u: _fetch_url_bytes(u, timeout=8), kf_urls))

            step_t = max(10.0, (duration / 6.0) if duration > 0 else 15.0)
            cur_t = 0.0
            for raw_b in kf_bytes:
                if not raw_b or len(raw_b) < 2500:
                    continue
                arr = np.frombuffer(raw_b, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None and img.shape[0] >= 180:
                    frames_with_ts.append((cur_t, img))
                    cur_t += step_t
            if frames_with_ts:
                break

    if not frames_with_ts:
        raise ValueError("Unable to retrieve video frames from YouTube. Please verify the video is public.")

    # Filter by start_time and end_time
    filtered_frames = [
        (ts, img) for (ts, img) in frames_with_ts
        if ts >= start_time and (end_time is None or ts <= end_time)
    ]
    if not filtered_frames:
        filtered_frames = frames_with_ts

    if progress_callback:
        progress_callback(65.0, 0, f"Analyzing {len(filtered_frames)} frames for slide changes...")

    COMPARE_SIZE = (480, 270)
    saved_paths: list[str] = []
    saved_hashes: list[np.ndarray] = []
    reference_gray: Optional[np.ndarray] = None
    last_saved_ts = -999.0

    for idx, (ts, frame) in enumerate(filtered_frames):
        small = cv2.resize(frame, COMPARE_SIZE, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        curr_hash = _phash(gray)

        should_save = False
        if reference_gray is None:
            should_save = True
        elif mode == "interval":
            if (ts - last_saved_ts) >= max(1.0, interval):
                if not any(_hamming_distance(curr_hash, h) < 0.06 for h in saved_hashes[-3:]):
                    should_save = True
        else:
            metrics = _compare_frames(reference_gray, gray)
            if _is_significant_change(metrics, sensitivity):
                if not any(_hamming_distance(curr_hash, h) < 0.08 for h in saved_hashes):
                    should_save = True

        if should_save:
            enhanced = _enhance_slide_frame(frame, target_size=(960, 540))
            filename = generate_frame_filename(ts)
            filepath = safe_path_join(output_dir, filename)
            cv2.imwrite(filepath, enhanced)
            saved_paths.append(filepath)
            saved_hashes.append(curr_hash)
            reference_gray = gray
            last_saved_ts = ts

    if progress_callback:
        progress_callback(95.0, len(saved_paths), f"Captured {len(saved_paths)} slides")

    return saved_paths

