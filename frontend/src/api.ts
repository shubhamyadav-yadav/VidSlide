import axios from 'axios';

const CANDIDATE_BACKENDS = [
  (typeof window !== 'undefined' ? localStorage.getItem('vidslide_backend_url') : null),
  import.meta.env.VITE_API_URL,
  'https://src-returned-unity-mobiles.trycloudflare.com',
  'http://127.0.0.1:8000',
  'http://localhost:8000',
].filter((u): u is string => Boolean(u && u.trim()));

let resolvedBaseUrl: string = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '');
let probePromise: Promise<string> | null = null;

/**
 * Automatically probes and selects the reachable FastAPI OpenCV backend
 * so both localhost:5173 and https://vid-slide.vercel.app connect to the
 * full-resolution OpenCV Detect -> Settle -> Capture video engine.
 */
export async function ensureBackendUrl(): Promise<string> {
  if (resolvedBaseUrl) return resolvedBaseUrl;
  if (probePromise) return probePromise;

  probePromise = (async () => {
    // If running locally on Vite dev server (:5173), check if Vite proxy works first
    if (typeof window !== 'undefined' && window.location.hostname === 'localhost') {
      try {
        const res = await fetch('/api/health', { method: 'GET' });
        if (res.ok) {
          resolvedBaseUrl = '';
          return '';
        }
      } catch {
        // continue to candidates
      }
    }

    for (const candidate of CANDIDATE_BACKENDS) {
      const clean = candidate.replace(/\/+$/, '');
      try {
        const controller = new AbortController();
        const tid = setTimeout(() => controller.abort(), 4000);
        const res = await fetch(`${clean}/api/health`, {
          method: 'GET',
          signal: controller.signal,
        });
        clearTimeout(tid);
        if (res.ok) {
          resolvedBaseUrl = clean;
          api.defaults.baseURL = clean;
          return clean;
        }
      } catch {
        // try next candidate
      }
    }

    // If on Vercel (HTTPS), default to the stable Cloudflare tunnel
    if (typeof window !== 'undefined' && window.location.hostname.includes('vercel.app')) {
      resolvedBaseUrl = 'https://src-returned-unity-mobiles.trycloudflare.com';
      api.defaults.baseURL = resolvedBaseUrl;
      return resolvedBaseUrl;
    }

    return resolvedBaseUrl;
  })();

  return probePromise;
}

// Trigger background probe immediately on page load
if (typeof window !== 'undefined') {
  ensureBackendUrl();
}

export const api = axios.create({
  baseURL: resolvedBaseUrl || undefined,
});

api.interceptors.request.use(async (config) => {
  const base = await ensureBackendUrl();
  if (base) {
    config.baseURL = base;
  }
  return config;
});

export const getApiUrl = (endpoint: string): string => {
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return `${resolvedBaseUrl}${cleanEndpoint}`;
};

export default api;
