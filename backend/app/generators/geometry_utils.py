"""Geometry utilities: validation and minor fixes for massing/facade/MEP alignment.
These helpers are intentionally conservative and do not mutate original inputs
unless explicitly requested by callers.
"""
from typing import List, Dict, Tuple
from shapely.geometry import Polygon, Point, LineString
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
