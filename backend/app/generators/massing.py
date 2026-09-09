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

        _PLATFORM_MAX_SQFT = 5500.0
        target_area_m2 = max(10, min(self._target_area_m2(spec), _PLATFORM_MAX_SQFT * 0.0929))
        floor_height_m = max(0.1, spec.floor_to_floor_height_ft * 0.3048)
        stories = max(1, spec.stories)

        mat = getattr(spec.structural_system, 'value', str(spec.structural_system))
        mat_color = MATERIAL_COLORS.get(mat, "#94a3b8")

        terrain = site_ctx.terrain or {}
        grad_x = terrain.get("grad_x", 0.0)
        grad_z = terrain.get("grad_z", 0.0)

        _buse = getattr(spec, 'building_use', None)
        _is_sfr = _buse in (BuildingUse.single_family, 'single_family')

        # Resolve style: explicit arg → spec.style → building-use default.
        # Never fall back to brief_shape ('rectangle') as a style name.
        style_val = style or getattr(spec, 'style', None)
        if hasattr(style_val, 'value'):
            style_val = style_val.value
        if not style_val:
            style_val = 'classic_gabled' if _is_sfr else 'modern_linear'


        # Human-readable style name for massing labels
        _STYLE_LABELS = {
            'classic_gabled':     'Gabled Traditional',
            'craftsman':          'Craftsman',
            'victorian':          'Victorian',
            'tudor':              'Tudor',
            'colonial':           'Colonial',
            'farmhouse':          'Farmhouse',
            'ranch':              'Ranch',
            'modern_linear':      'Modern',
            'contemporary_box':   'Contemporary',
            'minimalist':         'Minimalist',
            'mid_century_modern': 'Mid-Century Modern',
            'urban_infill':       'Urban Infill',
            'prefab_modern':      'Prefab Modern',
        }
        _style_label = _STYLE_LABELS.get(style_val or '',
                       (style_val or 'Standard').replace('_', ' ').title())

        # ── Max lot coverage: house must not fill the whole parcel ──
        # CA residential: SFR ≤45%, multi-family ≤60% of buildable envelope
        _max_coverage = 0.45 if _is_sfr else 0.60
        _max_fp_m2 = max(20.0, envelope_local.area * _max_coverage)
        _max_total_area = _max_fp_m2 * stories
        target_area_m2 = min(target_area_m2, _max_total_area)

        slope_mag = math.sqrt(grad_x ** 2 + grad_z ** 2)
        # Hillside mode: archetype sets 'sculpted' shape, OR slope > 15% triggers it
        # automatically even when archetype detection was skipped (e.g. MF building type).
        is_hillside = brief_shape in ('sculpted', 'hillside') or slope_mag > 0.15

        # Roof pitch from archetype — default 12/12 for Victorian/American-traditional
        _roof_pitch_12 = int(brief.get("roof_pitch_12", 12))

        if is_hillside:
            # True hillside stepped massing — each floor cascades downhill
            options = [
                self._option_hillside_stepped(
                    envelope_local, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, slope_mag, style_val,
                    label="A", name="Hillside Cascade",
                    desc="Each floor steps downhill — classic Oakland/Berkeley Hills form",
                    roof_pitch_12=_roof_pitch_12,
                ),
                self._option_hillside_stepped(
                    envelope_local, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, slope_mag, style_val,
                    label="B", name="Wide Hillside Terrace",
                    desc="Wider, shallower plates maximise view exposure on each terrace",
                    roof_pitch_12=_roof_pitch_12,
                ),
                self._option_hillside_split(
                    envelope_local, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, slope_mag, style_val,
                    roof_pitch_12=_roof_pitch_12,
                ),
            ]

        elif brief_shape == 'narrow_lot':
            # Victorian / Townhome / Urban Infill: all options stay narrow — no L or U cuts
            options = [
                self._option_rectangle(
                    envelope_local, target_w, target_d, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    label="A", name="Narrow Plate",
                    desc="Classic narrow-lot plan — maximises street-facade presence",
                    roof_pitch_12=_roof_pitch_12,
                    lock_width=True,
                ),
                self._option_narrow_with_rear_wing(
                    envelope_local, target_w, target_d, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    roof_pitch_12=_roof_pitch_12,
                ),
                self._option_stepped(
                    envelope_local, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    roof_pitch_12=_roof_pitch_12,
                ),
            ]

        elif brief_shape == 'wide_shallow':
            # Mid-Century / Prefab: wide shallow plate — Option A is always the wide plate
            options = [
                self._option_rectangle(
                    envelope_local, target_w, target_d, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    label="A", name="Wide Plate",
                    desc="Full-width shallow plan — classic ranch / mid-century proportions",
                    roof_pitch_12=_roof_pitch_12,
                ),
                self._option_l_shape(
                    envelope_local, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    roof_pitch_12=_roof_pitch_12,
                ),
                self._option_stepped(
                    envelope_local, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    roof_pitch_12=_roof_pitch_12,
                ),
            ]

        elif brief_shape == 'l_shape':
            # High-End Custom: complex non-rectangular massing
            options = [
                self._option_l_shape(
                    envelope_local, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    roof_pitch_12=_roof_pitch_12,
                ),
                self._option_u_shape(
                    envelope_local, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    roof_pitch_12=_roof_pitch_12,
                ),
                self._option_stepped(
                    envelope_local, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    roof_pitch_12=_roof_pitch_12,
                ),
            ]

        elif brief_shape == 'rectangle':
            # Production Tract: standard variety
            options = [
                self._option_rectangle(
                    envelope_local, target_w, target_d, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    label="A", name=f"{_style_label} Floor Plan",
                    desc="Clean rectangular footprint — maximum usable area per floor",
                    roof_pitch_12=_roof_pitch_12,
                ),
                self._option_l_shape(
                    envelope_local, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    roof_pitch_12=_roof_pitch_12,
                ),
                self._option_u_shape(
                    envelope_local, target_area_m2, stories,
                    floor_height_m, spec.priority, mat_color, grad_x, grad_z,
                    neighbor_local, style_val,
                    roof_pitch_12=_roof_pitch_12,
                ),
            ]
        else:
            options = [
                self._option_l_shape(envelope_local, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local, style_val, roof_pitch_12=_roof_pitch_12),
                self._option_stepped(envelope_local, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local, style_val, roof_pitch_12=_roof_pitch_12),
                self._option_u_shape(envelope_local, target_area_m2, stories, floor_height_m, spec.priority, mat_color, grad_x, grad_z, neighbor_local, style_val, roof_pitch_12=_roof_pitch_12),
            ]
        # ── Angled corners ───────────────────────────────────────────────────
        # Estate plans are not boxes. The reference sheet
        # backend/app/data/High-End-Custom/R.jpg cuts its master-suite bay, its
        # dining bay and its loggia corners at 45°. Chamfering the FOOTPRINT is
        # all that's needed: every room is clipped to it, so the angled walls
        # propagate into the plan without touching the row layout at all.
        _angled = bool(
            (design_brief or {}).get('angled_corners')
            or brief_shape == 'l_shape'
            or style_val in ('contemporary_luxury', 'sculpted_stepped')
        )
        if _angled:
            for opt in options:
                fp = opt.get('footprint')
                if not fp:
                    continue
                cut = self._chamfer_size(fp)
                if cut <= 0:
                    continue
                opt['footprint'] = self._chamfer_corners(fp, cut)

        levels = self._build_levels(stories, spec.floor_to_floor_height_ft)
        return options, levels

    @staticmethod
    def _chamfer_size(footprint: List) -> float:
        """Corner cut sized off the plan, ~6% of its short side, capped at 2.4 m."""
        xs = [p[0] for p in footprint]
        zs = [p[1] for p in footprint]
        short = min(max(xs) - min(xs), max(zs) - min(zs))
        if short < 8.0:
            return 0.0
        return min(2.4, max(0.9, short * 0.06))

    @staticmethod
    def _chamfer_corners(footprint: List, cut: float) -> List:
        """Replace each sufficiently open corner with a 45° cut.

        Only corners whose two edges are both comfortably longer than the cut
        are touched, so short jogs on an L or U plan keep their square return.
        """
        pts = [(float(p[0]), float(p[1])) for p in footprint]
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        n = len(pts)
        if n < 4:
            return footprint

        out: List[List[float]] = []
        for i in range(n):
            px, pz = pts[(i - 1) % n]
            cx, cz = pts[i]
            nx, nz = pts[(i + 1) % n]

            in_len = math.hypot(cx - px, cz - pz)
            out_len = math.hypot(nx - cx, nz - cz)
            # Leave the corner alone unless both legs can spare the cut with
            # room to spare — otherwise chamfering eats a whole short segment.
            if in_len < cut * 3.0 or out_len < cut * 3.0:
                out.append([cx, cz])
                continue

            t_in = cut / in_len
            t_out = cut / out_len
            out.append([cx + (px - cx) * t_in, cz + (pz - cz) * t_in])
            out.append([cx + (nx - cx) * t_out, cz + (nz - cz) * t_out])

        try:
            poly = Polygon(out)
            if not poly.is_valid or poly.area <= 0:
                return footprint
        except Exception:
            return footprint
        return out

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

    def _option_l_shape(self, envelope_local, target_area_m2, stories, floor_height_m, priority, mat_color, grad_x, grad_z, neighbors, style='modern_linear', roof_pitch_12: int = 12) -> Dict:
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
        # Gabled roofs use the bounding box and span the L-void — use flat parapet instead
        _l_style = 'modern_linear' if ('classic' in style or 'gabled' in style) else style
        meshes = self._extrude_footprint(footprint, stories, floor_height_m, "massing_a", mat_color, grad_x, grad_z, style=_l_style, roof_pitch_12=0)
        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        return {
            "label": "A", "name": "L-Shape",
            "description": "L-shaped plan — defines front yard, efficient corner circulation",
            "footprint": list(footprint.exterior.coords),
            "total_area_m2": total_area, "stories": stories, "floor_height_m": floor_height_m,
            "meshes": meshes,
            "score": self._score(footprint, total_area, target_area_m2, priority),
        }

    def _option_stepped(self, envelope_local, target_area_m2, stories, floor_height_m, priority, mat_color, grad_x, grad_z, neighbors, style='modern_linear', roof_pitch_12: int = 12) -> Dict:
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
        meshes = self._extrude_footprint(footprint, lower_stories, floor_height_m, "massing_b_low", mat_color, grad_x, grad_z, style='modern_linear', roof_pitch_12=0)  # lower always flat
        if upper_stories > 0:
            y_offset = lower_stories * floor_height_m
            upper_meshes = self._extrude_footprint(upper_footprint, upper_stories, floor_height_m, "massing_b_up", mat_color, grad_x, grad_z, style=style, roof_pitch_12=roof_pitch_12)
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

    def _option_u_shape(self, envelope_local, target_area_m2, stories, floor_height_m, priority, mat_color, grad_x, grad_z, neighbors, style='modern_linear', roof_pitch_12: int = 12) -> Dict:
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
        # Gabled roofs span the court void — use flat parapet on U-shapes
        _u_style = 'modern_linear' if ('classic' in style or 'gabled' in style) else style
        meshes = self._extrude_footprint(footprint, stories, floor_height_m, "massing_c", mat_color, grad_x, grad_z, style=_u_style, roof_pitch_12=0)
        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        return {
            "label": "C", "name": "U-Shape / Forecourt",
            "description": "U-shape with entry courtyard — classic apartment typology",
            "footprint": list(footprint.exterior.coords),
            "total_area_m2": total_area, "stories": stories, "floor_height_m": floor_height_m,
            "meshes": meshes,
            "score": self._score(footprint, total_area, target_area_m2, priority),
        }

    def _option_narrow_with_rear_wing(
        self, envelope_local, target_w, target_d, target_area_m2, stories,
        floor_height_m, priority, mat_color, grad_x, grad_z, neighbors,
        style='classic_gabled', roof_pitch_12: int = 10,
    ) -> Dict:
        """Narrow main body + wider rear service wing — Victorian T-plan.
        Front 70% of depth is the narrow public street-facing volume;
        rear 30% widens by ~40% for the service/kitchen wing."""
        base = envelope_local.buffer(-0.5)
        if base.is_empty:
            base = envelope_local
        target_fp_area = target_area_m2 / max(1, stories)
        eb = base.bounds
        cx = (eb[0] + eb[2]) / 2
        cz = (eb[1] + eb[3]) / 2
        half_w = min(target_w / 2, (eb[2] - eb[0]) / 2 * 0.95)
        half_d = min(target_d / 2, (eb[3] - eb[1]) / 2 * 0.95)

        front_d = half_d * 2 * 0.72   # 72% of depth is narrow main body
        rear_d  = half_d * 2 - front_d
        wing_hw = min(half_w * 1.40, (eb[2] - eb[0]) / 2 * 0.90)  # 40% wider rear

        main = box(cx - half_w, cz - half_d, cx + half_w, cz - half_d + front_d)
        wing = box(cx - wing_hw, cz - half_d + front_d, cx + wing_hw, cz + half_d)

        try:
            from shapely.ops import unary_union as _uu
            combined = _uu([main, wing]).intersection(base)
            if (combined.is_empty or not hasattr(combined, 'exterior')
                    or combined.area < 4.0):
                footprint = self._fit_to_area(base, target_fp_area)
            else:
                footprint = self._fit_to_area(combined, target_fp_area)
        except Exception:
            footprint = self._fit_to_area(base, target_fp_area)

        total_area = footprint.area * stories
        meshes = self._extrude_footprint(
            footprint, stories, floor_height_m, "massing_b",
            mat_color, grad_x, grad_z, style=style, roof_pitch_12=roof_pitch_12,
        )
        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        return {
            "label": "B", "name": "Narrow + Rear Wing",
            "description": "Narrow street facade with wider rear service wing — Victorian T-plan",
            "footprint": list(footprint.exterior.coords),
            "total_area_m2": total_area, "stories": stories,
            "floor_height_m": floor_height_m, "meshes": meshes,
            "score": self._score(footprint, total_area, target_area_m2, priority),
        }

    # ── Hillside helpers ──────────────────────────────────────────────────

    def _hillside_step_vec(self, grad_x: float, grad_z: float, slope_mag: float):
        """Return (dh_x, dh_z) unit vector pointing downhill, derived from USGS terrain gradient."""
        if slope_mag < 1e-4:
            return 0.0, 0.0    # no measurable slope — caller should not step
        return -grad_x / slope_mag, -grad_z / slope_mag

    def _option_hillside_stepped(
        self, envelope_local, target_area_m2, stories, floor_height_m,
        priority, mat_color, grad_x, grad_z, neighbors, slope_mag, style,
        label="A", name="Hillside Cascade", desc="Each floor cascades downhill",
        roof_pitch_12: int = 12,
    ) -> Dict:
        """
        Each level uses the same footprint area but shifts in the downhill
        direction, creating the cascading terraced form of Oakland / Berkeley /
        Los Altos Hills architecture.  Flat floors per level with shed roof on top.
        """
        base = envelope_local.buffer(-0.5)
        if base.is_empty:
            base = envelope_local
        target_fp_area = target_area_m2 / max(1, stories)
        footprint = self._fit_to_area(base, target_fp_area)
        # Use the HIGHEST terrain point under the footprint so the uphill wall
        # sits at grade and the downhill side is elevated (pilotis/foundation).
        base_terrain_y = max(
            self._ground_y(x, z, grad_x, grad_z)
            for x, z in footprint.exterior.coords
        )

        dh_x, dh_z = self._hillside_step_vec(grad_x, grad_z, slope_mag)
        # Step distance derived directly from measured slope: steeper = shorter step per level
        step_dist = max(0.8, min(floor_height_m / max(slope_mag, 0.05) * 0.30,
                                 floor_height_m * 1.5))

        meshes: List[Dict] = []
        level_footprints: List[Polygon] = []

        for lvl in range(stories):
            dx = dh_x * step_dist * lvl
            dz = dh_z * step_dist * lvl
            level_fp = shp_translate(footprint, dx, dz)
            clipped = level_fp.intersection(envelope_local)
            if (not clipped.is_empty and hasattr(clipped, 'exterior')
                    and clipped.area > 4.0):
                level_fp = clipped
            level_footprints.append(level_fp)

            y_offset = base_terrain_y + lvl * floor_height_m
            # Use 'sculpted' only on the top level to get a shed roof there
            lvl_style = style if lvl == stories - 1 else 'modern_linear'
            lvl_meshes = self._extrude_footprint(
                level_fp, 1, floor_height_m,
                f"hs_{label}_{lvl}", mat_color, 0.0, 0.0, style=lvl_style,
                roof_pitch_12=roof_pitch_12,
            )
            for m in lvl_meshes:
                if "vertices" in m:
                    m["vertices"] = [[v[0], v[1] + y_offset, v[2]]
                                     for v in m["vertices"]]
            meshes.extend(lvl_meshes)

        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        total_area = sum(fp.area for fp in level_footprints)
        return {
            "label": label, "name": name, "description": desc,
            "footprint": list(footprint.exterior.coords),
            "total_area_m2": total_area, "stories": stories,
            "floor_height_m": floor_height_m, "meshes": meshes,
            "score": self._score(footprint, total_area, target_area_m2, priority),
        }

    def _option_hillside_split(
        self, envelope_local, target_area_m2, stories, floor_height_m,
        priority, mat_color, grad_x, grad_z, neighbors, slope_mag, style,
        roof_pitch_12: int = 12,
    ) -> Dict:
        """
        Split-level hillside: half-floor steps (4-5 ft) so the house tracks the
        terrain contours closely — typical of 1960s-70s Berkeley/Marin Hills homes.
        Each half-level is offset both vertically (half floor height) and downhill.
        """
        base = envelope_local.buffer(-0.5)
        if base.is_empty:
            base = envelope_local
        target_fp_area = target_area_m2 / max(1, stories)
        footprint = self._fit_to_area(base, target_fp_area * 0.75)
        base_terrain_y = max(
            self._ground_y(x, z, grad_x, grad_z)
            for x, z in footprint.exterior.coords
        )

        dh_x, dh_z = self._hillside_step_vec(grad_x, grad_z, slope_mag)
        half_h = floor_height_m * 0.5
        step_dist = max(0.6, min(half_h / max(slope_mag, 0.05) * 0.30,
                                 floor_height_m))

        half_levels = stories * 2          # double the levels at half height
        meshes: List[Dict] = []
        level_footprints: List[Polygon] = []

        for hlvl in range(half_levels):
            dx = dh_x * step_dist * hlvl
            dz = dh_z * step_dist * hlvl
            level_fp = shp_translate(footprint, dx, dz)
            clipped = level_fp.intersection(envelope_local)
            if (not clipped.is_empty and hasattr(clipped, 'exterior')
                    and clipped.area > 3.0):
                level_fp = clipped
            level_footprints.append(level_fp)

            y_offset = base_terrain_y + hlvl * half_h
            lvl_style = style if hlvl == half_levels - 1 else 'modern_linear'
            lvl_meshes = self._extrude_footprint(
                level_fp, 1, half_h,
                f"hs_split_{hlvl}", mat_color, 0.0, 0.0, style=lvl_style,
                roof_pitch_12=roof_pitch_12,
            )
            for m in lvl_meshes:
                if "vertices" in m:
                    m["vertices"] = [[v[0], v[1] + y_offset, v[2]]
                                     for v in m["vertices"]]
            meshes.extend(lvl_meshes)

        meshes += self._terrain_and_overlap(footprint, neighbors, grad_x, grad_z)
        total_area = sum(fp.area for fp in level_footprints)
        return {
            "label": "C", "name": "Split-Level Hillside",
            "description": "Half-story steps track terrain contours — classic 1960s Berkeley/Marin split-level",
            "footprint": list(footprint.exterior.coords),
            "total_area_m2": total_area, "stories": stories,
            "floor_height_m": floor_height_m, "meshes": meshes,
            "score": self._score(footprint, total_area, target_area_m2, priority),
        }

    def _option_rectangle(self, envelope_local, tw, td, target_area_m2, stories, floor_height_m,
                          priority, mat_color, grad_x, grad_z, neighbors, style='classic_gabled',
                          label="A", name="Rectangle", desc="Rectangular footprint",
                          roof_pitch_12: int = 12, lock_width: bool = False) -> Dict:
        """Simple rectangular footprint — used for Victorian narrow-lot and other brief_shape='rectangle' archetypes."""
        base = envelope_local.buffer(-0.5)
        if base.is_empty:
            base = envelope_local
        target_fp_area = target_area_m2 / max(1, stories)
        eb = base.bounds
        cx = (eb[0] + eb[2]) / 2
        cz = (eb[1] + eb[3]) / 2
        half_w = min(tw / 2, (eb[2] - eb[0]) / 2 * 0.95)

        if lock_width:
            # Narrow-lot mode: width is sacred — grow only in depth to hit target area,
            # but cap the depth:width ratio. Real narrow-lot Victorians run up to
            # roughly 2.5:1; past that, a bigger target area should widen the
            # footprint (still narrow, just less absurd) rather than turn the house
            # into a hundred-foot-deep sliver.
            actual_w = half_w * 2
            needed_d = target_fp_area / max(actual_w, 0.1)
            _max_depth_ratio = 2.5
            if needed_d > actual_w * _max_depth_ratio:
                needed_d = actual_w * _max_depth_ratio
                actual_w = target_fp_area / needed_d
                half_w = min(actual_w / 2, (eb[2] - eb[0]) / 2 * 0.95)
            half_d = min(needed_d / 2, (eb[3] - eb[1]) / 2 * 0.95)
        else:
            half_d = min(td / 2, (eb[3] - eb[1]) / 2 * 0.95)

        rect = box(cx - half_w, cz - half_d, cx + half_w, cz + half_d)
        clipped = base.intersection(rect)
        if clipped.is_empty or not hasattr(clipped, 'exterior'):
            clipped = self._fit_to_area(base, target_fp_area)

        if lock_width:
            footprint = clipped  # already sized correctly; don't uniform-scale
        else:
            footprint = self._fit_to_area(clipped, target_fp_area)
        total_area = footprint.area * stories
        meshes = self._extrude_footprint(footprint, stories, floor_height_m, f"massing_{label.lower()}", mat_color, grad_x, grad_z, style=style, roof_pitch_12=roof_pitch_12)
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
                           style: str = 'modern_linear',
                           roof_pitch_12: int = 12) -> List[Dict]:
        coords = list(footprint.exterior.coords[:-1])
        if not coords:
            return []
        n = len(coords)
        total_height = stories * floor_height_m
        meshes = []

        # Footprint centroid — used for belt offset and gabled roof calculations
        cx_fp = sum(x for x, z in coords) / n
        cz_fp = sum(z for x, z in coords) / n

        # ── Main shell (wall faces only — no top cap, roof mesh closes the top) ──
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

        meshes.append({
            "element_id": f"{prefix}_mass",
            "element_type": "massing",
            "vertices": vertices, "faces": faces,
            "level": 0, "color": color,
        })

        # ── Floor-line belt: thin dark slab at each inter-floor boundary ──
        # Pushed 3 cm outward so it's always visible above the main wall surface.
        # Applied to multi-story modern/contemporary builds.
        _modern_style = any(k in style for k in ('modern', 'contemporary', 'minimalist', 'urban'))
        if stories >= 2 and _modern_style:
            BELT_H    = 0.14   # 14 cm slab depth
            BELT_PUSH = 0.03   # 3 cm outward from wall face
            for flr in range(1, stories):
                belt_y = flr * floor_height_m
                bv: List = []
                bf: List = []
                for x, z in coords:
                    gy = self._ground_y(x, z, grad_x, grad_z)
                    dx = x - cx_fp
                    dz = z - cz_fp
                    dist = math.sqrt(dx * dx + dz * dz) or 1.0
                    bx = x + (dx / dist) * BELT_PUSH
                    bz = z + (dz / dist) * BELT_PUSH
                    bv.append([bx, gy + belt_y, bz])           # bottom ring
                    bv.append([bx, gy + belt_y + BELT_H, bz])  # top ring
                for i in range(n):
                    j = (i + 1) % n
                    bf.append([2*i, 2*j, 2*j+1])
                    bf.append([2*i, 2*j+1, 2*i+1])
                meshes.append({
                    "element_id": f"{prefix}_belt_{flr}",
                    "element_type": "floor_band",
                    "vertices": bv, "faces": bf,
                    "level": flr - 1, "color": "#0f172a",
                })

        # ── Roof — three distinct forms per style ──
        roof_height_rel = stories * floor_height_m
        is_gabled   = ('classic' in style or 'gabled' in style or 'victorian' in style
                        or 'suburban' in style or 'colonial' in style or 'craftsman' in style
                        or 'farmhouse' in style or 'tudor' in style or 'ranch' in style)
        is_sculpted = 'sculpted' in style

        if is_gabled:
            # Gabled roof + porch are both owned by facade.py (correct normals, wall-aligned).
            # Massing only emits the wall shell for gabled styles.
            pass

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
        cx_f = sum(x for x, _ in coords) / n
        cz_f = sum(z for _, z in coords) / n

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
            cx_t = sum(x for x, _ in outer_coords) / len(outer_coords)
            cz_t = sum(z for _, z in outer_coords) / len(outer_coords)
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
        """Scale footprint to match target_area in both directions, preserving shape."""
        area = footprint.area
        if area < 0.01 or abs(area - target_area_m2) < 1.0:
            return footprint
        scale = math.sqrt(target_area_m2 / area)
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
        # Neither an explicit area nor unit count was given. A flat 500 sqft here
        # used to size the WHOLE building regardless of stories/bedrooms — for a
        # 2-story house that's 250 sqft/floor, nowhere near enough to hold real
        # rooms, and completely disconnected from however many units the
        # AI/floorplan step later decides to pack into the footprint. Scale by
        # stories using the same ~800 sqft/unit assumption used just above, so a
        # 2-story building defaults to roughly one reasonably-sized unit per floor
        # instead of a number with no relationship to the building at all.
        stories = max(1, getattr(spec, 'stories', None) or 1)
        return stories * 800 * 0.0929

    def _build_levels(self, stories: int, floor_height_ft: float) -> List[Level]:
        return [Level(
            index=i, elevation_ft=i * floor_height_ft, height_ft=floor_height_ft,
            label="Ground Floor" if i == 0 else f"Level {i + 1}"
        ) for i in range(stories)]
