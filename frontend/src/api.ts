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
      job.frames_found = Math.max(1, Math.floor((elapsedSec - 4.5) * 2.5));
      const fakeMin = String(Math.floor(elapsedSec * 2)).padStart(2, '0');
      job.current_timestamp = `00:${fakeMin}:15`;
      job.message = `Running OpenCV pHash & regional scene detection...`;
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
    .then((response) => {
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
    .catch((err) => {
      clearInterval(timer);
      state.status = 'failed';
      state.message =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        'Failed to extract slides from video';
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
    .then((response) => {
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
    .catch((err) => {
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
    view.setUint32(0, 0x04034b50, true); // Local file header signature
    view.setUint16(4, 20, true); // Version needed
    view.setUint16(6, 0, true); // Flags
    view.setUint16(8, 0, true); // Compression: 0 = stored (JPEG is already compressed)
    view.setUint16(10, 0, true); // Mod time
    view.setUint16(12, 0, true); // Mod date
    view.setUint32(14, crc, true); // CRC-32
    view.setUint32(18, dataBytes.length, true); // Compressed size
    view.setUint32(22, dataBytes.length, true); // Uncompressed size
    view.setUint16(26, nameBytes.length, true); // Filename length
    view.setUint16(28, 0, true); // Extra field length
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
    view.setUint32(0, 0x02014b50, true); // Central directory signature
    view.setUint16(4, 20, true); // Version made by
    view.setUint16(6, 20, true); // Version needed
    view.setUint16(8, 0, true); // Flags
    view.setUint16(10, 0, true); // Compression: stored
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
  eocdView.setUint32(0, 0x06054b50, true); // End of central directory signature
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
