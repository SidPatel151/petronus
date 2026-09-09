"""Geometry utilities: validation and minor fixes for massing/facade/MEP alignment.
These helpers are intentionally conservative and do not mutate original inputs
unless explicitly requested by callers.
"""
from typing import List, Dict, Optional, Tuple
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import polygonize, unary_union
import math


def validate_mep_coverage(rooms: List, elements: List, min_rooms_fraction: float = 0.9) -> Dict:
    """Check that most rooms have at least one MEP element inside or nearby.

    Returns a summary with lists of covered and uncovered room ids/indexes.
    """
    room_map = {}
    for i, r in enumerate(rooms):
        try:
            poly = Polygon(r.polygon)
        except Exception:
            poly = None
        room_map[i] = {"room": r, "poly": poly, "covered": False}

    for el in elements:
        # use element start point as representative
        try:
            sx, sy, sz = el.start
        except Exception:
            continue
        p = Point(sx, sz)
        for i, info in room_map.items():
            poly = info["poly"]
            if poly is None:
                # fallback: centroid test
                cx = sum(pt[0] for pt in info["room"].polygon) / max(1, len(info["room"].polygon))
                cz = sum(pt[1] for pt in info["room"].polygon) / max(1, len(info["room"].polygon))
                if math.hypot(sx - cx, sz - cz) < 1.0:
                    info["covered"] = True
            else:
                if poly.buffer(0.05).contains(p) or poly.distance(p) < 0.5:
                    info["covered"] = True

    covered = [i for i, info in room_map.items() if info["covered"]]
    uncovered = [i for i, info in room_map.items() if not info["covered"]]
    fraction = len(covered) / max(1, len(rooms))
    ok = fraction >= min_rooms_fraction
    return {"ok": ok, "fraction": fraction, "covered": covered, "uncovered": uncovered}


def footprint_polygon_from_walls_or_rooms(
    walls: List, rooms: List, level_index: int
) -> Optional[Polygon]:
    """Polygonize this level's exterior walls; fall back to a buffered union
    of this level's room polygons if the walls don't close cleanly.

    Shared by MEPRouter (which needs "the fixed envelope" to bound routing
    and containment checks) and the blueprint editor (which needs "the fixed
    envelope" to bound where rooms/walls may be edited) so the two agree on
    exactly the same footprint for a given level.
    """
    exterior = [
        LineString([w.start, w.end])
        for w in walls
        if getattr(w, "is_exterior", False) and w.level == level_index
        and len(w.start) >= 2 and len(w.end) >= 2
    ]
    try:
        candidates = list(polygonize(unary_union(exterior))) if exterior else []
        if candidates:
            shell = max(candidates, key=lambda p: p.area)
            if shell.is_valid and not shell.is_empty:
                return shell
    except Exception:
        pass

    # Safe fallback for incomplete wall graphs: union this level's room
    # polygons. A tiny closing buffer bridges wall-thickness gaps.
    try:
        room_polys = [
            Polygon(r.polygon)
            for r in rooms if r.level == level_index and len(r.polygon) >= 3
        ]
        merged = unary_union(room_polys).buffer(0.12, join_style=2)
        if not merged.is_empty:
            if merged.geom_type == "MultiPolygon":
                merged = max(merged.geoms, key=lambda p: p.area)
            return merged if merged.is_valid else merged.buffer(0)
    except Exception:
        pass
    return None


def snap_facade_to_massing(massing_footprint: List[Tuple[float, float]], facade_meshes: List[Dict], max_snap: float = 0.12) -> List[Dict]:
    """Return a copy of facade_meshes where vertices that are within `max_snap`
    meters of the massing footprint are snapped to the nearest point on the
    footprint boundary. This reduces z-fighting and small gaps.
    """
    if not massing_footprint:
        return facade_meshes

    fp = Polygon(massing_footprint)
    boundary = fp.boundary

    def snap_vertex(v):
        x, y, z = v
        # project (x,z) onto footprint boundary
        p = Point(x, z)
        nearest = boundary.interpolate(boundary.project(p))
        nx, nz = nearest.x, nearest.y
        d = math.hypot(nx - x, nz - z)
        if d <= max_snap:
            return [nx, y, nz]
        return v

    out = []
    for m in facade_meshes:
        m2 = dict(m)
        verts = m.get("vertices")
        if not verts:
            out.append(m2)
            continue
        new_verts = [snap_vertex(v) for v in verts]
        m2["vertices"] = new_verts
        out.append(m2)
    return out
