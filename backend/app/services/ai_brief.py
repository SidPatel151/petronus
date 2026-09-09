"""
AIBriefService — Claude decides every facade render parameter.
No lookup tables. The archetype tells Claude what direction to go;
Claude reads the blueprints and returns concrete numbers the renderer uses directly.
"""
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

_INDEX_PATH = Path(__file__).parent.parent / "data" / "blueprint_index.json"
_INDEX_CACHE: Optional[list] = None

CALIFORNIA_CODE_REFERENCES = [
    "CBC 2022 (California Building Code, 26th edition)",
    "CRC 2022 (California Residential Code)",
    "CALGreen 2022 (CAC Title 24 Part 11)",
    "Title 24 Part 6 2022 Energy Code",
    "ASCE 7-22 (loads & seismic)",
    "CA Fire Code 2022",
]


def _load_index() -> list:
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        _INDEX_CACHE = json.loads(_INDEX_PATH.read_text()) if _INDEX_PATH.exists() else []
    return _INDEX_CACHE


def _find_blueprints(archetype_id: str, bedrooms: int, sqft: float, n: int = 3) -> list:
    idx = _load_index()
    if not idx:
        return []
    def score(bp):
        s = 0.0
        if bp.get("archetype") == archetype_id: s += 4
        if bp.get("image_type") == "floor_plan": s += 2
        br = bp.get("bedrooms") or 0
        if br == bedrooms: s += 2
        elif abs(br - bedrooms) <= 1: s += 1
        bsqft = bp.get("total_sqft") or 0
        if bsqft and sqft:
            s += min(bsqft, sqft) / max(bsqft, sqft) * 2
        s += bp.get("confidence", 0)
        return s
    return sorted(idx, key=score, reverse=True)[:n]


def _bp_summary(bp: dict) -> str:
    sqft = bp.get("total_sqft", "?")
    br = bp.get("bedrooms", "?")
    style = bp.get("style", "")
    mat = bp.get("facade_material", "")
    rooms = bp.get("rooms", [])
    room_str = ", ".join(r["type"] for r in rooms[:8]) if rooms else "unknown"
    return f"  [{br}BR {sqft}sqft {style} {mat}] rooms: {room_str}"


def _get_api_key() -> str:
    try:
        from app.core.config import settings
        return settings.ANTHROPIC_API_KEY
    except Exception:
        import os
        return os.environ.get("ANTHROPIC_API_KEY", "")


async def get_design_brief(
    spec_dict: Dict[str, Any],
    site_ctx_dict: Dict[str, Any],
    neighbor_analysis: Dict[str, Any],
    archetype_id: str = "",
    archetype_display_name: str = "",
) -> Dict[str, Any]:
    api_key = _get_api_key()
    if not api_key:
        return _default_brief(spec_dict, neighbor_analysis)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        terrain      = site_ctx_dict.get("terrain", {}) or {}
        slope        = terrain.get("slope_pct", 0)
        avg_elev_m   = terrain.get("avg_elevation_m", 0)
        municipality = site_ctx_dict.get("municipality", "") or terrain.get("municipality", "")
        flood        = site_ctx_dict.get("flood_zone", "X")
        seismic      = site_ctx_dict.get("seismic_category", "D")
        parcel_sqft  = site_ctx_dict.get("area_sqft", 5000)
        weather      = site_ctx_dict.get("weather") or {}
        climate_zone = weather.get("climate_zone", "") if weather else ""
        temp_f       = weather.get("temp_f") if weather else None

        nav          = neighbor_analysis
        n_count      = nav.get("count", 0)
        avg_h        = nav.get("avg_height_m", 6)
        avg_w        = nav.get("avg_width_m", 12)
        avg_d        = nav.get("avg_depth_m", 14)
        dom_mat      = nav.get("dominant_material", "stucco")

        stories  = spec_dict.get("stories", 2)
        bedrooms = spec_dict.get("bedrooms", 3)
        sqft     = spec_dict.get("sqft") or spec_dict.get("target_gross_area_sqft", 2000)
        # Hard cap: platform never allows SFR above 5,500 sqft
        sqft     = min(float(sqft), 5500.0)
        style    = spec_dict.get("style", "")
        priority = spec_dict.get("priority", "cost")
        struct   = spec_dict.get("structural_system", "wood")
        # Max footprint per floor so width_m × depth_m stays within the sqft cap
        _max_fp_m2 = (sqft / max(stories, 1)) / 10.764

        if slope < 4:
            terrain_desc = "flat to gentle"
        elif slope < 8:
            terrain_desc = f"moderate slope ({slope:.1f}%)"
        else:
            terrain_desc = f"steep slope ({slope:.1f}%)"

        blueprints = _find_blueprints(archetype_id, bedrooms, sqft, n=3)
        bp_block = "\n".join(_bp_summary(b) for b in blueprints) or "  (no matching blueprints)"

        code_reference_list = "\n".join(f"- {c}" for c in CALIFORNIA_CODE_REFERENCES)
        prompt = f"""You are a California residential conceptual-design assistant. Given this site and its neighbors, output a concise JSON massing brief for a new residential building. Do not claim that the result is engineered, code-verified, permit-ready, or approved.

CURRENT PRELIMINARY CODE CONTEXT (applicability and local amendments require licensed/AHJ review):
{code_reference_list}

STRUCTURAL & SEISMIC SCREENING INPUTS:
- Unverified preliminary Seismic Design Category (SDC): {site_ctx_dict.get('seismic_category', 'D')}
- Preserve a continuous conceptual lateral-load path and avoid obvious soft/weak-story configurations
- Flag geotechnical, liquefaction, anchorage, bracing, diaphragm, and equipment-support design for project-specific engineering
- Do not invent member sizes, foundation capacity, or prescriptive seismic requirements

SITE:
- Location: {municipality or "unknown"} | {parcel_sqft:.0f} sqft lot
- Elevation: {avg_elev_m:.0f}m | Slope: {slope:.1f}% | {terrain_desc}
- Climate: {climate_zone}{f" ({temp_f:.0f}°F)" if temp_f else ""} | Flood: {flood} | SDC: {seismic}

NEIGHBORS ({n_count} nearby):
- Avg height: {avg_h:.1f}m | Footprint: {avg_w:.1f}m × {avg_d:.1f}m | Material: {dom_mat}

PROJECT: {stories} stories | {bedrooms} BR | {sqft:.0f} sqft | priority={priority} | structure={struct}
HARD SQFT CAP: {sqft:.0f} sqft total across all floors — NEVER return width_m × depth_m × {stories} stories above this.
Each floor footprint must be ≤ {_max_fp_m2:.1f} m², so width_m × depth_m ≤ {_max_fp_m2:.1f}

MATCHING BLUEPRINTS FROM OUR DATASET (use these proportions as inspiration, not copy):
{bp_block}

Return ONLY valid JSON. Every field is required — these values drive the 3D renderer directly:
{{
  "shape": "rectangle|narrow_lot|wide_shallow|l_shape|sculpted",
  "width_m": <float — footprint width, must satisfy width_m × depth_m ≤ {_max_fp_m2:.1f}>,
  "depth_m": <float — footprint depth, must satisfy width_m × depth_m ≤ {_max_fp_m2:.1f}>,
  "facade_material": "stucco|wood|brick|concrete|metal|stone|fiber_cement",
  "trim_color": "<hex — accent/trim color contrasting the facade>",
  "band_h_frac": <float 0.0-0.35 — floor band height fraction; 0=none>,
  "face_offset": <float 0.05-0.20 — facade relief/depth>,
  "window_ratio": <float 0.20-0.60 — window area fraction>,
  "win_h_frac": <float 0.30-0.80 — window height as fraction of floor height>,
  "win_w_cap_m": <float 0.8-3.5 — max window width meters>,
  "balcony_depth_m": <float 0.0-2.0 — balcony projection; 0=none>,
  "balcony_every_n_floors": <int 1-3; ignored if balcony_depth_m=0>,
  "porch_depth_m": <float 0.0-3.0 — entry porch depth; 0=none>,
  "horizontal_bands": <bool>,
  "roof_type": "flat|gabled|hipped|shed",
  "roof_pitch_12": <int 0-12>,
  "ground_floor_height_boost_m": <float 0.0-1.0>,
  "rationale": "<one sentence explaining key design decisions>"
}}"""

        msg = await asyncio.to_thread(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip any accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return _normalize_brief(json.loads(raw), spec_dict, neighbor_analysis)

    except Exception as e:
        fallback = _default_brief(spec_dict, neighbor_analysis)
        fallback["source"] = f"fallback ({str(e)[:80]})"
        return fallback


def _default_brief(spec_dict: Dict, nav: Dict) -> Dict[str, Any]:
    """Rule-based fallback when Claude is unavailable."""
    mat = nav.get("dominant_material", "stucco")
    shape = nav.get("dominant_shape", "rectangle")
    if shape not in {"rectangle", "l_shape", "bar", "u_shape", "stepped"}:
        shape = "rectangle"
    if mat not in {"stucco", "brick", "concrete", "wood", "steel"}:
        mat = "stucco"
    avg_w = nav.get("avg_width_m", 12)
    avg_d = nav.get("avg_depth_m", 14)
    return {
        "shape": "rectangle",
        "width_m": max(8, avg_w * 0.95),
        "depth_m": max(8, avg_d * 0.95),
        "facade_material": mat,
        "trim_color": "#4a4a4a",
        "band_h_frac": 0.14,
        "face_offset": 0.09,
        "window_ratio": 0.35,
        "win_h_frac": 0.50,
        "win_w_cap_m": 1.8,
        "balcony_depth_m": 0.0,
        "balcony_every_n_floors": 0,
        "porch_depth_m": 0.0,
        "horizontal_bands": True,
        "roof_type": "gabled",
        "roof_pitch_12": 5,
        "ground_floor_height_boost_m": 0.3,
        "penthouse_setback": False,
        "rationale": "Fallback defaults — Claude unavailable",
        "source": "fallback",
    }


def _normalize_brief(brief: Any, spec_dict: Dict, nav: Dict) -> Dict[str, Any]:
    """Constrain provider output so malformed AI values cannot break generation."""
    if not isinstance(brief, dict):
        raise ValueError("Design brief response must be a JSON object")
    default = _default_brief(spec_dict, nav)

    def choice(key: str, allowed: set[str]) -> str:
        value = str(brief.get(key, default[key])).lower()
        return value if value in allowed else default[key]

    def number(key: str, low: float, high: float) -> float:
        try:
            value = float(brief.get(key, default[key]))
        except (TypeError, ValueError):
            value = float(default[key])
        return max(low, min(high, value))

    def boolean(key: str) -> bool:
        value = brief.get(key, default[key])
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return bool(value)

    return {
        "shape": choice("shape", {"rectangle", "l_shape", "bar", "u_shape", "stepped"}),
        "width_m": number("width_m", 4.0, 80.0),
        "depth_m": number("depth_m", 4.0, 80.0),
        "window_ratio": number("window_ratio", 0.10, 0.70),
        "balcony_depth_m": number("balcony_depth_m", 0.0, 3.0),
        "balcony_every_n_floors": int(number("balcony_every_n_floors", 0, 10)),
        "facade_material": choice(
            "facade_material", {"stucco", "brick", "concrete", "wood", "steel"}
        ),
        "horizontal_bands": boolean("horizontal_bands"),
        "roof_type": choice("roof_type", {"flat", "parapet", "gabled", "shed"}),
        "ground_floor_height_boost_m": number("ground_floor_height_boost_m", 0.0, 1.5),
        "penthouse_setback": boolean("penthouse_setback"),
        "rationale": str(brief.get("rationale", default["rationale"]))[:300],
        "source": "claude",
    }
