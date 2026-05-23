"""
archetype_loader.py
Detects which building archetype matches the user's spec choices and loads
its constraint profile from data/archetypes/*.json.

No new generator — constraints are injected into existing generator inputs.
"""
import json
import os
from typing import Optional, Dict, Any

_ARCHETYPE_DIR = os.path.join(os.path.dirname(__file__), "../data/archetypes")


def detect_archetype(spec) -> Optional[str]:
    """
    Infer archetype ID from spec parameters.
    Returns the JSON filename stem (without .json), or None for generic generation.

    Victorian narrow-lot triggers when the user picks:
      - Priority   → space
      - HVAC       → mini_split
      - Structural → wood
      - Use        → single_family
      - Stories    → 2 or 3
    """
    pri      = getattr(spec.priority, 'value', str(spec.priority))
    hvac     = getattr(getattr(spec, 'hvac_preference', None), 'value',
                       str(getattr(spec, 'hvac_preference', '') or ''))
    use      = getattr(spec, 'building_use', 'multi_family')
    is_sfr   = use in ('single_family', 'adu')
    struct   = getattr(spec.structural_system, 'value', str(spec.structural_system))
    stories  = spec.stories or 2
    style    = getattr(getattr(spec, 'style', None), 'value',
                       str(getattr(spec, 'style', '') or ''))

    # Victorian: Space + Classic & Gabled + Mini Split + Wood + Single Family + 2-3 stories
    if (pri == 'space'
            and style == 'classic_gabled'
            and hvac == 'mini_split'
            and struct == 'wood'
            and is_sfr
            and stories >= 2):
        return 'victorian_narrow_lot'

    # Future archetypes added here — each is just another elif block
    return None


def load_archetype(archetype_id: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(_ARCHETYPE_DIR, f"{archetype_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def get_archetype(spec) -> Optional[Dict[str, Any]]:
    """Detect and load archetype for a spec. Returns None → generic generation."""
    aid = detect_archetype(spec)
    return load_archetype(aid) if aid else None


def apply_archetype_to_neighbor_style(archetype: Dict, neighbor_style: Dict) -> Dict:
    """
    Inject archetype facade constraints into neighbor_style so the facade
    generator produces the correct material, color, and arch_style.
    neighbor_style is mutated in place and returned.
    """
    pc = archetype.get('petronus_classification', {})
    palette = pc.get('facade_color_palette', {})

    neighbor_style['dominant_arch_style'] = pc.get('dominant_arch_style', 'modern')
    neighbor_style['dominant_material']   = 'wood'
    if palette.get('body'):
        neighbor_style['facade_color']    = palette['body']
    if palette.get('window_frame'):
        neighbor_style['window_color']    = palette['window_frame']

    # Victorian: tall narrow windows, no horizontal bands, no balconies
    neighbor_style['window_style']            = 'tall_narrow'
    neighbor_style['horizontal_bands']        = False
    neighbor_style['has_balconies']           = False

    return neighbor_style


def apply_archetype_to_design_brief(archetype: Dict, design_brief: Optional[Dict]) -> Dict:
    """
    Clamp design brief dimensions to archetype lot constraints.
    Returns a (possibly new) brief dict.
    """
    brief = dict(design_brief) if design_brief else {}
    lot = archetype.get('lot', {})

    # Convert ft → m for brief comparison
    max_w_ft = lot.get('width_ft_max', 35)
    max_w_m  = max_w_ft * 0.3048

    if 'width_m' in brief:
        brief['width_m'] = min(brief['width_m'], max_w_m)

    # Victorian is always a narrow rectangle — override shape
    brief['shape'] = 'rectangle'

    return brief
