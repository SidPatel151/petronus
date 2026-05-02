'use client';
import { useRef, useMemo, Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { useLoader } from '@react-three/fiber';
import { OrbitControls, Grid, Environment } from '@react-three/drei';
import * as THREE from 'three';
import { useAppStore, LayerKey } from '@/lib/store';
import { getTexture, resolveTexture } from '@/lib/textures';

// ── PBR texture sets — diff JPG + optional roughness JPG (no EXR) ─────
const PBR_SETS: Record<string, {
  diff: string; roughJpg?: string;
  repeatX: number; repeatY: number;
}> = {
  brick:          { diff: '/textures/brick_wall_10_diff_4k.jpg',         repeatX: 3, repeatY: 5 },
  stucco:         { diff: '/textures/painted_plaster_wall_diff_4k.jpg',  repeatX: 4, repeatY: 5 },
  wood:           { diff: '/textures/plank_flooring_04_diff_4k.jpg',     repeatX: 2, repeatY: 8 },
  stone:          { diff: '/textures/marble_01_diff_4k.jpg', roughJpg: '/textures/marble_01_rough_4k.jpg',           repeatX: 4, repeatY: 5 },
  marble:         { diff: '/textures/marble_01_diff_4k.jpg', roughJpg: '/textures/marble_01_rough_4k.jpg',           repeatX: 3, repeatY: 3 },
  roof_tiles:     { diff: '/textures/grey_roof_tiles_02_diff_4k.jpg', roughJpg: '/textures/grey_roof_tiles_02_rough_4k.jpg', repeatX: 5, repeatY: 5 },
  interior_tiles: { diff: '/textures/interior_tiles_diff_4k.jpg',        repeatX: 3, repeatY: 3 },
};

// Single hook — diff JPG always, rough JPG when available. No EXR.
function usePBRSet(name: string) {
  const set = PBR_SETS[name];
  const diff  = useLoader(THREE.TextureLoader, set?.diff     ?? '/textures/brick_wall_10_diff_4k.jpg');
  const rough = useLoader(THREE.TextureLoader, set?.roughJpg ?? set?.diff ?? '/textures/brick_wall_10_diff_4k.jpg');
  const rx = set?.repeatX ?? 3, ry = set?.repeatY ?? 5;
  diff.wrapS = diff.wrapT = THREE.RepeatWrapping; diff.repeat.set(rx, ry);
  diff.colorSpace = THREE.SRGBColorSpace;
  if (set?.roughJpg) { rough.wrapS = rough.wrapT = THREE.RepeatWrapping; rough.repeat.set(rx, ry); }
  return { diff, rough: set?.roughJpg ? rough : null };
}

// Procedural canvas texture fallback — always renders, never conditionally calls hooks
function ProceduralMaterial({ texName, fallbackColor, roughness = 0.9, metalness = 0.0, transparent = false, opacity = 1, polygonOffset = false, polygonOffsetFactor = 0, polygonOffsetUnits = 0 }: {
  texName: string; fallbackColor: string;
  roughness?: number; metalness?: number; transparent?: boolean; opacity?: number;
  polygonOffset?: boolean; polygonOffsetFactor?: number; polygonOffsetUnits?: number;
}) {
  const tex = useMemo(() => { try { return getTexture(texName); } catch { return null; } }, [texName]);
  return (
    <meshStandardMaterial
      map={tex ?? undefined} color={tex ? '#ffffff' : fallbackColor}
      roughness={roughness} metalness={metalness}
      transparent={transparent} opacity={opacity}
      polygonOffset={polygonOffset} polygonOffsetFactor={polygonOffsetFactor} polygonOffsetUnits={polygonOffsetUnits}
    />
  );
}

// Dispatcher — renders PBR inner if texture set exists, otherwise procedural
function PBRMaterial({ texName, fallbackColor, roughness = 0.9, metalness = 0.0, transparent = false, opacity = 1, polygonOffset = false, polygonOffsetFactor = 0, polygonOffsetUnits = 0 }: {
  texName: string; fallbackColor: string;
  roughness?: number; metalness?: number; transparent?: boolean; opacity?: number;
  polygonOffset?: boolean; polygonOffsetFactor?: number; polygonOffsetUnits?: number;
}) {
  if (PBR_SETS[texName]) {
    return <PBRMaterialInner texName={texName} roughness={roughness} metalness={metalness} transparent={transparent} opacity={opacity} polygonOffset={polygonOffset} polygonOffsetFactor={polygonOffsetFactor} polygonOffsetUnits={polygonOffsetUnits} />;
  }
  return <ProceduralMaterial texName={texName} fallbackColor={fallbackColor} roughness={roughness} metalness={metalness} transparent={transparent} opacity={opacity} polygonOffset={polygonOffset} polygonOffsetFactor={polygonOffsetFactor} polygonOffsetUnits={polygonOffsetUnits} />;
}

// Loads diff + optional roughness JPG — no EXR, always renders
function PBRMaterialInner({ texName, roughness, metalness, transparent, opacity, polygonOffset, polygonOffsetFactor, polygonOffsetUnits }: {
  texName: string; roughness: number; metalness: number; transparent: boolean; opacity: number;
  polygonOffset?: boolean; polygonOffsetFactor?: number; polygonOffsetUnits?: number;
}) {
  const { diff, rough } = usePBRSet(texName);
  return (
    <meshStandardMaterial map={diff} roughnessMap={rough ?? undefined}
      roughness={roughness} metalness={metalness} transparent={transparent} opacity={opacity}
      polygonOffset={polygonOffset} polygonOffsetFactor={polygonOffsetFactor} polygonOffsetUnits={polygonOffsetUnits} />
  );
}

const COLORS: Record<string, string> = {
  unit: '#1e3a5f', living: '#1e3a5f', bedroom: '#1a3352',
  bathroom: '#0f2040', kitchen: '#162d4a', corridor: '#0d1f33', stair: '#0a1a2e',
  foyer: '#1a2a3a', office: '#1e2a1e', pantry: '#1a2a1a', mudroom: '#2a1a1a',
  walk_in_closet: '#1a1a2a', family_room: '#1e3040', bonus_room: '#1a2a3a',
  loft: '#1e3050', media_room: '#0a0a1a', library: '#1a1a0a', gym: '#1a2a1a',
  laundry: '#1a1a2a', dining: '#2a2a1a',
  wall_exterior: '#334155', wall_interior: '#1e293b', wall_shear: '#7c3aed',
  plumbing: '#3b82f6', electrical: '#f59e0b', hvac: '#10b981', fire: '#ef4444',
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
const FLOOR_ROOM_TYPES = new Set([
  'bedroom','living','kitchen','bathroom','dining',
  'foyer','office','pantry','mudroom','walk_in_closet',
  'family_room','bonus_room','loft','media_room','library','gym',
  'laundry','corridor',
]);

function RoomMesh({ room, matColor, texName, roughness, metalness, floorH }: {
  room: any; matColor: string; texName?: string; roughness?: number; metalness?: number; floorH: number;
}) {
  if (!room.polygon?.length) return null;
  const isStructural = ['unit', 'corridor', 'stair'].includes(room.type);
  const isFloor = FLOOR_ROOM_TYPES.has(room.type);

  const geometry = useMemo(() => {
    try {
      const pts = room.polygon;
      const s = new THREE.Shape();
      s.moveTo(pts[0][0], -pts[0][1]);
      for (let i = 1; i < pts.length; i++) s.lineTo(pts[i][0], -pts[i][1]);
      s.closePath();
      if (isFloor) {
        // Floor slab: 80mm thick concrete-like slab so it reads as a solid element, not a paper plane
        const geo = new THREE.ExtrudeGeometry(s, { depth: 0.08, bevelEnabled: false });
        geo.rotateX(-Math.PI / 2);
        return geo;
      }
      // Structural shell height must match the actual floor-to-floor height, minus slab
      const geo = new THREE.ExtrudeGeometry(s, { depth: floorH - 0.08, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      return geo;
    } catch { return null; }
  }, [room.polygon, isFloor, floorH]);

  if (!geometry) return null;
  const subRoomColors: Record<string,string> = {
    bedroom: '#2a5080', living: '#2e5468', kitchen: '#3a5038',
    bathroom: '#2a4058', dining: '#484430',
    foyer: '#2e4870', office: '#2e4230', pantry: '#2a4428', mudroom: '#48302a',
    walk_in_closet: '#2a2a58', family_room: '#2a4868', bonus_room: '#2a4458',
    loft: '#30487a', media_room: '#181830', library: '#2a2a18', gym: '#2a4228',
    laundry: '#2a2a58',
  };
  const color = room.type === 'unit' ? matColor : subRoomColors[room.type] || COLORS[room.type] || '#1a2030';
  // Floor slabs sit 2cm above the structural slab so they're not z-fighting
  const yBase = (room.level || 0) * floorH + (isFloor ? 0.02 : 0);

  return (
    <mesh geometry={geometry} position={[0, yBase, 0]} receiveShadow castShadow={!isFloor}>
      <PBRMaterial
        texName={texName ?? ''}
        fallbackColor={color}
        roughness={roughness ?? 0.85}
        metalness={metalness ?? 0.0}
        transparent={isStructural}
        opacity={isStructural ? 0.92 : 1.0}
      />
    </mesh>
  );
}

// ── Ceiling: horizontal slab at ceiling height, facing downward ────────
// Rendered for all habitable rooms so the three planes (floor, wall, ceiling)
// are unambiguously distinct by their 3D position — no color legend required.
function CeilingMesh({ room, floorH }: { room: any; floorH: number }) {
  if (!room.polygon?.length) return null;

  const geometry = useMemo(() => {
    try {
      const pts = room.polygon;
      const s = new THREE.Shape();
      s.moveTo(pts[0][0], -pts[0][1]);
      for (let i = 1; i < pts.length; i++) s.lineTo(pts[i][0], -pts[i][1]);
      s.closePath();
      // 50mm ceiling board — thin but clearly a plane, not just a surface
      const geo = new THREE.ExtrudeGeometry(s, { depth: 0.05, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      return geo;
    } catch { return null; }
  }, [room.polygon]);

  if (!geometry) return null;
  // Ceiling sits 28cm below the floor slab above (accounts for structural slab thickness)
  const yCeiling = (room.level || 0) * floorH + floorH - 0.28;

  return (
    <mesh geometry={geometry} position={[0, yCeiling, 0]} receiveShadow>
      {/* Off-white gypsum board — naturally distinct from the darker floor and coloured walls */}
      <meshStandardMaterial color="#d8dfe8" roughness={0.92} metalness={0.0} side={THREE.DoubleSide} />
    </mesh>
  );
}

// ── Wall ───────────────────────────────────────────────────────────────
function WallMesh({ wall, matColor, texName, roughness, metalness, floorH }: {
  wall: any; matColor: string; texName?: string; roughness?: number; metalness?: number; floorH: number;
}) {
  const s = wall.start, e = wall.end;
  if (!s || !e) return null;
  const dx = e[0] - s[0], dz = e[1] - s[1];
  const length = Math.sqrt(dx * dx + dz * dz);
  if (length < 0.01) return null;

  const height = (wall.height_ft || 9) * 0.3048;
  const angle = Math.atan2(dz, dx);
  const cx = (s[0] + e[0]) / 2, cz = (s[1] + e[1]) / 2;
  const yBase = (wall.level || 0) * floorH + height / 2;
  const color = wall.is_shear ? COLORS.wall_shear : wall.is_exterior ? matColor : COLORS.wall_interior;

  return (
    <mesh position={[cx, yBase, cz]} rotation={[0, -angle, 0]} castShadow>
      <boxGeometry args={[length, height, 0.2]} />
      <PBRMaterial
        texName={wall.is_exterior ? (texName ?? '') : ''}
        fallbackColor={color}
        roughness={roughness ?? 0.9}
        metalness={metalness ?? 0.0}
      />
    </mesh>
  );
}

// ── Backend structural member (from StructuralEngine) ─────────────────
function StructuralMemberMesh({ member }: { member: any }) {
  const [x0, y0, z0] = member.start || [0, 0, 0];
  const [x1, y1, z1] = member.end || [x0, y0 + 3, z0];
  const dx = x1 - x0, dy = y1 - y0, dz = z1 - z0;
  const length = Math.sqrt(dx*dx + dy*dy + dz*dz);
  if (length < 0.01) return null;

  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, cz = (z0 + z1) / 2;
  const color = member.color || '#a855f7';
  const size = member.size_m || 0.2;
  const mat = member.material || 'wood';
  const roughness = mat === 'concrete' ? 0.85 : mat === 'steel' ? 0.3 : 0.7;
  const metalness = mat === 'steel' ? 0.7 : 0.0;

  const quaternion = useMemo(() => {
    const dir = new THREE.Vector3(dx, dy, dz).normalize();
    const up = new THREE.Vector3(0, 1, 0);
    const q = new THREE.Quaternion();
    if (Math.abs(dir.dot(up)) < 0.999) {
      q.setFromUnitVectors(up, dir);
    } else if (dir.y < 0) {
      q.setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI);
    }
    return q;
  }, [dx, dy, dz]);

  const type = member.type;

  if (type === 'column') {
    if (mat === 'steel') {
      // H-section column
      return (
        <group position={[cx, cy, cz]} quaternion={quaternion}>
          <mesh castShadow><boxGeometry args={[size, length, size * 0.15]} /><meshStandardMaterial color={color} roughness={roughness} metalness={metalness} /></mesh>
          <mesh castShadow><boxGeometry args={[size * 0.15, length, size]} /><meshStandardMaterial color={color} roughness={roughness} metalness={metalness} /></mesh>
        </group>
      );
    }
    return (
      <mesh position={[cx, cy, cz]} quaternion={quaternion} castShadow receiveShadow>
        <boxGeometry args={[size, length, size]} />
        <meshStandardMaterial color={color} roughness={roughness} metalness={metalness} />
      </mesh>
    );
  }

  if (type === 'beam' || type === 'joist') {
    const w = type === 'joist' ? size * 0.4 : size;
    return (
      <mesh position={[cx, cy, cz]} quaternion={quaternion} castShadow>
        <boxGeometry args={[w * 0.5, length, w]} />
        <meshStandardMaterial color={color} roughness={roughness} metalness={metalness} />
      </mesh>
    );
  }

  if (type === 'footing' || type === 'grade_beam') {
    // Flat box — footing is wider than the column above it
    const footW = type === 'footing' ? size * 3.5 : size * 1.5;
    return (
      <mesh position={[cx, cy, cz]} castShadow receiveShadow>
        <boxGeometry args={[footW, length, footW]} />
        <meshStandardMaterial color={color} roughness={0.9} metalness={0.0} transparent opacity={0.8} />
      </mesh>
    );
  }

  if (type === 'shear_wall') {
    // Thin panel along the wall
    return (
      <mesh position={[cx, cy, cz]} quaternion={quaternion} castShadow>
        <boxGeometry args={[length, size * 0.15, size * 3]} />
        <meshStandardMaterial color={color} roughness={0.7} metalness={0.0} transparent opacity={0.75} />
      </mesh>
    );
  }

  // Generic fallback
  return (
    <mesh position={[cx, cy, cz]} quaternion={quaternion} castShadow>
      <cylinderGeometry args={[size / 2, size / 2, length, 8]} />
      <meshStandardMaterial color={color} roughness={roughness} metalness={metalness} />
    </mesh>
  );
}

// ── Structural column ──────────────────────────────────────────────────
function StructuralColumns({ massing, levels, structuralSystem, floorH }: {
  massing: any; levels: any[]; structuralSystem: string; floorH: number;
}) {
  const footprint: [number, number][] = massing?.footprint || [];
  if (footprint.length < 3) return null;

  const totalH = levels.length * floorH;
  const yMid = totalH / 2;

  // Column size by structural system
  const colW = structuralSystem === 'concrete' ? 0.55
              : structuralSystem === 'steel'    ? 0.30
              : 0.22; // wood

  const colColor = structuralSystem === 'concrete' ? '#8C8C8C'
                 : structuralSystem === 'steel'    ? '#6B7B8D'
                 : '#7a5c30';

  // Collect column positions: footprint corners + midpoints on long edges (>5m)
  const positions: [number, number][] = [];
  const pts = footprint[footprint.length - 1][0] === footprint[0][0] &&
              footprint[footprint.length - 1][1] === footprint[0][1]
    ? footprint.slice(0, -1)   // drop closing duplicate
    : footprint;

  for (let i = 0; i < pts.length; i++) {
    positions.push(pts[i]);
    const next = pts[(i + 1) % pts.length];
    const dx = next[0] - pts[i][0], dz = next[1] - pts[i][1];
    const len = Math.sqrt(dx * dx + dz * dz);
    // Add intermediate column every 5m on longer edges
    const segs = Math.floor(len / 5);
    for (let s = 1; s < segs; s++) {
      positions.push([pts[i][0] + dx * s / segs, pts[i][1] + dz * s / segs]);
    }
  }

  const rough = structuralSystem === 'concrete' ? 0.85 : 0.3;
  const metal = structuralSystem === 'steel' ? 0.7 : 0.0;

  return (
    <>
      {positions.map(([x, z], i) => (
        <group key={i} position={[x, yMid, z]}>
          {structuralSystem === 'steel' ? (
            <>
              <mesh castShadow>
                <boxGeometry args={[colW, totalH, colW * 0.15]} />
                <meshStandardMaterial color={colColor} roughness={rough} metalness={metal} />
              </mesh>
              <mesh castShadow>
                <boxGeometry args={[colW * 0.15, totalH, colW]} />
                <meshStandardMaterial color={colColor} roughness={rough} metalness={metal} />
              </mesh>
            </>
          ) : (
            <mesh castShadow receiveShadow>
              <boxGeometry args={[colW, totalH, colW]} />
              <meshStandardMaterial color={colColor} roughness={rough} metalness={metal} />
            </mesh>
          )}
        </group>
      ))}
    </>
  );
}

// ── MEP line — 3D pipes/ducts/conduit ─────────────────────────────────
function MEPLine({ el }: { el: any }) {
  if (!el.start || !el.end) return null;

  const [x0, y0, z0] = el.start;
  const [x1, y1, z1] = el.end;
  const dx = x1 - x0, dy = y1 - y0, dz = z1 - z0;
  const length = Math.sqrt(dx*dx + dy*dy + dz*dz);
  if (length < 0.01) return null;

  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, cz = (z0 + z1) / 2;

  // Pipe/duct radius by system and type
  const isPlumbing = el.system === 'plumbing';
  const isHVAC = el.system === 'hvac';
  const isFire = el.system === 'fire';
  const radius = isPlumbing
    ? (el.type === 'riser' ? 0.07 : el.type === 'waste_branch' ? 0.06 : 0.04)
    : isHVAC
    ? (el.type === 'supply_duct' ? 0.18 : 0.06)
    : isFire
    ? (el.type === 'main' || el.type === 'riser' ? 0.06 : 0.04)
    : 0.03; // electrical conduit

  const color = COLORS[el.system] || '#888';

  // Rotation: default CylinderGeometry is along Y — rotate to point from start→end
  const geometry = useMemo(() => {
    const geo = new THREE.CylinderGeometry(radius, radius, length, 8, 1);
    return geo;
  }, [radius, length]);

  // Compute quaternion to orient cylinder from start to end
  const quaternion = useMemo(() => {
    const dir = new THREE.Vector3(dx, dy, dz).normalize();
    const up = new THREE.Vector3(0, 1, 0);
    const q = new THREE.Quaternion();
    if (Math.abs(dir.dot(up)) < 0.999) {
      q.setFromUnitVectors(up, dir);
    } else if (dir.y < 0) {
      q.setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI);
    }
    return q;
  }, [dx, dy, dz]);

  return (
    <mesh position={[cx, cy, cz]} quaternion={quaternion} geometry={geometry}>
      {isHVAC ? (
        <meshStandardMaterial color={color} roughness={0.5} metalness={0.3} transparent opacity={0.85} />
      ) : isPlumbing ? (
        <meshStandardMaterial color={color} roughness={0.4} metalness={0.5} />
      ) : isFire ? (
        <meshStandardMaterial color={color} roughness={0.35} metalness={0.55} emissive="#440000" emissiveIntensity={0.15} />
      ) : (
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.25} roughness={0.6} metalness={0.2} />
      )}
    </mesh>
  );
}

// ── MEP point (fixtures, panels, outlets, alarms, etc) ────────────────
function MEPPoint({ el }: { el: any }) {
  if (!el.start) return null;
  const [x, y, z] = el.start;
  const color = COLORS[el.type] || COLORS[el.system] || '#888';
  const type = el.type;

  if (type === 'toilet') {
    return (
      <group position={[x, y, z]}>
        <mesh position={[0, 0.22, 0]}><boxGeometry args={[0.45, 0.44, 0.65]} /><meshStandardMaterial color="#e8e8e8" roughness={0.3} /></mesh>
        <mesh position={[0, 0.5, -0.2]}><boxGeometry args={[0.42, 0.15, 0.28]} /><meshStandardMaterial color="#ddd" roughness={0.2} /></mesh>
      </group>
    );
  }
  if (type === 'sink') {
    return (
      <group position={[x, y, z]}>
        <mesh position={[0, 0.82, 0]}><boxGeometry args={[0.55, 0.07, 0.42]} /><meshStandardMaterial color="#d0d8e0" roughness={0.15} metalness={0.1} /></mesh>
        <mesh position={[0, 0.42, 0]}><boxGeometry args={[0.06, 0.84, 0.06]} /><meshStandardMaterial color="#aaa" metalness={0.7} roughness={0.2} /></mesh>
      </group>
    );
  }
  if (type === 'shower') {
    return (
      <group position={[x, y, z]}>
        <mesh position={[0, 0.06, 0]}><boxGeometry args={[0.9, 0.08, 0.9]} /><meshStandardMaterial color="#c8d8e8" roughness={0.1} metalness={0.05} transparent opacity={0.6} /></mesh>
        <mesh position={[0, 1.0, 0]}><cylinderGeometry args={[0.015, 0.015, 2.0, 6]} /><meshStandardMaterial color="#999" metalness={0.8} roughness={0.2} /></mesh>
      </group>
    );
  }
  if (type === 'outlet') {
    return (
      <group position={[x, y, z]}>
        {/* Outlet face plate */}
        <mesh>
          <boxGeometry args={[0.12, 0.18, 0.025]} />
          <meshStandardMaterial color="#f0f0ea" roughness={0.6} />
        </mesh>
        {/* Two socket holes (emissive so they read as real openings) */}
        <mesh position={[-0.025, 0.03, 0.013]}>
          <boxGeometry args={[0.015, 0.025, 0.005]} />
          <meshStandardMaterial color="#1a1a1a" emissive="#000" roughness={1} />
        </mesh>
        <mesh position={[0.025, 0.03, 0.013]}>
          <boxGeometry args={[0.015, 0.025, 0.005]} />
          <meshStandardMaterial color="#1a1a1a" emissive="#000" roughness={1} />
        </mesh>
      </group>
    );
  }
  if (type === 'fire_alarm') {
    return (
      <mesh position={[x, y, z]}>
        <cylinderGeometry args={[0.1, 0.1, 0.04, 12]} />
        <meshStandardMaterial color="#dd2200" emissive="#aa1100" emissiveIntensity={0.4} roughness={0.5} />
      </mesh>
    );
  }
  if (type === 'sprinkler') {
    return (
      <group position={[x, y, z]}>
        <mesh><cylinderGeometry args={[0.04, 0.04, 0.08, 8]} /><meshStandardMaterial color="#888" metalness={0.7} roughness={0.3} /></mesh>
        <mesh position={[0, -0.06, 0]}><sphereGeometry args={[0.06, 8, 8]} /><meshStandardMaterial color="#cc3300" /></mesh>
      </group>
    );
  }
  if (type === 'exhaust_fan') {
    return (
      <mesh position={[x, y, z]}>
        <boxGeometry args={[0.25, 0.06, 0.25]} />
        <meshStandardMaterial color="#334155" roughness={0.7} />
      </mesh>
    );
  }
  // ── Furniture ───────────────────────────────────────────────────────
  const FURNITURE_COLORS: Record<string, string> = {
    sofa: '#6b4c3b', bed: '#3a5a7a', counter: '#c8bfaa', stove: '#3a3a3a',
    refrigerator: '#c0c0c0', dining_table: '#7a5a3a', desk: '#5a3a1a',
    dresser: '#7a5a3a', coffee_table: '#5a3a1a', tv_unit: '#1a1a1a',
    washer: '#8888aa', dryer: '#8888aa', kitchen_island: '#c8bfaa',
    bookshelf: '#7a5a3a',
  };
  if (FURNITURE_COLORS[type] !== undefined) {
    const wm = ((el.width_in as number) || 36) / 39.37;
    const hm = ((el.height_in as number) || 30) / 39.37;
    const dm = type === 'sofa' ? 0.85
             : type === 'bed' ? 1.95
             : type === 'counter' ? 0.60
             : type === 'kitchen_island' ? 0.85
             : type === 'dresser' ? 0.50
             : type === 'bookshelf' ? 0.30
             : type === 'desk' ? 0.70
             : type === 'dining_table' ? 0.90
             : wm * 0.55;
    const fColor = FURNITURE_COLORS[type];
    return (
      <mesh position={[x, y + hm / 2, z]}>
        <boxGeometry args={[wm, hm, dm]} />
        <meshStandardMaterial color={fColor} roughness={0.88} metalness={0.04} />
      </mesh>
    );
  }

  // Generic: panel, lighting_point, mini_split_head, rooftop_unit
  const size = type === 'panel' ? 0.3 : type === 'rooftop_unit' ? 1.2 : 0.18;
  return (
    <mesh position={[x, y, z]}>
      {type === 'panel' ? <boxGeometry args={[0.1, 0.6, 0.4]} /> : <sphereGeometry args={[size / 2, 8, 8]} />}
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.4} />
    </mesh>
  );
}

// ── Door mesh ──────────────────────────────────────────────────────────
function DoorMesh({ mesh }: { mesh: any }) {
  const geometry = useMemo(() => {
    try {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(mesh.vertices.flat()), 3));
      geo.setIndex(new THREE.BufferAttribute(new Uint16Array(mesh.faces.flat()), 1));
      geo.computeVertexNormals();
      return geo;
    } catch { return null; }
  }, [mesh.vertices, mesh.faces]);
  if (!geometry) return null;
  const isDoor = mesh.element_type === 'door';
  return (
    <mesh geometry={geometry} castShadow>
      <meshStandardMaterial
        color={isDoor ? (mesh.color || '#7c5c3a') : '#1e293b'}
        roughness={isDoor ? 0.7 : 0.4}
        metalness={isDoor ? 0.05 : 0.1}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

// ── RoofMesh — kept for parapet/mono-pitch backend meshes ─────────────
function RoofMesh({ mesh }: { mesh: any }) {
  const geometry = useBufferGeo(mesh.vertices, mesh.faces);
  if (!geometry) return null;
  return (
    <mesh geometry={geometry} castShadow receiveShadow>
      <PBRMaterial texName="roof_tiles" fallbackColor={mesh.color || '#374151'} roughness={0.85} metalness={0.05} />
    </mesh>
  );
}

// ── HipRoofMesh — built from the same footprint as MassingShell ────────
// Eave ring = wall top ring (same pts, same totalH) → zero gap guaranteed.
function HipRoofMesh({ massing, levels, floorH, texName, roughness, metalness }: {
  massing: any; levels: any[]; floorH: number;
  texName: string; roughness: number; metalness: number;
}) {
  const footprint: [number, number][] = massing?.footprint || [];
  if (footprint.length < 3) return null;
  const totalH = levels.length * floorH;

  const geometry = useMemo(() => {
    try {
      // Strip closing point if Shapely included it
      const raw = footprint[footprint.length - 1][0] === footprint[0][0] &&
                  footprint[footprint.length - 1][1] === footprint[0][1]
        ? footprint.slice(0, -1) : footprint;
      const n = raw.length;
      if (n < 3) return null;

      const xs = raw.map(p => p[0]);
      const zs = raw.map(p => p[1]);
      const minD = Math.min(
        Math.max(...xs) - Math.min(...xs),
        Math.max(...zs) - Math.min(...zs),
      );
      const peakH = Math.max(0.6, minD * 0.28);   // ~17° pitch, min 0.6m

      // Apex at footprint centroid — always inside even for L/U shapes
      const apexX = xs.reduce((a, b) => a + b, 0) / n;
      const apexZ = zs.reduce((a, b) => a + b, 0) / n;
      const apexY = totalH + peakH;

      // Vertices: eave ring at EXACTLY totalH, then apex
      const verts = new Float32Array((n + 1) * 3);
      for (let i = 0; i < n; i++) {
        verts[i * 3]     = raw[i][0];
        verts[i * 3 + 1] = totalH;          // ← exactly matches MassingShell top
        verts[i * 3 + 2] = raw[i][1];
      }
      verts[n * 3]     = apexX;
      verts[n * 3 + 1] = apexY;
      verts[n * 3 + 2] = apexZ;

      // Fan triangles: each wall-top edge → apex
      const idx: number[] = [];
      for (let i = 0; i < n; i++) {
        const j = (i + 1) % n;
        idx.push(i, j, n);   // CCW winding, apex = index n
      }

      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(verts, 3));
      geo.setIndex(idx);
      geo.computeVertexNormals();
      return geo;
    } catch { return null; }
  }, [footprint, totalH]);

  if (!geometry) return null;
  return (
    <mesh geometry={geometry} castShadow receiveShadow>
      <PBRMaterial texName={texName} fallbackColor="#374151" roughness={roughness} metalness={metalness} />
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
  // Spandrel bands are opaque panels that cover the textured shell — skip them
  if (mesh.element_type === 'spandrel_band') return null;
  const isWindow = mesh.element_type === 'window';
  const isBalcony = mesh.element_type === 'balcony';
  const isRail = mesh.element_type === 'balcony_rail';

  if (isWindow) {
    return (
      <mesh geometry={geometry} castShadow={false} receiveShadow={false} renderOrder={2}>
        <meshPhysicalMaterial
          color="#a8d8f0"
          transmission={0.6}
          roughness={0.05}
          thickness={0.2}
          ior={1.45}
          transparent
          opacity={0.7}
          side={THREE.DoubleSide}
          depthWrite={false}
          polygonOffset
          polygonOffsetFactor={-2}
          polygonOffsetUnits={-2}
        />
      </mesh>
    );
  }
  if (mesh.element_type === 'window_frame') {
    return (
      <mesh geometry={geometry} castShadow receiveShadow renderOrder={2}>
        <meshStandardMaterial color="#1a2535" roughness={0.3} metalness={0.5} side={THREE.DoubleSide}
          polygonOffset polygonOffsetFactor={-2} polygonOffsetUnits={-2} />
      </mesh>
    );
  }

  return (
    <mesh geometry={geometry} castShadow receiveShadow>
      <meshStandardMaterial
        color={mesh.color || '#94a3b8'}
        roughness={isRail ? 0.4 : isBalcony ? 0.7 : 0.82}
        metalness={isRail ? 0.6 : 0.0}
        side={THREE.DoubleSide}
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

// ── Solid exterior shell extruded from massing footprint ──────────────
// This IS the building exterior — matches the parcel shape exactly.
function MassingShell({ massing, levels, floorH, texName, roughness, metalness }: {
  massing: any; levels: any[];
  floorH: number; texName: string; roughness: number; metalness: number;
}) {
  const footprint: [number, number][] = massing?.footprint || [];
  if (footprint.length < 3) return null;
  const totalH = levels.length * floorH;

  const geometry = useMemo(() => {
    try {
      const pts = footprint[footprint.length - 1][0] === footprint[0][0] &&
                  footprint[footprint.length - 1][1] === footprint[0][1]
        ? footprint.slice(0, -1) : footprint;
      const shape = new THREE.Shape();
      shape.moveTo(pts[0][0], -pts[0][1]);
      for (let i = 1; i < pts.length; i++) shape.lineTo(pts[i][0], -pts[i][1]);
      shape.closePath();
      const geo = new THREE.ExtrudeGeometry(shape, { depth: totalH, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      return geo;
    } catch { return null; }
  }, [footprint, totalH]);

  if (!geometry) return null;
  return (
    <mesh geometry={geometry} castShadow receiveShadow>
      <PBRMaterial texName={texName} fallbackColor="#334155" roughness={roughness} metalness={metalness} />
    </mesh>
  );
}

// ── Concrete floor slab at each level boundary ─────────────────────────
function FloorSlab({ massing, levelIdx, floorH }: {
  massing: any; levelIdx: number; floorH: number;
}) {
  const footprint: [number, number][] = massing?.footprint || [];
  if (footprint.length < 3) return null;

  const geometry = useMemo(() => {
    try {
      const pts = footprint[footprint.length - 1][0] === footprint[0][0] &&
                  footprint[footprint.length - 1][1] === footprint[0][1]
        ? footprint.slice(0, -1) : footprint;
      const shape = new THREE.Shape();
      shape.moveTo(pts[0][0], -pts[0][1]);
      for (let i = 1; i < pts.length; i++) shape.lineTo(pts[i][0], -pts[i][1]);
      shape.closePath();
      const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.22, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      return geo;
    } catch { return null; }
  }, [footprint]);

  if (!geometry) return null;
  return (
    <mesh geometry={geometry} position={[0, levelIdx * floorH, 0]} receiveShadow castShadow>
      <meshStandardMaterial color="#c8d0dc" roughness={0.55} metalness={0.1} />
    </mesh>
  );
}

// ── Parcel shape 3D preview (extruded to target height) ────────────────
function ParcelPreview({ parcelPolygon, siteCenter, targetHeight }: {
  parcelPolygon: any; siteCenter: [number, number]; targetHeight: number;
}) {
  const geometry = useMemo(() => {
    try {
      const coords = parcelPolygon?.coordinates?.[0];
      if (!coords || coords.length < 3) return null;
      const mPerDegLon = 111320 * Math.cos(siteCenter[1] * Math.PI / 180);
      const localPts = coords.map(([lon, lat]: [number, number]) => [
        (lon - siteCenter[0]) * mPerDegLon,
        (lat - siteCenter[1]) * 111320,
      ]);
      const shape = new THREE.Shape();
      shape.moveTo(localPts[0][0], -localPts[0][1]);
      for (let i = 1; i < localPts.length; i++) shape.lineTo(localPts[i][0], -localPts[i][1]);
      shape.closePath();
      const geo = new THREE.ExtrudeGeometry(shape, { depth: Math.max(1, targetHeight), bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      return geo;
    } catch { return null; }
  }, [parcelPolygon, siteCenter, targetHeight]);
  if (!geometry) return null;
  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial color="#00e5ff" roughness={0.7} transparent opacity={0.09} side={THREE.DoubleSide} />
    </mesh>
  );
}

// ── Helper: convert lat/lon to local meters ────────────────────────────
function toLocal(lon: number, lat: number, siteCenter: [number, number]): [number, number] {
  const x = (lon - siteCenter[0]) * 111320 * Math.cos(siteCenter[1] * Math.PI / 180);
  const z = (lat - siteCenter[1]) * 111320;
  return [x, z];
}

// ── Power plant 3D marker ──────────────────────────────────────────────
function PowerPlant({ feature, siteCenter }: { feature: any; siteCenter: [number, number] }) {
  const coords = feature.geometry?.coordinates;
  if (!coords) return null;
  const [x, z] = toLocal(coords[0], coords[1], siteCenter);
  if (Math.abs(x) > 2000 || Math.abs(z) > 2000) return null;
  const fuel = (feature.properties?.fuel || '').toUpperCase();
  const color = fuel === 'SUN' ? '#facc15' : fuel === 'WND' ? '#34d399' : fuel === 'GAS' ? '#f97316' : fuel === 'NUC' ? '#a78bfa' : '#94a3b8';
  return (
    <group position={[x, 0, z]}>
      {/* Stack */}
      <mesh position={[0, 8, 0]}>
        <cylinderGeometry args={[1.5, 2, 16, 8]} />
        <meshStandardMaterial color="#64748b" roughness={0.8} />
      </mesh>
      {/* Indicator sphere */}
      <mesh position={[0, 17, 0]}>
        <sphereGeometry args={[2, 10, 10]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.6} />
      </mesh>
      <pointLight position={[0, 18, 0]} intensity={0.4} color={color} distance={80} />
    </group>
  );
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
      shape.moveTo(localPts[0][0], -localPts[0][1]);
      for (let i = 1; i < localPts.length; i++) shape.lineTo(localPts[i][0], -localPts[i][1]);
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
  const { buildingModel, activeLayers, selectedSite, infrastructure, neighborConstraints, spec, siteContext, drawnParcel } = useAppStore();
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

  const allNeighborBuildings = useMemo(() => {
    const filtered = (infrastructure?.buildings || []).filter((b: any) => {
      const coords = b.geometry?.coordinates?.[0];
      if (!coords?.length) return true;
      const cx = coords.reduce((s: number, p: number[]) => s + p[0], 0) / coords.length;
      const cz = coords.reduce((s: number, p: number[]) => s + p[1], 0) / coords.length;
      if (buildingModel && exCentroid) {
        const dist = Math.sqrt((cx - exCentroid[0]) ** 2 + (cz - exCentroid[1]) ** 2);
        if (dist < 0.00003) return false;
      }
      return true;
    });
    // Sort by distance to site center and cap at 25 to reduce render load
    return filtered.sort((a: any, b: any) => {
      const ac = a.geometry?.coordinates?.[0] || [];
      const bc = b.geometry?.coordinates?.[0] || [];
      const acx = ac.length ? ac.reduce((s: number, p: number[]) => s + p[0], 0) / ac.length : 0;
      const acz = ac.length ? ac.reduce((s: number, p: number[]) => s + p[1], 0) / ac.length : 0;
      const bcx = bc.length ? bc.reduce((s: number, p: number[]) => s + p[0], 0) / bc.length : 0;
      const bcz = bc.length ? bc.reduce((s: number, p: number[]) => s + p[1], 0) / bc.length : 0;
      const da = (acx - siteCenter[0]) ** 2 + (acz - siteCenter[1]) ** 2;
      const db = (bcx - siteCenter[0]) ** 2 + (bcz - siteCenter[1]) ** 2;
      return da - db;
    }).slice(0, 25);
  }, [infrastructure?.buildings, buildingModel, exCentroid, siteCenter]);
  const closestNeighbors = neighborConstraints?.closest_neighbors || [];
  const powerConnection = infrastructure?.power_connection || null;

  const matColor = MATERIAL_COLORS[(spec as any)?.structural_system] || '#94a3b8';
  // Use actual floor-to-floor height from the model so massing bands, rooms, walls, and MEP all align
  const floorH = buildingModel?.levels?.[0]?.height_ft
    ? buildingModel.levels[0].height_ft * 0.3048
    : 3.0;
  const FLOOR_H = floorH;

  // Resolve wall texture: material_overrides.walls > design_brief (Claude AI) > neighbor_style (OSM)
  const wallOverride = (spec as any)?.material_overrides?.walls ?? '';
  const briefMat = (buildingModel as any)?.design_brief?.facade_material ?? '';
  const neighborMat = (buildingModel as any)?.neighbor_style?.dominant_material ?? '';
  const effectiveMat = (wallOverride && wallOverride !== 'ai') ? wallOverride : (briefMat || neighborMat);
  const { texName, roughness: texRoughness, metalness: texMetalness } = useMemo(
    () => resolveTexture((spec as any)?.structural_system ?? 'wood', effectiveMat),
    [(spec as any)?.structural_system, effectiveMat]
  );

  // Resolve floor texture separately from wall texture
  const floorOverride = (spec as any)?.material_overrides?.floors ?? '';
  const { texName: floorTexName, roughness: floorRoughness, metalness: floorMetalness } = useMemo(
    () => (floorOverride && floorOverride !== 'ai')
      ? resolveTexture('wood', floorOverride)
      : { texName: 'interior_tiles', roughness: 0.55, metalness: 0.0 },
    [floorOverride]
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
      {activeLayers['power_grid'] && infrastructure?.power_plants?.map((f: any, i: number) => (
        <PowerPlant key={`plant_${i}`} feature={f} siteCenter={siteCenter} />
      ))}
      {infrastructure?.manholes?.map((f: any, i: number) => (
        <Manhole key={`mh_${i}`} feature={f} siteCenter={siteCenter} />
      ))}

      {/* Generated building */}
      {buildingModel && (
        <>
          {/* ── Solid exterior shell ── */}
          {activeLayers['architecture'] && (() => {
            const massing = buildingModel.massing_options?.[buildingModel.chosen_massing_index];
            return (
              <>
                <MassingShell
                  massing={massing}
                  levels={buildingModel.levels}
                  floorH={floorH}
                  texName={texName}
                  roughness={texRoughness}
                  metalness={texMetalness}
                />
                {/* Floor slabs at each level boundary */}
                {buildingModel.levels.map((_: any, i: number) => (
                  <FloorSlab key={`slab_${i}`} massing={massing} levelIdx={i} floorH={floorH} />
                ))}
                {/* Room floors — thin colored slabs showing room layout */}
                {buildingModel.rooms
                  .filter((r: any) => FLOOR_ROOM_TYPES.has(r.type))
                  .map((r: any, i: number) => (
                    <RoomMesh key={`rm_${i}`} room={r} matColor={matColor} texName={floorTexName} roughness={floorRoughness} metalness={floorMetalness} floorH={floorH} />
                  ))}
              </>
            );
          })()}
          {/* Structural members — backend output only; no generic pillar fallback for residential */}
          {activeLayers['structure'] && (buildingModel.structural_members || []).length > 0 &&
            (buildingModel.structural_members || []).map((m: any) => (
              <StructuralMemberMesh key={m.id} member={m} />
            ))
          }
          {/* MEP: pipes, ducts, conduit, fixtures — fire system on its own 'fire' layer */}
          {buildingModel.mep_elements.map((el: any) => {
            const FIXTURE_TYPES = ['toilet','sink','shower','outlet','fire_alarm','sprinkler','exhaust_fan','kitchen_sink','range_hood'];
            const isFireFixture = ['sprinkler', 'fire_alarm'].includes(el.type);
            const isFixture = FIXTURE_TYPES.includes(el.type);
            if (el.system === 'fire' || isFireFixture) {
              if (!activeLayers['fire']) return null;
              return el.end ? <MEPLine key={el.id} el={el} /> : <MEPPoint key={el.id} el={el} />;
            }
            if (isFixture) {
              if (!activeLayers['fixtures']) return null;
              return <MEPPoint key={el.id} el={el} />;
            }
            if (!activeLayers[el.system as LayerKey]) return null;
            return el.end ? <MEPLine key={el.id} el={el} /> : <MEPPoint key={el.id} el={el} />;
          })}

          {/* Massing meshes: terrain, footprint outline, overlap, parapet */}
          {(() => {
            const massing = buildingModel.massing_options?.[buildingModel.chosen_massing_index];
            const meshes: any[] = massing?.meshes || [];
            // If backend generated a hip/gabled roof mesh, replace it with the
            // frontend HipRoofMesh that's built from the same footprint — zero gap.
            const hasHipRoof = meshes.some((m: any) => m.element_type === 'roof');
            return <>
              {meshes.map((m: any, i: number) => {
                if (m.element_type === 'terrain')      return <TerrainMesh key={`t_${i}`} mesh={m} />;
                if (m.element_type === 'floor_band')   return activeLayers['structure'] ? <FloorBandMesh key={`fb_${i}`} mesh={m} /> : null;
                if (m.element_type === 'overlap')      return <OverlapMesh key={`ov_${i}`} mesh={m} />;
                if (m.element_type === 'footprint_ok') return <FootprintMesh key={`fp_${i}`} mesh={m} />;
                if (m.element_type === 'roof')         return null; // replaced by HipRoofMesh below
                if (m.element_type === 'parapet')      return activeLayers['roof'] ? <RoofMesh key={`par_${i}`} mesh={m} /> : null;
                return null;
              })}
              {hasHipRoof && activeLayers['roof'] && (
                <HipRoofMesh
                  massing={massing}
                  levels={buildingModel.levels}
                  floorH={floorH}
                  texName={texName}
                  roughness={texRoughness}
                  metalness={texMetalness}
                />
              )}
            </>;
          })()}

          {/* Facade details: windows, doors, parapet */}
          {(buildingModel.meshes || []).map((mesh: any, i: number) => {
            if (mesh.element_type === 'door' || mesh.element_type === 'door_frame') {
              return activeLayers['architecture'] ? <DoorMesh key={`d_${i}`} mesh={mesh} /> : null;
            }
            if (!activeLayers['architecture']) return null;
            return <FacadeMesh key={`facade_${i}`} mesh={mesh} floorH={FLOOR_H} />;
          })}

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

      {/* Parcel shape envelope — only shown BEFORE generation */}
      {selectedSite && !buildingModel && (() => {
        const parcelPoly = drawnParcel || siteContext?.parcel_polygon;
        if (!parcelPoly) return null;
        const estH = ((spec as any).stories || 2) * (((spec as any).floor_to_floor_height_ft || 10) * 0.3048);
        return <ParcelPreview parcelPolygon={parcelPoly} siteCenter={siteCenter} targetHeight={estH} />;
      })()}

      {/* Empty state placeholder */}
      {!buildingModel && (() => {
        const parcelPoly = drawnParcel || siteContext?.parcel_polygon;
        if (parcelPoly && selectedSite) return null; // parcel preview handles it
        return (
          <mesh position={[0, 3, 0]}>
            <boxGeometry args={[20, 6, 12]} />
            <meshStandardMaterial color="#1e293b" wireframe />
          </mesh>
        );
      })()}
    </>
  );
}

const LAYER_GROUPS: { group: string; layers: { key: LayerKey; label: string; color: string }[] }[] = [
  { group: 'Building', layers: [
    { key: 'architecture', label: 'Walls & Windows', color: '#94a3b8' },
    { key: 'roof',         label: 'Roof', color: '#475569' },
    { key: 'structure',    label: 'Structure (cols/beams)', color: '#a855f7' },
  ]},
  { group: 'MEP', layers: [
    { key: 'plumbing',   label: 'Plumbing Pipes', color: '#3b82f6' },
    { key: 'electrical', label: 'Electrical Conduit', color: '#f59e0b' },
    { key: 'hvac',       label: 'HVAC Ducts', color: '#10b981' },
    { key: 'fire',       label: 'Fire Protection', color: '#ef4444' },
    { key: 'fixtures',   label: 'Fixtures & Outlets', color: '#60a5fa' },
  ]},
  { group: 'Site', layers: [
    { key: 'neighbors',  label: 'Neighbors', color: '#64748b' },
    { key: 'power_grid', label: 'Power Grid', color: '#facc15' },
    { key: 'issues',     label: 'Issues / Clashes', color: '#ef4444' },
  ]},
];

export default function BuildingViewer() {
  const { activeLayers, toggleLayer, buildingModel, neighborConstraints, feasibilityData, infrastructure } = useAppStore();
  const terrain = buildingModel?.site_context?.terrain;
  const feasibility = neighborConstraints?.feasibility;

  return (
    <div className="relative w-full h-full bg-[var(--surface-0)]">
      <Canvas
        shadows
        camera={{ position: [50, 40, 50], fov: 50, near: 0.1, far: 2000 }}
        gl={{ antialias: true, toneMapping: 4, toneMappingExposure: 1.1 }}
      >
        <color attach="background" args={['#080604']} />
        <fog attach="fog" args={['#080604', 120, 340]} />
        <ambientLight intensity={0.55} color="#f5ede0" />
        <hemisphereLight args={['#e8d8c0', '#202820', 0.6]} />
        <directionalLight position={[40, 70, 30]} intensity={1.8} castShadow color="#fff8f0"
          shadow-mapSize={[2048, 2048]} shadow-camera-far={300}
          shadow-camera-left={-80} shadow-camera-right={80}
          shadow-camera-top={80} shadow-camera-bottom={-80} />
        <directionalLight position={[-25, 20, -25]} intensity={0.35} color="#c8d8e8" />
        <directionalLight position={[0, -10, 20]} intensity={0.12} color="#f0e8d8" />
        <Environment preset="apartment" background={false} />
        <Suspense fallback={null}>
          <Scene />
        </Suspense>
        <OrbitControls makeDefault minDistance={0.5} maxDistance={500} maxPolarAngle={Math.PI} enablePan />
      </Canvas>

      {/* Layer toggles */}
      <div className="absolute top-4 right-4 panel p-3 space-y-2 animate-fade-in" style={{ minWidth: '160px' }}>
        <div className="text-[var(--text-secondary)] font-mono text-xs uppercase tracking-wider mb-1">Layers</div>
        {LAYER_GROUPS.map(({ group, layers }) => (
          <div key={group}>
            <div className="text-[9px] font-mono text-[var(--text-secondary)] uppercase tracking-widest opacity-50 mb-1 mt-1">{group}</div>
            {layers.map(({ key, label, color }) => (
              <button key={key} onClick={() => toggleLayer(key)} className="flex items-center gap-2 w-full text-left py-0.5">
                <div className="w-2.5 h-2.5 rounded-sm flex-shrink-0 transition-opacity"
                  style={{ background: color, opacity: activeLayers[key] ? 1 : 0.2 }} />
                <span className="text-[11px] font-mono transition-colors"
                  style={{ color: activeLayers[key] ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                  {label}
                </span>
              </button>
            ))}
          </div>
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
          {/* Real utility data from CEC */}
          {infrastructure?.gas_utility && (
            <div className="mt-1 pt-1 border-t border-[var(--border)]">
              <div className="text-[10px] font-mono text-[var(--text-secondary)] uppercase tracking-wider mb-1">Utilities</div>
              <div className="text-[10px] font-mono" style={{ color: 'var(--text-primary)' }}>
                ⛽ Gas: {infrastructure.gas_utility.abbr || infrastructure.gas_utility.name}
                <span className="opacity-50 ml-1">({infrastructure.gas_utility.category})</span>
              </div>
              {infrastructure.power_plants?.length > 0 && (
                <div className="text-[10px] font-mono text-[var(--text-secondary)]">
                  ⚡ Nearest plant: {infrastructure.power_plants[0].properties.name} ({infrastructure.power_plants[0].properties.fuel})
                </div>
              )}
              <div className="text-[9px] font-mono opacity-40 mt-0.5">Source: CA Energy Commission</div>
            </div>
          )}
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

      {/* Room summary panel — shown after generation */}
      {buildingModel && (() => {
        const rooms = buildingModel.rooms || [];
        const bedroomCount  = rooms.filter((r: any) => r.type === 'bedroom').length;
        const bathroomCount = rooms.filter((r: any) => r.type === 'bathroom').length;
        const totalSqft     = Math.round(rooms
          .filter((r: any) => !['unit', 'corridor', 'stair'].includes(r.type))
          .reduce((s: number, r: any) => s + (r.area_sqft || 0), 0));
        const lvlCount = buildingModel.levels?.length || 1;
        const use      = (buildingModel.spec as any)?.building_use || 'multi_family';
        const archHint = (buildingModel as any)?.design_brief?.archetype
          || (buildingModel as any)?.design_brief?.shape
          || '';
        const matHint  = (buildingModel as any)?.neighbor_style?.dominant_material || '';

        return (
          <div className="absolute top-4 left-4 panel p-3 animate-fade-in" style={{ minWidth: '180px' }}>
            <div className="text-[var(--text-secondary)] font-mono text-xs uppercase tracking-wider mb-2">Building Summary</div>
            <div className="space-y-1">
              {use === 'single_family' || use === 'adu' ? (
                <>
                  <div className="flex justify-between gap-4">
                    <span className="text-[11px] font-mono text-[var(--text-secondary)]">Bedrooms</span>
                    <span className="text-[11px] font-mono text-[var(--text-primary)] font-semibold">{bedroomCount} BR</span>
                  </div>
                  <div className="flex justify-between gap-4">
                    <span className="text-[11px] font-mono text-[var(--text-secondary)]">Bathrooms</span>
                    <span className="text-[11px] font-mono text-[var(--text-primary)] font-semibold">{bathroomCount} BA</span>
                  </div>
                </>
              ) : (
                <div className="flex justify-between gap-4">
                  <span className="text-[11px] font-mono text-[var(--text-secondary)]">Units</span>
                  <span className="text-[11px] font-mono text-[var(--text-primary)] font-semibold">
                    {new Set(rooms.filter((r: any) => r.unit_id && r.type !== 'unit').map((r: any) => r.unit_id)).size || 1}
                  </span>
                </div>
              )}
              <div className="flex justify-between gap-4">
                <span className="text-[11px] font-mono text-[var(--text-secondary)]">Floors</span>
                <span className="text-[11px] font-mono text-[var(--text-primary)] font-semibold">{lvlCount}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-[11px] font-mono text-[var(--text-secondary)]">Total area</span>
                <span className="text-[11px] font-mono text-[var(--accent-cyan)] font-semibold">{totalSqft.toLocaleString()} sqft</span>
              </div>
              {matHint && (
                <div className="flex justify-between gap-4">
                  <span className="text-[11px] font-mono text-[var(--text-secondary)]">Facade</span>
                  <span className="text-[11px] font-mono text-[var(--text-primary)] capitalize">{matHint}</span>
                </div>
              )}
              {archHint && (
                <div className="mt-1 pt-1 border-t border-[var(--border)]">
                  <span className="text-[10px] font-mono text-[var(--text-secondary)] italic capitalize">{archHint}</span>
                </div>
              )}
              {buildingModel.issues?.length > 0 && (
                <div className="mt-1 pt-1 border-t border-[var(--border)] flex items-center gap-1.5">
                  <div className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                    style={{ background: buildingModel.issues.some((i: any) => i.severity === 'error') ? 'var(--accent-red)' : 'var(--accent-amber)' }} />
                  <span className="text-[10px] font-mono text-[var(--text-secondary)]">
                    {buildingModel.issues.filter((i: any) => i.severity === 'error').length} errors,{' '}
                    {buildingModel.issues.filter((i: any) => i.severity === 'warning').length} warnings
                  </span>
                </div>
              )}
            </div>
          </div>
        );
      })()}

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
