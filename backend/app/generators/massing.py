"""
MassingGenerator
Produces 3 massing options centered at local origin (0,0) in meters.
Uses neighbor building footprints to:
  - Derive realistic width/depth from adjacent buildings
  - Generate floor band meshes so floors are visible
  - Show red overlap mesh where new footprint overlaps existing neighbors
  - Show green footprint outline on ground
"""
import math
import uuid
from typing import List, Dict, Any, Tuple, Optional
from shapely.geometry import shape, Polygon, box, MultiPolygon
from shapely.affinity import translate as shp_translate, scale as shp_scale
from shapely.ops import transform, unary_union
import pyproj

from app.models.schemas import BuildingModel, ProjectSpec, SiteContext, Level, Mesh
from app.constants import BuildingUse

MATERIAL_COLORS = {
    "wood":     "#8B6914",
    "steel":    "#6B7B8D",
    "concrete": "#8C8C8C",
}


class MassingGenerator:

    def generate(
        self,
        spec: ProjectSpec,
        site_ctx: SiteContext,
        neighbor_buildings: List[Dict] = [],
        design_brief: Optional[Dict] = None,
        style: Optional[str] = None,
    ) -> Tuple[List[Dict], List[Level]]:
        envelope = shape(site_ctx.buildable_envelope_2d)

        # Project everything to Web Mercator (meters)
        proj_fwd = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
        envelope_m = transform(proj_fwd, envelope)

        # Center at origin for Three.js
        cx_env = (envelope_m.bounds[0] + envelope_m.bounds[2]) / 2
        cy_env = (envelope_m.bounds[1] + envelope_m.bounds[3]) / 2
        envelope_local = shp_translate(envelope_m, -cx_env, -cy_env)

        # Convert neighbor buildings to local meter polygons
        neighbor_local = self._neighbors_to_local(neighbor_buildings, proj_fwd, cx_env, cy_env)

        # Analyze neighbors for realistic dimensions
        nav = self._analyze_neighbors(neighbor_local)

        # Resolve target dims: brief > neighbors > envelope-derived
        brief = design_brief or {}
        brief_w = brief.get("width_m")
        brief_d = brief.get("depth_m")
        brief_shape = brief.get("shape", "rectangle")

        bounds = envelope_local.bounds
        env_w = bounds[2] - bounds[0]
        env_d = bounds[3] - bounds[1]

        target_w = brief_w or nav.get("avg_width_m") or (env_w * 0.75)
        target_d = brief_d or nav.get("avg_depth_m") or (env_d * 0.75)

        # Clamp to envelope (with setback)
        target_w = min(target_w, env_w * 0.90)
        target_d = min(target_d, env_d * 0.90)

        target_area_m2 = max(10, self._target_area_m2(spec))
        floor_height_m = max(0.1, spec.floor_to_floor_height_ft * 0.3048)
        stories = max(1, spec.stories)

        mat = getattr(spec.structural_system, 'value', str(spec.structural_system))
        mat_color = MATERIAL_COLORS.get(mat, "#94a3b8")

        terrain = site_ctx.terrain or {}
        grad_x = terrain.get("grad_x", 0.0)
        grad_z = terrain.get("grad_z", 0.0)

        _buse = getattr(spec, 'building_use', None)
        _is_sfr = _buse in (BuildingUse.single_family, BuildingUse.adu, 'single_family', 'adu')
        _is_adu = _buse in (BuildingUse.adu, 'adu')

        # ADU is always a flat-roof modern box — porch/stair code must never run.
        if _is_adu:
            style_val = 'modern_linear'
        else:
            # Resolve style: explicit arg → spec.style → building-use default.
            # Never fall back to brief_shape ('rectangle') as a style name.
            style_val = style or getattr(spec, 'style', None)
            if hasattr(style_val, 'value'):
                style_val = style_val.value
            if not style_val:
                style_val = 'classic_gabled' if _is_sfr else 'modern_linear'

        # ── Max lot coverage: house must not fill the whole parcel ──
        # CA residential: SFR ≤45%, ADU ≤75%, multi-family ≤60% of buildable envelope
        _max_coverage = 0.75 if _is_adu else (0.45 if _is_sfr else 0.60)
        _max_fp_m2 = max(20.0, envelope_local.area * _max_coverage)
        _max_total_area = _max_fp_m2 * stories
        target_area_m2 = min(target_area_m2, _max_total_area)

        if brief_shape == 'rectangle':
            options = [
                self._option_rectangle(envelope_local, target_w, target_d, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local, style_val, label="A", name="Narrow Rectangle", desc="Full-depth narrow rectangle — classic Victorian narrow-lot form"),
                self._option_rectangle(envelope_local, target_w * 0.85, target_d * 1.1, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local, style_val, label="B", name="Deep Narrow", desc="Slightly narrower and deeper — maximises rear yard setback"),
                self._option_rectangle(envelope_local, target_w, target_d * 0.85, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local, style_val, label="C", name="Compact Rectangle", desc="Shorter depth with larger rear yard — good for light wells"),
            ]
        else:
            options = [
                self._option_l_shape(envelope_local, target_w, target_d, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local, style_val),
                self._option_stepped(envelope_local, target_w, target_d, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local, style_val),
                self._option_u_shape(envelope_local, target_w, target_d, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local, style_val),
            ]
        levels = self._build_levels(stories, spec.floor_to_floor_height_ft)
        return options, levels

    # ── Neighbor helpers ──────────────────────────────────────────────────

    def _neighbors_to_local(self, neighbor_buildings: List[Dict], proj_fwd, cx: float, cy: float) -> List[Polygon]:
        polys = []
        for b in neighbor_buildings:
            try:
                geom = shape(b.get("geometry", b))
                geom_m = transform(proj_fwd, geom)
                geom_local = shp_translate(geom_m, -cx, -cy)
                if geom_local.is_valid and not geom_local.is_empty:
                    if geom_local.geom_type == 'Polygon':
                        polys.append(geom_local)
                    elif geom_local.geom_type == 'MultiPolygon':
                        polys.extend(geom_local.geoms)
            except Exception:
                continue
        return polys

    def _analyze_neighbors(self, neighbor_local: List[Polygon]) -> Dict[str, Any]:
        if not neighbor_local:
            return {}
        widths, depths, areas = [], [], []
        for poly in neighbor_local:
            b = poly.bounds
            w = b[2] - b[0]
            d = b[3] - b[1]
            widths.append(w)
            depths.append(d)
            areas.append(poly.area)
        return {
            "count": len(neighbor_local),
            "avg_width_m": sum(widths) / len(widths),
            "avg_depth_m": sum(depths) / len(depths),
            "avg_area_m2": sum(areas) / len(areas),
        }

    # ── Option builders ───────────────────────────────────────────────────

    def _option_l_shape(self, envelope_local, tw, td, target_area_m2, stories, floor_height_m, priority, mat_color, grad_x, grad_z, neighbors, style='modern_linear') -> Dict:
        """L-shaped footprint: start with bounding rectangle, cut one rear corner."""
        base = envelope_local.buffer(-0.5)
        if base.is_empty:
            base = envelope_local
        target_fp_area = target_area_m2 / max(1, stories)
        scaled = self._fit_to_area(base, target_fp_area * 1.35)  # start larger so L has enough area
        b = scaled.bounds
        bw, bd = b[2] - b[0], b[3] - b[1]
        # Cut proportions vary by style: sculpted=smaller cut (chunkier), linear=larger cut (sleeker)
        if 'sculpted' in style:
            cut_w, cut_d = bw * 0.28, bd * 0.42
        elif 'linear' in style:
            cut_w, cut_d = bw * 0.52, bd * 0.38
        else:
            cut_w, cut_d = bw * 0.40, bd * 0.45
        cutout = box(b[2] - cut_w, b[3] - cut_d, b[2], b[3])
        footprint = scaled.difference(cutout)
        if footprint.is_empty or not footprint.is_valid or footprint.area < target_fp_area * 0.5:
            footprint = scaled  # fallback to rectangle if cut fails
        footprint = self._fit_to_area(footprint, target_fp_area)
        total_area = footprint.area * stories
        meshes = self._extrude_footprint(footprint, stories, floor_height_m, "massing_a", mat_color, grad_x, grad_z, style=style)
        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        return {
            "label": "A", "name": "L-Shape",
            "description": "L-shaped plan — defines front yard, efficient corner circulation",
            "footprint": list(footprint.exterior.coords),
            "total_area_m2": total_area, "stories": stories, "floor_height_m": floor_height_m,
            "meshes": meshes,
            "score": self._score(footprint, total_area, target_area_m2, priority),
        }

    def _option_stepped(self, envelope_local, tw, td, target_area_m2, stories, floor_height_m, priority, mat_color, grad_x, grad_z, neighbors, style='modern_linear') -> Dict:
        # Base floor = parcel shape scaled to target area; upper floors step back further
        base = envelope_local.buffer(-0.5)
        if base.is_empty:
            base = envelope_local
        target_fp_area = target_area_m2 / max(1, stories)
        footprint = self._fit_to_area(base, target_fp_area)
        upper_footprint = self._fit_to_area(base, target_fp_area * 0.7)
        if upper_footprint.is_empty:
            upper_footprint = footprint

        # Generate lower + upper meshes separately
        lower_stories = max(1, stories // 2)
        upper_stories = stories - lower_stories
        meshes = self._extrude_footprint(footprint, lower_stories, floor_height_m, "massing_b_low", mat_color, grad_x, grad_z, style='modern_linear')  # lower always flat
        if upper_stories > 0:
            y_offset = lower_stories * floor_height_m
            upper_meshes = self._extrude_footprint(upper_footprint, upper_stories, floor_height_m, "massing_b_up", mat_color, grad_x, grad_z, style=style)
            # Shift upper meshes up by lower floor height
            for m in upper_meshes:
                if "vertices" in m:
                    m["vertices"] = [[v[0], v[1] + y_offset, v[2]] for v in m["vertices"]]
            meshes += upper_meshes
        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        total_area = footprint.area * lower_stories + upper_footprint.area * upper_stories
        return {
            "label": "B", "name": "Stepped Massing",
            "description": "Upper floors set back — terraces + varied roofline",
            "footprint": list(footprint.exterior.coords),
            "total_area_m2": total_area, "stories": stories, "floor_height_m": floor_height_m,
            "meshes": meshes,
            "score": self._score(footprint, total_area, target_area_m2, priority),
        }

    def _option_u_shape(self, envelope_local, tw, td, target_area_m2, stories, floor_height_m, priority, mat_color, grad_x, grad_z, neighbors, style='modern_linear') -> Dict:
        base = envelope_local.buffer(-0.5)
        if base.is_empty:
            base = envelope_local
        target_fp_area = target_area_m2 / max(1, stories)
        scaled = self._fit_to_area(base, target_fp_area * 1.35)
        b = scaled.bounds
        bw = b[2] - b[0]
        bd = b[3] - b[1]
        # Court proportions vary by style: sculpted=narrow court (more mass), linear=wide open court
        if 'sculpted' in style:
            court_w, court_d = bw * 0.28, bd * 0.38
        elif 'linear' in style:
            court_w, court_d = bw * 0.52, bd * 0.32
        else:
            court_w, court_d = bw * 0.40, bd * 0.35
        cx = (b[0] + b[2]) / 2
        cutout = box(cx - court_w/2, b[1], cx + court_w/2, b[1] + court_d)
        footprint = scaled.difference(cutout)
        if footprint.is_empty or not footprint.is_valid:
            footprint = scaled
        footprint = self._fit_to_area(footprint, target_fp_area)
        total_area = footprint.area * stories
        meshes = self._extrude_footprint(footprint, stories, floor_height_m, "massing_c", mat_color, grad_x, grad_z, style=style)
        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        return {
            "label": "C", "name": "U-Shape / Forecourt",
            "description": "U-shape with entry courtyard — classic apartment typology",
            "footprint": list(footprint.exterior.coords),
            "total_area_m2": total_area, "stories": stories, "floor_height_m": floor_height_m,
            "meshes": meshes,
            "score": self._score(footprint, total_area, target_area_m2, priority),
        }

    def _option_rectangle(self, envelope_local, tw, td, target_area_m2, stories, floor_height_m,
                          priority, mat_color, grad_x, grad_z, neighbors, style='classic_gabled',
                          label="A", name="Rectangle", desc="Rectangular footprint") -> Dict:
        """Simple rectangular footprint — used for Victorian narrow-lot and other brief_shape='rectangle' archetypes."""
        base = envelope_local.buffer(-0.5)
        if base.is_empty:
            base = envelope_local
        target_fp_area = target_area_m2 / max(1, stories)
        eb = base.bounds
        # Build an explicit rectangle from tw × td, centered in the envelope
        cx = (eb[0] + eb[2]) / 2
        cz = (eb[1] + eb[3]) / 2
        half_w = min(tw / 2, (eb[2] - eb[0]) / 2 * 0.95)
        half_d = min(td / 2, (eb[3] - eb[1]) / 2 * 0.95)
        rect = box(cx - half_w, cz - half_d, cx + half_w, cz + half_d)
        clipped = base.intersection(rect)
        if clipped.is_empty or not hasattr(clipped, 'exterior'):
            clipped = self._fit_to_area(base, target_fp_area)
        footprint = self._fit_to_area(clipped, target_fp_area)
        total_area = footprint.area * stories
        meshes = self._extrude_footprint(footprint, stories, floor_height_m, f"massing_{label.lower()}", mat_color, grad_x, grad_z, style=style)
        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        return {
            "label": label, "name": name,
            "description": desc,
            "footprint": list(footprint.exterior.coords),
            "total_area_m2": total_area, "stories": stories, "floor_height_m": floor_height_m,
            "meshes": meshes,
            "score": self._score(footprint, total_area, target_area_m2, priority),
        }

    # ── Mesh builders ─────────────────────────────────────────────────────

    def _ground_y(self, x: float, z: float, grad_x: float, grad_z: float) -> float:
        return x * grad_x + z * grad_z

    def _extrude_footprint(self, footprint: Polygon, stories: int, floor_height_m: float,
                           prefix: str, color: str = "#94a3b8",
                           grad_x: float = 0.0, grad_z: float = 0.0,
                           style: str = 'modern_linear') -> List[Dict]:
        coords = list(footprint.exterior.coords[:-1])
        if not coords:
            return []
        n = len(coords)
        total_height = stories * floor_height_m
        meshes = []

        # ── Main shell (transparent-ish massing) ──
        vertices = []
        faces = []
        for x, z in coords:
            base_y = self._ground_y(x, z, grad_x, grad_z)
            vertices.append([x, base_y, z])
        for x, z in coords:
            base_y = self._ground_y(x, z, grad_x, grad_z)
            vertices.append([x, base_y + total_height, z])

        for i in range(n):
            j = (i + 1) % n
            faces.append([i, j, j + n])
            faces.append([i, j + n, i + n])

        # Top cap
        cx = sum(v[0] for v in vertices[n:]) / n
        cy_top = sum(v[1] for v in vertices[n:]) / n
        cz = sum(v[2] for v in vertices[n:]) / n
        center_idx = len(vertices)
        vertices.append([cx, cy_top, cz])
        for i in range(n):
            j = (i + 1) % n
            faces.append([n + i, center_idx, n + j])

        meshes.append({
            "element_id": f"{prefix}_mass",
            "element_type": "massing",
            "vertices": vertices, "faces": faces,
            "level": 0, "color": color,
        })

        # ── Roof — three distinct forms per style ──
        roof_height_rel = stories * floor_height_m
        is_gabled   = 'classic' in style or 'gabled' in style
        is_sculpted = 'sculpted' in style

        if is_gabled:
            # ── Gabled roof with ridge line — two slopes, triangular gable ends ──
            b = footprint.bounds
            bw = b[2] - b[0]
            bd = b[3] - b[1]
            # 12/12 pitch (45°) — steep Victorian/American-traditional roof
            # peak_height = half-span × tan(45°) = half-span × 1.0 = span × 0.5
            peak_height = min(bw, bd) * 0.5
            cx_b = (b[0] + b[2]) / 2
            cz_b = (b[1] + b[3]) / 2

            # Ridge runs along the LONG axis — same logic as the old frontend GableRoofMesh
            # but done here in the backend so it uses the real footprint coordinates.
            if bw >= bd:
                r0 = [b[0], self._ground_y(b[0], cz_b, grad_x, grad_z) + roof_height_rel + peak_height, cz_b]
                r1 = [b[2], self._ground_y(b[2], cz_b, grad_x, grad_z) + roof_height_rel + peak_height, cz_b]
            else:
                r0 = [cx_b, self._ground_y(cx_b, b[1], grad_x, grad_z) + roof_height_rel + peak_height, b[1]]
                r1 = [cx_b, self._ground_y(cx_b, b[3], grad_x, grad_z) + roof_height_rel + peak_height, b[3]]

            eave_verts = []
            for x, z in coords:
                gy = self._ground_y(x, z, grad_x, grad_z)
                eave_verts.append([x, gy + roof_height_rel, z])

            n_eave = len(eave_verts)
            R0, R1 = n_eave, n_eave + 1
            roof_verts = eave_verts + [r0, r1]
            roof_faces = []

            for i in range(n_eave):
                j = (i + 1) % n_eave
                ev_i, ev_j = eave_verts[i], eave_verts[j]
                d0i = (ev_i[0]-r0[0])**2 + (ev_i[2]-r0[2])**2
                d1i = (ev_i[0]-r1[0])**2 + (ev_i[2]-r1[2])**2
                d0j = (ev_j[0]-r0[0])**2 + (ev_j[2]-r0[2])**2
                d1j = (ev_j[0]-r1[0])**2 + (ev_j[2]-r1[2])**2
                near0_i = d0i <= d1i
                near0_j = d0j <= d1j
                if near0_i and near0_j:
                    roof_faces.extend([[i, j, R0], [R0, j, i]])
                elif not near0_i and not near0_j:
                    roof_faces.extend([[i, j, R1], [R1, j, i]])
                else:
                    Ri = R0 if near0_i else R1
                    Rj = R0 if near0_j else R1
                    roof_faces.extend([[i, j, Ri], [Ri, j, i], [j, Rj, Ri], [Ri, Rj, j]])

            meshes.append({
                "element_id": f"{prefix}_roof",
                "element_type": "roof",
                "vertices": roof_verts, "faces": roof_faces,
                "level": stories - 1, "color": "#374151",
            })

            # ── Front porch + staircase — American traditional gabled houses ──
            # Placed on the min-Z face (garage-door / street face per Victorian layout).
            porch_w    = bw * 0.65          # 65% of building width
            porch_d    = 2.4                # metres projection in front
            porch_h    = min(1.52, roof_height_rel * 0.35)  # ~5 ft raised entry
            step_rise  = 0.19               # metres per step (≈ 7.5 in)
            step_run   = 0.28               # metres per step (≈ 11 in)
            n_steps    = max(2, round(porch_h / step_rise))
            porch_floor_h = n_steps * step_rise

            px0 = cx_b - porch_w / 2
            px1 = cx_b + porch_w / 2
            # Front face of building is at b[1] (minimum Z); porch extends outward
            porch_z1 = b[1]
            porch_z0 = b[1] - porch_d
            base_porch = self._ground_y(cx_b, porch_z0, grad_x, grad_z)

            # Porch deck slab (flat platform at porch_floor_h)
            py_bot = base_porch
            py_top = base_porch + porch_floor_h
            porch_verts = [
                [px0, py_bot, porch_z0], [px1, py_bot, porch_z0],
                [px1, py_bot, porch_z1], [px0, py_bot, porch_z1],
                [px0, py_top, porch_z0], [px1, py_top, porch_z0],
                [px1, py_top, porch_z1], [px0, py_top, porch_z1],
            ]
            porch_faces = [
                [4, 5, 6], [4, 6, 7],   # top
                [0, 4, 7], [0, 7, 3],   # left side
                [1, 2, 6], [1, 6, 5],   # right side
                [0, 1, 5], [0, 5, 4],   # front face (outward)
            ]
            meshes.append({
                "element_id": f"{prefix}_porch",
                "element_type": "porch",
                "vertices": porch_verts, "faces": porch_faces,
                "level": 0, "color": "#c8a87a",
            })

            # Stair steps — extend outward from porch front edge
            sw0 = cx_b - porch_w * 0.45
            sw1 = cx_b + porch_w * 0.45
            for s in range(n_steps):
                s_z1 = porch_z0 - step_run * (n_steps - 1 - s)
                s_z0 = s_z1 - step_run
                s_y_top = base_porch + step_rise * (s + 1)
                step_verts = [
                    [sw0, base_porch, s_z0], [sw1, base_porch, s_z0],
                    [sw1, base_porch, s_z1], [sw0, base_porch, s_z1],
                    [sw0, s_y_top,    s_z0], [sw1, s_y_top,    s_z0],
                    [sw1, s_y_top,    s_z1], [sw0, s_y_top,    s_z1],
                ]
                step_faces = [
                    [4, 5, 6], [4, 6, 7],   # top tread
                    [0, 1, 5], [0, 5, 4],   # front riser
                    [0, 4, 7], [0, 7, 3],   # left side
                    [1, 2, 6], [1, 6, 5],   # right side
                ]
                meshes.append({
                    "element_id": f"{prefix}_step_{s}",
                    "element_type": "porch",
                    "vertices": step_verts, "faces": step_faces,
                    "level": 0, "color": "#b8996a",
                })

            # ── Porch columns (4 corners) ─────────────────────────────────
            col_hw   = 0.14          # half-width of column (28cm square)
            col_gap  = 0.22          # inset from porch edge so column sits inside rail
            col_y0   = base_porch + porch_floor_h
            canopy_y = col_y0 + 2.2  # 7.2ft clear head-room above porch deck
            for (col_x, col_z) in [(px0 + col_gap, porch_z0 + col_gap),
                                    (px1 - col_gap, porch_z0 + col_gap),
                                    (px0 + col_gap, porch_z1 - col_gap),
                                    (px1 - col_gap, porch_z1 - col_gap)]:
                cv = [
                    [col_x-col_hw, col_y0,  col_z-col_hw],
                    [col_x+col_hw, col_y0,  col_z-col_hw],
                    [col_x+col_hw, col_y0,  col_z+col_hw],
                    [col_x-col_hw, col_y0,  col_z+col_hw],
                    [col_x-col_hw, canopy_y, col_z-col_hw],
                    [col_x+col_hw, canopy_y, col_z-col_hw],
                    [col_x+col_hw, canopy_y, col_z+col_hw],
                    [col_x-col_hw, canopy_y, col_z+col_hw],
                ]
                cf = [[0,1,5],[0,5,4],[1,2,6],[1,6,5],
                      [2,3,7],[2,7,6],[3,0,4],[3,4,7]]
                meshes.append({
                    "element_id": f"{prefix}_col_{uuid.uuid4().hex[:4]}",
                    "element_type": "porch",
                    "vertices": cv, "faces": cf,
                    "level": 0, "color": "#f0ece4",
                })

            # ── Porch canopy slab (flat roof over porch) ─────────────────
            ct = 0.15   # slab thickness
            can_verts = [
                [px0 - 0.1, canopy_y,      porch_z0 - 0.1],
                [px1 + 0.1, canopy_y,      porch_z0 - 0.1],
                [px1 + 0.1, canopy_y,      porch_z1],
                [px0 - 0.1, canopy_y,      porch_z1],
                [px0 - 0.1, canopy_y + ct, porch_z0 - 0.1],
                [px1 + 0.1, canopy_y + ct, porch_z0 - 0.1],
                [px1 + 0.1, canopy_y + ct, porch_z1],
                [px0 - 0.1, canopy_y + ct, porch_z1],
            ]
            can_faces = [
                [4,5,6],[4,6,7],           # top face
                [0,4,7],[0,7,3],           # left
                [1,5,6],[1,6,2],           # right
                [0,1,5],[0,5,4],           # front
                [3,7,6],[3,6,2],           # back (flush with building wall)
                [0,3,2],[0,2,1],           # bottom face
            ]
            meshes.append({
                "element_id": f"{prefix}_porch_canopy",
                "element_type": "porch",
                "vertices": can_verts, "faces": can_faces,
                "level": 0, "color": "#7c5e3a",
            })

            # ── Porch railings (front + left side + right side) ──────────
            rail_y0  = base_porch + porch_floor_h + 0.05   # bottom of rail zone
            rail_y1  = base_porch + porch_floor_h + 0.92   # top rail height (36in)
            rail_t   = 0.05                                  # rail bar thickness
            post_hw  = 0.04                                  # baluster half-width

            def _box_mesh(ax0, ay0, az0, ax1, ay1, az1):
                return ([
                    [ax0,ay0,az0],[ax1,ay0,az0],[ax1,ay0,az1],[ax0,ay0,az1],
                    [ax0,ay1,az0],[ax1,ay1,az0],[ax1,ay1,az1],[ax0,ay1,az1],
                ], [
                    [4,5,6],[4,6,7],[0,3,2],[0,2,1],  # top + bottom
                    [0,4,7],[0,7,3],[1,2,6],[1,6,5],  # left + right
                    [0,1,5],[0,5,4],[3,7,6],[3,6,2],  # front + back
                ])

            def _add_rail_span(x0, z0, x1, z1, n_posts, tag):
                """Top rail, bottom rail, and n_posts+1 balusters along x0,z0→x1,z1."""
                # Axis: if x changes it's horizontal along X; if z changes, along Z
                if abs(x1 - x0) >= abs(z1 - z0):  # X-axis span
                    # Top rail bar
                    bv, bf = _box_mesh(x0, rail_y1 - rail_t, z0 - rail_t,
                                       x1, rail_y1,            z0 + rail_t)
                    meshes.append({"element_id": f"{prefix}_rt_{tag}", "element_type": "porch",
                                   "vertices": bv, "faces": bf, "level": 0, "color": "#c8b87a"})
                    # Bottom rail bar
                    bv, bf = _box_mesh(x0, rail_y0, z0 - rail_t,
                                       x1, rail_y0 + rail_t, z0 + rail_t)
                    meshes.append({"element_id": f"{prefix}_rb_{tag}", "element_type": "porch",
                                   "vertices": bv, "faces": bf, "level": 0, "color": "#c8b87a"})
                    for p in range(n_posts + 1):
                        t_p = p / max(1, n_posts)
                        px_p = x0 + t_p * (x1 - x0)
                        bv, bf = _box_mesh(px_p - post_hw, rail_y0, z0 - post_hw,
                                           px_p + post_hw, rail_y1, z0 + post_hw)
                        meshes.append({"element_id": f"{prefix}_rp_{tag}_{p}", "element_type": "porch",
                                       "vertices": bv, "faces": bf, "level": 0, "color": "#d4c89a"})
                else:  # Z-axis span
                    bv, bf = _box_mesh(x0 - rail_t, rail_y1 - rail_t, z0,
                                       x0 + rail_t, rail_y1,            z1)
                    meshes.append({"element_id": f"{prefix}_rt_{tag}", "element_type": "porch",
                                   "vertices": bv, "faces": bf, "level": 0, "color": "#c8b87a"})
                    bv, bf = _box_mesh(x0 - rail_t, rail_y0, z0,
                                       x0 + rail_t, rail_y0 + rail_t, z1)
                    meshes.append({"element_id": f"{prefix}_rb_{tag}", "element_type": "porch",
                                   "vertices": bv, "faces": bf, "level": 0, "color": "#c8b87a"})
                    for p in range(n_posts + 1):
                        t_p = p / max(1, n_posts)
                        pz_p = z0 + t_p * (z1 - z0)
                        bv, bf = _box_mesh(x0 - post_hw, rail_y0, pz_p - post_hw,
                                           x0 + post_hw, rail_y1, pz_p + post_hw)
                        meshes.append({"element_id": f"{prefix}_rp_{tag}_{p}", "element_type": "porch",
                                       "vertices": bv, "faces": bf, "level": 0, "color": "#d4c89a"})

            n_front = max(2, int(porch_w / 0.9))
            n_side  = max(1, int(porch_d / 0.9))
            _add_rail_span(px0 + col_gap, porch_z0, px1 - col_gap, porch_z0, n_front, "fr")
            _add_rail_span(px0, porch_z0 + col_gap, px0, porch_z1 - col_gap, n_side, "le")
            _add_rail_span(px1, porch_z0 + col_gap, px1, porch_z1 - col_gap, n_side, "ri")

        elif is_sculpted:
            # ── Mono-pitch shed roof — slopes low at front (min-Z), high at rear (max-Z) ──
            b_s = footprint.bounds
            z_min_s, z_max_s = b_s[1], b_s[3]
            z_range_s = max(z_max_s - z_min_s, 0.01)
            rise = (z_max_s - z_min_s) * 0.20   # ~11° mono-pitch slope

            shed_verts = []
            for x, z in coords:
                gy = self._ground_y(x, z, grad_x, grad_z)
                t = (z - z_min_s) / z_range_s
                shed_verts.append([x, gy + roof_height_rel + t * rise, z])

            # representative_point() is always inside the polygon — safe for L/U shapes
            rep = footprint.representative_point()
            rep_x, rep_z = rep.x, rep.y
            t_rep = (rep_z - z_min_s) / z_range_s
            rep_y = self._ground_y(rep_x, rep_z, grad_x, grad_z) + roof_height_rel + t_rep * rise
            ci_shed = len(shed_verts)
            shed_verts.append([rep_x, rep_y, rep_z])

            shed_faces = []
            n_s = len(coords)
            for i in range(n_s):
                j = (i + 1) % n_s
                shed_faces.append([i, j, ci_shed])
                shed_faces.append([ci_shed, j, i])  # double-sided

            meshes.append({
                "element_id": f"{prefix}_roof",
                "element_type": "roof",
                "vertices": shed_verts, "faces": shed_faces,
                "level": stories - 1, "color": "#1e293b",
            })

        else:
            # ── Flat roof with parapet walls (modern_linear) ──
            PARAPET_H = 0.7
            DECK_LIFT = 0.02  # sit 2cm above MassingShell top to eliminate z-fighting

            # Flat deck top face — fan from centroid so it works for any polygon shape
            deck_top_y = roof_height_rel + DECK_LIFT + 0.16
            deck_verts = []
            deck_faces = []
            for x, z in coords:
                gy = self._ground_y(x, z, grad_x, grad_z)
                deck_verts.append([x, gy + roof_height_rel + DECK_LIFT, z])  # bottom
            for x, z in coords:
                gy = self._ground_y(x, z, grad_x, grad_z)
                deck_verts.append([x, gy + deck_top_y, z])                   # top
            dcx = sum(v[0] for v in deck_verts[n:]) / n
            dcy = sum(v[1] for v in deck_verts[n:]) / n
            dcz = sum(v[2] for v in deck_verts[n:]) / n
            ci_d = len(deck_verts)
            deck_verts.append([dcx, dcy, dcz])
            for i in range(n):
                j = (i + 1) % n
                deck_faces.append([n+i, ci_d, n+j])
                deck_faces.append([ci_d, n+j, n+i])
            meshes.append({
                "element_id": f"{prefix}_roof",
                "element_type": "roof",
                "vertices": deck_verts, "faces": deck_faces,
                "level": stories - 1, "color": "#374151",
            })

            par_verts = []
            par_faces = []
            par_base_y = deck_top_y
            par_top_y  = par_base_y + PARAPET_H
            for x, z in coords:
                gy = self._ground_y(x, z, grad_x, grad_z)
                par_verts.append([x, gy + par_base_y, z])
            for x, z in coords:
                gy = self._ground_y(x, z, grad_x, grad_z)
                par_verts.append([x, gy + par_top_y, z])
            for i in range(n):
                j = (i + 1) % n
                par_faces.append([i, j, n+j])
                par_faces.append([i, n+j, n+i])
                par_faces.append([j, i, n+i])   # inner face
                par_faces.append([j, n+i, n+j])
            meshes.append({
                "element_id": f"{prefix}_parapet",
                "element_type": "parapet",
                "vertices": par_verts, "faces": par_faces,
                "level": stories - 1, "color": "#475569",
            })

        return meshes

    def _terrain_and_overlap(self, footprint: Polygon, neighbors: List[Polygon],
                              grad_x: float, grad_z: float) -> List[Dict]:
        meshes = []

        # ── Green footprint outline on ground ──
        coords = list(footprint.exterior.coords[:-1])
        n = len(coords)
        OUT = 0.12
        H = 0.08
        cx_f = sum(x for x, z in coords) / n
        cz_f = sum(z for x, z in coords) / n

        verts_fp = []
        faces_fp = []
        for x, z in coords:
            gy = self._ground_y(x, z, grad_x, grad_z)
            verts_fp.append([x, gy, z])        # inner bottom
        for x, z in coords:
            gy = self._ground_y(x, z, grad_x, grad_z)
            verts_fp.append([x, gy + H, z])    # inner top
        for x, z in coords:
            dx = x - cx_f; dz = z - cz_f
            dist = math.sqrt(dx*dx + dz*dz) or 1
            ox = x + dx/dist * OUT; oz = z + dz/dist * OUT
            gy = self._ground_y(ox, oz, grad_x, grad_z)
            verts_fp.append([ox, gy, oz])       # outer bottom
        for x, z in coords:
            dx = x - cx_f; dz = z - cz_f
            dist = math.sqrt(dx*dx + dz*dz) or 1
            ox = x + dx/dist * OUT; oz = z + dz/dist * OUT
            gy = self._ground_y(ox, oz, grad_x, grad_z)
            verts_fp.append([ox, gy + H, oz])   # outer top

        for i in range(n):
            j = (i + 1) % n
            faces_fp.append([2*n+i, 2*n+j, 3*n+j])
            faces_fp.append([2*n+i, 3*n+j, 3*n+i])
            faces_fp.append([n+i, 3*n+i, 3*n+j])
            faces_fp.append([n+i, 3*n+j, n+j])
            faces_fp.append([i, j, 2*n+j])
            faces_fp.append([i, 2*n+j, 2*n+i])

        meshes.append({
            "element_id": "footprint_ok",
            "element_type": "footprint_ok",
            "vertices": verts_fp, "faces": faces_fp,
            "level": 0, "color": "#00ff88",
        })

        # ── Terrain ground plane — follows the parcel footprint shape ──
        try:
            pad = 8.0
            outer = footprint.buffer(pad, join_style=2, cap_style=2)
            outer_coords = list(outer.exterior.coords[:-1])
        except Exception:
            outer_coords = None

        if outer_coords and len(outer_coords) >= 3:
            # Fan-triangulate the padded footprint polygon from its centroid
            cx_t = sum(x for x, z in outer_coords) / len(outer_coords)
            cz_t = sum(z for x, z in outer_coords) / len(outer_coords)
            gy_c = self._ground_y(cx_t, cz_t, grad_x, grad_z) - 0.05
            verts_t = [[cx_t, gy_c, cz_t]]   # index 0 = centroid
            for x, z in outer_coords:
                verts_t.append([x, self._ground_y(x, z, grad_x, grad_z) - 0.05, z])
            faces_t = []
            n_t = len(outer_coords)
            for i in range(n_t):
                j = (i + 1) % n_t
                faces_t.append([0, i + 1, j + 1])
        else:
            # Fallback: simple quad
            b = footprint.bounds
            pad = 8.0
            corners = [(b[0]-pad,b[1]-pad),(b[2]+pad,b[1]-pad),(b[2]+pad,b[3]+pad),(b[0]-pad,b[3]+pad)]
            verts_t = [[x, self._ground_y(x,z,grad_x,grad_z)-0.05, z] for x,z in corners]
            faces_t = [[0,1,2],[0,2,3]]

        meshes.append({
            "element_id": "terrain_plane",
            "element_type": "terrain",
            "vertices": verts_t, "faces": faces_t,
            "level": 0, "color": "#3d5a3e",
        })

        # ── Red overlap mesh where footprint overlaps neighbor buildings ──
        for idx, nb_poly in enumerate(neighbors):
            try:
                overlap = footprint.intersection(nb_poly)
                if overlap.is_empty:
                    continue
                polys_to_draw = []
                if overlap.geom_type == 'Polygon':
                    polys_to_draw = [overlap]
                elif overlap.geom_type in ('MultiPolygon', 'GeometryCollection'):
                    polys_to_draw = [g for g in overlap.geoms if g.geom_type == 'Polygon']

                for oi, op in enumerate(polys_to_draw):
                    oc = list(op.exterior.coords[:-1])
                    if len(oc) < 3:
                        continue
                    OV_H = 0.25
                    ov = []
                    of = []
                    for x, z in oc:
                        gy = self._ground_y(x, z, grad_x, grad_z)
                        ov.append([x, gy, z])
                    for x, z in oc:
                        gy = self._ground_y(x, z, grad_x, grad_z)
                        ov.append([x, gy + OV_H, z])
                    on = len(oc)
                    # Top face (fan from centroid)
                    ocx = sum(v[0] for v in ov[on:]) / on
                    ocy = sum(v[1] for v in ov[on:]) / on
                    ocz = sum(v[2] for v in ov[on:]) / on
                    ci = len(ov)
                    ov.append([ocx, ocy, ocz])
                    for i in range(on):
                        j = (i+1) % on
                        of.append([on+i, ci, on+j])
                    # Sides
                    for i in range(on):
                        j = (i+1) % on
                        of.append([i, j, on+j])
                        of.append([i, on+j, on+i])

                    meshes.append({
                        "element_id": f"overlap_{idx}_{oi}",
                        "element_type": "overlap",
                        "vertices": ov, "faces": of,
                        "level": 0, "color": "#ff4444",
                    })
            except Exception:
                continue

        return meshes

    def _fit_to_area(self, footprint: Polygon, target_area_m2: float) -> Polygon:
        """Scale footprint down to target_area if it's larger, preserving shape."""
        if footprint.area <= target_area_m2:
            return footprint
        scale = math.sqrt(target_area_m2 / footprint.area)
        return shp_scale(footprint, xfact=scale, yfact=scale, origin='centroid')

    # ── Utilities ─────────────────────────────────────────────────────────

    def _score(self, footprint, total_area_m2, target_area_m2, priority) -> Dict:
        area_match = max(0, 1.0 - abs(total_area_m2 - target_area_m2) / max(target_area_m2, 1))
        p = footprint.exterior.length
        compactness = (4 * math.pi * footprint.area) / (p ** 2 + 0.001)
        if priority == "cost":
            overall = 0.5 * area_match + 0.5 * compactness
        elif priority == "daylight":
            overall = 0.5 * area_match + 0.5 * (1 - compactness)
        else:
            overall = area_match
        return {"area_match": round(area_match, 2), "compactness": round(compactness, 2), "overall": round(overall, 2)}

    def _target_area_m2(self, spec: ProjectSpec) -> float:
        if spec.target_gross_area_sqft:
            return spec.target_gross_area_sqft * 0.0929
        if spec.unit_count:
            return spec.unit_count * 800 * 0.0929
        return 500

    def _build_levels(self, stories: int, floor_height_ft: float) -> List[Level]:
        return [Level(
            index=i, elevation_ft=i * floor_height_ft, height_ft=floor_height_ft,
            label="Ground Floor" if i == 0 else f"Level {i + 1}"
        ) for i in range(stories)]
