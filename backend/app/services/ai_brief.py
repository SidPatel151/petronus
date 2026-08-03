"""
AIBriefService
Calls Claude to generate a unique architectural design brief from site + neighbor context.
"""
import json
import asyncio
from typing import Dict, Any, List

from app.constants import CALIFORNIA_CODE_REFERENCES


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
) -> Dict[str, Any]:
    """
    Call Claude claude-sonnet-4-6 with site + neighbor context.
    Returns a structured design brief that drives massing + facade generation.
    Falls back to defaults if API key missing or call fails.
    """
    api_key = _get_api_key()
    if not api_key:
        return _default_brief(spec_dict, neighbor_analysis)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        parcel_sqft = site_ctx_dict.get("area_sqft", 5000)
        flood = site_ctx_dict.get("flood_zone", "X")
        seismic = site_ctx_dict.get("seismic_category", "D")
        terrain = site_ctx_dict.get("terrain", {})
        slope = terrain.get("slope_pct", 0)

        nav = neighbor_analysis
        avg_h = nav.get("avg_height_m", 6)
        avg_w = nav.get("avg_width_m", 12)
        avg_d = nav.get("avg_depth_m", 14)
        dominant_mat = nav.get("dominant_material", "stucco")
        dominant_shape = nav.get("dominant_shape", "rectangle")
        n_count = nav.get("count", 0)
        avg_stories = nav.get("avg_stories", 2)
        has_balconies = nav.get("has_balconies", False)

        stories = spec_dict.get("stories", 2)
        structural = spec_dict.get("structural_system", "wood")
        priority = spec_dict.get("priority", "cost")
        units = spec_dict.get("unit_count") or "unspecified"

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
- Parcel: {parcel_sqft:.0f} sqft
- Flood zone: {flood}
- Seismic: SDC {seismic}
- Terrain slope: {slope:.1f}%

NEIGHBORS ({n_count} buildings analyzed):
- Average height: {avg_h:.1f}m ({avg_stories:.1f} stories)
- Average footprint: {avg_w:.1f}m wide × {avg_d:.1f}m deep
- Dominant material: {dominant_mat}
- Dominant shape: {dominant_shape}
- Balconies common: {has_balconies}

PROJECT SPEC:
- Stories: {stories}
- Structural: {structural}
- Units: {units}
- Priority: {priority}

Respond with ONLY valid JSON, no markdown, no explanation:
{{
  "shape": "rectangle|l_shape|bar|u_shape|stepped",
  "width_m": <float, match neighbor scale>,
  "depth_m": <float, match neighbor scale>,
  "window_ratio": <float 0.25-0.55, match neighbor density>,
  "balcony_depth_m": <float 0.0-1.5>,
  "balcony_every_n_floors": <int 1-3, 0=none>,
  "facade_material": "stucco|brick|concrete|wood|steel",
  "horizontal_bands": <bool>,
  "roof_type": "flat|parapet|gabled|shed",
  "ground_floor_height_boost_m": <float 0.0-1.0>,
  "penthouse_setback": <bool>,
  "rationale": "<one sentence>"
}}"""

        msg = await asyncio.to_thread(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
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
        fallback["source"] = f"fallback ({str(e)[:60]})"
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
    has_bal = nav.get("has_balconies", False)
    return {
        "shape": shape,
        "width_m": max(8, avg_w * 0.95),
        "depth_m": max(8, avg_d * 0.95),
        "window_ratio": 0.35,
        "balcony_depth_m": 1.0 if has_bal else 0.0,
        "balcony_every_n_floors": 1 if has_bal else 0,
        "facade_material": mat,
        "horizontal_bands": True,
        "roof_type": "flat",
        "ground_floor_height_boost_m": 0.3,
        "penthouse_setback": spec_dict.get("stories", 2) >= 3,
        "rationale": "Rule-based default from neighbor analysis",
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
