"""
FacadeGenerator
Windows, balconies, floor bands, top-floor setback, roof parapet.
All Y coordinates are absolute local meters (lvl * floor_h).
"""
import math
import uuid
from typing import List, Dict, Any, Optional
from app.models.schemas import Wall, Level

MATERIAL_FACADE_COLORS = {
    "brick":    "#b5651d",
    "concrete": "#9ca3af",
    "glass":    "#bfdbfe",
    "wood":     "#a67c52",
    "stone":    "#b8a99a",
    "metal":    "#94a3b8",
    "stucco":   "#d6cbb8",
    "plaster":  "#e8dcc8",
}
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

        # Estimate width/depth from bounding box of geometry
        try:
            coords = b.get("geometry", {}).get("coordinates", [[]])[0]
            if len(coords) >= 3:
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                # degrees → rough meters
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

        # Brief overrides drive visual character to match neighbors
        window_ratio   = float(brief.get("window_ratio")   or style.get("window_ratio",   0.35))
        balcony_depth  = float(brief.get("balcony_depth_m") or style.get("balcony_depth_m", 1.0))
        bal_every_n    = int(brief.get("balcony_every_n_floors") or style.get("balcony_every_n_floors") or 1)
        add_bands      = bool(brief.get("horizontal_bands", style.get("horizontal_bands", True)))

        meshes: List[Dict] = []
        ext_walls = [w for w in walls if w.is_exterior and w.level == 0]

        for wall in ext_walls:
            s, e = wall.start, wall.end
            dx, dz = e[0] - s[0], e[1] - s[1]
            wall_len = math.sqrt(dx * dx + dz * dz)
            if wall_len < 1.5:
                continue

            ux, uz = dx / wall_len, dz / wall_len
            # Outward normal for CCW Shapely polygon: rotate wall direction +90° CW
            nx, nz = uz, -ux
            face_offset = 0.09  # flush with outer wall face

            for lvl in range(stories):
                base_y = lvl * floor_h

                # ── Horizontal floor band (spandrel) — skip if brief says no bands ──
                if add_bands:
                    band_h = floor_h * 0.20
                    band_verts = [
                        [s[0] + nx * face_offset,          base_y,          s[1] + nz * face_offset],
                        [e[0] + nx * face_offset,          base_y,          e[1] + nz * face_offset],
                        [e[0] + nx * face_offset,          base_y + band_h, e[1] + nz * face_offset],
                        [s[0] + nx * face_offset,          base_y + band_h, s[1] + nz * face_offset],
                    ]
                    meshes.append({
                        "element_id": f"band_{lvl}_{uuid.uuid4().hex[:4]}",
                        "element_type": "floor_band",
                        "vertices": band_verts,
                        "faces": [[0, 1, 2], [0, 2, 3]],
                        "level": 0,
                        "color": band_color,
                    })

                # ── Windows — density driven by window_ratio from brief ──
                # window_ratio controls what fraction of wall length is glass
                win_spacing = max(1.4, 2.8 * (1.0 - window_ratio))
                num_windows = max(1, int(wall_len / win_spacing))
                win_w = min(wall_len / num_windows * window_ratio * 2.0, wall_len / num_windows * 0.80)
                win_w = max(0.6, min(win_w, 2.2))
                win_h = floor_h * (0.35 + window_ratio * 0.3)   # taller windows = more glass
                win_sill = base_y + floor_h * (0.28 - window_ratio * 0.05)

                for i in range(num_windows):
                    t = (i + 0.5) / num_windows
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

                    # Window frame
                    ft = 0.04
                    for fv, ff in self._frame_quads(wcx, wcz, win_sill, win_h, win_w, ux, uz, nx, nz, face_offset, ft):
                        meshes.append({
                            "element_id": f"frm_{uuid.uuid4().hex[:6]}",
                            "element_type": "window_frame",
                            "vertices": fv, "faces": ff,
                            "level": 0, "color": "#1e293b",
                        })

                # ── Door on ground floor only ──
                if lvl == 0 and wall_len >= 2.0:
                    door_w = 1.05
                    door_h = 2.15
                    # Place door at 1/4 of wall length (not center, to avoid conflicting with windows)
                    t_door = 0.25
                    dcx = s[0] + t_door * dx
                    dcz = s[1] + t_door * dz
                    hdw = door_w / 2
                    door_sill = base_y
                    door_fo = face_offset + 0.01
                    # Door panel
                    meshes.append({
                        "element_id": f"door_{uuid.uuid4().hex[:6]}",
                        "element_type": "door",
                        "vertices": [
                            [dcx - ux*hdw + nx*door_fo, door_sill,            dcz - uz*hdw + nz*door_fo],
                            [dcx + ux*hdw + nx*door_fo, door_sill,            dcz + uz*hdw + nz*door_fo],
                            [dcx + ux*hdw + nx*door_fo, door_sill + door_h,   dcz + uz*hdw + nz*door_fo],
                            [dcx - ux*hdw + nx*door_fo, door_sill + door_h,   dcz - uz*hdw + nz*door_fo],
                        ],
                        "faces": [[0, 1, 2], [0, 2, 3], [2, 1, 0], [3, 2, 0]],
                        "level": 0,
                        "color": "#7c5c3a",
                    })
                    # Door frame
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

                # ── Balconies — only on floors matching bal_every_n, skip if depth=0 ──
                if lvl > 0 and balcony_depth > 0 and (lvl % bal_every_n == 0):
                    bal_depth = balcony_depth
                    bal_h = 0.12       # slab thickness
                    rail_h = 0.9       # railing height
                    rail_t = 0.04
                    bal_y = base_y + floor_h * 0.05  # slab sits just above floor line
                    proj = face_offset + bal_depth

                    # Split wall into per-unit balcony bays
                    bay_w = min(3.2, wall_len)
                    n_bays = max(1, int(wall_len / bay_w))
                    for b in range(n_bays):
                        t0 = b / n_bays
                        t1 = (b + 1) / n_bays
                        margin = 0.25
                        bx0 = s[0] + (t0 * wall_len + margin) * ux
                        bz0 = s[1] + (t0 * wall_len + margin) * uz
                        bx1 = s[0] + (t1 * wall_len - margin) * ux
                        bz1 = s[1] + (t1 * wall_len - margin) * uz

                        # Slab
                        meshes.append({
                            "element_id": f"bal_slab_{uuid.uuid4().hex[:5]}",
                            "element_type": "balcony",
                            "level": 0,
                            "color": balcony_color,
                            "vertices": [
                                [bx0 + nx*face_offset, bal_y,        bz0 + nz*face_offset],
                                [bx1 + nx*face_offset, bal_y,        bz1 + nz*face_offset],
                                [bx1 + nx*proj,        bal_y,        bz1 + nz*proj],
                                [bx0 + nx*proj,        bal_y,        bz0 + nz*proj],
                                [bx0 + nx*face_offset, bal_y+bal_h,  bz0 + nz*face_offset],
                                [bx1 + nx*face_offset, bal_y+bal_h,  bz1 + nz*face_offset],
                                [bx1 + nx*proj,        bal_y+bal_h,  bz1 + nz*proj],
                                [bx0 + nx*proj,        bal_y+bal_h,  bz0 + nz*proj],
                            ],
                            "faces": [
                                [0,1,2],[0,2,3],           # bottom
                                [4,6,5],[4,7,6],           # top
                                [0,4,5],[0,5,1],           # back
                                [2,6,7],[2,7,3],           # front
                                [0,3,7],[0,7,4],           # left
                                [1,5,6],[1,6,2],           # right
                            ],
                        })

                        # Front railing
                        rx = (bx0 + bx1) / 2
                        rz = (bz0 + bz1) / 2
                        rlen = math.sqrt((bx1-bx0)**2 + (bz1-bz0)**2)
                        rhw = rlen / 2
                        meshes.append({
                            "element_id": f"bal_rail_{uuid.uuid4().hex[:5]}",
                            "element_type": "balcony_rail",
                            "level": 0,
                            "color": "#334155",
                            "vertices": [
                                [rx - ux*rhw + nx*proj,      bal_y+bal_h,          rz - uz*rhw + nz*proj],
                                [rx + ux*rhw + nx*proj,      bal_y+bal_h,          rz + uz*rhw + nz*proj],
                                [rx + ux*rhw + nx*proj,      bal_y+bal_h+rail_h,   rz + uz*rhw + nz*proj],
                                [rx - ux*rhw + nx*proj,      bal_y+bal_h+rail_h,   rz - uz*rhw + nz*proj],
                                [rx - ux*rhw + nx*(proj-rail_t), bal_y+bal_h,      rz - uz*rhw + nz*(proj-rail_t)],
                                [rx + ux*rhw + nx*(proj-rail_t), bal_y+bal_h,      rz + uz*rhw + nz*(proj-rail_t)],
                                [rx + ux*rhw + nx*(proj-rail_t), bal_y+bal_h+rail_h, rz + uz*rhw + nz*(proj-rail_t)],
                                [rx - ux*rhw + nx*(proj-rail_t), bal_y+bal_h+rail_h, rz - uz*rhw + nz*(proj-rail_t)],
                            ],
                            "faces": [[0,1,2],[0,2,3],[5,4,7],[5,7,6],[3,2,6],[3,6,7],[0,3,7],[0,7,4],[1,5,6],[1,6,2]],
                        })

        # ── Top-floor setback (penthouse effect) ──────────────────────────
        if stories >= 2:
            self._add_setback_cap(meshes, massing_option, stories, floor_h, facade_color)

        # ── Roof parapet ──────────────────────────────────────────────────
        roof_y = stories * floor_h
        par_h = 0.65
        par_t = 0.20
        footprint = massing_option.get("footprint", [])
        n_pts = len(footprint)
        if n_pts >= 3:
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

        return meshes

    def _add_setback_cap(self, meshes, massing_option, stories, floor_h, color):
        """Inset the top floor slightly to create a penthouse/setback effect."""
        footprint = massing_option.get("footprint", [])
        n_pts = len(footprint)
        if n_pts < 3:
            return
        inset = 0.8  # meters setback on each side
        top_base = (stories - 1) * floor_h
        n = n_pts - 1 if (footprint[n_pts-1] == footprint[0]) else n_pts

        # Compute centroid for inward offset direction
        cx = sum(footprint[i][0] for i in range(n)) / n
        cz = sum(footprint[i][1] for i in range(n)) / n

        inner = []
        for i in range(n):
            x, z = footprint[i][0], footprint[i][1]
            dx, dz = cx - x, cz - z
            d = math.sqrt(dx*dx + dz*dz) or 1
            inner.append([x + dx/d * inset, z + dz/d * inset])

        # Vertical faces bridging original footprint → inset at top_base level
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
        """Darken a hex color by factor (0–1)."""
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
        hw = win_w / 2
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
