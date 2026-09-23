import pytest
import os
import sys
import zipfile
import tempfile
import numpy as np
import cv2
import asyncio
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from security import (
    validate_youtube_url, sanitize_filename, safe_path_join,
    validate_file_extension, generate_frame_filename, check_ip_safety
)
from extractor import extract_frames_scene_change, extract_frames_interval, create_zip
from main import app


def test_ssrf_localhost():
    with pytest.raises(ValueError):
        validate_youtube_url("http://localhost:8000")


def test_ssrf_metadata_endpoint():
    with pytest.raises(ValueError):
        validate_youtube_url("http://169.254.169.254/latest/meta-data")


def test_ssrf_evil_domain():
    with pytest.raises(ValueError):
        validate_youtube_url("http://evil.com/watch?v=abc")


@patch('socket.getaddrinfo')
def test_ssrf_private_ip_10(mock_getaddrinfo):
    mock_getaddrinfo.return_value = [(2, 1, 6, '', ('10.0.0.1', 80))]
    with pytest.raises(ValueError):
        validate_youtube_url("http://youtube.com/watch?v=abc")


@patch('socket.getaddrinfo')
def test_valid_youtube_url(mock_getaddrinfo):
    mock_getaddrinfo.return_value = [(2, 1, 6, '', ('142.250.80.46', 80))]
    res = validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert res == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@patch('socket.getaddrinfo')
def test_valid_youtu_be(mock_getaddrinfo):
    mock_getaddrinfo.return_value = [(2, 1, 6, '', ('142.250.80.46', 80))]
    res = validate_youtube_url("https://youtu.be/dQw4w9WgXcQ")
    assert res == "https://youtu.be/dQw4w9WgXcQ"


def test_path_traversal_filename():
    assert sanitize_filename("../../etc/passwd") == "passwd"


def test_null_byte_filename():
    assert sanitize_filename("file\x00.png") == "file.png"


def test_safe_path_join_traversal():
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ValueError):
            safe_path_join(td, "../../etc/passwd")


def test_valid_extensions():
    validate_file_extension("video.mp4")
    validate_file_extension("video.mkv")
    with pytest.raises(ValueError):
        validate_file_extension("script.sh")
    with pytest.raises(ValueError):
        validate_file_extension("program.exe")


def test_frame_filename_format():
    assert generate_frame_filename(134.0) == "frame_00h02m14s.png"


@pytest.fixture
def synthetic_video():
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tf:
        video_path = tf.name
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(video_path, fourcc, 30.0, (640, 480))
    
    # Slide 1: Blue background with "SLIDE 1" text pattern
    for _ in range(50):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (255, 0, 0)  # Blue
        cv2.putText(frame, "SLIDE 1 - INTRO", (50, 250), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 4)
        cv2.rectangle(frame, (20, 20), (620, 460), (200, 200, 200), 3)
        out.write(frame)
    # Slide 2: Green background with different text
    for _ in range(50):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (0, 255, 0)  # Green
        cv2.putText(frame, "SLIDE 2 - BODY", (50, 250), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 4)
        cv2.circle(frame, (320, 350), 80, (0, 0, 255), -1)
        out.write(frame)
    # Slide 3: Red background with different text
    for _ in range(50):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (0, 0, 255)  # Red
        cv2.putText(frame, "SLIDE 3 - END", (50, 250), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 0), 4)
        cv2.line(frame, (50, 400), (590, 400), (255, 255, 255), 5)
        out.write(frame)
        
    out.release()
    yield video_path
    os.remove(video_path)


def test_synthetic_video_scene_change(synthetic_video):
    with tempfile.TemporaryDirectory() as td:
        frames = extract_frames_scene_change(synthetic_video, td, sensitivity="medium", min_gap=0.3)
        # Must detect at least 2 of the 3 distinct slides
        assert len(frames) >= 2, f"Expected >=2 frames, got {len(frames)}: {frames}"


def test_synthetic_video_interval(synthetic_video):
    with tempfile.TemporaryDirectory() as td:
        frames = extract_frames_interval(synthetic_video, td, interval=1.0)
        # 5 seconds of video at 1s interval should yield at least 3 distinct frames
        assert len(frames) >= 3, f"Expected >=3 frames, got {len(frames)}: {frames}"


def test_zip_integrity(synthetic_video):
    with tempfile.TemporaryDirectory() as td:
        frames = extract_frames_interval(synthetic_video, td, interval=1.0)
        zip_path = os.path.join(td, 'out.zip')
        create_zip(td, zip_path)
        assert zipfile.is_zipfile(zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
            assert any(n.startswith("frame_") for n in names)


def test_zip_no_path_traversal(synthetic_video):
    with tempfile.TemporaryDirectory() as td:
        frames = extract_frames_interval(synthetic_video, td, interval=1.0)
        zip_path = os.path.join(td, 'out.zip')
        create_zip(td, zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                assert ".." not in name
                assert not os.path.isabs(name)


@pytest.mark.asyncio
async def test_api_ssrf_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/process-url", json={"url": "http://localhost:8080/evil"})
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_api_upload_invalid_extension():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/api/upload", 
            files={"file": ("test.txt", b"hello", "text/plain")},
            data={"mode": "scene_change", "sensitivity": "medium", "interval": 5.0}
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_api_progress_unknown_job():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/progress/nonexistent")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_download_unknown_job():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/download/nonexistent")
        assert response.status_code == 404


def test_long_video_duration_tolerated():
    from security import MAX_VIDEO_DURATION
    # 3096s was the user's video length in the error screenshot
    assert 3096 <= MAX_VIDEO_DURATION
    assert MAX_VIDEO_DURATION >= 14400  # at least 4 hours


@pytest.mark.asyncio
async def test_api_frames_unknown_job():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/frames/nonexistent")
        assert response.status_code == 404

