'use client';
import { useState, useMemo } from 'react';
import { useAppStore } from '@/lib/store';
import api from '@/lib/api';

// Compute sqft from a GeoJSON polygon using Shoelace on local-meter coords
function polyAreaSqft(poly: any): number | null {
  const coords = poly?.coordinates?.[0];
  if (!coords || coords.length < 3) return null;
  const cLon = coords.reduce((s: number, c: number[]) => s + c[0], 0) / coords.length;
  const cLat = coords.reduce((s: number, c: number[]) => s + c[1], 0) / coords.length;
  const mPerDegLat = 111320;
  const mPerDegLon = 111320 * Math.cos(cLat * Math.PI / 180);
  let area = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    const x1 = (coords[i][0] - cLon) * mPerDegLon;
    const y1 = (coords[i][1] - cLat) * mPerDegLat;
    const x2 = (coords[i + 1][0] - cLon) * mPerDegLon;
    const y2 = (coords[i + 1][1] - cLat) * mPerDegLat;
    area += x1 * y2 - x2 * y1;
  }
  return Math.round(Math.abs(area / 2) * 10.7639);
}

const GOALS = [
  { key: 'cost',   label: 'Budget Optimization',  icon: '$', desc: 'Minimize build cost' },
  { key: 'time',   label: 'Construction Speed',    icon: '⚡', desc: 'Fastest to construct' },
  { key: 'space',  label: 'Space Efficiency',      icon: '⊞', desc: 'Maximize living area' },
  { key: 'light',  label: 'Natural Light',         icon: '◎', desc: 'Daylight-first design' },
  { key: 'energy', label: 'Energy Performance',    icon: '♻', desc: 'Low energy use & cost' },
];

const DESIGN_STYLES = [
  { key: 'classic_gabled', label: 'Classic & Gabled',   desc: 'Pitched roofs, traditional forms' },
  { key: 'modern_linear',  label: 'Modern & Linear',    desc: 'Flat roof, clean horizontal lines' },
  { key: 'solid_sculpted', label: 'Solid & Sculpted',   desc: 'Monolithic, textured mass' },
];

const BUILDING_USES = [
  { key: 'single_family', label: 'Single Family' },
  { key: 'multi_family',  label: 'Multi-Family'  },
  { key: 'adu',           label: 'ADU'           },
];

// Sqft ranges per bedroom count: [min, max] — matches backend SFR_SQFT_RANGES
// priority drives where in range: cost/speed=low, light=mid, space=high
const SFR_SQFT_RANGES: Record<number, [number, number]> = {
  1: [500,  900],
  2: [800,  1300],
  3: [1200, 1900],
  4: [1800, 2800],
  5: [2500, 4200],
};

const PRIORITY_RANGE_POS: Record<string, number> = {
  cost: 0.0, time: 0.15, speed: 0.15, light: 0.5, daylight: 0.5, space: 1.0, energy: 0.3,
};

function sfrTargetSqft(bedrooms: number, priority: string): number {
  const [lo, hi] = SFR_SQFT_RANGES[bedrooms] ?? [1200, 1900];
  const t = PRIORITY_RANGE_POS[priority] ?? 0.5;
  return Math.round(lo + (hi - lo) * t);
}

// Maps priority + building use to a suggested house archetype label shown in UI
const ARCHETYPE_HINTS: Record<string, Record<string, string>> = {
  single_family: {
    cost:   'Ranch / Cape Cod — simple geometry, wood frame, affordable',
    time:   'Ranch / Foursquare — rectangular, fast to frame',
    light:  'Contemporary / Mid-Century Modern — large glazing, open plan',
    space:  'Colonial / Farmhouse — maximum rooms, efficient layout',
    energy: 'Prairie / Contemporary — high insulation, passive solar',
  },
  multi_family: { cost: 'Efficient corridor plan', time: 'Stacked units', light: 'Atrium plan', space: 'U-shape courtyard', energy: 'Passive-house block' },
  adu:          { cost: 'Compact studio', time: 'Modular box', light: 'South-facing studio', space: 'Loft layout', energy: 'Super-insulated box' },
};

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
  const { selectedSite, siteContext, neighborConstraints, spec, updateSpec, setBuildingModel, clickedBuilding, drawnParcel, buildingModel } = useAppStore();

  // Use drawn parcel area when available — more accurate than OSM parcel
  const parcelAreaSqft = useMemo(() =>
    polyAreaSqft(drawnParcel) ?? siteContext?.area_sqft ?? null,
    [drawnParcel, siteContext?.area_sqft]
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showMaterials, setShowMaterials] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  // Resolved materials: prefer the generated model's overrides (which include AI-picked),
  // fall back to user-set overrides in spec
  const resolvedOverrides: Record<string, string> = (buildingModel as any)?.spec?.material_overrides || {};
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
  const derivedArea = parcelAreaSqft
    ? Math.round(parcelAreaSqft * 0.65 / 100) * 100   // single floor footprint × 65% efficiency
    : 8000;
  const effectiveArea = spec.target_gross_area_sqft || derivedArea;

  const handleGenerate = async () => {
    if (!selectedSite) return;
    setLoading(true); setError('');

    // If user clicked an existing building, seed its material + height into the spec
    // so the generator matches that building's style
    const clickedProps = clickedBuilding?.properties || {};
    const clickedMat = (clickedProps.facade_mat || clickedProps['building:material'] || clickedProps.material || '').toLowerCase();
    const clickedLevels = parseInt(clickedProps['building:levels'] || clickedProps.levels || '0') || 0;
    const clickedHeight = clickedProps.height_m ? Math.round(parseFloat(clickedProps.height_m) / 3) : 0;
    const inferredStories = clickedLevels || clickedHeight || spec.stories || 2;

    const buildingUse = (spec as any).building_use || 'multi_family';
    const bedrooms = (spec as any).bedrooms || (buildingUse === 'single_family' ? 3 : undefined);

    const fullSpec: any = {
      region_country: 'US', region_state: 'CA',
      occupancy: buildingUse === 'multi_family' ? 'MultiFamilyResidential' : 'SingleFamilyResidential',
      permit_set: false,
      building_use: buildingUse,
      bedrooms: bedrooms || null,
      stories: inferredStories,
      floor_to_floor_height_ft: spec.floor_to_floor_height_ft || 10.0,
      structural_system: spec.structural_system || 'wood',
      hvac_preference: spec.hvac_preference || 'mini_split',
      parking_strategy: spec.parking_strategy || 'ignore',
      priority: spec.priority || 'cost',
      style: (spec as any).style || 'modern_linear',
      target_gross_area_sqft: effectiveArea,
      unit_count: buildingUse === 'multi_family' ? (spec.unit_count || null) : 1,
      // Merge clicked building's material into overrides if user hasn't set walls manually
      material_overrides: Object.keys({
        ...((spec as any).material_overrides || {}),
        ...(clickedMat && !((spec as any).material_overrides?.walls) ? { walls: clickedMat } : {}),
      }).length ? {
        ...((spec as any).material_overrides || {}),
        ...(clickedMat && !((spec as any).material_overrides?.walls) ? { walls: clickedMat } : {}),
      } : null,
      fine_details: (spec as any).fine_details || null,
      max_height_ft: (spec as any).max_height_ft || null,
      max_floors: (spec as any).max_floors || null,
      max_bedrooms: (spec as any).max_bedrooms || null,
      max_sqft: (spec as any).max_sqft || null,
      site: {
        latlon: { lat: selectedSite.lat, lon: selectedSite.lon },
        address: null,
        // Prefer user-drawn parcel polygon over OSM-derived one
        parcel_polygon: drawnParcel || siteContext?.parcel_polygon || null,
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
            {drawnParcel ? (
              <div className="flex items-center gap-2 text-xs font-mono text-[var(--accent-cyan)] bg-cyan-950/30 border border-cyan-800/30 rounded-lg px-3 py-2">
                ⬡ Custom parcel boundary active
              </div>
            ) : (
              <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-60">
                Site selected · define parcel shape on the map for precise boundaries
              </div>
            )}
            {siteContext && (
              <div className="grid grid-cols-2 gap-2">
                {[
                  { label: 'Area', val: `${parcelAreaSqft?.toLocaleString() ?? siteContext.area_sqft?.toFixed(0)} sqft${drawnParcel ? ' (drawn)' : ''}` },
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

      {/* Design Style */}
      <div className="panel-section space-y-3">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">Design Style</div>
        <div className="flex flex-col gap-2">
          {DESIGN_STYLES.map(({ key, label, desc }) => {
            const active = ((spec as any).style || 'modern_linear') === key;
            return (
              <button key={key} onClick={() => updateSpec({ style: key } as any)}
                className="rounded-xl px-3 py-2.5 text-left transition-all border"
                style={{
                  background: active ? 'rgba(0,229,255,0.08)' : 'var(--surface-3)',
                  borderColor: active ? 'var(--accent-cyan)' : 'var(--border)',
                }}>
                <div className="text-xs font-mono font-semibold" style={{ color: active ? 'var(--accent-cyan)' : 'var(--text-primary)' }}>{label}</div>
                <div className="text-[10px] font-mono text-[var(--text-secondary)] mt-0.5">{desc}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Building type */}
      <div className="panel-section space-y-3">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">Building Type</div>
        <div className="flex gap-2">
          {BUILDING_USES.map(({ key, label }) => {
            const active = ((spec as any).building_use || 'multi_family') === key;
            return (
              <button key={key} onClick={() => updateSpec({ building_use: key } as any)}
                className="flex-1 rounded-lg py-2 text-center text-xs font-mono transition-all border"
                style={{
                  background: active ? 'rgba(0,229,255,0.1)' : 'var(--surface-3)',
                  borderColor: active ? 'var(--accent-cyan)' : 'var(--border)',
                  color: active ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                }}>
                {label}
              </button>
            );
          })}
        </div>
        {/* Archetype hint based on priority + building use */}
        {(() => {
          const use = (spec as any).building_use || 'multi_family';
          const pri = (spec.priority || 'cost').replace('speed','time').replace('daylight','light').replace('budget','cost');
          const hint = ARCHETYPE_HINTS[use]?.[pri];
          return hint ? (
            <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70 italic">{hint}</div>
          ) : null;
        })()}
      </div>

      {/* Building parameters */}
      <div className="panel-section space-y-4">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">Building Parameters</div>

        {/* Bedrooms — only shown for single-family / ADU */}
        {['single_family', 'adu'].includes((spec as any).building_use || 'multi_family') && (() => {
          const br = (spec as any).bedrooms || 3;
          const pri = (spec.priority || 'cost') as string;
          const [lo, hi] = SFR_SQFT_RANGES[br] ?? [1200, 1900];
          const suggested = sfrTargetSqft(br, pri);
          return (
            <Field label="Bedrooms (1–5)">
              <div className="flex gap-1.5">
                {[1,2,3,4,5].map((n) => {
                  const active = br === n;
                  return (
                    <button key={n} onClick={() => updateSpec({ bedrooms: n } as any)}
                      className="flex-1 rounded-lg py-2 text-xs font-mono font-semibold transition-all border"
                      style={{
                        background: active ? 'rgba(0,229,255,0.1)' : 'var(--surface-3)',
                        borderColor: active ? 'var(--accent-cyan)' : 'var(--border)',
                        color: active ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                      }}>
                      {n}
                    </button>
                  );
                })}
              </div>
              {/* Range hint — shows realistic sqft band + where priority lands */}
              <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70 mt-1">
                {br}BR range: {lo.toLocaleString()}–{hi.toLocaleString()} sqft
                <span className="ml-2 text-[var(--accent-cyan)]">
                  ({pri} target: ~{suggested.toLocaleString()} sqft)
                </span>
              </div>
            </Field>
          );
        })()}

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
                {parcelAreaSqft
                  ? `Auto = parcel (${parcelAreaSqft.toLocaleString()} sqft${drawnParcel ? ', drawn' : ''}) × 65% efficiency`
                  : 'Set a target or select a site for auto-calc'}
              </div>
            )}
            {spec.target_gross_area_sqft && parcelAreaSqft && (() => {
              const singleFloorMax = parcelAreaSqft * 0.85;
              const multiFloorMax = singleFloorMax * stories;
              if (spec.target_gross_area_sqft > multiFloorMax) {
                return (
                  <div className="text-[10px] font-mono text-[var(--accent-red)]">
                    ✗ {spec.target_gross_area_sqft.toLocaleString()} sqft exceeds {stories}-floor max (~{Math.round(multiFloorMax).toLocaleString()} sqft) — add more floors or reduce target
                  </div>
                );
              }
              if (spec.target_gross_area_sqft > singleFloorMax) {
                const floorsNeeded = Math.ceil(spec.target_gross_area_sqft / singleFloorMax);
                return (
                  <div className="text-[10px] font-mono text-[var(--accent-amber)]">
                    ⚠ Target needs ~{floorsNeeded} floors to fit on this parcel ({parcelAreaSqft.toLocaleString()} sqft land)
                  </div>
                );
              }
              return null;
            })()}
          </div>
        </Field>

        {/* Unit count only for multi-family */}
        {((spec as any).building_use || 'multi_family') === 'multi_family' && (
          <Field label="Unit Count (optional)">
            <NumInput value={spec.unit_count} placeholder="e.g. 12" min={1}
              onChange={(v) => updateSpec({ unit_count: v ? Math.round(v) : undefined })} />
          </Field>
        )}

        <Field label="Floor-to-Floor Height (ft)">
          <NumInput value={spec.floor_to_floor_height_ft} min={8} max={20} step={0.5}
            onChange={(v) => updateSpec({ floor_to_floor_height_ft: v })} />
        </Field>
      </div>

      {/* Height & Code Limits */}
      <div className="panel-section space-y-4">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">Height & Limits</div>

        <Field label="Max Building Height">
          <div className="flex items-center gap-2">
            <NumInput
              value={(spec as any).max_height_ft}
              placeholder={`Auto: ~${Math.round(((spec.stories || 2) * (spec.floor_to_floor_height_ft || 10)))} ft`}
              min={8}
              onChange={(v) => updateSpec({ max_height_ft: v } as any)}
            />
            <span className="text-[10px] font-mono text-[var(--text-secondary)] flex-shrink-0 min-w-[52px]">
              {(spec as any).max_height_ft
                ? `= ${((spec as any).max_height_ft * 0.3048).toFixed(1)} m`
                : 'ft / m'}
            </span>
          </div>
          <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-60 mt-0.5">
            {`${spec.stories || 2} floor${(spec.stories || 2) > 1 ? 's' : ''} × ${spec.floor_to_floor_height_ft || 10} ft = ${Math.round((spec.stories || 2) * (spec.floor_to_floor_height_ft || 10))} ft`}
            {` (${((((spec.stories || 2) * (spec.floor_to_floor_height_ft || 10)) * 0.3048)).toFixed(1)} m)`}
          </div>
        </Field>

        <Field label="Max Floors">
          <NumInput
            value={(spec as any).max_floors}
            placeholder={`Current: ${spec.stories || 2}`}
            min={1}
            max={20}
            onChange={(v) => updateSpec({ max_floors: v ? Math.round(v) : undefined } as any)}
          />
        </Field>

        <Field label="Max Bedrooms">
          <NumInput
            value={(spec as any).max_bedrooms}
            placeholder="No limit"
            min={1}
            max={50}
            onChange={(v) => updateSpec({ max_bedrooms: v ? Math.round(v) : undefined } as any)}
          />
        </Field>

        <Field label="Max Total Sqft">
          <NumInput
            value={(spec as any).max_sqft}
            placeholder="No limit"
            min={100}
            onChange={(v) => updateSpec({ max_sqft: v } as any)}
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
      </div>

      {/* Materials (collapsible) */}
      <div className="panel-section space-y-3">
        <SectionToggle label="Materials (optional)" open={showMaterials} onToggle={() => setShowMaterials(v => !v)} />
        {showMaterials && (
          <div className="space-y-2 pt-1">
            <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70">
              {buildingModel
                ? 'Showing AI-selected materials. Override any to customize.'
                : 'Leave as "AI picks best" to auto-select based on your goal & style.'}
            </div>
            {MATERIAL_PARTS.map(({ key, label }) => {
              const userVal = materialOverrides[key];
              const aiVal = resolvedOverrides[key];
              const displayVal = userVal || 'ai';
              return (
                <div key={key} className="space-y-0.5">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs font-mono text-[var(--text-secondary)] w-28 flex-shrink-0">{label}</span>
                    <Select
                      value={displayVal}
                      onChange={(v) => setMaterial(key, v)}
                      options={MATERIAL_OPTIONS}
                    />
                  </div>
                  {!userVal && aiVal && (
                    <div className="text-[10px] font-mono pl-[7.5rem]" style={{ color: 'var(--accent-cyan)', opacity: 0.75 }}>
                      AI selected: {aiVal}
                    </div>
                  )}
                </div>
              );
            })}
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
