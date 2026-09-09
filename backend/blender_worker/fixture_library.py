"""
Procedural MEP fixture models — built once from bpy primitives, then instanced via
linked duplicates (shared mesh data) everywhere they're placed. No external asset
files: matches this codebase's existing "everything is generated" philosophy and
keeps the worker fully self-contained.

Any mep_points[].type not covered here falls back to a small sphere (today's
"just a dot" behavior) rather than silently dropping the fixture.
"""
import math

import bpy
from materials import get_material
from coords import to_blender

_TEMPLATE_CACHE: dict = {}


def _new_object(name: str, mesh: "bpy.types.Mesh") -> "bpy.types.Object":
    return bpy.data.objects.new(name, mesh)


def _link_bmesh_from_primitive(op_result_obj: "bpy.types.Object", helper_collection) -> "bpy.types.Object":
    """bpy primitive ops (mesh.primitive_*) link into the active collection automatically —
    move the created object into our own untracked helper collection and unlink from
    wherever the op put it, so template objects never end up in an export layer."""
    for coll in list(op_result_obj.users_collection):
        coll.objects.unlink(op_result_obj)
    helper_collection.objects.link(op_result_obj)
    return op_result_obj


def _add_bevel(obj: "bpy.types.Object", width: float = 0.08, segments: int = 2) -> None:
    """Rounds off sharp cube edges cheaply via Blender's native Bevel modifier —
    the 'sleek power-bank, not a bare digital box' look — instead of hand-rolling
    chamfer vertex math. `width` is in the object's LOCAL space (these primitives
    are all built on a 1-unit cube, so ~0.08 stays proportional after each part's
    own non-uniform object-level scale is applied). Left as a live modifier
    (not baked here) — the worker's final glTF export already runs with
    export_apply=True, which bakes every modifier at that point."""
    mod = obj.modifiers.new(name="Bevel", type='BEVEL')
    mod.width = width
    mod.segments = segments
    mod.limit_method = 'ANGLE'
    mod.angle_limit = 0.7853981  # 45°, so flat coplanar edges from the join don't get beveled too


def build_sprinkler(helper_collection) -> "bpy.types.Object":
    bpy.ops.mesh.primitive_cylinder_add(radius=0.035, depth=0.012, vertices=12)
    disc = bpy.context.active_object
    disc.name = "_tmpl_sprinkler"
    _link_bmesh_from_primitive(disc, helper_collection)
    disc.data.materials.append(get_material("sprinkler"))

    # Two thin deflector bars, joined into the disc mesh so the whole fixture is one object.
    bpy.ops.mesh.primitive_cube_add(size=1)
    bar1 = bpy.context.active_object
    bar1.scale = (0.05, 0.006, 0.006)
    bar1.location = (0, 0, -0.012)
    _link_bmesh_from_primitive(bar1, helper_collection)

    bpy.ops.mesh.primitive_cube_add(size=1)
    bar2 = bpy.context.active_object
    bar2.scale = (0.006, 0.05, 0.006)
    bar2.location = (0, 0, -0.012)
    _link_bmesh_from_primitive(bar2, helper_collection)

    bpy.ops.object.select_all(action='DESELECT')
    for o in (disc, bar1, bar2):
        o.select_set(True)
    bpy.context.view_layer.objects.active = disc
    bpy.ops.object.join()
    return disc


def build_smoke_alarm(helper_collection) -> "bpy.types.Object":
    bpy.ops.mesh.primitive_cylinder_add(radius=0.055, depth=0.02, vertices=16)
    base = bpy.context.active_object
    base.name = "_tmpl_smoke_alarm"
    _link_bmesh_from_primitive(base, helper_collection)
    base.data.materials.append(get_material("fixture", color="#f5f5f0"))

    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.02, segments=12, ring_count=6)
    dome = bpy.context.active_object
    dome.location = (0, 0, 0.015)
    dome.scale.z = 0.5
    _link_bmesh_from_primitive(dome, helper_collection)

    bpy.ops.object.select_all(action='DESELECT')
    for o in (base, dome):
        o.select_set(True)
    bpy.context.view_layer.objects.active = base
    bpy.ops.object.join()
    return base


def build_outlet(helper_collection) -> "bpy.types.Object":
    bpy.ops.mesh.primitive_cube_add(size=1)
    plate = bpy.context.active_object
    plate.name = "_tmpl_outlet"
    plate.scale = (0.07, 0.01, 0.11)
    _link_bmesh_from_primitive(plate, helper_collection)
    plate.data.materials.append(get_material("fixture", color="#e8e4da"))
    _add_bevel(plate)
    return plate


def build_light_switch(helper_collection) -> "bpy.types.Object":
    bpy.ops.mesh.primitive_cube_add(size=1)
    plate = bpy.context.active_object
    plate.name = "_tmpl_switch"
    plate.scale = (0.06, 0.01, 0.10)
    _link_bmesh_from_primitive(plate, helper_collection)
    plate.data.materials.append(get_material("fixture", color="#e8e4da"))

    bpy.ops.mesh.primitive_cube_add(size=1)
    toggle = bpy.context.active_object
    toggle.scale = (0.015, 0.012, 0.03)
    toggle.location = (0, -0.012, 0)
    _link_bmesh_from_primitive(toggle, helper_collection)

    bpy.ops.object.select_all(action='DESELECT')
    for o in (plate, toggle):
        o.select_set(True)
    bpy.context.view_layer.objects.active = plate
    bpy.ops.object.join()
    _add_bevel(plate)
    return plate


def build_sub_panel(helper_collection) -> "bpy.types.Object":
    bpy.ops.mesh.primitive_cube_add(size=1)
    door = bpy.context.active_object
    door.name = "_tmpl_panel"
    door.scale = (0.4, 0.12, 0.6)
    _link_bmesh_from_primitive(door, helper_collection)
    door.data.materials.append(get_material("panel"))

    bpy.ops.mesh.primitive_cylinder_add(radius=0.015, depth=0.05, vertices=8)
    handle = bpy.context.active_object
    handle.rotation_euler = (1.5708, 0, 0)
    handle.location = (0.15, -0.06, 0)
    _link_bmesh_from_primitive(handle, helper_collection)

    bpy.ops.object.select_all(action='DESELECT')
    for o in (door, handle):
        o.select_set(True)
    bpy.context.view_layer.objects.active = door
    bpy.ops.object.join()
    _add_bevel(door, width=0.05)
    return door


def build_diffuser(helper_collection) -> "bpy.types.Object":
    bpy.ops.mesh.primitive_cube_add(size=1)
    frame = bpy.context.active_object
    frame.name = "_tmpl_diffuser"
    frame.scale = (0.3, 0.3, 0.02)
    _link_bmesh_from_primitive(frame, helper_collection)
    frame.data.materials.append(get_material("fixture", color="#d8d8d4"))

    bars = [frame]
    for i in range(5):
        bpy.ops.mesh.primitive_cube_add(size=1)
        bar = bpy.context.active_object
        bar.scale = (0.28, 0.015, 0.01)
        bar.location = (0, -0.12 + i * 0.06, 0.015)
        _link_bmesh_from_primitive(bar, helper_collection)
        bars.append(bar)

    bpy.ops.object.select_all(action='DESELECT')
    for o in bars:
        o.select_set(True)
    bpy.context.view_layer.objects.active = frame
    bpy.ops.object.join()
    return frame


def build_condenser(helper_collection) -> "bpy.types.Object":
    bpy.ops.mesh.primitive_cube_add(size=1)
    body = bpy.context.active_object
    body.name = "_tmpl_condenser"
    body.scale = (0.4, 0.4, 0.45)
    body.location = (0, 0, 0.225)
    _link_bmesh_from_primitive(body, helper_collection)
    body.data.materials.append(get_material("fixture", color="#c9cdd0"))

    bpy.ops.mesh.primitive_torus_add(major_radius=0.15, minor_radius=0.015, major_segments=16, minor_segments=6)
    fan_ring = bpy.context.active_object
    fan_ring.location = (0, 0, 0.45)
    _link_bmesh_from_primitive(fan_ring, helper_collection)

    bpy.ops.object.select_all(action='DESELECT')
    for o in (body, fan_ring):
        o.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    return body


def build_toilet(helper_collection) -> "bpy.types.Object":
    bpy.ops.mesh.primitive_cube_add(size=1)
    tank = bpy.context.active_object
    tank.name = "_tmpl_toilet"
    tank.scale = (0.4, 0.2, 0.35)
    tank.location = (0, -0.2, 0.55)
    _link_bmesh_from_primitive(tank, helper_collection)
    tank.data.materials.append(get_material("fixture", color="#f5f5f2"))

    bpy.ops.mesh.primitive_cylinder_add(radius=0.22, depth=0.35, vertices=16)
    bowl = bpy.context.active_object
    bowl.scale = (1.0, 1.3, 1.0)
    bowl.location = (0, 0.05, 0.2)
    _link_bmesh_from_primitive(bowl, helper_collection)

    bpy.ops.object.select_all(action='DESELECT')
    for o in (tank, bowl):
        o.select_set(True)
    bpy.context.view_layer.objects.active = tank
    bpy.ops.object.join()
    return tank


def build_sink(helper_collection) -> "bpy.types.Object":
    bpy.ops.mesh.primitive_cube_add(size=1)
    basin = bpy.context.active_object
    basin.name = "_tmpl_sink"
    basin.scale = (0.5, 0.4, 0.15)
    basin.location = (0, 0, 0.8)
    _link_bmesh_from_primitive(basin, helper_collection)
    basin.data.materials.append(get_material("fixture", color="#f5f5f2"))

    bpy.ops.mesh.primitive_cylinder_add(radius=0.015, depth=0.2, vertices=8)
    faucet = bpy.context.active_object
    faucet.location = (0, -0.15, 0.95)
    _link_bmesh_from_primitive(faucet, helper_collection)

    bpy.ops.object.select_all(action='DESELECT')
    for o in (basin, faucet):
        o.select_set(True)
    bpy.context.view_layer.objects.active = basin
    bpy.ops.object.join()
    return basin


def build_main_panel(helper_collection) -> "bpy.types.Object":
    """Flush-mounted load center: a real panel is roughly 14x4x20 in
    (0.36 x 0.10 x 0.50 m), not a big featureless cube. Built as a shallow
    recessed can + a slightly proud door with a grip edge, so it reads as an
    electrical panel rather than an anonymous box."""
    bpy.ops.mesh.primitive_cube_add(size=1)
    can = bpy.context.active_object
    can.name = "_tmpl_main_panel"
    can.scale = (0.36, 0.10, 0.50)
    _link_bmesh_from_primitive(can, helper_collection)
    can.data.materials.append(get_material("panel"))

    bpy.ops.mesh.primitive_cube_add(size=1)
    door = bpy.context.active_object
    door.scale = (0.33, 0.015, 0.47)
    door.location = (0, -0.055, 0)
    _link_bmesh_from_primitive(door, helper_collection)

    # Thin vertical grip on the door's leading edge.
    bpy.ops.mesh.primitive_cube_add(size=1)
    grip = bpy.context.active_object
    grip.scale = (0.02, 0.018, 0.12)
    grip.location = (0.13, -0.068, 0)
    _link_bmesh_from_primitive(grip, helper_collection)

    bpy.ops.object.select_all(action='DESELECT')
    for o in (can, door, grip):
        o.select_set(True)
    bpy.context.view_layer.objects.active = can
    bpy.ops.object.join()
    _add_bevel(can, width=0.04)
    return can


def build_recessed_light(helper_collection) -> "bpy.types.Object":
    """Recessed ceiling downlight (~6 in / 0.15 m trim ring), not a floating
    sphere — `lighting_point` had no builder and fell through to the generic
    dot, which is what made ceilings look like they were full of blobs."""
    bpy.ops.mesh.primitive_cylinder_add(radius=0.075, depth=0.02, vertices=16)
    trim = bpy.context.active_object
    trim.name = "_tmpl_lighting_point"
    _link_bmesh_from_primitive(trim, helper_collection)
    trim.data.materials.append(get_material("fixture", color="#f4f1e8"))

    bpy.ops.mesh.primitive_cylinder_add(radius=0.055, depth=0.008, vertices=16)
    lens = bpy.context.active_object
    lens.location = (0, 0, -0.012)
    _link_bmesh_from_primitive(lens, helper_collection)

    bpy.ops.object.select_all(action='DESELECT')
    for o in (trim, lens):
        o.select_set(True)
    bpy.context.view_layer.objects.active = trim
    bpy.ops.object.join()
    return trim


def build_co_alarm(helper_collection) -> "bpy.types.Object":
    """CO alarm — same disc form factor as the smoke alarm it sits beside."""
    bpy.ops.mesh.primitive_cylinder_add(radius=0.055, depth=0.022, vertices=16)
    body = bpy.context.active_object
    body.name = "_tmpl_co_alarm"
    _link_bmesh_from_primitive(body, helper_collection)
    body.data.materials.append(get_material("fixture", color="#f8fafc"))
    _add_bevel(body, width=0.01)
    return body


def build_generic_dot(helper_collection) -> "bpy.types.Object":
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.04, segments=8, ring_count=6)
    obj = bpy.context.active_object
    obj.name = "_tmpl_generic"
    _link_bmesh_from_primitive(obj, helper_collection)
    obj.data.materials.append(get_material("fixture"))
    return obj


FIXTURE_BUILDERS = {
    "sprinkler": build_sprinkler,
    "smoke_alarm": build_smoke_alarm,
    "outlet": build_outlet,
    "ceiling_outlet": build_outlet,
    "light_switch": build_light_switch,
    "switch": build_light_switch,
    "sub_panel": build_sub_panel,
    "panel": build_sub_panel,
    "main_panel": build_main_panel,
    "lighting_point": build_recessed_light,
    "carbon_monoxide_alarm": build_co_alarm,
    "carbon_monoxide_detector": build_co_alarm,
    "co_detector": build_co_alarm,
    "supply_diffuser": build_diffuser,
    "return_grille": build_diffuser,
    "condenser_unit": build_condenser,
    "toilet": build_toilet,
    "sink": build_sink,
    "kitchen_sink": build_sink,
}


def get_or_build_template(fixture_type: str, helper_collection) -> "bpy.types.Object":
    if fixture_type in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[fixture_type]
    builder = FIXTURE_BUILDERS.get(fixture_type, build_generic_dot)
    template = builder(helper_collection)

    # Bake object-level scale and modifiers into the MESH DATA before caching.
    #
    # Every builder above starts from primitive_cube_add(size=1) — a 1 METRE
    # cube — and sizes it purely with `obj.scale`. But place_fixture instances
    # share only `template.data`; bpy.data.objects.new() gives the new object a
    # fresh transform at scale (1,1,1). So none of that sizing reached the
    # export and every outlet, switch and panel shipped as a 1 m cube.
    # The bevel modifiers were lost the same way: they live on the template
    # object, which is unlinked below and never exported.
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = template
    template.select_set(True)
    for mod in list(template.modifiers):
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except RuntimeError:
            template.modifiers.remove(mod)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    template.select_set(False)

    # bpy.ops.object.join() (used by most builders above) needs the object linked
    # into a real collection in the view layer to work — but the template itself
    # must never appear in the export, only its mesh data (shared by instances via
    # place_fixture). Unlink it here now that construction is done.
    for coll in list(template.users_collection):
        coll.objects.unlink(template)
    _TEMPLATE_CACHE[fixture_type] = template
    return template


def place_fixture(point: dict, target_collection, helper_collection) -> "bpy.types.Object":
    """point: {"id", "type", "layer", "position": [x,y,z], "rotation_deg": float|None}"""
    template = get_or_build_template(point["type"], helper_collection)
    inst = bpy.data.objects.new(f'{point["layer"]}_{point["type"]}_{point["id"]}', template.data)
    inst.location = to_blender(point["position"])
    # Normally a no-op: get_or_build_template bakes scale into the mesh, leaving
    # this at (1,1,1). Kept as a guard so a failed transform_apply degrades to a
    # correctly-sized fixture rather than a 1 m cube.
    inst.scale = template.scale
    # Orient wall-hosted devices to their host wall. Templates are modelled
    # facing -Y in Blender space (the source yaw is measured about +Y in the
    # scene's Y-up frame, where 0 deg faces +Z / Blender -Y), so the object's
    # Z rotation is just the incoming yaw. Without this the thin axis of every
    # faceplate pointed the same way no matter which wall it was on.
    yaw_deg = point.get("rotation_deg")
    if yaw_deg is not None:
        inst.rotation_euler = (0.0, 0.0, math.radians(float(yaw_deg)))
    target_collection.objects.link(inst)
    return inst


def reset_cache():
    _TEMPLATE_CACHE.clear()
