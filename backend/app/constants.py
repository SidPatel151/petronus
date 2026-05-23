"""
constants.py
All project-wide enums and fixed lookup tables.
Import from here instead of from schemas to avoid circular imports.
"""
from enum import Enum


# ── Structural ──────────────────────────────────────────────────────────────

class StructuralSystem(str, Enum):
    wood     = "wood"
    steel    = "steel"
    concrete = "concrete"


# ── HVAC ────────────────────────────────────────────────────────────────────

class HVACPreference(str, Enum):
    mini_split = "mini_split"
    rooftop    = "rooftop"


# ── Priority ────────────────────────────────────────────────────────────────

class PriorityType(str, Enum):
    cost     = "cost"
    time     = "time"      # fast construction (canonical)
    space    = "space"     # maximize living area
    light    = "light"     # natural daylight
    energy   = "energy"    # energy performance
    # legacy aliases — kept for backward compat with existing API clients
    speed    = "speed"
    daylight = "daylight"
    budget   = "budget"    # alias for cost


# ── Design style ─────────────────────────────────────────────────────────────

class DesignStyle(str, Enum):
    classic_gabled = "classic_gabled"   # pitched roofs, traditional forms
    modern_linear  = "modern_linear"    # flat/low-slope, clean horizontal lines
    solid_sculpted = "solid_sculpted"   # monolithic, textured mass


# ── Parking ─────────────────────────────────────────────────────────────────

class ParkingStrategy(str, Enum):
    ignore  = "ignore"
    surface = "surface"
    podium  = "podium"


# ── Building use ─────────────────────────────────────────────────────────────

class BuildingUse(str, Enum):
    single_family = "single_family"
    multi_family  = "multi_family"
    adu           = "adu"


# ── House archetypes ─────────────────────────────────────────────────────────
# Real architectural styles. Grouped by priority affinity.
# Source: McAlester "A Field Guide to American Houses", NAR, US Census, CA HCD.

class HouseArchetype(str, Enum):
    # Cost / Speed optimised
    ranch       = "ranch"
    cape_cod    = "cape_cod"
    foursquare  = "foursquare"
    saltbox     = "saltbox"
    # Space optimised
    colonial    = "colonial"
    farmhouse   = "farmhouse"
    tudor       = "tudor"
    split_level = "split_level"
    # Light / Contemporary
    contemporary     = "contemporary"
    mid_century_mod  = "mid_century_modern"
    prairie          = "prairie"
    a_frame          = "a_frame"
    # Regional / Material-driven
    craftsman        = "craftsman"
    mediterranean    = "mediterranean"
    victorian        = "victorian"
    # Small / Special
    adu_compact      = "adu_compact"


# ── Priority → archetype affinity ────────────────────────────────────────────
# For each priority, the ordered list of archetypes to prefer (most → least).
PRIORITY_ARCHETYPES: dict[str, list[str]] = {
    "cost":    ["ranch", "cape_cod", "foursquare"],
    "time":    ["ranch", "saltbox", "foursquare"],
    "speed":   ["ranch", "saltbox", "foursquare"],   # alias
    "light":   ["contemporary", "mid_century_modern", "prairie"],
    "daylight":["contemporary", "mid_century_modern", "prairie"],  # alias
    "space":   ["colonial", "farmhouse", "victorian", "craftsman"],
    "energy":  ["contemporary", "victorian", "craftsman"],
}


# ── SFR sqft ranges by bedroom count ─────────────────────────────────────────
# Tuple: (min_sqft, max_sqft).
# Sources: NAR, US Census, CA HCD — ranges reflect CA middle-market construction.
SFR_SQFT_RANGES: dict[int, tuple[int, int]] = {
    1: (500,   900),
    2: (800,  1300),
    3: (1200, 1900),
    4: (1800, 2800),
    5: (2500, 4200),
}

# ADU cap per CA law (HCD, post-2020 AB-68 / AB-881)
ADU_MAX_SQFT = 1200

# Priority → fractional position within sqft range (0.0 = min, 1.0 = max)
PRIORITY_SQFT_POSITION: dict[str, float] = {
    "cost": 0.0, "time": 0.15, "speed": 0.15,
    "light": 0.5, "daylight": 0.5, "space": 1.0,
}


def sfr_target_sqft(bedrooms: int, priority: str) -> int:
    """Return target sqft for SFR/ADU based on bedroom count and priority."""
    lo, hi = SFR_SQFT_RANGES.get(max(1, min(5, bedrooms)), (1200, 1900))
    t = PRIORITY_SQFT_POSITION.get(priority, 0.5)
    return round(lo + (hi - lo) * t)


# ── Facade material → hex color ───────────────────────────────────────────────

FACADE_COLORS: dict[str, str] = {
    "brick":    "#b5651d",
    "concrete": "#9ca3af",
    "glass":    "#bfdbfe",
    "wood":     "#a67c52",
    "stone":    "#b8a99a",
    "metal":    "#94a3b8",
    "stucco":   "#d6cbb8",
    "plaster":  "#e8dcc8",
}
