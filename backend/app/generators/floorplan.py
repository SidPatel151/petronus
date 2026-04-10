"""
FloorplanGenerator
Two modes:
  - Multi-family: corridor + unit cells (studio/1BR/2BR).
  - Single-family: whole-house room program keyed by bedroom count (1–5 BR),
    following real residential typology (Neufert / DeChiara proportions).
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
# Each entry is a list of rows; each row is a list of room dicts with frac_w.
# frac_d is the fraction of total depth this row consumes.
# Rooms within a row share the row height and are placed left→right by frac_w.
# Based on Neufert/DeChiara space standards + typical CA residential practice.
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
            {"type": "bedroom",  "frac_w": 1.0},   # single bedroom rear
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
            {"type": "bedroom",  "frac_w": 0.55},  # master
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

# For multi-story SFR: floor 0 is public, floor 1+ is private (bedrooms)
SFR_GROUND_ROWS = {  # keyed by bedrooms — public-only zone for level 0
    1: [SFR_PROGRAMS[1][0], SFR_PROGRAMS[1][1]],
    2: [SFR_PROGRAMS[2][0], SFR_PROGRAMS[2][1]],
    3: [SFR_PROGRAMS[3][0], SFR_PROGRAMS[3][1]],
    4: [SFR_PROGRAMS[4][0], SFR_PROGRAMS[4][1]],
    5: [SFR_PROGRAMS[5][0], SFR_PROGRAMS[5][1]],
}
SFR_UPPER_ROWS = {  # private zone on upper floors
    1: [SFR_PROGRAMS[1][2]],
    2: [SFR_PROGRAMS[2][2]],
    3: [SFR_PROGRAMS[3][2]],
    4: [SFR_PROGRAMS[4][2]],
    5: [SFR_PROGRAMS[5][2]],
}

# SFR_SQFT_RANGES, sfr_target_sqft imported from app.constants above

CORRIDOR_WIDTH_M = 1.8   # 6 ft min per code
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
        bounds = footprint.bounds  # minx miny maxx maxy
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

        # 1. Place stair core (near center-end)
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

        # 2. Corridor spine (runs length of building)
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

        # 3. Pack units above and below corridor
        unit_start_y_above = corr_y + CORRIDOR_WIDTH_M
        unit_start_y_below = corr_y  # units below corridor (front-facing)

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
                # Clip to actual footprint — prevents rooms in L-shape cutouts
                unit_shape = Polygon(raw_poly)
                try:
                    clipped = footprint.buffer(-0.05).intersection(unit_shape)
                except Exception:
                    clipped = unit_shape
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

                # Sub-rooms inside unit
                sub_rooms = self._place_unit_rooms(uid, ux, uy, uw, ud, tmpl, lvl)
                rooms.extend(sub_rooms)

                # Wet walls (bathrooms/kitchen share a wall)
                wet_walls = self._place_wet_walls(ux, uy, uw, ud, tmpl, lvl)
                walls.extend(wet_walls)

                cursor_x += uw
                unit_idx += 1

        # 4. Exterior walls
        ext_walls = self._place_exterior_walls(footprint, level)
        walls.extend(ext_walls)

        return rooms, walls

    def _determine_unit_mix(self, building_w: float, usable_depth: float) -> Dict[str, int]:
        """Simple heuristic: mostly 1BRs, some 2BRs if wide enough"""
        mix = {}
        slots = int(building_w / UNIT_TEMPLATES["1br"]["w"])
        two_br_count = max(0, slots // 3)
        one_br_count = slots - two_br_count
        studio_count = 0
        mix["2br"] = two_br_count
        mix["1br"] = one_br_count
        mix["studio"] = studio_count
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
            y_cursor += rd  # advance to next room's position
        return rooms

    def _place_wet_walls(self, ux, uy, uw, ud, tmpl, lvl) -> List[Wall]:
        walls = []
        # Vertical partition where bathroom meets kitchen (1/3 from right)
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
        """
        Lays out a single-family house using real residential room programs
        (SFR_PROGRAMS). Multi-story: ground floor = public spaces, upper
        floors = private (bedrooms/bathrooms).
        Rows run front→back (min_y → max_y). Each row's rooms run left→right.
        """
        rooms: List[Room] = []
        walls: List[Wall] = []
        lvl = level.index
        minx, miny, maxx, maxy = bounds
        n_floors = len(all_levels)
        br = max(1, min(5, bedrooms))

        # Select which row program to use for this floor
        if n_floors == 1:
            row_program = SFR_PROGRAMS[br]
        elif lvl == 0:
            # Ground: public spaces only (living, kitchen, dining, laundry)
            row_program = SFR_GROUND_ROWS[br]
            # Renormalize row frac_d so they fill the full floor depth
            total = sum(r["row_frac_d"] for r in row_program)
            row_program = [{**r, "row_frac_d": r["row_frac_d"] / total} for r in row_program]
        else:
            # Upper: private spaces (bedrooms, bathrooms)
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
                # Clip to footprint for non-rectangular shapes (U-shape etc.)
                cell = Polygon([[rx0, row_y0], [rx1, row_y0], [rx1, row_y1], [rx0, row_y1]])
                try:
                    clipped = footprint.buffer(-0.05).intersection(cell)
                except Exception:
                    clipped = cell
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
                # Interior partition wall on left edge of each room (except first)
                if x_cursor > minx + 0.5:
                    walls.append(Wall(
                        id=f"int_wall_{lvl}_{uuid.uuid4().hex[:5]}",
                        start=[rx0, row_y0], end=[rx0, row_y1],
                        height_ft=level.height_ft, level=lvl, is_exterior=False,
                    ))
                x_cursor += rw
            # Row divider wall (horizontal partition between rows)
            if row_y1 < maxy - 0.5:
                walls.append(Wall(
                    id=f"row_wall_{lvl}_{uuid.uuid4().hex[:5]}",
                    start=[minx, row_y1], end=[maxx, row_y1],
                    height_ft=level.height_ft, level=lvl, is_exterior=False,
                ))
            y_cursor += row_d

        # Exterior walls
        ext_walls = self._place_exterior_walls(footprint, level)
        walls.extend(ext_walls)
        return rooms, walls
