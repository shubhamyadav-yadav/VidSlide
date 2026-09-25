import re
import uuid
import socket
import ipaddress
from urllib.parse import urlparse
from pathlib import Path
import os

ALLOWED_YOUTUBE_HOSTS = {
    "www.youtube.com", "youtube.com", "m.youtube.com",
    "youtu.be", "www.youtu.be",
}

PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB
MAX_VIDEO_DURATION = int(os.environ.get("MAX_VIDEO_DURATION", 4 * 3600))  # 4 hours in seconds (14400s)


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
                raise ValueError(f"Resolved IP {ip_str} is in private network.")


def validate_youtube_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use HTTP or HTTPS")
        
    if parsed.hostname not in ALLOWED_YOUTUBE_HOSTS:
        raise ValueError(f"Hostname {parsed.hostname} is not allowed")
        
    check_ip_safety(parsed.hostname)
    
    return url


def sanitize_filename(name: str) -> str:
    name = name.replace("\x00", "")
    name = os.path.basename(name)
    name = name.replace("..", "")
    if not name:
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
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File extension {ext} not allowed.")


def generate_frame_filename(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"frame_{hours:02d}h{minutes:02d}m{secs:02d}s.png"
