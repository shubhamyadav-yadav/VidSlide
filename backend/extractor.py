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

    # Check metadata first
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
                if file.endswith('.png'):
                    file_path = safe_path_join(root, file)
                    arcname = file  # flat safe basename
                    zipf.write(file_path, arcname)
    return output_path
