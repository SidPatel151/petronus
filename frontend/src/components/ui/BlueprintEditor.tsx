'use client';
import { useMemo, useRef, useState } from 'react';
import { useAppStore } from '@/lib/store';

const M_TO_FT = 3.28084;
const SQM_TO_SQFT = 10.7639;

// Colour coding tuned for the paper ground below, not for a dark field. Real
// construction drawings are dark ink on light stock; rendering pale lines on a
// near-black background is the single biggest reason the plan didn't read like
// the reference sheets.
const ROOM_COLORS: Record<string, string> = {
  // The original palette's hues, kept as-is — cyan bedrooms, green living,
  // amber kitchen, red stair. Only the alpha is raised, because the same
  // values that read well on the old near-black field disappear on paper.
  bedroom: 'rgba(0,229,255,0.26)', bathroom: 'rgba(99,179,237,0.28)',
  kitchen: 'rgba(255,179,0,0.28)', living: 'rgba(0,255,136,0.24)',
  dining: 'rgba(196,168,130,0.34)', family_room: 'rgba(0,255,136,0.18)',
  garage: 'rgba(150,150,160,0.28)', corridor: 'rgba(120,120,140,0.18)',
  hall: 'rgba(120,120,140,0.18)', stair: 'rgba(239,68,68,0.20)',
  closet: 'rgba(160,160,170,0.22)', walk_in_closet: 'rgba(160,160,170,0.22)',
  laundry: 'rgba(120,160,220,0.24)', office: 'rgba(180,140,255,0.26)',
  foyer: 'rgba(196,168,130,0.22)', entry: 'rgba(196,168,130,0.22)',
  mudroom: 'rgba(150,130,100,0.26)', deck: 'rgba(120,200,140,0.22)',
  patio: 'rgba(120,200,140,0.22)', porch: 'rgba(120,200,140,0.22)',
  // Estate program (see High-End-Custom reference plans)
  great_room: 'rgba(0,255,136,0.30)', loggia: 'rgba(120,200,140,0.26)',
  wine_cellar: 'rgba(140,60,80,0.30)', butler_pantry: 'rgba(196,168,130,0.26)',
  cinema_room: 'rgba(90,70,140,0.28)', game_room: 'rgba(120,140,255,0.24)',
  sitting_room: 'rgba(0,255,136,0.16)', sauna: 'rgba(200,140,90,0.28)',
  pool_bath: 'rgba(99,179,237,0.22)', gym: 'rgba(180,200,120,0.26)',
  library: 'rgba(180,140,255,0.20)', dressing_room: 'rgba(160,160,170,0.24)',
  utility: 'rgba(120,120,140,0.22)', mechanical: 'rgba(120,120,140,0.22)',
  pantry: 'rgba(196,168,130,0.26)', half_bath: 'rgba(99,179,237,0.24)',
  media_room: 'rgba(90,70,140,0.24)', bonus_room: 'rgba(180,140,255,0.18)',
  loft: 'rgba(180,140,255,0.18)',
};
const DEFAULT_ROOM_COLOR = 'rgba(120,124,142,0.10)';

// Rooms drawn with a tile hatch, the way wet areas are shown on a real sheet.
const HATCHED_ROOM_TYPES = new Set([
  'bathroom', 'half_bath', 'pool_bath', 'sauna', 'laundry', 'mudroom',
]);

// Mirrors backend floorplan_editor.CONTAINER_ROOM_TYPES: floorplan.py
// creates a "unit" room as a bounding shell around every multi-family
// apartment's actual sub-rooms (living/kitchen/bathroom/bedroom). It always
// overlaps its own children by design and isn't something a user edits
// directly — rendering it as a filled box would visually bury its children,
// and it must be excluded from wall-sharing sign prediction the same way
// the backend excludes it from wall-matching.
const CONTAINER_ROOM_TYPES = new Set(['unit']);

// Plan-view drawing constants, in world units (metres) so they scale with
// the viewBox rather than with screen zoom.
// Wall poché: exterior assemblies are drawn heavier than interior partitions,
// as on a real sheet, instead of every wall being one hairline.
const WALL_T_M = 0.14;              // interior partition
const WALL_T_EXT_M = 0.26;          // exterior assembly
const PLAN_BG = '#f3efe4';          // drawing stock — must match the plan view
const INK = '#12161c';              // wall poché / lettering

const KNOWN_ROOM_TYPES = [
  'bedroom', 'living', 'family_room', 'dining', 'kitchen', 'office', 'loft',
  'media_room', 'bonus_room', 'bathroom', 'half_bath', 'laundry', 'utility',
  'mechanical', 'garage', 'foyer', 'entry', 'mudroom', 'corridor', 'hall',
  'hallway', 'unit', 'walk_in_closet', 'library', 'gym', 'stair', 'pantry',
  'closet', 'storage', 'open_to_below', 'balcony', 'patio', 'porch', 'deck',
  'great_room', 'loggia', 'wine_cellar', 'butler_pantry', 'cinema_room',
  'game_room', 'sitting_room', 'sauna', 'pool_bath', 'dressing_room',
];

/** Feet as architects write them: 12' or 23'-6, never 23.5'. */
function fmtFt(feet: number): string {
  const whole = Math.floor(feet);
  const inches = Math.round((feet - whole) * 12);
  if (inches === 0) return `${whole}'`;
  if (inches === 12) return `${whole + 1}'`;
  return `${whole}'-${inches}`;
}

function polygonCentroid(poly: number[][]): [number, number] {
  let x = 0, y = 0;
  for (const [px, py] of poly) { x += px; y += py; }
  return [x / poly.length, y / poly.length];
}

function polygonEdges(poly: number[][]): [number, number, number, number][] {
  // Tolerate an explicit closing duplicate of the first point, the same way
  // the backend's _polygon_edges does — otherwise a closed ring yields an
  // extra degenerate edge and the two match counts disagree.
  const pts = poly.length >= 2 &&
    poly[0][0] === poly[poly.length - 1][0] && poly[0][1] === poly[poly.length - 1][1]
      ? poly.slice(0, -1) : poly;
  const n = pts.length;
  const edges: [number, number, number, number][] = [];
  for (let i = 0; i < n; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[(i + 1) % n];
    edges.push([x0, y0, x1, y1]);
  }
  return edges;
}

// ── Live drag preview ────────────────────────────────────────────────────
// These mirror backend floorplan_editor so the plan can deform under the
// cursor in real time. They are PREVIEW ONLY — the server recomputes the
// authoritative geometry on release and its answer always wins. (Previously
// the client predicted the drag *direction* and the server trusted it, so any
// divergence between the two silently inverted the edit.)
const EDIT_GRID_M = 0.10;
const COORD_EPS_M = 0.03;
const MIN_EDIT_WIDTH_M = 0.9;

const snapM = (v: number) => Math.round(v / EDIT_GRID_M) * EDIT_GRID_M;

type WallMatch = { room: any; edge: [number, number, number, number] };

/** Mirrors floorplan_editor.move_wall's supporting-line + midpoint-in-span match. */
function matchWallRooms(wall: any, rooms: any[]): WallMatch[] {
  const [x0, y0] = wall.start;
  const [x1, y1] = wall.end;
  const horizontal = Math.abs(y1 - y0) <= 1e-3;
  const lineCoord = horizontal ? (y0 + y1) / 2 : (x0 + x1) / 2;
  const mid: [number, number] = [(x0 + x1) / 2, (y0 + y1) / 2];
  const matches: WallMatch[] = [];
  for (const room of rooms) {
    if (CONTAINER_ROOM_TYPES.has(room.type)) continue;
    for (const edge of polygonEdges(room.polygon)) {
      const [ex0, ey0, ex1, ey1] = edge;
      if (horizontal && Math.abs(ey0 - lineCoord) <= COORD_EPS_M && Math.abs(ey1 - lineCoord) <= COORD_EPS_M) {
        const lo = Math.min(ex0, ex1), hi = Math.max(ex0, ex1);
        if (mid[0] >= lo - 0.05 && mid[0] <= hi + 0.05) { matches.push({ room, edge }); break; }
      } else if (!horizontal && Math.abs(ex0 - lineCoord) <= COORD_EPS_M && Math.abs(ex1 - lineCoord) <= COORD_EPS_M) {
        const lo = Math.min(ey0, ey1), hi = Math.max(ey0, ey1);
        if (mid[1] >= lo - 0.05 && mid[1] <= hi + 0.05) { matches.push({ room, edge }); break; }
      }
    }
  }
  return matches;
}

/** Mirrors floorplan_editor._shift_edge_vertices — span-aware on both axes. */
function shiftEdgeVertices(
  poly: number[][], edge: [number, number, number, number],
  delta: number, horizontal: boolean,
): number[][] {
  const [ex0, ey0, ex1, ey1] = edge;
  const line = horizontal ? (ey0 + ey1) / 2 : (ex0 + ex1) / 2;
  const lo = horizontal ? Math.min(ex0, ex1) : Math.min(ey0, ey1);
  const hi = horizontal ? Math.max(ex0, ex1) : Math.max(ey0, ey1);
  return poly.map(([px, py]) => {
    const cross = horizontal ? py : px;
    const along = horizontal ? px : py;
    const onEdge = Math.abs(cross - line) <= COORD_EPS_M
      && along >= lo - COORD_EPS_M && along <= hi + COORD_EPS_M;
    if (!onEdge) return [px, py];
    return horizontal ? [px, py + delta] : [px + delta, py];
  });
}

/** Mirrors the backend's directly-solved travel clamp, so the ghost stops
 *  exactly where the committed edit will stop. */
function travelBounds(matches: WallMatch[], lineCoord: number, horizontal: boolean): [number, number] {
  const idx = horizontal ? 1 : 0;
  let lo = -1e9, hi = 1e9;
  for (const { room } of matches) {
    const vals = room.polygon.map((p: number[]) => p[idx]);
    const rMin = Math.min(...vals), rMax = Math.max(...vals);
    const extent = rMax - rMin;
    const slack = extent - Math.min(MIN_EDIT_WIDTH_M, extent);
    if (Math.abs(lineCoord - rMax) <= Math.abs(lineCoord - rMin)) lo = Math.max(lo, -slack);
    else hi = Math.min(hi, slack);
  }
  return [lo, hi];
}

function polygonAreaSqft(poly: number[][]): number {
  let a = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x0, y0] = poly[i];
    const [x1, y1] = poly[(i + 1) % poly.length];
    a += x0 * y1 - x1 * y0;
  }
  return Math.abs(a / 2) * SQM_TO_SQFT;
}

const SEV_COLOR: Record<string, string> = {
  warning: 'var(--accent-amber)',
  info: 'var(--accent-cyan)',
};

const WARNING_TYPE_LABELS: Record<string, string> = {
  overlap: 'Overlapping rooms',
  over_sqft: 'Over target sqft',
  below_min_size: 'Below minimum size',
  missing_stair: 'Missing stair',
  non_orthogonal: 'Non-orthogonal walls',
  unassigned_area: 'Unassigned space',
};

export default function BlueprintEditor() {
  const {
    blueprintDraftId, blueprintLevels, blueprintRooms, blueprintWalls,
    blueprintFootprintEnvelopes, blueprintWarnings, blueprintTargetSqft,
    blueprintActiveFloor, blueprintSelectedRoomId, blueprintBusy, blueprintError,
    blueprintFinalizing, jobProgress, jobStep,
    setBlueprintActiveFloor, setBlueprintSelectedRoom, applyBlueprintOp, finalizeBlueprint,
  } = useAppStore();

  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<
    { wallId: string; disp: number; horizontal: boolean; matches: WallMatch[] } | null
  >(null);
  const [expandedWarningGroups, setExpandedWarningGroups] = useState<Set<string>>(new Set());
  const dragState = useRef<{
    wallId: string; startX: number; startY: number; scale: number;
    horizontal: boolean; matches: WallMatch[]; loBound: number; hiBound: number;
  } | null>(null);
  const rafRef = useRef<number | null>(null);
  const [opError, setOpError] = useState('');
  const [finalizeError, setFinalizeError] = useState('');
  const [newType, setNewType] = useState('');

  const roomsOnFloor = useMemo(
    // "unit" shells are bookkeeping containers around their own sub-rooms
    // (see CONTAINER_ROOM_TYPES) — rendering them as a filled box would
    // visually bury living/kitchen/bathroom/bedroom underneath their own
    // apartment's shell, so they're excluded from the plan view entirely.
    () => blueprintRooms.filter((r: any) => r.level === blueprintActiveFloor && !CONTAINER_ROOM_TYPES.has(r.type)),
    [blueprintRooms, blueprintActiveFloor]
  );
  const wallsOnFloor = useMemo(
    () => blueprintWalls.filter((w: any) => w.level === blueprintActiveFloor),
    [blueprintWalls, blueprintActiveFloor]
  );
  // Unit shells are excluded from roomsOnFloor (they'd bury their children),
  // but still drawn as a labeled dashed boundary so multi-family plans are
  // readable as separate apartments.
  const unitShellsOnFloor = useMemo(
    () => blueprintRooms.filter((r: any) => r.level === blueprintActiveFloor && CONTAINER_ROOM_TYPES.has(r.type)),
    [blueprintRooms, blueprintActiveFloor]
  );
  const unitLabel = useMemo(() => {
    const ids = Array.from(new Set(
      blueprintRooms.filter((r: any) => CONTAINER_ROOM_TYPES.has(r.type)).map((r: any) => r.unit_id)
    ));
    return (unitId: string | null) => {
      const i = ids.indexOf(unitId);
      return i >= 0 ? `UNIT ${i + 1}` : 'UNIT';
    };
  }, [blueprintRooms]);
  const envelope = blueprintFootprintEnvelopes[String(blueprintActiveFloor)];

  const bbox = useMemo(() => {
    const pts: number[][] = envelope ? [...envelope] : roomsOnFloor.flatMap((r: any) => r.polygon);
    if (!pts.length) return { minX: 0, minY: 0, w: 10, h: 10 };
    const xs = pts.map((p) => p[0]); const ys = pts.map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const pad = 1.0;
    return { minX: minX - pad, minY: minY - pad, w: (maxX - minX) + pad * 2, h: (maxY - minY) + pad * 2 };
  }, [envelope, roomsOnFloor]);

  // Group repeated warnings by type — a multi-family floor can otherwise
  // produce a dozen near-identical "below minimum size" lines, one per room,
  // which reads as noise rather than signal.
  const warningGroups = useMemo(() => {
    const byType = new Map<string, typeof blueprintWarnings>();
    for (const w of blueprintWarnings) {
      const list = byType.get(w.type) || [];
      list.push(w);
      byType.set(w.type, list);
    }
    return Array.from(byType.entries())
      .map(([type, items]) => ({ type, items, severity: items[0]?.severity || 'info' }))
      .sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'warning' ? -1 : 1));
  }, [blueprintWarnings]);

  const toggleWarningGroup = (type: string) => {
    setExpandedWarningGroups((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type); else next.add(type);
      return next;
    });
  };

  // Rooms as they should look RIGHT NOW, including any in-progress drag. The
  // adjacent rooms used to stay frozen while a bare wall stroke slid away from
  // them, so a drag gave no sense of the rooms actually resizing — the plan
  // only caught up after the server round trip.
  //
  // Declared above the early return below: hooks must run in the same order on
  // every render, and a draft appearing mid-session flips that branch.
  const displayRooms = useMemo(() => {
    if (!drag || drag.disp === 0 || !drag.matches.length) return roomsOnFloor;
    const shifted = new Map<string, number[][]>();
    for (const { room, edge } of drag.matches) {
      shifted.set(room.id, shiftEdgeVertices(room.polygon, edge, drag.disp, drag.horizontal));
    }
    return roomsOnFloor.map((r: any) => {
      const poly = shifted.get(r.id);
      return poly ? { ...r, polygon: poly, area_sqft: polygonAreaSqft(poly) } : r;
    });
  }, [roomsOnFloor, drag]);

  // Walls follow the same displacement so the stroke stays in the gap between
  // the two (now resized) room fills instead of detaching from them.
  const displayWalls = useMemo(() => {
    if (!drag || drag.disp === 0) return wallsOnFloor;
    const [dx, dy] = drag.horizontal ? [0, drag.disp] : [drag.disp, 0];
    return wallsOnFloor.map((w: any) => (
      w.id === drag.wallId
        ? { ...w, start: [w.start[0] + dx, w.start[1] + dy], end: [w.end[0] + dx, w.end[1] + dy] }
        : w
    ));
  }, [wallsOnFloor, drag]);

  if (!blueprintDraftId) {
    return (
      <div className="h-full w-full flex items-center justify-center text-xs font-mono text-[var(--text-secondary)] italic">
        No blueprint draft yet — generate one from Project Setup.
      </div>
    );
  }

  const selectedRoom = blueprintRooms.find((r: any) => r.id === blueprintSelectedRoomId) || null;

  const endDrag = () => {
    if (rafRef.current !== null) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    dragState.current = null;
    setDrag(null);
  };

  const onWallPointerDown = (e: React.PointerEvent, wall: any) => {
    if (wall.is_exterior) return;
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    // preserveAspectRatio="meet" fits the WHOLE viewBox, so the uniform scale
    // is the LARGER of the two ratios. Using bbox.w/rect.width alone
    // understated metres-per-pixel whenever the plan was height-constrained
    // (a deep, narrow footprint in a wide panel — the common case), so the
    // wall lagged behind the cursor and then committed a shorter move.
    const scale = Math.max(bbox.w / rect.width, bbox.h / rect.height);

    const horizontal = Math.abs(wall.end[1] - wall.start[1]) <= 1e-3;
    const lineCoord = horizontal
      ? (wall.start[1] + wall.end[1]) / 2
      : (wall.start[0] + wall.end[0]) / 2;
    const matches = matchWallRooms(wall, roomsOnFloor);
    const [loBound, hiBound] = travelBounds(matches, lineCoord, horizontal);

    dragState.current = {
      wallId: wall.id, startX: e.clientX, startY: e.clientY,
      scale, horizontal, matches, loBound, hiBound,
    };
    setDrag({ wallId: wall.id, disp: 0, horizontal, matches });
  };

  const onWallPointerMove = (e: React.PointerEvent) => {
    const st = dragState.current;
    if (!st) return;
    const raw = st.horizontal
      ? (e.clientY - st.startY) * st.scale
      : (e.clientX - st.startX) * st.scale;
    // Snap and clamp on the client exactly as the server will, so the ghost
    // is a truthful preview of the committed result rather than sliding
    // continuously and then jumping on release.
    const disp = snapM(Math.max(st.loBound, Math.min(raw, st.hiBound)));
    // One state update per animation frame. Every pointermove used to set
    // state directly, re-reconciling the entire SVG scene graph per event.
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const cur = dragState.current;
      if (!cur) return;
      setDrag((d) => (d && d.disp === disp ? d : {
        wallId: cur.wallId, disp, horizontal: cur.horizontal, matches: cur.matches,
      }));
    });
  };

  const onWallPointerUp = async (e: React.PointerEvent, wall: any) => {
    const st = dragState.current;
    if (!st) return;
    const disp = drag?.disp ?? 0;
    if (rafRef.current !== null) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    dragState.current = null;
    setOpError('');

    // Match the server's own dead band (EDIT_GRID_M / 2). The old 0.03 m
    // threshold let 3-5 cm drags through, which the server then rejected with
    // a bogus "already at the minimum wall spacing" error.
    if (Math.abs(disp) < EDIT_GRID_M / 2) { setDrag(null); return; }

    // Send the raw signed world-axis displacement. The server owns direction;
    // the client no longer guesses which room grows.
    const deltaFt = disp * M_TO_FT;
    const res = await applyBlueprintOp('move_wall', {
      level: blueprintActiveFloor, wall_id: wall.id, delta_ft: deltaFt,
    });
    // Hold the preview until the authoritative geometry has landed in the
    // store, so the plan never flashes back to its pre-drag shape mid-request.
    setDrag(null);
    if (!res.ok && res.error) setOpError(res.error);
  };

  const handleRetype = async (roomId: string, type: string) => {
    setOpError('');
    const res = await applyBlueprintOp('retype_room', { level: blueprintActiveFloor, room_id: roomId, new_type: type });
    if (!res.ok && res.error) setOpError(res.error);
  };

  const handleDelete = async (roomId: string) => {
    setOpError('');
    const res = await applyBlueprintOp('delete_room', { level: blueprintActiveFloor, room_id: roomId });
    if (!res.ok && res.error) setOpError(res.error);
    else setBlueprintSelectedRoom(null);
  };

  const handleFinalize = async () => {
    setFinalizeError('');
    try {
      await finalizeBlueprint();
    } catch (e: any) {
      setFinalizeError(e.message || 'Finalize failed');
    }
  };

  const toPath = (poly: number[][]) => poly.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ') + ' Z';

  const totalSqft = blueprintRooms.reduce((s: number, r: any) => s + (r.area_sqft || 0), 0);

  return (
    <div className="h-full w-full flex flex-col bg-[var(--surface-0)]">
      {/* Floor tabs + summary */}
      <div className="flex-shrink-0 flex items-center justify-between px-4 py-2 border-b border-[var(--border)] bg-[var(--surface-1)]">
        <div className="flex items-center gap-1">
          {blueprintLevels.map((lvl: any) => (
            <button
              key={lvl.index}
              onClick={() => setBlueprintActiveFloor(lvl.index)}
              className="px-3 py-1.5 rounded-md text-xs font-mono transition-all"
              style={{
                background: blueprintActiveFloor === lvl.index ? 'var(--surface-4)' : 'transparent',
                color: blueprintActiveFloor === lvl.index ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                border: blueprintActiveFloor === lvl.index ? '1px solid var(--border)' : '1px solid transparent',
              }}
            >
              {lvl.label || `Level ${lvl.index + 1}`}
            </button>
          ))}
        </div>
        <div className="text-xs font-mono text-[var(--text-secondary)]">
          {totalSqft.toFixed(0)} / {blueprintTargetSqft.toFixed(0)} sqft
          {blueprintBusy && <span className="ml-2 text-[var(--accent-cyan)]">saving…</span>}
        </div>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Plan view */}
        <div className="flex-1 min-w-0 relative overflow-hidden" style={{ background: PLAN_BG }}>
          <svg
            ref={svgRef}
            viewBox={`${bbox.minX} ${bbox.minY} ${bbox.w} ${bbox.h}`}
            preserveAspectRatio="xMidYMid meet"
            className="w-full h-full"
            onPointerMove={onWallPointerMove}
            // Without this the ghost sticks forever when the gesture is
            // interrupted (touch cancel, pointer capture lost). Deliberately
            // NOT onPointerLeave — pointer capture keeps a drag alive outside
            // the svg, and cancelling on leave would kill legitimate drags.
            onPointerCancel={endDrag}
          >
            <defs>
              {/* Tile hatch for wet rooms, as drawn on a real sheet. */}
              <pattern
                id="wetHatch" width={0.30} height={0.30}
                patternUnits="userSpaceOnUse" patternTransform="rotate(45)"
              >
                <line x1={0} y1={0} x2={0} y2={0.30} stroke={INK} strokeWidth={0.018} opacity={0.30} />
                <line x1={0} y1={0} x2={0.30} y2={0} stroke={INK} strokeWidth={0.018} opacity={0.30} />
              </pattern>
              {/* Faint construction grid, 1 ft. */}
              <pattern id="planGrid" width={0.3048} height={0.3048} patternUnits="userSpaceOnUse">
                <path
                  d={`M ${0.3048} 0 L 0 0 0 ${0.3048}`} fill="none"
                  stroke={INK} strokeWidth={0.006} opacity={0.10}
                />
              </pattern>
            </defs>

            <rect
              x={bbox.minX} y={bbox.minY} width={bbox.w} height={bbox.h}
              fill="url(#planGrid)" style={{ pointerEvents: 'none' }}
            />

            {/* Unit shells (multi-family): dashed outline + label, so two
                apartments each having their own kitchen reads as two units
                rather than one house with duplicate rooms. */}
            {unitShellsOnFloor.map((u: any) => {
              const xs = u.polygon.map((p: number[]) => p[0]);
              const ys = u.polygon.map((p: number[]) => p[1]);
              return (
                <g key={u.id} style={{ pointerEvents: 'none' }}>
                  <path
                    d={toPath(u.polygon)} fill="none"
                    stroke="#8a6d3b" strokeOpacity={0.75}
                    strokeWidth={WALL_T_M * 0.55}
                    strokeDasharray={`${WALL_T_M * 3} ${WALL_T_M * 2}`}
                  />
                  <text
                    x={(Math.min(...xs) + Math.max(...xs)) / 2} y={Math.min(...ys) + bbox.w * 0.032}
                    fontSize={bbox.w * 0.022} fill="#8a6d3b" textAnchor="middle"
                    style={{ fontFamily: 'monospace', letterSpacing: '0.08em' }}
                  >
                    {unitLabel(u.unit_id)}
                  </text>
                </g>
              );
            })}
            {displayRooms.map((room: any) => {
              const [cx, cy] = polygonCentroid(room.polygon);
              const selected = room.id === blueprintSelectedRoomId;
              // Scale (and if need be, drop) labels that don't fit inside the
              // room box. An unscaled label on a small room spills across its
              // neighbours and reads as if the rooms themselves overlap.
              const rxs = room.polygon.map((p: number[]) => p[0]);
              const rys = room.polygon.map((p: number[]) => p[1]);
              const rw = Math.max(...rxs) - Math.min(...rxs);
              const rh = Math.max(...rys) - Math.min(...rys);
              // Room name in caps over its size in feet-and-inches, the way
              // every room on a real sheet is annotated ("LIVING / 20' x 23'-6").
              const label = room.type.replace(/_/g, ' ').toUpperCase();
              const dim = `${fmtFt(rw * M_TO_FT)} x ${fmtFt(rh * M_TO_FT)}`;
              const baseFs = bbox.w * 0.020;
              const fitFs = Math.min(baseFs, (rw * 0.88) / (label.length * 0.62), rh * 0.30);
              const showLabel = fitFs > bbox.w * 0.006;
              const showDim = showLabel && rh > fitFs * 2.8 && rw > dim.length * fitFs * 0.5;
              return (
                <g key={room.id} onClick={() => setBlueprintSelectedRoom(room.id)} style={{ cursor: 'pointer' }}>
                  <path
                    d={toPath(room.polygon)}
                    fill={ROOM_COLORS[room.type] || DEFAULT_ROOM_COLOR}
                  />
                  {HATCHED_ROOM_TYPES.has(room.type) && (
                    <path d={toPath(room.polygon)} fill="url(#wetHatch)" style={{ pointerEvents: 'none' }} />
                  )}
                  {selected && (
                    <path
                      d={toPath(room.polygon)} fill="rgba(0,150,190,0.16)"
                      stroke="#0a7ea4" strokeWidth={WALL_T_M * 0.45}
                      strokeLinejoin="miter"
                    />
                  )}
                  {showLabel && (
                    <text
                      x={cx} y={showDim ? cy : cy + fitFs * 0.35} fontSize={fitFs}
                      fill={INK} textAnchor="middle"
                      style={{
                        fontFamily: 'var(--font-mono, monospace)', fontWeight: 600,
                        letterSpacing: '0.10em', pointerEvents: 'none',
                      }}
                    >
                      {label}
                    </text>
                  )}
                  {showDim && (
                    <text
                      x={cx} y={cy + fitFs * 1.30} fontSize={fitFs * 0.78}
                      fill={INK} fillOpacity={0.68} textAnchor="middle"
                      style={{ fontFamily: 'var(--font-mono, monospace)', pointerEvents: 'none' }}
                    >
                      {dim}
                    </text>
                  )}
                </g>
              );
            })}
            {displayWalls.map((wall: any) => {
              const isDragging = drag?.wallId === wall.id;
              const [x0, y0] = wall.start; const [x1, y1] = wall.end;
              return (
                <g key={wall.id}>
                  {/* One line per wall, drawn in the gap the room fills
                      leave behind — so a shared wall is a single stroke,
                      not two room outlines plus a wall on top. */}
                  {/* An open boundary is a cased opening — the rooms flow into
                      each other, so no poché is drawn, just a faint break line
                      showing where the plan still separates them. */}
                  <line
                    x1={x0} y1={y0} x2={x1} y2={y1}
                    stroke={isDragging ? '#0a7ea4' : INK}
                    strokeWidth={
                      wall.is_open ? WALL_T_M * 0.22
                        : wall.is_exterior ? WALL_T_EXT_M : WALL_T_M
                    }
                    strokeLinecap="square"
                    strokeOpacity={wall.is_open ? 0.28 : 1}
                    strokeDasharray={wall.is_open ? `${WALL_T_M * 2.5} ${WALL_T_M * 2}` : undefined}
                  />
                  {!wall.is_exterior && (
                    // stroke="transparent" is unreliable for SVG hit-testing in
                    // Chrome (falls through to whatever's underneath) — use a
                    // real color at near-zero opacity instead, which is always
                    // painted for pointer-events purposes.
                    <line
                      x1={x0} y1={y0} x2={x1} y2={y1}
                      stroke="#ffffff" strokeOpacity={0.001} strokeWidth={WALL_T_M * 3}
                      pointerEvents="stroke"
                      style={{ cursor: Math.abs(x1 - x0) < 1e-3 ? 'ew-resize' : 'ns-resize' }}
                      onPointerDown={(e) => onWallPointerDown(e, wall)}
                      onPointerUp={(e) => onWallPointerUp(e, wall)}
                    />
                  )}
                </g>
              );
            })}
          </svg>
          {opError && (
            <div className="absolute bottom-3 left-3 right-3 text-[11px] font-mono text-red-400 bg-black/60 rounded-md px-3 py-2 border border-red-900">
              {opError}
            </div>
          )}
        </div>

        {/* Right panel: warnings + properties + finalize */}
        <div className="w-72 flex-shrink-0 flex flex-col border-l border-[var(--border)] bg-[var(--surface-1)] overflow-y-auto">
          <div className="panel-section">
            <div className="text-xs font-mono text-[var(--text-secondary)] uppercase tracking-wider mb-2">
              Blueprint — {blueprintLevels.length} floor{blueprintLevels.length !== 1 ? 's' : ''}
            </div>
            {blueprintError && <div className="text-[11px] font-mono text-red-400 mb-2">{blueprintError}</div>}
          </div>

          {warningGroups.length > 0 && (
            <div className="panel-section space-y-1.5">
              <div className="text-[10px] font-mono text-[var(--text-secondary)] uppercase tracking-wider">Warnings</div>
              {warningGroups.map((group) => {
                const expanded = expandedWarningGroups.has(group.type) || group.items.length <= 1;
                const color = SEV_COLOR[group.severity] || 'var(--text-secondary)';
                return (
                  <div key={group.type} className="rounded-md overflow-hidden" style={{ border: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                    <div
                      className="text-[11px] font-mono px-2.5 py-1.5 cursor-pointer flex items-center justify-between"
                      style={{ color }}
                      onClick={() => group.items.length > 1 ? toggleWarningGroup(group.type) : (group.items[0].room_ids?.[0] && setBlueprintSelectedRoom(group.items[0].room_ids[0]))}
                    >
                      <span>{WARNING_TYPE_LABELS[group.type] || group.type}</span>
                      <span className="opacity-70">
                        {group.items.length > 1 ? `${group.items.length} ${expanded ? '▾' : '▸'}` : ''}
                      </span>
                    </div>
                    {expanded && group.items.length > 1 && (
                      <div className="border-t" style={{ borderColor: 'var(--border)' }}>
                        {group.items.map((w) => (
                          <div
                            key={w.id}
                            className="text-[10px] font-mono px-2.5 py-1 cursor-pointer opacity-80 hover:opacity-100"
                            style={{ color }}
                            onClick={() => w.room_ids?.[0] && setBlueprintSelectedRoom(w.room_ids[0])}
                          >
                            {w.message}
                          </div>
                        ))}
                      </div>
                    )}
                    {expanded && group.items.length === 1 && (
                      <div className="text-[10px] font-mono px-2.5 pb-1.5 opacity-80" style={{ color }}>
                        {group.items[0].message}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {selectedRoom && (
            <div className="panel-section space-y-2">
              <div className="text-[10px] font-mono text-[var(--text-secondary)] uppercase tracking-wider">Selected Room</div>
              <select
                value={newType || selectedRoom.type}
                onChange={(e) => { setNewType(e.target.value); handleRetype(selectedRoom.id, e.target.value); }}
                className="w-full text-xs font-mono rounded-md px-2 py-1.5 bg-[var(--surface-2)] border border-[var(--border)] text-[var(--text-primary)]"
              >
                {KNOWN_ROOM_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <div className="text-[11px] font-mono text-[var(--text-secondary)]">
                {Math.round(selectedRoom.area_sqft)} sqft · level {selectedRoom.level}
              </div>
              <button
                onClick={() => handleDelete(selectedRoom.id)}
                className="w-full text-xs font-mono px-2.5 py-1.5 rounded-md border transition-all"
                style={{ borderColor: 'rgba(239,68,68,0.4)', color: '#ef4444', background: 'rgba(239,68,68,0.06)' }}
              >
                Delete Room
              </button>
            </div>
          )}

          <div className="mt-auto panel-section space-y-2">
            {finalizeError && <div className="text-[11px] font-mono text-red-400">{finalizeError}</div>}
            <button
              onClick={handleFinalize}
              disabled={blueprintFinalizing}
              className="w-full py-3 rounded-xl font-display font-semibold text-sm transition-all duration-200"
              style={{
                background: blueprintFinalizing ? 'var(--surface-3)' : 'linear-gradient(135deg, #c4a882, #e8d5b0)',
                color: blueprintFinalizing ? 'var(--text-secondary)' : '#0a0907',
                cursor: blueprintFinalizing ? 'not-allowed' : 'pointer',
              }}
            >
              {blueprintFinalizing ? `${jobStep || 'Generating…'} ${jobProgress ? `${jobProgress}%` : ''}` : 'Generate 3D House →'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
