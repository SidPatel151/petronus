"""Floorplan edit engine for the 2D blueprint stage.

Single source of truth: rooms are primary, walls are always fully re-derived
from rooms after any room-geometry change (mirrors floorplan.py's existing
_emit_interior_walls/_place_exterior_walls convention, generalized here from
rectangles to arbitrary orthogonal polygons so L/T/U-shaped rooms work).

Every op function mutates draft.model.rooms/draft.model.walls in place and
raises FloorplanEditError on a rejected op (caught by apply_op, which is the
single dispatcher used by both the manual /edit endpoint and AI chat edits —
see app/api/blueprint.py). Manual and AI edits therefore always go through
the exact same validated code path; nothing ever hands back raw geometry
that bypasses these checks.
"""
import hashlib
import math
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple

from shapely.geometry import Polygon

from app.generators.compliance import KNOWN_ROOM_TYPES
from app.generators.floorplan import (
    FP_INSET, MIN_ROOM_WIDTH_M, split_and_mark_open_walls,
)
from app.models.schemas import BlueprintWarning, Room, Wall
from app.services.draft_state import DraftState

# New constant — no discrete edit/design grid exists anywhere in floorplan.py
# today (layout uses continuous fractional splits). 0.10 m (~4 in) stays
# above floorplan.py's own float-noise tolerances (0.05 m boundary test,
# 0.001 m dedup rounding) while staying fine enough not to visibly distort
# the smallest existing minimum room width (bathroom, 1.5 m).
EDIT_GRID_M = 0.10

# New constant — no existing minimum-room-area concept anywhere in the
# codebase (compliance.py/constants.py/constraints.py all lack one).
MIN_ROOM_AREA_SQFT = 45.0

# Hard geometric floor for interactive edits (~3 ft). This is deliberately
# far below the per-type *recommended* widths in MIN_ROOM_WIDTH_M: those are
# design guidance surfaced as warnings by validate(), not edit constraints.
# Only this floor blocks a drag, and only to prevent degenerate slivers.
MIN_EDIT_WIDTH_M = 0.9

SQM_TO_SQFT = 10.7639
DEFAULT_MIN_WIDTH_M = 1.2
ORTHOGONAL_EPS_DEG = 2.0
COORD_EPS_M = 0.03

# floorplan.py deliberately creates a "unit" room as a bounding shell around
# every multi-family apartment's actual sub-rooms (living/kitchen/bathroom/
# bedroom, all sharing that unit's unit_id) — see floorplan.py's Room(type=
# "unit", ...) call sites. It ALWAYS overlaps/contains its own children by
# design, is not something a user edits directly, and its boundary often
# isn't axis-aligned-relative-to-its-children even when each child room is.
# It must be excluded from overlap/orthogonality/min-size warnings and from
# wall-sharing matches, or every multi-family floor spams false positives.
CONTAINER_ROOM_TYPES = {"unit"}


class FloorplanEditError(Exception):
    """Raised by an op function to reject an edit. Caught by apply_op and
    turned into {ok: False, error: str} — never propagates as a 500, since
    edits are non-blocking/rejectable by design, not server errors."""


def _snap(value: float, grid: float = EDIT_GRID_M) -> float:
    return round(round(value / grid) * grid, 6)


def _rooms_on_level(rooms: List[Room], level: int) -> List[Room]:
    return [r for r in rooms if r.level == level]


def _room_by_id(rooms: List[Room], room_id: str) -> Room:
    for r in rooms:
        if r.id == room_id:
            return r
    raise FloorplanEditError(f"Room '{room_id}' not found")


def _wall_by_id(walls: List[Wall], wall_id: str) -> Wall:
    for w in walls:
        if w.id == wall_id:
            return w
    raise FloorplanEditError(f"Wall '{wall_id}' not found")


def _polygon_edges(poly_coords: List[List[float]]) -> List[Tuple[float, float, float, float]]:
    """Each edge (x0,y0,x1,y1) of a polygon ring, tolerating an explicit
    closing duplicate of the first point."""
    pts = [tuple(p) for p in poly_coords]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    edges = []
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        edges.append((x0, y0, x1, y1))
    return edges


def _points_equal(p0: Tuple[float, float], p1: Tuple[float, float], eps: float = COORD_EPS_M) -> bool:
    return abs(p0[0] - p1[0]) <= eps and abs(p0[1] - p1[1]) <= eps


def _segment_matches_edge(seg: Tuple[float, float, float, float], edge: Tuple[float, float, float, float]) -> bool:
    sx0, sy0, sx1, sy1 = seg
    ex0, ey0, ex1, ey1 = edge
    fwd = _points_equal((sx0, sy0), (ex0, ey0)) and _points_equal((sx1, sy1), (ex1, ey1))
    rev = _points_equal((sx0, sy0), (ex1, ey1)) and _points_equal((sx1, sy1), (ex0, ey0))
    return fwd or rev


def _is_axis_aligned(x0: float, y0: float, x1: float, y1: float, eps: float = COORD_EPS_M) -> bool:
    """Orthogonality test.

    The tolerance deliberately matches COORD_EPS_M, the tolerance the editor
    itself uses to decide two coordinates are the same. At the old eps=1e-3
    the validator called geometry "non-orthogonal" that every other part of
    this module treated as perfectly coincident — a 30x disagreement that
    reported a warning on almost every generated room.
    """
    return abs(x1 - x0) <= eps or abs(y1 - y0) <= eps


def _is_drawable_angle(x0: float, y0: float, x1: float, y1: float,
                       tol_deg: float = 3.0) -> bool:
    """True when an edge sits on a 45° increment — the angles a plan may use.

    Chamfered bays and angled corners are deliberate estate geometry (see the
    45° cuts on the High-End-Custom reference plan), not defects. Flagging every
    non-orthogonal edge meant a correctly drawn angled room reported a warning
    for each of its cut corners. Anything off the 45° grid is still a real
    problem and still warns.
    """
    dx, dy = x1 - x0, y1 - y0
    if abs(dx) <= COORD_EPS_M and abs(dy) <= COORD_EPS_M:
        return True  # degenerate, not an angle problem
    angle = math.degrees(math.atan2(dy, dx)) % 45.0
    return angle <= tol_deg or angle >= 45.0 - tol_deg


def min_width_for(room_type: str) -> float:
    return MIN_ROOM_WIDTH_M.get(room_type, DEFAULT_MIN_WIDTH_M)


def room_extent_along_axis(polygon_coords: List[List[float]], axis: Literal["x", "y"]) -> float:
    idx = 0 if axis == "x" else 1
    vals = [p[idx] for p in polygon_coords]
    return max(vals) - min(vals) if vals else 0.0


def room_area_sqft(polygon_coords: List[List[float]]) -> float:
    try:
        return Polygon(polygon_coords).area * SQM_TO_SQFT
    except Exception:
        return 0.0


def _validated_polygon(coords: List[List[float]], room_type: str) -> Polygon:
    """Reject a shifted ring that folded in on itself.

    Without this an overshooting drag produces a bowtie, and shapely reports a
    bowtie's area as the *difference* of its two lobes — so the edit returned
    ok while the room's sqft silently collapsed. That is the "it makes the
    room smaller" symptom, reported as a success.
    """
    try:
        poly = Polygon(coords)
    except Exception:
        raise FloorplanEditError(f"That move would break the shape of '{room_type}'")
    if not poly.is_valid or poly.area <= 0.0:
        raise FloorplanEditError(f"That move would fold '{room_type}' in on itself")
    return poly


def _interior_wall_id(level: int, p0, p1) -> str:
    """Stable id for a derived interior wall, keyed on its endpoints.

    Endpoints are sorted so the id doesn't depend on which room's edge
    happened to produce the segment first, and rounded to the edit grid's
    resolution so float noise doesn't churn the id between rebuilds.
    """
    a, b = sorted([(round(p0[0], 2), round(p0[1], 2)), (round(p1[0], 2), round(p1[1], 2))])
    digest = hashlib.md5(f"{level}:{a[0]},{a[1]}:{b[0]},{b[1]}".encode()).hexdigest()
    return f"int_wall_{level}_{digest[:8]}"


# ── Wall derivation (rooms are primary, walls are always re-derived) ───────

def derive_walls_for_level(rooms: List[Room], footprint_envelope: Polygon, level: int, height_ft: float) -> List[Wall]:
    """Exterior walls come from the fixed footprint_envelope (never changes
    during editing, by construction — this is how the "footprint is fixed"
    product requirement is enforced structurally, not by convention).
    Interior walls come from every room-on-this-level polygon edge, deduped
    by canonical endpoint key, clipped to the interior inset, skipping any
    edge that lies on the exterior boundary. Generalizes floorplan.py's
    _place_exterior_walls + _emit_interior_walls from rectangles to
    arbitrary orthogonal polygons."""
    walls: List[Wall] = []

    ext_coords = list(footprint_envelope.exterior.coords)
    for i in range(len(ext_coords) - 1):
        walls.append(Wall(
            id=f"ext_wall_{level}_{i}",
            start=list(ext_coords[i]), end=list(ext_coords[i + 1]),
            height_ft=height_ft, level=level, is_exterior=True,
        ))

    fp_ext_band = footprint_envelope.exterior.buffer(0.05)
    fp_interior = footprint_envelope.buffer(-FP_INSET, join_style=2)
    seen: set = set()

    def try_add(x0: float, y0: float, x1: float, y1: float) -> None:
        key_pts = sorted([(round(x0, 3), round(y0, 3)), (round(x1, 3), round(y1, 3))])
        key = (key_pts[0], key_pts[1])
        if key in seen:
            return
        seen.add(key)

        from shapely.geometry import LineString
        line = LineString([[x0, y0], [x1, y1]])
        try:
            if fp_ext_band.contains(line):
                return
        except Exception:
            pass
        try:
            clipped = fp_interior.intersection(line)
            segs = ([clipped] if hasattr(clipped, "coords")
                     else (list(clipped.geoms) if hasattr(clipped, "geoms") else []))
            for seg in segs:
                if hasattr(seg, "coords"):
                    wc = list(seg.coords)
                    if len(wc) >= 2 and LineString(wc).length > 0.05:
                        # Derive the id from the segment's own geometry rather
                        # than a fresh uuid4. Every edit re-derives the whole
                        # level, so random ids meant the wall under the cursor
                        # ceased to exist after each drag: React remounted the
                        # entire wall layer (visible flicker) and a second drag
                        # against the now-stale id failed with "Wall not found".
                        walls.append(Wall(
                            id=_interior_wall_id(level, wc[0], wc[-1]),
                            start=[wc[0][0], wc[0][1]], end=[wc[-1][0], wc[-1][1]],
                            height_ft=height_ft, level=level, is_exterior=False,
                        ))
        except Exception:
            pass

    for room in _rooms_on_level(rooms, level):
        for edge in _polygon_edges(room.polygon):
            try_add(*edge)

    return walls


def _rebuild_level(draft: DraftState, level: int) -> None:
    envelope = draft.footprint_envelopes.get(level)
    if envelope is None:
        raise FloorplanEditError(f"No fixed footprint envelope recorded for level {level}")
    level_height_ft = next((lv.height_ft for lv in draft.model.levels if lv.index == level), 10.0)
    other_walls = [w for w in draft.model.walls if w.level != level]
    new_walls = derive_walls_for_level(draft.model.rooms, envelope, level, level_height_ft)
    # Walls are re-derived from scratch on every edit, so openness has to be
    # re-applied or an open-plan house would grow walls back as you drag.
    new_walls = split_and_mark_open_walls(
        draft.model.rooms, new_walls,
        (getattr(draft, "archetype", None) or {}).get("id", ""),
    )
    draft.model.walls = other_walls + new_walls


# ── Op: move_wall ────────────────────────────────────────────────────────

def move_wall(draft: DraftState, level: int, wall_id: str, delta_ft: float) -> None:
    walls = [w for w in draft.model.walls if w.level == level]
    wall = _wall_by_id(walls, wall_id)
    if wall.is_exterior:
        raise FloorplanEditError("Cannot move an exterior wall — the footprint is fixed once massing is chosen")

    x0, y0 = wall.start[0], wall.start[1]
    x1, y1 = wall.end[0], wall.end[1]
    if not _is_axis_aligned(x0, y0, x1, y1):
        raise FloorplanEditError("Wall is not axis-aligned — only orthogonal walls can be dragged")

    # Interior walls are clipped to the interior inset (FP_INSET) wherever
    # they'd otherwise touch the exterior boundary, so a wall's own start/end
    # rarely match a room polygon's raw edge endpoints exactly. Match by
    # supporting line + span OVERLAP, then use each room's OWN edge coordinates
    # (not the wall's) as that room's shift key — guaranteed to match exactly
    # since it came from that room's polygon in the first place.
    #
    # Overlap rather than "wall midpoint inside the edge's span": one supporting
    # line can be clipped into several wall segments, and a fragment's midpoint
    # frequently lands outside every room edge, which is what produced
    # "doesn't cleanly divide two rooms (matched 0)" on walls that plainly sat
    # between two rooms.
    horizontal = abs(y1 - y0) <= 1e-3  # wall runs along x, moves along y
    line_coord = (y0 + y1) / 2 if horizontal else (x0 + x1) / 2
    w_lo, w_hi = (min(x0, x1), max(x0, x1)) if horizontal else (min(y0, y1), max(y0, y1))
    wall_span = w_hi - w_lo
    # Long walls need a real shared stretch; short ones need most of themselves.
    min_overlap = min(0.25, wall_span * 0.6)

    # Exclude "unit" container shells — their boundary frequently coincides
    # with an interior wall between two of their OWN sub-rooms (a unit is
    # only as deep as whichever room sits against its outer edge there),
    # which would otherwise make a perfectly ordinary wall drag between two
    # real rooms look like it's "shared by 3 rooms."
    rooms = [r for r in _rooms_on_level(draft.model.rooms, level) if r.type not in CONTAINER_ROOM_TYPES]
    matches: List[Tuple[Room, Tuple[float, float, float, float]]] = []
    for r in rooms:
        best_edge = None
        best_overlap = 0.0
        for edge in _polygon_edges(r.polygon):
            ex0, ey0, ex1, ey1 = edge
            if horizontal:
                if abs(ey0 - line_coord) > COORD_EPS_M or abs(ey1 - line_coord) > COORD_EPS_M:
                    continue
                e_lo, e_hi = min(ex0, ex1), max(ex0, ex1)
            else:
                if abs(ex0 - line_coord) > COORD_EPS_M or abs(ex1 - line_coord) > COORD_EPS_M:
                    continue
                e_lo, e_hi = min(ey0, ey1), max(ey0, ey1)
            overlap = min(w_hi, e_hi) - max(w_lo, e_lo)
            # Keep the edge sharing the most of this wall. Taking the first
            # match meant a U-shaped room with two collinear faces could be
            # shifted by whichever face happened to come first in the ring.
            if overlap > best_overlap:
                best_overlap, best_edge = overlap, edge
        if best_edge is not None and best_overlap >= min_overlap:
            matches.append((r, best_edge))
    # A single match means the wall backs onto unassigned circulation space
    # rather than a second room; that room simply grows or shrinks into the
    # free space. Refusing this case made most walls in a generated plan
    # undraggable.
    if len(matches) not in (1, 2):
        raise FloorplanEditError(
            f"This wall doesn't cleanly divide two rooms (matched {len(matches)}) — "
            "try dragging a different wall"
        )

    # `delta_ft` is a SIGNED displacement along the wall's normal axis in world
    # coordinates: +Y for a wall running along X, +X for a wall running along Y.
    # The client sends its raw drag vector and never predicts which room grows.
    #
    # Direction used to be derived independently on both sides — from a vertex
    # average on the client and shapely's area centroid here. Those agree only
    # for rectangles, so on any L-shaped room, and on every wall matching a
    # single room, the two disagreed and the wall travelled opposite to the
    # cursor: you dragged a room outward and it shrank by exactly the drag
    # distance. Owning direction here removes the disagreement by construction.
    disp_m = _snap(delta_ft * 0.3048)

    # Only the matched edge's vertices move, so each room's extent along the
    # normal axis is linear in `disp_m`: a room whose edge sits on its high
    # side grows with positive displacement, one on its low side shrinks. That
    # makes the legal travel range directly solvable, with no search.
    axis_idx = 1 if horizontal else 0
    lo_bound, hi_bound = -1e9, 1e9
    for room, _edge in matches:
        vals = [p[axis_idx] for p in room.polygon]
        r_min, r_max = min(vals), max(vals)
        extent = r_max - r_min
        # Clamp against MIN_EDIT_WIDTH_M (a hard geometric floor that only
        # stops degenerate slivers), NOT the per-type recommended widths in
        # MIN_ROOM_WIDTH_M — generated plans routinely contain rooms already
        # below their type's recommendation, and using it as a hard limit
        # blocked virtually every drag. min(floor, current) lets an already
        # undersized room still be grown; it just can't shrink further.
        slack = extent - min(MIN_EDIT_WIDTH_M, extent)
        if abs(line_coord - r_max) <= abs(line_coord - r_min):
            lo_bound = max(lo_bound, -slack)   # edge on the high side: −disp shrinks it
        else:
            hi_bound = min(hi_bound, slack)    # edge on the low side: +disp shrinks it
    applied = _snap(max(lo_bound, min(disp_m, hi_bound)))
    if abs(applied) < EDIT_GRID_M / 2:
        raise FloorplanEditError(
            f"Can't move this wall any further — an adjoining room is already at "
            f"the {MIN_EDIT_WIDTH_M:.1f} m minimum wall spacing"
        )

    envelope = draft.footprint_envelopes.get(level)
    moved_ids = {room.id for room, _ in matches}
    blockers = [
        r for r in rooms
        if r.id not in moved_ids and len(r.polygon) >= 3
    ]

    # Overlap a room ALREADY has with each blocker before this edit. Generated
    # plans routinely contain small pre-existing overlaps, so an absolute
    # tolerance had to be loose enough to ignore them — at 0.2 m² that let a
    # drag push almost half a metre of one room into another before objecting,
    # which is how a room visibly ended up inside its neighbour. Comparing
    # against the starting overlap instead means existing slop never blocks a
    # drag, but a drag can never make the overlap worse either.
    baseline: Dict[Tuple[str, str], float] = {}
    for room, _edge in matches:
        for other in blockers:
            try:
                baseline[(room.id, other.id)] = (
                    Polygon(room.polygon).intersection(Polygon(other.polygon)).area
                )
            except Exception:
                baseline[(room.id, other.id)] = 0.0

    OVERLAP_SLACK_M2 = 0.02  # ~14 cm square, float/grid noise only

    def _obstruction(disp: float) -> Optional[str]:
        """Name of whatever stops the wall at `disp`, or None if it's clear."""
        for room, edge in matches:
            new_poly = _shift_edge_vertices(room.polygon, edge, disp, horizontal)
            try:
                poly = Polygon(new_poly)
            except Exception:
                return room.type
            if not poly.is_valid or poly.area <= 0.0:
                return room.type
            if envelope is not None:
                try:
                    if not envelope.buffer(1e-6).contains(poly):
                        return "the exterior footprint"
                except Exception:
                    pass
            for other in blockers:
                try:
                    area = poly.intersection(Polygon(other.polygon)).area
                    was = baseline.get((room.id, other.id), 0.0)
                    if area > was + OVERLAP_SLACK_M2:
                        return f"'{other.type}'"
                except Exception:
                    pass
        return None

    # Walk back toward zero until the move is legal, instead of refusing the
    # whole drag. Matched rooms are often only PARTIALLY adjacent along a wall,
    # so pushing them far enough will always eventually meet some third room —
    # rejecting outright meant a drag that was fine for its first 40 cm failed
    # entirely with "'corridor' would overlap 'bedroom'". Displacement is linear
    # in the shift, so stepping down the grid finds the limit directly.
    step = EDIT_GRID_M if applied > 0 else -EDIT_GRID_M
    probe = applied
    blocked_by = _obstruction(probe)
    while blocked_by is not None and abs(probe) > EDIT_GRID_M / 2:
        probe = _snap(probe - step)
        blocked_by = _obstruction(probe)
    if blocked_by is not None or abs(probe) < EDIT_GRID_M / 2:
        raise FloorplanEditError(
            f"Can't move this wall — {blocked_by or 'an adjoining room'} is in the way"
        )
    applied = probe

    moved: List[Tuple[Room, List[List[float]]]] = [
        (room, _shift_edge_vertices(room.polygon, edge, applied, horizontal))
        for room, edge in matches
    ]

    for room, new_poly in moved:
        room.polygon = new_poly
        room.area_sqft = room_area_sqft(new_poly)

    _rebuild_level(draft, level)


def _shift_edge_vertices(
    polygon: List[List[float]], edge_key: Tuple[float, float, float, float],
    delta: float, horizontal: bool,
) -> List[List[float]]:
    """Shift every vertex of `polygon` lying on `edge_key` by `delta` along
    that edge's normal axis, leaving the rest of the ring untouched — this is
    what lets an L/T/U-shaped room's non-adjacent corners stay put.

    Vertices are matched on BOTH axes: on the supporting line *and* within the
    edge's along-axis span. Matching the cross-axis alone made a room's entire
    collinear boundary sweep, including the stretch facing a different room
    around a corner, so grabbing a short wall visibly resized a face the user
    never touched. Matching against the edge's midpoint line (rather than
    requiring proximity to both of its endpoints) also fixes the silent no-op
    where an edge whose endpoints straddled the tolerance band moved nothing
    at all while still reporting success.
    """
    ex0, ey0, ex1, ey1 = edge_key
    if horizontal:
        line = (ey0 + ey1) / 2.0
        lo, hi = min(ex0, ex1), max(ex0, ex1)
    else:
        line = (ex0 + ex1) / 2.0
        lo, hi = min(ey0, ey1), max(ey0, ey1)

    out = []
    for (px, py) in polygon:
        cross, along = (py, px) if horizontal else (px, py)
        on_edge = (
            abs(cross - line) <= COORD_EPS_M
            and (lo - COORD_EPS_M) <= along <= (hi + COORD_EPS_M)
        )
        if on_edge:
            out.append([px, py + delta] if horizontal else [px + delta, py])
        else:
            out.append([px, py])
    return out


# ── Op: resize_room ──────────────────────────────────────────────────────

def resize_room(draft: DraftState, level: int, room_id: str, edge: Literal["north", "south", "east", "west"], delta_ft: float) -> None:
    rooms = _rooms_on_level(draft.model.rooms, level)
    room = _room_by_id(rooms, room_id)
    poly = room.polygon
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)

    horizontal = edge in ("north", "south")
    edge_val = {"north": maxy, "south": miny, "east": maxx, "west": minx}[edge]
    edge_pts = [tuple(p) for p in poly if (abs(p[1] - edge_val) <= COORD_EPS_M if horizontal else abs(p[0] - edge_val) <= COORD_EPS_M)]
    if len(edge_pts) < 2:
        raise FloorplanEditError(f"Room '{room_id}' has no '{edge}' edge to resize")

    edge_key = (edge_pts[0][0], edge_pts[0][1], edge_pts[-1][0], edge_pts[-1][1])
    # Exclude "unit" shells — see CONTAINER_ROOM_TYPES: a real room's edge
    # coinciding with its own containing unit's boundary isn't a conflict
    # with a neighboring room, it's just that unit only being as deep as
    # this room there.
    other_rooms = [r for r in rooms if r.id != room_id and r.type not in CONTAINER_ROOM_TYPES]
    for r in other_rooms:
        if any(_segment_matches_edge(edge_key, e) for e in _polygon_edges(r.polygon)):
            raise FloorplanEditError(
                f"The '{edge}' edge of '{room_id}' is shared with room '{r.id}' — use move_wall instead"
            )

    # By construction, a positive delta_ft always grows the room (moving
    # the chosen edge outward) and a negative delta_ft always shrinks it,
    # regardless of which cardinal edge is picked — `sign` just orients
    # that consistently for the underlying coordinate axis.
    grows_outward = edge in ("north", "east")
    sign = 1.0 if grows_outward else -1.0
    delta_m = _snap(delta_ft * 0.3048)

    # Clamp against the hard geometric floor, not the per-type recommended
    # width — same reasoning as move_wall (see MIN_EDIT_WIDTH_M).
    axis = "y" if horizontal else "x"
    old_extent = room_extent_along_axis(poly, axis)
    floor_w = min(MIN_EDIT_WIDTH_M, old_extent)
    if old_extent + delta_m < floor_w:
        delta_m = _snap(floor_w - old_extent)

    new_poly = _shift_edge_vertices(poly, edge_key, delta_m * sign, horizontal)
    _validated_polygon(new_poly, room.type)

    envelope = draft.footprint_envelopes.get(level)
    if envelope is not None and delta_m > 0:
        try:
            if not envelope.buffer(1e-6).contains(Polygon(new_poly)):
                raise FloorplanEditError(f"Resizing '{room_id}' outward would exceed the fixed footprint")
        except FloorplanEditError:
            raise
        except Exception:
            pass

    room.polygon = new_poly
    room.area_sqft = room_area_sqft(new_poly)
    _rebuild_level(draft, level)


# ── Op: add_room / delete_room / retype_room ────────────────────────────

def add_room(draft: DraftState, level: int, room_type: str, polygon_m: List[List[float]]) -> Room:
    if room_type not in KNOWN_ROOM_TYPES:
        raise FloorplanEditError(f"Unknown room type '{room_type}'")
    try:
        new_poly = Polygon(polygon_m)
        if not new_poly.is_valid or new_poly.area <= 0:
            raise FloorplanEditError("Room polygon is not a valid simple polygon")
    except FloorplanEditError:
        raise
    except Exception:
        raise FloorplanEditError("Room polygon could not be parsed")

    envelope = draft.footprint_envelopes.get(level)
    if envelope is not None and not envelope.buffer(1e-6).contains(new_poly):
        raise FloorplanEditError("New room must lie fully inside the fixed footprint for this level")

    # "unit" shells are excluded here too — a new room dropped into an
    # existing apartment's free space necessarily sits inside its unit
    # shell, which isn't the "existing room" conflict this guards against.
    for r in _rooms_on_level(draft.model.rooms, level):
        if r.type in CONTAINER_ROOM_TYPES:
            continue
        try:
            if Polygon(r.polygon).intersection(new_poly).area > 0.2:
                raise FloorplanEditError(
                    f"New room overlaps existing room '{r.id}' — free up space first with resize_room/move_wall"
                )
        except FloorplanEditError:
            raise
        except Exception:
            pass

    room = Room(
        id=f"room_{uuid.uuid4().hex[:8]}", type=room_type, polygon=polygon_m,
        level=level, area_sqft=room_area_sqft(polygon_m),
    )
    draft.model.rooms.append(room)
    _rebuild_level(draft, level)
    return room


def delete_room(draft: DraftState, level: int, room_id: str) -> None:
    room = _room_by_id(_rooms_on_level(draft.model.rooms, level), room_id)
    draft.model.rooms = [r for r in draft.model.rooms if r.id != room_id]
    _rebuild_level(draft, level)


def retype_room(draft: DraftState, level: int, room_id: str, new_type: str) -> None:
    if new_type not in KNOWN_ROOM_TYPES:
        raise FloorplanEditError(f"Unknown room type '{new_type}'")
    room = _room_by_id(_rooms_on_level(draft.model.rooms, level), room_id)
    room.type = new_type
    # No geometry change — walls are unaffected, skip re-derivation.


# ── validate() ───────────────────────────────────────────────────────────

def validate(
    rooms: List[Room], walls: List[Wall],
    footprint_envelopes: Dict[int, Polygon], target_sqft: float,
) -> List[BlueprintWarning]:
    warnings: List[BlueprintWarning] = []

    levels = sorted(set(r.level for r in rooms))
    for lvl in levels:
        lvl_rooms = _rooms_on_level(rooms, lvl)
        # "unit" shells intentionally contain/overlap their own sub-rooms
        # (see CONTAINER_ROOM_TYPES) — excluded from overlap/orthogonal/
        # min-size checks below, or every multi-family floor spams false
        # positives against its own children. Still included in the
        # unassigned-space union further down, since that check only cares
        # about total covered area, where a redundant containing polygon is
        # harmless (union of a shape and its own subset is just the shape).
        warnable_rooms = [r for r in lvl_rooms if r.type not in CONTAINER_ROOM_TYPES]
        polys = {r.id: Polygon(r.polygon) for r in warnable_rooms if len(r.polygon) >= 3}
        all_polys = {r.id: Polygon(r.polygon) for r in lvl_rooms if len(r.polygon) >= 3}

        seen_pairs = set()
        for r in warnable_rooms:
            for s in warnable_rooms:
                if r.id >= s.id or r.id not in polys or s.id not in polys:
                    continue
                key = (r.id, s.id)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                try:
                    inter = polys[r.id].intersection(polys[s.id]).area
                except Exception:
                    inter = 0.0
                if inter > 0.2:
                    warnings.append(BlueprintWarning(
                        id=f"overlap_{r.id}_{s.id}", severity="warning", type="overlap",
                        message=f"'{r.type}' and '{s.type}' overlap on level {lvl}",
                        room_ids=[r.id, s.id], level=lvl,
                    ))

        for r in warnable_rooms:
            min_w = min_width_for(r.type)
            width = min(room_extent_along_axis(r.polygon, "x"), room_extent_along_axis(r.polygon, "y"))
            if width < min_w or r.area_sqft < MIN_ROOM_AREA_SQFT:
                warnings.append(BlueprintWarning(
                    id=f"below_min_{r.id}", severity="warning", type="below_min_size",
                    message=f"'{r.type}' ({r.area_sqft:.0f} sqft) is below the recommended minimum size",
                    room_ids=[r.id], level=lvl,
                ))
            for (x0, y0, x1, y1) in _polygon_edges(r.polygon):
                if not _is_drawable_angle(x0, y0, x1, y1):
                    warnings.append(BlueprintWarning(
                        id=f"nonortho_{r.id}", severity="warning", type="non_orthogonal",
                        message=f"'{r.type}' has a non-orthogonal edge",
                        room_ids=[r.id], level=lvl,
                    ))
                    break

        envelope = footprint_envelopes.get(lvl)
        if envelope is not None and all_polys:
            try:
                from shapely.ops import unary_union
                free = envelope.difference(unary_union(list(all_polys.values())))
                free_sqft = free.area * SQM_TO_SQFT
                if free_sqft > 20:
                    warnings.append(BlueprintWarning(
                        id=f"unassigned_{lvl}", severity="info", type="unassigned_area",
                        message=f"{free_sqft:.0f} sqft of unassigned space on level {lvl}",
                        room_ids=[], level=lvl,
                    ))
            except Exception:
                pass

    # "unit" shell area is not summed here — it's a bounding box around
    # sub-rooms that already count their own area, so including both would
    # double-count every multi-family apartment's square footage.
    total_sqft = sum(r.area_sqft for r in rooms if r.type not in CONTAINER_ROOM_TYPES)
    if target_sqft and total_sqft > target_sqft * 1.05:
        warnings.append(BlueprintWarning(
            id="over_sqft", severity="warning", type="over_sqft",
            message=f"Total {total_sqft:.0f} sqft exceeds your {target_sqft:.0f} sqft target",
            room_ids=[],
        ))

    # Mirrors compliance.py's _check_egress presence-only rule exactly, so
    # the warning shown during editing and the eventual compliance result
    # after finalize never disagree.
    if len(levels) > 1 and not any(r.type == "stair" for r in rooms):
        warnings.append(BlueprintWarning(
            id="missing_stair", severity="warning", type="missing_stair",
            message="No 'stair' room connects your levels — add one before finalizing",
            room_ids=[],
        ))

    return warnings


# ── Dispatcher ───────────────────────────────────────────────────────────

_OP_FUNCS = {
    "move_wall": lambda draft, p: move_wall(draft, p["level"], p["wall_id"], p["delta_ft"]),
    "resize_room": lambda draft, p: resize_room(draft, p["level"], p["room_id"], p["edge"], p["delta_ft"]),
    "add_room": lambda draft, p: add_room(draft, p["level"], p["room_type"], p["polygon_m"]),
    "delete_room": lambda draft, p: delete_room(draft, p["level"], p["room_id"]),
    "retype_room": lambda draft, p: retype_room(draft, p["level"], p["room_id"], p["new_type"]),
    # relocate_room lands in a later phase.
}


def apply_op(draft: DraftState, op_type: str, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Single dispatcher used by both the manual /edit endpoint and AI chat
    edits. Returns (ok, error). On success, draft.model.rooms/walls are
    already mutated; caller is responsible for re-running validate()."""
    fn = _OP_FUNCS.get(op_type)
    if fn is None:
        return False, f"Unknown or not-yet-supported op_type '{op_type}'"
    try:
        fn(draft, params)
        return True, None
    except FloorplanEditError as e:
        return False, str(e)
    except KeyError as e:
        return False, f"Missing required param: {e}"
    except Exception as e:
        return False, f"Edit failed: {e}"
