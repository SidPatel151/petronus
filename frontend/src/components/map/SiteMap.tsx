'use client';
import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useAppStore } from '@/lib/store';
import api from '@/lib/api';

// ── Parcel helpers ───────────────────────────────────────────────────────────

function circleToPolygon(center: [number, number], radiusM: number, n = 64): any {
  const [lon, lat] = center;
  const pts: number[][] = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * 2 * Math.PI;
    const dLon = (radiusM / (111320 * Math.cos(lat * Math.PI / 180))) * Math.cos(a);
    const dLat = (radiusM / 111320) * Math.sin(a);
    pts.push([lon + dLon, lat + dLat]);
  }
  pts.push(pts[0]);
  return { type: 'Polygon', coordinates: [pts] };
}

function closedPolygon(vertices: [number, number][]): any {
  if (vertices.length < 3) return null;
  return { type: 'Polygon', coordinates: [[...vertices.map(([lon, lat]) => [lon, lat]), [vertices[0][0], vertices[0][1]]]] };
}

function polygonCentroid(coords: number[][]): [number, number] {
  const lon = coords.reduce((s, c) => s + c[0], 0) / coords.length;
  const lat = coords.reduce((s, c) => s + c[1], 0) / coords.length;
  return [lon, lat];
}

// Haversine distance in meters between two lat/lon points
function haversineDist(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const R = 6371000;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// Shoelace on projected coords (local meters) — accurate for any polygon shape
function calcAreaSqft(coords: number[][]): number {
  if (coords.length < 3) return 0;
  // Project to local meters using the polygon's centroid as origin
  const cLon = coords.reduce((s, c) => s + c[0], 0) / coords.length;
  const cLat = coords.reduce((s, c) => s + c[1], 0) / coords.length;
  const mPerDegLat = 111320;
  const mPerDegLon = 111320 * Math.cos(cLat * Math.PI / 180);
  // Shoelace in local meters
  let area = 0;
  const n = coords.length;
  for (let i = 0; i < n; i++) {
    const [x1, y1] = [(coords[i][0] - cLon) * mPerDegLon, (coords[i][1] - cLat) * mPerDegLat];
    const [x2, y2] = [(coords[(i + 1) % n][0] - cLon) * mPerDegLon, (coords[(i + 1) % n][1] - cLat) * mPerDegLat];
    area += x1 * y2 - x2 * y1;
  }
  return Math.abs(area) / 2 * 10.764; // m² → sqft
}

// For a polygon, detect if it's approximately rectangular and return {wFt, dFt}
function rectDimsFt(coords: number[][]): { wFt: number; dFt: number } | null {
  // Close the polygon and take the first 4 unique edges
  const pts = coords[coords.length - 1][0] === coords[0][0] && coords[coords.length - 1][1] === coords[0][1]
    ? coords.slice(0, -1) : coords;
  if (pts.length !== 4) return null;
  const sides = pts.map((p, i) => {
    const q = pts[(i + 1) % pts.length];
    return haversineDist(p[0], p[1], q[0], q[1]);
  });
  // A rectangle has opposite sides equal (within 2%)
  const [a, b, c, d] = sides;
  if (Math.abs(a - c) / Math.max(a, c) > 0.02 || Math.abs(b - d) / Math.max(b, d) > 0.02) return null;
  const w = Math.round((a + c) / 2 * 3.281);   // avg opposite sides → ft
  const dep = Math.round((b + d) / 2 * 3.281);
  return { wFt: w, dFt: dep };
}

function BuildingPopup({ building, onClose }: { building: any; onClose: () => void }) {
  const { siteContext } = useAppStore();
  const props = building.properties || {};
  const coords = building.geometry?.coordinates?.[0] || [];
  const footprintSqft = coords.length >= 3 ? calcAreaSqft(coords) : 0;
  const footprintM2 = footprintSqft / 10.764;
  const levelsNum = parseFloat(props['building:levels'] || props['levels'] || '1') || 1;
  const estLivingArea = footprintSqft * levelsNum;
  const parcelSqft = siteContext?.area_sqft || null;

  const buildingType = props['building'] || 'unknown';
  const levelsLabel = props['building:levels'] || props['levels'] || '?';
  const height = props['height_m'] ? `${Number(props['height_m']).toFixed(1)}m` : levelsLabel !== '?' ? `~${(Number(levelsLabel) * 3).toFixed(0)}m` : '?';
  const material = props['building:material'] || props['material'] || props['facade_mat'] || '—';
  const roofShape = props['roof:shape'] || props['roof_shape'] || '—';
  const roofMat = props['roof:material'] || '—';
  const power = props['power'] || props['utility'] || null;
  const name = props['name'] || props['addr:street'] ? `${props['addr:housenumber'] || ''} ${props['addr:street'] || ''}`.trim() : null;

  const typeLabel: Record<string, string> = {
    yes: 'Building', house: 'House', residential: 'Residential', apartments: 'Apartments',
    commercial: 'Commercial', retail: 'Retail', office: 'Office', industrial: 'Industrial',
    garage: 'Garage', shed: 'Shed', school: 'School', church: 'Church',
  };

  return (
    <div className="absolute bottom-24 left-4 z-50 panel p-4 w-72 animate-fade-in" style={{ maxHeight: '55vh', overflowY: 'auto' }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-[var(--accent-cyan)]" />
          <span className="text-xs font-mono font-semibold text-[var(--accent-cyan)] uppercase tracking-wider">
            {typeLabel[buildingType] || buildingType}
          </span>
        </div>
        <button onClick={onClose} className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-xs font-mono">✕</button>
      </div>

      {name && <div className="text-sm font-mono text-[var(--text-primary)] mb-3">{name}</div>}

      {/* Area breakdown */}
      <div className="bg-[var(--surface-3)] rounded-lg p-3 mb-3 space-y-1.5">
        <div className="text-[10px] font-mono text-[var(--text-secondary)] uppercase tracking-wider mb-1">Area (OSM footprint)</div>
        <div className="flex justify-between text-xs font-mono">
          <span className="text-[var(--text-secondary)]">Footprint</span>
          <span className="text-[var(--text-primary)]">{footprintSqft > 0 ? `${footprintSqft.toFixed(0)} sqft` : '—'}</span>
        </div>
        {levelsNum > 1 && (
          <div className="flex justify-between text-xs font-mono">
            <span className="text-[var(--text-secondary)]">Est. living ({levelsNum} floors)</span>
            <span className="text-[var(--accent-cyan)]">{estLivingArea.toFixed(0)} sqft</span>
          </div>
        )}
        {parcelSqft && (
          <div className="flex justify-between text-xs font-mono">
            <span className="text-[var(--text-secondary)]">Parcel (selected site)</span>
            <span className="text-[var(--accent-green)]">{parcelSqft.toFixed(0)} sqft</span>
          </div>
        )}
        <div className="text-[9px] font-mono text-[var(--text-secondary)] opacity-60 pt-1 border-t border-[var(--border)]">
          Note: OSM polygons are building outlines, not lot/parcel boundaries. For exact lot size use county assessor data.
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        {[
          { label: 'Stories', val: String(levelsLabel) },
          { label: 'Height', val: height },
          { label: 'Material', val: material },
          { label: 'Roof shape', val: roofShape },
          { label: 'Roof mat', val: roofMat },
          { label: 'Footprint m²', val: footprintM2 > 0 ? `${footprintM2.toFixed(0)} m²` : '—' },
        ].filter(r => r.val !== '—' && r.val !== '?').map(({ label, val }) => (
          <div key={label} className="bg-[var(--surface-3)] rounded-lg p-2">
            <div className="text-[10px] text-[var(--text-secondary)] font-mono">{label}</div>
            <div className="text-xs font-mono text-[var(--text-primary)] mt-0.5 truncate">{val}</div>
          </div>
        ))}
      </div>

      {/* Side clearances from building bbox */}
      {coords.length >= 3 && (() => {
        const xs = coords.map((c: number[]) => c[0]);
        const ys = coords.map((c: number[]) => c[1]);
        const wM = (Math.max(...xs) - Math.min(...xs)) * 111320 * Math.cos(37 * Math.PI / 180);
        const dM = (Math.max(...ys) - Math.min(...ys)) * 111320;
        const wFt = wM * 3.281;
        const dFt = dM * 3.281;
        return (
          <div className="bg-[var(--surface-3)] rounded-lg p-2 mb-3">
            <div className="text-[10px] text-[var(--text-secondary)] font-mono uppercase tracking-wider mb-1.5">Footprint Dimensions</div>
            <div className="flex gap-3 text-xs font-mono">
              <span className="text-[var(--accent-cyan)]">W: {wFt.toFixed(0)}ft ({wM.toFixed(1)}m)</span>
              <span className="text-[var(--accent-green)]">D: {dFt.toFixed(0)}ft ({dM.toFixed(1)}m)</span>
            </div>
          </div>
        );
      })()}

      {/* OSM tags for electrical/plumbing */}
      {(power || props['amenity'] || props['shop']) && (
        <div className="space-y-1">
          <div className="text-[10px] text-[var(--text-secondary)] font-mono uppercase tracking-wider">Utilities / Use</div>
          {power && <div className="text-xs font-mono text-[var(--accent-amber)]">⚡ Power: {power}</div>}
          {props['amenity'] && <div className="text-xs font-mono text-[var(--text-secondary)]">📍 {props['amenity']}</div>}
          {props['shop'] && <div className="text-xs font-mono text-[var(--text-secondary)]">🏪 {props['shop']}</div>}
        </div>
      )}

      <div className="mt-3 pt-2 border-t border-[var(--border)] text-[9px] font-mono text-[var(--text-secondary)] opacity-60">
        Source: OpenStreetMap · OSM ID: {props['osm_id'] || '—'}
      </div>
    </div>
  );
}

const MAP_LAYERS = [
  { id: 'buildings',     layers: ['buildings-fill','buildings-outline'],  color: '#334155', label: 'Buildings',       fill: true },
  { id: 'parcel',        layers: ['parcel-fill','parcel-line'],           color: '#00e5ff', label: 'Parcel',          dash: true },
  { id: 'buildable',     layers: ['buildable-fill','buildable-line'],     color: '#00ff88', label: 'Buildable zone' },
  { id: 'roads',         layers: ['roads-line'],                          color: '#ffb300', label: 'Roads' },
  { id: 'pipelines',     layers: ['pipes-line'],                          color: '#60a5fa', label: 'Sewage / Pipes',  dash: true },
  { id: 'power',         layers: ['power-line','power-connection-line'],  color: '#f59e0b', label: 'Power Lines' },
  { id: 'power_poles',   layers: ['power-poles-circle'],                  color: '#f59e0b', label: 'Power Poles',     circle: true },
  { id: 'power_plants',  layers: ['power-plants-circle'],                 color: '#fb923c', label: 'Power Plants',    circle: true },
  { id: 'hydrants',      layers: ['hydrants-circle'],                     color: '#ff4444', label: 'Fire Hydrants',   circle: true },
  { id: 'manholes',      layers: ['manholes-circle'],                     color: '#6b7280', label: 'Manholes',        circle: true },
  { id: 'places',        layers: ['places-circle'],                       color: '#94a3b8', label: 'Amenities',       circle: true },
];

function MapLayerToggles({ mapRef }: { mapRef: React.MutableRefObject<any> }) {
  const [visible, setVisible] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(MAP_LAYERS.map(l => [l.id, true]))
  );

  const toggle = (id: string) => {
    const map = mapRef.current;
    if (!map) return;
    const next = !visible[id];
    setVisible(v => ({ ...v, [id]: next }));
    const entry = MAP_LAYERS.find(l => l.id === id);
    entry?.layers.forEach(layerId => {
      if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', next ? 'visible' : 'none');
    });
  };

  return (
    <div className="absolute bottom-8 right-4 panel p-3 text-xs space-y-1 min-w-[160px]">
      <div className="text-[var(--text-secondary)] font-mono uppercase tracking-wider text-[10px] mb-2">Map Layers</div>
      {MAP_LAYERS.map(({ id, color, label, fill, dash, circle }) => (
        <button key={id} onClick={() => toggle(id)} className="flex items-center gap-2 w-full text-left py-0.5">
          {circle ? (
            <div className="w-2.5 h-2.5 rounded-full flex-shrink-0 transition-opacity" style={{ background: color, opacity: visible[id] ? 1 : 0.2 }} />
          ) : fill ? (
            <div className="w-4 h-2.5 rounded-sm flex-shrink-0 transition-opacity" style={{ background: color, opacity: visible[id] ? 0.7 : 0.15 }} />
          ) : (
            <div className="w-4 flex-shrink-0 transition-opacity" style={{ borderTop: `2px ${dash ? 'dashed' : 'solid'} ${color}`, opacity: visible[id] ? 1 : 0.2 }} />
          )}
          <span className="text-[11px] font-mono transition-colors"
            style={{ color: visible[id] ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
            {label}
          </span>
        </button>
      ))}
    </div>
  );
}

function LocationSearch({ onGo }: { onGo: (lat: number, lon: number) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Detect "lat, lon" or "lon, lat" coordinate patterns
  const parseCoords = (q: string): { lat: number; lon: number } | null => {
    const m = q.trim().match(/^(-?\d+\.?\d*)\s*[,\s]\s*(-?\d+\.?\d*)$/);
    if (!m) return null;
    const a = parseFloat(m[1]), b = parseFloat(m[2]);
    // Determine which is lat and which is lon by range
    if (a >= -90 && a <= 90 && b >= -180 && b <= 180) return { lat: a, lon: b };
    if (b >= -90 && b <= 90 && a >= -180 && a <= 180) return { lat: b, lon: a };
    return null;
  };

  const search = async (q: string) => {
    if (!q.trim() || q.trim().length < 3) { setResults([]); return; }

    // Direct coordinate input — show as immediate result, no API call
    const coords = parseCoords(q);
    if (coords) {
      setResults([{
        place_id: 'coords',
        lat: String(coords.lat), lon: String(coords.lon),
        display_name: `${coords.lat.toFixed(6)}, ${coords.lon.toFixed(6)}`,
        _isCoords: true,
      }]);
      setOpen(true);
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=5`,
        { headers: { 'Accept-Language': 'en' } }
      );
      const data = await res.json();
      setResults(data);
      setOpen(true);
    } catch { setResults([]); }
    setLoading(false);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value;
    setQuery(q);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(q), 400);
  };

  const pick = (r: any) => {
    onGo(parseFloat(r.lat), parseFloat(r.lon));
    // Show only the place name, never raw coordinates
    setQuery(r._isCoords ? '' : r.display_name.split(',').slice(0, 2).join(','));
    setOpen(false);
    setResults([]);
  };

  return (
    <div className="absolute top-3 left-1/2 -translate-x-1/2 z-50 w-80">
      <div className="relative flex items-center">
        <input
          value={query}
          onChange={handleChange}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder="Address, place, or lat, lon…"
          className="w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-lg px-3 py-2 pl-8 text-xs font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)] shadow-lg transition-colors"
          style={{ backdropFilter: 'blur(8px)' }}
        />
        <div className="absolute left-2.5 text-[var(--text-secondary)] pointer-events-none">
          {loading ? <span className="animate-spin inline-block">◌</span> : '⌕'}
        </div>
      </div>
      {open && results.length > 0 && (
        <div className="mt-1 bg-[var(--surface-1)] border border-[var(--border)] rounded-lg shadow-xl overflow-hidden">
          {results.map((r: any) => (
            <button
              key={r.place_id}
              onClick={() => pick(r)}
              className="w-full text-left px-3 py-2 text-xs font-mono hover:bg-[var(--surface-2)] transition-colors border-b border-[var(--border)] last:border-0"
            >
              {r._isCoords ? (
                <div className="flex items-center gap-2">
                  <span className="text-[var(--accent-cyan)] text-[10px]">⊕</span>
                  <div>
                    <div className="text-[var(--text-primary)]">Go to coordinates</div>
                    <div className="text-[10px] text-[var(--accent-cyan)] opacity-80">{r.display_name}</div>
                  </div>
                </div>
              ) : (
                <>
                  <div className="text-[var(--text-primary)] truncate">{r.display_name.split(',').slice(0, 2).join(',')}</div>
                  <div className="text-[10px] text-[var(--text-secondary)] opacity-60 truncate">{r.display_name}</div>
                </>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const CA_CENTER: [number, number] = [-119.4179, 36.7783];

const MAP_STYLE: any = {
  version: 8,
  sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap', maxzoom: 19 } },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
};

export default function SiteMap() {
  const mapRef = useRef<maplibregl.Map | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const [clickedBuilding, setClickedBuildingLocal] = useState<any | null>(null);

  // Parcel form state
  const [showParcelForm, setShowParcelForm] = useState(false);
  const [parcelType, setParcelType] = useState<'polygon' | 'circle' | 'map'>('polygon');
  const [parcelStep, setParcelStep] = useState<'count' | 'coords' | 'circle' | 'map'>('count');
  const [vertexCount, setVertexCount] = useState(4);
  const [vertexInputs, setVertexInputs] = useState<{ lat: string; lon: string }[]>([]);
  const [circleInput, setCircleInput] = useState({ lat: '', lon: '', radius: '', unit: 'ft' as 'ft' | 'm' });
  const [parcelError, setParcelError] = useState('');
  const [drawnArea, setDrawnArea] = useState<number | null>(null);
  const [drawnDims, setDrawnDims] = useState<string>('');
  const setDrawnParcelOnMapRef = useRef<(poly: any | null) => void>(() => {});

  // Interactive map-draw state
  const mapDrawActiveRef = useRef(false);
  const [mapDrawActive, setMapDrawActive] = useState(false);
  const mapDrawVertsRef = useRef<[number, number][]>([]); // [lon, lat]
  const [mapDrawVertCount, setMapDrawVertCount] = useState(0);
  const [coordsCopied, setCoordsCopied] = useState(false);
  const vertexMarkersRef = useRef<maplibregl.Marker[]>([]);
  const addMapVertexRef    = useRef<(lon: number, lat: number) => void>(() => {});
  const undoMapVertexRef   = useRef<() => void>(() => {});
  const clearMapDrawRef    = useRef<() => void>(() => {});
  const confirmMapParcelRef = useRef<() => Promise<void>>(async () => {});
  const updateDrawPreviewRef = useRef<() => void>(() => {});
  const typedPreviewMarkersRef = useRef<maplibregl.Marker[]>([]);
  const updateTypedPreviewRef = useRef<(inputs: { lat: string; lon: string }[]) => void>(() => {});
  const clearTypedPreviewRef  = useRef<() => void>(() => {});

  const { selectedSite, setSelectedSite, setSiteContext, setInfrastructure,
    setNeighborConstraints, setFeasibilityData, setClickedBuilding, setDrawnParcel } = useAppStore();

  const selectSiteRef = useRef<(lat: number, lon: number, parcelPolygon?: any) => void>(() => {});

  const setClickedBuilding2 = (b: any) => {
    setClickedBuildingLocal(b);
    setClickedBuilding(b);  // also update global store so AI chat can see it
  };

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({ container: containerRef.current, style: MAP_STYLE, center: CA_CENTER, zoom: 6 });
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.addControl(new maplibregl.ScaleControl(), 'bottom-left');

    map.on('load', () => {
      const emptyColl: any = { type: 'FeatureCollection', features: [] };
      ['hydrants', 'pipes', 'roads', 'power', 'parcel', 'buildable', 'buildings', 'power_connection', 'places', 'power_poles', 'manholes', 'power_plants',
       'drawn-parcel', 'draw-preview'].forEach(id => {
        map.addSource(id, { type: 'geojson', data: emptyColl });
      });

      map.addLayer({ id: 'buildings-fill', type: 'fill', source: 'buildings', paint: { 'fill-color': '#334155', 'fill-opacity': 0.5 } });
      map.addLayer({ id: 'buildings-outline', type: 'line', source: 'buildings', paint: { 'line-color': '#475569', 'line-width': 1 } });
      map.addLayer({ id: 'parcel-fill', type: 'fill', source: 'parcel', paint: { 'fill-color': '#00e5ff', 'fill-opacity': 0.08 } });
      map.addLayer({ id: 'parcel-line', type: 'line', source: 'parcel', paint: { 'line-color': '#00e5ff', 'line-width': 2, 'line-dasharray': [4, 2] } });
      map.addLayer({ id: 'buildable-fill', type: 'fill', source: 'buildable', paint: { 'fill-color': '#00ff88', 'fill-opacity': 0.12 } });
      map.addLayer({ id: 'buildable-line', type: 'line', source: 'buildable', paint: { 'line-color': '#00ff88', 'line-width': 1.5 } });
      map.addLayer({ id: 'roads-line', type: 'line', source: 'roads', paint: { 'line-color': '#ffb300', 'line-width': 1.5, 'line-opacity': 0.7 } });
      map.addLayer({ id: 'pipes-line', type: 'line', source: 'pipes', paint: { 'line-color': '#60a5fa', 'line-width': 1, 'line-dasharray': [3, 2] } });
      map.addLayer({ id: 'power-line', type: 'line', source: 'power', paint: { 'line-color': '#f59e0b', 'line-width': 1 } });
      map.addLayer({ id: 'hydrants-circle', type: 'circle', source: 'hydrants',
        paint: { 'circle-radius': 7, 'circle-color': '#ff4444', 'circle-stroke-width': 2, 'circle-stroke-color': '#fff', 'circle-opacity': 1 } });
      // Power grid connection line
      map.addLayer({ id: 'power-connection-line', type: 'line', source: 'power_connection',
        paint: { 'line-color': '#facc15', 'line-width': 2, 'line-dasharray': [4, 2], 'line-opacity': 0.9 } });
      // Nearby places (amenities, shops)
      map.addLayer({ id: 'places-circle', type: 'circle', source: 'places',
        paint: {
          'circle-radius': 4,
          'circle-color': [
            'match', ['get', 'place_type'],
            'restaurant', '#f97316',
            'cafe', '#a78bfa',
            'school', '#34d399',
            'hospital', '#f43f5e',
            'supermarket', '#60a5fa',
            'pharmacy', '#fb7185',
            '#94a3b8'
          ] as any,
          'circle-stroke-width': 1,
          'circle-stroke-color': '#fff',
          'circle-opacity': 0.85,
        }
      });

      // Power poles
      map.addLayer({ id: 'power-poles-circle', type: 'circle', source: 'power_poles',
        paint: { 'circle-radius': 5, 'circle-color': '#f59e0b', 'circle-stroke-width': 2, 'circle-stroke-color': '#1a1a24' } });
      // Manholes
      map.addLayer({ id: 'manholes-circle', type: 'circle', source: 'manholes',
        paint: { 'circle-radius': 4, 'circle-color': '#6b7280', 'circle-stroke-width': 1, 'circle-stroke-color': '#374151' } });
      // Power plants (larger, orange, colored by fuel type expression)
      map.addLayer({ id: 'power-plants-circle', type: 'circle', source: 'power_plants',
        paint: {
          'circle-radius': 10,
          'circle-color': [
            'match', ['get', 'fuel'],
            'Solar',   '#facc15',
            'Wind',    '#34d399',
            'Hydro',   '#38bdf8',
            'Nuclear', '#a78bfa',
            'Gas',     '#fb923c',
            'Coal',    '#6b7280',
            'Biomass', '#84cc16',
            '#fb923c',
          ] as any,
          'circle-stroke-width': 2,
          'circle-stroke-color': '#fff',
          'circle-opacity': 0.9,
        }
      });

      // ── Parcel overlay layers ─────────────────────────────────────────────
      map.addLayer({ id: 'drawn-parcel-fill', type: 'fill', source: 'drawn-parcel',
        paint: { 'fill-color': '#00e5ff', 'fill-opacity': 0.15 } });
      map.addLayer({ id: 'drawn-parcel-line', type: 'line', source: 'drawn-parcel',
        paint: { 'line-color': '#00e5ff', 'line-width': 3 } });
      // In-progress interactive draw preview
      map.addLayer({ id: 'draw-preview-fill', type: 'fill', source: 'draw-preview',
        paint: { 'fill-color': '#facc15', 'fill-opacity': 0.08 } });
      map.addLayer({ id: 'draw-preview-line', type: 'line', source: 'draw-preview',
        paint: { 'line-color': '#facc15', 'line-width': 2, 'line-dasharray': [4, 2] } });

      // Click on existing buildings → show info popup
      map.on('mouseenter', 'buildings-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'buildings-fill', () => { map.getCanvas().style.cursor = ''; });
      map.on('click', 'buildings-fill', (e: any) => {
        suppressMapClick = true;
        const f = e.features?.[0];
        if (f) setClickedBuilding2(f);
      });

      // Popups for hydrants, places, poles, manholes
      ['hydrants-circle', 'places-circle', 'power-poles-circle', 'manholes-circle'].forEach(layerId => {
        map.on('mouseenter', layerId, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', layerId, () => { map.getCanvas().style.cursor = ''; });
        map.on('click', layerId, (e: any) => {
          suppressMapClick = true;
          const f = e.features?.[0];
          if (!f) return;
          const props = f.properties || {};
          const coords = (f.geometry as any).coordinates;
          const label = layerId === 'hydrants-circle' ? '🚒 Fire Hydrant'
            : layerId === 'power-poles-circle' ? '⚡ Power Pole'
            : layerId === 'manholes-circle' ? '🔘 Manhole'
            : `📍 ${props.display_name || props.place_type || 'Place'}`;
          new maplibregl.Popup({ closeButton: false, className: 'petronus-popup' })
            .setLngLat(coords)
            .setHTML(`<div style="font-family:monospace;font-size:11px;background:#111118;color:#f0f0f8;padding:6px 8px;border-radius:6px;border:1px solid #2d2d3d">${label}</div>`)
            .addTo(map);
        });
      });

      // Power plant popups — larger detail card
      map.on('mouseenter', 'power-plants-circle', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'power-plants-circle', () => { map.getCanvas().style.cursor = ''; });
      map.on('click', 'power-plants-circle', (e: any) => {
        suppressMapClick = true;
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties || {};
        const coords = (f.geometry as any).coordinates;
        const fuelEmoji: Record<string, string> = {
          Solar: '☀️', Wind: '💨', Hydro: '💧', Nuclear: '⚛️',
          Gas: '🔥', Coal: '🏭', Biomass: '🌿',
        };
        const emoji = fuelEmoji[p.fuel] || '⚡';
        new maplibregl.Popup({ closeButton: true, className: 'petronus-popup' })
          .setLngLat(coords)
          .setHTML(`
            <div style="font-family:monospace;font-size:11px;background:#111118;color:#f0f0f8;padding:10px 12px;border-radius:8px;border:1px solid #2d2d3d;min-width:160px">
              <div style="font-size:13px;font-weight:600;margin-bottom:6px">${emoji} ${p.name || 'Power Plant'}</div>
              <div style="color:#94a3b8">Fuel: <span style="color:#fb923c">${p.fuel || '—'}</span></div>
              ${p.capacity_mw ? `<div style="color:#94a3b8">Capacity: <span style="color:#facc15">${Number(p.capacity_mw).toFixed(1)} MW</span></div>` : ''}
              <div style="margin-top:4px;font-size:9px;color:#475569">Source: CA Energy Commission</div>
            </div>
          `)
          .addTo(map);
      });
    });

    const setGeoJSON = (id: string, data: any) => {
      const src = map.getSource(id) as maplibregl.GeoJSONSource;
      if (src) src.setData(data);
    };

    // Prevent the generic map click from firing when a layer feature was clicked
    let suppressMapClick = false;

    const handleSiteSelect = async (lat: number, lng: number, drawnPolygon?: any) => {
      if (markerRef.current) markerRef.current.remove();
      const el = document.createElement('div');
      el.style.cssText = 'width:20px;height:20px;border-radius:50%;background:#00e5ff;border:3px solid white;box-shadow:0 0 12px rgba(0,229,255,0.6);';
      markerRef.current = new maplibregl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map);
      setSelectedSite({ lat, lon: lng });
      map.flyTo({ center: [lng, lat], zoom: 18, duration: 1000 });

      // Store drawn parcel in zustand so ProjectWizard can pass it to the API
      if (drawnPolygon) {
        setDrawnParcel(drawnPolygon);
      } else {
        setDrawnParcel(null);
      }

      try {
        const [ctx, infra] = await Promise.all([
          api.getSiteContext(lat, lng, drawnPolygon ?? undefined),
          api.getInfrastructure(lat, lng),
        ]);
        setSiteContext(ctx);
        setInfrastructure(infra);

        setGeoJSON('parcel', ctx.parcel_polygon ? { type: 'Feature', geometry: ctx.parcel_polygon, properties: {} } : { type: 'FeatureCollection', features: [] });
        setGeoJSON('buildable', ctx.buildable_envelope_2d ? { type: 'Feature', geometry: ctx.buildable_envelope_2d, properties: {} } : { type: 'FeatureCollection', features: [] });
        setGeoJSON('hydrants',         { type: 'FeatureCollection', features: infra.fire_hydrants   || [] });
        setGeoJSON('pipes',            { type: 'FeatureCollection', features: infra.pipelines       || [] });
        setGeoJSON('roads',            { type: 'FeatureCollection', features: infra.roads           || [] });
        setGeoJSON('power',            { type: 'FeatureCollection', features: infra.power_lines     || [] });
        setGeoJSON('buildings',        { type: 'FeatureCollection', features: infra.buildings       || [] });
        setGeoJSON('power_connection', infra.power_connection || { type: 'FeatureCollection', features: [] });
        setGeoJSON('places',           { type: 'FeatureCollection', features: infra.places          || [] });
        setGeoJSON('power_poles',      { type: 'FeatureCollection', features: infra.power_poles     || [] });
        setGeoJSON('manholes',         { type: 'FeatureCollection', features: infra.manholes        || [] });
        setGeoJSON('power_plants',     { type: 'FeatureCollection', features: (infra.power_plants || []).map((p: any) => ({
          type: 'Feature',
          geometry: p.geometry || { type: 'Point', coordinates: [lng, lat] },
          properties: p.properties || p,
        })) });

        const [neighbors] = await Promise.all([
          api.getNeighbors(lat, lng, ctx.parcel_polygon),
          api.getFeasibility(lat, lng, ctx.parcel_polygon)
            .then(feas => setFeasibilityData(feas))
            .catch(err => console.error('Feasibility error:', err)),
        ]);
        setNeighborConstraints(neighbors);

      } catch (err) {
        console.error('Site data error:', err);
      }
    };

    selectSiteRef.current = handleSiteSelect;

    // Expose parcel overlay updater to React state
    setDrawnParcelOnMapRef.current = (poly: any | null) => {
      const src = map.getSource('drawn-parcel') as maplibregl.GeoJSONSource;
      if (!src) return;
      src.setData(poly
        ? { type: 'Feature', geometry: poly, properties: {} }
        : { type: 'FeatureCollection', features: [] });
    };

    // ── Typed-coordinate live preview ───────────────────────────────────────

    clearTypedPreviewRef.current = () => {
      typedPreviewMarkersRef.current.forEach(m => m.remove());
      typedPreviewMarkersRef.current = [];
      if (!mapDrawActiveRef.current) {
        const src = map.getSource('draw-preview') as maplibregl.GeoJSONSource;
        src?.setData({ type: 'FeatureCollection', features: [] });
      }
    };

    updateTypedPreviewRef.current = (inputs) => {
      typedPreviewMarkersRef.current.forEach(m => m.remove());
      typedPreviewMarkersRef.current = [];
      const verts: [number, number][] = [];
      for (const inp of inputs) {
        const lat = parseFloat(inp.lat);
        const lon = parseFloat(inp.lon);
        if (!isNaN(lat) && !isNaN(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
          verts.push([lon, lat]);
          const el = document.createElement('div');
          el.style.cssText = 'width:10px;height:10px;border-radius:50%;background:#00e5ff;border:2px solid #fff;box-shadow:0 0 6px rgba(0,229,255,0.7);pointer-events:none;';
          typedPreviewMarkersRef.current.push(
            new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(map)
          );
        }
      }
      const src = map.getSource('draw-preview') as maplibregl.GeoJSONSource;
      if (!src) return;
      if (verts.length === 0) { src.setData({ type: 'FeatureCollection', features: [] }); return; }
      // Fly to first valid point if map is not already zoomed in
      if (verts.length === 1 && map.getZoom() < 14) {
        map.flyTo({ center: verts[0], zoom: 17, duration: 700 });
      }
      // Draw connecting line/polygon
      const ring = verts.length >= 3 ? [...verts, verts[0]] : verts;
      src.setData({
        type: 'Feature',
        geometry: verts.length >= 3
          ? { type: 'Polygon', coordinates: [ring] }
          : { type: 'LineString', coordinates: verts },
        properties: {},
      });
    };

    // ── Interactive map-draw helpers ────────────────────────────────────────

    const createVertexEl = () => {
      const el = document.createElement('div');
      el.style.cssText = 'width:14px;height:14px;border-radius:50%;background:#facc15;border:2px solid #fff;cursor:grab;box-shadow:0 0 8px rgba(250,204,21,0.7);';
      return el;
    };

    const updateDrawPreview = () => {
      const verts = mapDrawVertsRef.current;
      const src = map.getSource('draw-preview') as maplibregl.GeoJSONSource;
      if (!src) return;
      if (verts.length < 2) { src.setData({ type: 'FeatureCollection', features: [] }); return; }
      // Always close the ring visually when ≥3 vertices
      const ring = verts.length >= 3 ? [...verts, verts[0]] : verts;
      src.setData({
        type: 'Feature',
        geometry: verts.length >= 3
          ? { type: 'Polygon', coordinates: [ring] }
          : { type: 'LineString', coordinates: verts },
        properties: {},
      });
    };
    updateDrawPreviewRef.current = updateDrawPreview;

    addMapVertexRef.current = (lon, lat) => {
      const marker = new maplibregl.Marker({ element: createVertexEl(), draggable: true })
        .setLngLat([lon, lat])
        .addTo(map);
      marker.on('drag', () => {
        const pos = marker.getLngLat();
        const idx = vertexMarkersRef.current.indexOf(marker);
        if (idx >= 0) { mapDrawVertsRef.current[idx] = [pos.lng, pos.lat]; updateDrawPreview(); }
      });
      vertexMarkersRef.current.push(marker);
      mapDrawVertsRef.current = [...mapDrawVertsRef.current, [lon, lat]];
      setMapDrawVertCount(c => c + 1);
      updateDrawPreview();
    };

    undoMapVertexRef.current = () => {
      const last = vertexMarkersRef.current.pop();
      if (last) { last.remove(); mapDrawVertsRef.current = mapDrawVertsRef.current.slice(0, -1); setMapDrawVertCount(c => Math.max(0, c - 1)); updateDrawPreview(); }
    };

    clearMapDrawRef.current = () => {
      vertexMarkersRef.current.forEach(m => m.remove());
      vertexMarkersRef.current = [];
      mapDrawVertsRef.current = [];
      setMapDrawVertCount(0);
      updateDrawPreview();
    };

    confirmMapParcelRef.current = async () => {
      const verts = mapDrawVertsRef.current;
      if (verts.length < 3) return;
      const poly = closedPolygon(verts);
      if (!poly) return;
      const coords = poly.coordinates[0] as number[][];
      const [clon, clat] = polygonCentroid(coords);
      setDrawnArea(Math.round(calcAreaSqft(coords)));
      const rd = rectDimsFt(coords); setDrawnDims(rd ? `${rd.wFt}ft × ${rd.dFt}ft` : '');

      // Clear preview, show final parcel
      const previewSrc = map.getSource('draw-preview') as maplibregl.GeoJSONSource;
      previewSrc?.setData({ type: 'FeatureCollection', features: [] });
      vertexMarkersRef.current.forEach(m => m.remove());
      vertexMarkersRef.current = [];
      mapDrawVertsRef.current = [];
      setMapDrawVertCount(0);
      mapDrawActiveRef.current = false;
      setMapDrawActive(false);
      map.getCanvas().style.cursor = '';

      setDrawnParcelOnMapRef.current(poly);
      setDrawnParcel(poly);
      setShowParcelForm(false);
      setParcelStep('count');

      await handleSiteSelect(clat, clon, poly);
    };

    map.on('click', async (e) => {
      if (suppressMapClick) { suppressMapClick = false; return; }
      const { lng, lat } = e.lngLat;
      if (mapDrawActiveRef.current) {
        addMapVertexRef.current(lng, lat);
        return;
      }
      await handleSiteSelect(lat, lng);
    });

    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // Live map preview as user types polygon corner coordinates
  useEffect(() => {
    if (parcelStep === 'coords' && showParcelForm) {
      updateTypedPreviewRef.current(vertexInputs);
    } else {
      clearTypedPreviewRef.current();
    }
  }, [vertexInputs, parcelStep, showParcelForm]);

  return (
    <div className="relative w-full h-full">
      <div ref={containerRef} className="w-full h-full" />
      <LocationSearch onGo={(lat, lon) => selectSiteRef.current(lat, lon)} />

      {/* Selected site coordinates — moves to top-left when parcel form is open to avoid overlap */}
      {selectedSite && (
        <div className={`absolute z-50 panel px-3 py-1.5 flex items-center gap-2 animate-fade-in ${showParcelForm ? 'top-16 left-4' : 'bottom-36 left-4'}`}>
          <span className="text-[10px] font-mono text-[var(--text-secondary)] uppercase tracking-wider">Site</span>
          <span className="text-[11px] font-mono text-[var(--accent-cyan)]">
            {selectedSite.lat.toFixed(6)},&nbsp;{selectedSite.lon.toFixed(6)}
          </span>
          <button
            onClick={() => {
              navigator.clipboard.writeText(`${selectedSite.lat.toFixed(6)}, ${selectedSite.lon.toFixed(6)}`);
              setCoordsCopied(true);
              setTimeout(() => setCoordsCopied(false), 1500);
            }}
            className="text-[10px] font-mono px-1.5 py-0.5 rounded transition-colors"
            style={{ color: coordsCopied ? 'var(--accent-green)' : 'var(--text-secondary)', border: '1px solid var(--border)' }}
          >
            {coordsCopied ? 'copied' : 'copy'}
          </button>
        </div>
      )}

      {clickedBuilding && <BuildingPopup building={clickedBuilding} onClose={() => { setClickedBuildingLocal(null); setClickedBuilding(null); }} />}

      {/* Utility Layer Toggles */}
      <MapLayerToggles mapRef={mapRef} />

      {/* Define Land Parcel button + form */}
      <div className="absolute bottom-20 left-4 z-50 flex flex-col items-start gap-2">
        {!showParcelForm ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setShowParcelForm(true);
                setParcelStep(parcelType === 'circle' ? 'circle' : parcelType === 'map' ? 'map' : 'count');
                setParcelError('');
              }}
              className="panel px-3 py-2 text-[11px] font-mono flex items-center gap-1.5 hover:border-[var(--accent-cyan)] transition-colors"
              style={{ borderColor: drawnArea ? 'var(--accent-cyan)' : 'var(--border)' }}
            >
              <span style={{ color: drawnArea ? 'var(--accent-cyan)' : 'var(--text-secondary)' }}>⬡</span>
              <span style={{ color: drawnArea ? 'var(--accent-cyan)' : 'var(--text-primary)' }}>
                {drawnArea
                  ? `${drawnDims ? drawnDims + ' · ' : ''}${drawnArea.toLocaleString()} sqft`
                  : 'Define Land Shape'}
              </span>
            </button>
            {drawnArea && (
              <button
                onClick={() => {
                  setDrawnParcelOnMapRef.current(null);
                  setDrawnArea(null);
                  setDrawnDims('');
                  setDrawnParcel(null);
                }}
                className="text-[10px] font-mono text-[var(--text-secondary)] hover:text-[#f87171]"
              >
                clear
              </button>
            )}
          </div>
        ) : (
          <div className="panel p-4 w-80 flex flex-col gap-3">
            {/* Header */}
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono font-semibold text-[var(--text-primary)] uppercase tracking-wider">
                Define Land Shape
              </span>
              <button onClick={() => {
                  if (mapDrawActiveRef.current) {
                    mapDrawActiveRef.current = false;
                    setMapDrawActive(false);
                    clearMapDrawRef.current();
                    mapRef.current?.getCanvas().style.cursor != null && (mapRef.current!.getCanvas().style.cursor = '');
                  }
                  setShowParcelForm(false);
                  setParcelStep('count');
                  setParcelError('');
                }}
                className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-xs font-mono">✕</button>
            </div>

            {/* Shape type tabs */}
            {parcelStep !== 'coords' && (
              <div className="flex gap-1.5">
                {([
                  { key: 'polygon', label: '⬡ Type' },
                  { key: 'circle',  label: '◯ Circle' },
                  { key: 'map',     label: '📍 Click Map' },
                ] as const).map(({ key, label }) => (
                  <button key={key}
                    onClick={() => {
                      setParcelType(key);
                      setParcelError('');
                      if (key === 'circle') { setParcelStep('circle'); }
                      else if (key === 'map') { setParcelStep('map'); }
                      else { setParcelStep('count'); }
                    }}
                    className="flex-1 py-1.5 rounded-lg text-[10px] font-mono font-semibold transition-all border"
                    style={{
                      background: parcelType === key ? 'rgba(0,229,255,0.1)' : 'var(--surface-3)',
                      borderColor: parcelType === key ? 'var(--accent-cyan)' : 'var(--border)',
                      color: parcelType === key ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                    }}>
                    {label}
                  </button>
                ))}
              </div>
            )}

            {/* POLYGON — step: count */}
            {parcelStep === 'count' && (
              <>
                <div className="text-[11px] font-mono text-[var(--text-secondary)]">
                  How many corners does your land have?
                </div>
                <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-60">
                  e.g. 4 = square/rectangle · 3 = triangle · 5+ = irregular
                </div>
                <div className="flex gap-2">
                  {[3, 4, 5, 6].map(n => (
                    <button key={n} onClick={() => setVertexCount(n)}
                      className="flex-1 py-2 rounded-lg text-xs font-mono font-semibold transition-all border"
                      style={{
                        background: vertexCount === n ? 'rgba(0,229,255,0.1)' : 'var(--surface-3)',
                        borderColor: vertexCount === n ? 'var(--accent-cyan)' : 'var(--border)',
                        color: vertexCount === n ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                      }}>{n}</button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono text-[var(--text-secondary)]">Custom:</span>
                  <input type="number" min={3} max={20} value={vertexCount}
                    onChange={e => setVertexCount(Math.max(3, Math.min(20, parseInt(e.target.value) || 4)))}
                    className="w-20 bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-2 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)] font-mono" />
                </div>
                <button
                  onClick={() => {
                    setVertexInputs(Array.from({ length: vertexCount }, () => ({ lat: '', lon: '' })));
                    setParcelStep('coords');
                    setParcelError('');
                  }}
                  className="w-full py-2 rounded-lg text-xs font-mono font-semibold"
                  style={{ background: 'linear-gradient(135deg, #00e5ff, #00ff88)', color: '#000' }}>
                  Next → Enter {vertexCount} Corners
                </button>
              </>
            )}

            {/* POLYGON — step: coords */}
            {parcelStep === 'coords' && (
              <>
                <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70">
                  Enter lat, lon for each corner going around the boundary
                </div>
                <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                  {vertexInputs.map((v, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-[var(--text-secondary)] w-14 flex-shrink-0">
                        Corner {i + 1}
                      </span>
                      <input type="text" placeholder="lat" value={v.lat}
                        onChange={e => setVertexInputs(vi => vi.map((x, j) => j === i ? { ...x, lat: e.target.value } : x))}
                        className="flex-1 bg-[var(--surface-3)] border border-[var(--border)] rounded px-2 py-1 text-[11px] font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)] min-w-0"
                      />
                      <input type="text" placeholder="lon" value={v.lon}
                        onChange={e => setVertexInputs(vi => vi.map((x, j) => j === i ? { ...x, lon: e.target.value } : x))}
                        className="flex-1 bg-[var(--surface-3)] border border-[var(--border)] rounded px-2 py-1 text-[11px] font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)] min-w-0"
                      />
                    </div>
                  ))}
                </div>
                {parcelError && <div className="text-[10px] font-mono text-[#f87171]">{parcelError}</div>}
                <div className="flex gap-2">
                  <button onClick={() => { clearTypedPreviewRef.current(); setParcelStep('count'); setParcelError(''); }}
                    className="flex-1 py-2 rounded-lg text-xs font-mono border"
                    style={{ background: 'var(--surface-3)', borderColor: 'var(--border)', color: 'var(--text-secondary)' }}>
                    ← Back
                  </button>
                  <button
                    onClick={async () => {
                      const verts: [number, number][] = [];
                      for (let i = 0; i < vertexInputs.length; i++) {
                        const lat = parseFloat(vertexInputs[i].lat);
                        const lon = parseFloat(vertexInputs[i].lon);
                        if (isNaN(lat) || isNaN(lon)) { setParcelError(`Corner ${i + 1}: enter valid numbers`); return; }
                        if (lat < -90 || lat > 90) { setParcelError(`Corner ${i + 1}: lat must be −90 to 90`); return; }
                        if (lon < -180 || lon > 180) { setParcelError(`Corner ${i + 1}: lon must be −180 to 180`); return; }
                        verts.push([lon, lat]);
                      }
                      const poly = closedPolygon(verts);
                      if (!poly) { setParcelError('Need at least 3 valid corners'); return; }
                      const coords = poly.coordinates[0] as number[][];
                      const [clon, clat] = polygonCentroid(coords);
                      setDrawnArea(Math.round(calcAreaSqft(coords)));
                      const rd = rectDimsFt(coords); setDrawnDims(rd ? `${rd.wFt}ft × ${rd.dFt}ft` : '');
                      setDrawnParcelOnMapRef.current(poly);
                      setDrawnParcel(poly);
                      setShowParcelForm(false);
                      setParcelStep('count');
                      setParcelError('');
                      await selectSiteRef.current(clat, clon, poly);
                    }}
                    className="flex-1 py-2 rounded-lg text-xs font-mono font-semibold"
                    style={{ background: 'linear-gradient(135deg, #00e5ff, #00ff88)', color: '#000' }}>
                    Confirm Parcel
                  </button>
                </div>
              </>
            )}

            {/* CIRCLE */}
            {parcelStep === 'circle' && (
              <>
                <div className="text-[11px] font-mono text-[var(--text-secondary)]">
                  Enter the center of the circular land area and its radius.
                </div>
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-[var(--text-secondary)] w-14 flex-shrink-0">Center lat</span>
                    <input type="text" placeholder="e.g. 34.0522" value={circleInput.lat}
                      onChange={e => setCircleInput(c => ({ ...c, lat: e.target.value }))}
                      className="flex-1 bg-[var(--surface-3)] border border-[var(--border)] rounded px-2 py-1.5 text-[11px] font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)]"
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-[var(--text-secondary)] w-14 flex-shrink-0">Center lon</span>
                    <input type="text" placeholder="e.g. -118.2437" value={circleInput.lon}
                      onChange={e => setCircleInput(c => ({ ...c, lon: e.target.value }))}
                      className="flex-1 bg-[var(--surface-3)] border border-[var(--border)] rounded px-2 py-1.5 text-[11px] font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)]"
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-[var(--text-secondary)] w-14 flex-shrink-0">Radius</span>
                    <input type="text" placeholder="e.g. 100" value={circleInput.radius}
                      onChange={e => setCircleInput(c => ({ ...c, radius: e.target.value }))}
                      className="flex-1 bg-[var(--surface-3)] border border-[var(--border)] rounded px-2 py-1.5 text-[11px] font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)] min-w-0"
                    />
                    <div className="flex rounded overflow-hidden border border-[var(--border)]">
                      {(['ft', 'm'] as const).map(u => (
                        <button key={u} onClick={() => setCircleInput(c => ({ ...c, unit: u }))}
                          className="px-2 py-1.5 text-[10px] font-mono transition-colors"
                          style={{
                            background: circleInput.unit === u ? 'var(--accent-cyan)' : 'var(--surface-3)',
                            color: circleInput.unit === u ? '#000' : 'var(--text-secondary)',
                          }}>{u}</button>
                      ))}
                    </div>
                  </div>
                </div>
                {parcelError && <div className="text-[10px] font-mono text-[#f87171]">{parcelError}</div>}
                <button
                  onClick={async () => {
                    const lat = parseFloat(circleInput.lat);
                    const lon = parseFloat(circleInput.lon);
                    const r = parseFloat(circleInput.radius);
                    if (isNaN(lat) || lat < -90 || lat > 90) { setParcelError('Enter a valid center latitude (−90 to 90)'); return; }
                    if (isNaN(lon) || lon < -180 || lon > 180) { setParcelError('Enter a valid center longitude (−180 to 180)'); return; }
                    if (isNaN(r) || r <= 0) { setParcelError('Enter a positive radius'); return; }
                    const radiusM = circleInput.unit === 'ft' ? r * 0.3048 : r;
                    const poly = circleToPolygon([lon, lat], radiusM);
                    const areaM2 = Math.PI * radiusM * radiusM;
                    setDrawnArea(Math.round(areaM2 * 10.764));
                    const rFt = Math.round(radiusM * 3.281); setDrawnDims(`r=${rFt}ft`);
                    setDrawnParcelOnMapRef.current(poly);
                    setDrawnParcel(poly);
                    setShowParcelForm(false);
                    setParcelStep('count');
                    setParcelError('');
                    await selectSiteRef.current(lat, lon, poly);
                  }}
                  className="w-full py-2 rounded-lg text-xs font-mono font-semibold"
                  style={{ background: 'linear-gradient(135deg, #00e5ff, #00ff88)', color: '#000' }}>
                  Confirm Circle Parcel
                </button>
              </>
            )}

            {/* CLICK MAP */}
            {parcelStep === 'map' && (
              <>
                {!mapDrawActive ? (
                  <>
                    <div className="text-[11px] font-mono text-[var(--text-secondary)]">
                      Click points on the map to define each corner of your land. Drag any point to adjust it.
                    </div>
                    <button
                      onClick={() => {
                        mapDrawActiveRef.current = true;
                        setMapDrawActive(true);
                        clearMapDrawRef.current();
                        mapRef.current?.getCanvas().classList.add('cursor-crosshair');
                        mapRef.current!.getCanvas().style.cursor = 'crosshair';
                      }}
                      className="w-full py-2 rounded-lg text-xs font-mono font-semibold"
                      style={{ background: 'linear-gradient(135deg, #00e5ff, #00ff88)', color: '#000' }}>
                      Start Clicking Corners
                    </button>
                  </>
                ) : (
                  <>
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-mono text-[var(--accent-cyan)]">
                        {mapDrawVertCount} corner{mapDrawVertCount !== 1 ? 's' : ''} placed
                      </span>
                      <button
                        onClick={() => undoMapVertexRef.current()}
                        disabled={mapDrawVertCount === 0}
                        className="text-[10px] font-mono px-2 py-1 rounded border transition-colors"
                        style={{ borderColor: 'var(--border)', color: mapDrawVertCount > 0 ? 'var(--accent-amber, #f59e0b)' : 'var(--text-secondary)', background: 'var(--surface-3)' }}>
                        ↩ Undo
                      </button>
                    </div>
                    {mapDrawVertCount >= 3 ? (
                      <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70">
                        Shape ready — confirm or keep adding corners
                      </div>
                    ) : (
                      <div className="text-[10px] font-mono text-[var(--text-secondary)] opacity-70">
                        Need at least {3 - mapDrawVertCount} more corner{3 - mapDrawVertCount !== 1 ? 's' : ''}
                      </div>
                    )}
                    {parcelError && <div className="text-[10px] font-mono text-[#f87171]">{parcelError}</div>}
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          mapDrawActiveRef.current = false;
                          setMapDrawActive(false);
                          clearMapDrawRef.current();
                          mapRef.current!.getCanvas().style.cursor = '';
                          setParcelError('');
                        }}
                        className="flex-1 py-2 rounded-lg text-xs font-mono border"
                        style={{ background: 'var(--surface-3)', borderColor: 'var(--border)', color: 'var(--text-secondary)' }}>
                        Cancel
                      </button>
                      <button
                        onClick={async () => {
                          if (mapDrawVertCount < 3) { setParcelError('Place at least 3 corners first'); return; }
                          await confirmMapParcelRef.current();
                        }}
                        className="flex-1 py-2 rounded-lg text-xs font-mono font-semibold"
                        style={{
                          background: mapDrawVertCount >= 3 ? 'linear-gradient(135deg, #00e5ff, #00ff88)' : 'var(--surface-3)',
                          color: mapDrawVertCount >= 3 ? '#000' : 'var(--text-secondary)',
                          border: mapDrawVertCount < 3 ? '1px solid var(--border)' : 'none',
                        }}>
                        Confirm Parcel
                      </button>
                    </div>
                  </>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {!selectedSite && !showParcelForm && (
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none">
          <div className="panel px-6 py-4 text-center animate-pulse-slow">
            <div className="text-[var(--accent-cyan)] font-display text-lg font-semibold text-glow-cyan">
              Click anywhere in California
            </div>
            <div className="text-[var(--text-secondary)] text-sm mt-1">
              Or use "Define Land Shape" to enter your parcel boundary
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
