'use client';
import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useAppStore } from '@/lib/store';
import api from '@/lib/api';

function calcAreaSqft(coords: number[][]): number {
  // Shoelace formula on lat/lon → approx sqft
  let area = 0;
  const n = coords.length;
  for (let i = 0; i < n; i++) {
    const [x1, y1] = coords[i];
    const [x2, y2] = coords[(i + 1) % n];
    area += x1 * y2 - x2 * y1;
  }
  const areaLatLon = Math.abs(area) / 2;
  // Convert deg² → m² → sqft (at ~37°N)
  const m2 = areaLatLon * 111320 * 111320 * Math.cos(37 * Math.PI / 180);
  return m2 * 10.764;
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
  const { selectedSite, setSelectedSite, setSiteContext, setInfrastructure, setNeighborConstraints, setFeasibilityData, setClickedBuilding } = useAppStore();

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
      ['hydrants', 'pipes', 'roads', 'power', 'parcel', 'buildable', 'buildings', 'power_connection', 'places'].forEach(id => {
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

      // Click on existing buildings → show info popup
      map.on('mouseenter', 'buildings-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'buildings-fill', () => { map.getCanvas().style.cursor = ''; });
      map.on('click', 'buildings-fill', (e: any) => {
        e.preventDefault();
        e.stopPropagation?.();
        const f = e.features?.[0];
        if (f) setClickedBuilding2(f);
      });

      // Popups for hydrants and places
      ['hydrants-circle', 'places-circle', 'power-poles-circle'].forEach(layerId => {
        map.on('mouseenter', layerId, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', layerId, () => { map.getCanvas().style.cursor = ''; });
        map.on('click', layerId, (e: any) => {
          e.preventDefault();
          const f = e.features?.[0];
          if (!f) return;
          const props = f.properties || {};
          const coords = (f.geometry as any).coordinates;
          const label = layerId === 'hydrants-circle' ? '🚒 Fire Hydrant'
            : layerId === 'power-poles-circle' ? '⚡ Power Pole'
            : `📍 ${props.display_name || props.place_type || 'Place'}`;
          new maplibregl.Popup({ closeButton: false, className: 'petronus-popup' })
            .setLngLat(coords)
            .setHTML(`<div style="font-family:monospace;font-size:11px;background:#111118;color:#f0f0f8;padding:6px 8px;border-radius:6px;border:1px solid #2d2d3d">${label}</div>`)
            .addTo(map);
        });
      });
    });

    const setGeoJSON = (id: string, data: any) => {
      const src = map.getSource(id) as maplibregl.GeoJSONSource;
      if (src) src.setData(data);
    };

    map.on('click', async (e) => {
      const { lng, lat } = e.lngLat;

      if (markerRef.current) markerRef.current.remove();
      const el = document.createElement('div');
      el.style.cssText = 'width:20px;height:20px;border-radius:50%;background:#00e5ff;border:3px solid white;box-shadow:0 0 12px rgba(0,229,255,0.6);';
      markerRef.current = new maplibregl.Marker({ element: el }).setLngLat([lng, lat]).addTo(map);
      setSelectedSite({ lat, lon: lng });
      map.flyTo({ center: [lng, lat], zoom: 18, duration: 1000 });

      try {
        const [ctx, infra] = await Promise.all([
          api.getSiteContext(lat, lng),
          api.getInfrastructure(lat, lng),
        ]);
        setSiteContext(ctx);
        setInfrastructure(infra);

        // Always update — clears stale data from previous site clicks
        setGeoJSON('parcel', ctx.parcel_polygon ? { type: 'Feature', geometry: ctx.parcel_polygon, properties: {} } : { type: 'FeatureCollection', features: [] });
        setGeoJSON('buildable', ctx.buildable_envelope_2d ? { type: 'Feature', geometry: ctx.buildable_envelope_2d, properties: {} } : { type: 'FeatureCollection', features: [] });
        setGeoJSON('hydrants',         { type: 'FeatureCollection', features: infra.fire_hydrants   || [] });
        setGeoJSON('pipes',            { type: 'FeatureCollection', features: infra.pipelines       || [] });
        setGeoJSON('roads',            { type: 'FeatureCollection', features: infra.roads           || [] });
        setGeoJSON('power',            { type: 'FeatureCollection', features: infra.power_lines     || [] });
        setGeoJSON('buildings',        { type: 'FeatureCollection', features: infra.buildings       || [] });
        setGeoJSON('power_connection', infra.power_connection || { type: 'FeatureCollection', features: [] });
        setGeoJSON('places',           { type: 'FeatureCollection', features: infra.places          || [] });
        // Power poles as separate circles
        if (!map.getSource('power_poles')) {
          map.addSource('power_poles', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
          map.addLayer({ id: 'power-poles-circle', type: 'circle', source: 'power_poles',
            paint: { 'circle-radius': 5, 'circle-color': '#f59e0b', 'circle-stroke-width': 2, 'circle-stroke-color': '#1a1a24' } });
        }
        (map.getSource('power_poles') as maplibregl.GeoJSONSource)?.setData({ type: 'FeatureCollection', features: infra.power_poles || [] });
        // Manholes
        if (!map.getSource('manholes')) {
          map.addSource('manholes', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
          map.addLayer({ id: 'manholes-circle', type: 'circle', source: 'manholes',
            paint: { 'circle-radius': 4, 'circle-color': '#6b7280', 'circle-stroke-width': 1, 'circle-stroke-color': '#374151' } });
        }
        (map.getSource('manholes') as maplibregl.GeoJSONSource)?.setData({ type: 'FeatureCollection', features: infra.manholes || [] });

        // Fetch neighbors and legal feasibility in parallel
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
    });

    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  return (
    <div className="relative w-full h-full">
      <div ref={containerRef} className="w-full h-full" />
      {clickedBuilding && <BuildingPopup building={clickedBuilding} onClose={() => { setClickedBuildingLocal(null); setClickedBuilding(null); }} />}

      {/* Legend */}
      <div className="absolute bottom-8 right-4 panel p-3 text-xs space-y-1.5">
        <div className="text-[var(--text-secondary)] font-mono uppercase tracking-wider mb-2">Legend</div>
        {[
          { color: '#334155', label: 'Existing buildings', fill: true },
          { color: '#00e5ff', label: 'Parcel boundary', dash: true },
          { color: '#00ff88', label: 'Buildable envelope' },
          { color: '#ffb300', label: 'Roads' },
          { color: '#60a5fa', label: 'Pipelines' },
          { color: '#f59e0b', label: 'Power lines' },
          { color: '#facc15', label: 'Power grid connection', dash: true },
          { color: '#ff4444', label: 'Fire hydrants', circle: true },
          { color: '#94a3b8', label: 'Nearby places', circle: true },
        ].map((item) => (
          <div key={item.label} className="flex items-center gap-2">
            {item.circle ? (
              <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ background: item.color }} />
            ) : item.fill ? (
              <div className="w-5 h-3 rounded-sm flex-shrink-0 opacity-60" style={{ background: item.color }} />
            ) : (
              <div className="w-5 flex-shrink-0" style={{ borderTop: `2px ${item.dash ? 'dashed' : 'solid'} ${item.color}` }} />
            )}
            <span className="text-[var(--text-secondary)]">{item.label}</span>
          </div>
        ))}
      </div>

      {!selectedSite && (
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none">
          <div className="panel px-6 py-4 text-center animate-pulse-slow">
            <div className="text-[var(--accent-cyan)] font-display text-lg font-semibold text-glow-cyan">
              Click anywhere in California
            </div>
            <div className="text-[var(--text-secondary)] text-sm mt-1">
              Fetches real buildings, pipes, hydrants, power lines + neighbor analysis
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
