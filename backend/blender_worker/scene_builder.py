"""
Assembles the full bpy scene from a render payload (see app/services/render_payload.py
for the exact JSON contract this expects). Every object is named f"{layer}_{type}_{id}"
and linked into a Collection named identically to its layer, matching the frontend's
LayerKey categories — that's what lets the frontend recover per-category visibility
toggling from glTF node names after export.
"""
import bmesh
import bpy

import fixture_library
import mep_sweep
from coords import to_blender_all
from materials import get_material

FT_TO_M = 0.3048
WALL_THICKNESS_M = 0.15
FLOOR_THICKNESS_M = 0.12

LAYER_NAMES = [
    "shell", "architecture", "floors", "structure", "roof",
    "plumbing", "electrical", "hvac", "fire", "fixtures",
]


def _recalc_outward_normals(mesh: "bpy.types.Mesh") -> None:
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()


def _get_or_create_collection(name: str) -> "bpy.types.Collection":
    existing = bpy.data.collections.get(name)
    if existing:
        return existing
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    return coll


def _exclude_from_view_layer(collection_name: str) -> None:
    """Belt-and-suspenders: fixture templates get explicitly unlinked from this
    collection once built (fixture_library.get_or_build_template), but exclude the
    collection too in case anything is ever left linked in it."""
    for lc in bpy.context.view_layer.layer_collection.children:
        if lc.name == collection_name:
            lc.exclude = True


def import_mesh(mesh_dict: dict, collection: "bpy.types.Collection") -> "bpy.types.Object":
    """Existing Mesh dicts (walls/roof/doors/porches from massing.py/facade.py) already
    arrive as watertight vertex/face triangle data — direct translation, no remodeling."""
    verts = to_blender_all(mesh_dict["vertices"])
    faces = [tuple(f) for f in mesh_dict["faces"]]
    bm = bpy.data.meshes.new(mesh_dict["element_id"])
    bm.from_pydata(verts, [], faces)
    bm.update(calc_edges=True)
    bm.validate()
    name = f'{mesh_dict["layer"]}_{mesh_dict["element_type"]}_{mesh_dict["element_id"]}'
    obj = bpy.data.objects.new(name, bm)
    obj.data.materials.append(get_material(mesh_dict["element_type"], color=mesh_dict.get("color")))
    collection.objects.link(obj)
    return obj


def extrude_room_floor(room: dict, elevation_m: float, collection: "bpy.types.Collection") -> "bpy.types.Object":
    """room['polygon']: list of [x, z] pairs (horizontal plane), closed loop, no
    repeated closing vertex. Winding direction isn't guaranteed by the source, so
    normals are recalculated outward after construction rather than assumed."""
    pts2d = room["polygon"]
    n = len(pts2d)
    if n < 3:
        return None
    # Slabs hang BELOW their level's finished floor, the way a real slab does.
    # Extruding upward put level 1's slabs directly on top of level 0's rooms,
    # so looking down at the building you saw the upper floor's slabs covering
    # the ground-floor plan.
    y0, y1 = elevation_m - FLOOR_THICKNESS_M, elevation_m
    bottom_src = [(x, y0, z) for x, z in pts2d]
    top_src = [(x, y1, z) for x, z in pts2d]
    verts = to_blender_all(bottom_src + top_src)

    faces = [tuple(range(n)), tuple(range(2 * n - 1, n - 1, -1))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))

    bm = bpy.data.meshes.new(f'floor_{room["id"]}')
    bm.from_pydata(verts, [], faces)
    bm.update(calc_edges=True)
    _recalc_outward_normals(bm)
    bm.validate()

    obj = bpy.data.objects.new(f'floors_floor_{room["id"]}', bm)
    obj.data.materials.append(get_material("floor"))
    collection.objects.link(obj)
    return obj


def extrude_wall(wall: dict, elevation_m: float, collection: "bpy.types.Collection") -> "bpy.types.Object":
    """wall['start']/['end']: [x, z] pairs. Box built with explicit, known-correct
    winding (unlike the room polygon, this shape is fully authored here)."""
    import math

    sx, sz = wall["start"]
    ex, ez = wall["end"]
    dx, dz = ex - sx, ez - sz
    length = math.hypot(dx, dz)
    if length < 0.01:
        return None
    ux, uz = dx / length, dz / length
    nx, nz = -uz, ux
    hw = WALL_THICKNESS_M / 2.0

    y0 = elevation_m
    y1 = elevation_m + wall.get("height_ft", 9.0) * FT_TO_M

    p1 = (sx - nx * hw, y0, sz - nz * hw)
    p2 = (ex - nx * hw, y0, ez - nz * hw)
    p3 = (ex + nx * hw, y0, ez + nz * hw)
    p4 = (sx + nx * hw, y0, sz + nz * hw)
    p5 = (sx - nx * hw, y1, sz - nz * hw)
    p6 = (ex - nx * hw, y1, ez - nz * hw)
    p7 = (ex + nx * hw, y1, ez + nz * hw)
    p8 = (sx + nx * hw, y1, sz + nz * hw)

    verts = to_blender_all([p1, p2, p3, p4, p5, p6, p7, p8])
    faces = [
        (0, 1, 2), (0, 2, 3),        # bottom
        (4, 6, 5), (4, 7, 6),        # top
        (0, 4, 5), (0, 5, 1),        # side (start-facing normal)
        (1, 5, 6), (1, 6, 2),        # side
        (2, 6, 7), (2, 7, 3),        # side (end-facing normal)
        (3, 7, 4), (3, 4, 0),        # side
    ]
    bm = bpy.data.meshes.new(f'wall_{wall["id"]}')
    bm.from_pydata(verts, [], faces)
    bm.update(calc_edges=True)
    bm.validate()

    layer = "architecture"
    obj = bpy.data.objects.new(f'{layer}_wall_{wall["id"]}', bm)
    obj.data.materials.append(get_material("wall"))
    collection.objects.link(obj)
    return obj


def build_scene(payload: dict) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    fixture_library.reset_cache()
    mep_sweep.reset_cache()

    collections = {name: _get_or_create_collection(name) for name in LAYER_NAMES}
    templates = _get_or_create_collection("_templates")

    levels = {lvl["index"]: lvl for lvl in payload.get("levels", [])}

    def elevation_for(level_idx: int) -> float:
        lvl = levels.get(level_idx)
        return (lvl["elevation_ft"] * FT_TO_M) if lvl else 0.0

    for mesh_dict in payload.get("meshes", []):
        layer = mesh_dict.get("layer", "architecture")
        import_mesh(mesh_dict, collections.get(layer, collections["architecture"]))

    for room in payload.get("rooms", []):
        elevation_m = elevation_for(room.get("level", 0))
        extrude_room_floor(room, elevation_m, collections["floors"])

    for wall in payload.get("walls", []):
        elevation_m = elevation_for(wall.get("level", 0))
        extrude_wall(wall, elevation_m, collections["architecture"])

    for run in payload.get("mep_runs", []):
        layer = run.get("layer", "plumbing")
        mep_sweep.build_mep_run(run, collections.get(layer, collections["plumbing"]))

    for point in payload.get("mep_points", []):
        layer = point.get("layer", "fixtures")
        fixture_library.place_fixture(point, collections.get(layer, collections["fixtures"]), templates)

    _exclude_from_view_layer("_templates")
