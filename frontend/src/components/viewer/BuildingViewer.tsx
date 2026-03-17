'use client';
import { useRef, useMemo, Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid } from '@react-three/drei';
import * as THREE from 'three';
import { useAppStore, LayerKey } from '@/lib/store';
import { getTexture, resolveTexture } from '@/lib/textures';

const COLORS: Record<string, string> = {
  unit: '#1e3a5f', living: '#1e3a5f', bedroom: '#1a3352',
  bathroom: '#0f2040', kitchen: '#162d4a', corridor: '#0d1f33', stair: '#0a1a2e',
  wall_exterior: '#334155', wall_interior: '#1e293b', wall_shear: '#7c3aed',
  plumbing: '#3b82f6', electrical: '#f59e0b', hvac: '#10b981',
  fixture: '#60a5fa', panel: '#fbbf24', mini_split_head: '#34d399',
  issue_error: '#ef4444', issue_warning: '#f59e0b',
  neighbor: '#2d3748', neighbor_existing: '#7c3aed',
};

const MATERIAL_COLORS: Record<string, string> = {
  wood:     '#8B6914',
  steel:    '#6B7B8D',
  concrete: '#8C8C8C',
};

// ── Room: extrude polygon on XZ plane, Y is up ─────────────────────────
function RoomMesh({ room, matColor, texName, roughness, metalness }: {
  room: any; matColor: string; texName?: string; roughness?: number; metalness?: number;
}) {
  if (!room.polygon?.length) return null;
  const isStructural = ['unit', 'corridor', 'stair'].includes(room.type);
  const geometry = useMemo(() => {
    try {
      const shape = new THREE.Shape();
      const pts = room.polygon;
      shape.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) shape.lineTo(pts[i][0], pts[i][1]);
      shape.closePath();
      const depth = ['unit', 'corridor', 'stair'].includes(room.type) ? 2.8 : 0.12;
      const geo = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      return geo;
    } catch { return null; }
  }, [room.polygon, room.type]);

  const texture = useMemo(() => {
    if (room.type !== 'unit' || !texName) return null;
    try { return getTexture(texName); } catch { return null; }
  }, [texName, room.type]);

  if (!geometry) return null;
  const subRoomColors: Record<string,string> = {
    bedroom: '#1a3a5c', living: '#1e3a4a', kitchen: '#2a3a2a',
    bathroom: '#1a2a3a', dining: '#2a2a1a',
  };
  const color = room.type === 'unit' ? matColor : subRoomColors[room.type] || COLORS[room.type] || '#1a2030';
  const yBase = (room.level || 0) * 3.0;

  return (
    <mesh geometry={geometry} position={[0, yBase, 0]} receiveShadow castShadow>
      <meshStandardMaterial
        map={texture ?? undefined}
        color={texture ? '#ffffff' : color}
        transparent opacity={isStructural ? 0.92 : 0.75}
        roughness={roughness ?? 0.85}
        metalness={metalness ?? 0.0}
      />
    </mesh>
  );
}

// ── Wall ───────────────────────────────────────────────────────────────
function WallMesh({ wall, matColor, texName, roughness, metalness }: {
  wall: any; matColor: string; texName?: string; roughness?: number; metalness?: number;
}) {
  const s = wall.start, e = wall.end;
  if (!s || !e) return null;
  const dx = e[0] - s[0], dz = e[1] - s[1];
  const length = Math.sqrt(dx * dx + dz * dz);
  if (length < 0.01) return null;

  const texture = useMemo(() => {
    if (!wall.is_exterior || !texName) return null;
    try { return getTexture(texName); } catch { return null; }
  }, [texName, wall.is_exterior]);

  const height = (wall.height_ft || 9) * 0.3048;
  const angle = Math.atan2(dz, dx);
  const cx = (s[0] + e[0]) / 2, cz = (s[1] + e[1]) / 2;
  const yBase = (wall.level || 0) * 3.0 + height / 2;
  const color = wall.is_shear ? COLORS.wall_shear : wall.is_exterior ? matColor : COLORS.wall_interior;

  return (
    <mesh position={[cx, yBase, cz]} rotation={[0, -angle, 0]} castShadow>
      <boxGeometry args={[length, height, 0.2]} />
      <meshStandardMaterial
        map={texture ?? undefined}
        color={texture && wall.is_exterior ? '#ffffff' : color}
        roughness={roughness ?? 0.9}
        metalness={metalness ?? 0.0}
      />
    </mesh>
  );
}

// ── MEP line ───────────────────────────────────────────────────────────
function MEPLine({ el }: { el: any }) {
  if (!el.start || !el.end) return null;
  const pts = useMemo(() => new Float32Array([
    el.start[0], el.start[1], el.start[2],
    el.end[0], el.end[1], el.end[2],
  ]), [el]);

  const color = COLORS[el.system] || '#888';
  return (
    <line>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[pts, 3]} />
      </bufferGeometry>
      <lineBasicMaterial color={color} />
    </line>
  );
}

// ── MEP point (fixtures, panels, etc) ─────────────────────────────────
function MEPPoint({ el }: { el: any }) {
  if (!el.start) return null;
  const color = COLORS[el.type] || COLORS[el.system] || '#888';
  return (
    <mesh position={[el.start[0], el.start[1], el.start[2]]}>
      <sphereGeometry args={[0.2, 8, 8]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.5} />
    </mesh>
  );
}

// ── Facade detail mesh (windows, parapet) — Y coords are already absolute ──
function FacadeMesh({ mesh }: { mesh: any; floorH?: number }) {
  const geometry = useMemo(() => {
    try {
      const geo = new THREE.BufferGeometry();
      const verts = new Float32Array(mesh.vertices.flat());
      const idx = new Uint16Array(mesh.faces.flat());
      geo.setAttribute('position', new THREE.BufferAttribute(verts, 3));
      geo.setIndex(new THREE.BufferAttribute(idx, 1));
      geo.computeVertexNormals();
      return geo;
    } catch { return null; }
  }, [mesh.vertices, mesh.faces]);

  if (!geometry) return null;
  const isWindow = mesh.element_type === 'window';
  const isGlass = isWindow;
  const isBalcony = mesh.element_type === 'balcony';
  const isRail = mesh.element_type === 'balcony_rail';

  return (
    <mesh geometry={geometry} castShadow={!isGlass} receiveShadow>
      <meshStandardMaterial
        color={mesh.color || '#94a3b8'}
        transparent={isGlass}
        opacity={isGlass ? 0.55 : 1}
        roughness={isGlass ? 0.05 : isRail ? 0.4 : isBalcony ? 0.7 : 0.82}
        metalness={isGlass ? 0.2 : isRail ? 0.6 : 0.0}
        side={THREE.DoubleSide}
        depthWrite={!isGlass}
      />
    </mesh>
  );
}

// ── Generic buffer mesh builder ────────────────────────────────────────
function useBufferGeo(vertices: number[][], faces: number[][]) {
  return useMemo(() => {
    try {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(vertices.flat()), 3));
      geo.setIndex(new THREE.BufferAttribute(new Uint16Array(faces.flat()), 1));
      geo.computeVertexNormals();
      return geo;
    } catch { return null; }
  }, [vertices, faces]);
}

// ── Terrain mesh (sloped ground plane from massing) ────────────────────
function TerrainMesh({ mesh }: { mesh: any }) {
  const geometry = useBufferGeo(mesh.vertices, mesh.faces);
  if (!geometry) return null;
  return (
    <mesh geometry={geometry} receiveShadow>
      <meshStandardMaterial color={mesh.color || '#3d5a3e'} roughness={1} transparent opacity={0.75} side={THREE.DoubleSide} />
    </mesh>
  );
}

// ── Floor band mesh (visible floor plates) ─────────────────────────────
function FloorBandMesh({ mesh }: { mesh: any }) {
  const geometry = useBufferGeo(mesh.vertices, mesh.faces);
  if (!geometry) return null;
  return (
    <mesh geometry={geometry} castShadow>
      <meshStandardMaterial color={mesh.color || '#c0c8d8'} roughness={0.6} metalness={0.15} side={THREE.DoubleSide} />
    </mesh>
  );
}

// ── Overlap mesh (red where footprint overlaps neighbor) ───────────────
function OverlapMesh({ mesh }: { mesh: any }) {
  const geometry = useBufferGeo(mesh.vertices, mesh.faces);
  if (!geometry) return null;
  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial
        color="#ff4444" emissive="#ff2200" emissiveIntensity={0.6}
        transparent opacity={0.85} side={THREE.DoubleSide} depthWrite={false}
      />
    </mesh>
  );
}

// ── Footprint outline mesh (green ground indicator) ───────────────────
function FootprintMesh({ mesh }: { mesh: any }) {
  const geometry = useBufferGeo(mesh.vertices, mesh.faces);
  if (!geometry) return null;
  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial
        color="#00ff88" emissive="#00cc66" emissiveIntensity={0.5}
        transparent opacity={0.9} side={THREE.DoubleSide}
      />
    </mesh>
  );
}

// ── Helper: convert lat/lon to local meters ────────────────────────────
function toLocal(lon: number, lat: number, siteCenter: [number, number]): [number, number] {
  const x = (lon - siteCenter[0]) * 111320 * Math.cos(siteCenter[1] * Math.PI / 180);
  const z = (lat - siteCenter[1]) * 111320;
  return [x, z];
}

// ── Fire hydrant 3D ────────────────────────────────────────────────────
function FireHydrant({ feature, siteCenter }: { feature: any; siteCenter: [number, number] }) {
  const coords = feature.geometry?.coordinates;
  if (!coords) return null;
  const [x, z] = toLocal(coords[0], coords[1], siteCenter);
  if (Math.abs(x) > 200 || Math.abs(z) > 200) return null;
  return (
    <group position={[x, 0, z]}>
      {/* Base */}
      <mesh position={[0, 0.15, 0]}>
        <cylinderGeometry args={[0.12, 0.15, 0.3, 8]} />
        <meshStandardMaterial color="#cc2200" roughness={0.5} metalness={0.3} />
      </mesh>
      {/* Body */}
      <mesh position={[0, 0.5, 0]}>
        <cylinderGeometry args={[0.1, 0.12, 0.5, 8]} />
        <meshStandardMaterial color="#dd2200" roughness={0.5} metalness={0.3} />
      </mesh>
      {/* Outlets */}
      <mesh position={[0.13, 0.45, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.04, 0.04, 0.08, 6]} />
        <meshStandardMaterial color="#cc2200" roughness={0.5} metalness={0.4} />
      </mesh>
      <mesh position={[-0.13, 0.45, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.04, 0.04, 0.08, 6]} />
        <meshStandardMaterial color="#cc2200" roughness={0.5} metalness={0.4} />
      </mesh>
      {/* Cap */}
      <mesh position={[0, 0.78, 0]}>
        <cylinderGeometry args={[0.07, 0.1, 0.1, 6]} />
        <meshStandardMaterial color="#bbbbbb" roughness={0.3} metalness={0.7} />
      </mesh>
    </group>
  );
}

// ── Power pole 3D ──────────────────────────────────────────────────────
function PowerPole({ feature, siteCenter }: { feature: any; siteCenter: [number, number] }) {
  const coords = feature.geometry?.coordinates;
  if (!coords) return null;
  const [x, z] = toLocal(coords[0], coords[1], siteCenter);
  if (Math.abs(x) > 200 || Math.abs(z) > 200) return null;
  return (
    <group position={[x, 0, z]}>
      {/* Pole */}
      <mesh position={[0, 4, 0]}>
        <cylinderGeometry args={[0.08, 0.12, 8, 6]} />
        <meshStandardMaterial color="#5c3d1e" roughness={0.9} />
      </mesh>
      {/* Cross arm */}
      <mesh position={[0, 7.2, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.04, 0.04, 2.2, 6]} />
        <meshStandardMaterial color="#4a3010" roughness={0.9} />
      </mesh>
      {/* Insulators */}
      {[-0.9, 0, 0.9].map((ox) => (
        <mesh key={ox} position={[ox, 7.35, 0]}>
          <sphereGeometry args={[0.06, 6, 6]} />
          <meshStandardMaterial color="#ddddaa" roughness={0.4} />
        </mesh>
      ))}
      {/* Glow point at top */}
      <pointLight position={[0, 8.2, 0]} intensity={0.15} color="#f59e0b" distance={15} />
    </group>
  );
}

// ── Manhole cover 3D ───────────────────────────────────────────────────
function Manhole({ feature, siteCenter }: { feature: any; siteCenter: [number, number] }) {
  const coords = feature.geometry?.coordinates;
  if (!coords) return null;
  const [x, z] = toLocal(coords[0], coords[1], siteCenter);
  if (Math.abs(x) > 200 || Math.abs(z) > 200) return null;
  return (
    <mesh position={[x, 0.01, z]}>
      <cylinderGeometry args={[0.38, 0.38, 0.04, 16]} />
      <meshStandardMaterial color="#374151" roughness={0.95} metalness={0.2} />
    </mesh>
  );
}

// ── Neighbor building (gray box from lat/lon footprint projected) ──────
function NeighborBuilding({ building, siteCenter }: { building: any; siteCenter: [number, number] }) {
  const geometry = useMemo(() => {
    try {
      const coords = building.geometry?.coordinates?.[0];
      if (!coords || coords.length < 3) return null;
      const height = building.properties?.height_m || 6;
      const isExisting = building.properties?.is_existing;

      const localPts = coords.map(([lon, lat]: [number, number]) => {
        const x = (lon - siteCenter[0]) * 111320 * Math.cos(siteCenter[1] * Math.PI / 180);
        const z = (lat - siteCenter[1]) * 111320;
        return [x, z];
      });

      const shape = new THREE.Shape();
      shape.moveTo(localPts[0][0], localPts[0][1]);
      for (let i = 1; i < localPts.length; i++) shape.lineTo(localPts[i][0], localPts[i][1]);
      shape.closePath();

      const geo = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      return { geo, height, isExisting };
    } catch { return null; }
  }, [building, siteCenter]);

  if (!geometry) return null;
  const color = geometry.isExisting ? COLORS.neighbor_existing : COLORS.neighbor;

  return (
    <mesh geometry={geometry.geo} position={[0, 0, 0]} receiveShadow>
      <meshStandardMaterial color={color} transparent opacity={0.5} roughness={1} wireframe={false} />
    </mesh>
  );
}

// ── Gap indicator line between parcel and neighbor ─────────────────────
function GapLine({ neighbor, siteCenter }: { neighbor: any; siteCenter: [number, number] }) {
  if (!neighbor.footprint?.coordinates?.[0]) return null;
  const coords = neighbor.footprint.coordinates[0];
  const cx = coords.reduce((s: number, p: number[]) => s + p[0], 0) / coords.length;
  const cz_raw = coords.reduce((s: number, p: number[]) => s + p[1], 0) / coords.length;
  const nx = (cx - siteCenter[0]) * 111320 * Math.cos(siteCenter[1] * Math.PI / 180);
  const nz = (cz_raw - siteCenter[1]) * 111320;
  const color = neighbor.gap_m < 1.5 ? '#ef4444' : neighbor.gap_m < 3 ? '#f59e0b' : '#00ff88';

  const pts = useMemo(() => new Float32Array([0, 2, 0, nx, 2, nz]), [nx, nz]);

  return (
    <group>
      <line>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[pts, 3]} />
        </bufferGeometry>
        <lineBasicMaterial color={color} />
      </line>
      <mesh position={[nx, 2, nz]}>
        <sphereGeometry args={[0.3, 8, 8]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.8} />
      </mesh>
    </group>
  );
}

// ── Power grid connection line to nearest power line ───────────────────
function PowerGridLine({ connection, siteCenter }: { connection: any; siteCenter: [number, number] }) {
  const coords = connection?.geometry?.coordinates;
  if (!coords || coords.length < 2) return null;
  const [lon0, lat0] = coords[0];
  const [lon1, lat1] = coords[1];
  const scale = 111320 * Math.cos(siteCenter[1] * Math.PI / 180);
  const ex = (lon1 - lon0) * scale;
  const ez = (lat1 - lat0) * 111320;

  const pts = useMemo(() => new Float32Array([0, 1, 0, ex, 1, ez]), [ex, ez]);

  return (
    <group>
      <line>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[pts, 3]} />
        </bufferGeometry>
        <lineBasicMaterial color="#facc15" />
      </line>
      <mesh position={[ex, 1, ez]}>
        <sphereGeometry args={[0.5, 8, 8]} />
        <meshStandardMaterial color="#facc15" emissive="#facc15" emissiveIntensity={0.8} />
      </mesh>
    </group>
  );
}

// ── Main scene ─────────────────────────────────────────────────────────
function Scene() {
  const { buildingModel, activeLayers, selectedSite, infrastructure, neighborConstraints, spec } = useAppStore();
  const siteCenter: [number, number] = selectedSite ? [selectedSite.lon, selectedSite.lat] : [0, 0];

  // When a model is generated, hide the OSM building we're replacing.
  // Match by comparing footprint centroid in lat/lon to the existing_building footprint centroid.
  const existingFootprintCoords = neighborConstraints?.existing_building?.footprint?.coordinates?.[0];
  const exCentroid: [number, number] | null = existingFootprintCoords
    ? [
        existingFootprintCoords.reduce((s: number, p: number[]) => s + p[0], 0) / existingFootprintCoords.length,
        existingFootprintCoords.reduce((s: number, p: number[]) => s + p[1], 0) / existingFootprintCoords.length,
      ]
    : null;

  const allNeighborBuildings = (infrastructure?.buildings || []).filter((b: any) => {
    const coords = b.geometry?.coordinates?.[0];
    if (!coords?.length) return true;
    const cx = coords.reduce((s: number, p: number[]) => s + p[0], 0) / coords.length;
    const cz = coords.reduce((s: number, p: number[]) => s + p[1], 0) / coords.length;
    // Only hide the specific building being replaced (matched by centroid)
    if (buildingModel && exCentroid) {
      const dist = Math.sqrt((cx - exCentroid[0]) ** 2 + (cz - exCentroid[1]) ** 2);
      if (dist < 0.00003) return false;
    }
    return true;
  });
  const closestNeighbors = neighborConstraints?.closest_neighbors || [];
  const powerConnection = infrastructure?.power_connection || null;

  const matColor = MATERIAL_COLORS[(spec as any)?.structural_system] || '#94a3b8';
  const FLOOR_H = 3.0;

  // Resolve texture based on structural system + what neighbors are built from
  const neighborMat = buildingModel?.neighbor_style?.dominant_material ?? '';
  const { texName, roughness: texRoughness, metalness: texMetalness } = useMemo(
    () => resolveTexture((spec as any)?.structural_system ?? 'wood', neighborMat),
    [(spec as any)?.structural_system, neighborMat]
  );

  return (
    <>
      <Grid args={[300, 300]} cellColor="#0d1117" sectionColor="#1e293b" fadeDistance={150} position={[0, -0.05, 0]} />

      {/* Neighbor buildings from OSM */}
      {activeLayers['neighbors'] && allNeighborBuildings.map((b: any, i: number) => (
        <NeighborBuilding key={i} building={b} siteCenter={siteCenter} />
      ))}

      {/* Gap lines to closest neighbors */}
      {activeLayers['neighbors'] && closestNeighbors.map((n: any, i: number) => (
        <GapLine key={i} neighbor={n} siteCenter={siteCenter} />
      ))}

      {/* Power grid connection */}
      {activeLayers['power_grid'] && powerConnection && (
        <PowerGridLine connection={powerConnection} siteCenter={siteCenter} />
      )}

      {/* 3D site props — fire hydrants, power poles, manholes */}
      {infrastructure?.fire_hydrants?.map((f: any, i: number) => (
        <FireHydrant key={`fh_${i}`} feature={f} siteCenter={siteCenter} />
      ))}
      {infrastructure?.power_poles?.map((f: any, i: number) => (
        <PowerPole key={`pp_${i}`} feature={f} siteCenter={siteCenter} />
      ))}
      {infrastructure?.manholes?.map((f: any, i: number) => (
        <Manhole key={`mh_${i}`} feature={f} siteCenter={siteCenter} />
      ))}

      {/* Generated building */}
      {buildingModel && (
        <>
          {activeLayers['architecture'] && buildingModel.rooms.map((r: any) => (
            <RoomMesh key={r.id} room={r} matColor={matColor}
              texName={['unit','corridor','stair'].includes(r.type) ? texName : undefined}
              roughness={texRoughness} metalness={texMetalness} />
          ))}
          {activeLayers['architecture'] && buildingModel.walls.map((w: any) => (
            <WallMesh key={w.id} wall={w} matColor={matColor}
              texName={texName} roughness={texRoughness} metalness={texMetalness} />
          ))}
          {buildingModel.mep_elements.map((el: any) => {
            if (!activeLayers[el.system as LayerKey]) return null;
            return el.end ? <MEPLine key={el.id} el={el} /> : <MEPPoint key={el.id} el={el} />;
          })}
          {/* Massing meshes: terrain, floor bands, footprint, overlap */}
          {(buildingModel.massing_options?.[buildingModel.chosen_massing_index]?.meshes || []).map((m: any, i: number) => {
            if (m.element_type === 'terrain') return <TerrainMesh key={`t_${i}`} mesh={m} />;
            if (m.element_type === 'floor_band') return <FloorBandMesh key={`fb_${i}`} mesh={m} />;
            if (m.element_type === 'overlap') return <OverlapMesh key={`ov_${i}`} mesh={m} />;
            if (m.element_type === 'footprint_ok') return <FootprintMesh key={`fp_${i}`} mesh={m} />;
            return null;
          })}

          {/* Facade details: windows, parapet */}
          {activeLayers['architecture'] && (buildingModel.meshes || [])
            .filter((m: any) => m.element_type !== 'terrain')
            .map((mesh: any, i: number) => (
              <FacadeMesh key={`facade_${i}`} mesh={mesh} floorH={FLOOR_H} />
            ))}

          {activeLayers['issues'] && buildingModel.issues.map((issue: any) => {
            if (!issue.location) return null;
            const { min_x, max_x, min_y, max_y, min_z, max_z } = issue.location;
            const cx = ((min_x || 0) + (max_x || 0)) / 2 || 0;
            const cy = ((min_z || 0) + (max_z || 0)) / 2 || 3;
            const cz = ((min_y || 0) + (max_y || 0)) / 2 || 0;
            const color = issue.severity === 'error' ? COLORS.issue_error : COLORS.issue_warning;
            return (
              <mesh key={issue.id} position={[cx, cy, cz]}>
                <sphereGeometry args={[0.5, 12, 12]} />
                <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.6} transparent opacity={0.8} />
              </mesh>
            );
          })}
        </>
      )}

      {/* Empty state placeholder */}
      {!buildingModel && (
        <mesh position={[0, 3, 0]}>
          <boxGeometry args={[20, 6, 12]} />
          <meshStandardMaterial color="#1e293b" wireframe />
        </mesh>
      )}
    </>
  );
}

const LAYER_LABELS: { key: LayerKey; label: string; color: string }[] = [
  { key: 'neighbors', label: 'Neighbors', color: '#64748b' },
  { key: 'power_grid', label: 'Power Grid', color: '#facc15' },
  { key: 'architecture', label: 'Architecture', color: '#94a3b8' },
  { key: 'structure', label: 'Structure', color: '#a855f7' },
  { key: 'plumbing', label: 'Plumbing', color: '#3b82f6' },
  { key: 'electrical', label: 'Electrical', color: '#f59e0b' },
  { key: 'hvac', label: 'HVAC', color: '#10b981' },
  { key: 'issues', label: 'Issues', color: '#ef4444' },
];

export default function BuildingViewer() {
  const { activeLayers, toggleLayer, buildingModel, neighborConstraints, feasibilityData } = useAppStore();
  const terrain = buildingModel?.site_context?.terrain;
  const feasibility = neighborConstraints?.feasibility;

  return (
    <div className="relative w-full h-full bg-[var(--surface-0)]">
      <Canvas
        shadows
        camera={{ position: [50, 40, 50], fov: 50, near: 0.1, far: 2000 }}
        gl={{ antialias: true }}
      >
        <color attach="background" args={['#0a0a0f']} />
        <fog attach="fog" args={['#0a0a0f', 100, 300]} />
        <ambientLight intensity={0.35} />
        <hemisphereLight args={['#c8d8f0', '#3a4a30', 0.6]} />
        <directionalLight position={[40, 60, 30]} intensity={1.4} castShadow
          shadow-mapSize={[2048, 2048]} shadow-camera-far={300}
          shadow-camera-left={-80} shadow-camera-right={80}
          shadow-camera-top={80} shadow-camera-bottom={-80} />
        <directionalLight position={[-20, 30, -20]} intensity={0.4} color="#b0c8ff" />
        <pointLight position={[0, 5, 0]} intensity={0.2} color="#00e5ff" distance={60} />
        <Suspense fallback={null}>
          <Scene />
        </Suspense>
        <OrbitControls makeDefault minDistance={5} maxDistance={500} maxPolarAngle={Math.PI / 2.1} />
      </Canvas>

      {/* Layer toggles */}
      <div className="absolute top-4 right-4 panel p-3 space-y-1.5 animate-fade-in">
        <div className="text-[var(--text-secondary)] font-mono text-xs uppercase tracking-wider mb-2">Layers</div>
        {LAYER_LABELS.map(({ key, label, color }) => (
          <button key={key} onClick={() => toggleLayer(key)} className="flex items-center gap-2 w-full text-left">
            <div className="w-3 h-3 rounded-sm flex-shrink-0 transition-opacity"
              style={{ background: color, opacity: activeLayers[key] ? 1 : 0.2 }} />
            <span className="text-xs font-mono transition-colors"
              style={{ color: activeLayers[key] ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
              {label}
            </span>
          </button>
        ))}
      </div>

      {/* Site feasibility summary */}
      {feasibility && (
        <div className="absolute bottom-4 left-4 panel p-3 max-w-xs animate-fade-in">
          <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider mb-2">
            Site Feasibility
          </div>
          <div className="flex items-center gap-2 mb-2">
            <div className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ background: feasibility.feasible ? 'var(--accent-green)' : 'var(--accent-red)' }} />
            <span className="text-xs font-mono" style={{ color: feasibility.feasible ? 'var(--accent-green)' : 'var(--accent-red)' }}>
              {feasibility.feasible ? 'Feasible' : 'Issues detected'}
            </span>
          </div>
          <div className="text-[10px] font-mono text-[var(--text-secondary)] space-y-0.5">
            <div>Parcel: {feasibility.parcel_width_ft}ft × {feasibility.parcel_depth_ft}ft</div>
            {neighborConstraints?.min_neighbor_gap_ft && (
              <div>Closest neighbor: {neighborConstraints.min_neighbor_gap_ft}ft away</div>
            )}
            {neighborConstraints?.neighbor_count > 0 && (
              <div>{neighborConstraints.neighbor_count} neighboring buildings</div>
            )}
            {terrain && (
              <div className="flex items-center gap-1.5 mt-1 pt-1 border-t border-[var(--border)]">
                <span style={{ color: terrain.is_sloped ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
                  {terrain.is_sloped ? '⛰' : '▬'}
                </span>
                <span style={{ color: terrain.is_sloped ? 'var(--accent-amber)' : 'inherit' }}>
                  {terrain.is_sloped
                    ? `Hill: ${terrain.slope_pct}% slope (${terrain.slope_degrees}°)`
                    : 'Terrain: flat'}
                </span>
              </div>
            )}
            {terrain?.elevation_range_m > 0 && (
              <div>Elevation range: {terrain.elevation_range_m}m across parcel</div>
            )}
          </div>
            {/* Current weather */}
            {(buildingModel?.spec as any)?.site && buildingModel?.site_context && (() => {
              const weather = (buildingModel.site_context as any)?.hazard_detail?.current_weather;
              if (!weather || !weather.temp_f) return null;
              return (
                <div className="mt-1 pt-1 border-t border-[var(--border)]">
                  <div className="text-[10px] font-mono text-[var(--text-secondary)] uppercase tracking-wider mb-1">Current Conditions</div>
                  <div className="text-[10px] font-mono" style={{ color: 'var(--text-primary)' }}>
                    🌡 {weather.temp_f}°F · 💨 {weather.wind_mph} mph {weather.wind_dir}
                  </div>
                  <div className="text-[10px] font-mono text-[var(--text-secondary)]">{weather.description}</div>
                </div>
              );
            })()}
          {feasibility.issues?.map((issue: string, i: number) => (
            <div key={i} className="mt-1 text-[10px] font-mono text-[var(--accent-red)]">⚠ {issue}</div>
          ))}
          {feasibility.warnings?.slice(0, 2).map((w: string, i: number) => (
            <div key={i} className="mt-1 text-[10px] font-mono text-[var(--accent-amber)]">⚠ {w}</div>
          ))}

          {/* Legal / demolition feasibility */}
          {feasibilityData && (
            <div className="mt-2 pt-2 border-t border-[var(--border)]">
              <div className="text-[10px] font-mono text-[var(--text-secondary)] uppercase tracking-wider mb-1">Legal / Demolition</div>
              <div className="flex items-center gap-2 mb-1">
                <div className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ background: feasibilityData.demolition_feasible ? 'var(--accent-green)' : 'var(--accent-red)' }} />
                <span className="text-[10px] font-mono" style={{ color: feasibilityData.demolition_feasible ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                  {feasibilityData.demolition_feasible ? 'Demolition appears feasible' : 'Demolition restrictions detected'}
                </span>
              </div>
              {feasibilityData.landuse && (
                <div className="text-[10px] font-mono text-[var(--text-secondary)]">Landuse: {feasibilityData.landuse}</div>
              )}
              {feasibilityData.flood_flag && (
                <div className="text-[10px] font-mono text-[var(--accent-amber)]">⚠ FEMA Flood Zone {feasibilityData.flood_zone}</div>
              )}
              {feasibilityData.issues?.map((issue: string, i: number) => (
                <div key={i} className="text-[10px] font-mono text-[var(--accent-red)]">✗ {issue}</div>
              ))}
              {feasibilityData.warnings?.slice(0, 2).map((w: string, i: number) => (
                <div key={i} className="text-[10px] font-mono text-[var(--accent-amber)]">⚠ {w}</div>
              ))}
              {feasibilityData.note && (
                <div className="text-[9px] font-mono text-[var(--text-secondary)] mt-1 opacity-60">{feasibilityData.note}</div>
              )}
            </div>
          )}
        </div>
      )}

      {!buildingModel && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="text-[var(--text-secondary)] text-sm font-mono">
            {neighborConstraints ? '3D neighbors loaded — generate a building to see it here' : 'Select a site and generate a building'}
          </div>
        </div>
      )}
    </div>
  );
}
