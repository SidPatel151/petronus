"""
FloorplanGenerator
Two modes:
  - Multi-family: corridor + unit cells (studio/1BR/2BR).
  - Single-family (primary path): AI-generated room program from ai_room_program.py,
    which reads actual footprint dims + blueprint examples and calls Claude Haiku.
    Static SFR_PROGRAMS below are kept as a fallback if the AI call fails.
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
# All rooms, walls, and MEP elements must have their CENTER inside fp.buffer(-FP_INSET, join_style=2).
FP_INSET = 0.20

# Minimum room widths (metres), by room type — mirrors the more complete of
# the two per-function `_MIN_W` locals below (ground-floor row layout).
# Exported for reuse by app.generators.floorplan_editor; intentionally NOT
# wired back into the two local `_MIN_W` dicts below, since they differ
# slightly and consolidating them would change existing layout behavior.
MIN_ROOM_WIDTH_M: Dict[str, float] = {
    "bedroom": 2.7, "bathroom": 1.5, "kitchen": 2.4,
    "living": 3.0, "dining": 2.4, "family_room": 3.0,
    "office": 2.4, "loft": 2.4, "media_room": 2.7,
    "laundry": 1.5, "mudroom": 1.5, "foyer": 1.5,
    "corridor": 1.1, "hall": 1.1, "walk_in_closet": 1.2,
    "deck": 1.5, "garage": 2.7, "half_bath": 1.2,
    # Estate rooms. Minimums come off High-End-Custom/R.jpg, where a wine
    # cellar and pantry are 6 x 7 ft and the loggia is 13 x 32 ft — the small
    # service rooms genuinely are small, and clamping them to a generic 1.2 m
    # is part of why generated plans had no size spread at the bottom end.
    "wine_cellar": 1.6, "butler_pantry": 1.6, "cinema_room": 3.2,
    "game_room": 3.2, "sitting_room": 2.4, "sauna": 1.8,
    "pool_bath": 1.5, "loggia": 3.0, "gym": 2.4, "library": 2.4,
    "bonus_room": 2.7, "utility": 1.5, "mechanical": 1.5,
    "dressing_room": 1.8, "great_room": 4.2,
}

# ── Multi-family unit templates (row-based: each row is a horizontal band,
#    rooms within a row are placed side-by-side left→right) ─────────────────
UNIT_TEMPLATES = {
    "studio": {
        "w": 6.0, "d": 8.0, "area_sqft": 480,
        "rows": [
            {"frac_d": 0.55, "rooms": [{"type": "living",  "frac_w": 1.0}]},
            {"frac_d": 0.45, "rooms": [{"type": "kitchen",  "frac_w": 0.55}, {"type": "bathroom", "frac_w": 0.45}]},
        ]
    },
    "1br": {
        "w": 7.5, "d": 9.0, "area_sqft": 720,
        "rows": [
            {"frac_d": 0.40, "rooms": [{"type": "living",  "frac_w": 1.0}]},
            {"frac_d": 0.25, "rooms": [{"type": "kitchen",  "frac_w": 0.55}, {"type": "bathroom", "frac_w": 0.45}]},
            {"frac_d": 0.35, "rooms": [{"type": "bedroom", "frac_w": 1.0}]},
        ]
    },
    "2br": {
        "w": 9.0, "d": 10.0, "area_sqft": 960,
        "rows": [
            {"frac_d": 0.35, "rooms": [{"type": "living",  "frac_w": 1.0}]},
            {"frac_d": 0.25, "rooms": [{"type": "kitchen",  "frac_w": 0.50}, {"type": "bathroom", "frac_w": 0.50}]},
            {"frac_d": 0.40, "rooms": [{"type": "bedroom", "frac_w": 0.50}, {"type": "bedroom", "frac_w": 0.50}]},
        ]
    },
    "3br": {
        "w": 11.0, "d": 12.0, "area_sqft": 1400,
        "rows": [
            {"frac_d": 0.25, "rooms": [{"type": "living", "frac_w": 0.60}, {"type": "dining", "frac_w": 0.40}]},
            {"frac_d": 0.20, "rooms": [{"type": "kitchen", "frac_w": 0.55}, {"type": "bathroom", "frac_w": 0.45}]},
            {"frac_d": 0.18, "rooms": [{"type": "laundry", "frac_w": 0.40}, {"type": "half_bath", "frac_w": 0.60}]},
            {"frac_d": 0.37, "rooms": [{"type": "bedroom", "frac_w": 0.38}, {"type": "bedroom", "frac_w": 0.32}, {"type": "bedroom", "frac_w": 0.30}]},
        ]
    },
    "4br": {
        "w": 13.0, "d": 14.0, "area_sqft": 1900,
        "rows": [
            {"frac_d": 0.22, "rooms": [{"type": "living", "frac_w": 0.55}, {"type": "dining", "frac_w": 0.45}]},
            {"frac_d": 0.18, "rooms": [{"type": "kitchen", "frac_w": 0.55}, {"type": "bathroom", "frac_w": 0.45}]},
            {"frac_d": 0.15, "rooms": [{"type": "laundry", "frac_w": 0.40}, {"type": "office", "frac_w": 0.60}]},
            {"frac_d": 0.45, "rooms": [{"type": "bedroom", "frac_w": 0.32}, {"type": "bedroom", "frac_w": 0.26}, {"type": "bedroom", "frac_w": 0.22}, {"type": "bedroom", "frac_w": 0.20}]},
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
    6: [  # ~4,000 sqft — 6/3.5
        {"row_frac_d": 0.26, "rooms": [
            {"type": "living",      "frac_w": 0.38},
            {"type": "kitchen",     "frac_w": 0.32},
            {"type": "dining",      "frac_w": 0.30},
        ]},
        {"row_frac_d": 0.12, "rooms": [
            {"type": "family_room", "frac_w": 0.48},
            {"type": "laundry",     "frac_w": 0.26},
            {"type": "bathroom",    "frac_w": 0.26},
        ]},
        {"row_frac_d": 0.35, "rooms": [
            {"type": "bedroom",  "frac_w": 0.34},  # master
            {"type": "bathroom", "frac_w": 0.16},  # master bath
            {"type": "bedroom",  "frac_w": 0.25},
            {"type": "bedroom",  "frac_w": 0.25},
        ]},
        {"row_frac_d": 0.27, "rooms": [
            {"type": "bedroom",  "frac_w": 0.38},
            {"type": "bedroom",  "frac_w": 0.38},
            {"type": "bathroom", "frac_w": 0.24},
        ]},
    ],
    7: [  # ~5,000 sqft — 7/4
        {"row_frac_d": 0.24, "rooms": [
            {"type": "living",      "frac_w": 0.36},
            {"type": "kitchen",     "frac_w": 0.30},
            {"type": "dining",      "frac_w": 0.34},
        ]},
        {"row_frac_d": 0.12, "rooms": [
            {"type": "family_room", "frac_w": 0.45},
            {"type": "office",      "frac_w": 0.30},
            {"type": "laundry",     "frac_w": 0.25},
        ]},
        {"row_frac_d": 0.32, "rooms": [
            {"type": "bedroom",  "frac_w": 0.32},  # master
            {"type": "bathroom", "frac_w": 0.14},  # master bath
            {"type": "walk_in_closet", "frac_w": 0.12},
            {"type": "bedroom",  "frac_w": 0.22},
            {"type": "bedroom",  "frac_w": 0.20},
        ]},
        {"row_frac_d": 0.32, "rooms": [
            {"type": "bedroom",  "frac_w": 0.28},
            {"type": "bedroom",  "frac_w": 0.28},
            {"type": "bedroom",  "frac_w": 0.26},
            {"type": "bathroom", "frac_w": 0.18},
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
    6: [  # 6BR large estate
        {"row_frac_d": 0.13, "rooms": [
            {"type": "foyer",   "frac_w": 0.20},
            {"type": "living",  "frac_w": 0.50},
            {"type": "library", "frac_w": 0.30},
        ]},
        {"row_frac_d": 0.18, "rooms": [
            {"type": "kitchen",  "frac_w": 0.35},
            {"type": "dining",   "frac_w": 0.30},
            {"type": "pantry",   "frac_w": 0.15},
            {"type": "mudroom",  "frac_w": 0.20},
        ]},
        {"row_frac_d": 0.13, "rooms": [
            {"type": "laundry",  "frac_w": 0.28},
            {"type": "bathroom", "frac_w": 0.22},
            {"type": "office",   "frac_w": 0.50},
        ]},
        {"row_frac_d": 0.56, "rooms": [
            {"type": "family_room", "frac_w": 0.33},
            {"type": "media_room",  "frac_w": 0.27},
            {"type": "gym",         "frac_w": 0.22},
            {"type": "bonus_room",  "frac_w": 0.18},
        ]},
    ],
    7: [  # 7BR large estate
        {"row_frac_d": 0.12, "rooms": [
            {"type": "foyer",   "frac_w": 0.18},
            {"type": "living",  "frac_w": 0.52},
            {"type": "library", "frac_w": 0.30},
        ]},
        {"row_frac_d": 0.17, "rooms": [
            {"type": "kitchen",  "frac_w": 0.33},
            {"type": "dining",   "frac_w": 0.28},
            {"type": "pantry",   "frac_w": 0.18},
            {"type": "mudroom",  "frac_w": 0.21},
        ]},
        {"row_frac_d": 0.13, "rooms": [
            {"type": "laundry",  "frac_w": 0.25},
            {"type": "bathroom", "frac_w": 0.22},
            {"type": "office",   "frac_w": 0.53},
        ]},
        {"row_frac_d": 0.58, "rooms": [
            {"type": "family_room", "frac_w": 0.30},
            {"type": "media_room",  "frac_w": 0.25},
            {"type": "gym",         "frac_w": 0.25},
            {"type": "bonus_room",  "frac_w": 0.20},
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
    5: [  # 5BR large upper — primary suite is the dominant room on the floor
        # The primary suite gets a deep row of its own. Reference plans run the
        # primary at 2.0-2.5x a secondary bedroom (400 vs 160 sqft); the old
        # fracs put it at 1.36x, and in the 5BR case bedroom 3 was actually
        # LARGER than the primary. Bathrooms are also pulled back hard — they
        # used to end up the biggest rooms on the floor.
        {"row_frac_d": 0.38, "rooms": [
            {"type": "bedroom",         "frac_w": 0.46},  # primary suite
            {"type": "bathroom",        "frac_w": 0.20},  # primary bath
            {"type": "walk_in_closet",  "frac_w": 0.14},
            {"type": "bedroom",         "frac_w": 0.20},  # br2
        ]},
        {"row_frac_d": 0.34, "rooms": [
            {"type": "bedroom",    "frac_w": 0.30},  # br3
            {"type": "bedroom",    "frac_w": 0.28},  # br4
            {"type": "bedroom",    "frac_w": 0.27},  # br5
            {"type": "bathroom",   "frac_w": 0.15},
        ]},
        {"row_frac_d": 0.28, "rooms": [
            {"type": "loft",       "frac_w": 0.42},
            {"type": "media_room", "frac_w": 0.36},
            {"type": "bathroom",   "frac_w": 0.22},
        ]},
    ],
    6: [  # 6BR large upper
        {"row_frac_d": 0.36, "rooms": [
            {"type": "bedroom",        "frac_w": 0.44},  # primary suite
            {"type": "bathroom",       "frac_w": 0.19},  # primary bath
            {"type": "walk_in_closet", "frac_w": 0.13},
            {"type": "bedroom",        "frac_w": 0.24},  # br2
        ]},
        {"row_frac_d": 0.34, "rooms": [
            {"type": "bedroom",    "frac_w": 0.28},  # br3
            {"type": "bedroom",    "frac_w": 0.26},  # br4
            {"type": "bedroom",    "frac_w": 0.26},  # br5
            {"type": "bathroom",   "frac_w": 0.20},
        ]},
        {"row_frac_d": 0.30, "rooms": [
            {"type": "bedroom",    "frac_w": 0.34},  # br6
            {"type": "bonus_room", "frac_w": 0.30},
            {"type": "loft",       "frac_w": 0.22},
            {"type": "bathroom",   "frac_w": 0.14},
        ]},
    ],
    7: [  # 7BR large upper
        {"row_frac_d": 0.34, "rooms": [
            {"type": "bedroom",        "frac_w": 0.42},  # primary suite
            {"type": "bathroom",       "frac_w": 0.18},  # primary bath
            {"type": "walk_in_closet", "frac_w": 0.12},
            {"type": "bedroom",        "frac_w": 0.28},  # br2
        ]},
        {"row_frac_d": 0.26, "rooms": [
            {"type": "bedroom",  "frac_w": 0.30},  # br3
            {"type": "bedroom",  "frac_w": 0.28},  # br4
            {"type": "bedroom",  "frac_w": 0.27},  # br5
            {"type": "bathroom", "frac_w": 0.15},
        ]},
        {"row_frac_d": 0.24, "rooms": [
            {"type": "bedroom",    "frac_w": 0.36},  # br6
            {"type": "bedroom",    "frac_w": 0.34},  # br7
            {"type": "bathroom",   "frac_w": 0.16},
            {"type": "bathroom",   "frac_w": 0.14},
        ]},
        {"row_frac_d": 0.16, "rooms": [
            {"type": "loft",       "frac_w": 0.45},
            {"type": "bonus_room", "frac_w": 0.30},
            {"type": "media_room", "frac_w": 0.25},
        ]},
    ],
}

# Threshold: floor plate above this uses expanded large-house programs
# ── Estate / mansion programs ────────────────────────────────────────────────
# frac_w values are the measured room proportions from the reference plan
# backend/app/data/High-End-Custom/R.jpg, not invented ratios. That plan is a
# single-storey mansion: living 20x23.5, kitchen 17x23.5, dining 17x22, master
# 17x21 with a 14x17 bath, down to a 6x7 wine cellar — an 11:1 spread within
# one floor, which is the size hierarchy the large tables never produced.
SFR_GROUND_MANSION: List[Dict] = [
    {"row_frac_d": 0.30, "rooms": [
        {"type": "foyer",       "frac_w": 0.11},
        {"type": "great_room",  "frac_w": 0.59},   # R.jpg living, 470 sqft
        {"type": "office",      "frac_w": 0.24},
        {"type": "wine_cellar", "frac_w": 0.06},   # 6x7 — genuinely small
    ]},
    {"row_frac_d": 0.30, "rooms": [
        {"type": "kitchen",       "frac_w": 0.44},
        {"type": "dining",        "frac_w": 0.41},
        {"type": "butler_pantry", "frac_w": 0.05},
        {"type": "mudroom",       "frac_w": 0.10},
    ]},
    {"row_frac_d": 0.24, "rooms": [
        {"type": "cinema_room", "frac_w": 0.25},
        {"type": "game_room",   "frac_w": 0.25},
        {"type": "laundry",     "frac_w": 0.22},
        {"type": "gym",         "frac_w": 0.19},
        {"type": "half_bath",   "frac_w": 0.09},
    ]},
    {"row_frac_d": 0.16, "rooms": [
        {"type": "loggia",    "frac_w": 0.62},     # 13x32 covered outdoor room
        {"type": "sauna",     "frac_w": 0.17},
        {"type": "pool_bath", "frac_w": 0.21},
    ]},
]

# Upper floor: primary suite occupies most of one row, exactly as R.jpg's
# master + master bath + his/hers closets + sitting room do.
SFR_UPPER_MANSION: List[Dict] = [
    {"row_frac_d": 0.38, "rooms": [
        {"type": "bedroom",        "frac_w": 0.43},   # primary suite
        {"type": "bathroom",       "frac_w": 0.29},   # primary bath
        {"type": "walk_in_closet", "frac_w": 0.17},
        {"type": "sitting_room",   "frac_w": 0.11},
    ]},
    {"row_frac_d": 0.34, "rooms": [
        {"type": "bedroom",  "frac_w": 0.30},
        {"type": "bathroom", "frac_w": 0.13},
        {"type": "bedroom",  "frac_w": 0.30},
        {"type": "bathroom", "frac_w": 0.13},
        {"type": "library",  "frac_w": 0.14},
    ]},
    {"row_frac_d": 0.28, "rooms": [
        {"type": "bedroom",    "frac_w": 0.32},
        {"type": "bedroom",    "frac_w": 0.30},
        {"type": "bathroom",   "frac_w": 0.16},
        {"type": "bonus_room", "frac_w": 0.22},
    ]},
]

# Per-floor plate above which the estate programs are used instead of the
# "large" ones. 230 m2 = ~2,475 sqft per floor; R.jpg's own interior floor is
# roughly twice that.
MANSION_THRESHOLD_M2 = 230.0

LARGE_HOUSE_THRESHOLD_M2 = 80.0  # ~860 sqft per floor

# For multi-story SFR: floor 0 is public, floor 1+ is private (bedrooms)
SFR_GROUND_ROWS = {  # standard — keyed by bedrooms
    1: [SFR_PROGRAMS[1][0], SFR_PROGRAMS[1][1]],
    2: [SFR_PROGRAMS[2][0], SFR_PROGRAMS[2][1]],
    3: [SFR_PROGRAMS[3][0], SFR_PROGRAMS[3][1]],
    4: [SFR_PROGRAMS[4][0], SFR_PROGRAMS[4][1]],
    5: [SFR_PROGRAMS[5][0], SFR_PROGRAMS[5][1]],
    6: [SFR_PROGRAMS[6][0], SFR_PROGRAMS[6][1]],
    7: [SFR_PROGRAMS[7][0], SFR_PROGRAMS[7][1]],
}
def _upper_rows(br: int) -> List[Dict]:
    """Private upper-floor program: a shallow landing/hall band, then the
    bedroom rows.

    Rows 0 and 1 of SFR_PROGRAMS (living / kitchen / dining) are deliberately
    excluded — they are exactly what SFR_GROUND_ROWS already emits, so any
    upper floor built from the full program renders as a pixel-copy of floor 0.
    The leading hall band also gives the staircase somewhere to land instead
    of arriving in the middle of a bedroom.
    """
    hall = {"row_frac_d": 0.18, "rooms": [
        {"type": "corridor",       "frac_w": 0.62},
        {"type": "walk_in_closet", "frac_w": 0.38},
    ]}
    # Bedroom rows carry their own master bath, so no extra bath is added here.
    return [hall] + [dict(row) for row in SFR_PROGRAMS[br][2:]]


SFR_UPPER_ROWS = {br: _upper_rows(br) for br in SFR_PROGRAMS}

# Rooms that are circulation/service only — a floor made up of nothing but
# these has no habitable space and is a layout failure, not a valid plan.
_CIRCULATION_ONLY_TYPES = {"stair", "corridor", "hall", "hallway", "unit"}

# ── Room size ceilings ───────────────────────────────────────────────────────
# Medians measured across the training-label plans (backend/app/data/training)
# and blueprint_index: garage 520, living 280, dining 182, bedroom 160, kitchen
# 153, bathroom 72, closet 36 sqft. A room program has a FIXED number of rooms,
# so on a big plate the extra area inflated every room instead of adding any —
# a 6,800 sqft single-storey house came out with the same 16 rooms as a 4,200
# one, giving an 881 sqft kitchen and a 540 sqft dining room. Past these
# ceilings a cell is split and the remainder becomes a companion room.
ROOM_MAX_SQFT: Dict[str, float] = {
    "great_room": 520, "living": 420, "family_room": 400, "dining": 340,
    "kitchen": 340, "office": 260, "library": 260, "bedroom": 340,
    "bathroom": 160, "half_bath": 70, "walk_in_closet": 130,
    "cinema_room": 320, "game_room": 320, "media_room": 300, "gym": 300,
    "loggia": 420, "garage": 700, "laundry": 160, "mudroom": 140,
    "pantry": 90, "butler_pantry": 90, "wine_cellar": 90, "sauna": 90,
    "pool_bath": 90, "utility": 140, "mechanical": 140, "bonus_room": 380,
    "loft": 380, "sitting_room": 220, "foyer": 200, "corridor": 260,
    "dressing_room": 150, "storage": 110, "closet": 70, "deck": 320,
}

# What the leftover half of an oversized room becomes.
_SPLIT_COMPANION: Dict[str, str] = {
    "great_room": "sitting_room", "living": "sitting_room",
    "family_room": "sitting_room", "dining": "butler_pantry",
    "kitchen": "pantry", "bedroom": "walk_in_closet",
    "bathroom": "walk_in_closet", "office": "library",
    "library": "office", "cinema_room": "game_room",
    "game_room": "cinema_room", "gym": "sauna", "loggia": "deck",
    "garage": "utility", "bonus_room": "loft", "loft": "bonus_room",
    "corridor": "corridor", "foyer": "corridor",
    # Terminating links, so a very large cell keeps splitting down to
    # realistically small service rooms instead of leaving a 500 sqft pantry.
    "sitting_room": "office", "pantry": "storage",
    "butler_pantry": "pantry", "storage": "closet",
    "walk_in_closet": "closet", "laundry": "storage",
    "utility": "storage", "media_room": "storage", "deck": "deck",
}

_MIN_SPLIT_SQFT = 55.0   # never create a room smaller than this by splitting


def subdivide_cell(
    x0: float, y0: float, x1: float, y1: float, room_type: str, depth: int = 0,
) -> List[Tuple[Tuple[float, float, float, float], str]]:
    """Split an oversized cell into a room plus a companion, recursively.

    Splits across the cell's longer axis so neither half becomes a slot, and
    stops as soon as either half would fall under _MIN_SPLIT_SQFT or the room
    type has no sensible companion.
    """
    rect = (x0, y0, x1, y1)
    area_sqft = abs(x1 - x0) * abs(y1 - y0) * 10.764
    cap = ROOM_MAX_SQFT.get(room_type)
    companion = _SPLIT_COMPANION.get(room_type)
    if (
        cap is None or companion is None or depth >= 4
        or area_sqft <= cap or area_sqft < _MIN_SPLIT_SQFT * 2
    ):
        return [(rect, room_type)]

    # Give the primary room its full allowance and the remainder to the
    # companion, rather than halving — a great room should stay the big room.
    keep = min(max(cap / area_sqft, 0.35), 0.80)
    wide = abs(x1 - x0) >= abs(y1 - y0)
    if wide:
        cut = x0 + (x1 - x0) * keep
        a, b = (x0, y0, cut, y1), (cut, y0, x1, y1)
    else:
        cut = y0 + (y1 - y0) * keep
        a, b = (x0, y0, x1, cut), (x0, cut, x1, y1)

    for r in (a, b):
        if abs(r[2] - r[0]) * abs(r[3] - r[1]) * 10.764 < _MIN_SPLIT_SQFT:
            return [(rect, room_type)]

    return (
        subdivide_cell(*a, room_type, depth + 1)
        + subdivide_cell(*b, companion, depth + 1)
    )


# ── Open-plan circulation ────────────────────────────────────────────────────
# Whether a house walls its halls off or lets them run into the living space is
# an era/style decision, not a geometric one. A mid-century or contemporary
# plan opens the hall to the great room and the kitchen to the dining; a
# Victorian or a tract builder walls all of it.
OPEN_PLAN_ARCHETYPES = {
    "mid_century_modern", "prefab_modern", "high_end_custom",
    "urban_infill_zero_lot", "high_density_townhome",
}

# Pairs that lose their wall in an open-plan house.
_OPEN_PAIRS_FULL = {
    frozenset(p) for p in [
        ("great_room", "kitchen"), ("great_room", "dining"),
        ("great_room", "corridor"), ("great_room", "hall"),
        ("great_room", "foyer"), ("great_room", "loggia"),
        ("living", "kitchen"), ("living", "dining"),
        ("living", "family_room"), ("living", "corridor"),
        ("living", "hall"), ("living", "foyer"),
        ("kitchen", "dining"), ("kitchen", "family_room"),
        ("dining", "corridor"), ("dining", "hall"), ("dining", "loggia"),
        ("family_room", "corridor"), ("family_room", "hall"),
        ("foyer", "corridor"), ("foyer", "hall"),
        ("sitting_room", "bedroom"),
    ]
}

# Even a traditional plan runs the kitchen into the breakfast/dining area and
# leaves the entry open to the hall — it just keeps its living rooms walled.
_OPEN_PAIRS_TRADITIONAL = {
    frozenset(p) for p in [
        ("kitchen", "dining"),
        ("foyer", "corridor"), ("foyer", "hall"),
    ]
}


def open_pairs_for(archetype_id: str) -> set:
    return (
        _OPEN_PAIRS_FULL if archetype_id in OPEN_PLAN_ARCHETYPES
        else _OPEN_PAIRS_TRADITIONAL
    )


def _rooms_along_wall(
    wall: Wall, level_rooms: List[Room], horizontal: bool, line_coord: float,
) -> List[Tuple[float, float, str, bool]]:
    """Every room edge lying on this wall's line, as (lo, hi, type, is_far).

    `is_far` is which side of the line the room's body sits on.
    """
    spans: List[Tuple[float, float, str, bool]] = []
    for room in level_rooms:
        pts = room.polygon
        vals = [p[1] if horizontal else p[0] for p in pts]
        far = (sum(vals) / len(vals)) >= line_coord
        for i in range(len(pts)):
            ex0, ey0 = pts[i]
            ex1, ey1 = pts[(i + 1) % len(pts)]
            if horizontal:
                if abs(ey0 - line_coord) > 0.03 or abs(ey1 - line_coord) > 0.03:
                    continue
                lo, hi = min(ex0, ex1), max(ex0, ex1)
            else:
                if abs(ex0 - line_coord) > 0.03 or abs(ex1 - line_coord) > 0.03:
                    continue
                lo, hi = min(ey0, ey1), max(ey0, ey1)
            if hi - lo > 0.05:
                spans.append((lo, hi, room.type, far))
    return spans


def split_and_mark_open_walls(
    rooms: List[Room], walls: List[Wall], archetype_id: str,
) -> List[Wall]:
    """Split interior walls where the rooms either side change, then flag the
    stretches that should be cased openings.

    A row-based layout produces one long wall between two rows, so the same
    wall object is simultaneously the great-room/kitchen boundary and the
    office/kitchen boundary. Marking whole walls therefore opened almost
    nothing: any stretch that also backed onto a study or a closet kept the
    entire run walled. Splitting first lets the great room open to the kitchen
    while the study beside it stays enclosed.
    """
    pairs = open_pairs_for(archetype_id)
    by_level: Dict[int, List[Room]] = {}
    for room in rooms:
        if len(room.polygon) >= 3:
            by_level.setdefault(room.level, []).append(room)

    out: List[Wall] = []
    for wall in walls:
        x0, y0 = wall.start[0], wall.start[1]
        x1, y1 = wall.end[0], wall.end[1]
        horizontal = abs(y1 - y0) <= 1e-3
        vertical = abs(x1 - x0) <= 1e-3
        if wall.is_exterior or not (horizontal or vertical):
            out.append(wall)
            continue

        line_coord = (y0 + y1) / 2 if horizontal else (x0 + x1) / 2
        w_lo, w_hi = (
            (min(x0, x1), max(x0, x1)) if horizontal else (min(y0, y1), max(y0, y1))
        )
        spans = _rooms_along_wall(wall, by_level.get(wall.level, []), horizontal, line_coord)
        if not spans:
            out.append(wall)
            continue

        cuts = sorted({w_lo, w_hi} | {
            v for lo, hi, _t, _f in spans for v in (lo, hi) if w_lo < v < w_hi
        })
        segments: List[Tuple[float, float, bool]] = []
        for a, b in zip(cuts, cuts[1:]):
            if b - a < 0.12:          # ignore slivers
                continue
            mid = (a + b) / 2
            near = {t for lo, hi, t, far in spans if lo <= mid <= hi and not far}
            far_ = {t for lo, hi, t, far in spans if lo <= mid <= hi and far}
            is_open = bool(near and far_) and all(
                frozenset((p, q)) in pairs for p in near for q in far_
            )
            segments.append((a, b, is_open))

        if not segments:
            out.append(wall)
            continue
        # Nothing to gain from splitting a run that is uniformly one or the other.
        if all(seg[2] == segments[0][2] for seg in segments):
            wall.is_open = segments[0][2]
            out.append(wall)
            continue

        for idx, (a, b, is_open) in enumerate(segments):
            start = [a, line_coord] if horizontal else [line_coord, a]
            end = [b, line_coord] if horizontal else [line_coord, b]
            out.append(Wall(
                id=f"{wall.id}_s{idx}", start=start, end=end,
                height_ft=wall.height_ft, level=wall.level,
                is_exterior=False, is_shear=wall.is_shear, is_open=is_open,
            ))
    return out


def mark_open_walls(rooms: List[Room], walls: List[Wall], archetype_id: str) -> None:
    """Flag interior walls that should be cased openings instead of walls.

    Runs after wall derivation because that step works from bare rectangles and
    has no idea what room types sit either side. Matching mirrors
    floorplan_editor.move_wall: same supporting line, and a real overlap along
    the wall rather than a midpoint test.
    """
    pairs = open_pairs_for(archetype_id)
    if not pairs:
        return
    by_level: Dict[int, List[Room]] = {}
    for room in rooms:
        if len(room.polygon) >= 3:
            by_level.setdefault(room.level, []).append(room)

    for wall in walls:
        if wall.is_exterior:
            continue
        x0, y0 = wall.start[0], wall.start[1]
        x1, y1 = wall.end[0], wall.end[1]
        horizontal = abs(y1 - y0) <= 1e-3
        vertical = abs(x1 - x0) <= 1e-3
        if not (horizontal or vertical):
            continue
        line_coord = (y0 + y1) / 2 if horizontal else (x0 + x1) / 2
        w_lo, w_hi = (
            (min(x0, x1), max(x0, x1)) if horizontal else (min(y0, y1), max(y0, y1))
        )
        min_overlap = min(0.25, (w_hi - w_lo) * 0.6)

        # Rooms touching this wall, split by which side of it they sit on. A
        # single long wall commonly separates a set of rooms from another set —
        # the great room from both the kitchen and the dining, say — so
        # requiring exactly two touching rooms left most boundaries
        # unclassifiable and almost nothing opened up.
        near: List[str] = []
        far: List[str] = []
        for room in by_level.get(wall.level, []):
            best = 0.0
            pts = room.polygon
            for i in range(len(pts)):
                ex0, ey0 = pts[i]
                ex1, ey1 = pts[(i + 1) % len(pts)]
                if horizontal:
                    if abs(ey0 - line_coord) > 0.03 or abs(ey1 - line_coord) > 0.03:
                        continue
                    e_lo, e_hi = min(ex0, ex1), max(ex0, ex1)
                else:
                    if abs(ex0 - line_coord) > 0.03 or abs(ex1 - line_coord) > 0.03:
                        continue
                    e_lo, e_hi = min(ey0, ey1), max(ey0, ey1)
                best = max(best, min(w_hi, e_hi) - max(w_lo, e_lo))
            if best < min_overlap:
                continue
            vals = [p[1] if horizontal else p[0] for p in room.polygon]
            centre = sum(vals) / len(vals)
            (far if centre >= line_coord else near).append(room.type)

        # Open only when EVERY pairing across the boundary is an open one — a
        # wall that also backs onto a bedroom stays a wall.
        if near and far and all(
            frozenset((a, b)) in pairs for a in set(near) for b in set(far)
        ):
            wall.is_open = True


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
        ai_room_program: Optional[List[Dict]] = None,
        ai_unit_program: Optional[Dict] = None,  # from get_ai_unit_program (MF)
    ) -> Tuple[List[Room], List[Wall]]:

        footprint_coords = massing_option["footprint"]
        footprint = Polygon(footprint_coords)
        bounds = footprint.bounds
        w = bounds[2] - bounds[0]
        d = bounds[3] - bounds[1]

        all_rooms: List[Room] = []
        all_walls: List[Wall] = []

        is_sfr = getattr(spec, 'building_use', None) in (
            'single_family', BuildingUse.single_family
        )
        bedrooms = getattr(spec, 'bedrooms', None) or 1

        # Build a quick lookup: floor index → row program (from AI output)
        ai_floors: Dict[int, List[Dict]] = {}
        if ai_room_program:
            for fl in ai_room_program:
                ai_floors[fl["floor"]] = fl["rows"]

        # get_ai_unit_program's unit_mix is a PER-FLOOR unit count (see
        # ai_room_program.py's prompt: "unit_mix values are PER FLOOR"). This was
        # being computed and logged but never actually consumed by the layout —
        # _layout_multifamily_floor independently packed as many units as the
        # footprint could geometrically fit, silently ignoring what the AI decided.
        ai_units_per_floor: Optional[int] = None
        if ai_unit_program and ai_unit_program.get("unit_mix"):
            ai_units_per_floor = sum(int(v) for v in ai_unit_program["unit_mix"].values())

        for level in levels:
            if is_sfr:
                # ── Primary path: use AI-generated row program for this floor ──
                ai_rows = ai_floors.get(level.index)
                if ai_rows:
                    rooms, walls = self._layout_sfr_floor_from_rows(
                        footprint, bounds, w, d, level, levels, ai_rows, archetype=archetype
                    )
                else:
                    # Fallback: static programs
                    rooms, walls = self._layout_sfr_floor(
                        footprint, bounds, w, d, level, levels, bedrooms, archetype=archetype
                    )
            else:
                rooms, walls = self._layout_multifamily_floor(
                    footprint, bounds, w, d, level, spec, ai_units_per_floor=ai_units_per_floor
                )

            # Never ship a floor that is nothing but circulation.
            #
            # Every layout path filters out rooms that fall below their minimum
            # width/area, and on a tight plate that filter can reject ALL of
            # them — the corridor and stair survive because they're generated
            # separately, so the floor silently came out as "2 rooms, 0 units"
            # with no error anywhere in the log. Fall back to the single-unit
            # SFR layout, which degrades far better on small footprints, and
            # only accept the circulation-only result if that fails too.
            if not any(r.type not in _CIRCULATION_ONLY_TYPES for r in rooms):
                rescue_rooms, rescue_walls = self._layout_sfr_floor(
                    footprint, bounds, w, d, level, levels, bedrooms, archetype=archetype
                )
                if any(r.type not in _CIRCULATION_ONLY_TYPES for r in rescue_rooms):
                    rooms, walls = rescue_rooms, rescue_walls

            all_rooms.extend(rooms)
            all_walls.extend(walls)

        all_rooms = self._add_stair_landings(all_rooms)
        carved = self._carve_vertical_cores(all_rooms)
        all_walls = split_and_mark_open_walls(
            carved, all_walls, (archetype or {}).get('id', ''),
        )
        return carved, all_walls

    def _add_stair_landings(self, rooms: List[Room]) -> List[Room]:
        """Give every staircase a landing.

        The stair is placed after the row program and then carves itself out of
        whatever it overlaps, so it ended up as an isolated box floating in the
        middle of the plate with rooms butted straight against it — you arrive
        at the top of the flight into the side of a bedroom. A real plan always
        has circulation at the head of the stair. Skipped when the stair already
        touches a hall or corridor.
        """
        CIRC = {"corridor", "hall", "hallway", "foyer", "entry"}
        by_level: Dict[int, List[Room]] = {}
        for room in rooms:
            if len(room.polygon) >= 3:
                by_level.setdefault(room.level, []).append(room)

        landings: List[Room] = []
        for stair in [r for r in rooms if r.type == "stair" and len(r.polygon) >= 3]:
            level_rooms = by_level.get(stair.level, [])
            try:
                stair_poly = Polygon(stair.polygon)
            except Exception:
                continue
            touching_circ = any(
                other.type in CIRC
                and Polygon(other.polygon).buffer(0.12).intersects(stair_poly)
                for other in level_rooms
                if other.id != stair.id and len(other.polygon) >= 3
            )
            if touching_circ:
                continue

            sxs = [p[0] for p in stair.polygon]
            szs = [p[1] for p in stair.polygon]
            sx0, sx1 = min(sxs), max(sxs)
            sz0, sz1 = min(szs), max(szs)
            depth = 1.25
            # Try each side, keep the first that lands inside the building and
            # doesn't simply sit on top of another staircase.
            candidates = [
                (sx1, sz0, sx1 + depth, sz1), (sx0 - depth, sz0, sx0, sz1),
                (sx0, sz1, sx1, sz1 + depth), (sx0, sz0 - depth, sx1, sz0),
            ]
            host = None
            for (lx0, lz0, lx1, lz1) in candidates:
                cand = Polygon([[lx0, lz0], [lx1, lz0], [lx1, lz1], [lx0, lz1]])
                if cand.area < 1.0:
                    continue
                covered = sum(
                    cand.intersection(Polygon(o.polygon)).area
                    for o in level_rooms
                    if o.id != stair.id and o.type != "stair" and len(o.polygon) >= 3
                )
                # Must be substantially inside the building, not hanging out of it.
                if covered >= cand.area * 0.75:
                    host = cand
                    break
            if host is None:
                continue
            landings.append(Room(
                id=f"landing_{stair.level}_{uuid.uuid4().hex[:5]}",
                type="corridor", unit_id=stair.unit_id or "house",
                polygon=[[c[0], c[1]] for c in list(host.exterior.coords)[:-1]],
                level=stair.level, area_sqft=host.area * 10.764,
            ))
        return rooms + landings

    def _carve_vertical_cores(self, rooms: List[Room]) -> List[Room]:
        """Remove stair/core footprints from every overlapping programmed room.

        A room is carved by the cores on its OWN level and by those on the
        level BELOW it. The second half is what opens the stairwell: a flight
        rising from level N needs a hole in level N+1's floor to arrive
        through, but the AI room program is told not to place a stair room on
        the topmost floor, so nothing on level N+1 used to mark that void and
        the upper slab sealed over the staircase — you could see the steps run
        up into the underside of a bedroom floor. Carving level N's core out of
        level N+1's rooms creates the opening whether or not the upper level
        programmed a stair of its own. (Floor slabs are skipped for rooms typed
        "stair", so the carved-out region renders as an actual void.)
        """
        cores_by_level: Dict[int, List[Polygon]] = {}
        # Stair landings carve their host rooms the same way the stair does,
        # otherwise the landing simply overlaps whatever it was placed against.
        landing_by_level: Dict[int, List[Polygon]] = {}
        for room in rooms:
            if len(room.polygon) < 3:
                continue
            if room.type == "stair":
                cores_by_level.setdefault(room.level, []).append(Polygon(room.polygon))
            elif room.id.startswith("landing_"):
                landing_by_level.setdefault(room.level, []).append(Polygon(room.polygon))
        if not cores_by_level:
            return rooms
        carved: List[Room] = []
        for room in rooms:
            applicable = (
                cores_by_level.get(room.level, [])
                + cores_by_level.get(room.level - 1, [])
                + landing_by_level.get(room.level, [])
            )
            if room.type == "stair" or room.id.startswith("landing_") or not applicable:
                carved.append(room)
                continue
            remainder = Polygon(room.polygon)
            for core in applicable:
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
        ai_units_per_floor: Optional[int] = None,
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
        MIN_BAND_DEPTH_M = 2.5

        # Try a double-loaded corridor plan (front + back bands split by a central
        # hallway) first — that's the normal apartment-building layout. But a
        # narrow-lot rowhouse is architecturally single-loaded (one unit
        # front-to-back, no central hallway), and once the stair core eats into a
        # shallow footprint there may not be enough depth left for BOTH bands to
        # clear their minimum size — that wiped out every unit, leaving only the
        # stair/corridor rooms behind. If the corridor attempt yields zero usable
        # components, discard it and fall back to a single-loaded plan that uses
        # the whole available footprint as one component instead.
        corridor_z0 = min_z + (d - CORRIDOR_WIDTH_M) / 2.0
        corridor_strip = box(min_x, corridor_z0, max_x, corridor_z0 + CORRIDOR_WIDTH_M)
        corridor_shape = available.intersection(corridor_strip)
        if hasattr(corridor_shape, "geoms"):
            corridor_parts = [
                geometry for geometry in corridor_shape.geoms
                if geometry.geom_type == "Polygon" and geometry.area >= 1.0
            ]
            corridor_shape = max(corridor_parts, key=lambda geometry: geometry.area) if corridor_parts else None

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
                and (geometry.bounds[3] - geometry.bounds[1]) >= MIN_BAND_DEPTH_M
            )

        if components:
            if corridor_shape is not None and not corridor_shape.is_empty and hasattr(corridor_shape, "exterior"):
                rooms.append(Room(
                    id=f"corridor_{lvl}", type="corridor",
                    polygon=[[c[0], c[1]] for c in list(corridor_shape.exterior.coords)[:-1]],
                    level=lvl, area_sqft=corridor_shape.area * 10.764,
                ))
        else:
            geometries = list(available.geoms) if hasattr(available, "geoms") else [available]
            components = [
                geometry for geometry in geometries
                if geometry.geom_type == "Polygon" and geometry.area >= 6.0
                and (geometry.bounds[3] - geometry.bounds[1]) >= MIN_BAND_DEPTH_M
            ]
        # Priority: an explicit user-set total unit_count beats everything; next,
        # the AI's own per-floor decision (get_ai_unit_program's unit_mix, already
        # a per-floor count); only pack "as many units as geometrically fit" when
        # neither said anything — that geometric default is what silently doubled
        # the AI's intended unit count whenever unit_count wasn't set explicitly.
        explicit_requested: Optional[int] = None
        if spec.unit_count:
            explicit_requested = max(1, math.ceil(spec.unit_count / max(spec.stories, 1)))
        elif ai_units_per_floor:
            explicit_requested = max(1, ai_units_per_floor)

        # "Every disconnected wing gets at least one cell" only makes sense as a
        # default when nobody said how many units they want — it must not
        # override an explicit request. A shallow band split (or the stair core
        # clipping a corner) can fragment one architectural wing into several
        # small polygons; forcing a unit into each one silently inflated the
        # count past whatever was actually requested. When a count IS explicit
        # and there are more raw components than that, keep only the largest
        # ones (an explicit request caps things; it doesn't get overridden by
        # incidental geometry fragmentation).
        if explicit_requested is not None and len(components) > explicit_requested:
            components = sorted(components, key=lambda geometry: geometry.area, reverse=True)[:explicit_requested]
        components.sort(key=lambda geometry: (geometry.bounds[1], geometry.bounds[0]))

        slots = [max(1, round((component.bounds[2] - component.bounds[0]) / 7.5)) for component in components]
        requested_per_floor = explicit_requested if explicit_requested is not None else sum(slots)
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

    def _layout_sfr_floor_from_rows(
        self,
        footprint: Polygon,
        bounds: tuple,
        w: float,
        d: float,
        level: Any,
        all_levels: list,
        row_program: List[Dict],
        archetype: Optional[Dict] = None,
    ) -> Tuple[List[Room], List[Wall]]:
        """
        Place rooms from an AI-generated row program.
        Same geometry logic as _layout_sfr_floor but driven by Claude's output.
        """
        from app.constants import BuildingUse
        from shapely.geometry import Point

        rooms: List[Room] = []
        walls: List[Wall] = []
        lvl   = level.index
        minx, miny = bounds[0], bounds[1]
        floor_h_m  = level.height_ft * 0.3048 if hasattr(level, 'height_ft') else 3.05

        fp_interior = footprint.buffer(-FP_INSET, join_style=2)

        _MIN_W: Dict[str, float] = {
            "bedroom": 2.7, "bathroom": 1.5, "kitchen": 2.4,
            "living": 3.0, "dining": 2.4, "family_room": 3.0,
            "office": 2.4, "loft": 2.4, "media_room": 2.7,
            "laundry": 1.5, "mudroom": 1.5, "foyer": 1.5,
            "corridor": 1.1, "hall": 1.1, "walk_in_closet": 1.2,
            "deck": 1.5, "garage": 2.7, "half_bath": 1.2,
        }

        room_rects: List[Tuple[float, float, float, float]] = []
        y_cursor = miny

        for row in row_program:
            row_d = d * row["row_frac_d"]
            row_y0, row_y1 = y_cursor, y_cursor + row_d

            raw_widths = [w * rdef["frac_w"] for rdef in row["rooms"]]
            mins       = [_MIN_W.get(rdef["type"], 1.2) for rdef in row["rooms"]]
            clamped    = [max(rw, mn) for rw, mn in zip(raw_widths, mins)]
            clamp_tot  = sum(clamped)
            if clamp_tot > w:
                scale = w / clamp_tot
                adj   = [c * scale for c in clamped]
            else:
                leftover  = w - clamp_tot
                over_min  = [max(rw - mn, 0.0) for rw, mn in zip(raw_widths, mins)]
                over_tot  = sum(over_min) or 1.0
                adj = [cl + leftover * (ov / over_tot) for cl, ov in zip(clamped, over_min)]

            x_cursor = minx
            for rdef, rw in zip(row["rooms"], adj):
                rx0, rx1 = x_cursor, x_cursor + rw
                # A program has a fixed room count, so on a large plate the
                # spare area used to inflate every room rather than add any:
                # the same 16 rooms whether the floor was 4,200 or 6,800 sqft,
                # which is how a kitchen ended up at 881 sqft. Cells past their
                # type's ceiling are split, the remainder becoming a companion
                # room (kitchen -> pantry, bedroom -> closet, and so on).
                for (sx0, sy0, sx1, sy1), stype in subdivide_cell(
                    rx0, row_y0, rx1, row_y1, rdef["type"]
                ):
                    sub_area = (sx1 - sx0) * (sy1 - sy0)
                    cell = Polygon([
                        [sx0, sy0], [sx1, sy0], [sx1, sy1], [sx0, sy1],
                    ])
                    try:
                        clipped = fp_interior.intersection(cell)
                        if hasattr(clipped, 'geoms'):
                            clipped = max(clipped.geoms, key=lambda g: g.area)
                        if (clipped.is_empty or not hasattr(clipped, 'exterior')
                                or clipped.area < max(0.5, sub_area * 0.25)):
                            continue
                        poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                        cb = clipped.bounds
                        area = clipped.area * 10.764
                    except Exception:
                        if not fp_interior.contains(
                            Point((sx0 + sx1) / 2, (sy0 + sy1) / 2)
                        ):
                            continue
                        poly = [[sx0, sy0], [sx1, sy0], [sx1, sy1], [sx0, sy1]]
                        cb = (sx0, sy0, sx1, sy1)
                        area = sub_area * 10.764

                    rooms.append(Room(
                        id=f"ai_{stype}_{lvl}_{uuid.uuid4().hex[:5]}",
                        type=stype,
                        unit_id="house",
                        level=lvl,
                        polygon=poly,
                        area_sqft=round(area, 1),
                        center=[(cb[0] + cb[2]) / 2, (cb[1] + cb[3]) / 2],
                        dimensions={"w_m": round(cb[2] - cb[0], 2),
                                    "d_m": round(cb[3] - cb[1], 2)},
                    ))
                    room_rects.append((sx0, sy0, sx1, sy1))
                x_cursor += rw
            y_cursor += row_d

        # Stair fallback: add if AI missed it, but never on the topmost floor.
        n_floors = len(all_levels)
        is_top_floor = (lvl == n_floors - 1)
        if n_floors > 1 and not is_top_floor and "stair" not in {r.type for r in rooms}:
            maxx_sfr  = minx + w
            stair_w_s = min(w * 0.15, 1.5)
            stair_d_s = min(d * 0.28, 3.5)
            stair_loc = ((archetype or {}).get("staircase") or {}).get("location", "rear_right")
            if "left" in stair_loc or "spine" in stair_loc:
                sr_x0 = minx
            elif "center" in stair_loc:
                sr_x0 = minx + (w - stair_w_s) / 2
            else:  # rear_right / default
                sr_x0 = maxx_sfr - stair_w_s
            sr_y0 = miny + (d - stair_d_s) / 2
            # Right edge is sr_x0 + stair_w_s, NOT maxx_sfr: pinning it to the
            # far wall made the "left"/"spine" archetypes (
            # hillside_stepped, the townhomes) emit a stair band spanning the
            # entire footprint width, and "center" one spanning half of it.
            # _carve_vertical_cores then subtracted that band from every room
            # it crossed, keeping only the largest fragment of each.
            sr_x1 = sr_x0 + stair_w_s
            raw_stair = Polygon([[sr_x0, sr_y0], [sr_x1, sr_y0],
                                  [sr_x1, sr_y0 + stair_d_s], [sr_x0, sr_y0 + stair_d_s]])
            stair_poly = None
            try:
                cs = fp_interior.intersection(raw_stair)
                if hasattr(cs, 'geoms'):
                    cs = max(cs.geoms, key=lambda g: g.area)
                if not cs.is_empty and hasattr(cs, 'exterior') and cs.area >= 0.05:
                    stair_poly = [[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]]
            except Exception:
                pass
            if stair_poly:
                rooms.append(Room(id=f"ai_stair_{lvl}_{uuid.uuid4().hex[:5]}",
                                  type="stair", unit_id="house",
                                  polygon=stair_poly, level=lvl,
                                  area_sqft=round(stair_w_s * stair_d_s * 10.764, 1)))

        # Interior + exterior walls (same as static path)
        self._emit_interior_walls(room_rects, footprint, fp_interior, level, walls)
        walls.extend(self._place_exterior_walls(footprint, level))
        return rooms, walls

    def _layout_floor(
        self, footprint, bounds, w, d, level: Level, _spec: ProjectSpec,
        ai_unit_program: Optional[Dict] = None,
    ) -> Tuple[List[Room], List[Wall]]:
        """
        Multi-family floor layout with two modes:
          - Duplex (≤1 unit fits across width): stair at rear-right, units fill front.
          - Apartment (2+ units fit): double-loaded corridor at center, stair at left end.
        """
        rooms: List[Room] = []
        walls: List[Wall] = []
        lvl = level.index
        minx, miny, maxx, maxy = bounds
        fp_interior_mf = footprint.buffer(-FP_INSET, join_style=2)
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

        # Resolve unit mix and AI templates
        if ai_unit_program and ai_unit_program.get("unit_mix"):
            unit_mix = {k: v for k, v in ai_unit_program["unit_mix"].items() if v > 0}
        else:
            unit_mix = self._determine_unit_mix(w, d)
        ai_templates = (ai_unit_program or {}).get("templates", {})

        # Pick primary template to assess how many units fit width-wise
        primary_type = next(iter(unit_mix), "3br")
        _base = UNIT_TEMPLATES.get(primary_type) or UNIT_TEMPLATES.get("3br") or UNIT_TEMPLATES["1br"]
        _ai   = ai_templates.get(primary_type) or {}
        tmpl_w = float(_ai.get("w", _base["w"]))

        # How many units actually fit across the building width?
        units_across = max(1, int(w / tmpl_w)) if tmpl_w > 0 else 1

        all_rects: List[Tuple[float, float, float, float]] = []

        if units_across <= 1:
            # ── Duplex / stacked unit: one unit per floor ───────────────
            # Stair tucked into rear-right corner — front is all living space.
            stair_w_s = min(STAIR_W_M, w * 0.22)
            stair_d_s = min(STAIR_D_M, d * 0.30)
            sx0 = maxx - stair_w_s
            sy0 = maxy - stair_d_s
            raw_stair = Polygon([[sx0, sy0], [maxx, sy0], [maxx, maxy], [sx0, maxy]])
            stair_poly = None
            try:
                cs = fp_interior_mf.intersection(raw_stair)
                if hasattr(cs, 'geoms'):
                    cs = max(cs.geoms, key=lambda g: g.area)
                if not cs.is_empty and hasattr(cs, 'exterior') and cs.area >= 0.5:
                    stair_poly = [[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]]
            except Exception:
                pass
            if stair_poly:
                rooms.append(Room(id=f"stair_{lvl}", type="stair",
                                  polygon=stair_poly, level=lvl,
                                  area_sqft=round(stair_w_s * stair_d_s * 10.764, 1)))

            # Single unit fills the entire floor (minus stair corner)
            uid = f"unit_{primary_type}_{lvl}_0"
            tmpl = {**_base, **{k: v for k, v in _ai.items() if k in ("w", "d", "rows")}}
            # Stretch width and depth to fill the whole footprint
            uw = w
            ud = d
            raw_unit = Polygon([[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy]])
            try:
                clipped = fp_interior_mf.intersection(raw_unit)
                if hasattr(clipped, 'geoms'):
                    clipped = max(clipped.geoms, key=lambda g: g.area)
                if not clipped.is_empty and hasattr(clipped, 'exterior') and clipped.area >= 6.0:
                    unit_poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                    cb = clipped.bounds
                    uw, ud = cb[2] - cb[0], cb[3] - cb[1]
                else:
                    clipped = None
            except Exception:
                clipped = None

            if clipped is not None:
                rooms.append(Room(id=uid, type="unit", unit_id=uid,
                                  polygon=unit_poly, level=lvl,
                                  area_sqft=round(clipped.area * 10.764, 1)))
                sub_rooms = self._place_unit_rooms(
                    uid, cb[0], cb[1], uw, ud, tmpl, lvl, fp_interior=fp_interior_mf,
                )
                rooms.extend(sub_rooms)
                all_rects.append((cb[0], cb[1], cb[2], cb[3]))
                all_rects.extend(self._unit_subrects(cb, tmpl))

        else:
            # ── Apartment: double-loaded corridor at center ─────────────
            # Corridor runs east-west across the center of the building.
            # Stair at left end of corridor. Units fill front and back zones.
            corr_cy     = (miny + maxy) / 2
            corr_y0     = corr_cy - CORRIDOR_WIDTH_M / 2
            corr_y1     = corr_cy + CORRIDOR_WIDTH_M / 2
            # Stair takes the left slice of the corridor zone
            stair_w_s   = min(STAIR_W_M, w * 0.18)
            stair_y0    = miny
            stair_y1    = maxy
            raw_stair   = Polygon([[minx, stair_y0], [minx + stair_w_s, stair_y0],
                                    [minx + stair_w_s, stair_y1], [minx, stair_y1]])
            stair_poly  = None
            try:
                cs = fp_interior_mf.intersection(raw_stair)
                if hasattr(cs, 'geoms'):
                    cs = max(cs.geoms, key=lambda g: g.area)
                if not cs.is_empty and hasattr(cs, 'exterior') and cs.area >= 0.5:
                    stair_poly = [[c[0], c[1]] for c in list(cs.exterior.coords)[:-1]]
            except Exception:
                pass
            if stair_poly:
                rooms.append(Room(id=f"stair_{lvl}", type="stair",
                                  polygon=stair_poly, level=lvl,
                                  area_sqft=round(stair_w_s * (maxy - miny) * 10.764, 1)))

            # Corridor (excluding stair slice)
            raw_corr = Polygon([[minx + stair_w_s, corr_y0], [maxx, corr_y0],
                                 [maxx, corr_y1], [minx + stair_w_s, corr_y1]])
            try:
                cc = fp_interior_mf.intersection(raw_corr)
                if hasattr(cc, 'geoms'):
                    cc = max(cc.geoms, key=lambda g: g.area)
                corr_poly = [[c[0], c[1]] for c in list(cc.exterior.coords)[:-1]] if (
                    not cc.is_empty and hasattr(cc, 'exterior')) else list(raw_corr.exterior.coords[:-1])
            except Exception:
                corr_poly = [[c[0], c[1]] for c in raw_corr.exterior.coords[:-1]]
            rooms.append(Room(id=f"corridor_{lvl}", type="corridor",
                               polygon=corr_poly, level=lvl,
                               area_sqft=round((w - stair_w_s) * CORRIDOR_WIDTH_M * 10.764, 1)))
            corr_b = Polygon(corr_poly).bounds
            all_rects.append((corr_b[0], corr_b[1], corr_b[2], corr_b[3]))

            # Units on FRONT zone (miny → corr_y0) and BACK zone (corr_y1 → maxy)
            unit_idx  = 0
            usable_x0 = minx + stair_w_s
            usable_x1 = maxx
            for zone_y0, zone_y1 in [(miny, corr_y0), (corr_y1, maxy)]:
                zone_d = zone_y1 - zone_y0
                if zone_d < 3.0:
                    continue
                cursor_x = usable_x0
                for unit_type, count in unit_mix.items():
                    _bt = UNIT_TEMPLATES.get(unit_type) or UNIT_TEMPLATES.get("3br") or UNIT_TEMPLATES["1br"]
                    _at = ai_templates.get(unit_type) or {}
                    tmpl = {**_bt, **{k: v for k, v in _at.items() if k in ("w", "d", "rows")}}
                    for _ in range(count):
                        uw = min(float(tmpl["w"]), usable_x1 - cursor_x)
                        if uw < 3.0 or cursor_x >= usable_x1:
                            break
                        uid = f"unit_{unit_type}_{lvl}_{unit_idx}"
                        raw_unit = Polygon([[cursor_x, zone_y0], [cursor_x + uw, zone_y0],
                                            [cursor_x + uw, zone_y1], [cursor_x, zone_y1]])
                        try:
                            clipped = fp_interior_mf.intersection(raw_unit)
                            if hasattr(clipped, 'geoms'):
                                clipped = max(clipped.geoms, key=lambda g: g.area)
                            if clipped.is_empty or not hasattr(clipped, 'exterior') or clipped.area < 6.0:
                                cursor_x += uw; unit_idx += 1; continue
                            unit_poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                            cb = clipped.bounds
                        except Exception:
                            cursor_x += uw; unit_idx += 1; continue
                        rooms.append(Room(id=uid, type="unit", unit_id=uid,
                                          polygon=unit_poly, level=lvl,
                                          area_sqft=round(clipped.area * 10.764, 1)))
                        sub_rooms = self._place_unit_rooms(
                            uid, cb[0], cb[1], cb[2]-cb[0], cb[3]-cb[1],
                            tmpl, lvl, fp_interior=fp_interior_mf,
                        )
                        rooms.extend(sub_rooms)
                        all_rects.append((cb[0], cb[1], cb[2], cb[3]))
                        all_rects.extend(self._unit_subrects(cb, tmpl))
                        cursor_x += uw
                        unit_idx += 1

        self._emit_interior_walls(all_rects, footprint, fp_interior_mf, level, walls)
        walls.extend(self._place_exterior_walls(footprint, level))
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
        fp_interior = footprint.buffer(-FP_INSET, join_style=2)

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
        fp_interior = footprint.buffer(-FP_INSET, join_style=2)

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
        back_row_program: Optional[List[Dict]] = None,
    ) -> Tuple[List[Room], List[Wall]]:
        """Ground floor with front-facing attached garage + entry zone behind it."""
        rooms: List[Room] = []
        walls: List[Wall] = []
        lvl = level.index
        minx, miny = bounds[0], bounds[1]
        fp_interior = footprint.buffer(-FP_INSET, join_style=2)

        # Garage sized like a real garage, not as a fraction of the whole plate.
        # A full-width 40%-depth band on a 22 m plate came out at 1,628 sqft —
        # three times the largest garage in the reference plans (median 520 sqft).
        # Capped at roughly a 3-car bay; whatever front area is left over goes to
        # the living program alongside it.
        garage_d = min(d * 0.40, 6.8)     # ~22 ft deep, enough for a car
        garage_w = min(w, 9.8)            # ~32 ft, three bays
        entry_d  = d - garage_d

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
        _clip_room(minx, miny, minx + garage_w, miny + garage_d, "garage")

        entry_y0 = miny + garage_d
        entry_y1 = miny + d

        # Behind the garage, lay out the real ground-floor program rather than a
        # bare foyer + utility. This branch used to emit exactly three rooms and
        # return, so every archetype with garage_at_grade — high_end_custom
        # among them — lost its whole main floor: no great room, no kitchen, no
        # dining, despite its own floor_program listing them.
        back_rooms: List[Room] = []
        if back_row_program and (entry_y1 - entry_y0) > 2.5:
            garage_rect = Polygon([
                [minx, miny], [minx + garage_w, miny],
                [minx + garage_w, miny + garage_d], [minx, miny + garage_d],
            ])
            try:
                # Everything the garage doesn't occupy — an L when the garage is
                # narrower than the plate, so the front strip beside it is
                # programmed rather than left as dead area.
                back_fp = footprint.difference(garage_rect)
                if hasattr(back_fp, "geoms"):
                    back_fp = max(back_fp.geoms, key=lambda g: g.area)
                if not back_fp.is_empty and back_fp.area > 4.0:
                    _bb = back_fp.bounds
                    back_rooms, back_walls = self._layout_sfr_floor_from_rows(
                        back_fp, _bb, _bb[2] - _bb[0], _bb[3] - _bb[1],
                        level, all_levels or [level], back_row_program,
                    )
                    rooms.extend(back_rooms)
                    walls.extend(w_ for w_ in back_walls if not w_.is_exterior)
            except Exception:
                back_rooms = []

        if not back_rooms:
            # Fallback: the original entry + utility split.
            entry_w = w * 0.55
            utility_w = w - entry_w
            _clip_room(minx,           entry_y0, minx + entry_w,   entry_y1, "foyer")
            _clip_room(minx + entry_w, entry_y0, minx + entry_w + utility_w, entry_y1, "utility")

        # Collect room rects for wall generation
        room_rects: List[Tuple[float, float, float, float]] = [
            (minx, miny, minx + garage_w, miny + garage_d),
        ]
        if not back_rooms:
            _entry_w = w * 0.55
            room_rects += [
                (minx, entry_y0, minx + _entry_w, entry_y1),
                (minx + _entry_w, entry_y0, minx + w, entry_y1),
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
        # Row programs are defined up to 7BR; larger houses reuse the 7BR
        # program and gain their extra area through the plate, not more rows.
        br = max(1, min(7, bedrooms))

        # ── Archetype overrides ───────────────────────────────────────────────
        archetype_id = (archetype or {}).get('id', '')
        if archetype_id == 'victorian_narrow_lot' and lvl == 0:
            return self._layout_victorian_ground(footprint, bounds, w, d, level, all_levels)
        # Hillside street level: richer 4-room ground (garage+entry+mudroom+utility)
        if archetype_id == 'hillside_stepped' and lvl == 0:
            return self._layout_hillside_ground(footprint, bounds, w, d, level, all_levels)
        # Archetypes with ground-level garage (Urban Infill, Production Tract, etc.)
        _garage_at_grade = (archetype or {}).get('massing_hints', {}).get('garage_at_grade', False)
        if _garage_at_grade and lvl == 0:
            # Hand the ground-floor program through so the space behind the
            # garage gets the real living plan instead of a foyer and a closet.
            if footprint.area > MANSION_THRESHOLD_M2:
                _back = SFR_GROUND_MANSION
            elif footprint.area > LARGE_HOUSE_THRESHOLD_M2:
                _back = SFR_GROUND_LARGE.get(br, SFR_PROGRAMS[br])
            else:
                _back = SFR_GROUND_ROWS[br]
            _tot = sum(r["row_frac_d"] for r in _back) or 1.0
            _back = [{**r, "row_frac_d": r["row_frac_d"] / _tot} for r in _back]
            return self._layout_garage_ground(
                footprint, bounds, w, d, level, archetype_id, all_levels,
                back_row_program=_back,
            )

        floor_area_m2 = footprint.area
        use_large = floor_area_m2 > LARGE_HOUSE_THRESHOLD_M2
        # Estate plate: use the mansion programs, whose room proportions come
        # from a measured reference plan rather than from near-uniform fracs.
        use_mansion = floor_area_m2 > MANSION_THRESHOLD_M2

        _is_victorian = archetype_id == 'victorian_narrow_lot'

        # Select which row program to use for this floor.
        # Core rule: bedrooms can appear on ANY upper floor — the strict
        # "ground=public, upper=private" split is only enforced for large houses
        # where the expanded programs already mix things correctly.
        if n_floors == 1:
            if use_mansion:
                combined = SFR_GROUND_MANSION + SFR_UPPER_MANSION
                total = sum(r["row_frac_d"] for r in combined)
                row_program = [{**r, "row_frac_d": r["row_frac_d"] / total} for r in combined]
            elif use_large:
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
            if use_mansion:
                row_program = SFR_GROUND_MANSION
            elif use_large:
                row_program = SFR_GROUND_LARGE.get(br, SFR_PROGRAMS[br])
            else:
                row_program = SFR_GROUND_ROWS[br]
            total = sum(r["row_frac_d"] for r in row_program)
            row_program = [{**r, "row_frac_d": r["row_frac_d"] / total} for r in row_program]

        else:
            # Upper floors for ALL archetypes and all story counts:
            # - Large floor plate → SFR_UPPER_LARGE (bedrooms + bonus/loft/media)
            # - Otherwise        → SFR_UPPER_ROWS (landing + bedroom rows)
            #
            # Small 2-story and Victorian plans used to take the FULL
            # SFR_PROGRAMS here, on the theory that bedrooms and living space
            # should share the floor. But SFR_PROGRAMS rows 0-1 are literally
            # what SFR_GROUND_ROWS emits, so the upper floor came out as an
            # exact copy of the ground floor — same room types, same widths,
            # only the row depths renormalised. That is the single reason
            # "floor 2 looks identical to floor 1".
            if use_mansion:
                row_program = SFR_UPPER_MANSION
            elif use_large:
                row_program = SFR_UPPER_LARGE.get(br, SFR_UPPER_ROWS[br])
            else:
                row_program = SFR_UPPER_ROWS[br]
            total = sum(r["row_frac_d"] for r in row_program)
            row_program = [{**r, "row_frac_d": r["row_frac_d"] / total} for r in row_program]

        # One canonical interior boundary — everything must have its center inside this.
        fp_interior = footprint.buffer(-FP_INSET, join_style=2)

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
                # Same fixed-room-count problem as the AI row path: split cells
                # that exceed their type's ceiling rather than letting a big
                # plate inflate every room.
                for (sx0, sy0, sx1, sy1), stype in subdivide_cell(
                    rx0, row_y0, rx1, row_y1, rdef["type"]
                ):
                    sub_area = (sx1 - sx0) * (sy1 - sy0)
                    cell_shape = Polygon([
                        [sx0, sy0], [sx1, sy0], [sx1, sy1], [sx0, sy1],
                    ])
                    try:
                        clipped = fp_interior.intersection(cell_shape)
                        if hasattr(clipped, 'geoms'):
                            clipped = max(clipped.geoms, key=lambda g: g.area)
                        # Accept if clipped area >= 25% of the cell so partial
                        # rooms near L/U cut corners still get placed.
                        if (clipped.is_empty or not hasattr(clipped, 'exterior')
                                or clipped.area < max(0.5, sub_area * 0.25)):
                            continue
                        poly = [[c[0], c[1]] for c in list(clipped.exterior.coords)[:-1]]
                        cb = clipped.bounds
                        area = clipped.area * 10.764
                    except Exception:
                        if not fp_interior.contains(
                            Point((sx0 + sx1) / 2, (sy0 + sy1) / 2)
                        ):
                            continue
                        poly = [[sx0, sy0], [sx1, sy0], [sx1, sy1], [sx0, sy1]]
                        cb = (sx0, sy0, sx1, sy1)
                        area = sub_area * 10.764

                    rooms.append(Room(
                        id=f"sfr_{stype}_{lvl}_{uuid.uuid4().hex[:5]}",
                        type=stype,
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
