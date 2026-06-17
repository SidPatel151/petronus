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


def detect_archetype(spec, site_context=None) -> Optional[str]:
    """
    Infer archetype ID from spec parameters and (optionally) real site terrain data.
    Returns the JSON filename stem (without .json), or None for generic generation.
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

    # Terrain slope from real USGS data (if site context available)
    slope_pct = 0.0
    if site_context:
        terrain = getattr(site_context, 'terrain', None) or {}
        slope_pct = terrain.get('slope_pct', 0.0) if isinstance(terrain, dict) else 0.0

    # ADU: always takes priority over style-based detection
    is_adu = use in ('adu',) or getattr(use, 'value', '') == 'adu'
    if is_adu:
        return 'adu_compact'

    # Hillside: real slope ≥15% wins over everything — even explicit style choice.
    # A user who picks classic_gabled on a 20% slope still gets a hillside house.
    if is_sfr and slope_pct >= 15.0:
        return 'hillside_stepped'

    # Victorian: classic_gabled style + SFR 2+ stories (no HVAC restriction — users don't set it)
    if style == 'classic_gabled' and is_sfr and stories >= 2:
        return 'victorian_narrow_lot'

    # Hillside: explicit style choice (used when slope data is unavailable / flat parcel)
    if is_sfr and style in ('sculpted_stepped', 'hillside'):
        return 'hillside_stepped'

    # Mid-Century Modern: modern style + single family, 1-2 stories
    if (style in ('modern_linear', 'contemporary_box', 'mid_century')
            and is_sfr and stories <= 2):
        return 'mid_century_modern'

    # High-Density Townhome: multi-family + 3+ stories
    if use == 'multi_family' and stories >= 3 and pri in ('space', 'cost'):
        return 'high_density_townhome'

    # High-End Custom: quality priority + single family
    if is_sfr and pri == 'quality':
        return 'high_end_custom'

    # Urban Infill / Zero-Lot: space-priority modern SFR, 2+ stories
    if (is_sfr and pri == 'space' and stories >= 2
            and style in ('modern_linear', 'contemporary_box')):
        return 'urban_infill_zero_lot'

    # Production / Tract: cost-priority SFR, wood frame
    if is_sfr and pri == 'cost' and struct == 'wood':
        return 'production_tract'

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


def get_archetype(spec, site_context=None) -> Optional[Dict[str, Any]]:
    """Detect and load archetype for a spec. Returns None → generic generation."""
    aid = detect_archetype(spec, site_context=site_context)
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
    Set shape type + concrete lot dimensions so each archetype produces a
    visually distinctive building.

    'shape' values and their massing generator behaviour:
      'narrow_lot'   → 3 narrow-rectangle variants (Victorian, Townhome, Zero-Lot)
      'wide_shallow' → wide shallow plate variants (Mid-Century, Prefab)
      'l_shape'      → L + U + stepped complex massing (High-End Custom)
      'sculpted'     → hillside stepped massing
      'rectangle'    → standard rect / L / U (ADU, Production Tract)
    """
    brief = dict(design_brief) if design_brief else {}
    arch_id = archetype.get('id', '')

    if arch_id == 'victorian_narrow_lot':
        # Narrow SF lot: 25 ft wide × 60+ ft deep, tall multi-story
        brief['shape']        = 'narrow_lot'
        brief['width_m']      = min(brief.get('width_m', 9999), 7.6)   # 25 ft
        brief['depth_m']      = max(brief.get('depth_m', 0),   17.0)   # 56 ft min
        brief['arch_style']   = 'classic_gabled'
        brief['roof_pitch_12']= 10

    elif arch_id == 'adu_compact':
        # Compact backyard cottage — small rectangle
        brief['shape']        = 'rectangle'
        brief['width_m']      = min(brief.get('width_m', 9999), 9.8)   # 32 ft max
        brief['depth_m']      = min(brief.get('depth_m', 9999), 11.0)  # 36 ft max
        brief['arch_style']   = 'contemporary_box'
        brief['roof_pitch_12']= 0

    elif arch_id == 'mid_century_modern':
        # Wide shallow plate — classic ranch proportions
        brief['shape']        = 'wide_shallow'
        brief['width_m']      = max(brief.get('width_m', 0),   13.5)   # 44 ft wide minimum
        brief['depth_m']      = min(brief.get('depth_m', 9999), 12.0)  # 39 ft shallow max
        brief['arch_style']   = 'modern_linear'
        brief['roof_pitch_12']= 2

    elif arch_id == 'hillside_stepped':
        brief['shape']        = 'sculpted'
        brief['arch_style']   = 'sculpted_stepped'
        brief['roof_pitch_12']= 3

    elif arch_id == 'high_density_townhome':
        # Attached narrow units, 3+ stories
        brief['shape']        = 'narrow_lot'
        brief['width_m']      = min(brief.get('width_m', 9999), 8.0)   # 26 ft unit width
        brief['depth_m']      = max(brief.get('depth_m', 0),   14.0)   # 46 ft deep
        brief['arch_style']   = 'modern_linear'
        brief['roof_pitch_12']= 0

    elif arch_id == 'urban_infill_zero_lot':
        # Narrow modern infill
        brief['shape']        = 'narrow_lot'
        brief['width_m']      = min(brief.get('width_m', 9999), 7.6)   # 25 ft max
        brief['depth_m']      = max(brief.get('depth_m', 0),   14.0)
        brief['arch_style']   = 'contemporary_box'
        brief['roof_pitch_12']= 2

    elif arch_id == 'production_tract':
        # Standard ranch/tract — near-square proportions
        brief['shape']        = 'rectangle'
        brief['width_m']      = max(brief.get('width_m', 0),   11.0)   # 36 ft wide
        brief['depth_m']      = max(brief.get('depth_m', 0),   13.0)   # 43 ft deep
        brief['arch_style']   = 'classic_gabled'
        brief['roof_pitch_12']= 5

    elif arch_id == 'high_end_custom':
        # Complex irregular massing — L, U, stepped
        brief['shape']        = 'l_shape'
        brief['arch_style']   = 'modern_linear'
        brief['roof_pitch_12']= 4

    elif arch_id == 'prefab_modern':
        # Modular box — wide and shallow (2 modules wide)
        brief['shape']        = 'wide_shallow'
        brief['width_m']      = max(brief.get('width_m', 0),   12.0)   # 2× 6 m module
        brief['depth_m']      = min(brief.get('depth_m', 9999), 8.5)   # single module depth
        brief['arch_style']   = 'contemporary_box'
        brief['roof_pitch_12']= 0

    return brief
