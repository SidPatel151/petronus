'use client';
import { useState } from 'react';
import { useAppStore } from '@/lib/store';
import api from '@/lib/api';

const PRIORITIES = ['cost', 'speed', 'daylight'];
const STRUCTURAL = ['wood', 'steel', 'concrete'];
const HVAC_OPTS = ['mini_split', 'rooftop'];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">
        {label}
      </label>
      {children}
    </div>
  );
}

// Uncontrolled number input — avoids the "can't delete" bug
function NumInput({ value, onChange, placeholder, min, max, step }: {
  value: number | undefined;
  onChange: (v: number | undefined) => void;
  placeholder?: string;
  min?: number; max?: number; step?: number;
}) {
  return (
    <input
      type="number"
      defaultValue={value ?? ''}
      min={min} max={max} step={step}
      placeholder={placeholder}
      onChange={(e) => {
        const v = e.target.value;
        onChange(v === '' ? undefined : parseFloat(v));
      }}
      className="w-full bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)] transition-colors font-mono"
    />
  );
}

function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)] transition-colors font-mono"
    >
      {options.map((o) => (
        <option key={o} value={o}>{o.replace(/_/g, ' ')}</option>
      ))}
    </select>
  );
}

export default function ProjectWizard() {
  const {
    selectedSite, siteContext, neighborConstraints,
    spec, updateSpec, setBuildingModel
  } = useAppStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const canGenerate = !!selectedSite;
  const feasibility = neighborConstraints?.feasibility;
  const hasBlockingIssues = feasibility?.issues?.length > 0;

  const handleGenerate = async () => {
    if (!selectedSite) return;
    setLoading(true);
    setError('');

    const fullSpec = {
      region_country: 'US',
      region_state: 'CA',
      occupancy: 'MultiFamilyResidential',
      permit_set: false,
      stories: spec.stories || 2,
      floor_to_floor_height_ft: spec.floor_to_floor_height_ft || 10.0,
      structural_system: spec.structural_system || 'wood',
      hvac_preference: spec.hvac_preference || 'mini_split',
      parking_strategy: spec.parking_strategy || 'ignore',
      priority: spec.priority || 'cost',
      target_gross_area_sqft: spec.target_gross_area_sqft || 8000,
      unit_count: spec.unit_count || null,
      site: {
        latlon: { lat: selectedSite.lat, lon: selectedSite.lon },
        address: null,
        parcel_polygon: siteContext?.parcel_polygon || null,
      },
    };

    try {
      const result = await api.quickGenerate(fullSpec);
      if (result.result) {
        setBuildingModel(result.result);
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? detail.map((d: any) => `${d.loc?.join('.')}: ${d.msg}`).join(' | ')
        : detail || e.message || 'Generation failed';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Header */}
      <div className="panel-section">
        <div className="font-display text-lg font-semibold text-[var(--text-primary)]">Project Setup</div>
        <div className="text-xs text-[var(--text-secondary)] mt-0.5 font-mono">
          California · Multi-family Residential · ≤3 Stories
        </div>
      </div>

      {/* Site info */}
      <div className="panel-section space-y-3">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">Selected Site</div>
        {selectedSite ? (
          <div className="space-y-2">
            <div className="text-xs font-mono text-[var(--accent-cyan)]">
              {selectedSite.lat.toFixed(5)}, {selectedSite.lon.toFixed(5)}
            </div>
            {siteContext && (
              <div className="grid grid-cols-2 gap-2">
                {[
                  { label: 'Area', val: `${siteContext.area_sqft?.toFixed(0)} sqft` },
                  { label: 'Flood Zone', val: siteContext.flood_zone || 'X' },
                  { label: 'Seismic', val: `SDC ${siteContext.seismic_category}` + (siteContext.hazard_detail?.seismic?.source === 'USGS ASCE 7-22' ? ' ✓' : ' ~') },
                  { label: 'Wind', val: `${siteContext.wind_speed_mph} mph` + (siteContext.hazard_detail?.wind?.source === 'ATC ASCE 7-22' ? ' ✓' : ' ~') },
                ].map(({ label, val }) => (
                  <div key={label} className="bg-[var(--surface-3)] rounded-lg p-2">
                    <div className="text-[10px] text-[var(--text-secondary)] font-mono">{label}</div>
                    <div className="text-xs font-mono text-[var(--text-primary)] mt-0.5">{val}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Neighbor feasibility inline */}
            {feasibility && (
              <div className="rounded-lg border p-2 space-y-1"
                style={{ borderColor: hasBlockingIssues ? 'var(--accent-red)' : feasibility.warnings?.length ? 'var(--accent-amber)' : 'var(--accent-green)', background: hasBlockingIssues ? 'rgba(239,68,68,0.06)' : feasibility.warnings?.length ? 'rgba(255,179,0,0.06)' : 'rgba(0,255,136,0.06)' }}>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full flex-shrink-0"
                    style={{ background: hasBlockingIssues ? 'var(--accent-red)' : feasibility.warnings?.length ? 'var(--accent-amber)' : 'var(--accent-green)' }} />
                  <span className="text-xs font-mono font-semibold"
                    style={{ color: hasBlockingIssues ? 'var(--accent-red)' : feasibility.warnings?.length ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
                    {hasBlockingIssues ? 'Build not feasible' : feasibility.warnings?.length ? 'Feasible with warnings' : 'Site is feasible'}
                  </span>
                </div>
                <div className="text-[10px] font-mono text-[var(--text-secondary)]">
                  {feasibility.parcel_width_ft}ft × {feasibility.parcel_depth_ft}ft
                  {neighborConstraints?.min_neighbor_gap_ft && ` · Closest neighbor: ${neighborConstraints.min_neighbor_gap_ft}ft`}
                  {neighborConstraints?.neighbor_count > 0 && ` · ${neighborConstraints.neighbor_count} neighbors`}
                </div>
                {feasibility.issues?.map((issue: string, i: number) => (
                  <div key={i} className="text-[10px] font-mono text-[var(--accent-red)]">✗ {issue}</div>
                ))}
                {feasibility.warnings?.map((w: string, i: number) => (
                  <div key={i} className="text-[10px] font-mono text-[var(--accent-amber)]">⚠ {w}</div>
                ))}
                {neighborConstraints?.existing_building && (
                  <div className="text-[10px] font-mono text-[var(--accent-purple)] mt-1">
                    🏠 Existing {neighborConstraints.existing_building.levels}-story building on parcel
                    ({neighborConstraints.existing_building.area_sqft?.toFixed(0)} sqft)
                  </div>
                )}
              </div>
            )}

            {siteContext?.hazard_detail && (
              <div className="bg-[var(--surface-3)] rounded-lg p-2 space-y-0.5">
                <div className="text-[10px] font-mono text-[var(--text-secondary)] uppercase tracking-wider mb-1">Hazard Detail</div>
                {siteContext.hazard_detail.seismic && (
                  <div className="text-[10px] font-mono text-[var(--text-secondary)]">
                    🌍 {siteContext.hazard_detail.seismic.note}
                  </div>
                )}
                {siteContext.hazard_detail.wind && (
                  <div className="text-[10px] font-mono text-[var(--text-secondary)]">
                    💨 {siteContext.hazard_detail.wind.note}
                  </div>
                )}
              </div>
            )}
            {siteContext?.flood_flag && (
              <div className="flex items-center gap-2 text-xs font-mono text-[var(--accent-amber)] bg-amber-950/30 border border-amber-800/30 rounded-lg px-3 py-2">
                ⚠ Flood zone — elevation review required
              </div>
            )}
          </div>
        ) : (
          <div className="text-xs text-[var(--text-secondary)] font-mono italic">
            Click the map to select a site
          </div>
        )}
      </div>

      {/* Building parameters */}
      <div className="panel-section space-y-4">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">Building Parameters</div>

        <Field label="Stories (1–3)">
          <NumInput
            value={spec.stories}
            min={1} max={3}
            onChange={(v) => updateSpec({ stories: v ? Math.min(3, Math.max(1, Math.round(v))) : 2 })}
          />
        </Field>

        <Field label="Target Area (sqft)">
          <NumInput
            value={spec.target_gross_area_sqft}
            placeholder="e.g. 8000"
            min={100}
            onChange={(v) => updateSpec({ target_gross_area_sqft: v })}
          />
        </Field>

        <Field label="Unit Count (optional)">
          <NumInput
            value={spec.unit_count}
            placeholder="e.g. 12"
            min={1}
            onChange={(v) => updateSpec({ unit_count: v ? Math.round(v) : undefined })}
          />
        </Field>

        <Field label="Floor-to-Floor Height (ft)">
          <NumInput
            value={spec.floor_to_floor_height_ft}
            min={8} max={20} step={0.5}
            onChange={(v) => updateSpec({ floor_to_floor_height_ft: v })}
          />
        </Field>
      </div>

      {/* Systems */}
      <div className="panel-section space-y-4">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">Systems</div>

        <Field label="Structural System">
          <Select value={spec.structural_system || 'wood'} onChange={(v) => updateSpec({ structural_system: v })} options={STRUCTURAL} />
        </Field>

        <Field label="HVAC Preference">
          <Select value={spec.hvac_preference || 'mini_split'} onChange={(v) => updateSpec({ hvac_preference: v })} options={HVAC_OPTS} />
        </Field>

        <Field label="Optimization Priority">
          <div className="flex gap-2">
            {PRIORITIES.map((p) => (
              <button key={p} onClick={() => updateSpec({ priority: p })}
                className="flex-1 py-1.5 rounded-lg text-xs font-mono capitalize transition-all"
                style={{
                  background: spec.priority === p ? 'var(--accent-cyan)' : 'var(--surface-3)',
                  color: spec.priority === p ? '#000' : 'var(--text-secondary)',
                  border: `1px solid ${spec.priority === p ? 'var(--accent-cyan)' : 'var(--border)'}`,
                }}>
                {p}
              </button>
            ))}
          </div>
        </Field>
      </div>

      {/* Generate */}
      <div className="panel-section mt-auto">
        {error && (
          <div className="mb-3 text-xs font-mono text-[var(--accent-red)] bg-red-950/30 border border-red-800/30 rounded-lg px-3 py-2">
            {error}
          </div>
        )}
        {hasBlockingIssues && (
          <div className="mb-3 text-xs font-mono text-[var(--accent-amber)] bg-amber-950/30 border border-amber-800/30 rounded-lg px-3 py-2">
            ⚠ Fire separation issues detected — building may not be approvable. Generating anyway for review.
          </div>
        )}
        <button
          onClick={handleGenerate}
          disabled={!canGenerate || loading}
          className="w-full py-3 rounded-xl font-display font-semibold text-sm transition-all duration-200"
          style={{
            background: !canGenerate || loading ? 'var(--surface-3)' : hasBlockingIssues ? 'linear-gradient(135deg, #f59e0b, #ef4444)' : 'linear-gradient(135deg, #00e5ff, #00ff88)',
            color: canGenerate && !loading ? '#000' : 'var(--text-secondary)',
            cursor: canGenerate && !loading ? 'pointer' : 'not-allowed',
          }}>
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="animate-spin w-3 h-3 border border-black/30 border-t-black rounded-full" />
              Generating…
            </span>
          ) : hasBlockingIssues ? '⚠ Generate (Issues Detected)' : '⚡ Generate Building'}
        </button>
        {!canGenerate && (
          <div className="text-center text-[10px] text-[var(--text-secondary)] mt-2 font-mono">
            Select a site on the map first
          </div>
        )}
      </div>
    </div>
  );
}