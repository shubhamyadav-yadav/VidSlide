# Deployment Guide — VidSlide

This guide provides instructions for deploying **VidSlide** with the frontend hosted on **Vercel** and the FastAPI media extraction engine hosted on a container/cloud platform (e.g., Render, Railway, Fly.io, or your own VPS).

---

## Architecture Overview

```
┌─────────────────────────────────┐        ┌──────────────────────────────────┐
│         Vercel (Edge)           │        │   Render / Railway / VPS / Cloud │
│                                 │        │                                  │
│  React + Vite + Tailwind UI     │───────>│  FastAPI + OpenCV + yt-dlp       │
│  (Configured via vercel.json)   │  HTTP  │  (Runs background video workers) │
│  VITE_API_URL -> Backend URL    │  & SSE │                                  │
└─────────────────────────────────┘        └──────────────────────────────────┘
```

> **Why split frontend & backend?**  
> VidSlide uses OpenCV and `yt-dlp` to download video streams and perform perceptual frame analysis. These operations take 30–120 seconds and require ffmpeg/OpenCV binaries. Vercel serverless functions have a 15-second execution timeout on free tiers. Hosting the frontend on Vercel and the backend on a container runner gives you blazing fast global CDN performance for the UI with uninterrupted video processing power.

---

## 1. Deploy Frontend to Vercel

### Step 1: Import to Vercel
1. Go to [vercel.com](https://vercel.com) and log in.
2. Click **Add New...** -> **Project**.
3. Select your repository: `https://github.com/shubhamyadav-yadav/VidSlide.git`.
4. Vercel will automatically read the root `vercel.json` and configure:
   - **Framework Preset:** Vite
   - **Build Command:** `cd frontend && npm install && npm run build` (or automatic)
   - **Output Directory:** `frontend/dist`

### Step 2: Configure Environment Variables
Under **Environment Variables** in the Vercel project configuration, add:

| Key | Value | Description |
| :--- | :--- | :--- |
| `VITE_API_URL` | `https://your-backend-api.onrender.com` | The public URL of your deployed FastAPI backend (omit trailing slash). |

> **Note:** If you haven't deployed the backend yet, you can deploy the frontend first and update `VITE_API_URL` later under **Project Settings -> Environment Variables**.

### Step 3: Deploy
Click **Deploy**. Your VidSlide frontend will be live at `https://vidslide-<username>.vercel.app`!

---

## 2. Deploy Backend (FastAPI + OpenCV + yt-dlp)

Choose any container platform below:

### Option A: Render.com (Recommended & Free)
1. Go to [render.com](https://render.com) and log in.
2. Click **New +** -> **Web Service**.
3. Connect your GitHub repository `VidSlide`.
4. Configure:
   - **Name:** `vidslide-backend`
   - **Root Directory:** `backend`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Under **Environment Variables**:
   - `PYTHON_VERSION`: `3.11.9` (or `3.10`+)
   - `CORS_ORIGINS`: `https://vidslide.vercel.app` *(or your Vercel URL)*
6. Click **Create Web Service**.
7. Copy your assigned Render URL (e.g. `https://vidslide-backend.onrender.com`).

---

### Option B: Railway.app
1. Go to [railway.app](https://railway.app) and click **New Project** -> **Deploy from GitHub repo**.
2. Select `VidSlide`.
3. In service settings, set **Root Directory** to `/backend`.
4. Railway will automatically detect Python and install `requirements.txt`.
5. Under **Variables**, add:
   - `CORS_ORIGINS`: `https://your-app.vercel.app`
6. Click **Generate Domain** under Networking.

---

### Option C: Docker / VPS
You can run the full containerized backend on any VPS using the included `Dockerfile`:

```bash
docker build -t vidslide-backend .
docker run -d -p 8000:8000 \
  -e CORS_ORIGINS="https://your-app.vercel.app" \
  --name vidslide vidslide-backend
```

---

## 3. Verify Connection

1. Open your Vercel app URL: `https://your-app.vercel.app`.
2. Paste a short YouTube video URL (e.g., a 1-minute talk).
3. The real-time progress panel should connect via SSE to your backend and show live progress percentages.
4. When finished, review the captured slides and download the ZIP file.
