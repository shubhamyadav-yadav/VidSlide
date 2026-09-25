import os
import sys

# Ensure current directory and backend directory are on sys.path for both root & subdirectory Vercel builds
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
backend_dir = os.path.join(parent_dir, "backend")

for p in (current_dir, backend_dir, parent_dir):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("VERCEL", "1")

from main import app
