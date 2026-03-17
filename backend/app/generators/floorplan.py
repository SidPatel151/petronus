"""
FloorplanGenerator
Places unit templates + corridor + stair core inside chosen massing footprint.
Multi-family residential, ≤ 3 stories.
"""
import uuid
import math
from typing import List, Tuple, Dict, Any
from shapely.geometry import shape, Polygon, box, LineString
from shapely.ops import transform
import pyproj

from app.models.schemas import Room, Wall, ProjectSpec, Level

# Unit templates (width x depth in meters, room breakdown)
UNIT_TEMPLATES = {
    "studio": {
        "w": 6.0, "d": 8.0, "area_sqft": 480,
        "rooms": [
            {"type": "living", "frac_w": 1.0, "frac_d": 0.55},
            {"type": "kitchen", "frac_w": 0.5, "frac_d": 0.25},
            {"type": "bathroom", "frac_w": 0.5, "frac_d": 0.25},
        ]
    },
    "1br": {
        "w": 7.5, "d": 9.0, "area_sqft": 720,
        "rooms": [
            {"type": "living", "frac_w": 1.0, "frac_d": 0.45},
            {"type": "kitchen", "frac_w": 0.5, "frac_d": 0.25},
            {"type": "bathroom", "frac_w": 0.4, "frac_d": 0.3},
            {"type": "bedroom", "frac_w": 0.6, "frac_d": 0.3},
        ]
    },
    "2br": {
        "w": 9.0, "d": 10.0, "area_sqft": 960,
        "rooms": [
            {"type": "living", "frac_w": 1.0, "frac_d": 0.4},
            {"type": "kitchen", "frac_w": 0.5, "frac_d": 0.25},
            {"type": "bathroom", "frac_w": 0.4, "frac_d": 0.2},
            {"type": "bedroom", "frac_w": 0.5, "frac_d": 0.35},
            {"type": "bedroom", "frac_w": 0.5, "frac_d": 0.35},
        ]
    },
}

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

        for level in levels:
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
