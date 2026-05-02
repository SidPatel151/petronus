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

        style_val = style or getattr(spec, 'style', None) or brief_shape
        if hasattr(style_val, 'value'):
            style_val = style_val.value
        _buse = getattr(spec, 'building_use', None)
        _is_sfr = _buse in (BuildingUse.single_family, BuildingUse.adu, 'single_family', 'adu')
        _is_adu = _buse in (BuildingUse.adu, 'adu')
        if not style_val:
            style_val = 'classic_gabled' if _is_sfr else 'modern_linear'

        # ── Max lot coverage: house must not fill the whole parcel ──
        # CA residential: SFR ≤45%, ADU ≤75%, multi-family ≤60% of buildable envelope
        _max_coverage = 0.75 if _is_adu else (0.45 if _is_sfr else 0.60)
        _max_fp_m2 = max(20.0, envelope_local.area * _max_coverage)
        _max_total_area = _max_fp_m2 * stories
        target_area_m2 = min(target_area_m2, _max_total_area)

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

        # ── Floor bands — one per floor level ──
        BAND_H = 0.18   # band thickness
        BAND_OUT = 0.22  # overhang past wall face

        for floor_i in range(stories):
            band_y = floor_i * floor_height_m
            verts_b = []
            faces_b = []

            # Inner ring (at wall face), outer ring (overhang)
            for x, z in coords:
                gy = self._ground_y(x, z, grad_x, grad_z)
                verts_b.append([x, gy + band_y, z])            # inner bottom
            for x, z in coords:
                gy = self._ground_y(x, z, grad_x, grad_z)
                verts_b.append([x, gy + band_y + BAND_H, z])   # inner top

            # Outer ring: push each point outward by BAND_OUT
            cx_f = sum(x for x, z in coords) / n
            cz_f = sum(z for x, z in coords) / n
            for x, z in coords:
                dx = x - cx_f
                dz = z - cz_f
                dist = math.sqrt(dx*dx + dz*dz) or 1
                ox = x + dx/dist * BAND_OUT
                oz = z + dz/dist * BAND_OUT
                gy = self._ground_y(ox, oz, grad_x, grad_z)
                verts_b.append([ox, gy + band_y, oz])           # outer bottom
            for x, z in coords:
                dx = x - cx_f
                dz = z - cz_f
                dist = math.sqrt(dx*dx + dz*dz) or 1
                ox = x + dx/dist * BAND_OUT
                oz = z + dz/dist * BAND_OUT
                gy = self._ground_y(ox, oz, grad_x, grad_z)
                verts_b.append([ox, gy + band_y + BAND_H, oz])  # outer top

            # inner_bot=0..n-1, inner_top=n..2n-1, outer_bot=2n..3n-1, outer_top=3n..4n-1
            nb = n
            for i in range(nb):
                j = (i + 1) % nb
                # Outer face (front-facing)
                faces_b.append([2*nb+i, 2*nb+j, 3*nb+j])
                faces_b.append([2*nb+i, 3*nb+j, 3*nb+i])
                # Top face
                faces_b.append([nb+i, 3*nb+i, 3*nb+j])
                faces_b.append([nb+i, 3*nb+j, nb+j])
                # Bottom face
                faces_b.append([i, j, 2*nb+j])
                faces_b.append([i, 2*nb+j, 2*nb+i])

            meshes.append({
                "element_id": f"{prefix}_band_{floor_i}",
                "element_type": "floor_band",
                "vertices": verts_b, "faces": faces_b,
                "level": floor_i, "color": "#c0c8d8",
            })

        # ── Roof — three distinct forms per style ──
        roof_height_rel = stories * floor_height_m
        is_gabled   = 'classic' in style or 'gabled' in style
        is_sculpted = 'sculpted' in style

        if is_gabled:
            # ── True hip/pyramid roof — works for any polygon shape ──
            # Single apex above footprint centroid, fan triangles to every eave edge.
            b = footprint.bounds
            bw = b[2] - b[0]
            bd = b[3] - b[1]
            peak_height = min(bw, bd) * 0.30   # ~17° pitch

            # Use representative_point so apex is always inside concave shapes (L, U)
            rep = footprint.representative_point()
            apex_x, apex_z = rep.x, rep.y
            apex_y = self._ground_y(apex_x, apex_z, grad_x, grad_z) + roof_height_rel + peak_height

            eave_verts = []
            for x, z in coords:
                gy = self._ground_y(x, z, grad_x, grad_z)
                eave_verts.append([x, gy + roof_height_rel, z])

            apex_idx = len(eave_verts)
            roof_verts = eave_verts + [[apex_x, apex_y, apex_z]]
            roof_faces = []
            n_eave = len(eave_verts)

            # Fan triangles from each wall-top edge to apex.
            # Three.js DoubleSide handles back-face — no duplicate needed.
            for i in range(n_eave):
                j = (i + 1) % n_eave
                roof_faces.append([i, j, apex_idx])

            meshes.append({
                "element_id": f"{prefix}_roof",
                "element_type": "roof",
                "vertices": roof_verts, "faces": roof_faces,
                "level": stories - 1, "color": "#374151",
            })
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
            PARAPET_H = 0.7   # parapet height above roof deck

            # Roof deck (flat slab, 20cm thick — sits atop wall plate)
            deck_verts = []
            deck_faces = []
            for x, z in coords:
                gy = self._ground_y(x, z, grad_x, grad_z)
                deck_verts.append([x, gy + roof_height_rel, z])       # deck bottom
            for x, z in coords:
                gy = self._ground_y(x, z, grad_x, grad_z)
                deck_verts.append([x, gy + roof_height_rel + 0.18, z]) # deck top
            # Top face (fan from centroid)
            dcx = sum(v[0] for v in deck_verts[n:]) / n
            dcy = sum(v[1] for v in deck_verts[n:]) / n
            dcz = sum(v[2] for v in deck_verts[n:]) / n
            ci = len(deck_verts)
            deck_verts.append([dcx, dcy, dcz])
            for i in range(n):
                j = (i + 1) % n
                deck_faces.append([n+i, ci, n+j])   # top
                deck_faces.append([ci, n+j, n+i])
                deck_faces.append([i, j, n+j])       # side
                deck_faces.append([i, n+j, n+i])
            meshes.append({
                "element_id": f"{prefix}_roof",
                "element_type": "roof",
                "vertices": deck_verts, "faces": deck_faces,
                "level": stories - 1, "color": "#374151",
            })

            # Parapet walls around perimeter
            par_verts = []
            par_faces = []
            par_base_y = roof_height_rel + 0.18
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
