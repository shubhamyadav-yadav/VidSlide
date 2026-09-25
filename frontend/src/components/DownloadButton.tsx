import React, { useState } from 'react';
import { Download, Check, FileArchive } from 'lucide-react';
import { getApiUrl, getClientJob, buildClientZipBlob } from '../api';

interface DownloadButtonProps {
  jobId: string;
}

export const DownloadButton: React.FC<DownloadButtonProps> = ({ jobId }) => {
  const [downloadStarted, setDownloadStarted] = useState(false);

  const handleDownload = () => {
    const clientJob = getClientJob(jobId);
    if (clientJob && clientJob.frames && clientJob.frames.length > 0) {
      const blob = buildClientZipBlob(clientJob.frames);
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = blobUrl;
      link.setAttribute('download', `vidslide_slides_${jobId.slice(-6)}.zip`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
    } else {
      const targetId = clientJob?.serverJobId || jobId;
      const link = document.createElement('a');
      link.href = getApiUrl(`/api/download/${targetId}`);
      link.setAttribute('download', '');
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }

    setDownloadStarted(true);
    setTimeout(() => {
      setDownloadStarted(false);
    }, 3000);
  };

  return (
    <div className="mt-6 mb-16 flex flex-col sm:flex-row items-center justify-between gap-4 rounded-[18px] border border-[#281D24] bg-[#11131B] p-5 sm:p-6 shadow-2xl relative overflow-hidden">
      {/* Decorative top red gradient highlight */}
      <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-[#FF0033] to-transparent opacity-70" />

      <div className="flex items-center gap-3.5">
        <div className="flex h-11 w-11 items-center justify-center rounded-[12px] border border-red-500/30 bg-red-950/30 text-[#FF0000] shadow-[0_0_12px_rgba(255,0,51,0.2)]">
          <FileArchive className="h-5 w-5" />
        </div>
        <div>
          <p className="text-[14.5px] font-bold text-white font-display">
            Export Slide Archive
          </p>
          <p className="text-[12px] text-[#9194A2]">
            ZIP archive containing all full-resolution captured PNG slides
          </p>
        </div>
      </div>

      <button
        onClick={handleDownload}
        disabled={downloadStarted}
        className={`inline-flex items-center justify-center gap-2 rounded-[12px] px-6 py-3.5 text-[14px] font-bold transition-all w-full sm:w-auto shadow-lg cursor-pointer ${
          downloadStarted
            ? 'bg-emerald-600 text-white shadow-emerald-950/50 cursor-default'
            : 'bg-gradient-to-r from-[#FF0000] via-[#E62117] to-[#FF4D36] hover:from-[#FF1E27] hover:to-[#FF5A43] text-white shadow-[0_4px_24px_rgba(255,0,51,0.4)] hover:shadow-[0_6px_32px_rgba(255,0,51,0.6)] hover:-translate-y-0.5 border border-red-400/20'
        }`}
      >
        {downloadStarted ? (
          <>
            <Check className="h-4 w-4" />
            <span>Download Started</span>
          </>
        ) : (
          <>
            <Download className="h-4 w-4" />
            <span>Download All Slides (.zip)</span>
          </>
        )}
      </button>
    </div>
  );
};
