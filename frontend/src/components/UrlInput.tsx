import React, { useState } from 'react';
import axios from 'axios';
import { Youtube, Play, ChevronDown, ChevronUp, Loader2 } from 'lucide-react';

interface UrlInputProps {
  onJobStarted: (jobId: string) => void;
}

export const UrlInput: React.FC<UrlInputProps> = ({ onJobStarted }) => {
  const [url, setUrl] = useState('');
  const [mode, setMode] = useState<'scene' | 'interval'>('scene');
  const [sensitivity, setSensitivity] = useState<'Low' | 'Medium' | 'High'>('Medium');
  const [interval, setInterval] = useState(5);
  const [quality, setQuality] = useState<'1080p' | '720p' | '480p'>('1080p');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url) {
      setError('Please enter a YouTube URL');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await axios.post('/api/process-url', {
        url,
        mode: mode === 'scene' ? 'scene_change' : 'interval',
        sensitivity: sensitivity.toLowerCase(),
        interval,
        quality,
        start_time: startTime || undefined,
        end_time: endTime || undefined,
      });
      onJobStarted(response.data.job_id);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.response?.data?.message || err.message || 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="rounded-lg border border-border-subtle bg-surface-1 p-5">
      <form onSubmit={handleSubmit} className="space-y-5">
        {/* URL Input */}
        <div>
          <label htmlFor="url" className="mb-1.5 block text-xs font-medium text-gray-400">
            YouTube URL
          </label>
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
              <Youtube className="h-4 w-4 text-gray-600" />
            </div>
            <input
              type="url"
              id="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="block w-full rounded-md border border-border bg-surface-0 py-2 pl-9 pr-3 text-sm text-gray-200 placeholder-gray-600 transition-colors focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              placeholder="https://www.youtube.com/watch?v=..."
            />
          </div>
        </div>

        {/* Extraction Mode */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-gray-400">Extraction Mode</label>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setMode('scene')}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                mode === 'scene'
                  ? 'bg-accent text-white'
                  : 'border border-border bg-surface-2 text-gray-400 hover:text-gray-200'
              }`}
            >
              Scene Detection
            </button>
            <button
              type="button"
              onClick={() => setMode('interval')}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                mode === 'interval'
                  ? 'bg-accent text-white'
                  : 'border border-border bg-surface-2 text-gray-400 hover:text-gray-200'
              }`}
            >
              Fixed Interval
            </button>
          </div>
        </div>

        {/* Mode-specific options */}
        {mode === 'scene' ? (
          <div>
            <label className="mb-1.5 block text-xs font-medium text-gray-400">Sensitivity</label>
            <div className="flex gap-3">
              {(['Low', 'Medium', 'High'] as const).map((level) => (
                <label key={level} className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name="sensitivity"
                    value={level}
                    checked={sensitivity === level}
                    onChange={(e) => setSensitivity(e.target.value as typeof sensitivity)}
                    className="h-3.5 w-3.5 border-border-strong bg-surface-0 text-accent focus:ring-accent focus:ring-offset-0"
                  />
                  <span className="text-xs text-gray-300">{level}</span>
                </label>
              ))}
            </div>
          </div>
        ) : (
          <div>
            <label htmlFor="interval" className="mb-1.5 block text-xs font-medium text-gray-400">
              Interval (seconds)
            </label>
            <input
              type="number"
              id="interval"
              min="1"
              value={interval}
              onChange={(e) => setInterval(parseInt(e.target.value) || 1)}
              className="block w-24 rounded-md border border-border bg-surface-0 px-2.5 py-1.5 text-sm text-gray-200 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
        )}

        {/* Quality */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-gray-400">Resolution</label>
          <div className="flex gap-2">
            {[
              { label: '1080p', val: '1080p' as const },
              { label: '720p', val: '720p' as const },
              { label: '480p', val: '480p' as const },
            ].map((opt) => (
              <button
                key={opt.val}
                type="button"
                onClick={() => setQuality(opt.val)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  quality === opt.val
                    ? 'bg-accent/15 text-accent border border-accent/40'
                    : 'border border-border bg-surface-2 text-gray-500 hover:text-gray-300'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Advanced Options */}
        <div className="border-t border-border-subtle pt-3">
          <button
            type="button"
            onClick={() => setIsAdvancedOpen(!isAdvancedOpen)}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            {isAdvancedOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            Advanced options
          </button>

          {isAdvancedOpen && (
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="startTime" className="mb-1 block text-[11px] font-medium text-gray-500">
                  Start time
                </label>
                <input
                  type="text"
                  id="startTime"
                  value={startTime}
                  onChange={(e) => setStartTime(e.target.value)}
                  placeholder="00:00:00"
                  className="block w-full rounded-md border border-border bg-surface-0 px-2.5 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>
              <div>
                <label htmlFor="endTime" className="mb-1 block text-[11px] font-medium text-gray-500">
                  End time
                </label>
                <input
                  type="text"
                  id="endTime"
                  value={endTime}
                  onChange={(e) => setEndTime(e.target.value)}
                  placeholder="Optional"
                  className="block w-full rounded-md border border-border bg-surface-0 px-2.5 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-md border border-red-500/30 bg-red-950/30 px-3 py-2 text-sm text-red-400">
            {error}
          </div>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={isLoading}
          className="flex w-full items-center justify-center gap-2 rounded-md bg-accent py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isLoading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Processing…
            </>
          ) : (
            <>
              <Play className="h-4 w-4" />
              Extract Screenshots
            </>
          )}
        </button>
      </form>
    </div>
  );
};
