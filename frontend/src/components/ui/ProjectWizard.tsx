'use client';
import { useState } from 'react';
import { useAppStore } from '@/lib/store';
import api from '@/lib/api';

const GOALS = [
  { key: 'cost',  label: 'Cost',  icon: '$', desc: 'Minimize build cost' },
  { key: 'time',  label: 'Speed', icon: '⚡', desc: 'Fastest to construct' },
  { key: 'space', label: 'Space', icon: '⊞', desc: 'Maximize living area' },
  { key: 'light', label: 'Light', icon: '◎', desc: 'Natural daylight first' },
];

const STRUCTURAL = ['wood', 'steel', 'concrete'];
const HVAC_OPTS = ['mini_split', 'rooftop'];

const MATERIAL_PARTS = [
  { key: 'walls',          label: 'Exterior Walls' },
  { key: 'interior_walls', label: 'Interior Walls' },
  { key: 'roof',           label: 'Roof' },
  { key: 'floors',         label: 'Floors' },
  { key: 'windows',        label: 'Windows' },
  { key: 'foundation',     label: 'Foundation' },
];
const MATERIAL_OPTIONS = ['ai', 'wood', 'concrete', 'brick', 'metal', 'glass', 'stone', 'stucco'];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">{label}</label>
      {children}
    </div>
  );
}

function NumInput({ value, onChange, placeholder, min, max, step }: {
  value: number | undefined; onChange: (v: number | undefined) => void;
  placeholder?: string; min?: number; max?: number; step?: number;
}) {
  return (
    <input type="number" defaultValue={value ?? ''} min={min} max={max} step={step}
      placeholder={placeholder}
      onChange={(e) => { const v = e.target.value; onChange(v === '' ? undefined : parseFloat(v)); }}
      className="w-full bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)] transition-colors font-mono"
    />
  );
}

function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
      className="w-full bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)] transition-colors font-mono">
      {options.map((o) => <option key={o} value={o}>{o === 'ai' ? 'AI picks best' : o.replace(/_/g, ' ')}</option>)}
    </select>
  );
}

function SectionToggle({ label, open, onToggle }: { label: string; open: boolean; onToggle: () => void }) {
  return (
    <button onClick={onToggle} className="flex items-center justify-between w-full text-left">
      <span className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">{label}</span>
      <span className="text-xs font-mono text-[var(--text-secondary)]">{open ? '▲' : '▼'}</span>
    </button>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button onClick={() => onChange(!checked)}
      className="flex items-center justify-between w-full px-3 py-2 rounded-lg border transition-colors"
      style={{ borderColor: checked ? 'var(--accent-cyan)' : 'var(--border)', background: checked ? 'rgba(0,229,255,0.07)' : 'var(--surface-3)' }}>
      <span className="text-xs font-mono" style={{ color: checked ? 'var(--accent-cyan)' : 'var(--text-secondary)' }}>{label}</span>
      <div className="w-8 h-4 rounded-full relative transition-colors" style={{ background: checked ? 'var(--accent-cyan)' : 'var(--surface-2)' }}>
        <div className="w-3 h-3 rounded-full bg-white absolute top-0.5 transition-all" style={{ left: checked ? '17px' : '2px' }} />
      </div>
    </button>
  );
}

export default function ProjectWizard() {
  const { selectedSite, siteContext, neighborConstraints, spec, updateSpec, setBuildingModel } = useAppStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showMaterials, setShowMaterials] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  const materialOverrides: Record<string, string> = (spec as any).material_overrides || {};
  const fineDetails: Record<string, any> = (spec as any).fine_details || {};

  const setMaterial = (part: string, val: string) => {
    const next = { ...materialOverrides };
    if (val === 'ai') delete next[part]; else next[part] = val;
    updateSpec({ material_overrides: Object.keys(next).length ? next : null } as any);
  };

  const setDetail = (key: string, val: any) => {
    updateSpec({ fine_details: { ...fineDetails, [key]: val } } as any);
  };

  const canGenerate = !!selectedSite;
  const feasibility = neighborConstraints?.feasibility;
  const hasBlockingIssues = feasibility?.issues?.length > 0;

  // Derive a smart default area from parcel size × stories × efficiency factor
  const stories = spec.stories || 2;
  const derivedArea = siteContext?.area_sqft
    ? Math.round(siteContext.area_sqft * stories * 0.65 / 100) * 100
    : 8000;
  const effectiveArea = spec.target_gross_area_sqft || derivedArea;

  const handleGenerate = async () => {
    if (!selectedSite) return;
    setLoading(true); setError('');
    const fullSpec: any = {
      region_country: 'US', region_state: 'CA',
      occupancy: 'MultiFamilyResidential', permit_set: false,
      stories,
      floor_to_floor_height_ft: spec.floor_to_floor_height_ft || 10.0,
      structural_system: spec.structural_system || 'wood',
      hvac_preference: spec.hvac_preference || 'mini_split',
      parking_strategy: spec.parking_strategy || 'ignore',
      priority: spec.priority || 'cost',
      target_gross_area_sqft: effectiveArea,
      unit_count: spec.unit_count || null,
      material_overrides: (spec as any).material_overrides || null,
      fine_details: (spec as any).fine_details || null,
      site: {
        latlon: { lat: selectedSite.lat, lon: selectedSite.lon },
        address: null,
        parcel_polygon: siteContext?.parcel_polygon || null,
      },
    };
    try {
      const result = await api.quickGenerate(fullSpec);
      if (result.result) setBuildingModel(result.result);
    } catch (e: any) {
      const detail = e.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? detail.map((d: any) => `${d.loc?.join('.')}: ${d.msg}`).join(' | ')
        : detail || e.message || 'Generation failed';
      setError(msg);
    } finally { setLoading(false); }
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Header */}
      <div className="panel-section">
        <div className="font-display text-lg font-semibold text-[var(--text-primary)]">Project Setup</div>
        <div className="text-xs text-[var(--text-secondary)] mt-0.5 font-mono">California · Multi-family Residential</div>
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
                  {neighborConstraints?.min_neighbor_gap_ft && ` · Closest: ${neighborConstraints.min_neighbor_gap_ft}ft`}
                </div>
                {feasibility.issues?.map((issue: string, i: number) => (
                  <div key={i} className="text-[10px] font-mono text-[var(--accent-red)]">✗ {issue}</div>
                ))}
                {feasibility.warnings?.map((w: string, i: number) => (
                  <div key={i} className="text-[10px] font-mono text-[var(--accent-amber)]">⚠ {w}</div>
                ))}
              </div>
            )}
            {siteContext?.flood_flag && (
              <div className="flex items-center gap-2 text-xs font-mono text-[var(--accent-amber)] bg-amber-950/30 border border-amber-800/30 rounded-lg px-3 py-2">
                ⚠ Flood zone — elevation review required
              </div>
            )}
          </div>
        ) : (
          <div className="text-xs text-[var(--text-secondary)] font-mono italic">Click the map to select a site</div>
        )}
      </div>

      {/* Goals */}
      <div className="panel-section space-y-3">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">Primary Goal</div>
        <div className="grid grid-cols-2 gap-2">
          {GOALS.map(({ key, label, icon, desc }) => {
            const active = (spec.priority || 'cost') === key;
            return (
              <button key={key} onClick={() => updateSpec({ priority: key })}
                className="rounded-xl p-3 text-left transition-all border"
                style={{
                  background: active ? 'rgba(0,229,255,0.1)' : 'var(--surface-3)',
                  borderColor: active ? 'var(--accent-cyan)' : 'var(--border)',
                }}>
                <div className="text-lg mb-1" style={{ color: active ? 'var(--accent-cyan)' : 'var(--text-secondary)' }}>{icon}</div>
                <div className="text-xs font-mono font-semibold" style={{ color: active ? 'var(--accent-cyan)' : 'var(--text-primary)' }}>{label}</div>
                <div className="text-[10px] font-mono text-[var(--text-secondary)] mt-0.5">{desc}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Building parameters */}
      <div className="panel-section space-y-4">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">Building Parameters</div>
        <Field label="Stories (1–3)">
          <NumInput value={spec.stories} min={1} max={3}
            onChange={(v) => updateSpec({ stories: v ? Math.min(3, Math.max(1, Math.round(v))) : 2 })} />
        </Field>
        <Field label="Target Area (sqft)">
          <div className="space-y-1">
            <NumInput value={spec.target_gross_area_sqft} placeholder={`Auto: ~${derivedArea.toLocaleString()} sqft`} min={100}
              onChange={(v) => updateSpec({ target_gross_area_sqft: v })} />
            {!spec.target_gross_area_sqft && (
              <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70">
                {siteContext?.area_sqft
                  ? `Auto = parcel (${Math.round(siteContext.area_sqft).toLocaleString()} sqft) × ${stories} floors × 65%`
                  : 'Set a target or select a site for auto-calc'}
              </div>
            )}
            {spec.target_gross_area_sqft && siteContext?.area_sqft && spec.target_gross_area_sqft > siteContext.area_sqft * stories * 0.9 && (
              <div className="text-[10px] font-mono text-[var(--accent-amber)]">
                ⚠ Exceeds ~90% of buildable envelope — may not fit
              </div>
            )}
          </div>
        </Field>
        <Field label="Unit Count (optional)">
          <NumInput value={spec.unit_count} placeholder="e.g. 12" min={1}
            onChange={(v) => updateSpec({ unit_count: v ? Math.round(v) : undefined })} />
        </Field>
        <Field label="Floor-to-Floor Height (ft)">
          <NumInput value={spec.floor_to_floor_height_ft} min={8} max={20} step={0.5}
            onChange={(v) => updateSpec({ floor_to_floor_height_ft: v })} />
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
      </div>

      {/* Materials (collapsible) */}
      <div className="panel-section space-y-3">
        <SectionToggle label="Materials (optional)" open={showMaterials} onToggle={() => setShowMaterials(v => !v)} />
        {showMaterials && (
          <div className="space-y-2 pt-1">
            <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70">
              Leave as "AI picks best" to let the AI choose based on your goal.
            </div>
            {MATERIAL_PARTS.map(({ key, label }) => (
              <div key={key} className="flex items-center justify-between gap-3">
                <span className="text-xs font-mono text-[var(--text-secondary)] w-28 flex-shrink-0">{label}</span>
                <Select
                  value={materialOverrides[key] || 'ai'}
                  onChange={(v) => setMaterial(key, v)}
                  options={MATERIAL_OPTIONS}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Fine Details (collapsible) */}
      <div className="panel-section space-y-3">
        <SectionToggle label="Fine Details (optional)" open={showDetails} onToggle={() => setShowDetails(v => !v)} />
        {showDetails && (
          <div className="space-y-2 pt-1">
            <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70 mb-2">
              AI places these by default. Override counts or disable specific systems.
            </div>
            <Field label="Outlets per room">
              <NumInput value={fineDetails.outlets_per_room ?? 3} min={0} max={10}
                onChange={(v) => setDetail('outlets_per_room', v ?? 3)} />
            </Field>
            <div className="space-y-1.5">
              {[
                { key: 'fire_alarms',    label: 'Fire Alarms' },
                { key: 'exhaust_fans',   label: 'Exhaust Fans (bath/kitchen)' },
                { key: 'fire_sprinklers',label: 'Fire Sprinklers' },
              ].map(({ key, label }) => (
                <Toggle key={key} checked={fineDetails[key] !== false}
                  onChange={(v) => setDetail(key, v)} label={label} />
              ))}
            </div>
            <div className="mt-2 space-y-1">
              <div className="text-[10px] font-mono text-[var(--text-secondary)] uppercase tracking-wider">Included by default</div>
              {['Sink (kitchen + bath)', 'Toilet (per bathroom)', 'Shower (per bathroom)', 'Lighting (per room)'].map(item => (
                <div key={item} className="flex items-center gap-2 text-[10px] font-mono text-[var(--text-secondary)]">
                  <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)]" />
                  {item}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Generate */}
      <div className="panel-section mt-auto">
        {error && (
          <div className="mb-3 text-xs font-mono text-[var(--accent-red)] bg-red-950/30 border border-red-800/30 rounded-lg px-3 py-2">{error}</div>
        )}
        {hasBlockingIssues && (
          <div className="mb-3 text-xs font-mono text-[var(--accent-amber)] bg-amber-950/30 border border-amber-800/30 rounded-lg px-3 py-2">
            ⚠ Fire separation issues detected — generating anyway for review.
          </div>
        )}
        <button onClick={handleGenerate} disabled={!canGenerate || loading}
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
          <div className="text-center text-[10px] text-[var(--text-secondary)] mt-2 font-mono">Select a site on the map first</div>
        )}
      </div>
    </div>
  );
}
