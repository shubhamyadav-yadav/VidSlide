import React, { useState, useEffect, useCallback, useRef } from 'react';
import { api, getApiUrl } from '../api';
import { Film, X, ChevronLeft, ChevronRight, Download, ImageIcon, ZoomIn } from 'lucide-react';

interface PreviewGalleryProps {
  jobId: string;
}

interface FrameItem {
  name: string;
  time: string;
  url: string;
}

export const PreviewGallery: React.FC<PreviewGalleryProps> = ({ jobId }) => {
  const [frames, setFrames] = useState<FrameItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [columnCount, setColumnCount] = useState<3 | 4 | 5>(4);
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!jobId) return;

    let isMounted = true;
    const fetchFrames = async () => {
      try {
        const response = await api.get(`/api/frames/${jobId}`);
        const frameNames: string[] = response.data?.frames || [];
        const parsedFrames = frameNames.map((name) => {
          let time = name.replace(/^frame_/, '').replace(/\.png$/, '');
          const match = time.match(/(\d+)h(\d+)m(\d+)s/);
          if (match) {
            time = `${match[1].padStart(2, '0')}:${match[2].padStart(2, '0')}:${match[3].padStart(2, '0')}`;
          }
          return {
            name,
            time,
            url: getApiUrl(`/api/frame/${jobId}/${name}`),
          };
        });

        if (isMounted) {
          setFrames(parsedFrames);
        }
      } catch (err) {
        console.error('Failed to load frames:', err);
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    fetchFrames();
    return () => {
      isMounted = false;
    };
  }, [jobId]);

  const openLightbox = (index: number) => {
    setCurrentImageIndex(index);
    setIsModalOpen(true);
  };

  const closeLightbox = useCallback(() => {
    setIsModalOpen(false);
  }, []);

  const nextImage = useCallback((e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setCurrentImageIndex((prev) => (prev === frames.length - 1 ? 0 : prev + 1));
  }, [frames.length]);

  const prevImage = useCallback((e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setCurrentImageIndex((prev) => (prev === 0 ? frames.length - 1 : prev - 1));
  }, [frames.length]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isModalOpen) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        closeLightbox();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        nextImage();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        prevImage();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isModalOpen, closeLightbox, nextImage, prevImage]);

  const getGridColsClass = () => {
    switch (columnCount) {
      case 3: return 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3';
      case 5: return 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5';
      case 4:
      default:
        return 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4';
    }
  };

  return (
    <section className="mb-8" aria-label="Extracted Screenshots">
      {/* Section Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3.5 border-b border-[#281D24] mb-5">
        <div className="flex items-center gap-2.5">
          <Film className="h-4 w-4 text-[#FF0000]" />
          <h2 className="text-base font-bold text-white font-display">
            Extracted Screenshots
          </h2>
          <span className="rounded-full border border-red-500/40 bg-gradient-to-r from-red-600/20 to-orange-600/20 px-3 py-0.5 text-xs font-semibold text-red-200 shadow-[0_0_10px_rgba(255,0,51,0.2)]">
            {frames.length} {frames.length === 1 ? 'frame' : 'frames'} captured
          </span>
        </div>

        {/* Layout controls */}
        {frames.length > 0 && (
          <div className="hidden sm:flex items-center gap-1 text-xs text-[#9194A2]">
            <span className="text-[11.5px] text-[#5D6072] mr-1">Columns</span>
            {([3, 4, 5] as const).map((num) => (
              <button
                key={num}
                onClick={() => setColumnCount(num)}
                className={`h-6 w-6 rounded-[6px] border text-xs font-mono font-semibold transition-all ${
                  columnCount === num
                    ? 'border-red-500 text-red-200 bg-red-950/40 shadow-[0_0_8px_rgba(255,0,51,0.3)]'
                    : 'border-[#281D24] bg-[#161924] text-[#9194A2] hover:text-white'
                }`}
                aria-label={`Show ${num} columns`}
              >
                {num}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Gallery Content */}
      {loading ? (
        <div className="rounded-[18px] border border-[#281D24] bg-[#11131B] p-12 text-center">
          <div className="mx-auto mb-3 h-6 w-6 animate-spin rounded-full border-2 border-red-500 border-t-transparent" />
          <p className="text-xs text-[#9194A2]">Loading extracted slides…</p>
        </div>
      ) : frames.length === 0 ? (
        <div className="rounded-[18px] border border-[#281D24] bg-[#11131B] p-12 text-center">
          <ImageIcon className="mx-auto mb-3 h-8 w-8 text-[#5D6072] opacity-60" />
          <p className="text-sm font-semibold text-white">No slides detected</p>
          <p className="mt-1 text-xs text-[#9194A2] max-w-sm mx-auto">
            Try adjusting sensitivity or using fixed interval mode.
          </p>
        </div>
      ) : (
        <div className="scrollbar-custom max-h-[640px] overflow-y-auto rounded-[18px] border border-[#281D24] bg-[#11131B]/70 p-3 sm:p-4">
          <div className={`grid gap-3 sm:gap-4 ${getGridColsClass()}`}>
            {frames.map((frame, index) => (
              <div
                key={frame.name}
                role="button"
                tabIndex={0}
                onClick={() => openLightbox(index)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    openLightbox(index);
                  }
                }}
                className="group relative flex flex-col rounded-[12px] border border-[#281D24] bg-[#161924] transition-all duration-200 hover:border-red-500/70 hover:shadow-[0_4px_24px_rgba(255,0,51,0.2)] focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:outline-none cursor-pointer overflow-hidden"
                aria-label={`View frame ${index + 1} at timestamp ${frame.time}`}
              >
                {/* Thumbnail Container */}
                <div className="relative aspect-video w-full bg-black/60 overflow-hidden flex items-center justify-center">
                  <img
                    src={frame.url}
                    alt={`Screenshot at ${frame.time}`}
                    loading="lazy"
                    className="h-full w-full object-contain transition-transform duration-200 group-hover:scale-[1.01]"
                  />
                  <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/35 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                    <span className="rounded-[8px] bg-red-600/85 p-2 text-white shadow-lg backdrop-blur-xs">
                      <ZoomIn className="h-4 w-4" />
                    </span>
                  </div>
                </div>

                {/* Metadata Footer */}
                <div className="flex items-center justify-between px-3.5 py-2.5 border-t border-[#281D24] bg-[#11131B]">
                  <span className="font-mono text-xs text-white font-semibold">
                    {frame.time}
                  </span>
                  <span className="font-mono text-[11px] text-[#5D6072] font-medium">
                    #{index + 1}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Lightbox Modal */}
      {isModalOpen && frames.length > 0 && (
        <div
          ref={modalRef}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md p-3 sm:p-5"
          onClick={closeLightbox}
          role="dialog"
          aria-modal="true"
          aria-label="Screenshot Preview"
        >
          <div
            className="relative flex flex-col max-w-6xl w-full max-h-[92vh] rounded-[16px] border border-red-900/40 bg-[#11131B] shadow-[0_0_50px_rgba(255,0,51,0.25)] overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#281D24] bg-[#161924]/80">
              <div className="flex items-center gap-2.5 text-xs">
                <span className="font-mono font-bold text-white">
                  {frames[currentImageIndex].time}
                </span>
                <span className="text-[#5D6072]">•</span>
                <span className="text-red-300 font-medium">
                  Slide {currentImageIndex + 1} of {frames.length}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <a
                  href={frames[currentImageIndex].url}
                  download={frames[currentImageIndex].name}
                  className="inline-flex items-center gap-1.5 rounded-[8px] border border-red-500/40 bg-gradient-to-r from-red-600 to-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110 transition-all shadow-sm"
                  title="Download this slide"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Save Frame</span>
                </a>
                <button
                  onClick={closeLightbox}
                  className="rounded-[6px] p-1.5 text-[#9194A2] hover:bg-[#161924] hover:text-white transition-colors"
                  aria-label="Close preview"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* Modal Image Area */}
            <div className="relative flex flex-1 items-center justify-center bg-black/90 p-2 sm:p-4 min-h-[260px] max-h-[74vh]">
              <img
                src={frames[currentImageIndex].url}
                alt={`Screenshot at ${frames[currentImageIndex].time}`}
                className="max-h-[70vh] max-w-full object-contain rounded-[8px] shadow-2xl"
              />

              {frames.length > 1 && (
                <>
                  <button
                    onClick={prevImage}
                    className="absolute left-3 top-1/2 -translate-y-1/2 rounded-full border border-red-500/40 bg-[#11131B]/90 p-2 text-white hover:bg-red-600 transition-all shadow-lg focus-visible:ring-2 focus-visible:ring-red-500"
                    aria-label="Previous slide"
                  >
                    <ChevronLeft className="h-5 w-5" />
                  </button>
                  <button
                    onClick={nextImage}
                    className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full border border-red-500/40 bg-[#11131B]/90 p-2 text-white hover:bg-red-600 transition-all shadow-lg focus-visible:ring-2 focus-visible:ring-red-500"
                    aria-label="Next slide"
                  >
                    <ChevronRight className="h-5 w-5" />
                  </button>
                </>
              )}
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-between px-4 py-2.5 border-t border-[#1F171D] bg-[#090A0F] text-[11.5px] text-[#5D6072]">
              <div className="flex items-center gap-3">
                <span className="hidden sm:inline">
                  Navigate with <kbd className="rounded border border-[#281D24] bg-[#161924] px-1 font-mono text-[10px] text-red-300">←</kbd> <kbd className="rounded border border-[#281D24] bg-[#161924] px-1 font-mono text-[10px] text-red-300">→</kbd>
                </span>
                <span><kbd className="rounded border border-[#281D24] bg-[#161924] px-1 font-mono text-[10px] text-red-300">Esc</kbd> to close</span>
              </div>
              <span className="font-mono text-red-300 font-semibold">
                #{currentImageIndex + 1}
              </span>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
