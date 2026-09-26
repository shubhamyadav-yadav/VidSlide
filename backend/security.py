import ipaddress
import os
import re
import socket
import uuid
from typing import Optional
from urllib.parse import urlparse

ALLOWED_YOUTUBE_HOSTS = {
    "www.youtube.com",
    "youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB
MAX_VIDEO_DURATION = int(os.environ.get("MAX_VIDEO_DURATION", 4 * 3600))  # 4 hours (14400s)

# ISO Base Media (MP4/MOV) fourcc atoms typically present at byte offset 4..8
_ISO_BMFF_ATOMS = {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}
# Matroska / WebM EBML header magic bytes at offset 0..4
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"


def check_ip_safety(hostname: str) -> None:
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError(f"Could not resolve hostname: {hostname}")

    for info in addr_info:
        ip_str = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        for network in PRIVATE_NETWORKS:
            if ip_obj in network:
                raise ValueError(f"Resolved IP {ip_str} is in a restricted private network.")


def validate_youtube_url(url: str) -> str:
    if not url or len(url) > 2048:
        raise ValueError("Invalid URL length")

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use HTTP or HTTPS")

    if parsed.hostname not in ALLOWED_YOUTUBE_HOSTS:
        raise ValueError(f"Hostname {parsed.hostname} is not an allowed YouTube domain")

    check_ip_safety(parsed.hostname)
    return url.strip()


def validate_job_id(job_id: str) -> str:
    try:
        parsed = uuid.UUID(job_id, version=4)
        return str(parsed)
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Invalid job ID format")


def sanitize_filename(name: str) -> str:
    if not name:
        return "default_filename"
    name = name.replace("\x00", "")
    name = os.path.basename(name)
    name = name.replace("..", "")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if not name or name in (".", "_"):
        name = "default_filename"
    return name


def safe_path_join(base_dir: str, *parts: str) -> str:
    joined_path = os.path.join(base_dir, *parts)
    real_base = os.path.realpath(base_dir)
    real_path = os.path.realpath(joined_path)
    if not real_path.startswith(real_base + os.sep) and real_path != real_base:
        raise ValueError("Path traversal detected")
    return real_path


def validate_file_extension(filename: str) -> None:
    if not filename:
        raise ValueError("Filename is required")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File extension '{ext}' is not allowed.")


def validate_video_magic_bytes(header: bytes) -> None:
    """Verify that the uploaded file header matches a valid video container signature."""
    if not header or len(header) < 12:
        raise ValueError("Uploaded file is empty or too small to be a valid video.")
    if header[:4] == _EBML_MAGIC:
        return
    if header[4:8] in _ISO_BMFF_ATOMS:
        return
    raise ValueError("Invalid video file content signature.")


def parse_and_validate_timestamp(ts: Optional[str]) -> Optional[float]:
    if ts is None or not ts.strip():
        return None
    clean = ts.strip()
    if not re.match(r"^\d{1,3}(:\d{1,2}){0,2}(\.\d+)?$", clean):
        raise ValueError(f"Invalid timestamp format: '{clean}'. Expected HH:MM:SS or MM:SS.")
    parts = clean.split(":")
    if len(parts) == 3:
        seconds = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        seconds = float(parts[0]) * 60 + float(parts[1])
    else:
        seconds = float(parts[0])
    if seconds < 0 or seconds > MAX_VIDEO_DURATION:
        raise ValueError(f"Timestamp must be between 0 and {MAX_VIDEO_DURATION} seconds.")
    return seconds


def generate_frame_filename(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"frame_{hours:02d}h{minutes:02d}m{secs:02d}s.png"

