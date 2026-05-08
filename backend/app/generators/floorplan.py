"""
FloorplanGenerator
Two modes:
  - Multi-family: corridor + unit cells (studio/1BR/2BR).
  - Single-family: whole-house room program keyed by bedroom count (1–5 BR),
    following real residential typology (Neufert / DeChiara proportions).
    For large floor plates (>150 m² per floor), uses expanded programs with
    more rooms: foyer, office, pantry, mudroom, bonus_room, loft, etc.
"""
import uuid
import math
from typing import List, Tuple, Dict, Any, Optional
from shapely.geometry import shape, Polygon, box, LineString, Point
from shapely.ops import transform
import pyproj

from app.models.schemas import Room, Wall, ProjectSpec, Level
from app.constants import BuildingUse, SFR_SQFT_RANGES, PRIORITY_SQFT_POSITION, sfr_target_sqft

# Interior inset from exterior wall face — one constant, used everywhere.
# All rooms, walls, and MEP elements must have their CENTER inside fp.buffer(-FP_INSET).
FP_INSET = 0.20

# ── Multi-family unit templates (row-based: each row is a horizontal band,
#    rooms within a row are placed side-by-side left→right) ─────────────────
UNIT_TEMPLATES = {
    "studio": {
        "w": 6.0, "d": 8.0, "area_sqft": 480,
        "rows": [
            {"frac_d": 0.55, "rooms": [
                {"type": "living",  "frac_w": 1.0},
            ]},
            {"frac_d": 0.45, "rooms": [
                {"type": "kitchen",  "frac_w": 0.55},
                {"type": "bathroom", "frac_w": 0.45},
            ]},
        ]
    },
    "1br": {
        "w": 7.5, "d": 9.0, "area_sqft": 720,
        "rows": [
            {"frac_d": 0.40, "rooms": [
                {"type": "living",  "frac_w": 1.0},
            ]},
            {"frac_d": 0.25, "rooms": [
                {"type": "kitchen",  "frac_w": 0.55},
                {"type": "bathroom", "frac_w": 0.45},
            ]},
            {"frac_d": 0.35, "rooms": [
                {"type": "bedroom", "frac_w": 1.0},
            ]},
        ]
    },
    "2br": {
        "w": 9.0, "d": 10.0, "area_sqft": 960,
        "rows": [
            {"frac_d": 0.35, "rooms": [
                {"type": "living",  "frac_w": 1.0},
            ]},
            {"frac_d": 0.25, "rooms": [
                {"type": "kitchen",  "frac_w": 0.50},
                {"type": "bathroom", "frac_w": 0.50},
            ]},
            {"frac_d": 0.40, "rooms": [
                {"type": "bedroom", "frac_w": 0.50},
                {"type": "bedroom", "frac_w": 0.50},
            ]},
        ]
    },
}

# ── Single-family room programs (rows from front→back) ────────────────────────
# Standard programs (< 150 m² per floor ≈ ~1600 sqft)
SFR_PROGRAMS: Dict[int, List[Dict]] = {
    1: [  # ~700 sqft
        {"row_frac_d": 0.45, "rooms": [
            {"type": "living",   "frac_w": 0.65},
            {"type": "kitchen",  "frac_w": 0.35},
        ]},
        {"row_frac_d": 0.20, "rooms": [
            {"type": "dining",   "frac_w": 0.65},
            {"type": "bathroom", "frac_w": 0.35},
        ]},
        {"row_frac_d": 0.35, "rooms": [
            {"type": "bedroom",  "frac_w": 1.0},
        ]},
    ],
    2: [  # ~1,000 sqft
        {"row_frac_d": 0.38, "rooms": [
            {"type": "living",   "frac_w": 0.60},
            {"type": "kitchen",  "frac_w": 0.40},
        ]},
        {"row_frac_d": 0.14, "rooms": [
            {"type": "dining",   "frac_w": 0.60},
            {"type": "bathroom", "frac_w": 0.40},
        ]},
        {"row_frac_d": 0.48, "rooms": [
            {"type": "bedroom",  "frac_w": 0.55},
            {"type": "bedroom",  "frac_w": 0.45},
        ]},
    ],
    3: [  # ~1,500 sqft — classic 3/2
        {"row_frac_d": 0.35, "rooms": [
            {"type": "living",   "frac_w": 0.58},
            {"type": "kitchen",  "frac_w": 0.42},
        ]},
        {"row_frac_d": 0.13, "rooms": [
            {"type": "dining",   "frac_w": 0.58},
            {"type": "laundry",  "frac_w": 0.22},
            {"type": "bathroom", "frac_w": 0.20},
        ]},
        {"row_frac_d": 0.52, "rooms": [
            {"type": "bedroom",  "frac_w": 0.40},  # master
            {"type": "bathroom", "frac_w": 0.20},  # master bath
            {"type": "bedroom",  "frac_w": 0.20},
            {"type": "bedroom",  "frac_w": 0.20},
        ]},
    ],
    4: [  # ~2,200 sqft — 4/2.5
        {"row_frac_d": 0.30, "rooms": [
            {"type": "living",   "frac_w": 0.45},
            {"type": "kitchen",  "frac_w": 0.35},
            {"type": "dining",   "frac_w": 0.20},
        ]},
        {"row_frac_d": 0.14, "rooms": [
            {"type": "corridor", "frac_w": 0.55},
            {"type": "laundry",  "frac_w": 0.25},
            {"type": "bathroom", "frac_w": 0.20},
        ]},
        {"row_frac_d": 0.56, "rooms": [
            {"type": "bedroom",  "frac_w": 0.35},  # master
            {"type": "bathroom", "frac_w": 0.15},  # master bath
            {"type": "bedroom",  "frac_w": 0.17},
            {"type": "bedroom",  "frac_w": 0.17},
            {"type": "bedroom",  "frac_w": 0.16},
        ]},
    ],
    5: [  # ~3,000 sqft — 5/3
        {"row_frac_d": 0.28, "rooms": [
            {"type": "living",   "frac_w": 0.38},
            {"type": "kitchen",  "frac_w": 0.32},
            {"type": "dining",   "frac_w": 0.30},
        ]},
        {"row_frac_d": 0.12, "rooms": [
            {"type": "corridor", "frac_w": 0.50},
            {"type": "laundry",  "frac_w": 0.25},
            {"type": "bathroom", "frac_w": 0.25},
        ]},
        {"row_frac_d": 0.60, "rooms": [
            {"type": "bedroom",  "frac_w": 0.28},  # master suite
            {"type": "bathroom", "frac_w": 0.12},  # master bath
            {"type": "bedroom",  "frac_w": 0.15},
            {"type": "bedroom",  "frac_w": 0.15},
            {"type": "bedroom",  "frac_w": 0.15},
            {"type": "bedroom",  "frac_w": 0.15},
        ]},
    ],
}

# ── Large-house GROUND FLOOR programs (>150 m² per floor) ────────────────────
# Public spaces: foyer, living, kitchen, dining, office, mudroom, family room, etc.
SFR_GROUND_LARGE: Dict[int, List[Dict]] = {
    1: [  # 1BR large cottage
        {"row_frac_d": 0.30, "rooms": [
            {"type": "foyer",   "frac_w": 0.25},
            {"type": "living",  "frac_w": 0.75},
        ]},
        {"row_frac_d": 0.35, "rooms": [
            {"type": "kitchen", "frac_w": 0.55},
            {"type": "dining",  "frac_w": 0.45},
        ]},
        {"row_frac_d": 0.35, "rooms": [
            {"type": "laundry",  "frac_w": 0.40},
            {"type": "bathroom", "frac_w": 0.35},
            {"type": "mudroom",  "frac_w": 0.25},
        ]},
    ],
    2: [  # 2BR large
        {"row_frac_d": 0.22, "rooms": [
            {"type": "foyer",   "frac_w": 0.25},
            {"type": "living",  "frac_w": 0.75},
        ]},
        {"row_frac_d": 0.28, "rooms": [
            {"type": "kitchen", "frac_w": 0.45},
            {"type": "dining",  "frac_w": 0.35},
            {"type": "pantry",  "frac_w": 0.20},
        ]},
        {"row_frac_d": 0.15, "rooms": [
            {"type": "mudroom",  "frac_w": 0.35},
            {"type": "laundry",  "frac_w": 0.30},
            {"type": "bathroom", "frac_w": 0.35},
        ]},
        {"row_frac_d": 0.35, "rooms": [
            {"type": "family_room", "frac_w": 0.55},
            {"type": "office",      "frac_w": 0.45},
        ]},
    ],
    3: [  # 3BR large (e.g. 5200 sqft 2-story = ~2600 sqft per floor)
        {"row_frac_d": 0.18, "rooms": [
            {"type": "foyer",   "frac_w": 0.28},
            {"type": "living",  "frac_w": 0.72},
        ]},
        {"row_frac_d": 0.25, "rooms": [
            {"type": "kitchen",     "frac_w": 0.42},
            {"type": "dining",      "frac_w": 0.33},
            {"type": "pantry",      "frac_w": 0.25},
        ]},
        {"row_frac_d": 0.15, "rooms": [
            {"type": "mudroom",  "frac_w": 0.28},
            {"type": "laundry",  "frac_w": 0.32},
            {"type": "bathroom", "frac_w": 0.40},
        ]},
        {"row_frac_d": 0.42, "rooms": [
            {"type": "family_room", "frac_w": 0.55},
            {"type": "office",      "frac_w": 0.45},
        ]},
    ],
    4: [  # 4BR large
        {"row_frac_d": 0.16, "rooms": [
            {"type": "foyer",   "frac_w": 0.22},
            {"type": "living",  "frac_w": 0.78},
        ]},
        {"row_frac_d": 0.22, "rooms": [
            {"type": "kitchen",     "frac_w": 0.38},
            {"type": "dining",      "frac_w": 0.32},
            {"type": "pantry",      "frac_w": 0.18},
            {"type": "mudroom",     "frac_w": 0.12},
        ]},
        {"row_frac_d": 0.14, "rooms": [
            {"type": "laundry",  "frac_w": 0.30},
            {"type": "bathroom", "frac_w": 0.28},
            {"type": "office",   "frac_w": 0.42},
        ]},
        {"row_frac_d": 0.48, "rooms": [
            {"type": "family_room", "frac_w": 0.42},
            {"type": "media_room",  "frac_w": 0.30},
            {"type": "bonus_room",  "frac_w": 0.28},
        ]},
    ],
    5: [  # 5BR large / luxury
        {"row_frac_d": 0.14, "rooms": [
            {"type": "foyer",   "frac_w": 0.20},
            {"type": "living",  "frac_w": 0.50},
            {"type": "library", "frac_w": 0.30},
        ]},
        {"row_frac_d": 0.20, "rooms": [
            {"type": "kitchen",     "frac_w": 0.35},
            {"type": "dining",      "frac_w": 0.30},
            {"type": "pantry",      "frac_w": 0.15},
            {"type": "mudroom",     "frac_w": 0.20},
        ]},
        {"row_frac_d": 0.14, "rooms": [
            {"type": "laundry",  "frac_w": 0.28},
            {"type": "bathroom", "frac_w": 0.24},
            {"type": "office",   "frac_w": 0.48},
        ]},
        {"row_frac_d": 0.52, "rooms": [
            {"type": "family_room", "frac_w": 0.35},
            {"type": "media_room",  "frac_w": 0.28},
            {"type": "gym",         "frac_w": 0.20},
            {"type": "bonus_room",  "frac_w": 0.17},
        ]},
    ],
}

# ── Large-house UPPER FLOOR programs (>150 m² per floor) ─────────────────────
# Private spaces: bedrooms, bathrooms, walk-in closets, bonus rooms, loft
SFR_UPPER_LARGE: Dict[int, List[Dict]] = {
    1: [  # 1BR large upper
        {"row_frac_d": 0.60, "rooms": [
            {"type": "bedroom",         "frac_w": 0.55},
            {"type": "bathroom",        "frac_w": 0.25},
            {"type": "walk_in_closet",  "frac_w": 0.20},
        ]},
        {"row_frac_d": 0.40, "rooms": [
            {"type": "loft",       "frac_w": 0.55},
            {"type": "bonus_room", "frac_w": 0.45},
        ]},
    ],
    2: [  # 2BR large upper
        {"row_frac_d": 0.50, "rooms": [
            {"type": "bedroom",         "frac_w": 0.42},  # master
            {"type": "bathroom",        "frac_w": 0.22},  # master bath
            {"type": "walk_in_closet",  "frac_w": 0.16},
            {"type": "bedroom",         "frac_w": 0.20},
        ]},
        {"row_frac_d": 0.50, "rooms": [
            {"type": "bathroom",   "frac_w": 0.30},
            {"type": "loft",       "frac_w": 0.40},
            {"type": "bonus_room", "frac_w": 0.30},
        ]},
    ],
    3: [  # 3BR large upper
        {"row_frac_d": 0.38, "rooms": [
            {"type": "bedroom",         "frac_w": 0.36},  # master
            {"type": "bathroom",        "frac_w": 0.18},  # master bath
            {"type": "walk_in_closet",  "frac_w": 0.14},
            {"type": "bedroom",         "frac_w": 0.32},  # bedroom 2
        ]},
        {"row_frac_d": 0.35, "rooms": [
            {"type": "bedroom",    "frac_w": 0.35},  # bedroom 3
            {"type": "bathroom",   "frac_w": 0.22},  # shared bath 2
            {"type": "bonus_room", "frac_w": 0.43},
        ]},
        {"row_frac_d": 0.27, "rooms": [
            {"type": "loft",       "frac_w": 0.50},
            {"type": "media_room", "frac_w": 0.50},
        ]},
    ],
    4: [  # 4BR large upper
        {"row_frac_d": 0.35, "rooms": [
            {"type": "bedroom",         "frac_w": 0.30},  # master
            {"type": "bathroom",        "frac_w": 0.16},  # master bath
            {"type": "walk_in_closet",  "frac_w": 0.12},
            {"type": "bedroom",         "frac_w": 0.22},  # br2
            {"type": "bedroom",         "frac_w": 0.20},  # br3
        ]},
        {"row_frac_d": 0.35, "rooms": [
            {"type": "bedroom",    "frac_w": 0.24},  # br4
            {"type": "bathroom",   "frac_w": 0.18},
            {"type": "bathroom",   "frac_w": 0.18},
            {"type": "bonus_room", "frac_w": 0.40},
        ]},
        {"row_frac_d": 0.30, "rooms": [
            {"type": "loft",       "frac_w": 0.50},
            {"type": "media_room", "frac_w": 0.50},
        ]},
    ],
    5: [  # 5BR large upper
        {"row_frac_d": 0.32, "rooms": [
            {"type": "bedroom",         "frac_w": 0.26},  # master suite
            {"type": "bathroom",        "frac_w": 0.14},  # master bath
            {"type": "walk_in_closet",  "frac_w": 0.10},
            {"type": "bedroom",         "frac_w": 0.22},  # br2
            {"type": "bedroom",         "frac_w": 0.28},  # br3
        ]},
        {"row_frac_d": 0.33, "rooms": [
            {"type": "bedroom",    "frac_w": 0.20},  # br4
            {"type": "bedroom",    "frac_w": 0.20},  # br5
            {"type": "bathroom",   "frac_w": 0.16},
            {"type": "bathroom",   "frac_w": 0.16},
            {"type": "bonus_room", "frac_w": 0.28},
        ]},
        {"row_frac_d": 0.35, "rooms": [
            {"type": "loft",       "frac_w": 0.35},
            {"type": "media_room", "frac_w": 0.35},
            {"type": "gym",        "frac_w": 0.30},
        ]},
    ],
}

# Threshold: floor plate above this uses expanded large-house programs
LARGE_HOUSE_THRESHOLD_M2 = 150.0  # ~1615 sqft per floor

# For multi-story SFR: floor 0 is public, floor 1+ is private (bedrooms)
SFR_GROUND_ROWS = {  # standard — keyed by bedrooms
    1: [SFR_PROGRAMS[1][0], SFR_PROGRAMS[1][1]],
    2: [SFR_PROGRAMS[2][0], SFR_PROGRAMS[2][1]],
    3: [SFR_PROGRAMS[3][0], SFR_PROGRAMS[3][1]],
    4: [SFR_PROGRAMS[4][0], SFR_PROGRAMS[4][1]],
    5: [SFR_PROGRAMS[5][0], SFR_PROGRAMS[5][1]],
}
SFR_UPPER_ROWS = {  # standard
    1: [SFR_PROGRAMS[1][2]],
    2: [SFR_PROGRAMS[2][2]],
    3: [SFR_PROGRAMS[3][2]],
    4: [SFR_PROGRAMS[4][2]],
    5: [SFR_PROGRAMS[5][2]],
}

CORRIDOR_WIDTH_M = 1.8
STAIR_W_M = 3.0
STAIR_D_M = 5.0


class FloorplanGenerator:

    def generate(
        self,
        massing_option: Dict[str, Any],
        spec: ProjectSpec,
        levels: List[Level],
    ) -> Tuple[List[Room], List[Wall]]:

        footprint_coords = massing_option["footprint"]
        footprint = Polygon(footprint_coords)
        bounds = footprint.bounds
        w = bounds[2] - bounds[0]
        d = bounds[3] - bounds[1]

        all_rooms: List[Room] = []
        all_walls: List[Wall] = []

        is_sfr = getattr(spec, 'building_use', None) in ('single_family', BuildingUse.single_family)
        bedrooms = getattr(spec, 'bedrooms', None) or 3

        for level in levels:
            if is_sfr:
                rooms, walls = self._layout_sfr_floor(footprint, bounds, w, d, level, levels, bedrooms)
            else:
                rooms, walls = self._layout_floor(footprint, bounds, w, d, level, spec)
            all_rooms.extend(rooms)
            all_walls.extend(walls)

        return all_rooms, all_walls

    def _layout_floor(
        self, footprint, bounds, w, d, level: Level, spec: ProjectSpec
    ) -> Tuple[List[Room], List[Wall]]:
        rooms = []
        walls = []
        lvl = level.index
        minx, miny, maxx, maxy = bounds

        stair_x = minx + (w - STAIR_W_M) / 2
        stair_y = miny
        raw_stair = Polygon([
            [stair_x, stair_y],
            [stair_x + STAIR_W_M, stair_y],
            [stair_x + STAIR_W_M, stair_y + STAIR_D_M],
            [stair_x, stair_y + STAIR_D_M],
        ])
        fp_interior_mf = footprint.buffer(-FP_INSET)
        try:
            cs = fp_interior_mf.intersection(raw_stair)
            if hasattr(cs, 'geoms'):
                cs = max(cs.geoms, key=lambda g: g.area)
            stair_poly = [[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]] if (not cs.is_empty and hasattr(cs, 'exterior')) else [[c[0], c[1]] for c in raw_stair.exterior.coords[:-1]]
        except Exception:
            stair_poly = [[c[0], c[1]] for c in raw_stair.exterior.coords[:-1]]
        rooms.append(Room(
            id=f"stair_{lvl}",
            type="stair",
            polygon=stair_poly,
            level=lvl,
            area_sqft=STAIR_W_M * STAIR_D_M * 10.764,
        ))

        corr_y = miny + STAIR_D_M
        raw_corr = Polygon([
            [minx, corr_y],
            [maxx, corr_y],
            [maxx, corr_y + CORRIDOR_WIDTH_M],
            [minx, corr_y + CORRIDOR_WIDTH_M],
        ])
        try:
            cc = fp_interior_mf.intersection(raw_corr)
            if hasattr(cc, 'geoms'):
                cc = max(cc.geoms, key=lambda g: g.area)
            corridor_poly = [[c[0], c[1]] for c in list(cc.exterior.coords)[:-1]] if (not cc.is_empty and hasattr(cc, 'exterior')) else [[c[0], c[1]] for c in raw_corr.exterior.coords[:-1]]
        except Exception:
            corridor_poly = [[c[0], c[1]] for c in raw_corr.exterior.coords[:-1]]
        rooms.append(Room(
            id=f"corridor_{lvl}",
            type="corridor",
            polygon=corridor_poly,
            level=lvl,
            area_sqft=w * CORRIDOR_WIDTH_M * 10.764,
        ))

        unit_start_y_above = corr_y + CORRIDOR_WIDTH_M
        unit_mix = self._determine_unit_mix(w, d - STAIR_D_M - CORRIDOR_WIDTH_M)
        unit_idx = 0
        cursor_x = minx

        for unit_type, count in unit_mix.items():
            tmpl = UNIT_TEMPLATES[unit_type]
            for _ in range(count):
                if cursor_x + tmpl["w"] > maxx:
                    break
                uid = f"unit_{unit_type}_{lvl}_{unit_idx}"
                ux, uy = cursor_x, unit_start_y_above
                uw, ud = tmpl["w"], min(tmpl["d"], maxy - uy)
                if ud < 3:
                    cursor_x += tmpl["w"]
                    unit_idx += 1
                    continue

                raw_poly = [
                    [ux, uy], [ux + uw, uy],
                    [ux + uw, uy + ud], [ux, uy + ud],
                ]
                unit_shape = Polygon(raw_poly)
                try:
                    clipped = footprint.buffer(-FP_INSET).intersection(unit_shape)
                except Exception:
                    cursor_x += tmpl["w"]; unit_idx += 1; continue
                if hasattr(clipped, 'geoms'):
                    clipped = max(clipped.geoms, key=lambda g: g.area)
                if clipped.is_empty or not hasattr(clipped, 'exterior') or clipped.area < 6.0:
                    cursor_x += tmpl["w"]
                    unit_idx += 1
                    continue
                unit_poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                rooms.append(Room(
                    id=uid,
                    type="unit",
                    unit_id=uid,
                    polygon=unit_poly,
                    level=lvl,
                    area_sqft=clipped.area * 10.764,
                ))

                # Pass fp_interior so every sub-room is clipped to the actual
                # footprint polygon — no room can extend outside the walls.
                cb = clipped.bounds
                sub_rooms = self._place_unit_rooms(uid, cb[0], cb[1], cb[2]-cb[0], cb[3]-cb[1], tmpl, lvl, fp_interior=fp_interior_mf)
                rooms.extend(sub_rooms)

                raw_wet = self._place_wet_walls(cb[0], cb[1], cb[2]-cb[0], cb[3]-cb[1], tmpl, lvl)
                # Clip every unit wall to the actual footprint interior
                for w in raw_wet:
                    wl = LineString([w.start, w.end])
                    try:
                        cw = fp_interior_mf.intersection(wl)
                        segs = [cw] if hasattr(cw, 'coords') else (list(cw.geoms) if hasattr(cw, 'geoms') else [])
                        for seg in segs:
                            if hasattr(seg, 'coords'):
                                wc = list(seg.coords)
                                if len(wc) >= 2:
                                    walls.append(Wall(
                                        id=f"unit_wall_{uuid.uuid4().hex[:6]}",
                                        start=[wc[0][0], wc[0][1]], end=[wc[-1][0], wc[-1][1]],
                                        height_ft=w.height_ft, level=lvl, is_exterior=False,
                                    ))
                    except Exception:
                        walls.append(w)

                cursor_x += uw
                unit_idx += 1

        ext_walls = self._place_exterior_walls(footprint, level)
        walls.extend(ext_walls)

        return rooms, walls

    def _determine_unit_mix(self, building_w: float, usable_depth: float) -> Dict[str, int]:
        mix = {}
        slots = int(building_w / UNIT_TEMPLATES["1br"]["w"])
        two_br_count = max(0, slots // 3)
        one_br_count = slots - two_br_count
        mix["2br"] = two_br_count
        mix["1br"] = one_br_count
        mix["studio"] = 0
        return mix

    def _place_unit_rooms(self, uid, ux, uy, uw, ud, tmpl, lvl, fp_interior=None) -> List[Room]:
        """Place sub-rooms inside a unit using row-based layout.
        Each row is a horizontal band; rooms within a row are side-by-side.
        fp_interior: if provided, each room cell is intersected with the actual
        footprint interior so rooms never extend outside the building walls."""
        rooms = []
        y_cursor = uy
        for row in tmpl.get("rows", []):
            row_d = ud * row["frac_d"]
            x_cursor = ux
            for rdef in row.get("rooms", []):
                rw = uw * rdef["frac_w"]
                cell = Polygon([
                    [x_cursor,        y_cursor],
                    [x_cursor + rw,   y_cursor],
                    [x_cursor + rw,   y_cursor + row_d],
                    [x_cursor,        y_cursor + row_d],
                ])
                if fp_interior is not None:
                    try:
                        clipped = fp_interior.intersection(cell)
                        if hasattr(clipped, 'geoms'):
                            clipped = max(clipped.geoms, key=lambda g: g.area)
                        if clipped.is_empty or not hasattr(clipped, 'exterior') or clipped.area < 1.0:
                            x_cursor += rw
                            continue
                        poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                        area = clipped.area * 10.764
                    except Exception:
                        x_cursor += rw
                        continue
                else:
                    poly = [[c[0], c[1]] for c in cell.exterior.coords[:-1]]
                    area = rw * row_d * 10.764
                rooms.append(Room(
                    id=f"{uid}_{rdef['type']}_{uuid.uuid4().hex[:4]}",
                    type=rdef["type"],
                    unit_id=uid,
                    polygon=poly,
                    level=lvl,
                    area_sqft=area,
                ))
                x_cursor += rw
            y_cursor += row_d
        return rooms

    def _place_wet_walls(self, ux, uy, uw, ud, tmpl, lvl) -> List[Wall]:
        """Walls between all rooms in a unit:
        - Vertical walls between side-by-side rooms in the same row
        - Horizontal walls at every row boundary (separating living/kitchen/bedroom rows)
        The last row's bottom edge is the unit exterior — no wall there."""
        walls = []
        y_cursor = uy
        rows = tmpl.get("rows", [])
        for row_i, row in enumerate(rows):
            row_d = ud * row["frac_d"]
            row_rooms = row.get("rooms", [])

            # Vertical walls between side-by-side rooms in this row
            x_cursor = ux
            for rdef in row_rooms[:-1]:
                x_cursor += uw * rdef["frac_w"]
                walls.append(Wall(
                    id=f"unit_vwall_{uuid.uuid4().hex[:6]}",
                    start=[x_cursor, y_cursor],
                    end=[x_cursor, y_cursor + row_d],
                    height_ft=9.0, level=lvl, is_exterior=False,
                ))

            # Horizontal wall at the bottom of this row (between this row and the next)
            if row_i < len(rows) - 1:
                walls.append(Wall(
                    id=f"unit_hwall_{uuid.uuid4().hex[:6]}",
                    start=[ux,      y_cursor + row_d],
                    end=[ux + uw,   y_cursor + row_d],
                    height_ft=9.0, level=lvl, is_exterior=False,
                ))

            y_cursor += row_d
        return walls

    def _place_exterior_walls(self, footprint, level: Level) -> List[Wall]:
        walls = []
        coords = list(footprint.exterior.coords)
        for i in range(len(coords) - 1):
            walls.append(Wall(
                id=f"ext_wall_{level.index}_{i}",
                start=list(coords[i]),
                end=list(coords[i + 1]),
                height_ft=level.height_ft,
                level=level.index,
                is_exterior=True,
            ))
        return walls

    # ── Single-family residential layout ─────────────────────────────────────
    def _layout_sfr_floor(
        self, footprint, bounds, w, d, level: Level,
        all_levels: List[Level], bedrooms: int,
    ) -> Tuple[List[Room], List[Wall]]:
        rooms: List[Room] = []
        walls: List[Wall] = []
        lvl = level.index
        minx, miny, maxx, maxy = bounds
        n_floors = len(all_levels)
        br = max(1, min(5, bedrooms))

        floor_area_m2 = footprint.area
        use_large = floor_area_m2 > LARGE_HOUSE_THRESHOLD_M2

        # Select which row program to use for this floor
        if n_floors == 1:
            if use_large:
                # Single-story large: combine ground + upper programs
                ground = SFR_GROUND_LARGE.get(br, SFR_PROGRAMS[br])
                upper = SFR_UPPER_LARGE.get(br, [])
                combined = ground + upper
                total = sum(r["row_frac_d"] for r in combined)
                row_program = [{**r, "row_frac_d": r["row_frac_d"] / total} for r in combined]
            else:
                row_program = SFR_PROGRAMS[br]
        elif lvl == 0:
            if use_large:
                row_program = SFR_GROUND_LARGE.get(br, SFR_PROGRAMS[br])
            else:
                row_program = SFR_GROUND_ROWS[br]
            total = sum(r["row_frac_d"] for r in row_program)
            row_program = [{**r, "row_frac_d": r["row_frac_d"] / total} for r in row_program]
        else:
            if use_large:
                row_program = SFR_UPPER_LARGE.get(br, SFR_UPPER_ROWS[br])
            else:
                row_program = SFR_UPPER_ROWS[br]
            total = sum(r["row_frac_d"] for r in row_program)
            row_program = [{**r, "row_frac_d": r["row_frac_d"] / total} for r in row_program]

        # One canonical interior boundary — everything must have its center inside this.
        fp_interior = footprint.buffer(-FP_INSET)

        y_cursor = miny
        for row in row_program:
            row_d = d * row["row_frac_d"]
            row_y0 = y_cursor
            row_y1 = y_cursor + row_d
            x_cursor = minx
            for rdef in row["rooms"]:
                rw = w * rdef["frac_w"]
                rx0, rx1 = x_cursor, x_cursor + rw
                cell_cx = (rx0 + rx1) / 2
                cell_cz = (row_y0 + row_y1) / 2
                if not fp_interior.contains(Point(cell_cx, cell_cz)):
                    x_cursor += rw
                    continue
                # Cell center is inside — keep the room as a clean rectangle
                poly = [[rx0, row_y0], [rx1, row_y0], [rx1, row_y1], [rx0, row_y1]]
                rooms.append(Room(
                    id=f"sfr_{rdef['type']}_{lvl}_{uuid.uuid4().hex[:5]}",
                    type=rdef["type"],
                    unit_id="house",
                    polygon=poly, level=lvl,
                    area_sqft=rw * row_d * 10.764,
                ))
                if x_cursor > minx + 0.5:
                    # Column wall — clip to fp_interior (same as row walls)
                    col_line = LineString([[rx0, row_y0], [rx0, row_y1]])
                    try:
                        clipped_col = fp_interior.intersection(col_line)
                        segs = [clipped_col] if hasattr(clipped_col, 'coords') else (list(clipped_col.geoms) if hasattr(clipped_col, 'geoms') else [])
                        for seg in segs:
                            if hasattr(seg, 'coords'):
                                wc = list(seg.coords)
                                if len(wc) >= 2:
                                    walls.append(Wall(
                                        id=f"int_wall_{lvl}_{uuid.uuid4().hex[:5]}",
                                        start=[wc[0][0], wc[0][1]], end=[wc[-1][0], wc[-1][1]],
                                        height_ft=level.height_ft, level=lvl, is_exterior=False,
                                    ))
                    except Exception:
                        pass
                x_cursor += rw
            if row_y1 < maxy - 0.5:
                # Interior row wall — clip to footprint to avoid overrun in L/U shapes
                wall_line = LineString([[minx, row_y1], [maxx, row_y1]])
                try:
                    clipped_wall = fp_interior.intersection(wall_line)
                    segs = [clipped_wall] if hasattr(clipped_wall, 'coords') else (list(clipped_wall.geoms) if hasattr(clipped_wall, 'geoms') else [])
                    for seg in segs:
                        if hasattr(seg, 'coords'):
                            wc = list(seg.coords)
                            if len(wc) >= 2:
                                walls.append(Wall(
                                    id=f"row_wall_{lvl}_{uuid.uuid4().hex[:5]}",
                                    start=[wc[0][0], wc[0][1]], end=[wc[-1][0], wc[-1][1]],
                                    height_ft=level.height_ft, level=lvl, is_exterior=False,
                                ))
                except Exception:
                    pass
            y_cursor += row_d

        ext_walls = self._place_exterior_walls(footprint, level)
        walls.extend(ext_walls)
        return rooms, walls
