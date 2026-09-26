import React, { useState, useRef } from 'react';
import { api, ensureBackendUrl } from '../api';

interface VideoFormProps {
  onJobStarted: (jobId: string) => void;
  sensitivity: 'low' | 'medium' | 'high';
  onSensitivityChange: (sens: 'low' | 'medium' | 'high') => void;
}

export const VideoForm: React.FC<VideoFormProps> = ({
  onJobStarted,
  sensitivity,
  onSensitivityChange,
}) => {
  const [activeTab, setActiveTab] = useState<'url' | 'upload'>('url');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<'scene' | 'fixed'>('scene');
  const [interval, setInterval] = useState(5);
  const [quality, setQuality] = useState<'1080p' | '720p' | '480p'>('1080p');
  const [skipDuplicates, setSkipDuplicates] = useState(true);
  const [cropLetterbox, setCropLetterbox] = useState(false);
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const dropped = e.dataTransfer.files[0];
      if (validateFile(dropped)) setFile(dropped);
    }
  };

  const validateFile = (f: File) => {
    if (!f.name.match(/\.(mp4|mov|mkv|webm)$/i)) {
      setError('Supported video formats: .mp4, .mov, .mkv, .webm');
      return false;
    }
    if (f.size > 500 * 1024 * 1024) {
      setError('Maximum video size is 500 MB.');
      return false;
    }
    setError(null);
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    await ensureBackendUrl();

    const timestampRegex = /^\d{1,3}(:\d{1,2}){0,2}(\.\d+)?$/;
    if (startTime.trim() && !timestampRegex.test(startTime.trim())) {
      setError('Start time must be formatted as HH:MM:SS or MM:SS (e.g. 00:01:30)');
      return;
    }
    if (endTime.trim() && !timestampRegex.test(endTime.trim())) {
      setError('End time must be formatted as HH:MM:SS or MM:SS (e.g. 00:15:00)');
      return;
    }

    if (activeTab === 'url') {
      if (!url.trim()) {
        setError('Please enter a YouTube video URL');
        return;
      }
      setIsLoading(true);
      try {
        const response = await api.post('/api/process-url', {
          url: url.trim(),
          mode: mode === 'scene' ? 'scene_change' : 'interval',
          sensitivity,
          interval,
          quality,
          start_time: startTime.trim() || undefined,
          end_time: endTime.trim() || undefined,
        });
        onJobStarted(response.data.job_id);
      } catch (err: any) {
        if (err.message === 'Network Error' || !err.response) {
          setError('Backend engine is unreachable. Please verify the Python OpenCV server is running on your machine or open http://localhost:5173');
        } else {
          setError(err.response?.data?.detail || err.response?.data?.message || err.message || 'Processing failed');
        }
      } finally {
        setIsLoading(false);
      }
    } else {
      if (!file) {
        setError('Please choose or drop a video file');
        return;
      }
      setIsLoading(true);
      const formData = new FormData();
      formData.append('file', file);
      formData.append('mode', mode === 'scene' ? 'scene_change' : 'interval');
      if (mode === 'scene') formData.append('sensitivity', sensitivity);
      if (mode === 'fixed') formData.append('interval', interval.toString());
      if (startTime.trim()) formData.append('start_time', startTime.trim());
      if (endTime.trim()) formData.append('end_time', endTime.trim());

      try {
        const response = await api.post('/api/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        onJobStarted(response.data.job_id);
      } catch (err: any) {
        if (err.message === 'Network Error' || !err.response) {
          setError('Backend engine is unreachable. Please verify the Python OpenCV server is running on your machine or open http://localhost:5173');
        } else {
          setError(err.response?.data?.detail || err.response?.data?.message || err.message || 'Upload failed');
        }
      } finally {
        setIsLoading(false);
      }
    }
  };

  return (
    <div className="bg-[#11131B] border border-[#281D24] rounded-[18px] p-6 sm:p-7 shadow-2xl relative overflow-hidden">
      {/* Decorative top red gradient highlight */}
      <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-[#FF0033] to-transparent opacity-70" />

      <form onSubmit={handleSubmit}>
        {/* Tabs */}
        <div className="relative flex border-b border-[#281D24] mb-6">
          <button
            type="button"
            onClick={() => setActiveTab('url')}
            className={`pb-3.5 mr-7 text-[14.5px] font-semibold transition-colors relative flex items-center gap-2 ${
              activeTab === 'url' ? 'text-white' : 'text-[#9194A2] hover:text-white'
            }`}
          >
            <span>YouTube URL</span>
            {activeTab === 'url' && (
              <span className="absolute bottom-[-1px] left-0 right-0 h-[2.5px] bg-gradient-to-r from-[#FF0000] via-[#FF2A4D] to-[#FFA034] rounded-full shadow-[0_0_12px_rgba(255,0,51,0.7)]" />
            )}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('upload')}
            className={`pb-3.5 mr-7 text-[14.5px] font-semibold transition-colors relative flex items-center gap-2 ${
              activeTab === 'upload' ? 'text-white' : 'text-[#9194A2] hover:text-white'
            }`}
          >
            <span>Upload file</span>
            {activeTab === 'upload' && (
              <span className="absolute bottom-[-1px] left-0 right-0 h-[2.5px] bg-gradient-to-r from-[#FF0000] via-[#FF2A4D] to-[#FFA034] rounded-full shadow-[0_0_12px_rgba(255,0,51,0.7)]" />
            )}
          </button>
        </div>

        {/* Tab 1: Video URL */}
        {activeTab === 'url' && (
          <div className="mb-6">
            <label className="block text-[13.5px] text-[#9194A2] mb-2 font-medium">YouTube Video Link</label>
            <div className="relative">
              {/* YouTube Red Icon */}
              <div className="absolute left-3.5 top-1/2 -translate-y-1/2 flex items-center pointer-events-none text-[#FF0000]">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
                </svg>
              </div>
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://www.youtube.com/watch?v=…"
                className="w-full bg-[#161924] border border-[#281D24] rounded-[12px] text-white text-[14.5px] py-3 pl-11 pr-3.5 outline-none focus:border-red-500 focus:ring-2 focus:ring-red-500/20 placeholder-[#5D6072] transition-all shadow-inner"
              />
            </div>
          </div>
        )}

        {/* Tab 2: Upload File */}
        {activeTab === 'upload' && (
          <div className="mb-6">
            <label className="block text-[13.5px] text-[#9194A2] mb-2 font-medium">Video file</label>
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDrop}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click(); }}
              className={`border-[1.5px] border-dashed rounded-[12px] p-7 text-center cursor-pointer transition-all ${
                file
                  ? 'border-red-500 bg-red-950/20 border-solid shadow-[0_0_15px_rgba(255,0,51,0.15)]'
                  : 'border-[#281D24] hover:border-red-500/80 bg-[#161924]/60'
              }`}
            >
              <svg
                className="mx-auto mb-2.5 text-[#FF2A4D]"
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
              >
                <path d="M12 16V4M12 4l-4 4M12 4l4 4" />
                <path d="M4 16v3a2 2 0 002 2h12a2 2 0 002-2v-3" />
              </svg>
              <p className="text-[14px] text-[#9194A2]">
                {file ? (
                  <>
                    <b className="text-white">{file.name}</b> selected ({((file.size / 1024) / 1024).toFixed(1)} MB)
                  </>
                ) : (
                  <>
                    Drag a video here, or <b className="text-red-400">click to browse</b>
                  </>
                )}
              </p>
            </div>
            <input
              type="file"
              ref={fileInputRef}
              onChange={(e) => {
                if (e.target.files && e.target.files[0]) {
                  if (validateFile(e.target.files[0])) setFile(e.target.files[0]);
                }
              }}
              accept=".mp4,.mov,.mkv,.webm,video/mp4,video/quicktime,video/x-matroska,video/webm"
              className="hidden"
            />
          </div>
        )}

        {/* Extraction Mode Segmented Toggle with Red Gradient */}
        <div className="mb-6">
          <label className="block text-[13.5px] text-[#9194A2] mb-2 font-medium">Extraction mode</label>
          <div className="inline-flex bg-[#161924] border border-[#281D24] rounded-[10px] p-[3px] shadow-inner">
            <button
              type="button"
              onClick={() => setMode('scene')}
              className={`px-4 py-2 text-[13.5px] font-semibold rounded-[8px] transition-all ${
                mode === 'scene'
                  ? 'bg-gradient-to-r from-[#FF0000] to-[#E62117] text-white shadow-md shadow-red-950/60'
                  : 'text-[#9194A2] hover:text-white'
              }`}
            >
              Scene detection
            </button>
            <button
              type="button"
              onClick={() => setMode('fixed')}
              className={`px-4 py-2 text-[13.5px] font-semibold rounded-[8px] transition-all ${
                mode === 'fixed'
                  ? 'bg-gradient-to-r from-[#FF0000] to-[#E62117] text-white shadow-md shadow-red-950/60'
                  : 'text-[#9194A2] hover:text-white'
              }`}
            >
              Fixed interval
            </button>
          </div>
        </div>

        {/* Sensitivity Pills */}
        {mode === 'scene' && (
          <div className="mb-6">
            <label className="block text-[13.5px] text-[#9194A2] mb-2 font-medium">Sensitivity</label>
            <div className="flex gap-2 flex-wrap">
              {(['low', 'medium', 'high'] as const).map((lvl) => (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => onSensitivityChange(lvl)}
                  className={`px-4 py-2 rounded-[8px] text-[13.5px] font-semibold border transition-all ${
                    sensitivity === lvl
                      ? 'border-red-500 bg-gradient-to-r from-red-600/25 to-rose-600/25 text-red-200 shadow-[0_0_12px_rgba(255,0,51,0.25)]'
                      : 'border-[#281D24] bg-[#161924] text-[#9194A2] hover:text-white'
                  }`}
                >
                  {lvl.charAt(0).toUpperCase() + lvl.slice(1)}
                </button>
              ))}
            </div>
            <p className="text-[12.5px] text-[#5D6072] mt-2.5">
              Higher sensitivity catches subtler slide transitions, text changes, and bullet-point builds.
            </p>
          </div>
        )}

        {/* Interval input */}
        {mode === 'fixed' && (
          <div className="mb-6">
            <label className="block text-[13.5px] text-[#9194A2] mb-2 font-medium">Capture every</label>
            <div className="flex items-center gap-2.5">
              <input
                type="number"
                min="1"
                value={interval}
                onChange={(e) => setInterval(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-20 bg-[#161924] border border-[#281D24] rounded-[8px] text-white text-[13.5px] px-2.5 py-2 outline-none focus:border-red-500"
              />
              <span className="text-[12.5px] text-[#5D6072]">seconds</span>
            </div>
          </div>
        )}

        {/* Resolution Pills */}
        <div className="mb-6">
          <label className="block text-[13.5px] text-[#9194A2] mb-2 font-medium">Resolution</label>
          <div className="flex gap-2 flex-wrap">
            {(['1080p', '720p', '480p'] as const).map((res) => (
              <button
                key={res}
                type="button"
                onClick={() => setQuality(res)}
                className={`px-4 py-2 rounded-[8px] text-[13.5px] font-semibold border transition-all ${
                  quality === res
                    ? 'border-red-500 bg-gradient-to-r from-red-600/25 to-rose-600/25 text-red-200 shadow-[0_0_12px_rgba(255,0,51,0.25)]'
                    : 'border-[#281D24] bg-[#161924] text-[#9194A2] hover:text-white'
                }`}
              >
                {res}
              </button>
            ))}
          </div>
        </div>

        {/* Advanced Options Accordion */}
        <div className="pt-1 mb-6">
          <button
            type="button"
            onClick={() => setIsAdvancedOpen(!isAdvancedOpen)}
            className="inline-flex items-center gap-2 text-[14px] text-[#9194A2] hover:text-white transition-colors"
          >
            <svg
              className={`transition-transform duration-200 ${isAdvancedOpen ? 'rotate-180 text-red-400' : ''}`}
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
            Advanced options
          </button>

          {isAdvancedOpen && (
            <div className="mt-4 pt-3.5 border-t border-[#1F171D] space-y-4">
              {/* Skip near-duplicate */}
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-[13.5px] text-[#9194A2]">Skip near-duplicate frames</p>
                  <p className="text-[12px] text-[#5D6072]">Won't export two slides that look nearly identical</p>
                </div>
                <div
                  onClick={() => setSkipDuplicates(!skipDuplicates)}
                  className={`switch ${skipDuplicates ? 'on' : ''}`}
                  role="switch"
                  aria-checked={skipDuplicates}
                  tabIndex={0}
                />
              </div>

              {/* Crop letterbox */}
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-[13.5px] text-[#9194A2]">Crop letterbox bars</p>
                  <p className="text-[12px] text-[#5D6072]">Removes black bars around video edges</p>
                </div>
                <div
                  onClick={() => setCropLetterbox(!cropLetterbox)}
                  className={`switch ${cropLetterbox ? 'on' : ''}`}
                  role="switch"
                  aria-checked={cropLetterbox}
                  tabIndex={0}
                />
              </div>

              {/* Start & End Time Range */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                <div>
                  <label className="block text-[11.5px] text-[#5D6072] mb-1">Start Time (HH:MM:SS)</label>
                  <input
                    type="text"
                    value={startTime}
                    onChange={(e) => setStartTime(e.target.value)}
                    placeholder="00:00:00"
                    className="w-full bg-[#161924] border border-[#281D24] rounded-[8px] text-white text-[13.5px] px-2.5 py-1.5 outline-none focus:border-red-500"
                  />
                </div>
                <div>
                  <label className="block text-[11.5px] text-[#5D6072] mb-1">End Time (HH:MM:SS)</label>
                  <input
                    type="text"
                    value={endTime}
                    onChange={(e) => setEndTime(e.target.value)}
                    placeholder="Optional"
                    className="w-full bg-[#161924] border border-[#281D24] rounded-[8px] text-white text-[13.5px] px-2.5 py-1.5 outline-none focus:border-red-500"
                  />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Error Alert */}
        {error && (
          <div className="mb-4 p-3 rounded-[10px] bg-red-950/50 border border-red-500/40 text-red-300 text-[13px] shadow-[0_0_12px_rgba(255,0,51,0.2)]">
            {error}
          </div>
        )}

        {/* CTA Button with YouTube Red Multi-Gradient and Glow */}
        <button
          type="submit"
          disabled={isLoading}
          className="w-full bg-gradient-to-r from-[#FF0000] via-[#E62117] to-[#FF4D36] hover:from-[#FF1E27] hover:to-[#FF5A43] text-white font-semibold text-[15.5px] py-3.5 px-5 rounded-[12px] flex items-center justify-center gap-2.5 transition-all shadow-[0_4px_24px_rgba(255,0,51,0.4)] hover:shadow-[0_6px_32px_rgba(255,0,51,0.6)] hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer border border-red-400/20"
        >
          {isLoading ? (
            <>
              <div className="w-4 h-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
              <span>Extracting screenshots…</span>
            </>
          ) : (
            <>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5v14l11-7L8 5z" />
              </svg>
              <span>Extract screenshots</span>
            </>
          )}
        </button>
      </form>
    </div>
  );
};
