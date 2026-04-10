"""
material_scorer.py
Scores and selects materials from the materials database based on
the user's chosen priority goal and design style.

Weighting: 50% goal score + 50% style score.
"""
from typing import Optional
from app.data.materials_db import MATERIALS, SLOT_TO_OVERRIDE_KEY

# Map PriorityType values → goal key in materials_db
_PRIORITY_TO_GOAL: dict[str, str] = {
    "cost":    "budget",
    "budget":  "budget",
    "time":    "speed",
    "speed":   "speed",
    "space":   "space",
    "light":   "light",
    "daylight":"light",
    "energy":  "energy",
}

# Map DesignStyle values → style key in materials_db
_STYLE_TO_KEY: dict[str, str] = {
    "classic_gabled":  "classic_gabled",
    "modern_linear":   "modern_linear",
    "solid_sculpted":  "solid_sculpted",
}

_DEFAULT_STYLE = "modern_linear"
_DEFAULT_GOAL  = "budget"


def _goal_key(priority: str) -> str:
    return _PRIORITY_TO_GOAL.get(str(priority).lower(), _DEFAULT_GOAL)


def _style_key(style: Optional[str]) -> str:
    if style is None:
        return _DEFAULT_STYLE
    return _STYLE_TO_KEY.get(str(style).lower(), _DEFAULT_STYLE)


def score_material(material_id: str, priority: str, style: Optional[str] = None) -> float:
    """
    Return a 0-10 composite score for a material given a priority goal and design style.
    Weights: 50% goal score + 50% style score.
    Returns 0.0 if material_id not found.
    """
    mat = MATERIALS.get(material_id)
    if mat is None:
        return 0.0
    g = _goal_key(priority)
    s = _style_key(style)
    goal_score  = mat["goals"].get(g, 5)
    style_score = mat["styles"].get(s, 5)
    return round(0.5 * goal_score + 0.5 * style_score, 2)


def select_for_slot(slot: str, priority: str, style: Optional[str] = None) -> Optional[str]:
    """
    Return the material_id with the highest composite score for a given
    component slot (e.g. 'exterior_wall', 'roof_covering').
    Returns None if no materials cover this slot.
    """
    candidates = [
        (mid, score_material(mid, priority, style))
        for mid, mat in MATERIALS.items()
        if slot in mat.get("applicable_to", [])
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[1])[0]


def resolve_materials(priority: str, style: Optional[str] = None) -> dict[str, dict]:
    """
    For every component slot, pick the best-scoring material.
    Returns a dict: { slot -> {"material_id": ..., "score": ..., "facade_type": ...} }
    """
    from app.data.materials_db import COMPONENT_SLOTS
    result = {}
    for slot in COMPONENT_SLOTS:
        mid = select_for_slot(slot, priority, style)
        if mid:
            mat = MATERIALS[mid]
            result[slot] = {
                "material_id": mid,
                "name":        mat["name"],
                "facade_type": mat.get("facade_type"),
                "score":       score_material(mid, priority, style),
            }
    return result


def get_override_dict(
    priority: str,
    style: Optional[str] = None,
    user_overrides: Optional[dict] = None,
) -> dict[str, str]:
    """
    Build the `material_overrides` dict for ProjectSpec:
      { "walls": "wood", "roof": "metal", ... }

    1. Auto-resolve best material per slot from goal + style scores.
    2. Convert slot → override key (only slots that map to an override key).
    3. Apply user manual overrides on top (they win).
    """
    resolved = resolve_materials(priority, style)

    overrides: dict[str, str] = {}
    for slot, info in resolved.items():
        override_key = SLOT_TO_OVERRIDE_KEY.get(slot)
        if override_key and info.get("facade_type"):
            overrides[override_key] = info["facade_type"]

    # User-provided overrides win
    if user_overrides:
        overrides.update(user_overrides)

    return overrides
