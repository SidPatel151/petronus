'use client';
import { useState, useMemo } from 'react';
import { useAppStore } from '@/lib/store';
import type {
  CaliforniaCodeCycle,
  ConstructionScope,
  PrimaryDwellingSprinklerRequirement,
  ProjectSpec,
} from '@/lib/api';

// ── Parcel geometry helpers ────────────────────────────────────────────

/** Convert local meter offset [dx, dy] from a lat/lon center to [lon, lat] */
function offsetToLatLon(dx: number, dy: number, centerLon: number, centerLat: number): [number, number] {
  const mPerDegLat = 111320;
  const mPerDegLon = 111320 * Math.cos(centerLat * Math.PI / 180);
  return [centerLon + dx / mPerDegLon, centerLat + dy / mPerDegLat];
}

/** Build a GeoJSON Polygon from a list of [lon, lat] points */
function makeGeoJSONPolygon(points: [number, number][]): any {
  const ring = [...points, points[0]]; // close the ring
  return { type: 'Polygon', coordinates: [ring] };
}

/** Approximate a circle as a 32-sided polygon */
function circleToPolygon(radiusM: number, centerLon: number, centerLat: number): any {
  const N = 32;
  const pts: [number, number][] = [];
  for (let i = 0; i < N; i++) {
    const angle = (2 * Math.PI * i) / N;
    const dx = radiusM * Math.cos(angle);
    const dy = radiusM * Math.sin(angle);
    pts.push(offsetToLatLon(dx, dy, centerLon, centerLat));
  }
  return makeGeoJSONPolygon(pts);
}

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
  value: number | null | undefined; onChange: (v: number | undefined) => void;
  placeholder?: string; min?: number; max?: number; step?: number;
}) {
  return (
    <input type="number" defaultValue={value ?? ''} min={min} max={max} step={step}
      placeholder={placeholder}
      onChange={(e) => { const v = e.target.value; onChange(v === '' ? undefined : parseFloat(v)); }}
      className="w-full bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-gold)] transition-colors font-mono"
    />
  );
}

function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
      className="w-full bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-gold)] transition-colors font-mono">
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
      style={{ borderColor: checked ? 'var(--accent-gold)' : 'var(--border)', background: checked ? 'rgba(196,168,130,0.09)' : 'var(--surface-3)' }}>
      <span className="text-xs font-mono" style={{ color: checked ? 'var(--accent-gold)' : 'var(--text-secondary)' }}>{label}</span>
      <div className="w-8 h-4 rounded-full relative transition-colors" style={{ background: checked ? 'var(--accent-gold)' : 'var(--surface-2)' }}>
        <div className="w-3 h-3 rounded-full bg-white absolute top-0.5 transition-all" style={{ left: checked ? '17px' : '2px' }} />
      </div>
    </button>
  );
}

export default function ProjectWizard() {
  const { selectedSite, siteContext, neighborConstraints, spec, updateSpec, generateBuilding, clickedBuilding, drawnParcel, setDrawnParcel, buildingModel } = useAppStore();

  // Use drawn parcel area when available — more accurate than OSM parcel
  const parcelAreaSqft = useMemo(() =>
    polyAreaSqft(drawnParcel) ?? siteContext?.area_sqft ?? null,
    [drawnParcel, siteContext?.area_sqft]
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showMaterials, setShowMaterials] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [showLandShape, setShowLandShape] = useState(false);

  // Land shape manual entry state
  const [shapeType, setShapeType] = useState<'polygon' | 'circular'>('polygon');
  const [numVertices, setNumVertices] = useState(4);
  const [vertexInputs, setVertexInputs] = useState<{ x: string; y: string }[]>(
    Array.from({ length: 4 }, () => ({ x: '', y: '' }))
  );
  const [circleRadius, setCircleRadius] = useState<string>('');
  const [circleUnit, setCircleUnit] = useState<'m' | 'ft'>('ft');
  const [shapeError, setShapeError] = useState('');

  function updateVertexCount(n: number) {
    const clamped = Math.max(3, Math.min(20, n));
    setNumVertices(clamped);
    setVertexInputs(prev => {
      const next = [...prev];
      while (next.length < clamped) next.push({ x: '', y: '' });
      return next.slice(0, clamped);
    });
  }

  function applyLandShape() {
    setShapeError('');
    if (!selectedSite) { setShapeError('Select a site first'); return; }
    const cLon = selectedSite.lon, cLat = selectedSite.lat;

    if (shapeType === 'circular') {
      const r = parseFloat(circleRadius);
      if (!r || r <= 0) { setShapeError('Enter a valid radius'); return; }
      const rM = circleUnit === 'ft' ? r * 0.3048 : r;
      if (rM > 500) { setShapeError('Radius seems too large — enter meters/feet from site center, not lat/lon'); return; }
      setDrawnParcel(circleToPolygon(rM, cLon, cLat));
      return;
    }

    // Polygon — validate before converting
    const rawPts: [number, number][] = [];
    for (let i = 0; i < numVertices; i++) {
      const xStr = vertexInputs[i]?.x ?? '', yStr = vertexInputs[i]?.y ?? '';
      const x = parseFloat(xStr), y = parseFloat(yStr);
      if (isNaN(x) || isNaN(y)) { setShapeError(`Vertex ${i + 1}: enter both X and Y`); return; }
      if (Math.abs(x) > 500 || Math.abs(y) > 500) {
        setShapeError(`Vertex ${i + 1}: looks like lat/lon — enter meters from site center (e.g. X=15, Y=20)`);
        return;
      }
      rawPts.push([x, y]);
    }

    // Sort by angle around centroid so vertices always form a proper
    // convex polygon — no matter what order the user typed them in.
    const cx = rawPts.reduce((s, p) => s + p[0], 0) / rawPts.length;
    const cy = rawPts.reduce((s, p) => s + p[1], 0) / rawPts.length;
    const sorted = [...rawPts].sort((a, b) =>
      Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx)
    );

    const pts = sorted.map(([x, y]) => offsetToLatLon(x, y, cLon, cLat));
    setDrawnParcel(makeGeoJSONPolygon(pts));
  }

  // Pre-fill a rectangle from parcel area estimate
  function fillQuickRect(halfW = 15, halfD = 20) {
    setShapeType('polygon');
    updateVertexCount(4);
    setVertexInputs([
      { x: String(-halfW), y: String(-halfD) },
      { x: String( halfW), y: String(-halfD) },
      { x: String( halfW), y: String( halfD) },
      { x: String(-halfW), y: String( halfD) },
    ]);
  }

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
  const constructionScope = spec.construction_scope ?? 'new_construction';
  const permitApplicationDate = spec.permit_application_date ?? '';
  const codeCycle: CaliforniaCodeCycle = permitApplicationDate && permitApplicationDate < '2026-01-01'
    ? '2022'
    : '2025';

  const setPermitApplicationDate = (value: string) => {
    const filingDate = value || null;
    const filingCycle: CaliforniaCodeCycle = value && value < '2026-01-01' ? '2022' : '2025';
    updateSpec({ permit_application_date: filingDate, code_cycle: filingCycle });
  };

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
    const bathrooms = (spec as any).bathrooms ?? (buildingUse === 'single_family' ? 2 : undefined);

    const fullSpec: ProjectSpec = {
      region_country: 'US', region_state: 'CA',
      occupancy: buildingUse === 'multi_family' ? 'MultiFamilyResidential' : 'SingleFamilyResidential',
      construction_scope: constructionScope,
      permit_set: false,
      permit_application_date: permitApplicationDate || null,
      code_cycle: codeCycle,
      jurisdiction_city: spec.jurisdiction_city || null,
      building_use: buildingUse,
      bedrooms: bedrooms ?? null,
      bathrooms: bathrooms || null,
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
      primary_dwelling_sprinkler_requirement: buildingUse === 'adu'
        ? (spec.primary_dwelling_sprinkler_requirement ?? 'unknown')
        : 'unknown',
      primary_dwelling_sprinkler_determination_source: buildingUse === 'adu'
        ? (spec.primary_dwelling_sprinkler_determination_source || null)
        : null,
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
      await generateBuilding(fullSpec, 0);
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
              <div className="flex items-center gap-2 text-xs font-mono text-[var(--accent-gold)] rounded-lg px-3 py-2" style={{background:'rgba(196,168,130,0.07)',border:'1px solid rgba(196,168,130,0.2)'}}>
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

      {/* Land Shape Manual Entry */}
      <div className="panel-section space-y-3">
        <SectionToggle label="Land Shape (manual entry)" open={showLandShape} onToggle={() => setShowLandShape(v => !v)} />
        {showLandShape && (
          <div className="space-y-3 pt-1">
            <div className="text-[10px] font-mono text-[var(--accent-gold)] bg-[rgba(196,168,130,0.07)] border border-[rgba(196,168,130,0.2)] rounded-lg px-3 py-2 leading-relaxed">
              ⚠ Enter <strong>meter offsets</strong> from site center — not lat/lon.<br/>
              X = east (+) / west (−) &nbsp;·&nbsp; Y = north (+) / south (−)<br/>
              Example: a 30×40 ft lot → X: ±4.6, Y: ±6.1
            </div>

            {/* Shape type selector */}
            <div className="flex gap-2">
              {(['polygon', 'circular'] as const).map((t) => (
                <button key={t} onClick={() => setShapeType(t)}
                  className="flex-1 rounded-lg py-2 text-xs font-mono transition-all border capitalize"
                  style={{
                    background: shapeType === t ? 'rgba(196,168,130,0.12)' : 'var(--surface-3)',
                    borderColor: shapeType === t ? 'var(--accent-gold)' : 'var(--border)',
                    color: shapeType === t ? 'var(--accent-gold)' : 'var(--text-secondary)',
                  }}>
                  {t === 'polygon' ? 'Polygon' : 'Circular'}
                </button>
              ))}
            </div>

            {shapeType === 'circular' ? (
              <div className="space-y-2">
                <div className="text-[10px] font-mono text-[var(--text-secondary)]">
                  Circular parcel centered on selected site point
                </div>
                <div className="flex gap-2">
                  <input
                    type="number"
                    placeholder="Radius"
                    value={circleRadius}
                    min={1}
                    onChange={(e) => setCircleRadius(e.target.value)}
                    className="flex-1 bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-gold)] font-mono"
                  />
                  <div className="flex rounded-lg overflow-hidden border border-[var(--border)]">
                    {(['ft', 'm'] as const).map((u) => (
                      <button key={u} onClick={() => setCircleUnit(u)}
                        className="px-3 py-2 text-xs font-mono transition-colors"
                        style={{
                          background: circleUnit === u ? 'var(--accent-gold)' : 'var(--surface-3)',
                          color: circleUnit === u ? '#000' : 'var(--text-secondary)',
                        }}>
                        {u}
                      </button>
                    ))}
                  </div>
                </div>
                {circleRadius && !isNaN(parseFloat(circleRadius)) && (
                  <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70">
                    {circleUnit === 'ft'
                      ? `= ${(parseFloat(circleRadius) * 0.3048).toFixed(1)} m`
                      : `= ${(parseFloat(circleRadius) / 0.3048).toFixed(1)} ft`}
                    {' · '}area ≈ {Math.round(Math.PI * (circleUnit === 'ft' ? parseFloat(circleRadius) : parseFloat(circleRadius) / 0.3048) ** 2).toLocaleString()} sqft
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-2">
                <Field label={`Number of vertices (3–20)`}>
                  <div className="flex items-center gap-2">
                    <input
                      type="number" min={3} max={20} value={numVertices}
                      onChange={(e) => updateVertexCount(parseInt(e.target.value) || 3)}
                      className="w-20 bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-gold)] font-mono"
                    />
                    <span className="text-[10px] font-mono text-[var(--text-secondary)]">
                      {numVertices === 4 ? '(rectangle)' : numVertices === 3 ? '(triangle)' : numVertices === 6 ? '(hexagon)' : `(${numVertices}-sided)`}
                    </span>
                  </div>
                </Field>

                {/* Quick fill helpers */}
                <div className="flex gap-1 flex-wrap">
                  {[['30×40 ft', 4.6, 6.1], ['50×60 ft', 7.6, 9.1], ['60×100 ft', 9.1, 15.2], ['100×120 ft', 15.2, 18.3]] .map(([label, hw, hd]) => (
                    <button key={String(label)} onClick={() => fillQuickRect(Number(hw), Number(hd))}
                      className="px-2 py-1 rounded text-[9px] font-mono transition-all border"
                      style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', background: 'var(--surface-3)' }}>
                      {label}
                    </button>
                  ))}
                </div>

                <div className="space-y-1.5">
                  <div className="grid grid-cols-3 gap-1 text-[10px] font-mono text-[var(--text-secondary)] px-1">
                    <span>#</span><span>X (m east)</span><span>Y (m north)</span>
                  </div>
                  {Array.from({ length: numVertices }, (_, i) => {
                    const exX = ['-15','15','15','-15'][i] ?? '0';
                    const exY = ['-20','-20','20','20'][i] ?? '0';
                    return (
                    <div key={i} className="grid grid-cols-3 gap-1 items-center">
                      <span className="text-[10px] font-mono text-[var(--text-secondary)] text-center">{i + 1}</span>
                      <input
                        type="number" step="0.1"
                        placeholder={exX}
                        value={vertexInputs[i]?.x ?? ''}
                        onChange={(e) => {
                          const next = [...vertexInputs];
                          next[i] = { ...next[i], x: e.target.value };
                          setVertexInputs(next);
                        }}
                        className="bg-[var(--surface-3)] border border-[var(--border)] rounded px-2 py-1.5 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-gold)] font-mono w-full"
                      />
                      <input
                        type="number" step="0.1"
                        placeholder={exY}
                        value={vertexInputs[i]?.y ?? ''}
                        onChange={(e) => {
                          const next = [...vertexInputs];
                          next[i] = { ...next[i], y: e.target.value };
                          setVertexInputs(next);
                        }}
                        className="bg-[var(--surface-3)] border border-[var(--border)] rounded px-2 py-1.5 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-gold)] font-mono w-full"
                      />
                    </div>
                  );})}

                </div>
              </div>
            )}

            {shapeError && (
              <div className="text-[10px] font-mono text-[var(--accent-red)]">{shapeError}</div>
            )}

            <div className="flex gap-2">
              <button onClick={applyLandShape}
                className="flex-1 py-2 rounded-lg text-xs font-mono font-semibold transition-all"
                style={{ background: 'var(--accent-gold)', color: '#000' }}>
                Apply Shape
              </button>
              {drawnParcel && (
                <button onClick={() => setDrawnParcel(null)}
                  className="px-3 py-2 rounded-lg text-xs font-mono transition-all border"
                  style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)' }}>
                  Clear
                </button>
              )}
            </div>
            {drawnParcel && (
              <div className="text-[10px] font-mono text-[var(--accent-green)]">
                Parcel active · {parcelAreaSqft?.toLocaleString()} sqft
              </div>
            )}
          </div>
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
                  background: active ? 'rgba(196,168,130,0.12)' : 'var(--surface-3)',
                  borderColor: active ? 'var(--accent-gold)' : 'var(--border)',
                }}>
                <div className="text-lg mb-1" style={{ color: active ? 'var(--accent-gold)' : 'var(--text-secondary)' }}>{icon}</div>
                <div className="text-xs font-mono font-semibold" style={{ color: active ? 'var(--accent-gold)' : 'var(--text-primary)' }}>{label}</div>
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
                  background: active ? 'rgba(196,168,130,0.1)' : 'var(--surface-3)',
                  borderColor: active ? 'var(--accent-gold)' : 'var(--border)',
                }}>
                <div className="text-xs font-mono font-semibold" style={{ color: active ? 'var(--accent-gold)' : 'var(--text-primary)' }}>{label}</div>
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
                  background: active ? 'rgba(196,168,130,0.12)' : 'var(--surface-3)',
                  borderColor: active ? 'var(--accent-gold)' : 'var(--border)',
                  color: active ? 'var(--accent-gold)' : 'var(--text-secondary)',
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

      {/* Filing inputs determine which California code cycle can be evaluated. */}
      <div className="panel-section space-y-4">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">Preflight Basis</div>
        <Field label="Construction Scope">
          <Select
            value={constructionScope}
            onChange={(value) => updateSpec({ construction_scope: value as ConstructionScope })}
            options={['new_construction', 'addition', 'alteration']}
          />
        </Field>
        <Field label="Permit Application Date (optional)">
          <input
            type="date"
            min="2023-01-01"
            max="2028-12-31"
            value={permitApplicationDate}
            onChange={(event) => setPermitApplicationDate(event.target.value)}
            className="w-full bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-gold)] transition-colors font-mono"
          />
        </Field>
        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-3)] px-3 py-2">
          <div className="text-[10px] font-mono text-[var(--text-secondary)]">
            California code cycle: <span className="text-[var(--accent-gold)]">{codeCycle}</span>
          </div>
          <div className="text-[9px] font-mono text-[var(--text-secondary)] opacity-70 mt-1">
            Selected from supported 2023–2028 filing dates. With no filing date, the preliminary preflight uses the current 2025 cycle.
          </div>
        </div>
        {((spec as any).building_use || 'multi_family') === 'adu' && (
          <>
            <Field label="Primary Dwelling Sprinkler Requirement">
              <Select
                value={spec.primary_dwelling_sprinkler_requirement ?? 'unknown'}
                onChange={(value) => updateSpec({
                  primary_dwelling_sprinkler_requirement: value as PrimaryDwellingSprinklerRequirement,
                  primary_dwelling_sprinkler_determination_source: value === 'unknown'
                    ? null
                    : spec.primary_dwelling_sprinkler_determination_source,
                })}
                options={['unknown', 'required', 'not_required']}
              />
            </Field>
            {spec.primary_dwelling_sprinkler_requirement !== 'unknown' && (
              <Field label="Determination Source">
                <input
                  type="text"
                  value={spec.primary_dwelling_sprinkler_determination_source ?? ''}
                  onChange={(event) => updateSpec({
                    primary_dwelling_sprinkler_determination_source: event.target.value || null,
                  })}
                  placeholder="AHJ record, approved permit set, or written determination"
                  className="w-full bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-gold)] transition-colors font-mono"
                />
              </Field>
            )}
            <div className="text-[9px] font-mono text-[var(--text-secondary)] opacity-70">
              Whether sprinklers are installed is not, by itself, a legal determination that they are required.
            </div>
          </>
        )}
      </div>

      {/* Building parameters */}
      <div className="panel-section space-y-4">
        <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider">Building Parameters</div>

        {/* Bedrooms + Bathrooms — only shown for single-family / ADU */}
        {['single_family', 'adu'].includes((spec as any).building_use || 'multi_family') && (() => {
          const isAdu = (spec as any).building_use === 'adu';
          const br = (spec as any).bedrooms ?? (isAdu ? 1 : 3);
          const ba = (spec as any).bathrooms ?? (isAdu ? 1 : 2);
          const pri = (spec.priority || 'cost') as string;
          // ADU sqft ranges capped at CA legal limit of 1,200 sqft
          const ADU_SQFT: Record<number, [number, number]> = { 0: [300, 500], 1: [500, 800], 2: [700, 1200] };
          const [lo, hi] = isAdu ? (ADU_SQFT[br] ?? [500, 800]) : (SFR_SQFT_RANGES[br] ?? [1200, 1900]);
          const suggested = Math.min(isAdu ? 1200 : 99999, sfrTargetSqft(Math.max(1, br), pri));
          const baOptions = isAdu ? [1, 1.5, 2] : [1, 1.5, 2, 2.5, 3, 3.5];
          const brOptions = isAdu ? [0, 1, 2] : [1, 2, 3, 4, 5];
          return (
            <>
              <Field label={isAdu ? 'Bedrooms (Studio–2BR)' : 'Bedrooms (1–5)'}>
                <div className="flex gap-1.5">
                  {brOptions.map((n) => {
                    const active = br === n;
                    return (
                      <button key={n} onClick={() => updateSpec({ bedrooms: n } as any)}
                        className="flex-1 rounded-lg py-2 text-xs font-mono font-semibold transition-all border"
                        style={{
                          background: active ? 'rgba(196,168,130,0.12)' : 'var(--surface-3)',
                          borderColor: active ? 'var(--accent-gold)' : 'var(--border)',
                          color: active ? 'var(--accent-gold)' : 'var(--text-secondary)',
                        }}>
                        {n === 0 ? 'S' : n}
                      </button>
                    );
                  })}
                </div>
                <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70 mt-1">
                  {br === 0 ? 'Studio' : `${br}BR`} range: {lo.toLocaleString()}–{hi.toLocaleString()} sqft
                  {isAdu && <span className="ml-2 text-[var(--accent-amber)]">CA max 1,200 sqft</span>}
                  {!isAdu && <span className="ml-2 text-[var(--accent-gold)]">({pri} target: ~{suggested.toLocaleString()} sqft)</span>}
                </div>
              </Field>
              <Field label="Bathrooms">
                <div className="flex gap-1.5 flex-wrap">
                  {baOptions.map((n) => {
                    const active = ba === n;
                    return (
                      <button key={n} onClick={() => updateSpec({ bathrooms: n } as any)}
                        className="flex-1 rounded-lg py-2 text-xs font-mono font-semibold transition-all border"
                        style={{
                          background: active ? 'rgba(196,168,130,0.12)' : 'var(--surface-3)',
                          borderColor: active ? 'var(--accent-gold)' : 'var(--border)',
                          color: active ? 'var(--accent-gold)' : 'var(--text-secondary)',
                          minWidth: '2.5rem',
                        }}>
                        {n}
                      </button>
                    );
                  })}
                </div>
                <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70 mt-1">
                  {ba % 1 === 0
                    ? `${ba} full bath${ba > 1 ? 's' : ''} — toilet, sink, shower/tub`
                    : `${Math.floor(ba)} full + 1 half bath — half bath has toilet & sink only`}
                </div>
              </Field>
            </>
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
            {(() => {
              const buildingUseVal = (spec as any).building_use || 'multi_family';
              const isAduVal = buildingUseVal === 'adu';
              const isSfrVal = buildingUseVal === 'single_family';
              const platformCap = isAduVal ? 1200 : isSfrVal ? 5500 : null;
              const enteredArea = spec.target_gross_area_sqft;
              if (platformCap && enteredArea && enteredArea > platformCap) {
                return (
                  <div className="text-[10px] font-mono text-[var(--accent-amber)]">
                    ⚠ Will be capped at {platformCap.toLocaleString()} sqft at generation — {isAduVal ? 'CA ADU law (AB-68)' : 'platform SFR limit'}
                  </div>
                );
              }
              if (enteredArea && parcelAreaSqft) {
                const singleFloorMax = parcelAreaSqft * 0.85;
                const multiFloorMax = singleFloorMax * stories;
                if (enteredArea > multiFloorMax) {
                  return (
                    <div className="text-[10px] font-mono text-[var(--accent-red)]">
                      ✗ {enteredArea.toLocaleString()} sqft exceeds {stories}-floor max (~{Math.round(multiFloorMax).toLocaleString()} sqft) — add more floors or reduce target
                    </div>
                  );
                }
                if (enteredArea > singleFloorMax) {
                  const floorsNeeded = Math.ceil(enteredArea / singleFloorMax);
                  return (
                    <div className="text-[10px] font-mono text-[var(--accent-amber)]">
                      ⚠ Target needs ~{floorsNeeded} floors to fit on this parcel ({parcelAreaSqft.toLocaleString()} sqft land)
                    </div>
                  );
                }
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
                    <div className="text-[10px] font-mono pl-[7.5rem]" style={{ color: 'var(--accent-gold)', opacity: 0.75 }}>
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
            background: !canGenerate || loading ? 'var(--surface-3)' : hasBlockingIssues ? 'linear-gradient(135deg, #f59e0b, #ef4444)' : 'linear-gradient(135deg, #c4a882, #e8d5b0)',
            color: canGenerate && !loading ? '#0a0907' : 'var(--text-secondary)',
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
