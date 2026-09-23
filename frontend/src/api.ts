import axios from 'axios';

/**
 * Resolved Backend API Base URL.
 * In production (e.g. Vercel), set VITE_API_URL to your backend host (e.g., https://vidslide-backend.onrender.com).
 * In local development or reverse proxy setups, leave it empty to use relative paths (/api/...).
 */
export const API_BASE_URL = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '');

export const api = axios.create({
  baseURL: API_BASE_URL || undefined,
});

/**
 * Generates an absolute or relative URL for a given API endpoint.
 * Useful for EventSource (SSE), window downloads, and image src tags.
 */
export const getApiUrl = (endpoint: string): string => {
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return `${API_BASE_URL}${cleanEndpoint}`;
};

export default api;
