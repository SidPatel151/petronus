"""
FacadeGenerator
Windows, balconies, floor bands, roof, parapet, arch-style trim.
All Y coordinates are absolute local meters (lvl * floor_h).

FAKE DATA NOTE:
  - window_style / dominant_arch_style / dominant_roof_shape come from OSM tags
    (building:architecture, roof:shape). These tags exist on <5% of OSM buildings in the US.
    When missing, extract_neighbor_style returns "modern" / "flat" / "standard" defaults.
  - has_balconies likewise almost never exists in OSM — defaults to False.
  - All of this is real when present; fabricated when not.
"""
import math
import uuid
from typing import List, Dict, Any, Optional, Tuple
from app.models.schemas import Wall, Level
from app.constants import FACADE_COLORS as MATERIAL_FACADE_COLORS

WINDOW_COLOR = "#7dd3fc"

# ── Room-to-window specs — what window goes behind each room type ────────────
_ROOM_WIN = {
    "bedroom":     {"w": 1.05, "h": 1.30, "sill_frac": 0.28, "style": "double_hung"},
    "bathroom":    {"w": 0.55, "h": 0.50, "sill_frac": 0.52, "style": "casement"},
    "half_bath":   {"w": 0.45, "h": 0.45, "sill_frac": 0.55, "style": "casement"},
    "kitchen":     {"w": 0.90, "h": 0.75, "sill_frac": 0.40, "style": "casement"},
    "living":      {"w": 1.60, "h": 1.40, "sill_frac": 0.18, "style": "picture"},
    "family_room": {"w": 1.60, "h": 1.40, "sill_frac": 0.18, "style": "picture"},
    "dining":      {"w": 1.00, "h": 1.20, "sill_frac": 0.25, "style": "double_hung"},
    "office":      {"w": 1.00, "h": 1.30, "sill_frac": 0.28, "style": "double_hung"},
    "library":     {"w": 1.10, "h": 1.40, "sill_frac": 0.22, "style": "picture"},
    "bonus_room":  {"w": 1.10, "h": 1.20, "sill_frac": 0.28, "style": "double_hung"},
    "loft":        {"w": 1.10, "h": 1.20, "sill_frac": 0.28, "style": "double_hung"},
    "utility":     {"w": 0.45, "h": 0.40, "sill_frac": 0.55, "style": "casement"},
    "laundry":     {"w": 0.45, "h": 0.40, "sill_frac": 0.55, "style": "casement"},
    "media_room":  {"w": 0.60, "h": 0.60, "sill_frac": 0.38, "style": "casement"},
}
_NO_WIN_TYPES = {"garage", "stair", "mechanical", "corridor", "hallway", "foyer",
                 "entry", "mudroom", "attic", "roof", "walk_in_closet",
                 "porch", "balcony", "deck", "covered_porch"}
_PATIO_TYPES  = {"living", "dining", "family_room"}

# Per-arch-style multipliers for (w_scale, h_scale, sill_frac_offset).
# Keys must match the arch_style values that actually flow through the system
# (from apply_archetype_to_design_brief / AI brief), NOT archetype JSON IDs.
#
# Actual values in use:
#   classic_gabled    → victorian_narrow_lot, production_tract (tall traditional)
#   contemporary_box  → urban_infill_zero_lot, prefab_modern (large glazing)
#   modern_linear     → mid_century_modern, high_density_townhome, high_end_custom (wide horizontal)
#   sculpted_stepped  → hillside_stepped (panoramic view windows)
#
# AI can also produce any of the secondary styles below when there's no archetype override.
# Porch width as a fraction of the entry wall, per style. Module scope so the
# porch footprint can be worked out BEFORE windows are placed.
_PORCH_WIDTH_RANGE: Dict[str, Tuple[float, float]] = {
    "craftsman":        (0.62, 0.82),  # signature wide wraparound porch
    "victorian":        (0.55, 0.72),  # ornate front facade, varies per lot
    "classic_gabled":   (0.50, 0.68),  # production/tract — some wider, some not
    "farmhouse":        (0.60, 0.80),  # full-width barn porch vibe
    "colonial":         (0.42, 0.58),  # centered portico, symmetrical
    "tudor":            (0.30, 0.45),  # modest covered entry arch
    "suburban":         (0.22, 0.35),  # small stoop
    "contemporary_box": (0.20, 0.30),  # minimal covered entry
    "ranch":            (0.22, 0.32),  # low spread-out stoop
}


def _porch_width_frac(arch_style: str, flen: float, porch_depth: float) -> float:
    """Deterministic porch width fraction — same building, same porch."""
    lo, hi = _PORCH_WIDTH_RANGE.get(arch_style, (0.28, 0.42))
    seed = abs(hash((round(flen, 1), round(porch_depth, 1)))) % 1000 / 1000.0
    return lo + seed * (hi - lo)


_ARCH_WIN_SCALE: Dict[str, Tuple[float, float, float]] = {
    # ── Primary styles set by archetype system ──────────────────────────────
    "classic_gabled":       (0.78, 1.22, -0.02),  # Victorian/tract: taller than wide
    "contemporary_box":     (1.40, 1.45, -0.06),  # urban infill: near floor-to-ceiling
    "modern_linear":        (1.25, 1.05,  0.00),  # MCM/townhome: wide, generous height
    "sculpted_stepped":     (1.35, 1.38, -0.05),  # Hillside: panoramic picture windows for views
    # ── Secondary styles (AI-generated when no archetype override) ──────────
    "victorian":            (0.68, 1.40, -0.04),  # Narrow double-hung
    "victorian_edwardian_narrow": (0.65, 1.42, -0.04),
    "tudor":                (0.72, 1.28, -0.03),
    "craftsman":            (0.85, 1.12, -0.01),
    "colonial":             (0.80, 1.15, -0.02),
    "farmhouse":            (0.92, 1.02,  0.00),
    "ranch":                (1.28, 0.68,  0.09),  # Wide & low banded windows
    "minimalist":           (1.38, 1.42, -0.07),  # Floor-to-ceiling
    "contemporary_luxury":  (1.50, 1.50, -0.08),  # High-end custom: floor-to-ceiling glass walls
    "suburban_traditional": (0.85, 1.10,  0.00),  # Tract builder standard
    "contemporary_stepped": (1.30, 1.35, -0.05),  # Same as sculpted_stepped
}


def _pip(px: float, pz: float, poly: list) -> bool:
    """Ray-cast point-in-polygon test (2D in XZ plane)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, zi = poly[i][0], poly[i][1]
        xj, zj = poly[j][0], poly[j][1]
        if (zi > pz) != (zj > pz):
            denom = zj - zi
            if abs(denom) > 1e-12 and px < (xj - xi) * (pz - zi) / denom + xi:
                inside = not inside
        j = i
    return inside


def extract_neighbor_style(buildings: List[Dict]) -> Dict[str, Any]:
    heights, materials, colors, roof_shapes, arch_styles = [], [], [], [], []
    widths, depths = [], []
    balcony_count, total = 0, 0

    for b in buildings:
        props = b.get("properties", {})
        total += 1

        h = props.get("height_m")
        if h:
            try: heights.append(float(h))
            except: pass

        try:
            coords = b.get("geometry", {}).get("coordinates", [[]])[0]
            if len(coords) >= 3:
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                w = (max(xs) - min(xs)) * 111320 * math.cos(math.radians(ys[0]))
                d = (max(ys) - min(ys)) * 111320
                if 2 < w < 200: widths.append(w)
                if 2 < d < 200: depths.append(d)
        except Exception:
            pass

        mat = (props.get("facade_mat") or props.get("building:material") or props.get("material", "")).lower()
        if mat: materials.append(mat)

        col = props.get("facade_color") or props.get("building:colour") or props.get("building:color")
        if col: colors.append(col)

        roof = props.get("roof_shape", "").lower()
        if roof and roof != "flat": roof_shapes.append(roof)

        arch = props.get("arch_style", "").lower()
        if arch: arch_styles.append(arch)

        if props.get("has_balconies"): balcony_count += 1

    dominant_mat  = max(set(materials),   key=materials.count)   if materials   else "stucco"
    dominant_roof = max(set(roof_shapes), key=roof_shapes.count) if roof_shapes else "flat"
    dominant_arch = max(set(arch_styles), key=arch_styles.count) if arch_styles else "modern"

    facade_color = (
        max(set(colors), key=colors.count) if colors
        else MATERIAL_FACADE_COLORS.get(dominant_mat, "#d6cbb8")
    )

    window_style = "standard"
    if dominant_arch in ("craftsman", "victorian", "tudor", "colonial"):
        window_style = "tall_narrow"
    elif dominant_arch in ("modern", "contemporary", "minimalist"):
        window_style = "wide"

    balcony_prevalence = balcony_count / max(total, 1)

    return {
        "avg_neighbor_height_m": sum(heights) / len(heights) if heights else 9.0,
        "avg_width_m":           sum(widths)  / len(widths)  if widths  else 12.0,
        "avg_depth_m":           sum(depths)  / len(depths)  if depths  else 14.0,
        "avg_stories":           round((sum(heights) / len(heights)) / 3.0) if heights else 2,
        "dominant_material":     dominant_mat,
        "dominant_roof_shape":   dominant_roof,
        "dominant_arch_style":   dominant_arch,
        "dominant_shape":        "rectangle",
        "has_balconies":         balcony_prevalence > 0.2,
        "facade_color":          facade_color,
        "window_color":          WINDOW_COLOR,
        "window_style":          window_style,
        "add_pitched_roof":      dominant_roof in ("gabled", "hipped", "gambrel", "mansard"),
        "balcony_prevalence":    balcony_prevalence,
    }


class FacadeGenerator:

    def generate(
        self,
        massing_option: Dict,
        walls: List[Wall],
        levels: List[Level],
        neighbor_style: Optional[Dict] = None,
        design_brief: Optional[Dict] = None,
        rooms: Optional[List] = None,
        semantic_model: Optional[Dict] = None,
    ) -> List[Dict]:
        style = neighbor_style or {}
        brief = design_brief or {}
        # Use actual floor height from levels so roof_y matches wall tops exactly.
        floor_h = (levels[0].height_ft * 0.3048) if levels and getattr(levels[0], 'height_ft', None) else 3.0
        stories = len(levels)

        # ── Material → color: brief drives the building, neighbors are context ──
        _MAT_COLORS = {
            "stucco":        "#d4c5a9",
            "wood":          "#8b6914",
            "cedar":         "#9b6a2f",
            "redwood":       "#8b4513",
            "brick":         "#a0522d",
            "concrete":      "#9a9a9a",
            "metal":         "#708090",
            "steel":         "#607080",
            "fiber_cement":  "#c0b8aa",
            "stone":         "#7a6a5a",
            "glass":         "#aec8d8",
            "vinyl":         "#cfc9be",
        }
        brief_mat = (brief.get("facade_material") or "").lower()
        neighbor_color = style.get("facade_color", "#d6cbb8")
        facade_color = _MAT_COLORS.get(brief_mat, neighbor_color)

        win_color = style.get("window_color", WINDOW_COLOR)
        band_color = self._darken(facade_color, 0.75)
        balcony_color = self._darken(facade_color, 0.65)

        # ── Arch style: brief takes priority over neighbor context ──────────
        arch_style = brief.get("arch_style") or style.get("dominant_arch_style", "modern")

        # ── All render parameters from Claude's brief — no lookup tables ───────
        window_ratio  = min(float(brief.get("window_ratio") or style.get("window_ratio", 0.35)), 0.55)
        bal_every_n   = int(brief.get("balcony_every_n_floors") or 1)
        bal_every_n   = max(1, min(bal_every_n, max(1, stories - 1)))
        add_bands     = bool(brief.get("horizontal_bands", style.get("horizontal_bands", True)))
        has_balconies = bool(style.get("has_balconies", False))

        band_h_frac   = float(brief.get("band_h_frac", 0.15))
        face_offset   = float(brief.get("face_offset", 0.09))
        win_h_frac    = float(brief.get("win_h_frac", 0.50))
        win_w_cap     = float(brief.get("win_w_cap_m", 1.8))
        balcony_depth = float(brief.get("balcony_depth_m") or 0.0)
        trim_color    = brief.get("trim_color") or "#4a4a4a"
        if balcony_depth == 0.0 and has_balconies:
            balcony_depth = 0.65  # neighbour fallback only if Claude left it at 0

        meshes: List[Dict] = []
        ext_walls = [w for w in walls if w.is_exterior and w.level == 0]

        # Prefer using massing footprint if provided to ensure roofs/parapets align.
        footprint = massing_option.get("footprint") if massing_option else None
        if footprint:
            poly_pts = [(round(p[0], 6), round(p[1], 6)) for p in footprint]
            poly_cx = sum(p[0] for p in poly_pts) / len(poly_pts) if poly_pts else 0.0
            poly_cz = sum(p[1] for p in poly_pts) / len(poly_pts) if poly_pts else 0.0
            from types import SimpleNamespace
            ext_walls = []
            nfp = len(poly_pts)
            for i in range(nfp):
                s = poly_pts[i]
                e = poly_pts[(i + 1) % nfp]
                ext_walls.append(SimpleNamespace(
                    id=f"footprint_wall_{i}",
                    start=(s[0], s[1]), end=(e[0], e[1]),
                    is_exterior=True, level=0,
                ))
        else:
            # Build an ordered, deduplicated polygon of exterior wall endpoints.
            # Walls may be unordered or contain near-duplicate vertices; compute a
            # centroid and sort vertices by angle to produce a stable CCW ordering.
            poly_pts_raw = []
            for w in ext_walls:
                poly_pts_raw.append((round(w.start[0], 6), round(w.start[1], 6)))
                poly_pts_raw.append((round(w.end[0], 6), round(w.end[1], 6)))
            poly_pts_uniq = []
            for p in poly_pts_raw:
                if p not in poly_pts_uniq:
                    poly_pts_uniq.append(p)

            if poly_pts_uniq:
                poly_cx = sum(p[0] for p in poly_pts_uniq) / len(poly_pts_uniq)
                poly_cz = sum(p[1] for p in poly_pts_uniq) / len(poly_pts_uniq)
                poly_pts = sorted(poly_pts_uniq, key=lambda q: math.atan2(q[1] - poly_cz, q[0] - poly_cx))
            else:
                poly_pts = []
                poly_cx = poly_cz = 0.0

        # ── Semantic model openings — Claude's exact window positions ────────
        # Keys: "f{level}_front" → list of opening dicts
        _sem_opens: Dict[str, List] = {}
        _sem_w = 0.0
        if semantic_model:
            _sem_w = float((semantic_model.get("footprint") or {}).get("width_m", 0))
            for op in (semantic_model.get("openings") or []):
                wid = op.get("wall_id", "")
                if wid:
                    _sem_opens.setdefault(wid, []).append(op)

        # Back-face Z for patio door detection
        _back_face_z = (max((w.start[1] + w.end[1]) / 2 for w in ext_walls)
                        if ext_walls else 0.0)

        # Pre-compute each front wall segment's cumulative start offset so
        # semantic window positions (offset_m along full facade) are mapped
        # correctly even when the front face has multiple segments.
        _front_face_z_tmp = min((w.start[1] + w.end[1]) / 2 for w in ext_walls) if ext_walls else 0.0
        _front_segs = sorted(
            [w for w in ext_walls if (w.start[1] + w.end[1]) / 2 <= _front_face_z_tmp + 0.5],
            key=lambda w: min(w.start[0], w.end[0]),
        )
        _front_seg_offset: Dict[int, float] = {}
        _cum = 0.0
        for _fw in _front_segs:
            _front_seg_offset[id(_fw)] = _cum
            _fdx, _fdz = _fw.end[0] - _fw.start[0], _fw.end[1] - _fw.start[1]
            _cum += math.sqrt(_fdx * _fdx + _fdz * _fdz)
        _front_total_w = _cum

        # Claude measures every opening's offset_m along ITS OWN invented
        # footprint.width_m, but the wall those offsets are painted onto is the
        # chosen massing footprint, whose width is generally different (the
        # archetype rules overwrite the AI's dimensions right after it runs).
        # Applying raw offsets therefore slid and bunched the whole front
        # elevation — windows drifting off one end of the facade, which is a
        # large part of "the 3D doesn't follow the plan". Rescale the openings
        # onto the front face that actually exists.
        if _sem_w > 0.01 and _front_total_w > 0.01 and abs(_front_total_w - _sem_w) > 0.05:
            _sem_scale = _front_total_w / _sem_w
            _sem_opens = {
                wid: [
                    {
                        **op,
                        "offset_m": float(op.get("offset_m", 0.0)) * _sem_scale,
                        "width_m": float(op.get("width_m", 1.0)) * _sem_scale,
                    }
                    for op in ops
                ]
                for wid, ops in _sem_opens.items()
            }
            _sem_w = _front_total_w

        # ── Entry door rules ─────────────────────────────────────────────────
        # Front face = wall(s) with minimum average Z (street-facing in local coords).
        is_gabled_style = ('classic' in arch_style or 'gabled' in arch_style
                           or 'victorian' in arch_style or 'suburban' in arch_style
                           or arch_style in ('craftsman', 'tudor', 'farmhouse', 'colonial'))
        is_victorian = ('victorian' in arch_style
                        or arch_style in ('classic_gabled', 'craftsman', 'tudor'))
        is_modern    = arch_style in ('modern_linear', 'contemporary_box', 'minimalist')
        _is_vic_narrow = 'victorian_edwardian' in arch_style
        front_face_z = (min((w.start[1] + w.end[1]) / 2 for w in ext_walls)
                        if ext_walls else 0.0)
        # Victorian narrow-lot: garage at grade, main entry elevated ~1.2m (≈4ft) above grade.
        # Other gabled styles: 2 steps (0.36m). Modern: flush.
        if _is_vic_narrow:
            entry_sill_y = 1.22
        elif is_gabled_style:
            entry_sill_y = 0.36
        else:
            entry_sill_y = 0.0
        door_placed = False
        # Door world position + wall vectors — captured when door is placed so the
        # porch code can center on the door rather than the wall midpoint.
        _door_cx: float | None = None
        _door_cz: float | None = None
        _door_ux: float = 1.0
        _door_uz: float = 0.0
        _door_nx: float = 0.0
        _door_nz: float = -1.0
        _door_flen: float = 0.0

        # Track which front walls get bay windows so we don't double-window them
        bay_wall_ids: set = set()

        # ── Where the front door goes ────────────────────────────────────────
        # It used to be hardcoded to the midpoint of whichever front segment
        # came first, so it bore no relation to the plan: you could enter
        # straight into a bedroom while the foyer sat at the other end of the
        # house. Anchor it on the ground-floor entry room instead, and fall
        # back to the midpoint only when the plan has no entry-ish room.
        _door_seg_id = id(_front_segs[0]) if _front_segs else None
        _door_t = 0.5
        _entry_cands = [
            r for r in (rooms or [])
            if r.level == 0 and r.type in ("foyer", "entry", "mudroom")
        ] or [r for r in (rooms or []) if r.level == 0 and r.type == "living"]
        if _entry_cands and _front_segs:
            # Front-most candidate, then its centre along X.
            _entry = min(
                _entry_cands,
                key=lambda r: sum(p[1] for p in r.polygon) / max(len(r.polygon), 1),
            )
            _exs = [p[0] for p in _entry.polygon]
            _entry_cx = (min(_exs) + max(_exs)) / 2
            for _fw in _front_segs:
                _lo, _hi = min(_fw.start[0], _fw.end[0]), max(_fw.start[0], _fw.end[0])
                if _lo - 0.3 <= _entry_cx <= _hi + 0.3:
                    _door_seg_id = id(_fw)
                    _span_x = _fw.end[0] - _fw.start[0]
                    if abs(_span_x) > 1e-6:
                        # Keep the leaf clear of the corners.
                        _door_t = min(max((_entry_cx - _fw.start[0]) / _span_x, 0.12), 0.88)
                    break

        # Ground-floor extent the porch will cover, as a fraction along the
        # entry wall. The porch is built after the wall loop, so the window
        # pass had no idea it existed and happily placed openings across the
        # deck, columns and porch roof.
        _porch_lo = _porch_hi = None
        _porch_depth = float(brief.get("porch_depth_m") or 0.0)
        if _porch_depth > 0.1 and _door_seg_id is not None:
            _pseg = next((f for f in _front_segs if id(f) == _door_seg_id), None)
            if _pseg is not None:
                _plen = math.hypot(
                    _pseg.end[0] - _pseg.start[0], _pseg.end[1] - _pseg.start[1]
                )
                if _plen > 0.5:
                    _pf = _porch_width_frac(arch_style, _plen, _porch_depth)
                    _pw = min(_plen * _pf, _plen - 0.5)
                    _pw = max(_pw, min(2.2, _plen * 0.25))
                    _half = (_pw / 2) / _plen
                    _porch_lo, _porch_hi = _door_t - _half, _door_t + _half

        for wall in ext_walls:
            s, e = wall.start, wall.end
            dx, dz = e[0] - s[0], e[1] - s[1]
            wall_len = math.sqrt(dx * dx + dz * dz)
            if wall_len < 1.5:
                continue

            ux, uz = dx / wall_len, dz / wall_len
            nx, nz = uz, -ux  # outward normal (assumes CCW polygon)
            mid_x = (s[0] + e[0]) / 2
            mid_z = (s[1] + e[1]) / 2
            if nx * (mid_x - poly_cx) + nz * (mid_z - poly_cz) < 0:
                nx, nz = -nx, -nz

            _wall_mid_z = (s[1] + e[1]) / 2
            _is_front   = _wall_mid_z <= front_face_z + 0.5
            _is_back    = not _is_front and _wall_mid_z >= _back_face_z - 0.5
            _is_side    = not _is_front and not _is_back

            for lvl in range(stories):
                base_y = lvl * floor_h
                entry_on_this_wall = (
                    lvl == 0 and wall_len >= 2.0 and _is_front and not door_placed
                    and (_door_seg_id is None or id(wall) == _door_seg_id)
                )
                if entry_on_this_wall:
                    # Record where the door actually landed. The entry stairs
                    # (_is_vic_narrow branch) and the whole porch assembly are
                    # gated on `_door_cx is not None`, but it was only ever
                    # assigned inside a second, duplicated door block further
                    # down that `door_placed = True` already made unreachable.
                    # So no plan ever got a porch, and the door hung 0.36-1.22 m
                    # off the ground with no steps under it.
                    _door_cx, _door_cz = self._add_entry_door(
                        meshes, s, e, dx, dz, ux, uz, nx, nz,
                        face_offset, entry_sill_y, arch_style, facade_color,
                        t_door=_door_t,
                    )
                    _door_ux, _door_uz = ux, uz
                    _door_nx, _door_nz = nx, nz
                    _door_flen = wall_len
                    door_placed = True

                # ── Horizontal floor band (spandrel) ──────────────────────
                if add_bands and band_h_frac > 0:
                    bh = floor_h * band_h_frac
                    fo = face_offset + (0.04 if arch_style in ("craftsman", "victorian", "tudor") else 0)
                    band_verts = [
                        [s[0] + nx * fo, base_y,      s[1] + nz * fo],
                        [e[0] + nx * fo, base_y,      e[1] + nz * fo],
                        [e[0] + nx * fo, base_y + bh, e[1] + nz * fo],
                        [s[0] + nx * fo, base_y + bh, s[1] + nz * fo],
                    ]
                    meshes.append({
                        "element_id": f"band_{lvl}_{uuid.uuid4().hex[:4]}",
                        "element_type": "floor_band",
                        "vertices": band_verts,
                        "faces": [[0, 1, 2], [0, 2, 3]],
                        "level": 0,
                        "color": band_color,
                    })

                    if arch_style in ("craftsman", "victorian"):
                        accent_y = base_y + bh + 0.05
                        accent_h = 0.06
                        acc_verts = [
                            [s[0] + nx * fo, accent_y,            s[1] + nz * fo],
                            [e[0] + nx * fo, accent_y,            e[1] + nz * fo],
                            [e[0] + nx * fo, accent_y + accent_h, e[1] + nz * fo],
                            [s[0] + nx * fo, accent_y + accent_h, s[1] + nz * fo],
                        ]
                        meshes.append({
                            "element_id": f"accent_{lvl}_{uuid.uuid4().hex[:4]}",
                            "element_type": "floor_band",
                            "vertices": acc_verts,
                            "faces": [[0, 1, 2], [0, 2, 3]],
                            "level": 0,
                            "color": self._darken(facade_color, 0.55),
                        })

                # ── Victorian bay window: 3-sided projection on front face ──
                if (
                    is_victorian and _is_front and wall_len >= 3.0
                    and not entry_on_this_wall
                ):
                    bay_already = wall.id in bay_wall_ids
                    if not bay_already:
                        bay_wall_ids.add(wall.id)
                        self._add_bay_window(
                            meshes, s, e, dx, dz, ux, uz, nx, nz,
                            wall_len, base_y, floor_h, face_offset,
                            win_color, facade_color, lvl,
                        )
                        # Skip regular windows on this wall+level for bay-windowed floors
                        continue

                # ── Mid-century / modern: horizontal strip windows on front ──
                if is_modern and _is_front and wall_len >= 4.0:
                    door_gap = None
                    if entry_on_this_wall:
                        # Include the frame and a small installation tolerance,
                        # expressed as distance along the wall from ``s``.
                        door_half_clear = 1.05 / 2.0 + 0.06 + 0.05
                        door_gap = (
                            wall_len * 0.5 - door_half_clear,
                            wall_len * 0.5 + door_half_clear,
                        )
                    self._add_strip_window(
                        meshes, s, e, dx, dz, ux, uz, nx, nz,
                        wall_len, base_y, floor_h, face_offset, win_color, lvl,
                        door_gap=door_gap,
                    )
                    continue

                # ── Window placement: semantic → room-aware → math fallback ──
                _sem_key = f"f{lvl}_front"
                _use_sem = _is_front and bool(_sem_opens.get(_sem_key)) and _sem_w > 0

                if _use_sem:
                    _seg_start = _front_seg_offset.get(id(wall), 0.0)
                    self._place_semantic_windows(
                        meshes, s, e, dx, dz, ux, uz, nx, nz,
                        wall_len, base_y, floor_h, face_offset,
                        win_color, trim_color, arch_style, lvl,
                        _sem_opens[_sem_key], _sem_w, _seg_start,
                    )
                elif not _is_front:
                    # Room-aware for side and back walls
                    adj = self._find_adj_room(wall, rooms or [], lvl, -nx, -nz)
                    self._place_side_windows(
                        meshes, s, e, dx, dz, ux, uz, nx, nz,
                        wall_len, base_y, floor_h, face_offset,
                        win_color, trim_color, arch_style, lvl, adj,
                        is_back=_is_back, wall=wall, rooms=rooms or [],
                    )
                else:
                    # ── Front windows, driven by the room behind each bay ────
                    # This used to be one width/height/sill for the whole wall,
                    # repeated at even fractions — every opening on the facade
                    # identical, which is what read as "patternized". Now each
                    # bay probes the room behind it and takes that room's own
                    # window spec, scaled by the architectural style. A bedroom,
                    # a bathroom and a living room on the same elevation now get
                    # visibly different openings.
                    win_spacing = max(1.4, 2.8 * (1.0 - window_ratio))
                    num_windows = max(1, int(wall_len / win_spacing))
                    is_sfr_style = 'classic' in arch_style or 'gabled' in arch_style
                    num_windows = min(num_windows, 4 if is_sfr_style else 5)
                    _win_top_max = base_y + floor_h - 0.25

                    for i in range(num_windows):
                        t = (i + 0.5) / num_windows

                        # No opening where the porch will be built.
                        if (
                            lvl == 0 and _porch_lo is not None
                            and id(wall) == _door_seg_id
                            and _porch_lo - 0.02 <= t <= _porch_hi + 0.02
                        ):
                            continue

                        bay_room = self._room_at_wall_frac(
                            wall, rooms or [], lvl, -nx, -nz, t
                        )
                        if bay_room is not None and bay_room.type in _NO_WIN_TYPES:
                            continue
                        win_w, win_h, win_sill_frac, _bay_style = self._room_window_spec(
                            bay_room.type if bay_room else None,
                            arch_style, window_ratio, win_h_frac, floor_h,
                        )
                        win_w = max(0.55, min(win_w, win_w_cap, wall_len / num_windows * 0.85))
                        win_sill = base_y + floor_h * win_sill_frac
                        if win_sill + win_h > _win_top_max:
                            win_h = max(0.3, _win_top_max - win_sill)

                        if entry_on_this_wall:
                            _door_w = 1.05
                            _clearance = (_door_w / 2 + win_w / 2 + 0.10) / wall_len
                            if abs(t - _door_t) < _clearance:
                                continue

                        wcx = s[0] + t * dx
                        wcz = s[1] + t * dz
                        hw = win_w / 2

                        verts = [
                            [wcx - ux*hw + nx*face_offset, win_sill,         wcz - uz*hw + nz*face_offset],
                            [wcx + ux*hw + nx*face_offset, win_sill,         wcz + uz*hw + nz*face_offset],
                            [wcx + ux*hw + nx*face_offset, win_sill + win_h, wcz + uz*hw + nz*face_offset],
                            [wcx - ux*hw + nx*face_offset, win_sill + win_h, wcz - uz*hw + nz*face_offset],
                        ]
                        meshes.append({
                            "element_id": f"win_{uuid.uuid4().hex[:6]}",
                            "element_type": "window",
                            "vertices": verts,
                            "faces": [[0, 1, 2], [0, 2, 3], [2, 1, 0], [3, 2, 0]],
                            "level": 0,
                            "color": win_color,
                        })

                        ft = 0.07 if arch_style in ("craftsman", "victorian", "colonial") else 0.04
                        for fv, ff in self._frame_quads(wcx, wcz, win_sill, win_h, win_w, ux, uz, nx, nz, face_offset, ft):
                            meshes.append({
                                "element_id": f"frm_{uuid.uuid4().hex[:6]}",
                                "element_type": "window_frame",
                                "vertices": fv, "faces": ff,
                                "level": 0,
                                "color": "#1e293b" if arch_style in ("modern", "minimalist") else "#f5f0e8",
                            })

                # ── Entry door: ONE door, front face only ─────────────────
                wall_mid_z = (s[1] + e[1]) / 2
                is_front = wall_mid_z <= front_face_z + 0.5
                if lvl == 0 and wall_len >= 2.0 and is_front and not door_placed:
                    door_placed = True
                    door_w = 1.05
                    door_h = 2.15
                    t_door = 0.5
                    dcx = s[0] + t_door * dx
                    dcz = s[1] + t_door * dz
                    _door_cx, _door_cz = dcx, dcz
                    _door_ux, _door_uz = ux, uz
                    _door_nx, _door_nz = nx, nz
                    _door_flen = wall_len
                    hdw = door_w / 2
                    door_sill = entry_sill_y
                    door_fo = face_offset + 0.01
                    meshes.append({
                        "element_id": f"door_{uuid.uuid4().hex[:6]}",
                        "element_type": "door",
                        "vertices": [
                            [dcx - ux*hdw + nx*door_fo, door_sill,          dcz - uz*hdw + nz*door_fo],
                            [dcx + ux*hdw + nx*door_fo, door_sill,          dcz + uz*hdw + nz*door_fo],
                            [dcx + ux*hdw + nx*door_fo, door_sill + door_h, dcz + uz*hdw + nz*door_fo],
                            [dcx - ux*hdw + nx*door_fo, door_sill + door_h, dcz - uz*hdw + nz*door_fo],
                        ],
                        "faces": [[0, 1, 2], [0, 2, 3], [2, 1, 0], [3, 2, 0]],
                        "level": 0,
                        "color": "#7c5c3a",
                    })
                    ft = 0.06
                    meshes.append({
                        "element_id": f"door_frame_{uuid.uuid4().hex[:5]}",
                        "element_type": "door_frame",
                        "vertices": [
                            [dcx - ux*(hdw+ft) + nx*door_fo, door_sill,              dcz - uz*(hdw+ft) + nz*door_fo],
                            [dcx + ux*(hdw+ft) + nx*door_fo, door_sill,              dcz + uz*(hdw+ft) + nz*door_fo],
                            [dcx + ux*(hdw+ft) + nx*door_fo, door_sill + door_h+ft,  dcz + uz*(hdw+ft) + nz*door_fo],
                            [dcx - ux*(hdw+ft) + nx*door_fo, door_sill + door_h+ft,  dcz - uz*(hdw+ft) + nz*door_fo],
                        ],
                        "faces": [[0, 1, 2], [0, 2, 3]],
                        "level": 0,
                        "color": "#334155",
                    })

                    # ── Entry canopy for modern / contemporary styles ──
                    if arch_style in ('contemporary_box', 'modern_linear', 'minimalist',
                                      'contemporary', 'urban_infill'):
                        can_y    = door_sill + door_h + 0.12   # just above door head
                        can_proj = face_offset + 0.85           # 85 cm projection
                        can_t    = 0.09                         # slab thickness
                        can_hw   = door_w * 1.60                # wider than door
                        can_c    = self._darken(facade_color, 0.60)
                        can_v = [
                            [dcx - ux*can_hw + nx*face_offset, can_y,       dcz - uz*can_hw + nz*face_offset],
                            [dcx + ux*can_hw + nx*face_offset, can_y,       dcz + uz*can_hw + nz*face_offset],
                            [dcx + ux*can_hw + nx*can_proj,    can_y,       dcz + uz*can_hw + nz*can_proj],
                            [dcx - ux*can_hw + nx*can_proj,    can_y,       dcz - uz*can_hw + nz*can_proj],
                            [dcx - ux*can_hw + nx*face_offset, can_y+can_t, dcz - uz*can_hw + nz*face_offset],
                            [dcx + ux*can_hw + nx*face_offset, can_y+can_t, dcz + uz*can_hw + nz*face_offset],
                            [dcx + ux*can_hw + nx*can_proj,    can_y+can_t, dcz + uz*can_hw + nz*can_proj],
                            [dcx - ux*can_hw + nx*can_proj,    can_y+can_t, dcz - uz*can_hw + nz*can_proj],
                        ]
                        can_f = [
                            [4,5,6],[4,6,7],   # top face
                            [0,4,7],[0,7,3],   # left side
                            [1,5,6],[1,6,2],   # right side
                            [3,7,6],[3,6,2],   # front edge
                            [0,3,2],[0,2,1],   # bottom face
                        ]
                        meshes.append({
                            "element_id": f"canopy_{uuid.uuid4().hex[:5]}",
                            "element_type": "porch",
                            "vertices": can_v, "faces": can_f,
                            "level": 0, "color": can_c,
                        })
                        # Two slim steel support legs under the canopy
                        for leg_sign in (-1, 1):
                            leg_x = dcx + ux * can_hw * 0.75 * leg_sign
                            leg_z = dcz + uz * can_hw * 0.75 * leg_sign
                            leg_proj = face_offset + can_proj * 0.55
                            lhw = 0.04
                            leg_v = [
                                [leg_x - ux*lhw + nx*leg_proj, door_sill,       leg_z - uz*lhw + nz*leg_proj],
                                [leg_x + ux*lhw + nx*leg_proj, door_sill,       leg_z + uz*lhw + nz*leg_proj],
                                [leg_x + ux*lhw + nx*leg_proj, can_y,           leg_z + uz*lhw + nz*leg_proj],
                                [leg_x - ux*lhw + nx*leg_proj, can_y,           leg_z - uz*lhw + nz*leg_proj],
                            ]
                            meshes.append({
                                "element_id": f"canopy_leg_{uuid.uuid4().hex[:4]}",
                                "element_type": "porch",
                                "vertices": leg_v,
                                "faces": [[0,1,2],[0,2,3],[2,1,0],[3,2,0]],
                                "level": 0, "color": "#334155",
                            })

                # ── Balconies ─────────────────────────────────────────────
                if lvl > 0 and balcony_depth > 0 and (lvl % bal_every_n == 0):
                    bal_depth = balcony_depth
                    bal_h  = 0.12
                    rail_h = 0.9
                    rail_t = 0.04
                    bal_y  = base_y + floor_h * 0.05
                    proj   = face_offset + bal_depth

                    bay_w  = min(3.2, wall_len)
                    n_bays = max(1, int(wall_len / bay_w))
                    for b in range(n_bays):
                        t0 = b / n_bays
                        t1 = (b + 1) / n_bays
                        margin = 0.25
                        bx0 = s[0] + (t0 * wall_len + margin) * ux
                        bz0 = s[1] + (t0 * wall_len + margin) * uz
                        bx1 = s[0] + (t1 * wall_len - margin) * ux
                        bz1 = s[1] + (t1 * wall_len - margin) * uz

                        meshes.append({
                            "element_id": f"bal_slab_{uuid.uuid4().hex[:5]}",
                            "element_type": "balcony",
                            "level": 0,
                            "color": balcony_color,
                            "vertices": [
                                [bx0 + nx*face_offset, bal_y,       bz0 + nz*face_offset],
                                [bx1 + nx*face_offset, bal_y,       bz1 + nz*face_offset],
                                [bx1 + nx*proj,        bal_y,       bz1 + nz*proj],
                                [bx0 + nx*proj,        bal_y,       bz0 + nz*proj],
                                [bx0 + nx*face_offset, bal_y+bal_h, bz0 + nz*face_offset],
                                [bx1 + nx*face_offset, bal_y+bal_h, bz1 + nz*face_offset],
                                [bx1 + nx*proj,        bal_y+bal_h, bz1 + nz*proj],
                                [bx0 + nx*proj,        bal_y+bal_h, bz0 + nz*proj],
                            ],
                            "faces": [
                                [0,1,2],[0,2,3],
                                [4,6,5],[4,7,6],
                                [0,4,5],[0,5,1],
                                [2,6,7],[2,7,3],
                                [0,3,7],[0,7,4],
                                [1,5,6],[1,6,2],
                            ],
                        })

                        rx  = (bx0 + bx1) / 2
                        rz  = (bz0 + bz1) / 2
                        rlen = math.sqrt((bx1-bx0)**2 + (bz1-bz0)**2)
                        rhw = rlen / 2
                        meshes.append({
                            "element_id": f"bal_rail_{uuid.uuid4().hex[:5]}",
                            "element_type": "balcony_rail",
                            "level": 0,
                            "color": "#334155",
                            "vertices": [
                                [rx - ux*rhw + nx*proj,          bal_y+bal_h,          rz - uz*rhw + nz*proj],
                                [rx + ux*rhw + nx*proj,          bal_y+bal_h,          rz + uz*rhw + nz*proj],
                                [rx + ux*rhw + nx*proj,          bal_y+bal_h+rail_h,   rz + uz*rhw + nz*proj],
                                [rx - ux*rhw + nx*proj,          bal_y+bal_h+rail_h,   rz - uz*rhw + nz*proj],
                                [rx - ux*rhw + nx*(proj-rail_t), bal_y+bal_h,          rz - uz*rhw + nz*(proj-rail_t)],
                                [rx + ux*rhw + nx*(proj-rail_t), bal_y+bal_h,          rz + uz*rhw + nz*(proj-rail_t)],
                                [rx + ux*rhw + nx*(proj-rail_t), bal_y+bal_h+rail_h,   rz + uz*rhw + nz*(proj-rail_t)],
                                [rx - ux*rhw + nx*(proj-rail_t), bal_y+bal_h+rail_h,   rz - uz*rhw + nz*(proj-rail_t)],
                            ],
                            "faces": [[0,1,2],[0,2,3],[5,4,7],[5,7,6],[3,2,6],[3,6,7],[0,3,7],[0,7,4],[1,5,6],[1,6,2]],
                        })

        # ── Pitched roof — facade is the single source of truth for all roof shapes.
        # Massing._extrude_footprint skips gabled geometry (wrong normals); facade owns it.
        roof_type = (brief.get("roof_type") or "").lower()
        if roof_type in ("gabled", "hipped", "hip", "shed"):
            self._add_pitched_roof(
                meshes, massing_option, stories, floor_h, facade_color, roof_type
            )

        # ── Victorian raised-entry exterior stairs ────────────────────────────
        if _is_vic_narrow and _door_cx is not None and entry_sill_y > 0.5:
            _stair_w  = min(1.6, _door_flen * 0.45)
            _n_steps  = max(4, round(entry_sill_y / 0.18))
            _step_h   = entry_sill_y / _n_steps
            _step_d   = 0.28                             # tread depth
            _stair_col = self._darken(facade_color, 0.78)
            _snx, _snz = _door_nx, _door_nz
            _sux, _suz = _door_ux, _door_uz
            _shw = _stair_w / 2
            for _si in range(_n_steps):
                _bot_y = _si * _step_h
                _top_y = (_si + 1) * _step_h
                _proj_near = face_offset + (_n_steps - _si) * _step_d
                _proj_far  = face_offset + (_n_steps - _si - 1) * _step_d
                meshes.append({
                    "element_id": f"vstair_{uuid.uuid4().hex[:5]}",
                    "element_type": "porch",
                    "level": 0, "color": _stair_col,
                    "vertices": [
                        [_door_cx - _sux*_shw + _snx*_proj_near, _bot_y, _door_cz - _suz*_shw + _snz*_proj_near],
                        [_door_cx + _sux*_shw + _snx*_proj_near, _bot_y, _door_cz + _suz*_shw + _snz*_proj_near],
                        [_door_cx + _sux*_shw + _snx*_proj_far,  _top_y, _door_cz + _suz*_shw + _snz*_proj_far],
                        [_door_cx - _sux*_shw + _snx*_proj_far,  _top_y, _door_cz - _suz*_shw + _snz*_proj_far],
                    ],
                    "faces": [[0,1,2],[0,2,3],[2,1,0],[3,2,0]],
                })

        # ── Traditional covered porch (non-modern styles) ────────────────────
        porch_depth = float(brief.get("porch_depth_m") or 0.0)
        if porch_depth > 0.1 and not is_modern and _door_cx is not None:
            # Use the door wall vectors so the porch is perfectly aligned.
            fux, fuz = _door_ux, _door_uz
            fnx, fnz = _door_nx, _door_nz
            flen = _door_flen

            # Per-style width range (min_frac, max_frac) — pick a value seeded by
            # the footprint size so the same building always looks the same but
            # different buildings of the same style vary naturally.
            _lo, _hi = _PORCH_WIDTH_RANGE.get(arch_style, (0.28, 0.42))
            # Deterministic variation: hash footprint dimensions so same house = same porch
            _pw_frac = _porch_width_frac(arch_style, flen, porch_depth)

            pw = min(flen * _pw_frac, flen - 0.5)   # at least 25cm wall visible on each side
            pw = max(pw, min(2.2, flen * 0.25))      # never narrower than door + clearance

            phw = pw / 2
            # Center on the door, not the wall midpoint
            pcx = _door_cx
            pcz = _door_cz
            proj = face_offset + porch_depth
            deck_t = 0.22
            deck_col = self._darken(facade_color, 0.80)
            # Deck slab
            meshes.append({
                "element_id": f"porch_deck_{uuid.uuid4().hex[:5]}",
                "element_type": "porch",
                "level": 0, "color": deck_col,
                "vertices": [
                    [pcx-fux*phw + fnx*face_offset, entry_sill_y,        pcz-fuz*phw + fnz*face_offset],
                    [pcx+fux*phw + fnx*face_offset, entry_sill_y,        pcz+fuz*phw + fnz*face_offset],
                    [pcx+fux*phw + fnx*proj,        entry_sill_y,        pcz+fuz*phw + fnz*proj],
                    [pcx-fux*phw + fnx*proj,        entry_sill_y,        pcz-fuz*phw + fnz*proj],
                    [pcx-fux*phw + fnx*face_offset, entry_sill_y-deck_t, pcz-fuz*phw + fnz*face_offset],
                    [pcx+fux*phw + fnx*face_offset, entry_sill_y-deck_t, pcz+fuz*phw + fnz*face_offset],
                    [pcx+fux*phw + fnx*proj,        entry_sill_y-deck_t, pcz+fuz*phw + fnz*proj],
                    [pcx-fux*phw + fnx*proj,        entry_sill_y-deck_t, pcz-fuz*phw + fnz*proj],
                ],
                "faces": [[0,1,2],[0,2,3],[7,6,5],[7,5,4],[0,4,5],[0,5,1],[1,5,6],[1,6,2],[2,6,7],[2,7,3],[3,7,4],[3,4,0]],
            })
            # Porch columns (2 front corners)
            col_h = floor_h * 0.92
            col_r = 0.12
            col_col = trim_color
            for sign in (-1, 1):
                cxp = pcx + fux*phw*0.82*sign + fnx*proj
                czp = pcz + fuz*phw*0.82*sign + fnz*proj
                meshes.append({
                    "element_id": f"porch_col_{uuid.uuid4().hex[:4]}",
                    "element_type": "porch",
                    "level": 0, "color": col_col,
                    "vertices": [
                        [cxp-col_r, entry_sill_y,       czp-col_r],
                        [cxp+col_r, entry_sill_y,       czp-col_r],
                        [cxp+col_r, entry_sill_y,       czp+col_r],
                        [cxp-col_r, entry_sill_y,       czp+col_r],
                        [cxp-col_r, entry_sill_y+col_h, czp-col_r],
                        [cxp+col_r, entry_sill_y+col_h, czp-col_r],
                        [cxp+col_r, entry_sill_y+col_h, czp+col_r],
                        [cxp-col_r, entry_sill_y+col_h, czp+col_r],
                    ],
                    "faces": [[0,1,2],[0,2,3],[4,7,6],[4,6,5],[0,4,5],[0,5,1],[1,5,6],[1,6,2],[2,6,7],[2,7,3],[3,7,4],[3,4,0]],
                })
            # Porch roof overhang
            rov_t = 0.10
            rov_y = entry_sill_y + col_h
            meshes.append({
                "element_id": f"porch_roof_{uuid.uuid4().hex[:4]}",
                "element_type": "porch",
                "level": 0, "color": self._darken(facade_color, 0.70),
                "vertices": [
                    [pcx-fux*(phw+0.15) + fnx*face_offset, rov_y,       pcz-fuz*(phw+0.15) + fnz*face_offset],
                    [pcx+fux*(phw+0.15) + fnx*face_offset, rov_y,       pcz+fuz*(phw+0.15) + fnz*face_offset],
                    [pcx+fux*(phw+0.15) + fnx*(proj+0.15), rov_y,       pcz+fuz*(phw+0.15) + fnz*(proj+0.15)],
                    [pcx-fux*(phw+0.15) + fnx*(proj+0.15), rov_y,       pcz-fuz*(phw+0.15) + fnz*(proj+0.15)],
                    [pcx-fux*(phw+0.15) + fnx*face_offset, rov_y+rov_t, pcz-fuz*(phw+0.15) + fnz*face_offset],
                    [pcx+fux*(phw+0.15) + fnx*face_offset, rov_y+rov_t, pcz+fuz*(phw+0.15) + fnz*face_offset],
                    [pcx+fux*(phw+0.15) + fnx*(proj+0.15), rov_y+rov_t, pcz+fuz*(phw+0.15) + fnz*(proj+0.15)],
                    [pcx-fux*(phw+0.15) + fnx*(proj+0.15), rov_y+rov_t, pcz-fuz*(phw+0.15) + fnz*(proj+0.15)],
                ],
                "faces": [[4,5,6],[4,6,7],[0,3,2],[0,2,1]],
            })

        # ── Garage doors — only when AI puts a garage room in the program ────
        garage_rooms = [r for r in (rooms or []) if getattr(r, 'type', '') == 'garage' and getattr(r, 'level', 0) == 0]
        if garage_rooms and ext_walls:
            for gr in garage_rooms:
                gp = gr.polygon or []
                if len(gp) < 3:
                    continue
                gxs = [p[0] for p in gp]
                gzs = [p[1] for p in gp]
                gcx = sum(gxs) / len(gxs)
                gcz = sum(gzs) / len(gzs)
                gw  = max(gxs) - min(gxs)
                # Find the best exterior wall for the garage door.
                # Preference order: (1) front face (street) walls within reach of garage,
                # (2) side walls near garage, (3) absolutely nearest wall.
                # This prevents garage doors from appearing on the back or facing the porch.
                front_walls_near = [
                    ew for ew in ext_walls
                    if (ew.start[1]+ew.end[1])/2 <= front_face_z + 0.5
                    and math.sqrt(((ew.start[0]+ew.end[0])/2-gcx)**2+((ew.start[1]+ew.end[1])/2-gcz)**2) < 10.0
                ]
                candidate_walls = front_walls_near if front_walls_near else ext_walls
                best_wall, best_d = None, 999.0
                for ew in candidate_walls:
                    emx = (ew.start[0]+ew.end[0])/2
                    emz = (ew.start[1]+ew.end[1])/2
                    d   = math.sqrt((emx-gcx)**2+(emz-gcz)**2)
                    if d < best_d:
                        best_d, best_wall = d, ew
                if best_wall is None or best_d > 12.0:
                    continue
                es, ee = best_wall.start, best_wall.end
                edx, edz = ee[0]-es[0], ee[1]-es[1]
                elen = max(0.01, math.sqrt(edx*edx+edz*edz))
                eux, euz = edx/elen, edz/elen
                enx, enz = euz, -eux
                if enx*((es[0]+ee[0])/2-poly_cx)+enz*((es[1]+ee[1])/2-poly_cz) < 0:
                    enx, enz = -enx, -enz
                # Garage door: 2.7m wide (single bay), 2.35m tall, centered on wall
                gd_w = min(gw * 0.85, 5.5)   # up to double-wide
                gd_h = 2.35
                gd_fo = face_offset + 0.02
                ghw   = gd_w / 2
                # Panel sections (4 horizontal panels)
                n_panels = 4
                ph = gd_h / n_panels
                panel_col = self._darken(facade_color, 0.65)
                for pi in range(n_panels):
                    py0 = pi * ph
                    py1 = py0 + ph - 0.04
                    meshes.append({
                        "element_id": f"gdoor_p{pi}_{uuid.uuid4().hex[:4]}",
                        "element_type": "garage_door",
                        "level": 0, "color": panel_col,
                        "vertices": [
                            [gcx-eux*ghw + enx*gd_fo, py0, gcz-euz*ghw + enz*gd_fo],
                            [gcx+eux*ghw + enx*gd_fo, py0, gcz+euz*ghw + enz*gd_fo],
                            [gcx+eux*ghw + enx*gd_fo, py1, gcz+euz*ghw + enz*gd_fo],
                            [gcx-eux*ghw + enx*gd_fo, py1, gcz-euz*ghw + enz*gd_fo],
                        ],
                        "faces": [[0,1,2],[0,2,3],[2,1,0],[3,2,0]],
                    })
                # Garage door frame
                ft = 0.06
                meshes.append({
                    "element_id": f"gdoor_frame_{uuid.uuid4().hex[:4]}",
                    "element_type": "door_frame",
                    "level": 0, "color": trim_color,
                    "vertices": [
                        [gcx-eux*(ghw+ft) + enx*gd_fo, 0,        gcz-euz*(ghw+ft) + enz*gd_fo],
                        [gcx+eux*(ghw+ft) + enx*gd_fo, 0,        gcz+euz*(ghw+ft) + enz*gd_fo],
                        [gcx+eux*(ghw+ft) + enx*gd_fo, gd_h+ft,  gcz+euz*(ghw+ft) + enz*gd_fo],
                        [gcx-eux*(ghw+ft) + enx*gd_fo, gd_h+ft,  gcz-euz*(ghw+ft) + enz*gd_fo],
                    ],
                    "faces": [[0,1,2],[0,2,3]],
                })

        return meshes

    def _add_entry_door(
        self, meshes, s, e, dx, dz, ux, uz, nx, nz,
        face_offset, door_sill, arch_style, facade_color, t_door: float = 0.5,
    ):
        """Append the single front entry assembly before style window shortcuts.

        `t_door` is the fraction along this wall where the leaf is centred,
        chosen by the caller from the plan's entry room.
        """
        door_w = 1.05
        door_h = 2.15
        dcx = s[0] + t_door * dx
        dcz = s[1] + t_door * dz
        hdw = door_w / 2
        # The casing stands proud of the wall and the leaf sits recessed behind
        # it. Both used to sit at the same face_offset + 0.01, so the frame —
        # which is drawn larger than the leaf — was exactly coplanar with it and
        # z-fought the door away to nothing.
        door_fo  = face_offset + 0.005
        frame_fo = face_offset + 0.025
        meshes.append({
            "element_id": f"door_{uuid.uuid4().hex[:6]}",
            "element_type": "door",
            "vertices": [
                [dcx - ux*hdw + nx*door_fo, door_sill,          dcz - uz*hdw + nz*door_fo],
                [dcx + ux*hdw + nx*door_fo, door_sill,          dcz + uz*hdw + nz*door_fo],
                [dcx + ux*hdw + nx*door_fo, door_sill + door_h, dcz + uz*hdw + nz*door_fo],
                [dcx - ux*hdw + nx*door_fo, door_sill + door_h, dcz - uz*hdw + nz*door_fo],
            ],
            "faces": [[0, 1, 2], [0, 2, 3], [2, 1, 0], [3, 2, 0]],
            "level": 0,
            "color": "#7c5c3a",
        })
        # Casing as a border RING (outer ▭ minus inner ▭), not a filled quad.
        # The old two-triangle version covered the whole opening, so the slate
        # frame painted straight over the door leaf.
        ft = 0.06
        ow, oh0, oh1 = hdw + ft, door_sill - ft, door_sill + door_h + ft
        def _fv(off_u, y):
            return [dcx + ux*off_u + nx*frame_fo, y, dcz + uz*off_u + nz*frame_fo]
        meshes.append({
            "element_id": f"door_frame_{uuid.uuid4().hex[:5]}",
            "element_type": "door_frame",
            "vertices": [
                _fv(-ow, oh0), _fv(ow, oh0), _fv(ow, oh1), _fv(-ow, oh1),          # outer 0-3
                _fv(-hdw, door_sill), _fv(hdw, door_sill),                          # inner 4-5
                _fv(hdw, door_sill + door_h), _fv(-hdw, door_sill + door_h),        # inner 6-7
            ],
            "faces": [
                [0, 1, 5], [0, 5, 4],   # threshold
                [1, 2, 6], [1, 6, 5],   # right jamb
                [2, 3, 7], [2, 7, 6],   # head
                [3, 0, 4], [3, 4, 7],   # left jamb
            ],
            "level": 0,
            "color": "#334155",
        })

        if arch_style not in (
            "contemporary_box", "modern_linear", "minimalist",
            "contemporary", "urban_infill",
        ):
            return dcx, dcz

        can_y = door_sill + door_h + 0.12
        can_proj = face_offset + 0.85
        can_t = 0.09
        can_hw = door_w * 1.60
        can_c = self._darken(facade_color, 0.60)
        can_v = [
            [dcx - ux*can_hw + nx*face_offset, can_y,       dcz - uz*can_hw + nz*face_offset],
            [dcx + ux*can_hw + nx*face_offset, can_y,       dcz + uz*can_hw + nz*face_offset],
            [dcx + ux*can_hw + nx*can_proj,    can_y,       dcz + uz*can_hw + nz*can_proj],
            [dcx - ux*can_hw + nx*can_proj,    can_y,       dcz - uz*can_hw + nz*can_proj],
            [dcx - ux*can_hw + nx*face_offset, can_y+can_t, dcz - uz*can_hw + nz*face_offset],
            [dcx + ux*can_hw + nx*face_offset, can_y+can_t, dcz + uz*can_hw + nz*face_offset],
            [dcx + ux*can_hw + nx*can_proj,    can_y+can_t, dcz + uz*can_hw + nz*can_proj],
            [dcx - ux*can_hw + nx*can_proj,    can_y+can_t, dcz - uz*can_hw + nz*can_proj],
        ]
        meshes.append({
            "element_id": f"canopy_{uuid.uuid4().hex[:5]}",
            "element_type": "porch",
            "vertices": can_v,
            "faces": [
                [4,5,6], [4,6,7], [0,4,7], [0,7,3], [1,5,6],
                [1,6,2], [3,7,6], [3,6,2], [0,3,2], [0,2,1],
            ],
            "level": 0,
            "color": can_c,
        })
        for leg_sign in (-1, 1):
            leg_x = dcx + ux * can_hw * 0.75 * leg_sign
            leg_z = dcz + uz * can_hw * 0.75 * leg_sign
            leg_proj = face_offset + can_proj * 0.55
            lhw = 0.04
            meshes.append({
                "element_id": f"canopy_leg_{uuid.uuid4().hex[:4]}",
                "element_type": "porch",
                "vertices": [
                    [leg_x - ux*lhw + nx*leg_proj, door_sill, leg_z - uz*lhw + nz*leg_proj],
                    [leg_x + ux*lhw + nx*leg_proj, door_sill, leg_z + uz*lhw + nz*leg_proj],
                    [leg_x + ux*lhw + nx*leg_proj, can_y,     leg_z + uz*lhw + nz*leg_proj],
                    [leg_x - ux*lhw + nx*leg_proj, can_y,     leg_z - uz*lhw + nz*leg_proj],
                ],
                "faces": [[0,1,2], [0,2,3], [2,1,0], [3,2,0]],
                "level": 0,
                "color": "#334155",
            })
        return dcx, dcz

    # ── Victorian bay window — 3-sided box projection on front face ─────────────
    def _add_bay_window(
        self, meshes, s, e, dx, dz, ux, uz, nx, nz,
        wall_len, base_y, floor_h, face_offset,
        win_color, facade_color, lvl,
    ):
        """Rectangular 3-sided bay window projecting 0.65 m out from the facade.
        Placed left-of-centre on even floors, right-of-centre on odd (Victorian asymmetry)."""
        BAY_PROJ  = 0.65
        BAY_W     = min(1.55, wall_len * 0.55)
        SILL_Y    = base_y + floor_h * 0.28
        TOP_Y     = base_y + floor_h * 0.88
        SILL_BASE = base_y
        fo        = face_offset

        t_center  = 0.38 if lvl % 2 == 0 else 0.62   # alternate position per floor
        bcx = s[0] + t_center * dx
        bcz = s[1] + t_center * dz
        hw  = BAY_W / 2
        sw  = BAY_W * 0.28  # side-panel width

        # Bay outer box: front face + two angled side faces
        # Points at sill level (8 pts: 4 inner, 4 outer)
        def pt(t_along, proj):
            cx = s[0] + t_along * dx
            cz = s[1] + t_along * dz
            return [cx + nx * (fo + proj), None, cz + nz * (fo + proj)]

        # Inner-wall attachment points (no projection)
        il = [bcx - ux*hw + nx*fo,  None, bcz - uz*hw + nz*fo]
        ir = [bcx + ux*hw + nx*fo,  None, bcz + uz*hw + nz*fo]
        # Outer-front points (full projection)
        ol = [bcx - ux*(hw-sw) + nx*(fo+BAY_PROJ), None, bcz - uz*(hw-sw) + nz*(fo+BAY_PROJ)]
        oc = [bcx + nx*(fo+BAY_PROJ),               None, bcz + nz*(fo+BAY_PROJ)]
        or_ = [bcx + ux*(hw-sw) + nx*(fo+BAY_PROJ), None, bcz + uz*(hw-sw) + nz*(fo+BAY_PROJ)]

        def at(p, y): return [p[0], y, p[2]]

        # Sill base fill (opaque panel from floor to sill)
        sill_verts = [
            at(il, SILL_BASE), at(ol, SILL_BASE), at(oc, SILL_BASE), at(or_, SILL_BASE), at(ir, SILL_BASE),
            at(il, SILL_Y),    at(ol, SILL_Y),    at(oc, SILL_Y),    at(or_, SILL_Y),    at(ir, SILL_Y),
        ]
        sill_faces = [[0,1,6],[0,6,5],[1,2,7],[1,7,6],[2,3,8],[2,8,7],[3,4,9],[3,9,8]]
        meshes.append({
            "element_id": f"bay_sill_{uuid.uuid4().hex[:5]}",
            "element_type": "window_frame",
            "vertices": sill_verts, "faces": sill_faces,
            "level": 0, "color": self._darken(facade_color, 0.85),
        })

        # Bay glass (sill to top)
        glass_verts = [
            at(il, SILL_Y), at(ol, SILL_Y), at(oc, SILL_Y), at(or_, SILL_Y), at(ir, SILL_Y),
            at(il, TOP_Y),  at(ol, TOP_Y),  at(oc, TOP_Y),  at(or_, TOP_Y),  at(ir, TOP_Y),
        ]
        glass_faces = [[0,1,6],[0,6,5],[1,2,7],[1,7,6],[2,3,8],[2,8,7],[3,4,9],[3,9,8],
                       [5,6,7],[5,7,8],[5,8,9]]  # back face (inside) + top cap
        meshes.append({
            "element_id": f"bay_glass_{uuid.uuid4().hex[:5]}",
            "element_type": "window",
            "vertices": glass_verts, "faces": glass_faces,
            "level": 0, "color": win_color,
        })

        # Header / cornice above bay
        HDR_H = 0.10
        hdr_verts = [
            at(il, TOP_Y), at(ol, TOP_Y), at(oc, TOP_Y), at(or_, TOP_Y), at(ir, TOP_Y),
            at(il, TOP_Y+HDR_H), at(ol, TOP_Y+HDR_H), at(oc, TOP_Y+HDR_H),
            at(or_, TOP_Y+HDR_H), at(ir, TOP_Y+HDR_H),
        ]
        meshes.append({
            "element_id": f"bay_hdr_{uuid.uuid4().hex[:5]}",
            "element_type": "window_frame",
            "vertices": hdr_verts,
            "faces": [[0,1,6],[0,6,5],[1,2,7],[1,7,6],[2,3,8],[2,8,7],[3,4,9],[3,9,8],
                      [5,6,7],[5,7,8],[5,8,9]],
            "level": 0, "color": self._darken(facade_color, 0.70),
        })

    # ── Mid-century / modern: continuous horizontal strip window ─────────────
    def _add_strip_window(
        self, meshes, s, e, dx, dz, ux, uz, nx, nz,
        wall_len, base_y, floor_h, face_offset, win_color, lvl,
        door_gap=None,
    ):
        """Full-width horizontal band of glazing — mid-century / prefab modern style.
        Strip leaves 20% margins on each side and a solid sill + head band."""
        MARGIN    = wall_len * 0.12
        SILL_Y    = base_y + floor_h * 0.30
        TOP_Y     = base_y + floor_h * 0.82
        fo        = face_offset

        start_d = MARGIN
        end_d = wall_len - MARGIN
        segments = [(start_d, end_d)]
        if door_gap is not None:
            gap_start = max(start_d, float(door_gap[0]))
            gap_end = min(end_d, float(door_gap[1]))
            segments = []
            if gap_start - start_d >= 0.30:
                segments.append((start_d, gap_start))
            if end_d - gap_end >= 0.30:
                segments.append((gap_end, end_d))

        for segment_start, segment_end in segments:
            segment_len = segment_end - segment_start
            x0 = s[0] + ux * segment_start
            z0 = s[1] + uz * segment_start
            x1 = s[0] + ux * segment_end
            z1 = s[1] + uz * segment_end
            strip_verts = [
                [x0 + nx*fo, SILL_Y, z0 + nz*fo],
                [x1 + nx*fo, SILL_Y, z1 + nz*fo],
                [x1 + nx*fo, TOP_Y,  z1 + nz*fo],
                [x0 + nx*fo, TOP_Y,  z0 + nz*fo],
            ]
            meshes.append({
                "element_id": f"strip_win_{uuid.uuid4().hex[:5]}",
                "element_type": "window",
                "vertices": strip_verts,
                "faces": [[0,1,2],[0,2,3],[2,1,0],[3,2,0]],
                "level": lvl, "color": win_color,
            })
            # Thin dark frame for each retained glazing segment.
            FT = 0.04
            for fv, ff in self._frame_quads(
                (x0+x1)/2, (z0+z1)/2, SILL_Y, TOP_Y-SILL_Y, segment_len,
                ux, uz, nx, nz, fo, FT,
            ):
                meshes.append({
                    "element_id": f"strip_frm_{uuid.uuid4().hex[:5]}",
                    "element_type": "window_frame",
                    "vertices": fv, "faces": ff,
                    "level": lvl, "color": "#1e293b",
                })

    # ── Flat parapet (original logic, extracted) ──────────────────────────────
    def _add_flat_parapet(self, meshes, massing_option, stories, floor_h, facade_color):
        roof_y = stories * floor_h
        par_h  = 0.65
        par_t  = 0.20
        footprint = massing_option.get("footprint", [])
        n_pts = len(footprint)
        if n_pts < 3:
            return
        # If massing already provided parapet/roof meshes, avoid duplicating them.
        for m in massing_option.get("meshes", []):
            if m.get("element_type") in ("parapet", "roof"):
                return
        n = n_pts - 1 if (footprint[0] == footprint[-1]) else n_pts
        for i in range(n):
            x0, z0 = footprint[i][0], footprint[i][1]
            x1, z1 = footprint[(i+1) % n][0], footprint[(i+1) % n][1]
            seg = math.sqrt((x1-x0)**2 + (z1-z0)**2)
            if seg < 0.1:
                continue
            ux2, uz2 = (x1-x0)/seg, (z1-z0)/seg
            nx2, nz2 = uz2, -ux2
            verts = [
                [x0,             roof_y,         z0],
                [x1,             roof_y,         z1],
                [x1,             roof_y + par_h, z1],
                [x0,             roof_y + par_h, z0],
                [x0 + nx2*par_t, roof_y,         z0 + nz2*par_t],
                [x1 + nx2*par_t, roof_y,         z1 + nz2*par_t],
                [x1 + nx2*par_t, roof_y + par_h, z1 + nz2*par_t],
                [x0 + nx2*par_t, roof_y + par_h, z0 + nz2*par_t],
            ]
            meshes.append({
                "element_id": f"par_{i}",
                "element_type": "parapet",
                "vertices": verts,
                "faces": [[0,1,2],[0,2,3],[5,4,7],[5,7,6],[3,2,6],[3,6,7],[0,3,7],[0,7,4],[1,5,6],[1,6,2]],
                "level": 0,
                "color": facade_color,
            })

    # ── Pitched roof (gabled or hipped) ──────────────────────────────────────
    def _add_pitched_roof(self, meshes, massing_option, stories, floor_h, facade_color, roof_type="gabled"):
        footprint = massing_option.get("footprint", [])
        n_pts = len(footprint)
        if n_pts < 3:
            return

        # If massing already provided a roof, skip pitched roof generation to
        # avoid overlapping roof geometry.
        for m in massing_option.get("meshes", []):
            if m.get("element_type") == "roof":
                return

        roof_y = stories * floor_h
        n = n_pts - 1 if (footprint[0] == footprint[-1]) else n_pts
        pts = [[footprint[i][0], footprint[i][1]] for i in range(n)]

        # Bounding box → determine long axis for ridge
        EAVE = 0.3  # overhang so roof edge sits outside wall face, not recessed
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        min_x, max_x = min(xs) - EAVE, max(xs) + EAVE
        min_z, max_z = min(zs) - EAVE, max(zs) + EAVE
        w = max_x - min_x
        d = max_z - min_z
        cx = (min_x + max_x) / 2
        cz = (min_z + max_z) / 2

        # Ridge height: ~30% of the shorter span (typical residential pitch)
        ridge_h = min(w, d) * 0.30
        roof_color = self._darken(facade_color, 0.55)

        if roof_type in ("hipped", "hip"):
            # Hip roof: 4 triangular/trapezoidal faces converging to a ridge at centre
            inset = min(w, d) * 0.18
            ridge_y = roof_y + ridge_h

            # Eave corners at roof base
            corners = [
                [min_x, min_z], [max_x, min_z],
                [max_x, max_z], [min_x, max_z],
            ]
            # Ridge corners (inset)
            ridge_pts = [
                [min_x + inset, cz],
                [max_x - inset, cz],
            ] if w >= d else [
                [cx, min_z + inset],
                [cx, max_z - inset],
            ]

            # Build faces: front, back, left, right slopes
            if w >= d:
                # Ridge runs along X; front/back are trapezoids, sides are triangles
                faces_verts = [
                    # Front slope
                    [corners[0], corners[1],
                     [ridge_pts[1][0], min_z, ridge_pts[1][1]],  # not used but pad
                     [ridge_pts[0][0], min_z, ridge_pts[0][1]]],
                    # Back slope
                    [corners[3], corners[2],
                     [ridge_pts[1][0], max_z, ridge_pts[1][1]],
                     [ridge_pts[0][0], max_z, ridge_pts[0][1]]],
                ]
                # Simple trapezoid front/back slopes + triangular gable ends
                def hip_face(a, b, rb, ra):
                    v = [
                        [a[0], roof_y,   a[1]],
                        [b[0], roof_y,   b[1]],
                        [rb[0], ridge_y, rb[1]],
                        [ra[0], ridge_y, ra[1]],
                    ]
                    return v, [[0,1,2],[0,2,3]]

                r0 = [ridge_pts[0][0], ridge_pts[0][1]]
                r1 = [ridge_pts[1][0], ridge_pts[1][1]]

                for (a, b, ra, rb) in [
                    (corners[0], corners[1], r0, r1),   # front
                    (corners[2], corners[3], r1, r0),   # back
                ]:
                    v, f = hip_face(a, b, ra, rb)
                    meshes.append({
                        "element_id": f"roof_slope_{uuid.uuid4().hex[:4]}",
                        "element_type": "roof",
                        "vertices": v, "faces": f,
                        "level": 0, "color": roof_color,
                    })

                # Triangular end slopes
                for (tip, base_a, base_b) in [
                    (r0, corners[0], corners[3]),
                    (r1, corners[1], corners[2]),
                ]:
                    v = [
                        [base_a[0], roof_y,   base_a[1]],
                        [base_b[0], roof_y,   base_b[1]],
                        [tip[0],    ridge_y,  tip[1]],
                    ]
                    meshes.append({
                        "element_id": f"roof_end_{uuid.uuid4().hex[:4]}",
                        "element_type": "roof",
                        "vertices": v, "faces": [[0,1,2],[2,1,0]],
                        "level": 0, "color": roof_color,
                    })
        else:
            # Gabled roof: 2 rectangular sloping faces + 2 triangular gable ends
            if w >= d:
                # Ridge runs along X axis
                ridge_y = roof_y + ridge_h
                # Front slope: from min_z eave → ridge at cz
                meshes.append({
                    "element_id": f"roof_front_{uuid.uuid4().hex[:4]}",
                    "element_type": "roof",
                    "vertices": [
                        [min_x, roof_y,   min_z],
                        [max_x, roof_y,   min_z],
                        [max_x, ridge_y,  cz],
                        [min_x, ridge_y,  cz],
                    ],
                    "faces": [[0,1,2],[0,2,3],[2,1,0],[3,2,0]],
                    "level": 0, "color": roof_color,
                })
                # Back slope
                meshes.append({
                    "element_id": f"roof_back_{uuid.uuid4().hex[:4]}",
                    "element_type": "roof",
                    "vertices": [
                        [min_x, roof_y,   max_z],
                        [max_x, roof_y,   max_z],
                        [max_x, ridge_y,  cz],
                        [min_x, ridge_y,  cz],
                    ],
                    "faces": [[0,2,1],[0,3,2],[1,2,0],[2,3,0]],
                    "level": 0, "color": roof_color,
                })
                # Gable ends (triangles)
                for ex in [min_x, max_x]:
                    meshes.append({
                        "element_id": f"roof_gable_{uuid.uuid4().hex[:4]}",
                        "element_type": "roof",
                        "vertices": [
                            [ex, roof_y,   min_z],
                            [ex, roof_y,   max_z],
                            [ex, ridge_y,  cz],
                        ],
                        "faces": [[0,1,2],[2,1,0]],
                        "level": 0, "color": self._darken(facade_color, 0.75),
                    })
            else:
                # Ridge runs along Z axis
                ridge_y = roof_y + ridge_h
                meshes.append({
                    "element_id": f"roof_left_{uuid.uuid4().hex[:4]}",
                    "element_type": "roof",
                    "vertices": [
                        [min_x, roof_y,   min_z],
                        [min_x, roof_y,   max_z],
                        [cx,    ridge_y,  max_z],
                        [cx,    ridge_y,  min_z],
                    ],
                    "faces": [[0,1,2],[0,2,3],[2,1,0],[3,2,0]],
                    "level": 0, "color": roof_color,
                })
                meshes.append({
                    "element_id": f"roof_right_{uuid.uuid4().hex[:4]}",
                    "element_type": "roof",
                    "vertices": [
                        [max_x, roof_y,   min_z],
                        [max_x, roof_y,   max_z],
                        [cx,    ridge_y,  max_z],
                        [cx,    ridge_y,  min_z],
                    ],
                    "faces": [[0,2,1],[0,3,2],[1,2,0],[2,3,0]],
                    "level": 0, "color": roof_color,
                })
                for ez in [min_z, max_z]:
                    meshes.append({
                        "element_id": f"roof_gable_{uuid.uuid4().hex[:4]}",
                        "element_type": "roof",
                        "vertices": [
                            [min_x, roof_y,   ez],
                            [max_x, roof_y,   ez],
                            [cx,    ridge_y,  ez],
                        ],
                        "faces": [[0,1,2],[2,1,0]],
                        "level": 0, "color": self._darken(facade_color, 0.75),
                    })

    # ── Top-floor setback ─────────────────────────────────────────────────────
    def _add_setback_cap(self, meshes, massing_option, stories, floor_h, color):
        footprint = massing_option.get("footprint", [])
        n_pts = len(footprint)
        if n_pts < 3:
            return
        inset = 0.8
        top_base = (stories - 1) * floor_h
        n = n_pts - 1 if (footprint[n_pts-1] == footprint[0]) else n_pts

        cx = sum(footprint[i][0] for i in range(n)) / n
        cz = sum(footprint[i][1] for i in range(n)) / n

        inner = []
        for i in range(n):
            x, z = footprint[i][0], footprint[i][1]
            dx, dz = cx - x, cz - z
            d = math.sqrt(dx*dx + dz*dz) or 1
            inner.append([x + dx/d * inset, z + dz/d * inset])

        for i in range(n):
            j = (i+1) % n
            verts = [
                [footprint[i][0], top_base, footprint[i][1]],
                [footprint[j][0], top_base, footprint[j][1]],
                [inner[j][0],     top_base, inner[j][1]],
                [inner[i][0],     top_base, inner[i][1]],
            ]
            meshes.append({
                "element_id": f"setback_{i}",
                "element_type": "setback_ledge",
                "vertices": verts,
                "faces": [[0,1,2],[0,2,3],[2,1,0],[3,2,0]],
                "level": 0,
                "color": self._darken(color, 0.7),
            })

    def _darken(self, hex_color: str, factor: float) -> str:
        try:
            h = hex_color.lstrip('#')
            if len(h) != 6:
                return hex_color
            r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
            r, g, b = int(r*factor), int(g*factor), int(b*factor)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    # ── Room-aware helpers ────────────────────────────────────────────────────

    # CRC R310: a bedroom egress window needs 5.7 sq ft (0.53 m²) net clear,
    # with minimum clear width 20 in (0.51 m) and height 24 in (0.61 m). The
    # archetypes carry the same number as california_compliance.
    # egress_window_min_sqft. Bedrooms therefore can't be given token windows.
    _EGRESS_MIN_AREA_M2 = 0.53
    _EGRESS_MIN_W_M = 0.51
    _EGRESS_MIN_H_M = 0.61

    def _room_window_spec(
        self, room_type: Optional[str], arch_style: str,
        window_ratio: float, win_h_frac: float, floor_h: float,
    ) -> Tuple[float, float, float, str]:
        """(width_m, height_m, sill_frac, style) for the room behind a bay.

        Composes the per-room-type table with the per-style multipliers — the
        same composition _place_side_windows already used, which the front
        elevation never did.
        """
        ws, hs, ss = _ARCH_WIN_SCALE.get(arch_style, (1.0, 1.0, 0.0))
        if room_type and room_type in _ROOM_WIN:
            spec = _ROOM_WIN[room_type]
            win_w = spec["w"] * ws
            win_h = spec["h"] * hs
            sill_frac = max(0.08, spec["sill_frac"] + ss)
            style = spec["style"]
        else:
            # Unknown room behind this bay — fall back to the brief's scalars,
            # still style-scaled so the elevation doesn't go flat.
            win_w = 1.10 * ws
            win_h = floor_h * win_h_frac * (0.8 + window_ratio * 0.4)
            sill_frac = max(0.08, (0.28 - window_ratio * 0.05) + ss)
            style = "double_hung"

        if room_type == "bedroom":
            win_w = max(win_w, self._EGRESS_MIN_W_M)
            win_h = max(win_h, self._EGRESS_MIN_H_M)
            if win_w * win_h < self._EGRESS_MIN_AREA_M2:
                win_h = self._EGRESS_MIN_AREA_M2 / win_w
            # Sill max 44 in (1.12 m) above the floor for egress.
            sill_frac = min(sill_frac, 1.12 / max(floor_h, 0.1))
        return win_w, win_h, sill_frac, style

    def _room_at_wall_frac(
        self, wall, rooms: list, lvl: int,
        inward_nx: float, inward_nz: float, t_frac: float,
    ):
        """Room behind one specific point along a wall.

        _find_adj_room returns a single room for the whole wall, so a facade
        spanning a bedroom, a bath and a stair got one window spec for all
        three. Probing per bay is what lets openings differ along one elevation.
        """
        s, e = wall.start, wall.end
        dx, dz = e[0] - s[0], e[1] - s[1]
        lvl_rooms = [
            r for r in rooms
            if r.level == lvl and r.polygon and len(r.polygon) >= 3
        ]
        if not lvl_rooms:
            return None
        lvl_rooms.sort(key=lambda r: r.area_sqft)
        for depth in (0.9, 1.5, 2.2):
            px = s[0] + t_frac * dx + inward_nx * depth
            pz = s[1] + t_frac * dz + inward_nz * depth
            for room in lvl_rooms:
                if _pip(px, pz, room.polygon):
                    return room
        return None

    def _find_adj_room(self, wall, rooms: list, lvl: int, inward_nx: float, inward_nz: float):
        """Find the room adjacent to an exterior wall by probing inward."""
        s, e = wall.start, wall.end
        dx, dz = e[0] - s[0], e[1] - s[1]
        wl = math.sqrt(dx * dx + dz * dz)
        if wl < 0.1 or not rooms:
            return None
        lvl_rooms = sorted(
            [r for r in rooms if r.level == lvl and r.polygon and len(r.polygon) >= 3],
            key=lambda r: r.area_sqft,
        )
        for t_frac in (0.25, 0.5, 0.75):
            px = s[0] + t_frac * dx + inward_nx * 1.2
            pz = s[1] + t_frac * dz + inward_nz * 1.2
            for room in lvl_rooms:
                if _pip(px, pz, room.polygon):
                    return room
        return None

    def _add_styled_window(
        self, meshes, wcx, wcz, win_sill, win_h, win_w,
        ux, uz, nx, nz, fo, win_color, trim_color, style, lvl,
    ):
        """Place a window with style-specific detail (mullion, divider, etc.)."""
        hw = win_w / 2
        ft = 0.055

        meshes.append({
            "element_id": f"win_{uuid.uuid4().hex[:6]}",
            "element_type": "window",
            "vertices": [
                [wcx - ux*hw + nx*fo, win_sill,          wcz - uz*hw + nz*fo],
                [wcx + ux*hw + nx*fo, win_sill,          wcz + uz*hw + nz*fo],
                [wcx + ux*hw + nx*fo, win_sill + win_h,  wcz + uz*hw + nz*fo],
                [wcx - ux*hw + nx*fo, win_sill + win_h,  wcz - uz*hw + nz*fo],
            ],
            "faces": [[0, 1, 2], [0, 2, 3], [2, 1, 0], [3, 2, 0]],
            "level": 0,
            "color": win_color,
        })
        for fv, ff in self._frame_quads(wcx, wcz, win_sill, win_h, win_w, ux, uz, nx, nz, fo, ft):
            meshes.append({
                "element_id": f"frm_{uuid.uuid4().hex[:6]}",
                "element_type": "window_frame",
                "vertices": fv, "faces": ff,
                "level": 0, "color": trim_color,
            })

        # Style-specific interior detail
        if style == "double_hung":
            mid_y = win_sill + win_h * 0.55
            bar_t = 0.038
            meshes.append({
                "element_id": f"mullion_{uuid.uuid4().hex[:5]}",
                "element_type": "window_frame",
                "vertices": [
                    [wcx - ux*hw + nx*fo, mid_y,         wcz - uz*hw + nz*fo],
                    [wcx + ux*hw + nx*fo, mid_y,         wcz + uz*hw + nz*fo],
                    [wcx + ux*hw + nx*fo, mid_y + bar_t, wcz + uz*hw + nz*fo],
                    [wcx - ux*hw + nx*fo, mid_y + bar_t, wcz - uz*hw + nz*fo],
                ],
                "faces": [[0, 1, 2], [0, 2, 3]],
                "level": 0, "color": trim_color,
            })

        elif style == "casement" and win_w > 0.7:
            # Thin vertical divider (paired casement)
            dv_t = 0.038
            meshes.append({
                "element_id": f"div_{uuid.uuid4().hex[:5]}",
                "element_type": "window_frame",
                "vertices": [
                    [wcx - ux*dv_t + nx*fo, win_sill,          wcz - uz*dv_t + nz*fo],
                    [wcx + ux*dv_t + nx*fo, win_sill,          wcz + uz*dv_t + nz*fo],
                    [wcx + ux*dv_t + nx*fo, win_sill + win_h,  wcz + uz*dv_t + nz*fo],
                    [wcx - ux*dv_t + nx*fo, win_sill + win_h,  wcz - uz*dv_t + nz*fo],
                ],
                "faces": [[0, 1, 2], [0, 2, 3], [2, 1, 0], [3, 2, 0]],
                "level": 0, "color": trim_color,
            })

    def _place_semantic_windows(
        self, meshes, s, e, dx, dz, ux, uz, nx, nz,
        wall_len, base_y, floor_h, fo, win_color, trim_color,
        arch_style, lvl, openings, sem_w, seg_start_m: float = 0.0,
    ):
        """Place windows at Claude's exact fractional positions with style detail."""
        ws, hs, ss = _ARCH_WIN_SCALE.get(arch_style, (1.0, 1.0, 0.0))
        for op in openings:
            if op.get("type") not in ("window",):
                continue
            offset_m = float(op.get("offset_m", 0))
            win_w    = float(op.get("width_m", 1.0)) * ws
            win_h    = float(op.get("height_m", 1.3)) * hs
            sill_abs = float(op.get("sill_m", 0.9))
            style    = op.get("style", "double_hung")

            # Window center in facade-space (measured along full front face)
            win_center_facade = offset_m + win_w / 2

            # Only place this window if its center falls within this segment
            seg_end_m = seg_start_m + wall_len
            if win_center_facade < seg_start_m - 0.1 or win_center_facade > seg_end_m + 0.1:
                continue

            if style == "bay_3panel":
                self._add_bay_window(
                    meshes, s, e, dx, dz, ux, uz, nx, nz,
                    wall_len, base_y, floor_h, fo,
                    win_color, self._darken(win_color, 0.5), lvl,
                )
                continue

            if style == "strip_horizontal":
                self._add_strip_window(
                    meshes, s, e, dx, dz, ux, uz, nx, nz,
                    wall_len, base_y, floor_h, fo, win_color, lvl,
                )
                continue

            # Map window center from facade-space into this segment's [0,1] fraction
            t_center = (win_center_facade - seg_start_m) / max(wall_len, 0.01)
            t_center = min(max(t_center, 0.05), 0.95)
            wcx = s[0] + t_center * dx
            wcz = s[1] + t_center * dz
            win_sill = base_y + sill_abs + (floor_h * ss)
            _top_max = base_y + floor_h - 0.2
            if win_sill + win_h > _top_max:
                win_h = max(0.3, _top_max - win_sill)
            if win_h < 0.3:
                continue

            self._add_styled_window(
                meshes, wcx, wcz, win_sill, win_h,
                min(win_w, wall_len * 0.7),
                ux, uz, nx, nz, fo, win_color, trim_color, style, lvl,
            )

    def _place_side_windows(
        self, meshes, s, e, dx, dz, ux, uz, nx, nz,
        wall_len, base_y, floor_h, fo, win_color, trim_color,
        arch_style, lvl, adj_room, is_back, wall=None, rooms=None,
    ):
        """Room-aware windows for non-front walls."""
        rooms = rooms or []
        rtype = adj_room.type if adj_room else None

        if rtype in _NO_WIN_TYPES:
            return

        # Back wall + living/dining/family → patio sliding glass door
        if is_back and rtype in _PATIO_TYPES:
            self._add_patio_door(
                meshes, s, e, dx, dz, ux, uz, nx, nz,
                wall_len, base_y, floor_h, fo, win_color, trim_color, lvl,
            )
            return

        spec = _ROOM_WIN.get(rtype or "", {
            "w": 0.9, "h": 1.2, "sill_frac": 0.28, "style": "double_hung",
        })
        ws, hs, ss = _ARCH_WIN_SCALE.get(arch_style, (1.0, 1.0, 0.0))
        win_w    = min(spec["w"] * ws, wall_len * 0.40)
        win_h    = spec["h"] * hs
        win_sill = base_y + floor_h * max(0.08, spec["sill_frac"] + ss)
        _top_max = base_y + floor_h - 0.2
        if win_sill + win_h > _top_max:
            win_h = max(0.3, _top_max - win_sill)
        if win_h < 0.3 or win_w < 0.3:
            return

        # Place multiple windows on long side walls (one per ~2.8m of wall length)
        n_wins = max(1, min(4, int(wall_len / 2.8)))
        for i in range(n_wins):
            t = (i + 0.5) / n_wins
            wcx = s[0] + t * (e[0] - s[0])
            wcz = s[1] + t * (e[1] - s[1])
            # Re-probe per bay: a long side wall commonly runs past two or three
            # different rooms, and sizing the whole wall from the single room
            # _find_adj_room happened to hit made every opening on it identical.
            bay = self._room_at_wall_frac(wall, rooms, lvl, -nx, -nz, t) if wall is not None else None
            bay_type = bay.type if bay is not None else rtype
            if bay_type in _NO_WIN_TYPES:
                continue
            b_w, b_h, b_sill_frac, b_style = self._room_window_spec(
                bay_type, arch_style, 0.38, 0.50, floor_h,
            )
            b_w = min(b_w, wall_len * 0.40)
            b_sill = base_y + floor_h * b_sill_frac
            if b_sill + b_h > _top_max:
                b_h = max(0.3, _top_max - b_sill)
            if b_h < 0.3 or b_w < 0.3:
                continue
            self._add_styled_window(
                meshes, wcx, wcz, b_sill, b_h, b_w,
                ux, uz, nx, nz, fo, win_color, trim_color, b_style, lvl,
            )

    def _add_patio_door(
        self, meshes, s, e, dx, dz, ux, uz, nx, nz,
        wall_len, base_y, floor_h, fo, win_color, trim_color, lvl,
    ):
        """Sliding glass patio door — back wall, living/dining rooms."""
        pd_w = min(2.0, wall_len * 0.55)
        pd_h = floor_h * 0.82
        hw   = pd_w / 2
        ft   = 0.06
        wcx  = (s[0] + e[0]) / 2
        wcz  = (s[1] + e[1]) / 2

        meshes.append({
            "element_id": f"patio_{uuid.uuid4().hex[:5]}",
            "element_type": "window",
            "vertices": [
                [wcx - ux*hw + nx*fo, base_y,          wcz - uz*hw + nz*fo],
                [wcx + ux*hw + nx*fo, base_y,          wcz + uz*hw + nz*fo],
                [wcx + ux*hw + nx*fo, base_y + pd_h,   wcz + uz*hw + nz*fo],
                [wcx - ux*hw + nx*fo, base_y + pd_h,   wcz - uz*hw + nz*fo],
            ],
            "faces": [[0, 1, 2], [0, 2, 3], [2, 1, 0], [3, 2, 0]],
            "level": 0, "color": win_color,
        })
        for fv, ff in self._frame_quads(wcx, wcz, base_y, pd_h, pd_w, ux, uz, nx, nz, fo, ft):
            meshes.append({
                "element_id": f"patio_frm_{uuid.uuid4().hex[:5]}",
                "element_type": "window_frame",
                "vertices": fv, "faces": ff,
                "level": 0, "color": trim_color,
            })
        # Center rail between two sliding panels
        rail_t = 0.04
        meshes.append({
            "element_id": f"patio_rail_{uuid.uuid4().hex[:5]}",
            "element_type": "window_frame",
            "vertices": [
                [wcx - ux*rail_t + nx*fo, base_y,        wcz - uz*rail_t + nz*fo],
                [wcx + ux*rail_t + nx*fo, base_y,        wcz + uz*rail_t + nz*fo],
                [wcx + ux*rail_t + nx*fo, base_y + pd_h, wcz + uz*rail_t + nz*fo],
                [wcx - ux*rail_t + nx*fo, base_y + pd_h, wcz - uz*rail_t + nz*fo],
            ],
            "faces": [[0, 1, 2], [0, 2, 3], [2, 1, 0], [3, 2, 0]],
            "level": 0, "color": trim_color,
        })

    def _frame_quads(self, wcx, wcz, sill, win_h, win_w, ux, uz, nx, nz, fo, ft):
        hw  = win_w / 2
        top = sill + win_h
        return [
            ([  # Bottom bar
                [wcx - ux*hw + nx*fo, sill,      wcz - uz*hw + nz*fo],
                [wcx + ux*hw + nx*fo, sill,      wcz + uz*hw + nz*fo],
                [wcx + ux*hw + nx*fo, sill + ft, wcz + uz*hw + nz*fo],
                [wcx - ux*hw + nx*fo, sill + ft, wcz - uz*hw + nz*fo],
            ], [[0,1,2],[0,2,3]]),
            ([  # Top bar
                [wcx - ux*hw + nx*fo, top - ft, wcz - uz*hw + nz*fo],
                [wcx + ux*hw + nx*fo, top - ft, wcz + uz*hw + nz*fo],
                [wcx + ux*hw + nx*fo, top,      wcz + uz*hw + nz*fo],
                [wcx - ux*hw + nx*fo, top,      wcz - uz*hw + nz*fo],
            ], [[0,1,2],[0,2,3]]),
        ]
