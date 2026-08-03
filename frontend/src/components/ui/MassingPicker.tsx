'use client';
import { useState } from 'react';
import { useAppStore } from '@/lib/store';

export default function MassingPicker() {
  const {
    buildingModel,
    generationSpec,
    selectedMassing,
    setSelectedMassing,
    generateBuilding,
    jobStatus,
  } = useAppStore();
  const [error, setError] = useState('');

  if (!buildingModel?.massing_options?.length) return null;

  const appliedMassing = buildingModel.chosen_massing_index ?? 0;
  const hasPendingChoice = selectedMassing !== appliedMassing;
  const isGenerating = jobStatus === 'running';
  const selectedOption = buildingModel.massing_options[selectedMassing];

  const handleConfirm = async () => {
    if (!hasPendingChoice || isGenerating) return;

    const sourceSpec = buildingModel.spec ?? generationSpec;
    if (!sourceSpec) {
      setError('This project is missing its generation settings. Generate it again from Project Setup.');
      return;
    }

    setError('');
    try {
      await generateBuilding(sourceSpec, selectedMassing);
    } catch (e: any) {
      const detail = e.response?.data?.detail;
      const message = Array.isArray(detail)
        ? detail.map((item: any) => `${item.loc?.join('.')}: ${item.msg}`).join(' | ')
        : detail || e.message || 'Massing regeneration failed.';
      setError(message);
    }
  };

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
            disabled={isGenerating}
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
      <p className="mt-3 text-[10px] font-mono text-[var(--text-secondary)]">
        Confirming regenerates the floor plan, structure, facade, and MEP for the selected massing.
      </p>
      <button
        type="button"
        onClick={handleConfirm}
        disabled={!hasPendingChoice || isGenerating}
        className="mt-2 w-full rounded-lg border px-3 py-2 text-xs font-mono transition-all disabled:cursor-not-allowed disabled:opacity-50"
        style={{
          background: hasPendingChoice ? 'rgba(0,229,255,0.08)' : 'var(--surface-2)',
          borderColor: hasPendingChoice ? 'var(--accent-cyan)' : 'var(--border)',
          color: hasPendingChoice ? 'var(--accent-cyan)' : 'var(--text-secondary)',
        }}
      >
        {isGenerating
          ? 'Regenerating complete building...'
          : hasPendingChoice
            ? `Generate ${selectedOption?.label || `option ${selectedMassing + 1}`}`
            : 'Current massing applied'}
      </button>
      {error && (
        <div className="mt-2 text-[10px] font-mono text-red-400" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
