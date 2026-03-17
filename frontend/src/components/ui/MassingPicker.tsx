'use client';
import { useAppStore } from '@/lib/store';

export default function MassingPicker() {
  const { buildingModel, selectedMassing, setSelectedMassing } = useAppStore();

  if (!buildingModel?.massing_options?.length) return null;

  return (
    <div className="panel-section">
      <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider mb-3">
        Massing Options
      </div>
      <div className="space-y-2">
        {buildingModel.massing_options.map((opt: any, i: number) => (
          <button
            key={i}
            onClick={() => setSelectedMassing(i)}
            className="w-full text-left rounded-lg p-3 transition-all border"
            style={{
              background: selectedMassing === i ? 'rgba(0,229,255,0.08)' : 'var(--surface-2)',
              borderColor: selectedMassing === i ? 'var(--accent-cyan)' : 'var(--border)',
            }}
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs font-mono text-[var(--text-primary)]">
                  <span style={{ color: 'var(--accent-cyan)' }}>{opt.label}</span> — {opt.name}
                </div>
                <div className="text-[10px] font-mono text-[var(--text-secondary)] mt-0.5">
                  {opt.description}
                </div>
              </div>
              <div className="text-right ml-3 flex-shrink-0">
                <div className="text-xs font-mono" style={{ color: 'var(--accent-green)' }}>
                  {opt.score?.overall ? `${(opt.score.overall * 100).toFixed(0)}` : '--'}
                </div>
                <div className="text-[10px] text-[var(--text-secondary)] font-mono">score</div>
              </div>
            </div>
            <div className="mt-2 flex gap-3 text-[10px] font-mono text-[var(--text-secondary)]">
              <span>{(opt.total_area_m2 * 10.764).toFixed(0)} sqft</span>
              <span>{opt.stories} stories</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
