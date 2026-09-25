import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { getApiUrl } from '../api';

interface ProgressPanelProps {
  jobId: string;
  onCompleted: () => void;
  onFailed: (error: string) => void;
}

interface ProgressData {
  status: 'idle' | 'downloading' | 'extracting' | 'packaging' | 'completed' | 'failed';
  progress: number;
  frames_found: number;
  current_timestamp: string;
  message: string;
}

export const ProgressPanel: React.FC<ProgressPanelProps> = ({ jobId, onCompleted, onFailed }) => {
  const [data, setData] = useState<ProgressData>({
    status: 'idle',
    progress: 0,
    frames_found: 0,
    current_timestamp: '00:00:00',
    message: 'Starting job...',
  });

  useEffect(() => {
    if (!jobId) return;

    let isCompletedOrFailed = false;
    const eventSource = new EventSource(getApiUrl(`/api/progress/${jobId}`));

    eventSource.onmessage = (event) => {
      try {
        const parsedData: ProgressData = JSON.parse(event.data);
        setData(parsedData);

        if (parsedData.status === 'completed') {
          isCompletedOrFailed = true;
          eventSource.close();
          onCompleted();
        } else if (parsedData.status === 'failed') {
          isCompletedOrFailed = true;
          eventSource.close();
          onFailed(parsedData.message || 'Job failed');
        }
      } catch (err) {
        console.error('Error parsing SSE data:', err);
      }
    };

    eventSource.onerror = (err) => {
      console.warn('EventSource reconnecting/error:', err);
    };

    // Polling fallback to guarantee state synchronization even if SSE is buffered
    const pollTimer = setInterval(async () => {
      if (isCompletedOrFailed) {
        clearInterval(pollTimer);
        return;
      }
      try {
        const res = await fetch(getApiUrl(`/api/frames/${jobId}`));
        if (res.ok) {
          const frameData = await res.json();
          if (frameData.status === 'completed') {
            isCompletedOrFailed = true;
            clearInterval(pollTimer);
            eventSource.close();
            setData(prev => ({
              ...prev,
              status: 'completed',
              progress: 100,
              frames_found: frameData.count || frameData.frames?.length || prev.frames_found,
              message: `Extracted ${frameData.count || frameData.frames?.length || 0} slides successfully!`
            }));
            onCompleted();
          } else if (frameData.status === 'failed') {
            isCompletedOrFailed = true;
            clearInterval(pollTimer);
            eventSource.close();
            onFailed(frameData.message || 'Job failed');
          }
        }
      } catch {
        // ignore polling network errors
      }
    }, 1500);

    return () => {
      clearInterval(pollTimer);
      eventSource.close();
    };
  }, [jobId, onCompleted, onFailed]);

  const getStatusBadge = () => {
    switch (data.status) {
      case 'completed':
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/15 px-3 py-0.5 text-xs font-semibold text-emerald-300 shadow-[0_0_10px_rgba(16,185,129,0.2)]">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Completed
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-red-500/40 bg-red-500/15 px-3 py-0.5 text-xs font-semibold text-red-300 shadow-[0_0_10px_rgba(255,0,51,0.2)]">
            <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
            Failed
          </span>
        );
      case 'downloading':
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-red-500/40 bg-red-500/10 px-3 py-0.5 text-xs font-semibold text-red-300 shadow-[0_0_10px_rgba(255,0,51,0.2)]">
            <Loader2 className="h-3 w-3 animate-spin text-[#FF0000]" />
            Downloading video
          </span>
        );
      case 'extracting':
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-red-500/40 bg-gradient-to-r from-red-600/20 to-orange-600/20 px-3 py-0.5 text-xs font-semibold text-red-200 shadow-[0_0_12px_rgba(255,0,51,0.3)]">
            <Loader2 className="h-3 w-3 animate-spin text-[#FF2A4D]" />
            Extracting slides
          </span>
        );
      case 'packaging':
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/15 px-3 py-0.5 text-xs font-semibold text-amber-300 shadow-[0_0_10px_rgba(245,158,11,0.2)]">
            <Loader2 className="h-3 w-3 animate-spin text-amber-400" />
            Packaging ZIP
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[#281D24] bg-[#161924] px-3 py-0.5 text-xs font-medium text-[#9194A2]">
            <Loader2 className="h-3 w-3 animate-spin" />
            Initializing
          </span>
        );
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'completed': return 'Extraction completed successfully';
      case 'failed': return 'Extraction failed';
      case 'downloading': return 'Downloading video stream from YouTube';
      case 'extracting': return 'Detecting scene transitions & capturing slides';
      case 'packaging': return 'Creating high-resolution ZIP archive';
      default: return 'Initializing extraction engine';
    }
  };

  const percentValue = Math.min(100, Math.max(0, Math.round(data.progress)));

  return (
    <div className="bg-[#11131B] border border-[#281D24] rounded-[18px] p-6 sm:p-7 shadow-2xl mb-8 relative overflow-hidden">
      {/* Decorative top red gradient highlight */}
      <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-[#FF0033] to-transparent opacity-70" />

      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-[#281D24]">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-bold text-white font-display">Processing Job</h2>
          <span className="text-xs text-[#5D6072] font-mono">#{jobId.slice(0, 8)}</span>
        </div>
        {getStatusBadge()}
      </div>

      {/* Activity Details */}
      <div className="pt-4 pb-2">
        <div className="flex items-center justify-between text-[13.5px] text-[#9194A2] mb-2 font-medium">
          <span className="truncate pr-2 text-white">
            {data.message || getStatusText(data.status)}
          </span>
        </div>

        {/* Multi-Gradient Progress Bar */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-[11.5px] font-medium text-[#9194A2]">
            <span>Overall Progress</span>
            <span className="font-mono text-red-300 font-semibold">{percentValue}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-[#161924] p-[1px]">
            <div
              className={`h-full rounded-full transition-all duration-300 ease-out shadow-sm ${
                data.status === 'completed'
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-400'
                  : data.status === 'failed'
                  ? 'bg-red-500'
                  : 'bg-gradient-to-r from-[#FF0000] via-[#FF2A4D] to-[#FFA034] shadow-[0_0_12px_rgba(255,0,51,0.6)]'
              }`}
              style={{ width: `${percentValue}%` }}
              role="progressbar"
              aria-valuenow={percentValue}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
        </div>
      </div>

      {/* Metrics Footer */}
      <div className="grid grid-cols-3 gap-3 pt-4 mt-3 border-t border-[#1F171D]">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-[#5D6072] mb-0.5">
            Frames Found
          </p>
          <p className="text-xl font-bold bg-gradient-to-r from-white to-red-200 bg-clip-text text-transparent font-mono">
            {data.frames_found}
          </p>
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-[#5D6072] mb-0.5">
            Current Time
          </p>
          <p className="text-xl font-bold text-white font-mono">
            {data.status === 'completed' ? 'Done' : data.current_timestamp || '00:00:00'}
          </p>
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-[#5D6072] mb-0.5">
            Status
          </p>
          <p className="text-[14px] font-semibold text-red-300 mt-1">
            {data.status.charAt(0).toUpperCase() + data.status.slice(1)}
          </p>
        </div>
      </div>
    </div>
  );
};
