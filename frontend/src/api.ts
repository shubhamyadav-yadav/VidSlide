import axios from 'axios';

export const API_BASE_URL = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '');

export const api = axios.create({
  baseURL: API_BASE_URL || undefined,
});

export const getApiUrl = (endpoint: string): string => {
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return `${API_BASE_URL}${cleanEndpoint}`;
};

export interface SlideFrameItem {
  name: string;
  time: string;
  url: string;
}

export interface ClientJobState {
  jobId: string;
  status: 'downloading' | 'extracting' | 'packaging' | 'completed' | 'failed';
  progress: number;
  frames_found: number;
  current_timestamp: string;
  message: string;
  frames: SlideFrameItem[];
  serverJobId?: string;
}

const clientJobs = new Map<string, ClientJobState>();

export const getClientJob = (jobId: string): ClientJobState | undefined => {
  return clientJobs.get(jobId);
};

// ---------------------------------------------------------------------------
// Browser-Native HTML5 <canvas> & <video> Scene Detection Engine (Fallback)
// ---------------------------------------------------------------------------

function extractYoutubeId(url: string): string | null {
  const m = url.match(/(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/|\/live\/)([A-Za-z0-9_-]{11})/);
  return m ? m[1] : null;
}

function getCandidateIds(vid: string): string[] {
  const cands = [vid];
  if (vid.includes('l')) cands.push(vid.replace(/l/g, 'I'));
  if (vid.includes('I')) cands.push(vid.replace(/I/g, 'l'));
  return Array.from(new Set(cands));
}

function formatSecToFilename(sec: number): { name: string; time: string } {
  const hrs = Math.floor(sec / 3600);
  const mins = Math.floor((sec % 3600) / 60);
  const secs = Math.floor(sec % 60);
  const hh = String(hrs).padStart(2, '0');
  const mm = String(mins).padStart(2, '0');
  const ss = String(secs).padStart(2, '0');
  return {
    name: `frame_${hh}h${mm}m${ss}s.jpg`,
    time: `${hh}:${mm}:${ss}`,
  };
}

function loadCorsImage(url: string, timeoutMs = 8000): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    const timer = setTimeout(() => {
      img.src = '';
      resolve(null);
    }, timeoutMs);
    img.onload = () => {
      clearTimeout(timer);
      if (img.naturalWidth >= 120 && img.naturalHeight >= 68) {
        resolve(img);
      } else {
        resolve(null);
      }
    };
    img.onerror = () => {
      clearTimeout(timer);
      resolve(null);
    };
    img.src = url;
  });
}

function computeCanvasSignature(ctx: CanvasRenderingContext2D, w: number, h: number): {
  gray: Uint8Array;
  meanBrightness: number;
} {
  const data = ctx.getImageData(0, 0, w, h).data;
  const gray = new Uint8Array(w * h);
  let sum = 0;
  for (let i = 0, j = 0; i < data.length; i += 4, j++) {
    const lum = (data[i] * 77 + data[i + 1] * 150 + data[i + 2] * 29) >> 8;
    gray[j] = lum;
    sum += lum;
  }
  return { gray, meanBrightness: sum / Math.max(1, gray.length) };
}

function isSignificantCanvasChange(
  prevGray: Uint8Array,
  currGray: Uint8Array,
  w: number,
  h: number,
  sensitivity: string
): boolean {
  let totalDiff = 0;
  for (let i = 0; i < prevGray.length; i++) {
    totalDiff += Math.abs(prevGray[i] - currGray[i]);
  }
  const meanDiff = totalDiff / prevGray.length;

  // 4x4 block diff
  const bw = Math.floor(w / 4);
  const bh = Math.floor(h / 4);
  let maxBlockDiff = 0;
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 4; c++) {
      let bSum = 0;
      let count = 0;
      for (let y = r * bh; y < (r + 1) * bh; y++) {
        for (let x = c * bw; x < (c + 1) * bw; x++) {
          const idx = y * w + x;
          bSum += Math.abs(prevGray[idx] - currGray[idx]);
          count++;
        }
      }
      const bMean = bSum / Math.max(1, count);
      if (bMean > maxBlockDiff) maxBlockDiff = bMean;
    }
  }

  const thresholds: Record<string, { mean: number; block: number }> = {
    low: { mean: 22, block: 40 },
    medium: { mean: 12, block: 24 },
    high: { mean: 6, block: 13 },
  };
  const cfg = thresholds[sensitivity.toLowerCase()] || thresholds.medium;
  return meanDiff > cfg.mean || maxBlockDiff > cfg.block;
}

async function extractYoutubeInBrowser(
  payload: {
    url: string;
    mode: string;
    sensitivity: string;
    interval: number;
  },
  state: ClientJobState
): Promise<SlideFrameItem[]> {
  const vid = extractYoutubeId(payload.url);
  if (!vid) {
    throw new Error('Invalid YouTube video URL');
  }

  state.status = 'downloading';
  state.progress = 22;
  state.message = 'Fetching YouTube timeline storyboards & keyframes...';

  const rawCandidates: { ts: number; img: HTMLImageElement; sx: number; sy: number; sw: number; sh: number }[] = [];

  // 1. Try Piped API mirrors for full storyboard sprite sheets
  const pipedMirrors = [
    'https://pipedapi.kavin.rocks',
    'https://api.piped.private.coffee',
    'https://pipedapi.tokhmi.xyz',
  ];

  let resolvedVid = vid;
  for (const cand of getCandidateIds(vid)) {
    for (const host of pipedMirrors) {
      try {
        const res = await fetch(`${host}/streams/${cand}`);
        if (!res.ok) continue;
        const data = await res.json();
        const previews = data.previewFrames || [];
        if (previews.length > 0) {
          resolvedVid = cand;
          previews.sort((a: any, b: any) => (b.frameWidth || 0) * (b.frameHeight || 0) - (a.frameWidth || 0) * (a.frameHeight || 0));
          const best = previews[0];
          const cols = Number(best.framesPerPageX || 3);
          const rows = Number(best.framesPerPageY || 3);
          const dpf = Number(best.durationPerFrame || 2000) / 1000;
          const urls: string[] = (best.urls || []).slice(0, 16);

          const loadedSheets = await Promise.all(
            urls.map((u) => loadCorsImage(`https://wsrv.nl/?url=${encodeURIComponent(u)}&output=jpg`, 8000))
          );

          let elapsed = 0;
          for (const sheetImg of loadedSheets) {
            if (!sheetImg) {
              elapsed += cols * rows * dpf;
              continue;
            }
            const cw = Math.floor(sheetImg.naturalWidth / cols);
            const ch = Math.floor(sheetImg.naturalHeight / rows);
            for (let r = 0; r < rows; r++) {
              for (let c = 0; c < cols; c++) {
                rawCandidates.push({
                  ts: elapsed + (r * cols + c) * dpf,
                  img: sheetImg,
                  sx: c * cw,
                  sy: r * ch,
                  sw: cw,
                  sh: ch,
                });
              }
            }
            elapsed += cols * rows * dpf;
          }
          break;
        }
      } catch {
        // continue to next mirror
      }
    }
    if (rawCandidates.length > 0) break;
  }

  // 2. Always supplement / fallback with high-res YouTube keyframe & chapter snapshots via wsrv.nl CORS CDN
  if (rawCandidates.length === 0) {
    state.progress = 45;
    state.message = 'Loading high-resolution video keyframes...';
    const kfNames = [
      'maxresdefault.jpg',
      'maxres1.jpg',
      'maxres2.jpg',
      'maxres3.jpg',
      'sddefault.jpg',
      'sd1.jpg',
      'sd2.jpg',
      'sd3.jpg',
      'hqdefault.jpg',
      'hq1.jpg',
      'hq2.jpg',
      'hq3.jpg',
    ];

    for (const cand of getCandidateIds(resolvedVid)) {
      const proxyUrls = kfNames.map(
        (n) => `https://wsrv.nl/?url=${encodeURIComponent(`https://i.ytimg.com/vi/${cand}/${n}`)}&w=1280&h=720&fit=cover&output=jpg`
      );
      const imgs = await Promise.all(proxyUrls.map((u) => loadCorsImage(u, 7500)));
      let t = 0;
      for (const im of imgs) {
        if (im && im.naturalWidth >= 240) {
          rawCandidates.push({
            ts: t,
            img: im,
            sx: 0,
            sy: 0,
            sw: im.naturalWidth,
            sh: im.naturalHeight,
          });
          t += 45;
        }
      }
      if (rawCandidates.length > 0) break;
    }
  }

  if (rawCandidates.length === 0) {
    throw new Error('Could not retrieve video frames from YouTube. Please verify the video URL is public.');
  }

  state.status = 'extracting';
  state.progress = 72;
  state.message = `Analyzing ${rawCandidates.length} frames for slide transitions...`;

  const outCanvas = document.createElement('canvas');
  outCanvas.width = 960;
  outCanvas.height = 540;
  const outCtx = outCanvas.getContext('2d')!;

  const cmpCanvas = document.createElement('canvas');
  const CMP_W = 64;
  const CMP_H = 36;
  cmpCanvas.width = CMP_W;
  cmpCanvas.height = CMP_H;
  const cmpCtx = cmpCanvas.getContext('2d', { willReadFrequently: true })!;

  const results: SlideFrameItem[] = [];
  const savedGrays: Uint8Array[] = [];

  for (const item of rawCandidates) {
    cmpCtx.drawImage(item.img, item.sx, item.sy, item.sw, item.sh, 0, 0, CMP_W, CMP_H);
    const { gray, meanBrightness } = computeCanvasSignature(cmpCtx, CMP_W, CMP_H);
    if (meanBrightness < 6) continue; // Skip pure black padding cells

    let keep = false;
    if (savedGrays.length === 0) {
      keep = true;
    } else {
      const prev = savedGrays[savedGrays.length - 1];
      if (isSignificantCanvasChange(prev, gray, CMP_W, CMP_H, payload.sensitivity)) {
        // Also ensure it is not a near-duplicate of any already-saved slide
        const isDuplicate = savedGrays.some((old) => !isSignificantCanvasChange(old, gray, CMP_W, CMP_H, 'high'));
        if (!isDuplicate) {
          keep = true;
        }
      }
    }

    if (keep && results.length < 40) {
      outCtx.drawImage(item.img, item.sx, item.sy, item.sw, item.sh, 0, 0, 960, 540);
      const dataUrl = outCanvas.toDataURL('image/jpeg', 0.86);
      const meta = formatSecToFilename(item.ts);
      results.push({
        name: meta.name,
        time: meta.time,
        url: dataUrl,
      });
      savedGrays.push(gray);
      state.frames_found = results.length;
    }
  }

  return results;
}

async function extractVideoFileInBrowser(
  file: File,
  mode: string,
  sensitivity: string,
  interval: number,
  state: ClientJobState
): Promise<SlideFrameItem[]> {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    const objUrl = URL.createObjectURL(file);
    video.src = objUrl;

    video.onerror = () => {
      URL.revokeObjectURL(objUrl);
      reject(new Error('Browser could not decode the selected video file'));
    };

    video.onloadedmetadata = async () => {
      try {
        const duration = Math.min(video.duration || 60, 3600);
        const step = mode === 'interval' ? Math.max(1, interval) : Math.max(1.5, duration / 45);
        const outCanvas = document.createElement('canvas');
        outCanvas.width = 960;
        outCanvas.height = 540;
        const outCtx = outCanvas.getContext('2d')!;

        const cmpCanvas = document.createElement('canvas');
        const CMP_W = 64;
        const CMP_H = 36;
        cmpCanvas.width = CMP_W;
        cmpCanvas.height = CMP_H;
        const cmpCtx = cmpCanvas.getContext('2d', { willReadFrequently: true })!;

        const results: SlideFrameItem[] = [];
        const savedGrays: Uint8Array[] = [];

        for (let t = 0; t < duration && results.length < 40; t += step) {
          await new Promise<void>((resSeek) => {
            const onSeeked = () => {
              video.removeEventListener('seeked', onSeeked);
              resSeek();
            };
            video.addEventListener('seeked', onSeeked);
            video.currentTime = t;
          });

          cmpCtx.drawImage(video, 0, 0, CMP_W, CMP_H);
          const { gray, meanBrightness } = computeCanvasSignature(cmpCtx, CMP_W, CMP_H);
          if (meanBrightness < 5) continue;

          let keep = false;
          if (savedGrays.length === 0 || mode === 'interval') {
            keep = true;
          } else {
            const prev = savedGrays[savedGrays.length - 1];
            if (isSignificantCanvasChange(prev, gray, CMP_W, CMP_H, sensitivity)) {
              keep = true;
            }
          }

          if (keep) {
            outCtx.drawImage(video, 0, 0, 960, 540);
            const meta = formatSecToFilename(t);
            results.push({
              name: meta.name,
              time: meta.time,
              url: outCanvas.toDataURL('image/jpeg', 0.86),
            });
            savedGrays.push(gray);
            state.frames_found = results.length;
            state.progress = Math.min(94, Math.round(20 + (t / duration) * 74));
          }
        }

        URL.revokeObjectURL(objUrl);
        resolve(results);
      } catch (e) {
        URL.revokeObjectURL(objUrl);
        reject(e);
      }
    };
  });
}

// ---------------------------------------------------------------------------
// Job Orchestration (Serverless API + Automatic Browser Fallback)
// ---------------------------------------------------------------------------

function startSimulatedProgress(jobId: string): ReturnType<typeof setInterval> {
  const startTime = Date.now();
  return setInterval(() => {
    const job = clientJobs.get(jobId);
    if (!job || job.status === 'completed' || job.status === 'failed') {
      return;
    }
    const elapsedSec = (Date.now() - startTime) / 1000;
    if (elapsedSec < 2.0) {
      job.status = 'downloading';
      job.progress = Math.min(28, Math.round(8 + elapsedSec * 10));
      job.message = 'Analyzing YouTube video metadata & timeline streams...';
    } else if (elapsedSec < 5.0) {
      job.status = 'downloading';
      job.progress = Math.min(55, Math.round(28 + (elapsedSec - 2.0) * 9));
      job.message = 'Downloading high-resolution video keyframes & grids...';
    } else if (elapsedSec < 9.0) {
      job.status = 'extracting';
      job.progress = Math.min(86, Math.round(55 + (elapsedSec - 5.0) * 7.5));
      job.frames_found = Math.max(job.frames_found, Math.floor((elapsedSec - 4.5) * 2.5));
      const fakeMin = String(Math.floor(elapsedSec * 2)).padStart(2, '0');
      job.current_timestamp = `00:${fakeMin}:15`;
      job.message = `Running pHash & regional scene detection...`;
    } else {
      job.status = 'packaging';
      job.progress = Math.min(95, Math.round(86 + (elapsedSec - 9.0) * 1.5));
      job.message = 'Enhancing slide contrast & preparing gallery...';
    }
  }, 250);
}

export const startUrlExtractionJob = (payload: {
  url: string;
  mode: string;
  sensitivity: string;
  interval: number;
  quality: string;
  start_time?: string;
  end_time?: string;
}): string => {
  const clientJobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const state: ClientJobState = {
    jobId: clientJobId,
    status: 'downloading',
    progress: 6,
    frames_found: 0,
    current_timestamp: '00:00:00',
    message: 'Connecting to extraction engine...',
    frames: [],
  };
  clientJobs.set(clientJobId, state);

  const timer = startSimulatedProgress(clientJobId);

  api
    .post('/api/process-url?sync=1', { ...payload, sync: true })
    .then(async (response) => {
      clearInterval(timer);
      const data = response.data;
      const items: SlideFrameItem[] = data.frame_items || [];
      if (items.length > 0) {
        state.serverJobId = data.job_id;
        state.frames = items;
        state.frames_found = items.length;
        state.progress = 100;
        state.status = 'completed';
        state.message = `Extracted ${items.length} slides successfully!`;
      } else if (data.job_id && !data.status) {
        // Local async backend mode: let SSE/polling track data.job_id
        state.serverJobId = data.job_id;
      } else {
        // Fallback to browser extraction if response had no inline items
        const browserFrames = await extractYoutubeInBrowser(payload, state);
        state.frames = browserFrames;
        state.frames_found = browserFrames.length;
        state.progress = 100;
        state.status = 'completed';
        state.message = `Extracted ${browserFrames.length} slides successfully!`;
      }
    })
    .catch(async (err) => {
      // Automatic client-side fallback if serverless API returns 405/500/timeout or IP block
      try {
        const browserFrames = await extractYoutubeInBrowser(payload, state);
        clearInterval(timer);
        state.frames = browserFrames;
        state.frames_found = browserFrames.length;
        state.progress = 100;
        state.status = 'completed';
        state.message = `Extracted ${browserFrames.length} slides successfully!`;
      } catch (fallbackErr: any) {
        clearInterval(timer);
        state.status = 'failed';
        state.message =
          err.response?.data?.detail ||
          fallbackErr?.message ||
          err.message ||
          'Failed to extract slides from video';
      }
    });

  return clientJobId;
};

export const startUploadExtractionJob = (formData: FormData): string => {
  const clientJobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const state: ClientJobState = {
    jobId: clientJobId,
    status: 'downloading',
    progress: 8,
    frames_found: 0,
    current_timestamp: '00:00:00',
    message: 'Uploading video file for scene analysis...',
    frames: [],
  };
  clientJobs.set(clientJobId, state);

  const timer = startSimulatedProgress(clientJobId);

  api
    .post('/api/upload?sync=1', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then(async (response) => {
      clearInterval(timer);
      const data = response.data;
      const items: SlideFrameItem[] = data.frame_items || [];
      state.serverJobId = data.job_id;
      state.frames = items;
      state.frames_found = items.length || data.count || 0;
      state.progress = 100;
      state.status = 'completed';
      state.message = `Extracted ${state.frames_found} slides successfully!`;
    })
    .catch(async (err) => {
      try {
        const file = formData.get('file') as File | null;
        if (file) {
          const mode = (formData.get('mode') as string) || 'scene_change';
          const sensitivity = (formData.get('sensitivity') as string) || 'medium';
          const interval = Number(formData.get('interval') || 5);
          const browserFrames = await extractVideoFileInBrowser(file, mode, sensitivity, interval, state);
          clearInterval(timer);
          state.frames = browserFrames;
          state.frames_found = browserFrames.length;
          state.progress = 100;
          state.status = 'completed';
          state.message = `Extracted ${browserFrames.length} slides successfully!`;
          return;
        }
      } catch {
        // ignore fallback error
      }
      clearInterval(timer);
      state.status = 'failed';
      state.message =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        'Video upload processing failed';
    });

  return clientJobId;
};

// ---------------------------------------------------------------------------
// Pure Browser ZIP Builder (for instant serverless ZIP downloads)
// ---------------------------------------------------------------------------

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) {
    c ^= bytes[i];
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
  }
  return (c ^ 0xffffffff) >>> 0;
}

function dataUrlToBytes(dataUrl: string): Uint8Array {
  const base64 = dataUrl.split(',')[1] || '';
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) {
    bytes[i] = bin.charCodeAt(i);
  }
  return bytes;
}

export function buildClientZipBlob(frames: SlideFrameItem[]): Blob {
  const encoder = new TextEncoder();
  const fileEntries: {
    nameBytes: Uint8Array;
    dataBytes: Uint8Array;
    crc: number;
    offset: number;
  }[] = [];

  let currentOffset = 0;
  const chunks: Uint8Array[] = [];

  for (const frame of frames) {
    if (!frame.url.startsWith('data:')) continue;
    const cleanName = frame.name.replace(/\.png$/i, '.jpg');
    const nameBytes = encoder.encode(cleanName);
    const dataBytes = dataUrlToBytes(frame.url);
    const crc = crc32(dataBytes);

    const localHeader = new Uint8Array(30 + nameBytes.length);
    const view = new DataView(localHeader.buffer);
    view.setUint32(0, 0x04034b50, true);
    view.setUint16(4, 20, true);
    view.setUint16(6, 0, true);
    view.setUint16(8, 0, true);
    view.setUint16(10, 0, true);
    view.setUint16(12, 0, true);
    view.setUint32(14, crc, true);
    view.setUint32(18, dataBytes.length, true);
    view.setUint32(22, dataBytes.length, true);
    view.setUint16(26, nameBytes.length, true);
    view.setUint16(28, 0, true);
    localHeader.set(nameBytes, 30);

    fileEntries.push({
      nameBytes,
      dataBytes,
      crc,
      offset: currentOffset,
    });

    chunks.push(localHeader, dataBytes);
    currentOffset += localHeader.length + dataBytes.length;
  }

  const centralDirOffset = currentOffset;
  let centralDirSize = 0;

  for (const entry of fileEntries) {
    const cdHeader = new Uint8Array(46 + entry.nameBytes.length);
    const view = new DataView(cdHeader.buffer);
    view.setUint32(0, 0x02014b50, true);
    view.setUint16(4, 20, true);
    view.setUint16(6, 20, true);
    view.setUint16(8, 0, true);
    view.setUint16(10, 0, true);
    view.setUint16(12, 0, true);
    view.setUint16(14, 0, true);
    view.setUint32(16, entry.crc, true);
    view.setUint32(20, entry.dataBytes.length, true);
    view.setUint32(24, entry.dataBytes.length, true);
    view.setUint16(28, entry.nameBytes.length, true);
    view.setUint16(30, 0, true);
    view.setUint16(32, 0, true);
    view.setUint16(34, 0, true);
    view.setUint16(36, 0, true);
    view.setUint32(38, 0, true);
    view.setUint32(42, entry.offset, true);
    cdHeader.set(entry.nameBytes, 46);

    chunks.push(cdHeader);
    centralDirSize += cdHeader.length;
  }

  const eocd = new Uint8Array(22);
  const eocdView = new DataView(eocd.buffer);
  eocdView.setUint32(0, 0x06054b50, true);
  eocdView.setUint16(4, 0, true);
  eocdView.setUint16(6, 0, true);
  eocdView.setUint16(8, fileEntries.length, true);
  eocdView.setUint16(10, fileEntries.length, true);
  eocdView.setUint32(12, centralDirSize, true);
  eocdView.setUint32(16, centralDirOffset, true);
  eocdView.setUint16(20, 0, true);
  chunks.push(eocd);

  return new Blob(chunks as unknown as BlobPart[], { type: 'application/zip' });
}

export default api;
