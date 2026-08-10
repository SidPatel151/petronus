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
    _use_str = getattr(use, 'value', str(use))
    is_sfr   = _use_str in ('single_family', 'adu')
    struct   = getattr(spec.structural_system, 'value', str(spec.structural_system))
    stories  = spec.stories or 2
    style    = getattr(getattr(spec, 'style', None), 'value',
                       str(getattr(spec, 'style', '') or ''))

    # Terrain signals from USGS 3DEP (works anywhere in the US, not city-specific)
    slope_pct  = 0.0
    avg_elev_m = 0.0
    if site_context:
        terrain = getattr(site_context, 'terrain', None) or {}
        if isinstance(terrain, dict):
            slope_pct  = terrain.get('slope_pct', 0.0)
            avg_elev_m = terrain.get('avg_elevation_m', 0.0)

    # ADU: always takes priority over style-based detection
    is_adu = use in ('adu',) or getattr(use, 'value', '') == 'adu'
    if is_adu:
        return 'adu_compact'

    # Hillside detection — purely elevation/slope based so it works globally:
    # • Parcel slope ≥ 8 %  →  stepped massing required
    # • Avg elevation ≥ 200 m (≈ 660 ft) →  mountain/foothill territory regardless of micro-slope
    # • Elevated (≥ 100 m) + any notable grade (≥ 4 %)  →  combined signal for rolling hills
    _steep    = slope_pct >= 8.0
    _mountain = avg_elev_m >= 200.0
    _hilly    = avg_elev_m >= 100.0 and slope_pct >= 4.0
    if _steep or _mountain or _hilly:
        return 'hillside_stepped'

    # Lot size signal — used as a secondary signal, not a gate
    lot_sqft = getattr(site_context, 'area_sqft', 0) if site_context else 0
    is_small_lot = 0 < lot_sqft < 5_000   # SF rowhouse ~2.5K sqft

    # Style-first: if user explicitly chose a style, respect it regardless of building_use.
    # A user who picks Victorian + "multi-family" wants a Victorian-style building.
    if style == 'classic_gabled' and stories >= 2:
        return 'victorian_narrow_lot'

    if style in ('sculpted_stepped', 'hillside'):
        return 'hillside_stepped'

    if style in ('modern_linear', 'contemporary_box', 'mid_century') and stories <= 2:
        return 'mid_century_modern'

    # After style is resolved, fall through to use-type defaults
    # Hillside: explicit style choice (slope data unavailable or flat parcel override)
    if is_sfr and style in ('sculpted_stepped', 'hillside'):
        return 'hillside_stepped'

    # Mid-Century Modern: modern style + single family, 1-2 stories
    if (style in ('modern_linear', 'contemporary_box', 'mid_century')
            and is_sfr and stories <= 2):
        return 'mid_century_modern'

    # High-Density Townhome: multi-family any story count
    if _use_str == 'multi_family':
        if is_small_lot:
            return 'urban_infill_zero_lot'
        return 'high_density_townhome'

    # High-End Custom: quality priority + single family
    if is_sfr and pri == 'quality':
        return 'high_end_custom'

    # Urban Infill / Zero-Lot: space-priority modern SFR, 2+ stories, small lot
    if (is_sfr and pri == 'space' and stories >= 2
            and style in ('modern_linear', 'contemporary_box') and is_small_lot):
        return 'urban_infill_zero_lot'

    # Production / Tract: cost-priority SFR, wood frame — the suburban default
    if is_sfr and pri == 'cost' and struct == 'wood':
        return 'production_tract'

    # Prefab Modern: prefab structural system
    if struct in ('prefab', 'modular'):
        return 'prefab_modern'

    # SFR fallback: if nothing matched, use production tract as the sensible default
    if is_sfr:
        return 'production_tract'

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
        neighbor_style['horizontal_bands']  = True   # floor-line bands
        neighbor_style['has_balconies']     = True   # small deck on 2-story ADU
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
        neighbor_style['dominant_arch_style'] = 'suburban_traditional'
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
    Enforce physical massing constraints per archetype.
    Only touches shape/footprint/arch_style — Claude owns all facade/material params.

    'shape' values:
      'narrow_lot'   → Victorian, Townhome, Zero-Lot
      'wide_shallow' → Mid-Century, Prefab
      'l_shape'      → High-End Custom
      'sculpted'     → Hillside stepped
      'rectangle'    → ADU, Production Tract
    """
    brief = dict(design_brief) if design_brief else {}
    arch_id = archetype.get('id', '')

    # Helper: enforce aspect ratio without destroying the area Claude computed.
    # Solves for (w, d) such that w*d = original area and w/d = target_ratio.
    def _ratio(w: float, d: float, target_ratio: float) -> tuple:
        area = max(w * d, 1.0)
        new_w = (area * target_ratio) ** 0.5
        new_d = area / new_w
        return round(new_w, 2), round(new_d, 2)

    w = brief.get('width_m') or 12.0
    d = brief.get('depth_m') or 12.0

    if arch_id == 'victorian_narrow_lot':
        brief['shape']         = 'narrow_lot'
        brief['arch_style']    = 'classic_gabled'
        brief['roof_type']     = 'gabled'
        brief['roof_pitch_12'] = 10
        # Victorian = narrow and deep: width capped at 7.6m, depth grows to match area
        brief['width_m'] = min(w, 7.6)
        brief['depth_m'] = max((w * d) / brief['width_m'], 17.0)

    elif arch_id == 'adu_compact':
        brief['shape']         = 'rectangle'
        brief['arch_style']    = 'contemporary_box'
        brief['roof_type']     = 'flat'
        brief['roof_pitch_12'] = 0
        brief['width_m']       = min(w, 9.8)
        brief['depth_m']       = (w * d) / brief['width_m']

    elif arch_id == 'mid_century_modern':
        brief['shape']         = 'wide_shallow'
        brief['arch_style']    = 'modern_linear'
        brief['roof_type']     = 'shed'
        brief['roof_pitch_12'] = 1
        # MCM = wider than deep (ratio ~1.5:1) — preserve area, enforce ratio
        brief['width_m'], brief['depth_m'] = _ratio(w, d, 1.5)
        brief['width_m'] = max(brief['width_m'], 11.0)

    elif arch_id == 'hillside_stepped':
        brief['shape']         = 'sculpted'
        brief['arch_style']    = 'sculpted_stepped'
        brief['roof_type']     = 'shed'
        brief['roof_pitch_12'] = 2

    elif arch_id == 'high_density_townhome':
        brief['shape']         = 'narrow_lot'
        brief['arch_style']    = 'modern_linear'
        brief['roof_type']     = 'flat'
        brief['roof_pitch_12'] = 0
        # Townhome = narrow per unit, depth grows with area
        brief['width_m'] = min(w, 8.5)
        brief['depth_m'] = max((w * d) / brief['width_m'], 14.0)

    elif arch_id == 'urban_infill_zero_lot':
        brief['shape']         = 'narrow_lot'
        brief['arch_style']    = 'contemporary_box'
        brief['roof_type']     = 'flat'
        brief['roof_pitch_12'] = 0
        brief['width_m'] = min(w, 8.0)
        brief['depth_m'] = max((w * d) / brief['width_m'], 14.0)

    elif arch_id == 'production_tract':
        brief['shape']         = 'rectangle'
        brief['arch_style']    = 'suburban_traditional'
        brief['roof_type']     = 'gabled'
        brief['roof_pitch_12'] = 6
        # Near-square footprint: ratio ~1.1:1
        brief['width_m'], brief['depth_m'] = _ratio(w, d, 1.1)
        brief['width_m'] = max(brief['width_m'], 11.0)
        brief['depth_m'] = max(brief['depth_m'], 11.0)

    elif arch_id == 'high_end_custom':
        brief['shape']         = 'l_shape'
        brief['arch_style']    = 'modern_linear'
        brief['roof_type']     = 'flat'
        brief['roof_pitch_12'] = 1

    elif arch_id == 'prefab_modern':
        brief['shape']         = 'wide_shallow'
        brief['arch_style']    = 'contemporary_box'
        brief['roof_type']     = 'flat'
        brief['roof_pitch_12'] = 1
        brief['width_m'], brief['depth_m'] = _ratio(w, d, 1.6)
        brief['width_m'] = max(brief['width_m'], 12.0)

    return brief
