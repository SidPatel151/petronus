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
LARGE_HOUSE_THRESHOLD_M2 = 80.0  # ~860 sqft per floor

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
        archetype: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Room], List[Wall]]:

        footprint_coords = massing_option["footprint"]
        footprint = Polygon(footprint_coords)
        bounds = footprint.bounds
        w = bounds[2] - bounds[0]
        d = bounds[3] - bounds[1]

        all_rooms: List[Room] = []
        all_walls: List[Wall] = []

        is_sfr = getattr(spec, 'building_use', None) in (
            'single_family', 'adu', BuildingUse.single_family, BuildingUse.adu
        )
        bedrooms = getattr(spec, 'bedrooms', None) or 1

        for level in levels:
            if is_sfr:
                rooms, walls = self._layout_sfr_floor(
                    footprint, bounds, w, d, level, levels, bedrooms, archetype=archetype
                )
            else:
                rooms, walls = self._layout_multifamily_floor(footprint, bounds, w, d, level, spec)
            all_rooms.extend(rooms)
            all_walls.extend(walls)

        return self._carve_vertical_cores(all_rooms), all_walls

    def _carve_vertical_cores(self, rooms: List[Room]) -> List[Room]:
        """Remove stair/core footprints from every overlapping programmed room."""
        cores_by_level: Dict[int, List[Polygon]] = {}
        for room in rooms:
            if room.type == "stair" and len(room.polygon) >= 3:
                cores_by_level.setdefault(room.level, []).append(Polygon(room.polygon))
        if not cores_by_level:
            return rooms
        carved: List[Room] = []
        for room in rooms:
            if room.type == "stair" or room.level not in cores_by_level:
                carved.append(room)
                continue
            remainder = Polygon(room.polygon)
            for core in cores_by_level[room.level]:
                if remainder.intersects(core):
                    remainder = remainder.difference(core.buffer(0.02, join_style=2))
            if hasattr(remainder, "geoms"):
                polygon_parts = [
                    geometry for geometry in remainder.geoms
                    if geometry.geom_type == "Polygon" and geometry.area >= 0.5
                ]
                remainder = max(polygon_parts, key=lambda geometry: geometry.area) if polygon_parts else None
            if remainder is None or remainder.is_empty or not hasattr(remainder, "exterior") or remainder.area < 0.5:
                continue
            carved.append(room.model_copy(update={
                "polygon": [[c[0], c[1]] for c in list(remainder.exterior.coords)[:-1]],
                "area_sqft": remainder.area * 10.764,
            }))
        return carved

    def _find_vertical_core(
        self, interior: Polygon, target_width: float, target_depth: float
    ) -> Optional[Polygon]:
        """Find a repeatable stair/core rectangle inside irregular footprints."""
        if interior.is_empty:
            return None
        if interior.geom_type == "MultiPolygon":
            interior = max(interior.geoms, key=lambda geometry: geometry.area)
        min_x, min_z, max_x, max_z = interior.bounds
        center_x = (min_x + max_x) / 2.0
        center_z = (min_z + max_z) / 2.0
        for scale in (1.0, 0.85, 0.70):
            width = min(target_width * scale, max_x - min_x)
            depth = min(target_depth * scale, max_z - min_z)
            x_positions = [
                center_x - width / 2.0,
                max_x - width,
                min_x,
                min_x + (max_x - min_x - width) * 0.25,
                min_x + (max_x - min_x - width) * 0.75,
            ]
            z_positions = [
                min_z,
                center_z - depth / 2.0,
                max_z - depth,
                min_z + (max_z - min_z - depth) * 0.25,
                min_z + (max_z - min_z - depth) * 0.75,
            ]
            preferred = [
                (x_positions[0], z_positions[0]),
                (x_positions[1], z_positions[0]),
                (x_positions[2], z_positions[0]),
                (x_positions[1], z_positions[1]),
                (x_positions[2], z_positions[1]),
                (x_positions[0], z_positions[1]),
            ]
            seen = set()
            for x0, z0 in preferred + [(x, z) for z in z_positions for x in x_positions]:
                key = (round(x0, 5), round(z0, 5))
                if key in seen:
                    continue
                seen.add(key)
                candidate = Polygon([
                    [x0, z0], [x0 + width, z0],
                    [x0 + width, z0 + depth], [x0, z0 + depth],
                ])
                if interior.covers(candidate):
                    return candidate
        return None

    def _layout_multifamily_floor(
        self, footprint: Polygon, bounds, w: float, d: float,
        level: Level, spec: ProjectSpec,
    ) -> Tuple[List[Room], List[Wall]]:
        """Lay out a complete double-loaded multifamily floor.

        Rooms are allocated on both sides of a centered corridor.  Irregular
        band components (for example the two legs of a U-shaped footprint) are
        programmed independently so a whole wing cannot be left empty.
        """
        rooms: List[Room] = []
        walls: List[Wall] = []
        lvl = level.index
        min_x, min_z, max_x, max_z = bounds
        interior = footprint.buffer(-FP_INSET, join_style=2)
        if interior.is_empty:
            return rooms, self._place_exterior_walls(footprint, level)

        core = self._find_vertical_core(interior, STAIR_W_M, STAIR_D_M)
        if core is not None:
            rooms.append(Room(
                id=f"stair_{lvl}", type="stair",
                polygon=[[c[0], c[1]] for c in list(core.exterior.coords)[:-1]],
                level=lvl, area_sqft=core.area * 10.764,
            ))
        available = interior.difference(core.buffer(0.02, join_style=2)) if core is not None else interior

        corridor_z0 = min_z + (d - CORRIDOR_WIDTH_M) / 2.0
        corridor_strip = box(min_x, corridor_z0, max_x, corridor_z0 + CORRIDOR_WIDTH_M)
        corridor_shape = available.intersection(corridor_strip)
        if hasattr(corridor_shape, "geoms"):
            corridor_parts = [
                geometry for geometry in corridor_shape.geoms
                if geometry.geom_type == "Polygon" and geometry.area >= 1.0
            ]
            corridor_shape = max(corridor_parts, key=lambda geometry: geometry.area) if corridor_parts else None
        if corridor_shape is not None and not corridor_shape.is_empty and hasattr(corridor_shape, "exterior"):
            rooms.append(Room(
                id=f"corridor_{lvl}", type="corridor",
                polygon=[[c[0], c[1]] for c in list(corridor_shape.exterior.coords)[:-1]],
                level=lvl, area_sqft=corridor_shape.area * 10.764,
            ))

        band_shapes = [
            available.intersection(box(min_x, min_z, max_x, corridor_z0)),
            available.intersection(box(min_x, corridor_z0 + CORRIDOR_WIDTH_M, max_x, max_z)),
        ]
        components: List[Polygon] = []
        for band_shape in band_shapes:
            geometries = list(band_shape.geoms) if hasattr(band_shape, "geoms") else [band_shape]
            components.extend(
                geometry for geometry in geometries
                if geometry.geom_type == "Polygon" and geometry.area >= 6.0
                and (geometry.bounds[3] - geometry.bounds[1]) >= 2.5
            )
        components.sort(key=lambda geometry: (geometry.bounds[1], geometry.bounds[0]))

        # Start with conventional ~7.5m-wide units, but honor the user's total
        # count where geometry permits. Every disconnected wing retains at
        # least one programmed cell.
        slots = [max(1, round((component.bounds[2] - component.bounds[0]) / 7.5)) for component in components]
        requested_per_floor = (
            max(1, math.ceil(spec.unit_count / max(spec.stories, 1)))
            if spec.unit_count else sum(slots)
        )
        target_slots = max(len(components), requested_per_floor)
        while sum(slots) < target_slots and components:
            candidates = [
                ((component.bounds[2] - component.bounds[0]) / (slots[index] + 1), index)
                for index, component in enumerate(components)
            ]
            next_width, index = max(candidates)
            if next_width < 3.2:
                break
            slots[index] += 1
        while sum(slots) > target_slots and any(count > 1 for count in slots):
            index = min(
                (idx for idx, count in enumerate(slots) if count > 1),
                key=lambda idx: (components[idx].bounds[2] - components[idx].bounds[0]) / slots[idx],
            )
            slots[index] -= 1

        all_rects: List[Tuple[float, float, float, float]] = []
        if corridor_shape is not None and hasattr(corridor_shape, "bounds"):
            all_rects.append(corridor_shape.bounds)
        unit_index = 0
        for component_index, (component, component_slots) in enumerate(zip(components, slots)):
            comp_min_x, comp_min_z, comp_max_x, comp_max_z = component.bounds
            cell_width = (comp_max_x - comp_min_x) / component_slots
            for slot_index in range(component_slots):
                x0 = comp_min_x + cell_width * slot_index
                x1 = comp_min_x + cell_width * (slot_index + 1)
                cell = component.intersection(box(x0, comp_min_z, x1, comp_max_z))
                if hasattr(cell, "geoms"):
                    polygons = [geometry for geometry in cell.geoms if geometry.geom_type == "Polygon"]
                    cell = max(polygons, key=lambda geometry: geometry.area) if polygons else None
                if cell is None or cell.is_empty or not hasattr(cell, "exterior") or cell.area < 6.0:
                    continue
                cell_bounds = cell.bounds
                width = cell_bounds[2] - cell_bounds[0]
                unit_type = "2br" if width >= 8.5 else "1br"
                template = UNIT_TEMPLATES[unit_type]
                uid = f"unit_{unit_type}_{lvl}_{component_index}_{slot_index}_{unit_index}"
                rooms.append(Room(
                    id=uid, type="unit", unit_id=uid,
                    polygon=[[c[0], c[1]] for c in list(cell.exterior.coords)[:-1]],
                    level=lvl, area_sqft=cell.area * 10.764,
                ))
                sub_rooms = self._place_unit_rooms(
                    uid,
                    cell_bounds[0], cell_bounds[1],
                    cell_bounds[2] - cell_bounds[0], cell_bounds[3] - cell_bounds[1],
                    template, lvl, fp_interior=cell,
                )
                rooms.extend(sub_rooms)
                all_rects.append(cell_bounds)
                all_rects.extend(self._unit_subrects(cell_bounds, template))
                unit_index += 1

        self._emit_interior_walls(all_rects, footprint, interior, level, walls)
        walls.extend(self._place_exterior_walls(footprint, level))
        return rooms, walls

    def _layout_floor(
        self, footprint, bounds, w, d, level: Level, _spec: ProjectSpec
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
            if not cs.is_empty and hasattr(cs, 'exterior'):
                stair_poly = [[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]]
            else:
                stair_poly = None   # outside footprint — omit
        except Exception:
            stair_poly = None
        # The fixed front-center candidate can sit entirely in a U-shaped
        # courtyard. Fall back to a contained side core found by a deterministic
        # footprint search so every occupied level retains vertical egress.
        stair_shape = self._find_vertical_core(fp_interior_mf, STAIR_W_M, STAIR_D_M)
        if stair_shape is not None:
            stair_poly = [[c[0], c[1]] for c in list(stair_shape.exterior.coords)[:-1]]
        if stair_poly:
            rooms.append(Room(
                id=f"stair_{lvl}",
                type="stair",
                polygon=stair_poly,
                level=lvl,
                area_sqft=Polygon(stair_poly).area * 10.764,
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

        # Collect room rects for unified wall generation (stair excluded — it's an
        # open shaft, not a walled room; corridor/unit edges define its boundaries).
        all_rects: List[Tuple[float, float, float, float]] = []
        corr_b = Polygon(corridor_poly).bounds
        all_rects.append((corr_b[0], corr_b[1], corr_b[2], corr_b[3]))

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

                cb = clipped.bounds
                sub_rooms = self._place_unit_rooms(
                    uid, cb[0], cb[1], cb[2]-cb[0], cb[3]-cb[1],
                    tmpl, lvl, fp_interior=fp_interior_mf,
                )
                rooms.extend(sub_rooms)

                # Unit shell + all sub-room rects for unified wall generation
                all_rects.append((cb[0], cb[1], cb[2], cb[3]))
                all_rects.extend(self._unit_subrects(cb, tmpl))

                cursor_x += uw
                unit_idx += 1

        # One wall per unique shared edge; exterior edges automatically skipped
        self._emit_interior_walls(all_rects, footprint, fp_interior_mf, level, walls)

        ext_walls = self._place_exterior_walls(footprint, level)
        walls.extend(ext_walls)

        return rooms, walls

    def _determine_unit_mix(self, building_w: float, _usable_depth: float) -> Dict[str, int]:
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

    def _layout_victorian_ground(
        self, footprint, bounds, w, d, level: Level, all_levels: List[Level]
    ) -> Tuple[List[Room], List[Wall]]:
        """Ground floor of a Victorian narrow-lot: garage (front 60%) + utility rear (40%).
        Wet wall anchor and panel location are placed in the rear utility zone per archetype spec."""
        rooms: List[Room] = []
        walls: List[Wall] = []
        lvl = level.index
        minx, miny, maxx, maxy = bounds
        fp_interior = footprint.buffer(-FP_INSET)

        def _clip_polygon(raw_shape) -> List[List[float]]:
            """Clip a raw rectangular polygon to fp_interior so it never extends outside walls."""
            try:
                clipped = fp_interior.intersection(raw_shape)
                if hasattr(clipped, 'geoms'):
                    clipped = max(clipped.geoms, key=lambda g: g.area)
                if clipped.is_empty or not hasattr(clipped, 'exterior'):
                    return list(raw_shape.exterior.coords[:-1])
                return [[x, y] for x, y in clipped.exterior.coords[:-1]]
            except Exception:
                return list(raw_shape.exterior.coords[:-1])

        # Garage: front 60% of depth
        garage_d = d * 0.60
        garage_rect = (minx, miny, maxx, miny + garage_d)
        garage_shape = Polygon([[minx, miny], [maxx, miny], [maxx, miny + garage_d], [minx, miny + garage_d]])
        garage_poly = _clip_polygon(garage_shape)
        rooms.append(Room(
            id=f"victorian_garage_{lvl}",
            type="garage",
            unit_id="house",
            polygon=garage_poly,
            level=lvl,
            area_sqft=w * garage_d * 10.764,
        ))

        # Utility / mechanical rear: back 40% — houses panel, water heater, laundry
        util_y0 = miny + garage_d
        util_rect = (minx, util_y0, maxx, maxy)
        # Split rear into laundry (left 55%) and mechanical (right 45%)
        split_x = minx + w * 0.55
        laundry_shape = Polygon([[minx, util_y0], [split_x, util_y0], [split_x, maxy], [minx, maxy]])
        mech_shape = Polygon([[split_x, util_y0], [maxx, util_y0], [maxx, maxy], [split_x, maxy]])
        rooms.append(Room(
            id=f"victorian_laundry_{lvl}",
            type="laundry",
            unit_id="house",
            polygon=_clip_polygon(laundry_shape),
            level=lvl,
            area_sqft=(split_x - minx) * (maxy - util_y0) * 10.764,
        ))
        rooms.append(Room(
            id=f"victorian_mechanical_{lvl}",
            type="mechanical",
            unit_id="house",
            polygon=_clip_polygon(mech_shape),
            level=lvl,
            area_sqft=(maxx - split_x) * (maxy - util_y0) * 10.764,
        ))

        # Interior walls from room rects
        room_rects = [garage_rect, util_rect]
        self._emit_interior_walls(room_rects, footprint, fp_interior, level, walls)

        ext_walls = self._place_exterior_walls(footprint, level)
        walls.extend(ext_walls)

        # Stair — only for multi-story buildings
        n_floors = len(all_levels)
        if n_floors > 1:
            maxx_sfr = bounds[2]
            stair_w_sfr = min(w * 0.15, 1.5)
            stair_d_sfr = min(d * 0.28, 3.5)
            sr_x0 = maxx_sfr - stair_w_sfr
            sr_y0 = miny + (d - stair_d_sfr) / 2
            raw_sfr_stair = Polygon([
                [sr_x0, sr_y0], [maxx_sfr, sr_y0],
                [maxx_sfr, sr_y0 + stair_d_sfr], [sr_x0, sr_y0 + stair_d_sfr],
            ])
            sfr_stair_poly = None
            try:
                cs = fp_interior.intersection(raw_sfr_stair)
                if hasattr(cs, 'geoms'):
                    cs = max(cs.geoms, key=lambda g: g.area)
                if not cs.is_empty and hasattr(cs, 'exterior') and cs.area >= 0.05:
                    sfr_stair_poly = [[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]]
            except Exception:
                pass
            if not sfr_stair_poly:
                # Fallback: center-back position
                sr_x0 = minx + (w - stair_w_sfr) / 2
                sr_y0 = miny
                raw_sfr_stair = Polygon([
                    [sr_x0, sr_y0], [sr_x0 + stair_w_sfr, sr_y0],
                    [sr_x0 + stair_w_sfr, sr_y0 + stair_d_sfr], [sr_x0, sr_y0 + stair_d_sfr],
                ])
                try:
                    cs = fp_interior.intersection(raw_sfr_stair)
                    if hasattr(cs, 'geoms'):
                        cs = max(cs.geoms, key=lambda g: g.area)
                    if not cs.is_empty and hasattr(cs, 'exterior') and cs.area >= 0.05:
                        sfr_stair_poly = [[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]]
                except Exception:
                    pass
            if sfr_stair_poly:
                stair_shape = Polygon(sfr_stair_poly)
                carved_rooms: List[Room] = []
                for placed_room in rooms:
                    room_shape = Polygon(placed_room.polygon)
                    if not room_shape.intersects(stair_shape):
                        carved_rooms.append(placed_room)
                        continue
                    remainder = room_shape.difference(stair_shape.buffer(0.02, join_style=2))
                    if hasattr(remainder, 'geoms'):
                        polygon_parts = [
                            geometry for geometry in remainder.geoms
                            if geometry.geom_type == 'Polygon' and geometry.area >= 0.5
                        ]
                        remainder = max(polygon_parts, key=lambda geometry: geometry.area) if polygon_parts else None
                    if remainder is None or remainder.is_empty or not hasattr(remainder, 'exterior') or remainder.area < 0.5:
                        continue
                    carved_rooms.append(placed_room.model_copy(update={
                        "polygon": [[c[0], c[1]] for c in list(remainder.exterior.coords)[:-1]],
                        "area_sqft": remainder.area * 10.764,
                    }))
                rooms = carved_rooms
                room_rects = [Polygon(room.polygon).bounds for room in rooms]
                rooms.append(Room(
                    id=f"sfr_stair_{lvl}_{uuid.uuid4().hex[:5]}",
                    type="stair",
                    unit_id="house",
                    polygon=sfr_stair_poly,
                    level=lvl,
                    area_sqft=stair_shape.area * 10.764,
                ))

        return rooms, walls

    def _emit_interior_walls(
        self,
        room_rects: List[Tuple[float, float, float, float]],
        footprint,
        fp_interior,
        level: Level,
        walls: List[Wall],
    ) -> None:
        """For each room rect generate all 4 wall segments, deduplicate shared walls,
        and skip segments that lie on the exterior footprint boundary (those are
        handled by _place_exterior_walls). Clips each kept segment to fp_interior."""
        lvl = level.index
        fp_ext_band = footprint.exterior.buffer(0.05)
        seen: set = set()

        def try_add(x0: float, y0: float, x1: float, y1: float) -> None:
            # Canonical order so (A→B) and (B→A) hash the same
            if (x0, y0) > (x1, y1):
                x0, y0, x1, y1 = x1, y1, x0, y0
            key = (round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3))
            if key in seen:
                return
            seen.add(key)

            line = LineString([[x0, y0], [x1, y1]])
            # Skip walls that are entirely on the exterior boundary
            try:
                if fp_ext_band.contains(line):
                    return
            except Exception:
                pass

            # Clip to interior and emit
            try:
                clipped = fp_interior.intersection(line)
                segs = ([clipped] if hasattr(clipped, 'coords')
                        else (list(clipped.geoms) if hasattr(clipped, 'geoms') else []))
                for seg in segs:
                    if hasattr(seg, 'coords'):
                        wc = list(seg.coords)
                        if len(wc) >= 2 and LineString(wc).length > 0.05:
                            walls.append(Wall(
                                id=f"int_wall_{lvl}_{uuid.uuid4().hex[:6]}",
                                start=[wc[0][0], wc[0][1]],
                                end=[wc[-1][0], wc[-1][1]],
                                height_ft=level.height_ft,
                                level=lvl, is_exterior=False,
                            ))
            except Exception:
                pass

        for (rx0, ry0, rx1, ry1) in room_rects:
            try_add(rx0, ry0, rx1, ry0)  # top edge
            try_add(rx1, ry0, rx1, ry1)  # right edge
            try_add(rx0, ry1, rx1, ry1)  # bottom edge
            try_add(rx0, ry0, rx0, ry1)  # left edge

    def _unit_subrects(
        self, cb: Tuple[float, float, float, float], tmpl: Dict
    ) -> List[Tuple[float, float, float, float]]:
        """Return (x0,y0,x1,y1) for every sub-room cell in a unit template,
        scaled to the clipped unit bounds cb=(minx,miny,maxx,maxy)."""
        ux, uy = cb[0], cb[1]
        uw, ud = cb[2] - cb[0], cb[3] - cb[1]
        rects = []
        y_cursor = uy
        for row in tmpl.get("rows", []):
            row_d = ud * row["frac_d"]
            x_cursor = ux
            for rdef in row.get("rooms", []):
                rw = uw * rdef["frac_w"]
                rects.append((x_cursor, y_cursor, x_cursor + rw, y_cursor + row_d))
                x_cursor += rw
            y_cursor += row_d
        return rects

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

    # ── Hillside street-level ground floor ───────────────────────────────────
    def _layout_hillside_ground(
        self, footprint, bounds, w, d, level: Level,
        all_levels: List[Level],
    ) -> Tuple[List[Room], List[Wall]]:
        """Street level of a hillside stepped house: garage (front) + entry + mudroom + utility.
        Generates 4 rooms so the ground floor is not nearly empty."""
        rooms: List[Room] = []
        walls: List[Wall] = []
        lvl = level.index
        minx, miny = bounds[0], bounds[1]
        fp_interior = footprint.buffer(-FP_INSET)

        def _clip_room(x0: float, y0: float, x1: float, y1: float, rtype: str) -> None:
            cell = Polygon([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
            try:
                clipped = fp_interior.intersection(cell)
                if hasattr(clipped, 'geoms'):
                    clipped = max(clipped.geoms, key=lambda g: g.area)
                if clipped.is_empty or not hasattr(clipped, 'exterior') or clipped.area < 0.5:
                    return
                poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                rooms.append(Room(
                    id=f"hs_{rtype}_{lvl}_{uuid.uuid4().hex[:5]}",
                    type=rtype, unit_id="house", polygon=poly, level=lvl,
                    area_sqft=clipped.area * 10.764,
                ))
            except Exception:
                pass

        # Garage: front 40% of depth
        garage_d = d * 0.40
        _clip_room(minx, miny, minx + w, miny + garage_d, "garage")

        # Service zone: back 60% split into entry(40%), mudroom(30%), utility(30%)
        svc_y0 = miny + garage_d
        svc_y1 = miny + d
        entry_x1 = minx + w * 0.40
        mud_x1   = minx + w * 0.70
        _clip_room(minx,     svc_y0, entry_x1, svc_y1, "foyer")
        _clip_room(entry_x1, svc_y0, mud_x1,   svc_y1, "mudroom")
        _clip_room(mud_x1,   svc_y0, minx + w, svc_y1, "utility")

        room_rects: List[Tuple[float, float, float, float]] = [
            (minx, miny,   minx + w,  miny + garage_d),
            (minx, svc_y0, entry_x1,  svc_y1),
            (entry_x1, svc_y0, mud_x1, svc_y1),
            (mud_x1, svc_y0, minx + w, svc_y1),
        ]
        self._emit_interior_walls(room_rects, footprint, fp_interior, level, walls)
        walls.extend(self._place_exterior_walls(footprint, level))

        # Stair — only for multi-story
        n_floors = len(all_levels) if all_levels else 1
        if n_floors > 1:
            stair_w = min(w * 0.15, 1.5)
            stair_d_s = min(d * 0.28, 3.5)
            sr_x0 = (minx + w) - stair_w
            sr_y0 = miny + (d - stair_d_s) / 2
            raw_stair = Polygon([
                [sr_x0, sr_y0], [sr_x0 + stair_w, sr_y0],
                [sr_x0 + stair_w, sr_y0 + stair_d_s], [sr_x0, sr_y0 + stair_d_s],
            ])
            try:
                cs = fp_interior.intersection(raw_stair)
                if hasattr(cs, 'geoms'):
                    cs = max(cs.geoms, key=lambda g: g.area)
                if not cs.is_empty and hasattr(cs, 'exterior') and cs.area >= 0.05:
                    rooms.append(Room(
                        id=f"hs_stair_{lvl}_{uuid.uuid4().hex[:5]}",
                        type="stair", unit_id="house",
                        polygon=[[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]],
                        level=lvl, area_sqft=stair_w * stair_d_s * 10.764,
                    ))
            except Exception:
                pass

        return rooms, walls

    # ── Garage-on-grade ground floor (Urban Infill / Production Tract) ─────────
    def _layout_garage_ground(
        self, footprint, bounds, w, d, level: Level, archetype_id: str,
        all_levels: List[Level] = None,
    ) -> Tuple[List[Room], List[Wall]]:
        """Ground floor with front-facing attached garage + entry zone behind it."""
        rooms: List[Room] = []
        walls: List[Wall] = []
        lvl = level.index
        minx, miny = bounds[0], bounds[1]
        fp_interior = footprint.buffer(-FP_INSET)

        # Garage takes the front 40% of the depth; entry+utility gets the back 60%.
        garage_depth_frac = 0.40
        garage_d = d * garage_depth_frac
        entry_d  = d * (1.0 - garage_depth_frac)

        def _clip_room(x0: float, y0: float, x1: float, y1: float, rtype: str) -> None:
            cell = Polygon([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
            try:
                clipped = fp_interior.intersection(cell)
                if hasattr(clipped, 'geoms'):
                    clipped = max(clipped.geoms, key=lambda g: g.area)
                if clipped.is_empty or not hasattr(clipped, 'exterior') or clipped.area < 0.5:
                    return
                poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                cb = clipped.bounds
                rooms.append(Room(
                    id=f"sfr_{rtype}_{lvl}_{uuid.uuid4().hex[:5]}",
                    type=rtype, unit_id="house", polygon=poly, level=lvl,
                    area_sqft=clipped.area * 10.764,
                ))
            except Exception:
                pass

        # Garage (front)
        _clip_room(minx, miny, minx + w, miny + garage_d, "garage")

        # Entry + utility behind garage
        entry_w = w * 0.55
        utility_w = w - entry_w
        entry_y0 = miny + garage_d
        entry_y1 = miny + d
        _clip_room(minx,           entry_y0, minx + entry_w,   entry_y1, "foyer")
        _clip_room(minx + entry_w, entry_y0, minx + entry_w + utility_w, entry_y1, "utility")

        # Collect room rects for wall generation
        room_rects: List[Tuple[float, float, float, float]] = [
            (minx, miny, minx + w, miny + garage_d),
            (minx, miny + garage_d, minx + entry_w, miny + d),
            (minx + entry_w, miny + garage_d, minx + w, miny + d),
        ]
        self._emit_interior_walls(room_rects, footprint, fp_interior, level, walls)
        walls.extend(self._place_exterior_walls(footprint, level))

        # Stair — only for multi-story buildings
        n_floors = len(all_levels) if all_levels is not None else 1
        if n_floors > 1:
            maxx_sfr = minx + w
            miny_local = bounds[1]
            stair_w_sfr = min(w * 0.15, 1.5)
            stair_d_sfr = min(d * 0.28, 3.5)
            sr_x0 = maxx_sfr - stair_w_sfr
            sr_y0 = miny_local + (d - stair_d_sfr) / 2
            raw_sfr_stair = Polygon([
                [sr_x0, sr_y0], [maxx_sfr, sr_y0],
                [maxx_sfr, sr_y0 + stair_d_sfr], [sr_x0, sr_y0 + stair_d_sfr],
            ])
            sfr_stair_poly = None
            try:
                cs = fp_interior.intersection(raw_sfr_stair)
                if hasattr(cs, 'geoms'):
                    cs = max(cs.geoms, key=lambda g: g.area)
                if not cs.is_empty and hasattr(cs, 'exterior') and cs.area >= 0.05:
                    sfr_stair_poly = [[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]]
            except Exception:
                pass
            if not sfr_stair_poly:
                # Fallback: center-back position
                sr_x0 = minx + (w - stair_w_sfr) / 2
                sr_y0 = miny_local
                raw_sfr_stair = Polygon([
                    [sr_x0, sr_y0], [sr_x0 + stair_w_sfr, sr_y0],
                    [sr_x0 + stair_w_sfr, sr_y0 + stair_d_sfr], [sr_x0, sr_y0 + stair_d_sfr],
                ])
                try:
                    cs = fp_interior.intersection(raw_sfr_stair)
                    if hasattr(cs, 'geoms'):
                        cs = max(cs.geoms, key=lambda g: g.area)
                    if not cs.is_empty and hasattr(cs, 'exterior') and cs.area >= 0.05:
                        sfr_stair_poly = [[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]]
                except Exception:
                    pass
            if sfr_stair_poly:
                rooms.append(Room(
                    id=f"sfr_stair_{lvl}_{uuid.uuid4().hex[:5]}",
                    type="stair",
                    unit_id="house",
                    polygon=sfr_stair_poly,
                    level=lvl,
                    area_sqft=stair_w_sfr * stair_d_sfr * 10.764,
                ))

        return rooms, walls

    # ── Single-family residential layout ─────────────────────────────────────
    def _layout_sfr_floor(
        self, footprint, bounds, w, d, level: Level,
        all_levels: List[Level], bedrooms: int,
        archetype: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Room], List[Wall]]:
        rooms: List[Room] = []
        walls: List[Wall] = []
        lvl = level.index
        minx, miny = bounds[0], bounds[1]
        n_floors = len(all_levels)
        br = max(1, min(5, bedrooms))

        # ── Archetype overrides ───────────────────────────────────────────────
        archetype_id = (archetype or {}).get('id', '')
        if archetype_id == 'victorian_narrow_lot' and lvl == 0:
            return self._layout_victorian_ground(footprint, bounds, w, d, level, all_levels)
        if archetype_id == 'adu_compact':
            return self._layout_adu_floor(footprint, bounds, w, d, level, all_levels, bedrooms, archetype)
        # Hillside street level: richer 4-room ground (garage+entry+mudroom+utility)
        if archetype_id == 'hillside_stepped' and lvl == 0:
            return self._layout_hillside_ground(footprint, bounds, w, d, level, all_levels)
        # Archetypes with ground-level garage (Urban Infill, Production Tract, etc.)
        _garage_at_grade = (archetype or {}).get('massing_hints', {}).get('garage_at_grade', False)
        if _garage_at_grade and lvl == 0:
            return self._layout_garage_ground(footprint, bounds, w, d, level, archetype_id, all_levels)

        floor_area_m2 = footprint.area
        use_large = floor_area_m2 > LARGE_HOUSE_THRESHOLD_M2

        _is_victorian = archetype_id == 'victorian_narrow_lot'

        # Select which row program to use for this floor.
        # Core rule: bedrooms can appear on ANY upper floor — the strict
        # "ground=public, upper=private" split is only enforced for large houses
        # where the expanded programs already mix things correctly.
        if n_floors == 1:
            if use_large:
                # Single story large: all public spaces + all bedrooms on one floor
                ground = SFR_GROUND_LARGE.get(br, SFR_PROGRAMS[br])
                upper  = SFR_UPPER_LARGE.get(br, [])
                combined = ground + upper
                total = sum(r["row_frac_d"] for r in combined)
                row_program = [{**r, "row_frac_d": r["row_frac_d"] / total} for r in combined]
            else:
                row_program = SFR_PROGRAMS[br]

        elif lvl == 0:
            # Ground floor: public living spaces (kitchen, living, dining)
            if use_large:
                row_program = SFR_GROUND_LARGE.get(br, SFR_PROGRAMS[br])
            else:
                row_program = SFR_GROUND_ROWS[br]
            total = sum(r["row_frac_d"] for r in row_program)
            row_program = [{**r, "row_frac_d": r["row_frac_d"] / total} for r in row_program]

        else:
            # Upper floors for ALL archetypes:
            # - Large floor plate → SFR_UPPER_LARGE (bedrooms + bonus/loft/media)
            # - Small 2-story → full SFR_PROGRAMS so bedrooms + living share the floor
            # - Small 3-story → SFR_UPPER_ROWS (bedrooms focused, floor is compact)
            # Victorian floor 1 also uses full SFR_PROGRAMS so it mirrors real Victorian
            # layouts where a guest bedroom sits on the main living floor.
            if use_large:
                row_program = SFR_UPPER_LARGE.get(br, SFR_UPPER_ROWS[br])
            elif n_floors == 2 or _is_victorian:
                # Two-story or Victorian: upper floor gets the FULL per-bedroom program
                # (living + kitchen + bedrooms) so rooms are not artificially segregated.
                row_program = list(SFR_PROGRAMS.get(br, SFR_PROGRAMS[3]))
            else:
                row_program = SFR_UPPER_ROWS[br]
            total = sum(r["row_frac_d"] for r in row_program)
            row_program = [{**r, "row_frac_d": r["row_frac_d"] / total} for r in row_program]

        # One canonical interior boundary — everything must have its center inside this.
        fp_interior = footprint.buffer(-FP_INSET)

        # Minimum room widths (metres) — enforced per room type to avoid slivers.
        _MIN_W: Dict[str, float] = {
            "bedroom": 2.7, "bathroom": 1.5, "kitchen": 2.4,
            "living": 3.0, "dining": 2.4, "family_room": 3.0,
            "office": 2.4, "loft": 2.4, "media_room": 2.7,
            "laundry": 1.5, "mudroom": 1.5, "foyer": 1.5,
            "corridor": 1.1, "hall": 1.1, "walk_in_closet": 1.2,
        }

        # Phase 1: place rooms, collect their rects for wall generation
        room_rects: List[Tuple[float, float, float, float]] = []
        y_cursor = miny
        for row in row_program:
            row_d = d * row["row_frac_d"]
            row_y0 = y_cursor
            row_y1 = y_cursor + row_d

            # Enforce minimum widths: clamp each room up to its minimum, then
            # renormalise remaining rooms so the row still sums to full width.
            raw_widths = [w * rdef["frac_w"] for rdef in row["rooms"]]
            mins = [_MIN_W.get(rdef["type"], 1.2) for rdef in row["rooms"]]
            clamped = [max(rw, mn) for rw, mn in zip(raw_widths, mins)]
            clamped_total = sum(clamped)
            if clamped_total > w:
                # Scale all rooms proportionally to fit
                scale = w / clamped_total
                adj_widths = [rw * scale for rw in clamped]
            else:
                # Distribute leftover width proportionally to rooms at their minimum
                leftover = w - clamped_total
                over_min = [max(rw - mn, 0.0) for rw, mn in zip(raw_widths, mins)]
                over_total = sum(over_min) or 1.0
                adj_widths = [cl + leftover * (ov / over_total)
                              for cl, ov in zip(clamped, over_min)]

            x_cursor = minx
            for rdef, rw in zip(row["rooms"], adj_widths):
                rx0, rx1 = x_cursor, x_cursor + rw
                row_area = rw * row_d
                cell_shape = Polygon([
                    [rx0, row_y0], [rx1, row_y0],
                    [rx1, row_y1], [rx0, row_y1],
                ])
                try:
                    clipped = fp_interior.intersection(cell_shape)
                    if hasattr(clipped, 'geoms'):
                        clipped = max(clipped.geoms, key=lambda g: g.area)
                    # Accept if clipped area ≥ 25% of the cell so partial rooms
                    # near L/U cut corners still get placed instead of leaving gaps.
                    if clipped.is_empty or not hasattr(clipped, 'exterior') or clipped.area < max(0.5, row_area * 0.25):
                        x_cursor += rw
                        continue
                    poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                    cb = clipped.bounds
                    area = clipped.area * 10.764
                except Exception:
                    # Fallback: full rectangle — only if center is inside
                    cell_cx = (rx0 + rx1) / 2
                    cell_cz = (row_y0 + row_y1) / 2
                    if not fp_interior.contains(Point(cell_cx, cell_cz)):
                        x_cursor += rw
                        continue
                    poly = [[rx0, row_y0], [rx1, row_y0], [rx1, row_y1], [rx0, row_y1]]
                    cb = (rx0, row_y0, rx1, row_y1)
                    area = row_area * 10.764

                rooms.append(Room(
                    id=f"sfr_{rdef['type']}_{lvl}_{uuid.uuid4().hex[:5]}",
                    type=rdef["type"],
                    unit_id="house",
                    polygon=poly, level=lvl,
                    area_sqft=area,
                ))
                room_rects.append((cb[0], cb[1], cb[2], cb[3]))
                x_cursor += rw
            y_cursor += row_d

        # Phase 2: stair void — multi-story SFR needs an opening on every floor so the
        # upper level doesn't visually cover the stairwell. Place a stair room at the
        # right edge of the floor plate, centred in depth, on every floor.
        if n_floors > 1:
            maxx_sfr = minx + w
            stair_w_sfr = min(w * 0.15, 1.5)
            stair_d_sfr = min(d * 0.28, 3.5)
            sr_x0 = maxx_sfr - stair_w_sfr
            sr_y0 = miny + (d - stair_d_sfr) / 2
            raw_sfr_stair = Polygon([
                [sr_x0, sr_y0], [maxx_sfr, sr_y0],
                [maxx_sfr, sr_y0 + stair_d_sfr], [sr_x0, sr_y0 + stair_d_sfr],
            ])
            sfr_stair_poly = None
            try:
                cs = fp_interior.intersection(raw_sfr_stair)
                if hasattr(cs, 'geoms'):
                    cs = max(cs.geoms, key=lambda g: g.area)
                if not cs.is_empty and hasattr(cs, 'exterior') and cs.area >= 0.05:
                    sfr_stair_poly = [[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]]
            except Exception:
                pass   # clip failed — try fallback below
            if not sfr_stair_poly:
                # Fallback: center-back position
                sr_x0 = minx + (w - stair_w_sfr) / 2
                sr_y0 = miny
                raw_sfr_stair = Polygon([
                    [sr_x0, sr_y0], [sr_x0 + stair_w_sfr, sr_y0],
                    [sr_x0 + stair_w_sfr, sr_y0 + stair_d_sfr], [sr_x0, sr_y0 + stair_d_sfr],
                ])
                try:
                    cs = fp_interior.intersection(raw_sfr_stair)
                    if hasattr(cs, 'geoms'):
                        cs = max(cs.geoms, key=lambda g: g.area)
                    if not cs.is_empty and hasattr(cs, 'exterior') and cs.area >= 0.05:
                        sfr_stair_poly = [[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]]
                except Exception:
                    pass
            if sfr_stair_poly:
                rooms.append(Room(
                    id=f"sfr_stair_{lvl}_{uuid.uuid4().hex[:5]}",
                    type="stair",
                    unit_id="house",
                    polygon=sfr_stair_poly,
                    level=lvl,
                    area_sqft=stair_w_sfr * stair_d_sfr * 10.764,
                ))

        # Phase 3: emit one interior wall per unique shared edge, skip exterior edges
        self._emit_interior_walls(room_rects, footprint, fp_interior, level, walls)

        ext_walls = self._place_exterior_walls(footprint, level)
        walls.extend(ext_walls)
        return rooms, walls

    # ── ADU programs derived from adu_compact.json blueprint analysis ─────────
    # Row-based program tuples: (type, frac_w, frac_d) — same encoding as SFR.
    # Bedrooms key: 0=studio, 1=1BR (standard narrow), 2=2BR.
    # Single-story 1BR variant (>800 sqft) falls through to 1BR since ADU
    # generator will choose the right proportions from actual footprint size.
    _ADU_GROUND: Dict[int, List[Dict]] = {
        0: [  # Studio — single level, 380 sqft ~20x20
            {"row_frac_d": 0.45, "rooms": [
                {"type": "living",   "frac_w": 0.75},
                {"type": "foyer",    "frac_w": 0.25},
            ]},
            {"row_frac_d": 0.35, "rooms": [
                {"type": "kitchen",  "frac_w": 0.55},
                {"type": "bathroom", "frac_w": 0.45},
            ]},
            {"row_frac_d": 0.20, "rooms": [
                {"type": "living",   "frac_w": 1.0},   # sleeping zone open to living
            ]},
        ],
        1: [  # 1BR/1BA — 2-story 658 sqft, 25x14. Ground: living + kitchen + stair.
            {"row_frac_d": 0.50, "rooms": [
                {"type": "living",   "frac_w": 0.75},
                {"type": "stair",    "frac_w": 0.25},
            ]},
            {"row_frac_d": 0.50, "rooms": [
                {"type": "kitchen",  "frac_w": 0.75},
                {"type": "stair",    "frac_w": 0.25},
            ]},
        ],
        2: [  # 2BR/2BA — 2-story 1155 sqft, 30x20. Ground: living + kitchen/island + entry + half-bath.
            {"row_frac_d": 0.55, "rooms": [
                {"type": "living",   "frac_w": 0.55},
                {"type": "foyer",    "frac_w": 0.20},
                {"type": "stair",    "frac_w": 0.25},
            ]},
            {"row_frac_d": 0.45, "rooms": [
                {"type": "kitchen",  "frac_w": 0.60},
                {"type": "bathroom", "frac_w": 0.20},
                {"type": "stair",    "frac_w": 0.20},
            ]},
        ],
    }

    _ADU_UPPER: Dict[int, List[Dict]] = {
        1: [  # 1BR upper: bedroom + bath + closet + stair landing (left spine matches L0)
            {"row_frac_d": 0.60, "rooms": [
                {"type": "bedroom",  "frac_w": 0.75},
                {"type": "stair",    "frac_w": 0.25},
            ]},
            {"row_frac_d": 0.40, "rooms": [
                {"type": "bathroom", "frac_w": 0.50},
                {"type": "closet",   "frac_w": 0.25},
                {"type": "hall",     "frac_w": 0.25},
            ]},
        ],
        2: [  # 2BR upper: primary bed + bath, bedroom 2 + bath, hall + stair landing
            {"row_frac_d": 0.25, "rooms": [
                {"type": "hall",      "frac_w": 0.75},
                {"type": "stair",     "frac_w": 0.25},
            ]},
            {"row_frac_d": 0.40, "rooms": [
                {"type": "bedroom",   "frac_w": 0.50},
                {"type": "bedroom",   "frac_w": 0.50},
            ]},
            {"row_frac_d": 0.35, "rooms": [
                {"type": "bathroom",  "frac_w": 0.40},
                {"type": "closet",    "frac_w": 0.20},
                {"type": "bathroom",  "frac_w": 0.40},
            ]},
        ],
    }

    def _layout_adu_floor(
        self, footprint, bounds, w, d, level: Level,
        all_levels: List[Level], bedrooms: int,
        archetype: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Room], List[Wall]]:
        """ADU room layout: compact rectangle programs from adu_compact.json blueprints."""
        rooms: List[Room] = []
        walls: List[Wall] = []
        lvl = level.index
        minx, miny = bounds[0], bounds[1]
        n_floors = len(all_levels)

        # Clamp bedrooms to what the ADU programs support (0=studio, 1=1BR, 2=2BR)
        br = max(0, min(2, bedrooms))

        if n_floors == 1 or br == 0:
            # Single-story studio OR single-floor 1BR/2BR: use ground program only
            row_program = self._ADU_GROUND.get(br, self._ADU_GROUND[1])
        elif lvl == 0:
            row_program = self._ADU_GROUND.get(br, self._ADU_GROUND[1])
        else:
            row_program = self._ADU_UPPER.get(br, self._ADU_UPPER[1])

        # Normalize fractions so they always sum to 1.0
        total_d = sum(r["row_frac_d"] for r in row_program)
        row_program = [{**r, "row_frac_d": r["row_frac_d"] / total_d} for r in row_program]

        fp_interior = footprint.buffer(-FP_INSET)
        room_rects: List[Tuple[float, float, float, float]] = []
        y_cursor = miny

        for row in row_program:
            row_d = d * row["row_frac_d"]
            row_y0 = y_cursor
            row_y1 = y_cursor + row_d
            x_cursor = minx
            for rdef in row["rooms"]:
                rw = w * rdef["frac_w"]
                rx0, rx1 = x_cursor, x_cursor + rw
                row_area = rw * row_d
                cell_shape = Polygon([
                    [rx0, row_y0], [rx1, row_y0],
                    [rx1, row_y1], [rx0, row_y1],
                ])
                try:
                    clipped = fp_interior.intersection(cell_shape)
                    if hasattr(clipped, 'geoms'):
                        clipped = max(clipped.geoms, key=lambda g: g.area)
                    if clipped.is_empty or not hasattr(clipped, 'exterior') or clipped.area < max(0.5, row_area * 0.25):
                        x_cursor += rw
                        continue
                    poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                    cb = clipped.bounds
                    area = clipped.area * 10.764
                except Exception:
                    cell_cx = (rx0 + rx1) / 2
                    cell_cy = (row_y0 + row_y1) / 2
                    if not fp_interior.contains(Point(cell_cx, cell_cy)):
                        x_cursor += rw
                        continue
                    poly = [[rx0, row_y0], [rx1, row_y0], [rx1, row_y1], [rx0, row_y1]]
                    cb = (rx0, row_y0, rx1, row_y1)
                    area = row_area * 10.764
                rooms.append(Room(
                    id=f"adu_{rdef['type']}_{lvl}_{uuid.uuid4().hex[:5]}",
                    type=rdef["type"],
                    unit_id="adu",
                    polygon=poly, level=lvl,
                    area_sqft=area,
                ))
                room_rects.append((cb[0], cb[1], cb[2], cb[3]))
                x_cursor += rw
            y_cursor += row_d

        self._emit_interior_walls(room_rects, footprint, fp_interior, level, walls)
        walls.extend(self._place_exterior_walls(footprint, level))
        return rooms, walls
