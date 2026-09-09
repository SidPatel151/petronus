"""
constraints.py — Single source of truth for all platform rules and limits.

Every hard cap, zoning rule, and code requirement lives here.
Import LIMITS and RULES anywhere instead of repeating magic numbers.
Claude receives a compact text rendering of these so it knows the rules.
"""
from dataclasses import dataclass, field
from typing import Dict, List


# ── Platform hard caps ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PlatformLimits:
    # Platform ceiling for a detached house. 5,500 was a middle-market number
    # and it clamped the whole high-end range flat: a 6BR and a 7BR both landed
    # on exactly 5,500, so "bigger house" stopped meaning anything. Custom homes
    # of 8-15k sqft are ordinary in this segment.
    sfr_max_sqft:      int   = 25_000
    # Per-archetype ceiling for genuinely large custom work (see
    # ARCHETYPE_RULES["high_end_custom"]). Kept separate so the tract/infill
    # archetypes stay at a realistic middle-market size.
    #
    # Sized off the reference plans, not a guess: High-End-Custom/R.jpg is a
    # single-storey mansion whose interior alone sums to ~5,100 sqft — more
    # than the entire old 5,500 platform cap — plus two 646 sqft garages and a
    # 416 sqft loggia, on a 151 x 120 ft footprint. Two storeys of that is
    # 10-12k, and estate work runs past 20k.
    custom_max_sqft:   int   = 25_000
    tract_max_sqft:    int   = 6_500   # production/infill/townhome ceiling
    mf_max_sqft:       int   = 50_000  # multi-family generous cap
    sfr_max_bedrooms:  int   = 10      # large custom homes run past 7
    max_stories:       int   = 3       # wizard UI max
    min_bedroom_w_m:   float = 2.7     # IRC R304.1 minimum habitable room width
    min_bathroom_w_m:  float = 1.5
    min_kitchen_w_m:   float = 2.4
    min_living_w_m:    float = 3.0
    min_corridor_w_m:  float = 1.1     # IRC R311.6
    floor_to_floor_ft: float = 10.0   # default SFR floor-to-floor

LIMITS = PlatformLimits()


# ── Archetype-specific rules ──────────────────────────────────────────────────

@dataclass(frozen=True)
class ArchetypeRule:
    display_name:      str
    max_sqft:          int
    max_bedrooms:      int
    max_stories:       int
    min_slope_pct:     float = 0.0    # trigger slope (0 = style-driven)
    min_elevation_m:   float = 0.0    # trigger elevation
    requires_garage:   bool  = False
    wui_zone:          bool  = False  # Wildland-Urban Interface
    note:              str   = ""


ARCHETYPE_RULES: Dict[str, ArchetypeRule] = {
    "hillside_stepped": ArchetypeRule(
        display_name="Hillside Stepped Home",
        max_sqft=LIMITS.sfr_max_sqft,
        max_bedrooms=LIMITS.sfr_max_bedrooms,
        max_stories=LIMITS.max_stories,
        min_slope_pct=8.0,
        min_elevation_m=100.0,
        requires_garage=True,
        wui_zone=True,
        note="Split-level stepped massing following terrain. Each level has its own deck and roofline. "
             "Ejector pump required for bathrooms below sewer main. Multi-zone HVAC mandatory.",
    ),
    "victorian_narrow_lot": ArchetypeRule(
        display_name="Victorian Narrow Lot",
        max_sqft=LIMITS.sfr_max_sqft,
        max_bedrooms=LIMITS.sfr_max_bedrooms,
        max_stories=LIMITS.max_stories,
        note="25 ft wide lot, 2-3 stories, pitched gabled roof, front porch.",
    ),
    "mid_century_modern": ArchetypeRule(
        display_name="Mid-Century Modern",
        max_sqft=LIMITS.sfr_max_sqft,
        max_bedrooms=LIMITS.sfr_max_bedrooms,
        max_stories=2,
        note="Wide shallow plate, low-slope roof, clerestory windows, indoor-outdoor flow.",
    ),
    "high_density_townhome": ArchetypeRule(
        display_name="High-Density Townhome",
        max_sqft=LIMITS.mf_max_sqft,
        max_bedrooms=4,
        max_stories=LIMITS.max_stories,
        note="Attached units, 3+ stories, shared party walls.",
    ),
    "high_end_custom": ArchetypeRule(
        display_name="High-End Custom",
        max_sqft=LIMITS.custom_max_sqft,
        max_bedrooms=LIMITS.sfr_max_bedrooms,
        max_stories=LIMITS.max_stories,
        note="Complex L/U/stepped massing, quality priority, premium materials. "
             "Large plate with a wide spread of room sizes — great room and "
             "primary suite are multiples of a secondary bedroom.",
    ),
    "urban_infill_zero_lot": ArchetypeRule(
        display_name="Urban Infill / Zero-Lot",
        max_sqft=LIMITS.sfr_max_sqft,
        max_bedrooms=LIMITS.sfr_max_bedrooms,
        max_stories=LIMITS.max_stories,
        note="Narrow modern infill, 25 ft wide, contemporary box, zero side setback.",
    ),
    "production_tract": ArchetypeRule(
        display_name="Production Tract",
        max_sqft=LIMITS.sfr_max_sqft,
        max_bedrooms=LIMITS.sfr_max_bedrooms,
        max_stories=2,
        requires_garage=True,
        note="Standard ranch/tract, near-square footprint, wood frame, attached 2-car garage.",
    ),
    "prefab_modern": ArchetypeRule(
        display_name="Prefab / Modular",
        max_sqft=LIMITS.sfr_max_sqft,
        max_bedrooms=LIMITS.sfr_max_bedrooms,
        max_stories=2,
        note="Modular box, 2 modules wide, flat or low-slope roof, factory-built.",
    ),
}


# ── California Code references (compact version for Claude prompts) ───────────

CA_CODE_COMPACT: List[str] = [
    "CBC 2022 + CA Title 24 energy compliance",
    "Fully electric: heat-pump HVAC + HPWH + induction cooktop",
    "Solar PV ready + battery pre-wire (NEC 705)",
    "EV charging: 1 dedicated 240 V/40 A circuit per garage space (CA T-24)",
    "Seismic: ASCE 7-22 SDC D+ → special ductile detailing, no soft stories",
    "WUI zone: Class A roofing, ember-resistant vents, 1-hour exterior walls",
]


# ── Compact text rendering for Claude prompts ─────────────────────────────────

def limits_for_prompt() -> str:
    """Return a compact multi-line string Claude can read in a system prompt."""
    rules = "\n".join(
        f"  {aid}: {r.max_sqft:,} sqft max, {r.max_bedrooms} BR max, {r.max_stories} stories"
        + (f", WUI" if r.wui_zone else "")
        + (f" — {r.note[:80]}" if r.note else "")
        for aid, r in ARCHETYPE_RULES.items()
    )
    return f"""PLATFORM LIMITS (hard constraints — never exceed):
  SFR max: {LIMITS.sfr_max_sqft:,} sqft | Max bedrooms: {LIMITS.sfr_max_bedrooms}
  Max stories: {LIMITS.max_stories}
  Min room widths: bedroom {LIMITS.min_bedroom_w_m}m, bath {LIMITS.min_bathroom_w_m}m, kitchen {LIMITS.min_kitchen_w_m}m

ARCHETYPE RULES:
{rules}

CA CODE (non-negotiable):
{chr(10).join('  ' + c for c in CA_CODE_COMPACT)}"""
