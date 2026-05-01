"""
StructuralEngine
Computes structural members (columns, beams, joists, footings) for residential buildings.
Uses simplified ASD (Allowable Stress Design) per IBC/ASCE 7-22 for residential.

Coordinate convention: all positions in local meters (X east, Y up, Z north).
All sizes reported in both imperial (design) and metric (output).
"""
import math
import uuid
from typing import List, Dict, Tuple, Optional, Any
from shapely.geometry import Polygon, box
from shapely.affinity import scale as shp_scale
from app.models.schemas import Level

# ── Design loads (ASCE 7-22 Table 4.3-1, residential) ────────────────────
DEAD_LOAD_FLOOR_PSF = {
    "wood":     15.0,   # wood framing + sheathing + finishes
    "steel":    20.0,   # steel + composite deck + concrete topping
    "concrete": 35.0,   # post-tension slab
}
LIVE_LOAD_RESIDENTIAL_PSF = 40.0     # IBC 1607.3, Table 1607.1
LIVE_LOAD_ROOF_PSF        = 20.0     # IBC 1607.11 (or snow — whichever governs)
DEAD_LOAD_ROOF_PSF        = 20.0     # roofing + insulation + MEP
PARTITION_LOAD_PSF        = 15.0     # IBC 1607.5 movable partitions

# ── Seismic weight factor (simplified — adds mass for seismic calc) ────────
SEISMIC_WEIGHT_FACTOR = {
    "A": 1.0, "B": 1.05, "C": 1.10, "D": 1.20, "E": 1.30, "F": 1.40
}

# ── Column allowable loads (ASD) ──────────────────────────────────────────
# Wood: Douglas Fir-Larch #2, Fc=1000 psi, size factor applied
WOOD_FC_PSI    = 900    # conservative Fc* for posts
STEEL_FY_KSI   = 46     # A500 Grade B HSS
CONCRETE_FC_PSI = 4000  # normal-weight concrete

# ── Max column grid spacing by structural system ──────────────────────────
MAX_GRID_M = {
    "wood":     4.5,   # ~15 ft — wood joist max practical span
    "steel":    7.6,   # ~25 ft — steel beam economical span
    "concrete": 6.1,   # ~20 ft — PT slab economical span
}

# ── Standard wood post sizes (nominal inches → actual mm) ─────────────────
WOOD_POST_SIZES = [
    (4, 4, 89),    # 4x4 — 89mm actual
    (6, 6, 140),   # 6x6
    (8, 8, 184),   # 8x8
    (10, 10, 235), # 10x10
    (12, 12, 286), # 12x12
]

# ── Standard steel HSS sizes (nominal OD inches, wall t inches, area in²) ─
STEEL_HSS_SIZES = [
    (3.5,  0.216, 2.14),   # HSS 3.5x3.5x1/4
    (4.0,  0.237, 3.37),   # HSS 4x4x1/4
    (5.0,  0.258, 4.59),   # HSS 5x5x1/4
    (6.0,  0.280, 6.17),   # HSS 6x6x1/4
    (8.0,  0.312, 9.36),   # HSS 8x8x5/16
]

# ── Standard wood beam sizes (nominal b x d inches, S in³) ────────────────
WOOD_BEAM_SIZES = [
    (2, 10,  21.4),  # 2x10 joist S
    (2, 12,  31.6),  # 2x12 joist S
    (4, 10,  49.9),  # 4x10 beam
    (4, 12,  73.8),  # 4x12 beam
    (6, 12, 121.2),  # 6x12 beam
    (6, 14, 167.1),  # 6x14 beam
    (3, 14, 87.5),   # LVL 3.5x14 (triple 2x14 LVL)
]

# ── Steel W-shape beams (designation, S_x in³, weight plf) ────────────────
STEEL_BEAM_SIZES = [
    ("W8x10",   7.81,  10),
    ("W8x18",  15.2,   18),
    ("W10x22", 23.2,   22),
    ("W10x33", 35.0,   33),
    ("W12x26", 33.4,   26),
    ("W12x40", 51.9,   40),
    ("W14x30", 42.0,   30),
    ("W14x48", 70.3,   48),
    ("W16x36", 56.5,   36),
    ("W16x57", 92.2,   57),
]


class StructuralMember:
    """A single structural member with geometry and sizing info."""
    def __init__(self, member_id: str, member_type: str, start: List[float], end: List[float],
                 section: str, material: str, load_kips: float = 0.0,
                 size_m: float = 0.15, color: str = "#a855f7"):
        self.id = member_id
        self.type = member_type        # column, beam, joist, footing, shear_wall
        self.start = start             # [x, y, z]
        self.end = end                 # [x, y, z]
        self.section = section         # e.g. "6x6", "W10x22", "HSS5x5x1/4"
        self.material = material       # wood, steel, concrete
        self.load_kips = round(load_kips, 1)
        self.size_m = size_m           # cross-section dimension for rendering
        self.color = color

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "start": self.start,
            "end": self.end,
            "section": self.section,
            "material": self.material,
            "load_kips": self.load_kips,
            "size_m": self.size_m,
            "color": self.color,
        }


class StructuralEngine:

    def generate(
        self,
        footprint_coords: List[Tuple[float, float]],
        levels: List[Level],
        structural_system: str,
        site_ctx_dict: Dict[str, Any],
        target_area_m2: float = 200.0,
        is_sfr: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Generate all structural members for the building.
        Returns a list of dicts (serializable).
        """
        mat = getattr(structural_system, 'value', str(structural_system)).lower()
        stories = len(levels)
        floor_h = levels[0].height_ft * 0.3048 if levels else 3.0

        footprint = Polygon(footprint_coords)
        bounds = footprint.bounds  # minx, miny, maxx, maxy
        bw = bounds[2] - bounds[0]
        bd = bounds[3] - bounds[1]

        # ── 1. Compute design loads ──────────────────────────────────────
        sdc = site_ctx_dict.get("seismic_category", "D")
        wind_mph = site_ctx_dict.get("wind_speed_mph", 90.0)
        seismic_w = SEISMIC_WEIGHT_FACTOR.get(sdc[:1], 1.2)

        dead_floor = DEAD_LOAD_FLOOR_PSF.get(mat, 15.0)
        live_floor = LIVE_LOAD_RESIDENTIAL_PSF + PARTITION_LOAD_PSF
        dead_roof  = DEAD_LOAD_ROOF_PSF
        live_roof  = LIVE_LOAD_ROOF_PSF

        # Total floor load (psf) per floor
        floor_load_psf = dead_floor + live_floor   # e.g. 70 psf
        roof_load_psf  = dead_roof  + live_roof    # e.g. 40 psf

        members: List[StructuralMember] = []

        # ── 2. Column grid ───────────────────────────────────────────────
        grid_m = min(MAX_GRID_M.get(mat, 4.5), bw / 2, bd / 2)
        grid_m = max(grid_m, 2.5)

        # Wood SFR uses perimeter-only columns (platform framing uses bearing walls, not columns)
        # For large houses (>400 m²) or non-wood/non-SFR: use full grid
        if is_sfr and mat == "wood" and target_area_m2 < 400:
            col_positions = self._perimeter_columns(footprint, bounds, grid_m)
        else:
            col_positions = self._column_grid(footprint, bounds, grid_m)

        # ── 3. Column sizing and placement ──────────────────────────────
        trib_area_m2 = grid_m ** 2  # tributary area per column (m²)
        trib_area_ft2 = trib_area_m2 * 10.764

        # Cumulative axial load on ground-floor column (accumulates all floors)
        floor_P_kips = (floor_load_psf * trib_area_ft2) / 1000.0  # per floor
        roof_P_kips  = (roof_load_psf  * trib_area_ft2) / 1000.0
        total_P_kips = floor_P_kips * stories + roof_P_kips

        # Apply seismic amplification
        total_P_kips *= seismic_w

        col_section, col_size_m, col_color = self._size_column(mat, total_P_kips, floor_h * stories)

        for (cx, cz) in col_positions:
            # Ground-floor column (full height)
            col_base_y = 0.0
            col_top_y  = stories * floor_h
            members.append(StructuralMember(
                member_id=f"col_{uuid.uuid4().hex[:6]}",
                member_type="column",
                start=[cx, col_base_y, cz],
                end=[cx, col_top_y, cz],
                section=col_section,
                material=mat,
                load_kips=total_P_kips,
                size_m=col_size_m,
                color=col_color,
            ))

            # Footing at base
            footing_size = max(0.6, col_size_m * 3.5)
            members.append(StructuralMember(
                member_id=f"ftg_{uuid.uuid4().hex[:6]}",
                member_type="footing",
                start=[cx - footing_size/2, -0.6, cz - footing_size/2],
                end=[cx + footing_size/2,  0.0,  cz + footing_size/2],
                section=f"{footing_size*39.37:.0f}in sq spread footing",
                material="concrete",
                load_kips=total_P_kips,
                size_m=footing_size,
                color="#64748b",
            ))

        # ── 4. Beams at each floor level ─────────────────────────────────
        beam_section, beam_size_m, beam_color = self._size_beam(
            mat, floor_load_psf, grid_m, grid_m
        )

        for lvl_idx in range(1, stories + 1):  # beam at each floor + roof
            beam_y = lvl_idx * floor_h - 0.25   # just below floor slab
            is_roof = (lvl_idx == stories)
            load_psf = roof_load_psf if is_roof else floor_load_psf
            b_section, b_size, b_color = self._size_beam(mat, load_psf, grid_m, grid_m)

            for i, (cx1, cz1) in enumerate(col_positions):
                for j, (cx2, cz2) in enumerate(col_positions):
                    if i >= j:
                        continue
                    dist = math.sqrt((cx2-cx1)**2 + (cz2-cz1)**2)
                    if abs(dist - grid_m) < 0.5:  # adjacent columns
                        span_load = load_psf * grid_m / 1000.0  # kips/ft total
                        M_kips_ft = span_load * (grid_m * 3.281) ** 2 / 8
                        members.append(StructuralMember(
                            member_id=f"beam_{uuid.uuid4().hex[:6]}",
                            member_type="beam",
                            start=[cx1, beam_y, cz1],
                            end=[cx2, beam_y, cz2],
                            section=b_section,
                            material=mat,
                            load_kips=span_load * grid_m * 3.281,
                            size_m=b_size,
                            color=b_color,
                        ))

        # ── 5. Perimeter grade beams (foundation) ────────────────────────
        fp_coords = list(footprint.exterior.coords[:-1])
        for i in range(len(fp_coords)):
            x1, z1 = fp_coords[i]
            x2, z2 = fp_coords[(i+1) % len(fp_coords)]
            members.append(StructuralMember(
                member_id=f"gb_{uuid.uuid4().hex[:5]}",
                member_type="grade_beam",
                start=[x1, -0.45, z1],
                end=[x2, -0.45, z2],
                section="12x18 conc grade beam",
                material="concrete",
                load_kips=0,
                size_m=0.30,
                color="#475569",
            ))

        # ── 6. Shear walls (seismic + wind) ─────────────────────────────
        # Place shear walls at building perimeter and one interior cross wall
        if sdc in ("C", "D", "E", "F") or wind_mph >= 100:
            shear_members = self._add_shear_walls(footprint, fp_coords, floor_h, stories, mat)
            members.extend(shear_members)

        return [m.to_dict() for m in members]

    # ── Column sizing ─────────────────────────────────────────────────────────

    def _size_column(self, mat: str, P_kips: float, height_m: float) -> Tuple[str, float, str]:
        """Returns (section_label, size_m_for_rendering, color)."""
        if mat == "wood":
            P_lbs = P_kips * 1000
            # P = Fc* × A × CF (size factor) — simplified
            Fc_adj = WOOD_FC_PSI * 0.8  # Fc with Cd=1.0, CM=0.9, Ct=1.0
            req_area_in2 = P_lbs / Fc_adj
            for nom_b, nom_d, actual_mm in WOOD_POST_SIZES:
                actual_in = actual_mm / 25.4
                if actual_in * actual_in >= req_area_in2:
                    return f"{nom_b}x{nom_d} DF-L #2", actual_mm / 1000, "#8B6914"
            return "12x12 DF-L #2", 0.286, "#8B6914"

        elif mat == "steel":
            # Simplified: P = φPn = 0.9 × Fy × A (ignoring buckling, conservative)
            req_area_in2 = P_kips / (0.9 * STEEL_FY_KSI)
            for od, t, area in STEEL_HSS_SIZES:
                if area >= req_area_in2:
                    size_m = od * 0.0254
                    return f"HSS{od}x{od}x{t}", size_m, "#6B7B8D"
            return "HSS8x8x5/16", 0.203, "#6B7B8D"

        else:  # concrete
            # P = 0.80 × [0.85 × fc × (Ag - Ast) + Fy_rebar × Ast]
            # Assume 2% steel ratio: Ast = 0.02 × Ag
            # Simplified: P ≈ 0.80 × 0.85 × fc × Ag (conservative)
            req_Ag_in2 = (P_kips * 1000) / (0.80 * 0.85 * CONCRETE_FC_PSI)
            side_in = math.sqrt(req_Ag_in2)
            side_in_round = max(12, math.ceil(side_in / 2) * 2)  # round to even inches
            size_m = side_in_round * 0.0254
            return f"{side_in_round}x{side_in_round} conc col", size_m, "#8C8C8C"

    # ── Beam sizing ───────────────────────────────────────────────────────────

    def _size_beam(self, mat: str, load_psf: float, span_m: float, trib_w_m: float) -> Tuple[str, float, str]:
        """Returns (section_label, depth_m_for_rendering, color)."""
        span_ft = span_m * 3.281
        trib_ft = trib_w_m * 3.281
        w_plf = load_psf * trib_ft            # uniform load plf
        M_lbs_ft = w_plf * span_ft**2 / 8    # max moment (simple span)
        M_in_lbs = M_lbs_ft * 12

        if mat == "wood":
            Fb = 1200  # psi, DF-L #2 adjusted
            req_S_in3 = M_in_lbs / Fb
            for b, d, S in WOOD_BEAM_SIZES:
                if S >= req_S_in3:
                    depth_m = d * 0.0254
                    return f"{b}x{d} DF-L beam", depth_m, "#8B6914"
            return "6x14 DF-L beam", 0.356, "#8B6914"

        elif mat == "steel":
            Fb_ksi = 0.6 * (STEEL_FY_KSI)     # ASD allowable bending
            M_kips_in = M_in_lbs / 1000
            req_Sx_in3 = M_kips_in / Fb_ksi
            for desig, Sx, wt in STEEL_BEAM_SIZES:
                if Sx >= req_Sx_in3:
                    d_in = int(desig.split('x')[0][1:])  # parse depth from W10x22 → 10
                    return desig, d_in * 0.0254, "#6B7B8D"
            return "W16x57", 0.406, "#6B7B8D"

        else:  # concrete
            # Simplified: d ≈ span/15 for slab, use 8-12in beam depth
            d_in = max(8, int(span_ft * 0.8))
            d_in = min(d_in, 24)
            return f"{d_in}in conc beam", d_in * 0.0254, "#8C8C8C"

    # ── Column grid generation ────────────────────────────────────────────────

    def _column_grid(self, footprint: Polygon, bounds: Tuple, grid_m: float) -> List[Tuple[float, float]]:
        """Generate grid of column positions clipped to footprint (inset by 0.3m)."""
        minx, miny, maxx, maxy = bounds
        fp_inset = footprint.buffer(-0.3)
        positions = []

        # Generate grid points
        x = minx
        while x <= maxx + 0.1:
            z = miny
            while z <= maxy + 0.1:
                pt_box = Polygon([(x-0.1, z-0.1), (x+0.1, z-0.1), (x+0.1, z+0.1), (x-0.1, z+0.1)])
                if fp_inset.intersects(pt_box):
                    positions.append((x, z))
                z += grid_m
            x += grid_m

        # Always include footprint corners (setback 0.5m)
        fp_coords = list(footprint.exterior.coords[:-1])
        for (cx, cz) in fp_coords:
            # Find direction toward centroid
            centx = sum(p[0] for p in fp_coords) / len(fp_coords)
            centz = sum(p[1] for p in fp_coords) / len(fp_coords)
            dx, dz = centx - cx, centz - cz
            dist = max(0.01, math.sqrt(dx*dx + dz*dz))
            corner_x = cx + dx/dist * 0.5
            corner_z = cz + dz/dist * 0.5
            # Deduplicate
            if not any(math.sqrt((p[0]-corner_x)**2 + (p[1]-corner_z)**2) < grid_m*0.4 for p in positions):
                positions.append((corner_x, corner_z))

        return positions

    def _perimeter_columns(self, footprint: Polygon, bounds: Tuple, grid_m: float) -> List[Tuple[float, float]]:
        """
        For wood SFR: columns only at perimeter corners + midpoints on long walls.
        Platform framing uses load-bearing walls, not interior columns.
        """
        fp_coords = list(footprint.exterior.coords[:-1])
        positions = []
        centx = sum(p[0] for p in fp_coords) / len(fp_coords)
        centz = sum(p[1] for p in fp_coords) / len(fp_coords)

        # Corner columns (setback 0.3m inward)
        for (cx, cz) in fp_coords:
            dx, dz = centx - cx, centz - cz
            dist = max(0.01, math.sqrt(dx*dx + dz*dz))
            positions.append((cx + dx/dist * 0.3, cz + dz/dist * 0.3))

        # Midpoint columns on walls longer than 6m
        for i in range(len(fp_coords)):
            x1, z1 = fp_coords[i]
            x2, z2 = fp_coords[(i+1) % len(fp_coords)]
            seg_len = math.sqrt((x2-x1)**2 + (z2-z1)**2)
            if seg_len > 6.0:
                n_segs = max(1, int(seg_len / grid_m))
                for s in range(1, n_segs):
                    t = s / n_segs
                    mx = x1 + (x2-x1)*t
                    mz = z1 + (z2-z1)*t
                    dx, dz = centx - mx, centz - mz
                    dist = max(0.01, math.sqrt(dx*dx + dz*dz))
                    positions.append((mx + dx/dist * 0.3, mz + dz/dist * 0.3))

        return positions

    # ── Shear walls ───────────────────────────────────────────────────────────

    def _add_shear_walls(self, footprint, fp_coords, floor_h, stories, mat) -> List[StructuralMember]:
        members = []
        # Add shear wall panels at each perimeter wall segment (mark thicker)
        for i in range(len(fp_coords)):
            x1, z1 = fp_coords[i]
            x2, z2 = fp_coords[(i+1) % len(fp_coords)]
            seg_len = math.sqrt((x2-x1)**2 + (z2-z1)**2)
            if seg_len < 1.2:
                continue
            # Shear wall panel: 20% of each perimeter wall
            panel_len = min(seg_len * 0.20, 1.5)
            mid_x = (x1 + x2) / 2
            mid_z = (z1 + z2) / 2
            ux, uz = (x2-x1)/seg_len, (z2-z1)/seg_len
            px1 = mid_x - ux * panel_len/2
            pz1 = mid_z - uz * panel_len/2
            px2 = mid_x + ux * panel_len/2
            pz2 = mid_z + uz * panel_len/2
            for lvl_i in range(stories):
                base_y = lvl_i * floor_h
                members.append(StructuralMember(
                    member_id=f"sw_{uuid.uuid4().hex[:5]}",
                    member_type="shear_wall",
                    start=[px1, base_y, pz1],
                    end=[px2, base_y + floor_h, pz2],
                    section="OSB shear panel" if mat == "wood" else "conc shear wall",
                    material=mat,
                    load_kips=0,
                    size_m=0.15,
                    color="#7c3aed",
                ))
        return members
