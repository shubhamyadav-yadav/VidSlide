import React from 'react';

interface InteractivePreviewProps {
  sensitivity: 'low' | 'medium' | 'high';
}

export const InteractivePreview: React.FC<InteractivePreviewProps> = ({ sensitivity }) => {
  // Count scenes based on sensitivity level
  const sceneCount = sensitivity === 'low' ? 4 : sensitivity === 'medium' ? 7 : 11;

  // Timeline marks positions (%)
  const markPositions = [
    6, 16, 24, 33, 44, 55, 63, 72, 80, 88, 95
  ];

  return (
    <div className="bg-[#11131B] border border-[#281D24] rounded-[18px] p-6 sm:p-7 shadow-2xl lg:sticky lg:top-24 relative overflow-hidden">
      {/* Decorative top red gradient highlight */}
      <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-[#FF0033] to-transparent opacity-70" />

      {/* Label and Badge */}
      <div className="flex items-center justify-between text-[13px] text-[#9194A2] mb-5">
        <span className="font-semibold text-white">Live Slide Detection</span>
        <span className="text-[12.5px] font-semibold text-red-300 bg-gradient-to-r from-red-500/20 via-rose-500/20 to-orange-500/20 border border-red-500/35 rounded-full px-3 py-0.5 shadow-[0_0_12px_rgba(255,0,51,0.25)]">
          {sceneCount} scenes detected
        </span>
      </div>

      {/* Filmstrip with stylized preview frames */}
      <div className="flex gap-2.5 overflow-x-auto pb-2.5 mb-4 scrollbar-custom">
        {/* Frame 1: Title card with red chip & bars */}
        <div className="flex-none w-[90px] h-[62px] rounded-[8px] bg-[#161924] border border-[#281D24] p-2 flex flex-col justify-center gap-1.5 hover:border-red-500/50 transition-colors">
          <div className="w-4 h-4 rounded-[4px] bg-gradient-to-tr from-[#FF0000] to-[#FF4D36] shadow-[0_0_8px_rgba(255,0,51,0.5)]" />
          <div className="h-1 rounded-[2px] w-[70%] bg-gradient-to-r from-red-400 to-rose-400 opacity-70" />
          <div className="h-1 rounded-[2px] w-[45%] bg-[#281D24]" />
        </div>

        {/* Frame 2: Bar chart slide with red/coral gradient */}
        <div className="flex-none w-[90px] h-[62px] rounded-[8px] bg-[#161924] border border-[#281D24] p-2 flex flex-col justify-end hover:border-red-500/50 transition-colors">
          <div className="flex items-end gap-[3px] h-6">
            <span className="w-1.5 bg-gradient-to-t from-[#FF0000] to-[#FFA034] rounded-[1px] h-[60%]" />
            <span className="w-1.5 bg-gradient-to-t from-[#FF0000] to-[#FFA034] rounded-[1px] h-[95%]" />
            <span className="w-1.5 bg-gradient-to-t from-[#FF0000] to-[#FFA034] rounded-[1px] h-[40%]" />
            <span className="w-1.5 bg-gradient-to-t from-[#FF0000] to-[#FFA034] rounded-[1px] h-[75%]" />
          </div>
        </div>

        {/* Frame 3: Content list */}
        <div className="flex-none w-[90px] h-[62px] rounded-[8px] bg-[#161924] border border-[#281D24] p-2 flex flex-col justify-center gap-1.5 hover:border-red-500/50 transition-colors">
          <div className="h-1 rounded-[2px] w-[70%] bg-gradient-to-r from-red-400 to-amber-400 opacity-80" />
          <div className="h-1 rounded-[2px] w-[45%] bg-[#281D24]" />
          <div className="h-1 rounded-[2px] w-[60%] bg-[#281D24]" />
        </div>

        {/* Frame 4: Red accent chip */}
        <div className="flex-none w-[90px] h-[62px] rounded-[8px] bg-[#161924] border border-[#281D24] p-2 flex flex-col justify-center gap-1.5 hover:border-red-500/50 transition-colors">
          <div className="w-4 h-4 rounded-[4px] bg-gradient-to-tr from-[#FF0033] to-[#FF6536] shadow-[0_0_8px_rgba(255,0,51,0.5)]" />
          <div className="h-1 rounded-[2px] w-[70%] bg-[#5D6072]" />
        </div>

        {/* Frame 5: Analytics comparison */}
        <div className="flex-none w-[90px] h-[62px] rounded-[8px] bg-[#161924] border border-[#281D24] p-2 flex flex-col justify-end hover:border-red-500/50 transition-colors">
          <div className="flex items-end gap-[3px] h-6">
            <span className="w-1.5 bg-gradient-to-t from-[#E62117] to-[#FF453A] rounded-[1px] h-[80%]" />
            <span className="w-1.5 bg-gradient-to-t from-[#E62117] to-[#FF453A] rounded-[1px] h-[35%]" />
            <span className="w-1.5 bg-gradient-to-t from-[#E62117] to-[#FF453A] rounded-[1px] h-[65%]" />
          </div>
        </div>

        {/* Frame 6: Summary notes */}
        <div className="flex-none w-[90px] h-[62px] rounded-[8px] bg-[#161924] border border-[#281D24] p-2 flex flex-col justify-center gap-1.5 hover:border-red-500/50 transition-colors">
          <div className="h-1 rounded-[2px] w-[70%] bg-gradient-to-r from-red-400 to-rose-400 opacity-70" />
          <div className="h-1 rounded-[2px] w-[70%] bg-[#281D24]" />
        </div>
      </div>

      {/* Timeline track with glowing red gradient ticks */}
      <div className="relative h-[30px] mb-1.5">
        <div className="absolute top-[14px] left-0 right-0 h-[2px] bg-[#281D24] rounded-full" />
        {markPositions.map((pos, idx) => {
          const isVisible = idx < sceneCount;
          return (
            <div
              key={pos}
              className={`absolute top-[8px] w-[2.5px] h-[14px] rounded-full transition-all duration-200 ${
                isVisible
                  ? 'bg-gradient-to-b from-[#FFA034] via-[#FF2A4D] to-[#FF0000] opacity-100 scale-y-100 shadow-[0_0_8px_rgba(255,0,51,0.8)]'
                  : 'bg-[#5D6072] opacity-0 scale-y-50'
              }`}
              style={{ left: `${pos}%` }}
            />
          );
        })}
      </div>

      {/* Time labels */}
      <div className="flex justify-between text-[11.5px] text-[#5D6072] mb-5 font-mono">
        <span>0:00</span>
        <span>12:34</span>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-2 text-[12.5px] text-[#9194A2] pt-4 border-t border-[#1F171D]">
        <span className="w-[8px] h-[8px] rounded-full bg-[#FF0000] shadow-[0_0_8px_#FF0000]" />
        <span>Detected slide transition</span>
      </div>
    </div>
  );
};
