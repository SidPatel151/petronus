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
from typing import List, Dict, Any, Optional
from app.models.schemas import Wall, Level
from app.constants import FACADE_COLORS as MATERIAL_FACADE_COLORS

WINDOW_COLOR = "#7dd3fc"


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
    ) -> List[Dict]:
        style = neighbor_style or {}
        brief = design_brief or {}
        floor_h = 3.0
        stories = len(levels)
        facade_color = style.get("facade_color", "#d6cbb8")
        win_color = style.get("window_color", WINDOW_COLOR)
        band_color = self._darken(facade_color, 0.75)
        balcony_color = self._darken(facade_color, 0.65)

        # ── Resolve arch style — drives geometry decisions ──────────────────
        arch_style = style.get("dominant_arch_style", "modern")

        # Brief overrides drive visual character to match neighbors
        window_ratio  = min(float(brief.get("window_ratio") or style.get("window_ratio", 0.35)), 0.55)
        balcony_depth = 0.0  # disabled — residential buildings don't get balconies
        bal_every_n   = int(brief.get("balcony_every_n_floors") or style.get("balcony_every_n_floors") or 1)
        add_bands     = bool(brief.get("horizontal_bands", style.get("horizontal_bands", True)))

        # ── Arch style overrides ─────────────────────────────────────────────
        face_offset = 0.09  # base flush offset
        if arch_style in ("craftsman", "victorian", "tudor"):
            # Deep facade relief, taller bands, narrow windows
            face_offset = 0.15
            band_h_frac = 0.30
            add_bands = True
        elif arch_style in ("modern", "minimalist", "contemporary", "contemporary_box"):
            # Clean flat facade, no spandrel bands, designed windows (not curtain wall)
            add_bands = False
            window_ratio = min(max(window_ratio, 0.40), 0.52)   # cap — not full glass wall
            band_h_frac = 0.0
        elif arch_style in ("colonial", "spanish", "mediterranean"):
            # Moderate bands, symmetrical windows, arched suggestion
            face_offset = 0.12
            band_h_frac = 0.22
            add_bands = True
        else:
            band_h_frac = 0.20

        # ── Window style from neighbors ─────────────────────────────────────
        window_style = style.get("window_style", "standard")
        if window_style == "tall_narrow":
            win_h_frac = 0.65
            win_w_cap  = 0.85
        elif window_style in ("wide", "large_horizontal"):
            win_h_frac = 0.38
            win_w_cap  = 2.4
        else:  # standard
            win_h_frac = 0.50
            win_w_cap  = 1.8

        meshes: List[Dict] = []
        ext_walls = [w for w in walls if w.is_exterior and w.level == 0]

        # Compute polygon centroid from exterior wall endpoints for correct outward normal
        poly_pts = [w.start for w in ext_walls]
        poly_cx = sum(p[0] for p in poly_pts) / len(poly_pts) if poly_pts else 0.0
        poly_cz = sum(p[1] for p in poly_pts) / len(poly_pts) if poly_pts else 0.0

        # ── Entry door rules ─────────────────────────────────────────────────
        # Front face = wall(s) with minimum average Z (street-facing in local coords).
        # Only ONE exterior door per building, placed on the front face.
        is_gabled_style = 'classic' in arch_style or 'gabled' in arch_style
        front_face_z = (min((w.start[1] + w.end[1]) / 2 for w in ext_walls)
                        if ext_walls else 0.0)
        # For gabled (Victorian/SFR porch), door sill matches porch deck height.
        if is_gabled_style and stories >= 1:
            _porch_h = min(1.52, stories * floor_h * 0.35)
            _step_rise = 0.19
            _n_steps = max(2, round(_porch_h / _step_rise))
            entry_sill_y = _n_steps * _step_rise
        else:
            entry_sill_y = 0.0
        door_placed = False   # one door total per building

        for wall in ext_walls:
            s, e = wall.start, wall.end
            dx, dz = e[0] - s[0], e[1] - s[1]
            wall_len = math.sqrt(dx * dx + dz * dz)
            if wall_len < 1.5:
                continue

            ux, uz = dx / wall_len, dz / wall_len
            nx, nz = uz, -ux  # outward normal (assumes CCW polygon)
            # Verify: normal must point AWAY from polygon centroid
            mid_x = (s[0] + e[0]) / 2
            mid_z = (s[1] + e[1]) / 2
            if nx * (mid_x - poly_cx) + nz * (mid_z - poly_cz) < 0:
                nx, nz = -nx, -nz  # polygon is CW — flip to outward

            for lvl in range(stories):
                base_y = lvl * floor_h

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

                    # Craftsman/Victorian: add a second thin accent strip above the band
                    if arch_style in ("craftsman", "victorian"):
                        accent_y = base_y + bh + 0.05
                        accent_h = 0.06
                        acc_verts = [
                            [s[0] + nx * fo, accent_y,          s[1] + nz * fo],
                            [e[0] + nx * fo, accent_y,          e[1] + nz * fo],
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

                # ── Windows ──────────────────────────────────────────────
                win_spacing = max(1.4, 2.8 * (1.0 - window_ratio))
                num_windows = max(1, int(wall_len / win_spacing))
                # Hard cap: residential houses shouldn't have a row of 6+ windows
                is_sfr_style = 'classic' in arch_style or 'gabled' in arch_style
                num_windows = min(num_windows, 2 if is_sfr_style else 3)
                raw_win_w   = wall_len / num_windows * window_ratio * 2.0
                win_w       = max(0.55, min(raw_win_w, win_w_cap))
                win_h       = floor_h * win_h_frac * (0.8 + window_ratio * 0.4)
                win_sill    = base_y + floor_h * (0.28 - window_ratio * 0.05)

                # Pre-compute front-face status so we can skip windows over the door.
                _wall_mid_z = (s[1] + e[1]) / 2
                _is_front = _wall_mid_z <= front_face_z + 0.5

                for i in range(num_windows):
                    t = (i + 0.5) / num_windows

                    # Skip any window whose centre would land on the entry door zone.
                    if lvl == 0 and _is_front and not door_placed:
                        _t_door = 0.25
                        _door_w = 1.05
                        _clearance = (_door_w / 2 + win_w / 2 + 0.10) / wall_len
                        if abs(t - _t_door) < _clearance:
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

                    # Window frame — thicker for traditional styles
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
                    t_door = 0.25
                    dcx = s[0] + t_door * dx
                    dcz = s[1] + t_door * dz
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

        return meshes

    # ── Flat parapet (original logic, extracted) ──────────────────────────────
    def _add_flat_parapet(self, meshes, massing_option, stories, floor_h, facade_color):
        roof_y = stories * floor_h
        par_h  = 0.65
        par_t  = 0.20
        footprint = massing_option.get("footprint", [])
        n_pts = len(footprint)
        if n_pts < 3:
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

        roof_y = stories * floor_h
        n = n_pts - 1 if (footprint[0] == footprint[-1]) else n_pts
        pts = [[footprint[i][0], footprint[i][1]] for i in range(n)]

        # Bounding box → determine long axis for ridge
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
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
