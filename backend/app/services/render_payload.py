"""
Builds the minimal JSON contract the Blender render worker (backend/blender_worker/)
consumes — pure Python, no bpy dependency, so it's testable with the normal Python
3.11 pytest suite and doesn't need to live inside the 3.13-only worker.

LAYER_KEY_MAP is the single source of truth mapping this app's element_type/system
vocabulary (confirmed against app/generators/massing.py, facade.py, mep.py) to the
frontend's LayerKey categories (frontend/src/lib/store.ts). Keep both in sync if
either side adds a new category.
"""
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from app.models.schemas import BuildingModel

FT_TO_M = 0.3048

# Mesh element_type -> LayerKey. Debug/site-overlay mesh types (footprint outline,
# terrain patch, red neighbor-overlap warning) aren't real building geometry and are
# skipped entirely — they're editor visual aids, not part of the building itself.
#
# The opaque outer shell lives on its own "shell" layer rather than under
# "architecture". Grouping it with the interior meant the viewer's see-through
# toggle could only fade the shell by also fading every interior wall, door and
# window to 18% opacity — so the edited plan was either invisible inside a solid
# box or an unreadable haze of overlapping ghosts. Nothing the user drew in 2D
# could be seen in the render, which is why it looked like the house ignored the
# blueprint entirely.
MESH_LAYER_MAP: Dict[str, str] = {
    "massing": "shell",
    "floor_band": "shell",
    "setback_ledge": "shell",
    "parapet": "shell",
    "window": "architecture",
    "window_frame": "architecture",
    "door": "architecture",
    "door_frame": "architecture",
    "garage_door": "architecture",
    "porch": "architecture",
    "balcony": "architecture",
    "balcony_rail": "architecture",
    "roof": "roof",
}
SKIPPED_MESH_TYPES = {"footprint_ok", "terrain", "overlap"}

# MEPElement.system -> LayerKey (direct match; "fire" and "fixtures" are already
# valid LayerKey values, "fixtures" also covers furniture emitted under that system).
MEP_SYSTEM_LAYER_MAP: Dict[str, str] = {
    "plumbing": "plumbing",
    "electrical": "electrical",
    "hvac": "hvac",
    "fire": "fire",
    "fixtures": "fixtures",
}


# MEPElement types that are schedule/records rather than physical devices —
# app/generators/mep.py emits one "branch_circuit" per breaker, positioned at
# the panel, purely so compliance can audit the circuit schedule. They are not
# objects in space: rendering them stacked every panel location with a blob of
# geometry. They stay in model.mep_elements for compliance; they just never
# become geometry.
NON_GEOMETRIC_MEP_TYPES = {"branch_circuit"}


def _mesh_layer(element_type: str) -> str:
    return MESH_LAYER_MAP.get(element_type, "architecture")


def _mep_layer(system: str) -> str:
    return MEP_SYSTEM_LAYER_MAP.get(system, "fixtures")


def group_mep_runs(elements: List[Any]) -> Tuple[List[dict], List[dict]]:
    """Reconstructs continuous polylines from route_parent_id-chained MEPElement
    segments (written by app/generators/mep.py:_contain_and_reroute) and separates
    out true point fixtures (end is None). Returns (runs, points)."""
    by_parent: Dict[str, list] = defaultdict(list)
    points: List[dict] = []

    for e in elements:
        if e.type in NON_GEOMETRIC_MEP_TYPES:
            continue
        meta = e.metadata or {}
        parent_id = meta.get("route_parent_id")
        if e.end is None:
            points.append({
                "id": e.id, "system": e.system, "type": e.type,
                "layer": _mep_layer(e.system),
                "level": e.level, "position": e.start,
                # Yaw of the host wall's inward normal. Dropping it here left
                # place_fixture with nothing but a location, so every outlet,
                # switch and panel in the GLB was axis-aligned regardless of
                # the wall it belonged to.
                "rotation_deg": e.rotation_deg,
                "metadata": meta,
            })
        elif parent_id:
            by_parent[parent_id].append(e)
        else:
            # Single-segment run with no chaining metadata — still a valid 2-point run.
            by_parent[e.id].append(e)

    runs: List[dict] = []
    for parent_id, segs in by_parent.items():
        segs.sort(key=lambda s: (s.metadata or {}).get("route_segment", 0))
        polyline = [segs[0].start] + [s.end for s in segs]
        first = segs[0]
        runs.append({
            "parent_id": parent_id,
            "system": first.system,
            "type": first.type,
            "layer": _mep_layer(first.system),
            "diameter_in": first.diameter_in,
            "width_in": first.width_in,
            "height_in": first.height_in,
            "polyline": polyline,
        })
    return runs, points


def build_render_payload(model: BuildingModel) -> Dict[str, Any]:
    meshes: List[dict] = []

    chosen = model.massing_options[model.chosen_massing_index] if model.massing_options else None
    if chosen:
        for m in chosen.get("meshes", []):
            if m.get("element_type") in SKIPPED_MESH_TYPES:
                continue
            meshes.append({**m, "layer": _mesh_layer(m.get("element_type", ""))})

    for m in model.meshes:
        if m.get("element_type") in SKIPPED_MESH_TYPES:
            continue
        meshes.append({**m, "layer": _mesh_layer(m.get("element_type", ""))})

    rooms = [{"id": r.id, "level": r.level, "polygon": r.polygon} for r in model.rooms]
    # Interior walls only. Every exterior footprint edge was previously drawn
    # three times over — once by the massing shell, once as a 0.15 m extruded
    # wall box centred on the same line, and once more by the facade meshes,
    # which synthesise their own exterior from the massing footprint. That is
    # guaranteed z-fighting on every outside surface plus ~3x the triangles.
    # The shell and facade own the exterior; walls own the interior.
    walls = [
        {"id": w.id, "level": w.level, "start": w.start, "end": w.end, "height_ft": w.height_ft}
        # Open boundaries are cased openings, not built walls — extruding them
        # would wall an open-plan house back up in 3D.
        for w in model.walls if not w.is_exterior and not w.is_open
    ]
    mep_runs, mep_points = group_mep_runs(model.mep_elements)

    levels = [
        {"index": lvl.index, "elevation_ft": lvl.elevation_ft, "height_ft": lvl.height_ft}
        for lvl in model.levels
    ]

    return {
        "meshes": meshes,
        "rooms": rooms,
        "walls": walls,
        "mep_runs": mep_runs,
        "mep_points": mep_points,
        "levels": levels,
        "units": "meters",
    }
