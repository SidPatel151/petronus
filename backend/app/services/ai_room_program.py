"""
ai_room_program.py
Replaces the hardcoded SFR_PROGRAMS lookup tables in floorplan.py.

Workflow:
  1. Load blueprint_index.json (cached in memory after first read)
  2. Find 2-3 blueprints that match the current archetype + sqft range
  3. Build a compact prompt with real footprint dims + examples + platform limits
  4. Ask Claude Haiku for a dynamic room layout in JSON (absolute meters)
  5. Convert Claude's output to the row-dict format floorplan.py expects
  6. On any failure, fall back to None → floorplan.py uses static programs

Token budget per call: ~400 tokens in, ~300 tokens out  ≈ $0.001 (Haiku pricing)
"""
import asyncio
import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.constraints import LIMITS, ARCHETYPE_RULES, limits_for_prompt

_INDEX_PATH  = Path(__file__).parent.parent / "data" / "blueprint_index.json"
_INDEX_CACHE: Optional[List[Dict]] = None   # loaded once, never reloaded mid-run


def _load_index() -> List[Dict]:
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        if _INDEX_PATH.exists():
            _INDEX_CACHE = json.loads(_INDEX_PATH.read_text())
        else:
            _INDEX_CACHE = []
    return _INDEX_CACHE


def _find_examples(archetype_id: str, bedrooms: int, target_sqft: float, n: int = 2) -> List[Dict]:
    """Return up to n blueprints from the index that best match this job.

    Strategy: archetype-matched blueprints always win. Only fall back to
    non-matching archetypes if there aren't enough archetype matches.
    """
    index = _load_index()
    if not index:
        return []

    def _score(bp: dict, primary: bool) -> float:
        score = 100.0 if primary else 0.0  # archetype match = decisive
        if bp.get("building_type") in ("sfr", "townhouse", "victorian"):
            score += 1.0
        bp_br = bp.get("bedrooms") or 0
        if bp_br == bedrooms:
            score += 4.0
        elif abs((bp_br or 0) - bedrooms) <= 1:
            score += 2.0
        bp_sqft = bp.get("total_sqft") or 0
        if bp_sqft and target_sqft:
            ratio = min(bp_sqft, target_sqft) / max(bp_sqft, target_sqft)
            score += ratio * 3.0
        score += bp.get("confidence", 0.0) * 2
        # Prioritise floor plans — exterior photos lack room data
        if bp.get("image_type") == "floor_plan":
            score += 2.0
        elif bp.get("image_type") == "sketch":
            score += 1.0
        # Penalise entries with no room data
        if not bp.get("rooms"):
            score -= 3.0
        return score

    archetype_pool = [bp for bp in index if bp.get("archetype") == archetype_id]
    fallback_pool  = [bp for bp in index if bp.get("archetype") != archetype_id]

    ranked_primary  = sorted(archetype_pool, key=lambda bp: _score(bp, True),  reverse=True)
    ranked_fallback = sorted(fallback_pool,  key=lambda bp: _score(bp, False), reverse=True)

    results = ranked_primary[:n]
    if len(results) < n:
        results += ranked_fallback[: n - len(results)]
    return results


def _bp_to_compact(bp: dict) -> str:
    """Convert a blueprint index entry to a compact multi-line string for the prompt."""
    sqft  = bp.get("total_sqft", "?")
    br    = bp.get("bedrooms", "?")
    fp    = bp.get("footprint_ft") or {}
    dims  = f"{fp.get('width','?')}×{fp.get('depth','?')}ft" if fp else "unknown dims"
    style = bp.get("style", "")
    header = f"[{bp.get('archetype','?')} | {br}BR | {sqft} sqft | {dims} | {style}]"

    rooms_by_floor: Dict[int, List[str]] = {}
    for r in bp.get("rooms", []):
        f = r.get("floor", 0)
        entry = r["type"]
        if r.get("approx_sqft"):
            entry += f"({r['approx_sqft']}sf)"
        if r.get("position"):
            entry += f"@{r['position']}"
        rooms_by_floor.setdefault(f, []).append(entry)

    lines = [header]
    for fl in sorted(rooms_by_floor):
        lines.append(f"  F{fl}: {', '.join(rooms_by_floor[fl])}")
    stair = bp.get("stair") or {}
    if stair.get("present"):
        lines.append(f"  Stair: {stair.get('location','?')} → {stair.get('direction','?')}")
    if bp.get("wet_wall_location"):
        lines.append(f"  Wet wall: {bp['wet_wall_location']}")
    return "\n".join(lines)


def _archetype_layout_brief(arch: Optional[Dict]) -> str:
    """
    Compact per-floor layout reference extracted from archetype JSON.
    Tells Claude EXACTLY what rooms go on each floor, where the wet wall
    and stair live, and the 2-3 most critical MEP constraints.
    """
    if not arch:
        return ""
    lines = [f"ARCHETYPE LAYOUT REFERENCE — {arch.get('display_name', '')}:"]

    # Per-floor room lists
    fp = arch.get("floor_program", {})
    if fp:
        floor_order = [k for k in fp if k not in ("note",)]
        for key in floor_order:
            fl = fp[key]
            if not isinstance(fl, dict):
                continue
            use   = fl.get("use", "")
            rooms = fl.get("rooms", [])
            note  = fl.get("mep_note", "")
            label = key.replace("_", " ").title()
            room_str = ", ".join(rooms[:10]) if rooms else "(see note)"
            lines.append(f"  {label} ({use}): {room_str}")
            if note:
                lines.append(f"    MEP: {note[:120]}")

    # Per-variant bedroom programs, where an archetype declares them
    bp = arch.get("bedroom_programs", {})
    if bp:
        lines.append("  Bedroom program variants:")
        for prog_name, prog in bp.items():
            if not isinstance(prog, dict):
                continue
            br  = prog.get("bedrooms", "?")
            sqft = prog.get("target_sqft", "?")
            st  = prog.get("stories", 1)
            lines.append(f"    {prog_name}: {br}BR, {sqft} sqft, {st} story")

    # Wet wall location
    ww = arch.get("wet_wall", {})
    if ww.get("location"):
        loc = ww["location"]
        note = ww.get("note", "")[:80]
        lines.append(f"  Wet wall: {loc}" + (f" — {note}" if note else ""))

    # Stair location
    sc = arch.get("staircase", {})
    if sc.get("location"):
        lines.append(f"  Stair: {sc['location']} (width {sc.get('width_ft','?')} ft, runs {sc.get('run_direction','?')})")

    # Massing hints
    mh = arch.get("massing_hints", {})
    if mh.get("plan_shape"):
        ratio = mh.get("width_to_depth_ratio_typical", "")
        lines.append(f"  Plan shape: {mh['plan_shape']}" + (f" (W:D ≈ {ratio})" if ratio else ""))
    if mh.get("roof_type"):
        lines.append(f"  Roof: {mh['roof_type']}")

    # Top 4 known constraints
    kcs = arch.get("known_constraints_summary", [])
    if kcs:
        lines.append("  Key constraints:")
        for kc in kcs[:4]:
            lines.append(f"    • {kc[:110]}")

    return "\n".join(lines)


def _get_api_key() -> str:
    try:
        from app.core.config import settings
        return settings.ANTHROPIC_API_KEY
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY", "")


async def get_ai_room_program(
    footprint_w_m: float,
    footprint_d_m: float,
    archetype_id: str,
    bedrooms: int,
    stories: int,
    target_sqft: float,
    site_ctx: Dict[str, Any],
    bathrooms: float = 2.0,
    archetype_data: Optional[Dict] = None,
) -> Optional[List[Dict]]:
    """
    Ask Claude Haiku to generate a room layout for one floor or the whole house.

    Returns a list of per-floor programs:
      [
        {"floor": 0, "rows": [
          {"row_frac_d": 0.35, "rooms": [{"type": "garage", "frac_w": 0.55}, ...]},
          ...
        ]},
        {"floor": 1, "rows": [...]},
      ]
    Returns None on failure → caller falls back to static programs.
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    # Gather terrain/site signals for context
    terrain      = site_ctx.get("terrain", {}) or {}
    slope_pct    = terrain.get("slope_pct", 0)
    avg_elev_m   = terrain.get("avg_elevation_m", 0)
    municipality = terrain.get("municipality", "") or site_ctx.get("municipality", "")
    weather      = site_ctx.get("weather", {}) or {}
    climate_zone = weather.get("climate_zone", "unknown") if weather else "unknown"
    temp_f       = weather.get("temp_f") if weather else None

    # Find matching blueprint examples
    examples = _find_examples(archetype_id, bedrooms, target_sqft, n=2)
    example_text = "\n\n".join(_bp_to_compact(e) for e in examples) if examples else "No matching blueprints available."

    # Archetype-specific note + layout brief from JSON
    arule = ARCHETYPE_RULES.get(archetype_id)
    archetype_note = arule.note if arule else ""
    arch_layout_brief = _archetype_layout_brief(archetype_data)

    area_m2  = footprint_w_m * footprint_d_m
    area_sqft_fp = area_m2 * 10.764

    # Count full vs half baths
    full_baths = int(bathrooms)
    half_baths = 1 if (bathrooms - full_baths) >= 0.5 else 0

    prompt = f"""You are an expert residential architect. Generate a room layout JSON for the building below.

{limits_for_prompt()}

THIS BUILDING:
- Archetype: {archetype_id} ({archetype_note[:120] if archetype_note else 'standard'})
- Footprint: {footprint_w_m:.1f}m wide × {footprint_d_m:.1f}m deep (= {area_sqft_fp:.0f} sqft/floor)
- Target total: {target_sqft:.0f} sqft | {stories} stories
- Slope: {slope_pct:.1f}% | Elevation: {avg_elev_m:.0f}m | Location: {municipality or 'unknown'}
- Climate: {climate_zone}{f' ({temp_f:.0f}°F now)' if temp_f else ''}

REFERENCE BLUEPRINTS FROM OUR DATASET:
{example_text}

{arch_layout_brief}

HARD CONSTRAINTS — follow exactly:
- EXACTLY {bedrooms} bedrooms (type="bedroom") across all floors — no more, no less
- EXACTLY {full_baths} full bathrooms (type="bathroom") + {half_baths} half bath (type="half_bath")
- Generate EXACTLY {stories} floor(s): floors numbered 0 through {stories - 1}
- Rooms must fit inside {footprint_w_m:.1f}m × {footprint_d_m:.1f}m footprint
- frac_w values per row must sum to 1.0; row_frac_d values per floor must sum to 1.0
- Minimum widths (meters): bedroom {LIMITS.min_bedroom_w_m}, bath {LIMITS.min_bathroom_w_m}, kitchen {LIMITS.min_kitchen_w_m}, living {LIMITS.min_living_w_m}
- For hillside/slope > 8%: floor 0 = garage+entry+utility, main living on floor 1+; otherwise floor 0 = living/garage, upper floors = bedrooms
- Include stair room on each floor EXCEPT the topmost (floor {stories - 1}) — no staircase on the top floor unless there is an attic above it
- Hillside/mountain: include decks, split levels, view-oriented living spaces
- Do not exceed {LIMITS.sfr_max_bedrooms} bedrooms total
- TOTAL BUILDING AREA MUST NOT EXCEED {min(int(target_sqft), LIMITS.sfr_max_sqft):,} sqft — this is a hard platform cap, never go above it under any circumstances
- Target total area is {target_sqft:.0f} sqft; size rooms so they sum to approximately this, never more than {min(int(target_sqft), LIMITS.sfr_max_sqft):,} sqft

SPATIAL ORDERING — hard rules (rows are ordered front-to-back within each floor):
- Row 1 of floor 0 (front, facing street): foyer, entry, or living room — NEVER stair, garage, or bathroom first
- Row 2 of floor 0: kitchen, dining, family room — public spaces needing natural light
- Middle rows of any floor: stair, hallway, laundry, utility — circulation and service
- Last rows of any floor: bedrooms and bathrooms — private, away from street
- Stair must NOT be the first room from the front door — put foyer or entry before it
- Bathrooms are interior — place them between bedrooms, never on the front facade row
- Each floor must have at least 3 rows so rooms spread front-to-back across the full depth

FLOOR ASSIGNMENT — non-negotiable (match the ARCHETYPE LAYOUT REFERENCE exactly):
- dining room, living room, kitchen MUST be on floor 0 (or the floor the archetype assigns them to)
- bedrooms and bathrooms MUST be on the upper floor(s) — NEVER on floor 0 of a 2-story home
- For 2-story SFR: floor 0 = entry + living + dining + kitchen + half_bath; floor 1 = ALL bedrooms + baths
- Do NOT split dining/kitchen across different floors from living

Return ONLY valid JSON — no markdown, no explanation:
{{
  "floors": [
    {{
      "floor": 0,
      "rows": [
        {{"row_frac_d": 0.35, "rooms": [{{"type": "garage", "frac_w": 0.65}}, {{"type": "entry", "frac_w": 0.35}}]}},
        {{"row_frac_d": 0.65, "rooms": [{{"type": "utility", "frac_w": 0.5}}, {{"type": "laundry", "frac_w": 0.5}}]}}
      ]
    }},
    {{
      "floor": 1,
      "rows": [...]
    }}
  ]
}}

Valid room types: living, kitchen, dining, bedroom, bathroom, foyer, office, pantry,
walk_in_closet, family_room, bonus_room, loft, media_room, library, gym, laundry, corridor,
garage, mechanical, utility, stair, deck, half_bath"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = await asyncio.to_thread(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            # A multi-floor room program runs well past 2,500 tokens; the old
            # cap truncated the response mid-JSON, so json.loads raised
            # "Expecting ',' delimiter" and every request silently fell back
            # to the static SFR_PROGRAMS templates.
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        if getattr(msg, "stop_reason", None) == "max_tokens":
            logging.getLogger(__name__).warning(
                "[ai_room_program] response hit max_tokens and is truncated — "
                "falling back to static programs"
            )
            return None
        raw = msg.content[0].text.strip()
        # Strip markdown fences if present
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                if part.startswith("json"):
                    raw = part[4:].strip()
                    break
                elif part.strip().startswith("{"):
                    raw = part.strip()
                    break
        # Extract just the outermost JSON object (ignore trailing text)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        raw = raw[start:end]
        data = json.loads(raw)
        floors = data.get("floors", [])
        if not floors:
            return None
        # Validate + normalise fractions
        return _enforce_floor_assignment(_normalise(floors), stories, archetype_data)
    except Exception as e:
        logging.getLogger(__name__).error(f"[ai_room_program] failed: {e}", exc_info=True)
        return None


# Room types that belong on the ground floor of a multi-storey house. The
# prompt already states this as non-negotiable, but nothing verified it, so a
# model that answered with a kitchen or living room on floor 1 had it built
# exactly as written — the "why is there a kitchen upstairs" bug.
_GROUND_ONLY_TYPES = {
    "kitchen", "living", "dining", "family_room", "foyer", "entry",
    "mudroom", "pantry", "garage",
}

# The archetype JSONs name rooms in prose ("primary_bedroom", "living_room");
# the generator's vocabulary is narrower. Map one onto the other so
# floor_program can be compared against generated room types.
_ARCHETYPE_ROOM_ALIASES = {
    # Entry / circulation
    "entry_hall": "foyer", "entry": "foyer", "grand_entry": "foyer",
    "entry_atrium_or_foyer": "foyer",
    "hall": "corridor", "hallway": "corridor",
    # Living
    "parlor": "living", "living_room": "living", "great_room": "great_room",
    "sitting_room": "sitting_room", "family": "family_room",
    "dining_room": "dining", "formal_dining": "dining",
    # Kitchen
    "chef_kitchen": "kitchen", "catering_kitchen": "kitchen",
    "butler_pantry": "butler_pantry",
    # Sleeping
    "primary_bedroom": "bedroom", "master_bedroom": "bedroom",
    "guest_bedroom": "bedroom", "primary_suite": "bedroom",
    "closets": "walk_in_closet", "closet": "closet",
    "dressing_room": "dressing_room",
    # Bathrooms. half_bath is not in the generator vocabulary, so a powder
    # room maps to a full bathroom rather than leaking an unknown type.
    "full_bath": "bathroom", "primary_bath": "bathroom", "bath": "bathroom",
    "hall_bath": "bathroom", "ensuite_bath": "bathroom", "spa_bath": "bathroom",
    "half_bath": "bathroom", "powder_room": "bathroom", "powder": "bathroom",
    "guest_powder_room": "bathroom", "pool_bath": "pool_bath",
    # Garage / service. Every "N_car_garage" spelling collapses to garage.
    "2_car_garage": "garage", "3_car_garage": "garage",
    "garage_1_car": "garage", "garage_2_car": "garage",
    "garage_or_bicycle_storage": "garage", "ev_charging_station": "garage",
    "utility_closet": "utility", "mechanical_closet": "mechanical",
    "mechanical_room": "mechanical", "av_it_room": "utility",
    "laundry_closet": "laundry", "laundry_room": "laundry",
    "laundry_utility": "laundry",
    # Work / flex
    "home_office": "office", "study": "office", "office": "office",
    "family_loft": "loft", "flex_loft": "loft", "loft_optional": "loft",
    "flex_room": "office", "bonus": "bonus_room",
    "den": "office", "home_gym": "gym", "steam_room": "sauna",
    "wine_cellar": "wine_cellar", "cinema_room": "cinema_room",
    "media_room": "media_room", "game_room": "game_room",
    # Outdoor
    "outdoor_deck_or_patio": "deck", "deck_or_juliet_balcony": "balcony",
    "roof_deck": "deck", "loggia": "loggia",
    "utility": "utility", "mechanical": "mechanical",
}


def _normalise_archetype_room(name: str) -> Optional[str]:
    """Map an archetype's prose room name onto a type the generator can build.

    Returns None for anything that still isn't in the generator's vocabulary.
    Previously unmapped names were passed through verbatim, so a floor_program
    entry like "2_car_garage" or "primary_suite" became the allowed-set for
    that storey and could be handed straight to the layout as a room type it
    has no width, colour or geometry for."""
    from app.generators.compliance import KNOWN_ROOM_TYPES

    key = str(name).strip().lower().replace(" ", "_")
    mapped = _ARCHETYPE_ROOM_ALIASES.get(key, key)
    return mapped if mapped in KNOWN_ROOM_TYPES else None


def archetype_floor_rooms(archetype: Optional[Dict]) -> Dict[int, set]:
    """Allowed room types per level index, from the archetype's floor_program.

    Every archetype JSON declares exactly which rooms belong on which storey —
    the Victorian, for instance, puts the single kitchen on floor_1 and only
    bedrooms/baths on floor_2. That data was only ever pasted into the prompt as
    advice; nothing checked the result against it. Returns {} when the archetype
    has no usable floor_program, meaning "no constraint".
    """
    if not archetype:
        return {}
    program = archetype.get("floor_program") or {}
    if not isinstance(program, dict):
        return {}

    # Keys are ordered ground → up. "floor_3_optional" and similar suffixes are
    # tolerated; "note" is prose, not a storey.
    ordered = [
        key for key, value in program.items()
        if key != "note" and isinstance(value, dict) and value.get("rooms")
    ]
    out: Dict[int, set] = {}
    for index, key in enumerate(ordered):
        rooms = program[key].get("rooms") or []
        mapped = {_normalise_archetype_room(r) for r in rooms}
        mapped.discard(None)
        if mapped:
            out[index] = mapped
    return out


def _enforce_floor_assignment(
    floors: Optional[List[Dict]], stories: int,
    archetype: Optional[Dict] = None,
) -> Optional[List[Dict]]:
    """Reject or repair programs that put public rooms on an upper floor.

    Repairable case: the type also exists on floor 0, so the upper one is a
    duplicate and becomes a bedroom (or a closet if the slot is too narrow).
    Unrepairable case: the house's ONLY kitchen/living room is upstairs —
    rewriting it would leave the ground floor without one, so the whole program
    is rejected and the caller falls back to the static templates.
    """
    if not floors or stories < 2:
        return floors

    # The archetype's own floor_program is authoritative where it applies. Only
    # trust it when it describes exactly as many storeys as we're building —
    # the Victorian's program covers a 3-4 storey house (garage / living /
    # sleeping / attic), and forcing that onto a 2-storey build would put the
    # bedrooms nowhere.
    by_level = archetype_floor_rooms(archetype)
    if len(by_level) != stories:
        by_level = {}

    # Which floors each room type currently occupies in the model's answer.
    present: Dict[str, set] = {}
    for floor in floors:
        for row in floor["rows"]:
            for room in row["rooms"]:
                present.setdefault(room["type"], set()).add(floor["floor"])

    # Preference order when a misplaced room has to become something else.
    # Ordered by how much floor area the type normally wants, so a big cell
    # becomes a living room rather than, say, the third bathroom in a row —
    # which is what picking alphabetically out of the allowed set produced.
    _PREFER_WIDE = (
        "great_room", "living", "family_room", "kitchen", "dining",
        "bedroom", "office", "bonus_room", "loft", "library", "garage",
    )
    _PREFER_NARROW = (
        "walk_in_closet", "closet", "storage", "pantry", "laundry",
        "bathroom", "utility", "mechanical",
    )

    def _replacement(allowed: Optional[set], frac_w: float) -> str:
        # `allowed` is already filtered to the generator's vocabulary by
        # archetype_floor_rooms, so anything picked here is buildable.
        order = _PREFER_NARROW + _PREFER_WIDE if frac_w < 0.22 else _PREFER_WIDE + _PREFER_NARROW
        if allowed:
            for candidate in order:
                if candidate in allowed:
                    return candidate
            for candidate in sorted(allowed):
                if candidate not in ("corridor", "stair", "hall"):
                    return candidate
        return "bedroom" if frac_w >= 0.22 else "walk_in_closet"

    log = logging.getLogger(__name__)
    for floor in floors:
        level = floor["floor"]
        allowed = by_level.get(level)
        for row in floor["rows"]:
            for room in row["rooms"]:
                room_type = room["type"]
                if allowed is not None:
                    if room_type in allowed:
                        continue
                    correct_levels = {
                        lvl for lvl, types in by_level.items() if room_type in types
                    }
                else:
                    # No usable floor_program: fall back to the generic rule
                    # that public rooms belong on the ground floor.
                    if level == 0 or room_type not in _GROUND_ONLY_TYPES:
                        continue
                    correct_levels = {0}

                # Safe to rewrite only if this type already appears on a floor
                # where it belongs. Otherwise rewriting it would delete the
                # house's only kitchen rather than relocating it.
                if not (present.get(room_type, set()) & correct_levels):
                    log.warning(
                        "[ai_room_program] '%s' appears only on floor %s, which is "
                        "not where it belongs — rejecting program, falling back to "
                        "static templates", room_type, level,
                    )
                    return None
                room["type"] = _replacement(allowed, room["frac_w"])

    # Finally: no two storeys may come back as the same set of rooms. Type
    # enforcement above only relocates rooms that are on the *wrong* floor —
    # it cannot see a model that simply answered with the same program twice,
    # which is the "why is floor 2 identical to floor 1" case. There is no way
    # to invent a distinct upper floor here, so hand back None and let the
    # static templates (which are genuinely different per storey) take over.
    from collections import Counter
    signatures = [
        tuple(sorted(Counter(
            room["type"] for row in floor["rows"] for room in row["rooms"]
        ).items()))
        for floor in floors
    ]
    if len(signatures) > 1 and len(set(signatures)) < len(signatures):
        log.warning(
            "[ai_room_program] two storeys came back with identical room sets — "
            "rejecting program, falling back to static templates"
        )
        return None
    return floors


def _normalise(floors: List[Dict]) -> List[Dict]:
    """
    Ensure frac_w sums to 1.0 per row and row_frac_d sums to 1.0 per floor.
    Clamps any negatives. Returns None if data is unparseable.
    """
    out = []
    for fl in floors:
        rows = fl.get("rows", [])
        if not rows:
            continue
        # Normalise row depths
        total_d = sum(max(r.get("row_frac_d", 0), 0.01) for r in rows) or 1.0
        norm_rows = []
        for row in rows:
            rd = max(row.get("row_frac_d", 0), 0.01) / total_d
            rooms = row.get("rooms", [])
            total_w = sum(max(rm.get("frac_w", 0), 0.01) for rm in rooms) or 1.0
            norm_rooms = [
                {"type": rm.get("type", "corridor"), "frac_w": max(rm.get("frac_w", 0), 0.01) / total_w}
                for rm in rooms
            ]
            norm_rows.append({"row_frac_d": rd, "rooms": norm_rooms})
        # Coerce the floor index to int and keep it unique. floorplan.py keys
        # its lookup by `level.index` (an int), so a model that answered
        # "floor": "1" produced a str key that never matched and that level
        # silently dropped to the static program — one AI floor and one
        # hardcoded floor in the same house. Duplicate indices used to
        # overwrite each other in that dict for the same reason.
        try:
            floor_idx = int(fl.get("floor", len(out)))
        except (TypeError, ValueError):
            floor_idx = len(out)
        if any(o["floor"] == floor_idx for o in out):
            floor_idx = max(o["floor"] for o in out) + 1
        out.append({"floor": floor_idx, "rows": norm_rows})
    return out if out else None


async def get_ai_unit_program(
    footprint_w_m: float,
    footprint_d_m: float,
    stories: int,
    unit_count: Optional[int],
    bedrooms_per_unit: int,
    site_ctx: Dict[str, Any],
    target_sqft: float = 0,
    archetype_data: Optional[Dict] = None,
) -> Optional[Dict]:
    """
    Ask Claude to generate a multi-family unit mix and room templates.

    Returns:
      {
        "unit_mix": {"studio": 0, "1br": 2, "2br": 1, "3br": 0},
        "templates": {
          "1br": {"w": 8.0, "d": 10.0, "rows": [...]},
          "2br": {"w": 10.0, "d": 12.0, "rows": [...]}
        }
      }
    Returns None on failure → caller uses hardcoded UNIT_TEMPLATES.
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    terrain      = site_ctx.get("terrain", {}) or {}
    slope_pct    = terrain.get("slope_pct", 0)
    avg_elev_m   = terrain.get("avg_elevation_m", 0)
    municipality = site_ctx.get("municipality", "") or terrain.get("municipality", "CA")
    seismic      = site_ctx.get("seismic_category", "D")
    weather      = site_ctx.get("weather", {}) or {}
    climate_zone = weather.get("climate_zone", "unknown") if weather else "unknown"

    floor_area_sqft  = footprint_w_m * footprint_d_m * 10.764
    total_sqft_label = f"{target_sqft:.0f}" if target_sqft > 0 else f"≈{floor_area_sqft * stories:.0f}"
    approx_units     = unit_count or max(1, round(footprint_w_m / 8))
    unit_sqft_target = (target_sqft / max(stories, 1) / max(approx_units, 1)) if target_sqft > 0 else (floor_area_sqft / max(approx_units, 1))

    is_steep = slope_pct >= 10.0
    hillside_note = ""
    if is_steep:
        hillside_note = f"""
HILLSIDE DESIGN (slope {slope_pct:.1f}%): This is a steep site. Design accordingly:
- Ground floor (level 0): garage, mechanical, storage, mudroom — these go INTO the hillside
- Upper floors: living spaces, bedrooms, decks on downhill (view) side
- Each unit should have an entry from the uphill street level
- Include deck/balcony room on downhill facade
- Fewer units per floor is better — 1-2 large units rather than 4 small ones"""

    arch_brief = _archetype_layout_brief(archetype_data)

    prompt = f"""You are a licensed residential architect designing a multi-family building.

SITE: {municipality} | slope {slope_pct:.1f}% | elevation {avg_elev_m:.0f}m | seismic {seismic} | climate {climate_zone}
BUILDING: {footprint_w_m:.1f}m wide × {footprint_d_m:.1f}m deep | {stories} stories | {floor_area_sqft:.0f} sqft/floor
TARGET: {total_sqft_label} sqft total | ~{bedrooms_per_unit} BR per unit | each unit ≈{unit_sqft_target:.0f} sqft{f' | {unit_count} units/floor' if unit_count else ''}
{hillside_note}
{arch_brief}

HARD RULES:
- unit_mix values are PER FLOOR (integer count of each unit type on each floor)
- frac_w per row must sum to 1.0; frac_d per template must sum to 1.0
- Include w (width in meters) and d (depth in meters) for each template — these set actual unit size
- Each unit's w × d should give roughly {unit_sqft_target:.0f} sqft (= {unit_sqft_target/10.764:.1f} m²)
- Valid room types: living, kitchen, dining, bedroom, bathroom, half_bath, foyer, office,
  laundry, corridor, garage, mechanical, utility, stair, deck, mudroom, walk_in_closet

Return ONLY valid JSON, no markdown:
{{
  "unit_mix": {{"studio": 0, "1br": 0, "2br": 0, "3br": 1}},
  "templates": {{
    "3br": {{
      "w": 11.0,
      "d": 13.0,
      "rows": [
        {{"frac_d": 0.25, "rooms": [{{"type": "living", "frac_w": 0.6}}, {{"type": "dining", "frac_w": 0.4}}]}},
        {{"frac_d": 0.20, "rooms": [{{"type": "kitchen", "frac_w": 0.55}}, {{"type": "bathroom", "frac_w": 0.45}}]}},
        {{"frac_d": 0.20, "rooms": [{{"type": "laundry", "frac_w": 0.4}}, {{"type": "half_bath", "frac_w": 0.6}}]}},
        {{"frac_d": 0.35, "rooms": [{{"type": "bedroom", "frac_w": 0.38}}, {{"type": "bedroom", "frac_w": 0.32}}, {{"type": "bedroom", "frac_w": 0.30}}]}}
      ]
    }}
  }}
}}"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = await asyncio.to_thread(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            # See get_ai_room_program: 2,500 tokens truncated the unit-template
            # JSON mid-object, so this always fell back to static UNIT_TEMPLATES.
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        if getattr(msg, "stop_reason", None) == "max_tokens":
            logging.getLogger(__name__).warning(
                "[ai_unit_program] response hit max_tokens and is truncated — "
                "falling back to static unit templates"
            )
            return None
        raw = msg.content[0].text.strip()
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                stripped = part.lstrip("json").strip()
                if stripped.startswith("{"):
                    raw = stripped
                    break
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        data = json.loads(raw[start:end])
        if "unit_mix" not in data or "templates" not in data:
            return None
        # Normalise all template rows; preserve w/d from Claude
        for tmpl in data["templates"].values():
            rows = tmpl.get("rows", [])
            total = sum(max(r.get("frac_d", 0), 0.01) for r in rows) or 1.0
            for r in rows:
                r["frac_d"] = max(r.get("frac_d", 0), 0.01) / total
                w_total = sum(max(rm.get("frac_w", 0), 0.01) for rm in r.get("rooms", [])) or 1.0
                for rm in r.get("rooms", []):
                    rm["frac_w"] = max(rm.get("frac_w", 0), 0.01) / w_total
        return data
    except Exception as e:
        logging.getLogger(__name__).error(f"[ai_unit_program] failed: {e}", exc_info=True)
        return None
