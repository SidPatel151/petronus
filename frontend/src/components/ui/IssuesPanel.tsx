'use client';
import { useAppStore } from '@/lib/store';

const SEV_COLOR: Record<string, string> = {
  error: 'var(--accent-red)',
  warning: 'var(--accent-amber)',
  info: 'var(--accent-cyan)',
};

const SEV_BG: Record<string, string> = {
  error: 'rgba(239,68,68,0.08)',
  warning: 'rgba(255,179,0,0.08)',
  info: 'rgba(0,229,255,0.08)',
};

const SEV_ICON: Record<string, string> = {
  error: 'x',
  warning: '!',
  info: 'i',
};

export default function IssuesPanel() {
  const { buildingModel, setSelectedIssue, selectedIssueId } = useAppStore();

  if (!buildingModel) return (
    <div className="p-4 text-xs text-[var(--text-secondary)] font-mono italic">
      No model generated yet
    </div>
  );

  const issues = buildingModel.issues || [];
  const errors = issues.filter((i: any) => i.severity === 'error');
  const warnings = issues.filter((i: any) => i.severity === 'warning');
  const infos = issues.filter((i: any) => i.severity === 'info');

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Summary */}
      <div className="panel-section flex gap-3">
        <div className="flex-1 bg-[var(--surface-3)] rounded-lg p-2 text-center">
          <div className="text-lg font-display font-bold text-[var(--accent-red)]">{errors.length}</div>
          <div className="text-[10px] font-mono text-[var(--text-secondary)]">Errors</div>
        </div>
        <div className="flex-1 bg-[var(--surface-3)] rounded-lg p-2 text-center">
          <div className="text-lg font-display font-bold text-[var(--accent-amber)]">{warnings.length}</div>
          <div className="text-[10px] font-mono text-[var(--text-secondary)]">Warnings</div>
        </div>
        <div className="flex-1 bg-[var(--surface-3)] rounded-lg p-2 text-center">
          <div className="text-lg font-display font-bold text-[var(--accent-cyan)]">{infos.length}</div>
          <div className="text-[10px] font-mono text-[var(--text-secondary)]">Info</div>
        </div>
      </div>

      {/* Issue list */}
      <div className="flex-1 overflow-y-auto">
        {issues.length === 0 ? (
          <div className="p-4 text-center">
            <div className="text-[var(--accent-green)] text-2xl mb-2">✓</div>
            <div className="text-xs font-mono text-[var(--text-secondary)]">No preflight findings reported</div>
            <div className="text-[9px] font-mono text-[var(--text-secondary)] opacity-60 mt-1">
              This is not a permit approval or professional compliance determination.
            </div>
          </div>
        ) : (
          <div className="space-y-2 p-3">
            {issues.map((issue: any) => (
              <button
                key={issue.id}
                onClick={() => setSelectedIssue(issue.id === selectedIssueId ? null : issue.id)}
                className="w-full text-left rounded-lg p-3 transition-all border"
                style={{
                  background: selectedIssueId === issue.id ? (SEV_BG[issue.severity] || SEV_BG.info) : 'var(--surface-2)',
                  borderColor: selectedIssueId === issue.id ? (SEV_COLOR[issue.severity] || SEV_COLOR.info) : 'var(--border)',
                }}
              >
                <div className="flex items-start gap-2">
                  <span className="text-xs font-mono font-bold mt-0.5" style={{ color: SEV_COLOR[issue.severity] || SEV_COLOR.info }}>
                    {SEV_ICON[issue.severity] || SEV_ICON.info}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-mono text-[var(--text-primary)] leading-relaxed">
                      {issue.message}
                    </div>
                    {selectedIssueId === issue.id && (
                      <div className="mt-2 space-y-1.5 animate-fade-in">
                        <div className="text-[10px] font-mono text-[var(--accent-green)]">
                          Fix: {issue.fix_suggestion}
                        </div>
                        {issue.citation && (
                          <div className="text-[10px] font-mono text-[var(--text-secondary)] italic">
                            {issue.citation}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Generation log */}
      <div className="panel-section">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider mb-2">
          Generation Log
        </div>
        <div className="bg-[var(--surface-0)] rounded-lg p-2 max-h-32 overflow-y-auto font-mono text-[10px] text-[var(--text-secondary)] space-y-0.5">
          {buildingModel.generation_log?.map((line: string, i: number) => (
            <div key={i} className="flex gap-2">
              <span className="text-[var(--accent-cyan)] opacity-40 flex-shrink-0">›</span>
              <span>{line}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
