# VidSlide — Frame Extraction Studio

> Turn any video into clean presentation slides automatically.

VidSlide is a hardened, production-ready web application that extracts high-quality screenshots and slides from YouTube videos or uploaded video files, detects scene changes using perceptual hashing and multi-metric analysis, compresses the frames into a secure ZIP archive, and serves them through an intuitive web interface.

---

## Features

- **Scene Detection Engine:** Multi-metric comparison (global mean difference, regional block diff, and DCT-based perceptual hashing `pHash`) with 3-phase *Detect → Settle → Capture* to avoid blurred transition frames.
- **YouTube Extraction:** Downloads video streams directly using `yt-dlp` with automatic retry, format resolution, and instant cleanup.
- **Local File Upload:** Drag-and-drop support for `.mp4`, `.mov`, `.mkv`, and `.webm` files up to 500 MB.
- **Real-Time Progress:** Server-Sent Events (SSE) streaming percentage, frames captured, and live video timestamps with fallback polling synchronization.
- **Interactive Studio UI:**
  - Modern YouTube Red multi-gradient styling
  - Live slide detection preview with dynamic timeline marks
  - Responsive column density switcher (3 / 4 / 5 columns)
  - Full-screen lightbox modal with keyboard navigation (<kbd>←</kbd> / <kbd>→</kbd> / <kbd>Esc</kbd>)
  - Single-frame download and full ZIP archive export
- **Mobile & Desktop Responsive:** Optimized touch targets and seamless layout adaptation.

---

## Tech Stack

- **Backend:** Python, FastAPI, OpenCV (`cv2`), `yt-dlp`, `numpy`, `slowapi`
- **Frontend:** React, TypeScript, Vite, Tailwind CSS, Lucide Icons, Axios

---

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+

### 1. Backend Setup

```bash
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Running Tests

```bash
python -m pytest backend/tests/test_pipeline.py -v
```

---

## Deployment

VidSlide is ready for cloud deployment:
- **Frontend on Vercel:** Zero-configuration deployment using the included `vercel.json`. Set `VITE_API_URL` to point to your backend.
- **Backend on Render / Railway / Docker:** Media processing engine running FastAPI and OpenCV.

See the complete step-by-step [Deployment Guide](DEPLOYMENT.md) for full instructions.

---

## License

MIT
