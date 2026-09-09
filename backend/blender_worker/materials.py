"""
element_type / system -> Principled BSDF material lookup.
Materials are cached by name so repeated calls reuse the same bpy.types.Material.
"""
import bpy

_CACHE: dict = {}

# Architecture/structure element_type colors — these keys match the real
# element_type strings massing.py/facade.py emit (verified against those files).
ELEMENT_TYPE_COLORS = {
    "wall": (0.71, 0.55, 0.35),
    "roof": (0.35, 0.28, 0.24),
    "door": (0.42, 0.28, 0.16),
    "window": (0.55, 0.70, 0.75),
    "porch": (0.55, 0.42, 0.30),
    "floor": (0.62, 0.55, 0.48),
    "column": (0.55, 0.55, 0.55),
    "beam": (0.55, 0.55, 0.55),
    "fixture": (0.80, 0.80, 0.78),
}

# MEP system-level fallback — real-world trade color conventions, so distinct
# systems read as distinct systems (a "grid") instead of one uniform gray blob.
# This is the primary color source for MEP runs/points: mep.py's actual `type`
# vocabulary (cold_supply, feeder, conduit_branch, fire_riser, ...) is far more
# specific than any small lookup table could enumerate, so system is the
# reliable key — type-level overrides below only cover the few conventions
# worth calling out individually.
SYSTEM_COLORS = {
    "plumbing":   (0.55, 0.58, 0.62),   # copper/galvanized default
    "electrical": (0.12, 0.12, 0.13),   # black conduit/EMT
    "hvac":       (0.68, 0.70, 0.72),   # galvanized sheet metal
    "fire":       (0.72, 0.08, 0.08),   # NFPA fire-protection red
    "fixtures":   (0.80, 0.80, 0.78),
}

# Specific type-level overrides where a real convention is iconic enough to be
# worth breaking out of the system default (hot/cold water being the big one).
TYPE_OVERRIDES = {
    "cold_supply":       (0.20, 0.45, 0.80),   # blue
    "cold_water_riser":  (0.20, 0.45, 0.80),
    "hot_supply":        (0.80, 0.25, 0.15),   # red/orange
    "hot_water_riser":   (0.80, 0.25, 0.15),
    "waste_branch":      (0.25, 0.25, 0.27),   # cast iron / ABS black
    "soil_stack":        (0.25, 0.25, 0.27),
    "vent_branch":       (0.55, 0.58, 0.62),
    "sewer_lateral":     (0.25, 0.25, 0.27),
    "refrigerant_line":  (0.72, 0.45, 0.20),   # insulated copper
    "refrigerant_riser": (0.72, 0.45, 0.20),
    "sprinkler":         (0.85, 0.85, 0.82),   # the fixture head itself, not the pipe
    "sub_panel":         (0.25, 0.25, 0.27),
    "panel":             (0.25, 0.25, 0.27),
}

GLASS_TYPES = {"window"}


def _hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return (0.7, 0.7, 0.7)
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return (r, g, b)


def _resolve_color(element_type: str, color: str, system: str) -> tuple:
    if color:
        return _hex_to_rgb(color)
    if element_type in TYPE_OVERRIDES:
        return TYPE_OVERRIDES[element_type]
    if system in SYSTEM_COLORS:
        return SYSTEM_COLORS[system]
    if element_type in ELEMENT_TYPE_COLORS:
        return ELEMENT_TYPE_COLORS[element_type]
    return (0.7, 0.7, 0.7)


def get_material(element_type: str, color: str = None, system: str = None,
                  roughness: float = 0.6) -> "bpy.types.Material":
    key = f"{element_type}:{color or ''}:{system or ''}"
    if key in _CACHE:
        return _CACHE[key]

    rgb = _resolve_color(element_type, color, system)

    mat = bpy.data.materials.new(name=key[:60])
    # Materials have an active node_tree with a Principled BSDF by default in this
    # Blender version — `use_nodes` is deprecated for removal, so don't set it.
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
        if element_type in GLASS_TYPES and "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = 0.9
            bsdf.inputs["Roughness"].default_value = 0.05
            if "IOR" in bsdf.inputs:
                bsdf.inputs["IOR"].default_value = 1.45

    _CACHE[key] = mat
    return mat


def reset_cache():
    _CACHE.clear()
