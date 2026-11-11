import os
import re
import shutil
import time
import uuid
import zipfile
from typing import Callable, Optional

import cv2
import numpy as np
import yt_dlp

from security import generate_frame_filename, safe_path_join, MAX_VIDEO_DURATION

# Locate portable FFmpeg binary if available (e.g. from imageio-ffmpeg)
FFMPEG_EXE = None
try:
    import imageio_ffmpeg
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_EXE = shutil.which("ffmpeg")

if FFMPEG_EXE and os.path.exists(FFMPEG_EXE):
    _ffmpeg_dir = os.path.dirname(FFMPEG_EXE)
    if _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")


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

            # Map download cleanly from 10% - 50% without dipping backwards
            overall_pct = round(10.0 + (raw_pct * 0.40), 1)
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
            f'bestvideo[height<={max_height}][ext=mp4][vcodec^=avc1]/'
            f'bestvideo[height<={max_height}][vcodec^=avc1]/'
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


_COMPARE_SIZE = (480, 270)
_CANNY_KERNEL = np.ones((3, 3), np.uint8)


def _extract_features(frame: np.ndarray, compute_hash: bool = True) -> dict:
    """
    Extract lightweight grayscale, edge mask, dilated edge mask, and optional
    perceptual hash from a full-resolution video frame for accurate slide comparison.
    """
    small = cv2.resize(frame, _COMPARE_SIZE, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150) > 0
    edges_dil = cv2.dilate(edges.astype(np.uint8), _CANNY_KERNEL) > 0
    return {
        'gray': gray,
        'edges': edges,
        'edges_dil': edges_dil,
        'edge_count': int(np.count_nonzero(edges)),
        'phash': _phash(gray) if compute_hash else None,
    }


def _compare_features(f1: dict, f2: dict) -> dict:
    """
    Compare precomputed slide feature dictionaries using changed-pixel ratio,
    4x4 grid regional changes, edge disappearance (new slide vs ink overlay),
    and edge appearance (incremental bullet builds).
    """
    g1, g2 = f1['gray'], f2['gray']
    diff = cv2.absdiff(g1, g2)
    mean_diff = float(np.mean(diff))
    changed_mask = diff > 25
    changed_ratio = float(np.count_nonzero(changed_mask)) / diff.size

    h, w = diff.shape
    bh, bw = max(1, h // 4), max(1, w // 4)
    max_block_chg = 0.0
    active_blocks = 0
    for r in range(4):
        for c in range(4):
            blk = changed_mask[r * bh:(r + 1) * bh, c * bw:(c + 1) * bw]
            ratio = float(np.count_nonzero(blk)) / max(1, blk.size)
            if ratio > max_block_chg:
                max_block_chg = ratio
            if ratio > 0.025:
                active_blocks += 1

    e1_cnt = f1['edge_count']
    e2_cnt = f2['edge_count']
    if e1_cnt >= 40:
        edge_dis = float(np.count_nonzero(f1['edges'] & (~f2['edges_dil']))) / e1_cnt
    else:
        edge_dis = changed_ratio

    if e2_cnt >= 40:
        edge_app = float(np.count_nonzero(f2['edges'] & (~f1['edges_dil']))) / e2_cnt
    else:
        edge_app = changed_ratio

    hash_dist = None
    if f1['phash'] is not None and f2['phash'] is not None:
        hash_dist = _hamming_distance(f1['phash'], f2['phash'])

    return {
        'mean_diff': mean_diff,
        'changed_ratio': changed_ratio,
        'max_block_chg': max_block_chg,
        'active_blocks': active_blocks,
        'edge_dis': edge_dis,
        'edge_app': edge_app,
        'hash_dist': hash_dist,
    }


def _compare_frames(gray1: np.ndarray, gray2: np.ndarray) -> dict:
    """Compatibility helper comparing two pre-resized grayscale frames."""
    e1 = cv2.Canny(gray1, 50, 150) > 0
    e2 = cv2.Canny(gray2, 50, 150) > 0
    f1 = {
        'gray': gray1,
        'edges': e1,
        'edges_dil': cv2.dilate(e1.astype(np.uint8), _CANNY_KERNEL) > 0,
        'edge_count': int(np.count_nonzero(e1)),
        'phash': _phash(gray1),
    }
    f2 = {
        'gray': gray2,
        'edges': e2,
        'edges_dil': cv2.dilate(e2.astype(np.uint8), _CANNY_KERNEL) > 0,
        'edge_count': int(np.count_nonzero(e2)),
        'phash': _phash(gray2),
    }
    return _compare_features(f1, f2)


def _is_significant_change(metrics: dict, sensitivity: str) -> bool:
    """
    Determine whether the visual change represents a real slide transition or
    meaningful content step while filtering minor annotations, cursor movement,
    single-corner presenter webcam motion, and translucent scrim overlays.
    """
    s = sensitivity.lower()
    # Ignore translucent dimming overlays (e.g. OS control center) where background darkens
    # uniformly across the screen while underlying slide text edges stay mostly intact.
    if metrics['changed_ratio'] > 0.60 and metrics['edge_dis'] < 0.12 and metrics['edge_app'] < 0.25:
        return False

    if s == "low":
        new_slide = (
            metrics['edge_dis'] >= 0.18
            and metrics['edge_app'] >= 0.18
            and metrics['changed_ratio'] >= 0.025
        )
        visual_swap = (
            metrics['changed_ratio'] >= 0.14
            and metrics['active_blocks'] >= 4
            and metrics['edge_dis'] >= 0.10
        )
        spread_content_swap = (
            metrics['changed_ratio'] >= 0.03
            and metrics['max_block_chg'] >= 0.14
            and metrics['active_blocks'] >= 5
            and (metrics['edge_dis'] >= 0.05 or metrics['edge_app'] >= 0.15)
        )
        return new_slide or visual_swap or spread_content_swap

    if s == "high":
        new_slide = (
            metrics['edge_dis'] >= 0.12
            and metrics['changed_ratio'] >= 0.015
            and metrics['active_blocks'] >= 2
        )
        visual_swap = metrics['changed_ratio'] >= 0.06 and metrics['active_blocks'] >= 3
        subtle_build = (
            (metrics['edge_app'] >= 0.14 or metrics['edge_dis'] >= 0.08)
            and metrics['max_block_chg'] >= 0.030
            and metrics['changed_ratio'] >= 0.004
            and metrics['active_blocks'] >= 2
        )
        return new_slide or visual_swap or subtle_build

    # Medium (default): balanced capture of every distinct slide + multi-line/code builds
    new_slide = (
        metrics['edge_dis'] >= 0.16
        and metrics['edge_app'] >= 0.16
        and metrics['changed_ratio'] >= 0.025
    )
    visual_swap = (
        metrics['changed_ratio'] >= 0.10
        and metrics['active_blocks'] >= 4
        and metrics['edge_dis'] >= 0.08
    )
    spread_content_swap = (
        metrics['changed_ratio'] >= 0.028
        and metrics['max_block_chg'] >= 0.12
        and metrics['active_blocks'] >= 4
        and (metrics['edge_dis'] >= 0.05 or metrics['edge_app'] >= 0.14)
    )
    content_add = (
        metrics['edge_app'] >= 0.28
        and metrics['changed_ratio'] >= 0.0045
        and metrics['max_block_chg'] >= 0.045
        and metrics['active_blocks'] >= 2
    )
    return new_slide or visual_swap or spread_content_swap or content_add


def _is_duplicate_of_saved(cand_feat: dict, saved_feats: list[dict], sensitivity: str) -> bool:
    """Check if candidate matches a previously saved slide (e.g. presenter flipped back briefly)."""
    s = sensitivity.lower()
    for prev in saved_feats:
        m = _compare_features(prev, cand_feat)
        if m['changed_ratio'] >= 0.03 and m['max_block_chg'] >= 0.12 and m['active_blocks'] >= 4:
            continue
        if s == "high":
            if m['edge_dis'] < 0.08 and m['edge_app'] < 0.10 and m['changed_ratio'] < 0.015:
                return True
        else:
            if m['edge_dis'] < 0.14 and m['changed_ratio'] < 0.08 and m['edge_app'] < 0.25:
                return True
            if (
                m['hash_dist'] is not None
                and m['hash_dist'] < 0.05
                and m['edge_dis'] < 0.15
                and m['edge_app'] < 0.22
            ):
                return True
    return False


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
    
    1. DETECT: Identify when significant structural/edge changes occur from the current slide.
    2. SETTLE: Wait until the frame stabilizes for a continuous dwell window (~0.75s)
       so wipe/fade animations finish and brief accidental flicks are ignored, while
       bounding settling duration so corner webcam motion never stalls capture.
    3. CAPTURE: Verify uniqueness against previously captured slides and save the
       full-resolution PNG frame.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Failed to open video file")
        
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or np.isnan(fps):
        fps = 30.0
        
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_duration = (total_frames / fps) if total_frames > 0 else 0.0
    effective_end = end_time if (end_time is not None and end_time > 0) else video_duration
    duration_range = max(0.1, (effective_end - start_time)) if effective_end > start_time else max(0.1, video_duration)
    
    if start_time > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, start_time * 1000.0)
        
    saved_paths: list[str] = []
    saved_feats: list[dict] = []
    current_scene_feat: Optional[dict] = None
    last_saved_time = start_time - min_gap
    frame_count = 0
    
    sample_step = max(1, round(fps / 4.0))  # 4 Hz scan
    settle_step = max(1, round(fps / 5.0))  # 5 Hz settle check

    INITIAL_SETTLE_SEC = 0.35
    SETTLE_HOLD_SEC = 0.75
    SETTLE_MAX_SEC = 3.0
    
    settling = False
    settle_start_time = 0.0
    stable_since_time = 0.0
    settle_prev_gray = None
    settle_best_frame = None
    settle_best_time = 0.0
    settle_min_step_diff = float('inf')

    def _save_frame(frame_img: np.ndarray, ts_sec: float) -> str:
        filename = generate_frame_filename(max(0.0, ts_sec))
        filepath = safe_path_join(output_dir, filename)
        cv2.imwrite(filepath, frame_img)
        return filepath
    
    while True:
        ret = cap.grab()
        if not ret:
            break
            
        frame_count += 1
        approx_time = start_time + (frame_count / fps)
        
        if end_time is not None and approx_time > end_time + 1.0:
            break
        
        if settling:
            if frame_count % settle_step != 0:
                continue
        else:
            if (frame_count % sample_step != 0) and (current_scene_feat is not None):
                continue
        
        ret, frame = cap.retrieve()
        if not ret or frame is None:
            continue

        actual_msec = cap.get(cv2.CAP_PROP_POS_MSEC)
        current_time = (actual_msec / 1000.0) if actual_msec > 0 else approx_time
        if start_time > 0 and current_time < start_time - 0.2:
            continue
        if end_time is not None and current_time > end_time:
            break
            
        small = cv2.resize(frame, _COMPARE_SIZE, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        
        # === PHASE 1: Initial slide capture ===
        if not settling and current_scene_feat is None:
            settling = True
            settle_start_time = current_time
            stable_since_time = current_time
            settle_prev_gray = gray.copy()
            settle_best_frame = frame.copy()
            settle_best_time = current_time
            settle_min_step_diff = float('inf')
            continue
        
        # === PHASE 2: Settling mode ===
        if settling:
            diff_step = cv2.absdiff(gray, settle_prev_gray)
            step_mean = float(np.mean(diff_step))
            step_chg = float(np.count_nonzero(diff_step > 20)) / diff_step.size

            h, w = diff_step.shape
            bh, bw = max(1, h // 4), max(1, w // 4)
            moving_blocks = sum(
                1
                for r in range(4)
                for c in range(4)
                if float(np.count_nonzero(diff_step[r * bh:(r + 1) * bh, c * bw:(c + 1) * bw] > 20))
                / max(1, bh * bw)
                > 0.03
            )

            is_stable = (step_chg < 0.015 and step_mean < 3.5) or (
                moving_blocks <= 2 and step_chg < 0.06 and step_mean < 6.0
            )
            if is_stable:
                settle_best_frame = frame.copy()
                settle_best_time = current_time
            else:
                stable_since_time = current_time
                if step_mean < settle_min_step_diff:
                    settle_min_step_diff = step_mean
                    settle_best_frame = frame.copy()
                    settle_best_time = current_time

            settle_prev_gray = gray.copy()
            stable_duration = current_time - stable_since_time
            total_settle = current_time - settle_start_time
            required_hold = INITIAL_SETTLE_SEC if len(saved_feats) == 0 else SETTLE_HOLD_SEC

            if stable_duration >= required_hold or total_settle >= SETTLE_MAX_SEC:
                cand_feat = _extract_features(settle_best_frame, compute_hash=True)
                if len(saved_feats) == 0:
                    fpath = _save_frame(settle_best_frame, settle_best_time)
                    saved_paths.append(fpath)
                    saved_feats.append(cand_feat)
                    current_scene_feat = cand_feat
                    last_saved_time = settle_best_time
                else:
                    m_cur = _compare_features(current_scene_feat, cand_feat)
                    if _is_significant_change(m_cur, sensitivity):
                        if not _is_duplicate_of_saved(cand_feat, saved_feats, sensitivity):
                            if (settle_best_time - last_saved_time) >= min_gap:
                                fpath = _save_frame(settle_best_frame, settle_best_time)
                                saved_paths.append(fpath)
                                saved_feats.append(cand_feat)
                                last_saved_time = settle_best_time
                        current_scene_feat = cand_feat

                settling = False
                settle_best_frame = None
                continue
        else:
            # === PHASE 1 continued: Fast-skip unchanged frames ===
            fast_diff = cv2.absdiff(gray, current_scene_feat['gray'])
            fast_chg = float(np.count_nonzero(fast_diff > 25)) / fast_diff.size
            if fast_chg >= 0.003:
                feat = _extract_features(frame, compute_hash=False)
                metrics = _compare_features(current_scene_feat, feat)
                if _is_significant_change(metrics, sensitivity) and (current_time - last_saved_time) >= min_gap:
                    settling = True
                    settle_start_time = current_time
                    stable_since_time = current_time
                    settle_prev_gray = gray.copy()
                    settle_best_frame = frame.copy()
                    settle_best_time = current_time
                    settle_min_step_diff = float('inf')

        # Progress reporting
        if progress_callback and (frame_count % (sample_step * 5) == 0):
            percent = ((current_time - start_time) / duration_range) * 100.0
            percent = min(99.0, max(0.0, percent))

            hours = int(current_time // 3600)
            minutes = int((current_time % 3600) // 60)
            secs = int(current_time % 60)
            ts_str = f"{hours:02d}:{minutes:02d}:{secs:02d}"

            progress_callback(percent, len(saved_paths), ts_str)
            
    # Handle end-of-video settling: capture final valid slide if clip ended before full hold
    if settling and settle_best_frame is not None:
        total_settle = settle_best_time - settle_start_time
        if len(saved_paths) == 0:
            fpath = _save_frame(settle_best_frame, settle_best_time)
            saved_paths.append(fpath)
        elif total_settle >= 1.0 and (settle_best_time - last_saved_time) >= min_gap:
            cand_feat = _extract_features(settle_best_frame, compute_hash=True)
            m_cur = _compare_features(current_scene_feat, cand_feat)
            if _is_significant_change(m_cur, sensitivity) and not _is_duplicate_of_saved(
                cand_feat, saved_feats, sensitivity
            ):
                fpath = _save_frame(settle_best_frame, settle_best_time)
                saved_paths.append(fpath)

    cap.release()
    
    if progress_callback:
        progress_callback(100.0, len(saved_paths), "Done")
        
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


