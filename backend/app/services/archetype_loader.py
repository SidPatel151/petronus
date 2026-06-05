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

    # ADU: always takes priority over style-based detection
    is_adu = use in ('adu',) or getattr(use, 'value', '') == 'adu'
    if is_adu:
        return 'adu_compact'

    # Victorian: Space + Classic & Gabled + Mini Split + Wood + Single Family + 2-3 stories
    if (pri == 'space'
            and style == 'classic_gabled'
            and hvac == 'mini_split'
            and struct == 'wood'
            and is_sfr
            and stories >= 2):
        return 'victorian_narrow_lot'

    # Mid-Century Modern: modern style + slab + single family
    if (style in ('modern_linear', 'contemporary_box', 'mid_century')
            and is_sfr
            and stories == 1):
        return 'mid_century_modern'

    # Hillside: sculpted massing style (implies hillside/stepped site)
    if style == 'sculpted_stepped' or style == 'hillside':
        return 'hillside_stepped'

    # High-Density Townhome: multi-family + 3-4 stories + wood or concrete
    if (use == 'multi_family'
            and stories >= 3
            and pri in ('space', 'cost')):
        return 'high_density_townhome'

    # Urban Infill / Zero-Lot: single family + high priority on space + small footprint
    if (is_sfr and pri == 'space' and stories >= 2
            and style in ('modern_linear', 'contemporary_box')):
        return 'urban_infill_zero_lot'

    # Production / Tract: cost-priority SFR, wood frame, 1-2 stories
    if (is_sfr and pri == 'cost' and struct == 'wood' and stories <= 2):
        return 'production_tract'

    # High-End Custom: quality priority + single family
    if (is_sfr and pri == 'quality'):
        return 'high_end_custom'

    # Prefab Modern: prefab structural system
    if struct in ('prefab', 'modular'):
        return 'prefab_modern'

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
    arch_id = archetype.get('id', '')

    neighbor_style['dominant_arch_style'] = pc.get('dominant_arch_style', 'modern')
    neighbor_style['dominant_material']   = 'wood'
    if palette.get('body'):
        neighbor_style['facade_color']    = palette['body']
    if palette.get('window_frame'):
        neighbor_style['window_color']    = palette['window_frame']

    if arch_id == 'adu_compact':
        neighbor_style['window_style']      = 'large_horizontal'
        neighbor_style['horizontal_bands']  = False
        neighbor_style['has_balconies']     = False
        neighbor_style['dominant_material'] = 'fiber_cement'
    elif arch_id == 'victorian_narrow_lot':
        neighbor_style['window_style']     = 'tall_narrow'
        neighbor_style['horizontal_bands'] = False
        neighbor_style['has_balconies']    = False
    elif arch_id == 'mid_century_modern':
        neighbor_style['window_style']      = 'large_horizontal'
        neighbor_style['horizontal_bands']  = False
        neighbor_style['has_balconies']     = False
        neighbor_style['dominant_material'] = 'wood'
        neighbor_style['dominant_arch_style'] = 'modern_linear'
    elif arch_id == 'hillside_stepped':
        neighbor_style['window_style']      = 'large_horizontal'
        neighbor_style['horizontal_bands']  = True
        neighbor_style['has_balconies']     = True
        neighbor_style['dominant_arch_style'] = 'sculpted_stepped'
    elif arch_id == 'high_density_townhome':
        neighbor_style['window_style']      = 'large_horizontal'
        neighbor_style['horizontal_bands']  = True
        neighbor_style['has_balconies']     = True
        neighbor_style['dominant_material'] = 'fiber_cement'
        neighbor_style['dominant_arch_style'] = 'modern_linear'
    elif arch_id == 'urban_infill_zero_lot':
        neighbor_style['window_style']      = 'large_horizontal'
        neighbor_style['horizontal_bands']  = False
        neighbor_style['has_balconies']     = False
        neighbor_style['dominant_arch_style'] = 'contemporary_box'
    elif arch_id == 'production_tract':
        neighbor_style['window_style']      = 'double_hung'
        neighbor_style['horizontal_bands']  = False
        neighbor_style['has_balconies']     = False
        neighbor_style['dominant_arch_style'] = 'classic_gabled'
    elif arch_id == 'high_end_custom':
        neighbor_style['window_style']      = 'large_horizontal'
        neighbor_style['horizontal_bands']  = False
        neighbor_style['has_balconies']     = True
        neighbor_style['dominant_material'] = 'stucco'
        neighbor_style['dominant_arch_style'] = 'modern_linear'
    elif arch_id == 'prefab_modern':
        neighbor_style['window_style']      = 'large_horizontal'
        neighbor_style['horizontal_bands']  = True
        neighbor_style['has_balconies']     = False
        neighbor_style['dominant_material'] = 'fiber_cement'
        neighbor_style['dominant_arch_style'] = 'contemporary_box'

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

    arch_id = archetype.get('id', '')

    massing = archetype.get('massing_hints', {})
    brief_shape = massing.get('brief_shape', '')

    if arch_id == 'adu_compact':
        brief['shape'] = 'rectangle'
        max_w_m = 32 * 0.3048
        if 'width_m' in brief:
            brief['width_m'] = min(brief['width_m'], max_w_m)
    elif arch_id == 'victorian_narrow_lot':
        brief['shape'] = 'rectangle'
    elif arch_id == 'mid_century_modern':
        brief['shape'] = 'rectangle'   # wide, shallow single-story plate
        brief['arch_style'] = 'modern_linear'
    elif arch_id == 'hillside_stepped':
        brief['shape'] = 'sculpted'    # stepped/irregular massing
        brief['arch_style'] = 'sculpted_stepped'
    elif arch_id == 'high_density_townhome':
        brief['shape'] = 'rectangle'
        brief['arch_style'] = 'modern_linear'
    elif arch_id == 'urban_infill_zero_lot':
        brief['shape'] = 'rectangle'
        brief['arch_style'] = 'contemporary_box'
        max_w_m = 25 * 0.3048   # zero-lot is narrow
        if 'width_m' in brief:
            brief['width_m'] = min(brief['width_m'], max_w_m)
    elif arch_id == 'production_tract':
        brief['shape'] = 'rectangle'
        brief['arch_style'] = 'classic_gabled'
    elif arch_id == 'high_end_custom':
        brief['shape'] = 'rectangle'
        brief['arch_style'] = 'modern_linear'
    elif arch_id == 'prefab_modern':
        brief['shape'] = 'rectangle'
        brief['arch_style'] = 'contemporary_box'
        max_w_m = 14 * 0.3048   # single module highway width
        if 'width_m' in brief:
            brief['width_m'] = min(brief['width_m'], max_w_m * 2)  # up to 2 modules wide

    return brief
