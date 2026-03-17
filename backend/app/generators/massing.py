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
from shapely.affinity import translate as shp_translate
from shapely.ops import transform, unary_union
import pyproj

from app.models.schemas import BuildingModel, ProjectSpec, SiteContext, Level, Mesh

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

        options = [
            self._option_rectangle(envelope_local, target_w, target_d, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local),
            self._option_l_shape(envelope_local, target_w, target_d, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local),
            self._option_bar(envelope_local, target_w, target_d, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local),
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

    def _option_rectangle(self, envelope_local, tw, td, target_area_m2, stories, floor_height_m, priority, mat_color, grad_x, grad_z, neighbors) -> Dict:
        bw = tw
        bh = td
        footprint = box(-bw/2, -bh/2, bw/2, bh/2)
        if not envelope_local.buffer(1).contains(footprint):
            footprint = envelope_local.buffer(-0.5)
        total_area = footprint.area * stories
        meshes = self._extrude_footprint(footprint, stories, floor_height_m, "massing_a", mat_color, grad_x, grad_z)
        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        return {
            "label": "A", "name": "Compact Rectangle",
            "description": "Efficient massing sized to match neighboring footprints",
            "footprint": list(footprint.exterior.coords),
            "total_area_m2": total_area, "stories": stories, "floor_height_m": floor_height_m,
            "meshes": meshes,
            "score": self._score(footprint, total_area, target_area_m2, priority),
        }

    def _option_l_shape(self, envelope_local, tw, td, target_area_m2, stories, floor_height_m, priority, mat_color, grad_x, grad_z, neighbors) -> Dict:
        bw = tw
        bh = td
        full = box(-bw/2, -bh/2, bw/2, bh/2)
        cutout = box(bw * 0.1, bh * 0.1, bw/2, bh/2)
        footprint = full.difference(cutout)
        if footprint.is_empty or not envelope_local.buffer(1).contains(footprint):
            footprint = envelope_local.buffer(-0.5)
        total_area = footprint.area * stories
        coords = list(footprint.exterior.coords)
        meshes = self._extrude_footprint(footprint, stories, floor_height_m, "massing_b", mat_color, grad_x, grad_z)
        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        return {
            "label": "B", "name": "L-Shape / Courtyard",
            "description": "L-shape massing — better daylight and outdoor space",
            "footprint": coords,
            "total_area_m2": total_area, "stories": stories, "floor_height_m": floor_height_m,
            "meshes": meshes,
            "score": self._score(footprint, total_area, target_area_m2, priority),
        }

    def _option_bar(self, envelope_local, tw, td, target_area_m2, stories, floor_height_m, priority, mat_color, grad_x, grad_z, neighbors) -> Dict:
        # Bar: wider than deep, matches neighbor width
        bar_length = tw * 1.2
        bar_depth = max(td * 0.6, 8.0)
        bounds = envelope_local.bounds
        bar_length = min(bar_length, (bounds[2] - bounds[0]) * 0.90)
        bar_depth = min(bar_depth, (bounds[3] - bounds[1]) * 0.90)
        footprint = box(-bar_length/2, -bar_depth/2, bar_length/2, bar_depth/2)
        if not envelope_local.buffer(1).contains(footprint):
            footprint = envelope_local.buffer(-0.5)
        total_area = footprint.area * stories
        meshes = self._extrude_footprint(footprint, stories, floor_height_m, "massing_c", mat_color, grad_x, grad_z)
        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        return {
            "label": "C", "name": "Bar Building",
            "description": "Long bar — maximizes unit count with double-loaded corridor",
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
                           grad_x: float = 0.0, grad_z: float = 0.0) -> List[Dict]:
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

        # ── Terrain ground plane ──
        pad = 8.0
        b = footprint.bounds
        x0, x1 = b[0] - pad, b[2] + pad
        z0, z1 = b[1] - pad, b[3] + pad
        corners = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
        verts_t = [[x, self._ground_y(x, z, grad_x, grad_z) - 0.05, z] for x, z in corners]
        meshes.append({
            "element_id": "terrain_plane",
            "element_type": "terrain",
            "vertices": verts_t, "faces": [[0,1,2],[0,2,3]],
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
