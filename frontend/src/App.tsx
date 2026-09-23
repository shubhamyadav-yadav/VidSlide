import { useState } from 'react';
import { Plus } from 'lucide-react';
import { VideoForm } from './components/VideoForm';
import { InteractivePreview } from './components/InteractivePreview';
import { ProgressPanel } from './components/ProgressPanel';
import { PreviewGallery } from './components/PreviewGallery';
import { DownloadButton } from './components/DownloadButton';

type JobStatus = 'idle' | 'processing' | 'completed' | 'failed';

function App() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [sensitivity, setSensitivity] = useState<'low' | 'medium' | 'high'>('medium');

  const handleJobStarted = (newJobId: string) => {
    setJobId(newJobId);
    setJobStatus('processing');
    setError(null);
  };

  const handleJobCompleted = () => {
    setJobStatus('completed');
  };

  const handleJobFailed = (errorMessage: string) => {
    setJobStatus('failed');
    setError(errorMessage);
  };

  const handleReset = () => {
    setJobId(null);
    setJobStatus('idle');
    setError(null);
  };

  const isWorking = jobStatus === 'processing' || jobStatus === 'completed';

  return (
    <div className="min-h-screen flex flex-col bg-[#090A0F] text-[#F4F5F8] font-sans relative selection:bg-red-500/25 selection:text-white">
      {/* Ambient background light gradients */}
      <div 
        className="pointer-events-none fixed inset-x-0 top-0 h-[500px] z-0 opacity-80"
        style={{
          background: 'radial-gradient(ellipse 80% 60% at 50% -15%, rgba(255, 0, 51, 0.16) 0%, rgba(255, 77, 54, 0.06) 50%, transparent 80%)'
        }}
        aria-hidden="true"
      />
      <div 
        className="pointer-events-none fixed right-[-100px] top-[150px] w-[350px] h-[350px] rounded-full z-0 opacity-30 blur-[100px]"
        style={{ background: 'linear-gradient(135deg, rgba(255, 0, 0, 0.25), rgba(255, 122, 0, 0.15))' }}
        aria-hidden="true"
      />

      {/* Topbar */}
      <header className="sticky top-0 z-30 flex items-center justify-between px-4 sm:px-8 py-3.5 sm:py-4 border-b border-[#281D24] bg-[#090A0F]/80 backdrop-blur-md">
        <div className="flex items-center gap-3">
          {/* Brand Mark with YouTube Red Multi-Gradient and Glow */}
          <div className="w-[32px] h-[32px] rounded-[10px] flex-none bg-gradient-to-br from-[#FF0000] via-[#E62117] to-[#FF4D36] flex items-center justify-center shadow-[0_0_18px_rgba(255,0,51,0.45)] border border-red-400/30">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
              <path d="M8 5v14l11-7L8 5z" fill="white" />
            </svg>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="font-display font-bold text-[18px] tracking-tight bg-gradient-to-r from-white via-red-100 to-red-400 bg-clip-text text-transparent">
              VidSlide
            </span>
            <span className="text-[#5D6072] text-[12px] font-medium hidden sm:inline">
              YouTube Slide Studio
            </span>
          </div>
        </div>

        <nav className="flex items-center gap-3 sm:gap-5">
          {isWorking ? (
            <button
              onClick={handleReset}
              className="inline-flex items-center gap-1.5 rounded-full border border-red-500/40 bg-gradient-to-r from-red-950/40 to-black px-3.5 py-1.5 text-xs font-semibold text-red-200 hover:border-red-400 hover:text-white transition-all shadow-sm"
            >
              <Plus className="h-3.5 w-3.5" />
              New Extraction
            </button>
          ) : (
            <span className="text-xs text-[#9194A2] hover:text-[#F4F5F8] cursor-pointer transition-colors hidden sm:inline">
              How it works
            </span>
          )}

          {/* Engine Online Status Pill with Glowing YouTube Red Dot */}
          <div className="flex items-center gap-2 border border-red-500/30 bg-red-950/30 rounded-full px-3 py-1 text-xs text-red-300 shadow-[0_0_10px_rgba(255,0,51,0.15)]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#FF0000] shadow-[0_0_8px_#FF0000] animate-pulse" />
            <span className="font-medium">Engine online</span>
          </div>
        </nav>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-[1160px] w-full mx-auto px-4 sm:px-8 py-8 sm:py-14 relative z-10">
        {/* Hero Section */}
        <div className="max-w-[660px] mb-8 sm:mb-12">
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-red-950/40 border border-red-500/25 text-[11.5px] font-semibold text-red-300 mb-3 shadow-[0_0_12px_rgba(255,0,51,0.15)]">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
            <span>Smart YouTube Frame Extractor</span>
          </div>
          <h1 className="font-display font-bold text-3xl sm:text-4xl lg:text-[42px] leading-[1.14] tracking-tight mb-3.5">
            <span className="bg-gradient-to-r from-white via-red-100 to-white bg-clip-text text-transparent">Turn any video </span>
            <span className="bg-gradient-to-r from-[#FF0033] via-[#FF3B56] to-[#FFA034] bg-clip-text text-transparent">into clean slides.</span>
          </h1>
          <p className="text-[#9194A2] text-[15px] sm:text-[16px] leading-[1.6]">
            Paste a YouTube link and VidSlide automatically detects every slide change, delivering clean, high-resolution presentation notes ready to export.
          </p>
        </div>

        {/* Error Alert */}
        {error && jobStatus === 'failed' && (
          <div className="mb-6 rounded-[14px] border border-red-500/40 bg-red-950/40 p-4 shadow-[0_0_15px_rgba(255,0,51,0.2)]" role="alert">
            <p className="text-sm font-semibold text-red-400">Processing failed</p>
            <p className="mt-0.5 text-xs text-red-300/80">{error}</p>
          </div>
        )}

        {/* If Idle or Failed: Show 2-Column Workspace (Form + Interactive Preview) */}
        {!isWorking && (
          <div className="grid grid-cols-1 lg:grid-cols-[1.25fr_1fr] gap-6 items-start">
            <VideoForm
              onJobStarted={handleJobStarted}
              sensitivity={sensitivity}
              onSensitivityChange={setSensitivity}
            />
            <InteractivePreview sensitivity={sensitivity} />
          </div>
        )}

        {/* If Processing or Completed: Show Progress and Extracted Results */}
        {isWorking && jobId && (
          <div>
            <ProgressPanel
              jobId={jobId}
              onCompleted={handleJobCompleted}
              onFailed={handleJobFailed}
            />

            {jobStatus === 'completed' && (
              <>
                <PreviewGallery jobId={jobId} />
                <DownloadButton jobId={jobId} />
              </>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
