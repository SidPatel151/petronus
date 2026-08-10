"""
AISemanticsBuilder — Claude generates the full parametric building model.

Claude doesn't fill in parameter slots. It describes the entire building
from architectural knowledge: wall positions, opening placements, roof geometry,
material choices. The result is a SemanticBuildingModel the frontend geometry
engine converts to Three.js geometry with real CSG wall openings.
"""
import base64
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List

_DATA_ROOT       = Path(__file__).parent.parent / "data"
_BLUEPRINT_INDEX = _DATA_ROOT / "blueprint_index.json"

# Hard caps enforced after Claude's response
SFR_MAX_SQFT   = 5500
SFR_MAX_BED    = 7
ADU_MAX_SQFT   = 1200


def _load_blueprint_examples(archetype_id: str, max_examples: int = 2) -> List[Dict]:
    """Return the best matching blueprint entries from the pre-built index."""
    if not _BLUEPRINT_INDEX.exists():
        return []
    try:
        entries = json.loads(_BLUEPRINT_INDEX.read_text())
    except Exception:
        return []
    matches = [e for e in entries if e.get("archetype") == archetype_id and e.get("confidence", 0) >= 0.7]
    matches.sort(key=lambda e: (-(e.get("confidence", 0)), -len(e.get("rooms", []))))
    return matches[:max_examples]


def _blueprint_image_blocks(examples: List[Dict]) -> List[Dict]:
    """Build Claude vision content blocks for blueprint images."""
    blocks = []
    mt_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    for ex in examples:
        src = ex.get("source_file", "")
        if not src:
            continue
        img_path = _DATA_ROOT / src
        if not img_path.exists():
            continue
        mt = mt_map.get(img_path.suffix.lower(), "image/jpeg")
        try:
            b64 = base64.standard_b64encode(img_path.read_bytes()).decode("utf-8")
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}})
        except Exception:
            pass
    return blocks


def _blueprint_text_summary(examples: List[Dict]) -> str:
    """Convert blueprint index entries to a compact text description for the prompt."""
    if not examples:
        return ""
    lines = ["\nREFERENCE BLUEPRINTS (from real images of this archetype):"]
    for i, ex in enumerate(examples, 1):
        rooms = ex.get("rooms", [])
        room_str = ", ".join(
            f"{r['type']}(fl{r.get('floor', 0)}{', '+r['position'] if r.get('position') else ''})"
            for r in rooms[:10]
        )
        lines.append(
            f"  [{i}] {ex.get('building_type','?')} | "
            f"{ex.get('bedrooms','?')}BR {ex.get('bathrooms','?')}BA | "
            f"{ex.get('total_sqft','?')} sqft | "
            f"{ex.get('floors','?')} stories | "
            f"material={ex.get('facade_material','?')} | style={ex.get('style','?')}"
        )
        if room_str:
            lines.append(f"     Rooms: {room_str}")
        if ex.get("stair"):
            s = ex["stair"]
            lines.append(f"     Stair: {s.get('location','?')} {s.get('direction','')}")
        if ex.get("wet_wall_location"):
            lines.append(f"     Wet wall: {ex['wet_wall_location']}")
        if ex.get("notes"):
            lines.append(f"     Notes: {ex['notes']}")
    lines.append("Use these blueprints as your primary visual and programmatic reference.")
    return "\n".join(lines)


def _get_api_key() -> str:
    try:
        from app.core.config import settings
        return settings.ANTHROPIC_API_KEY
    except Exception:
        import os
        return os.environ.get("ANTHROPIC_API_KEY", "")


async def generate_semantic_building(
    spec_dict: Dict[str, Any],
    site_ctx_dict: Dict[str, Any],
    neighbor_analysis: Dict[str, Any],
    archetype_id: str = "",
    archetype_display_name: str = "",
) -> Dict[str, Any]:
    """
    Ask Claude to generate a complete SemanticBuildingModel JSON.
    Returns dict matching the TypeScript SemanticBuildingModel interface.
    Falls back to _default_model() if Claude fails.
    """
    api_key = _get_api_key()
    if not api_key:
        return _default_model(spec_dict, neighbor_analysis, archetype_id)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        terrain      = site_ctx_dict.get("terrain", {}) or {}
        slope        = terrain.get("slope_pct", 0)
        avg_elev_m   = terrain.get("avg_elevation_m", 0)
        municipality = site_ctx_dict.get("municipality", "")
        flood        = site_ctx_dict.get("flood_zone", "X")
        seismic      = site_ctx_dict.get("seismic_category", "D")
        parcel_sqft  = site_ctx_dict.get("area_sqft", 5000)
        weather      = site_ctx_dict.get("weather") or {}
        climate_zone = weather.get("climate_zone", "") if weather else ""

        stories   = spec_dict.get("stories", 2)
        bedrooms  = min(int(spec_dict.get("bedrooms", 3)), SFR_MAX_BED)
        bathrooms = float(spec_dict.get("bathrooms", 2))
        priority  = spec_dict.get("priority", "cost")
        use       = spec_dict.get("building_use", "single_family")

        # Use-aware sqft cap: SFR=5500, ADU=1200, multi-family no hard cap here
        _sqft_caps = {"single_family": SFR_MAX_SQFT, "adu": ADU_MAX_SQFT}
        _sqft_cap  = _sqft_caps.get(use, 50_000)
        sqft       = min(float(spec_dict.get("sqft") or spec_dict.get("target_gross_area_sqft", 2000)), _sqft_cap)

        nav      = neighbor_analysis
        avg_w    = nav.get("avg_width_m", 12)
        avg_d    = nav.get("avg_depth_m", 14)
        dom_mat  = nav.get("dominant_material", "stucco")

        # Build a meaningful arch_label — never fall back to "single-family residential" for MF
        _use_labels = {
            "single_family": "single-family residential",
            "multi_family":  "multi-family residential",
            "adu":           "accessory dwelling unit (ADU)",
        }
        arch_label = archetype_display_name or archetype_id or _use_labels.get(use, "residential")

        # Load real blueprint images + metadata for this archetype
        bp_examples    = _load_blueprint_examples(archetype_id or "")
        bp_img_blocks  = _blueprint_image_blocks(bp_examples)
        bp_text        = _blueprint_text_summary(bp_examples)

        # Target footprint area per floor so Claude can solve dimensions directly
        _floor_area_m2 = (sqft / 10.764) / max(stories, 1)
        _floor_area_sqft_per_floor = sqft / max(stories, 1)

        prompt = f"""You are a licensed residential architect. Design a building and return ONLY a compact JSON spec.
{bp_text}

PLATFORM LIMITS (hard caps — never exceed):
  SFR max: {SFR_MAX_SQFT:,} sqft | ADU max: {ADU_MAX_SQFT:,} sqft | SFR max bedrooms: {SFR_MAX_BED}
  Multi-family: no platform sqft cap — size to unit count and lot coverage

ARCHETYPE: {arch_label}
Make it authentically represent the archetype — NOT a generic box.
victorian_narrow_lot: bay windows, steep gable (9-12), wood siding, ornate trim, narrow lot.
mid_century_modern: ribbon/strip windows, low pitch (0-3), wide shallow plan, indoor-outdoor.
hillside_stepped: large glazing, flat/shed roof, cantilevered upper floor, follows terrain steps.
adu_compact: compact footprint, flat roof, fiber cement, efficient open plan.
high_density_townhome: stacked units, shared party walls, roof deck, contemporary materials.
urban_infill_zero_lot: narrow modern box, 3 stories, zero side setback, metal/glass facade.
production_tract: near-square footprint, attached garage, gabled roof, cost-efficient.
high_end_custom: complex L/U massing, premium materials, quality finishes throughout.
prefab_modern: modular rectangular sections, flat or low-slope, factory precision.

SITE: {municipality or "CA"} | lot {parcel_sqft:.0f} sqft | slope {slope:.1f}% | elev {avg_elev_m:.0f}m | seismic SDC {seismic}
Neighbors: {avg_w:.1f}m wide avg | dominant material: {dom_mat}

HARD CONSTRAINTS — follow exactly:
- Building use: {use} | Priority: {priority}
- Bedrooms: EXACTLY {bedrooms} | Bathrooms: EXACTLY {bathrooms}
- Total gross area: EXACTLY {sqft:.0f} sqft across {stories} floor(s)
- Stories: EXACTLY {stories}
- Footprint: width_m × depth_m = {_floor_area_m2:.1f} m² per floor
  ({_floor_area_sqft_per_floor:.0f} sqft/floor × {stories} floors = {sqft:.0f} sqft total)

Return ONLY valid JSON, no markdown:
{{
  "style_intent": "<one sentence>",
  "footprint": {{"width_m": <n>, "depth_m": <n>, "shape": "rectangle|narrow_lot|l_shape"}},
  "floors": [{{"level": 0, "height_m": <n>}}, {{"level": 1, "height_m": <n>}}],
  "facade": {{
    "material": "wood_siding|stucco|brick|concrete|fiber_cement|metal_panel|stone",
    "windows_per_floor": [
      {{"floor": 0, "wins": [{{"style": "bay_3panel|double_hung|strip_horizontal|picture|casement|sliding_glass", "pos_frac": <0-1>, "width_m": <n>, "height_m": <n>, "sill_m": <n>}}]}},
      {{"floor": 1, "wins": [...]}}
    ],
    "door": {{"pos_frac": <0-1>, "width_m": 1.05, "style": "paneled|victorian_paneled|modern_flush"}},
    "porch": {{"type": "entry|wraparound|rear_deck|none", "depth_m": <n>, "width_frac": <0-1>}}
  }},
  "roof": {{"type": "flat|gabled|hipped|shed|mansard", "pitch_12": <0-12>, "material": "asphalt_shingle|slate|metal_standing_seam|clay_tile|flat_membrane", "overhang_m": <0.3-0.8>}},
  "trim": {{"band_height_m": <0=none,0.1-0.3=band>, "band_at_floor": [<floors>], "trim_color": "<hex>"}},
  "materials": {{"wall_body": "<same as facade.material>", "trim_color": "<hex>", "window_frame_color": "<hex>", "door_color": "<hex>", "roof": "<roof material>"}}
}}"""

        # Build message content — images first so Claude sees real blueprints
        content: List[Dict] = []
        for img_block in bp_img_blocks:
            content.append(img_block)
        content.append({"type": "text", "text": prompt})

        msg = await asyncio.to_thread(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=2500,
            messages=[{"role": "user", "content": content}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = "\n".join(l for l in raw.splitlines() if not l.startswith("```")).strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end <= start:
            raise ValueError("No JSON in response")
        compact = json.loads(raw[start:end])

        # Expand compact design spec into full SemanticBuildingModel
        model = _expand_compact(compact, stories, archetype_id, target_sqft=sqft)
        model["_bedrooms"]  = bedrooms
        model["_bathrooms"] = bathrooms
        model["_sqft"]      = sqft
        model["_source"]    = "claude"
        return model

    except Exception as e:
        fb = _default_model(spec_dict, neighbor_analysis, archetype_id)
        fb["_source"] = f"fallback ({str(e)[:80]})"
        return fb


def _expand_compact(c: Dict, stories: int, archetype_id: str, target_sqft: float = 0) -> Dict[str, Any]:
    """
    Convert Claude's compact design spec into a full SemanticBuildingModel
    with explicit wall coordinates and opening offset_m values.
    Rescales the footprint if Claude's dimensions are more than 10% off the target.
    """
    import math as _math
    fp   = c.get("footprint", {})
    w    = float(fp.get("width_m", 10))
    d    = float(fp.get("depth_m", 12))
    shp  = fp.get("shape", "rectangle")

    # Enforce target sqft — rescale footprint if Claude missed by more than 10%
    if target_sqft > 0 and stories > 0:
        actual_sqft = w * d * stories * 10.764
        ratio = target_sqft / max(actual_sqft, 1)
        if ratio < 0.90 or ratio > 1.10:
            scale = _math.sqrt(ratio)
            w = round(w * scale, 2)
            d = round(d * scale, 2)
    mat  = c.get("facade", {}).get("material", c.get("materials", {}).get("wall_body", "stucco"))

    floor_specs = c.get("floors", [{"level": i, "height_m": 3.0} for i in range(stories)])
    # Pad or trim to match stories
    while len(floor_specs) < stories:
        floor_specs.append({"level": len(floor_specs), "height_m": 3.0})
    floor_specs = floor_specs[:stories]

    facade    = c.get("facade", {})
    wins_by_fl: Dict[int, list] = {}
    for wf in facade.get("windows_per_floor", []):
        fl = int(wf.get("floor", 0))
        wins_by_fl[fl] = wf.get("wins", [])

    door_spec = facade.get("door", {})
    porch_spec = facade.get("porch", {})

    walls: list = []
    openings: list = []

    for fs in floor_specs:
        fl  = int(fs.get("level", 0))
        fh  = float(fs.get("height_m", 3.0))
        walls += [
            {"id": f"f{fl}_front", "floor": fl, "start": [0,   0], "end": [w,   0], "height_m": fh, "thickness_m": 0.15, "exterior": True,  "material": mat},
            {"id": f"f{fl}_right", "floor": fl, "start": [w,   0], "end": [w,   d], "height_m": fh, "thickness_m": 0.15, "exterior": True,  "material": mat},
            {"id": f"f{fl}_back",  "floor": fl, "start": [w,   d], "end": [0,   d], "height_m": fh, "thickness_m": 0.15, "exterior": True,  "material": mat},
            {"id": f"f{fl}_left",  "floor": fl, "start": [0,   d], "end": [0,   0], "height_m": fh, "thickness_m": 0.15, "exterior": True,  "material": mat},
        ]

        # Windows from Claude's compact spec
        for i, wc in enumerate(wins_by_fl.get(fl, [])):
            pos = float(wc.get("pos_frac", 0.2))
            ww  = float(wc.get("width_m", 1.0))
            offset = pos * w
            if offset + ww >= w - 0.1:
                continue
            openings.append({
                "id": f"win_f{fl}_{i}",
                "wall_id": f"f{fl}_front",
                "type": "window",
                "style": wc.get("style", "double_hung"),
                "offset_m": round(offset, 2),
                "width_m": ww,
                "height_m": float(wc.get("height_m", 1.3)),
                "sill_m": float(wc.get("sill_m", 0.9)),
            })

        # Front door on floor 0
        if fl == 0 and door_spec:
            pos = float(door_spec.get("pos_frac", 0.82))
            dw  = float(door_spec.get("width_m", 1.05))
            offset = max(0.2, pos * w)
            if offset + dw < w:
                openings.append({
                    "id": "door_main", "wall_id": "f0_front",
                    "type": "door", "style": door_spec.get("style", "paneled"),
                    "offset_m": round(offset, 2), "width_m": dw, "height_m": 2.1, "sill_m": 0.0,
                })

    # ── Side + back wall openings — per archetype defaults ──────────────
    # Gives the SemanticViewer side/back windows without a separate AI call.
    _SIDE_WINS_BY_ARCH = {
        "victorian_narrow_lot": [
            {"side": "left",  "style": "double_hung",    "off": 0.28, "w": 0.78, "h": 1.35, "sill": 0.85},
            {"side": "right", "style": "double_hung",    "off": 0.35, "w": 0.78, "h": 1.35, "sill": 0.85},
        ],
        "mid_century_modern": [
            {"side": "left",  "style": "strip_horizontal","off": 0.08, "w": 3.2,  "h": 0.72, "sill": 1.45},
            {"side": "right", "style": "strip_horizontal","off": 0.08, "w": 3.2,  "h": 0.72, "sill": 1.45},
        ],
        "hillside_stepped": [
            {"side": "left",  "style": "picture",         "off": 0.20, "w": 2.0,  "h": 1.8,  "sill": 0.35},
            {"side": "right", "style": "sliding_glass",   "off": 0.15, "w": 2.4,  "h": 2.1,  "sill": 0.0},
        ],
        "_default": [
            {"side": "left",  "style": "double_hung",    "off": 0.30, "w": 0.90, "h": 1.25, "sill": 0.90},
            {"side": "right", "style": "double_hung",    "off": 0.30, "w": 0.90, "h": 1.25, "sill": 0.90},
            {"side": "back",  "style": "sliding_glass",  "off": 0.28, "w": 2.00, "h": 2.10, "sill": 0.0},
        ],
    }
    import uuid as _uuid
    _side_specs = _SIDE_WINS_BY_ARCH.get(archetype_id, _SIDE_WINS_BY_ARCH["_default"])
    for fs in floor_specs:
        fl  = int(fs.get("level", 0))
        for sw in _side_specs:
            side    = sw["side"]
            wall_id = f"f{fl}_{side}"
            dim     = d if side in ("left", "right") else w
            offset  = sw["off"] * dim
            if offset + sw["w"] >= dim - 0.12:
                continue
            openings.append({
                "id": f"win_{side}_f{fl}_{_uuid.uuid4().hex[:4]}",
                "wall_id": wall_id,
                "type": "window",
                "style": sw["style"],
                "offset_m": round(offset, 2),
                "width_m":  sw["w"],
                "height_m": sw["h"],
                "sill_m":   sw["sill"],
            })

    # Porches
    porches = []
    if porch_spec and porch_spec.get("type", "none") != "none":
        porches.append({
            "type": porch_spec["type"], "floor": 0,
            "depth_m": float(porch_spec.get("depth_m", 1.5)),
            "width_m": round(w * float(porch_spec.get("width_frac", 0.4)), 1),
            "wall_id": "f0_front",
        })

    roof   = c.get("roof", {})
    trim   = c.get("trim", {})
    mats   = c.get("materials", {})

    return {
        "style_intent": c.get("style_intent", ""),
        "archetype_id": archetype_id,
        "footprint":    {"width_m": w, "depth_m": d, "shape": shp, "offset_x": 0, "offset_z": 0},
        "floors":       floor_specs,
        "walls":        walls,
        "openings":     openings,
        "porches":      porches,
        "roof": {
            "type":             roof.get("type", "gabled"),
            "pitch_12":         roof.get("pitch_12", 4),
            "material":         roof.get("material", "asphalt_shingle"),
            "overhang_m":       roof.get("overhang_m", 0.5),
            "parapet_height_m": 0.6,
        },
        "trim": {
            "cornice_height_m": 0.2,
            "band_height_m":    float(trim.get("band_height_m", 0)),
            "band_at_floor":    trim.get("band_at_floor", []),
            "trim_color":       trim.get("trim_color") or mats.get("trim_color", "#4a4a4a"),
        },
        "materials": {
            "wall_body":          mat,
            "trim_color":         mats.get("trim_color", "#4a4a4a"),
            "window_frame_color": mats.get("window_frame_color", "#2a2a2a"),
            "door_color":         mats.get("door_color", "#3a2a1a"),
            "roof":               mats.get("roof", roof.get("material", "asphalt_shingle")),
        },
    }


def _default_model(spec_dict: Dict, nav: Dict, archetype_id: str = "") -> Dict[str, Any]:
    """
    Archetype-specific fallback — no Claude needed.
    Each archetype produces a visually distinct building so the pipeline
    can be tested without API credits.
    """
    import math as _math
    stories     = spec_dict.get("stories", 2)
    bedrooms    = spec_dict.get("bedrooms", 3)
    target_sqft = float(spec_dict.get("target_gross_area_sqft", 0))

    # Archetype presets — real architectural proportions per style
    PRESETS = {
        "victorian_narrow_lot": {
            "intent": "Victorian Narrow Lot — 1890s wood rowhouse, steep gable, bay windows",
            "w": 7.3, "d": 17.0, "fh": 3.4,
            "shape": "narrow_lot",
            "mat": "wood_siding", "trim": "#f5f0e8", "frame": "#2a1a0a", "door_c": "#5c3010",
            "roof_type": "gabled", "pitch": 10, "roof_mat": "slate", "overhang": 0.6,
            "band_h": 0.18, "band_floors": [0, 1],
            "front_wins": [
                {"style": "bay_3panel", "offset_frac": 0.15, "w": 2.8, "h": 2.0, "sill": 0.45},
            ],
            "upper_wins": [
                {"style": "double_hung", "offset_frac": 0.20, "w": 0.85, "h": 1.4, "sill": 0.75},
                {"style": "double_hung", "offset_frac": 0.65, "w": 0.85, "h": 1.4, "sill": 0.75},
            ],
            "porches": [{"type": "entry", "depth_m": 1.2, "width_frac": 0.5}],
        },
        "mid_century_modern": {
            "intent": "Mid-Century Modern — wide shallow plate, ribbon windows, low roof",
            "w": 14.5, "d": 11.0, "fh": 2.75,
            "shape": "wide_shallow",
            "mat": "wood_siding", "trim": "#1a1a1a", "frame": "#0a0a0a", "door_c": "#2a1a0a",
            "roof_type": "shed", "pitch": 2, "roof_mat": "flat_membrane", "overhang": 0.9,
            "band_h": 0.0, "band_floors": [],
            "front_wins": [
                {"style": "strip_horizontal", "offset_frac": 0.08, "w": 10.5, "h": 1.1, "sill": 1.4},
            ],
            "upper_wins": [
                {"style": "strip_horizontal", "offset_frac": 0.08, "w": 10.5, "h": 1.0, "sill": 1.3},
            ],
            "porches": [{"type": "entry", "depth_m": 2.5, "width_frac": 0.35}],
        },
        "hillside_stepped": {
            "intent": "Hillside Stepped — cantilevered levels, large glazing, deck",
            "w": 11.0, "d": 13.0, "fh": 3.1,
            "shape": "sculpted",
            "mat": "concrete", "trim": "#708090", "frame": "#1a2a3a", "door_c": "#2a3a4a",
            "roof_type": "flat", "pitch": 0, "roof_mat": "flat_membrane", "overhang": 0.3,
            "band_h": 0.0, "band_floors": [],
            "front_wins": [
                {"style": "picture", "offset_frac": 0.10, "w": 3.5, "h": 2.4, "sill": 0.3},
                {"style": "picture", "offset_frac": 0.55, "w": 3.0, "h": 2.4, "sill": 0.3},
            ],
            "upper_wins": [
                {"style": "sliding_glass", "offset_frac": 0.08, "w": 4.5, "h": 2.2, "sill": 0.3},
            ],
            "porches": [{"type": "rear_deck", "depth_m": 2.8, "width_frac": 0.8}],
        },
        "high_end_custom": {
            "intent": "High-End Custom — L-shape stone & glass, modern luxury",
            "w": 15.0, "d": 16.0, "fh": 3.2,
            "shape": "l_shape",
            "mat": "stone", "trim": "#c0b090", "frame": "#1a1a1a", "door_c": "#3a2a1a",
            "roof_type": "flat", "pitch": 0, "roof_mat": "flat_membrane", "overhang": 0.4,
            "band_h": 0.0, "band_floors": [],
            "front_wins": [
                {"style": "picture",  "offset_frac": 0.08, "w": 4.2, "h": 2.6, "sill": 0.3},
                {"style": "casement", "offset_frac": 0.55, "w": 2.0, "h": 2.2, "sill": 0.5},
            ],
            "upper_wins": [
                {"style": "picture",  "offset_frac": 0.08, "w": 5.0, "h": 2.0, "sill": 0.5},
            ],
            "porches": [{"type": "entry", "depth_m": 3.0, "width_frac": 0.4}],
        },
        "adu_compact": {
            "intent": "ADU Compact — small efficient unit, fiber cement, flat roof",
            "w": 9.0, "d": 10.5, "fh": 2.9,
            "shape": "rectangle",
            "mat": "fiber_cement", "trim": "#4a6a8a", "frame": "#1a2a3a", "door_c": "#2a3a2a",
            "roof_type": "flat", "pitch": 0, "roof_mat": "flat_membrane", "overhang": 0.25,
            "band_h": 0.12, "band_floors": [0],
            "front_wins": [
                {"style": "casement", "offset_frac": 0.12, "w": 1.4, "h": 1.5, "sill": 0.9},
                {"style": "casement", "offset_frac": 0.60, "w": 1.4, "h": 1.5, "sill": 0.9},
            ],
            "upper_wins": [
                {"style": "casement", "offset_frac": 0.20, "w": 1.2, "h": 1.2, "sill": 0.9},
                {"style": "casement", "offset_frac": 0.65, "w": 1.2, "h": 1.2, "sill": 0.9},
            ],
            "porches": [],
        },
        "production_tract": {
            "intent": "Production Tract — classic suburban gabled SFR, stucco & brick",
            "w": 12.5, "d": 14.0, "fh": 3.0,
            "shape": "rectangle",
            "mat": "stucco", "trim": "#f0ece0", "frame": "#3a3030", "door_c": "#5a3820",
            "roof_type": "gabled", "pitch": 6, "roof_mat": "asphalt_shingle", "overhang": 0.5,
            "band_h": 0.0, "band_floors": [],
            "front_wins": [
                {"style": "double_hung", "offset_frac": 0.12, "w": 1.1, "h": 1.3, "sill": 0.9},
                {"style": "double_hung", "offset_frac": 0.65, "w": 1.1, "h": 1.3, "sill": 0.9},
            ],
            "upper_wins": [
                {"style": "double_hung", "offset_frac": 0.15, "w": 1.0, "h": 1.2, "sill": 0.9},
                {"style": "double_hung", "offset_frac": 0.65, "w": 1.0, "h": 1.2, "sill": 0.9},
            ],
            "porches": [{"type": "entry", "depth_m": 1.5, "width_frac": 0.45}],
        },
        "prefab_modern": {
            "intent": "Prefab Modern — wide shallow metal panel, flat roof, minimal",
            "w": 13.0, "d": 8.5, "fh": 2.85,
            "shape": "wide_shallow",
            "mat": "metal_panel", "trim": "#aaaaaa", "frame": "#222222", "door_c": "#111111",
            "roof_type": "flat", "pitch": 0, "roof_mat": "flat_membrane", "overhang": 0.2,
            "band_h": 0.10, "band_floors": [0, 1],
            "front_wins": [
                {"style": "strip_horizontal", "offset_frac": 0.06, "w": 9.0, "h": 1.0, "sill": 1.5},
            ],
            "upper_wins": [
                {"style": "strip_horizontal", "offset_frac": 0.06, "w": 9.0, "h": 0.9, "sill": 1.4},
            ],
            "porches": [],
        },
    }

    p = PRESETS.get(archetype_id, PRESETS["production_tract"])
    w, d, fh = p["w"], p["d"], p["fh"]

    # Rescale footprint to hit target_sqft if it's set and we're more than 10% off
    if target_sqft > 0:
        actual = w * d * stories * 10.764
        ratio  = target_sqft / max(actual, 1)
        if ratio < 0.90 or ratio > 1.10:
            scale = _math.sqrt(ratio)
            w = round(w * scale, 2)
            d = round(d * scale, 2)

    def make_floor(fl: int) -> tuple:
        ws = [
            {"id": f"f{fl}_front", "floor": fl, "start": [0, 0],   "end": [w, 0],   "height_m": fh, "thickness_m": 0.15, "exterior": True,  "material": p["mat"]},
            {"id": f"f{fl}_right", "floor": fl, "start": [w, 0],   "end": [w, d],   "height_m": fh, "thickness_m": 0.15, "exterior": True,  "material": p["mat"]},
            {"id": f"f{fl}_back",  "floor": fl, "start": [w, d],   "end": [0, d],   "height_m": fh, "thickness_m": 0.15, "exterior": True,  "material": p["mat"]},
            {"id": f"f{fl}_left",  "floor": fl, "start": [0, d],   "end": [0, 0],   "height_m": fh, "thickness_m": 0.15, "exterior": True,  "material": p["mat"]},
        ]
        ops = []
        win_list = p["front_wins"] if fl == 0 else p["upper_wins"]
        for i, wc in enumerate(win_list):
            offset = wc["offset_frac"] * w
            if offset + wc["w"] >= w - 0.2:
                continue
            ops.append({
                "id": f"win_f{fl}_{i}",
                "wall_id": f"f{fl}_front",
                "type": "window",
                "style": wc["style"],
                "offset_m": round(offset, 2),
                "width_m":  wc["w"],
                "height_m": wc["h"],
                "sill_m":   wc["sill"],
            })
        if fl == 0:
            door_offset = max(0.3, w * 0.82)
            if door_offset + 1.05 < w:
                ops.append({
                    "id": "door_main", "wall_id": "f0_front",
                    "type": "door", "style": "paneled",
                    "offset_m": round(door_offset, 2), "width_m": 1.05, "height_m": 2.1, "sill_m": 0.0,
                })
        return ws, ops

    walls, openings = [], []
    for fl in range(stories):
        fw, fo = make_floor(fl)
        walls.extend(fw); openings.extend(fo)

    porches = []
    for pc in p.get("porches", []):
        porches.append({
            "type":    pc["type"],
            "floor":   0,
            "depth_m": pc["depth_m"],
            "width_m": round(w * pc["width_frac"], 1),
            "wall_id": "f0_front",
        })

    return {
        "style_intent": p["intent"],
        "archetype_id": archetype_id,
        "footprint":    {"width_m": w, "depth_m": d, "shape": p["shape"], "offset_x": 0, "offset_z": 0},
        "floors":       [{"level": i, "height_m": fh} for i in range(stories)],
        "walls":        walls,
        "openings":     openings,
        "porches":      porches,
        "roof": {
            "type": p["roof_type"], "pitch_12": p["pitch"],
            "material": p["roof_mat"], "overhang_m": p["overhang"],
            "parapet_height_m": 0.6,
        },
        "trim": {
            "cornice_height_m": 0.2,
            "band_height_m":    p["band_h"],
            "band_at_floor":    p["band_floors"],
            "trim_color":       p["trim"],
        },
        "materials": {
            "wall_body":          p["mat"],
            "trim_color":         p["trim"],
            "window_frame_color": p["frame"],
            "door_color":         p["door_c"],
            "roof":               p["roof_mat"],
        },
        "_source": "fallback-archetype",
    }
