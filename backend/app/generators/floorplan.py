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
from shapely.geometry import shape, Polygon, box, LineString
from shapely.ops import transform
import pyproj

from app.models.schemas import Room, Wall, ProjectSpec, Level
from app.constants import BuildingUse, SFR_SQFT_RANGES, PRIORITY_SQFT_POSITION, sfr_target_sqft

# ── Multi-family unit templates ───────────────────────────────────────────────
UNIT_TEMPLATES = {
    "studio": {
        "w": 6.0, "d": 8.0, "area_sqft": 480,
        "rooms": [
            {"type": "living",   "frac_w": 1.0, "frac_d": 0.55},
            {"type": "kitchen",  "frac_w": 0.5, "frac_d": 0.25},
            {"type": "bathroom", "frac_w": 0.5, "frac_d": 0.25},
        ]
    },
    "1br": {
        "w": 7.5, "d": 9.0, "area_sqft": 720,
        "rooms": [
            {"type": "living",   "frac_w": 1.0, "frac_d": 0.45},
            {"type": "kitchen",  "frac_w": 0.5, "frac_d": 0.25},
            {"type": "bathroom", "frac_w": 0.4, "frac_d": 0.30},
            {"type": "bedroom",  "frac_w": 0.6, "frac_d": 0.30},
        ]
    },
    "2br": {
        "w": 9.0, "d": 10.0, "area_sqft": 960,
        "rooms": [
            {"type": "living",   "frac_w": 1.0, "frac_d": 0.40},
            {"type": "kitchen",  "frac_w": 0.5, "frac_d": 0.25},
            {"type": "bathroom", "frac_w": 0.4, "frac_d": 0.20},
            {"type": "bedroom",  "frac_w": 0.5, "frac_d": 0.35},
            {"type": "bedroom",  "frac_w": 0.5, "frac_d": 0.35},
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
        stair_poly = [
            [stair_x, stair_y],
            [stair_x + STAIR_W_M, stair_y],
            [stair_x + STAIR_W_M, stair_y + STAIR_D_M],
            [stair_x, stair_y + STAIR_D_M],
        ]
        rooms.append(Room(
            id=f"stair_{lvl}",
            type="stair",
            polygon=stair_poly,
            level=lvl,
            area_sqft=STAIR_W_M * STAIR_D_M * 10.764,
        ))

        corr_y = miny + STAIR_D_M
        corridor_poly = [
            [minx, corr_y],
            [maxx, corr_y],
            [maxx, corr_y + CORRIDOR_WIDTH_M],
            [minx, corr_y + CORRIDOR_WIDTH_M],
        ]
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
                    clipped = footprint.buffer(-0.05).intersection(unit_shape)
                except Exception:
                    clipped = unit_shape
                if hasattr(clipped, 'geoms'):
                    clipped = max(clipped.geoms, key=lambda g: g.area)
                if clipped.is_empty or clipped.area < 6.0:
                    cursor_x += tmpl["w"]
                    unit_idx += 1
                    continue
                if hasattr(clipped, 'exterior'):
                    unit_poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                else:
                    unit_poly = raw_poly
                rooms.append(Room(
                    id=uid,
                    type="unit",
                    unit_id=uid,
                    polygon=unit_poly,
                    level=lvl,
                    area_sqft=clipped.area * 10.764,
                ))

                sub_rooms = self._place_unit_rooms(uid, ux, uy, uw, ud, tmpl, lvl)
                rooms.extend(sub_rooms)

                wet_walls = self._place_wet_walls(ux, uy, uw, ud, tmpl, lvl)
                walls.extend(wet_walls)

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

    def _place_unit_rooms(self, uid, ux, uy, uw, ud, tmpl, lvl) -> List[Room]:
        rooms = []
        y_cursor = uy
        for rdef in tmpl["rooms"]:
            rw = uw * rdef["frac_w"]
            rd = ud * rdef["frac_d"]
            if y_cursor + rd > uy + ud + 0.01:
                break
            poly = [[ux, y_cursor], [ux + rw, y_cursor],
                    [ux + rw, y_cursor + rd], [ux, y_cursor + rd]]
            rooms.append(Room(
                id=f"{uid}_{rdef['type']}_{uuid.uuid4().hex[:4]}",
                type=rdef["type"],
                unit_id=uid,
                polygon=poly,
                level=lvl,
                area_sqft=rw * rd * 10.764,
            ))
            y_cursor += rd
        return rooms

    def _place_wet_walls(self, ux, uy, uw, ud, tmpl, lvl) -> List[Wall]:
        walls = []
        wx = ux + uw * 0.6
        walls.append(Wall(
            id=f"wet_wall_{uuid.uuid4().hex[:6]}",
            start=[wx, uy],
            end=[wx, uy + ud * 0.5],
            height_ft=9.0,
            level=lvl,
            is_exterior=False,
        ))
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

        y_cursor = miny
        for row in row_program:
            row_d = d * row["row_frac_d"]
            row_y0 = y_cursor
            row_y1 = y_cursor + row_d
            x_cursor = minx
            for rdef in row["rooms"]:
                rw = w * rdef["frac_w"]
                rx0, rx1 = x_cursor, x_cursor + rw
                cell = Polygon([[rx0, row_y0], [rx1, row_y0], [rx1, row_y1], [rx0, row_y1]])
                try:
                    clipped = footprint.buffer(-0.05).intersection(cell)
                except Exception:
                    clipped = cell
                if hasattr(clipped, 'geoms'):
                    clipped = max(clipped.geoms, key=lambda g: g.area)
                if clipped.is_empty or clipped.area < 2.0:
                    x_cursor += rw
                    continue
                if hasattr(clipped, 'exterior'):
                    poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                else:
                    poly = [[rx0, row_y0], [rx1, row_y0], [rx1, row_y1], [rx0, row_y1]]
                room_id = f"sfr_{rdef['type']}_{lvl}_{uuid.uuid4().hex[:5]}"
                rooms.append(Room(
                    id=room_id, type=rdef["type"],
                    unit_id="house",
                    polygon=poly, level=lvl,
                    area_sqft=clipped.area * 10.764,
                ))
                if x_cursor > minx + 0.5:
                    walls.append(Wall(
                        id=f"int_wall_{lvl}_{uuid.uuid4().hex[:5]}",
                        start=[rx0, row_y0], end=[rx0, row_y1],
                        height_ft=level.height_ft, level=lvl, is_exterior=False,
                    ))
                x_cursor += rw
            if row_y1 < maxy - 0.5:
                walls.append(Wall(
                    id=f"row_wall_{lvl}_{uuid.uuid4().hex[:5]}",
                    start=[minx, row_y1], end=[maxx, row_y1],
                    height_ft=level.height_ft, level=lvl, is_exterior=False,
                ))
            y_cursor += row_d

        ext_walls = self._place_exterior_walls(footprint, level)
        walls.extend(ext_walls)
        return rooms, walls
