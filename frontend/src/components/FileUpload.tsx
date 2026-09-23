import React, { useState, useRef } from 'react';
import axios from 'axios';
import { Upload, CloudUpload, Play, ChevronDown, ChevronUp, Loader2, X } from 'lucide-react';

interface FileUploadProps {
  onJobStarted: (jobId: string) => void;
}

export const FileUpload: React.FC<FileUploadProps> = ({ onJobStarted }) => {
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [mode, setMode] = useState<'scene' | 'interval'>('scene');
  const [sensitivity, setSensitivity] = useState<'Low' | 'Medium' | 'High'>('Medium');
  const [interval, setInterval] = useState(5);
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const validateFile = (selectedFile: File) => {
    const validTypes = ['video/mp4', 'video/quicktime', 'video/x-matroska', 'video/webm'];
    if (!validTypes.includes(selectedFile.type) && !selectedFile.name.match(/\.(mp4|mov|mkv|webm)$/i)) {
      setError('Invalid file type. Accepted: .mp4, .mov, .mkv, .webm');
      return false;
    }
    if (selectedFile.size > 500 * 1024 * 1024) {
      setError('File exceeds 500 MB limit.');
      return false;
    }
    setError(null);
    return true;
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFile = e.dataTransfer.files[0];
      if (validateFile(droppedFile)) {
        setFile(droppedFile);
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selectedFile = e.target.files[0];
      if (validateFile(selectedFile)) {
        setFile(selectedFile);
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError('Please select a video file');
      return;
    }

    setIsUploading(true);
    setError(null);
    setUploadProgress(0);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('mode', mode === 'scene' ? 'scene_change' : 'interval');
    if (mode === 'scene') formData.append('sensitivity', sensitivity.toLowerCase());
    if (mode === 'interval') formData.append('interval', interval.toString());
    if (startTime) formData.append('start_time', startTime);
    if (endTime) formData.append('end_time', endTime);

    try {
      const response = await axios.post('/api/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / (progressEvent.total || 1));
          setUploadProgress(percentCompleted);
        },
      });
      onJobStarted(response.data.job_id);
    } catch (err: any) {
      setError(err.response?.data?.message || err.message || 'Upload failed');
      setIsUploading(false);
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / 1024).toFixed(0)} KB`;
  };

  return (
    <div className="rounded-lg border border-border-subtle bg-surface-1 p-5">
      <form onSubmit={handleSubmit} className="space-y-5">
        {/* Drop Zone */}
        <div
          className={`relative flex flex-col items-center justify-center rounded-lg border border-dashed p-6 transition-colors cursor-pointer ${
            isDragging
              ? 'border-accent bg-accent-ghost'
              : file
              ? 'border-emerald-500/40 bg-emerald-950/10'
              : 'border-border-strong bg-surface-0 hover:border-gray-500'
          }`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click(); }}
          aria-label="Drop a video file here or click to browse"
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            className="hidden"
            accept=".mp4,.mov,.mkv,.webm,video/mp4,video/quicktime,video/x-matroska,video/webm"
          />

          {file ? (
            <div className="text-center">
              <Upload className="mx-auto h-5 w-5 text-emerald-400 mb-2" />
              <p className="text-sm font-medium text-gray-200 truncate max-w-[280px]">{file.name}</p>
              <p className="mt-0.5 text-xs text-gray-500">{formatFileSize(file.size)}</p>
              <button
                type="button"
                className="mt-2 inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
                onClick={(e) => { e.stopPropagation(); setFile(null); }}
              >
                <X className="h-3 w-3" />
                Remove
              </button>
            </div>
          ) : (
            <div className="text-center">
              <CloudUpload className="mx-auto h-6 w-6 text-gray-600 mb-2" />
              <p className="text-sm text-gray-400">
                Drop video here or <span className="text-accent">browse</span>
              </p>
              <p className="mt-1 text-[11px] text-gray-600">
                MP4, MOV, MKV, WebM · Max 500 MB
              </p>
            </div>
          )}
        </div>

        {/* Mode */}
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

        {/* Mode-specific */}
        {mode === 'scene' ? (
          <div>
            <label className="mb-1.5 block text-xs font-medium text-gray-400">Sensitivity</label>
            <div className="flex gap-3">
              {(['Low', 'Medium', 'High'] as const).map((level) => (
                <label key={level} className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name="upload-sensitivity"
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
            <label htmlFor="interval-upload" className="mb-1.5 block text-xs font-medium text-gray-400">
              Interval (seconds)
            </label>
            <input
              type="number"
              id="interval-upload"
              min="1"
              value={interval}
              onChange={(e) => setInterval(parseInt(e.target.value) || 1)}
              className="block w-24 rounded-md border border-border bg-surface-0 px-2.5 py-1.5 text-sm text-gray-200 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
        )}

        {/* Advanced */}
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
                <label htmlFor="startTimeUpload" className="mb-1 block text-[11px] font-medium text-gray-500">
                  Start time
                </label>
                <input
                  type="text"
                  id="startTimeUpload"
                  value={startTime}
                  onChange={(e) => setStartTime(e.target.value)}
                  placeholder="00:00:00"
                  className="block w-full rounded-md border border-border bg-surface-0 px-2.5 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                />
              </div>
              <div>
                <label htmlFor="endTimeUpload" className="mb-1 block text-[11px] font-medium text-gray-500">
                  End time
                </label>
                <input
                  type="text"
                  id="endTimeUpload"
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

        {/* Upload progress */}
        {isUploading && (
          <div>
            <div className="mb-1 flex items-center justify-between text-[11px] text-gray-500">
              <span>Uploading…</span>
              <span>{uploadProgress}%</span>
            </div>
            <div className="h-1 w-full overflow-hidden rounded-full bg-surface-2">
              <div
                className="h-full rounded-full bg-accent transition-all duration-300"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={isUploading || !file}
          className="flex w-full items-center justify-center gap-2 rounded-md bg-accent py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isUploading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Uploading & Processing…
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
