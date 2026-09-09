"""
Standalone bpy smoke test — no FastAPI, no orchestrator involvement.
Run directly: venv/bin/python scratch_test.py
Produces test.glb next to this script. Verifies before any real module gets built:
  - a plain triangle mesh imports via from_pydata
  - a round pipe (Bezier + bevel_depth) sweeps smoothly through a bend
  - a rectangular duct (POLY + custom bevel_object profile) keeps a true box cross-section
  - a tiny procedural fixture (stand-in for a sprinkler head) renders as a real shape, not a dot
  - export_scene.gltf produces a loadable GLB
"""
import bpy
import math


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_material(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    return mat


def build_box_mesh(collection):
    """A simple wall-like box, from_pydata — mirrors how real Mesh dicts (vertices/faces) get imported."""
    verts = [
        (0, 0, 0), (2, 0, 0), (2, 0, 3), (0, 0, 3),
        (0, 0.2, 0), (2, 0.2, 0), (2, 0.2, 3), (0, 0.2, 3),
    ]
    faces = [
        (0, 1, 2), (0, 2, 3),        # front
        (4, 6, 5), (4, 7, 6),        # back
        (0, 4, 5), (0, 5, 1),        # bottom
        (3, 2, 6), (3, 6, 7),        # top
        (0, 3, 7), (0, 7, 4),        # left
        (1, 5, 6), (1, 6, 2),        # right
    ]
    bm = bpy.data.meshes.new("wall_mesh")
    bm.from_pydata(verts, [], faces)
    bm.update(calc_edges=True)
    bm.validate()
    obj = bpy.data.objects.new("architecture_wall_test001", bm)
    obj.data.materials.append(make_material("wall_mat", (0.71, 0.55, 0.35)))
    collection.objects.link(obj)
    return obj


def build_round_pipe(collection):
    """Bezier + AUTO handles + bevel_depth — Blender auto-rounds the elbow at the bend."""
    polyline = [(3, 0, 0.5), (5, 0, 0.5), (5, 0, 2.0), (7, 0, 2.0)]  # one bend
    curve = bpy.data.curves.new("pipe_curve", type='CURVE')
    curve.dimensions = '3D'
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(len(polyline) - 1)
    for i, (x, y, z) in enumerate(polyline):
        bp = spline.bezier_points[i]
        bp.co = (x, y, z)
        bp.handle_left_type = bp.handle_right_type = 'AUTO'
    diameter_in = 1.5
    curve.bevel_depth = (diameter_in / 2) * 0.0254
    curve.bevel_resolution = 4
    curve.fill_mode = 'FULL'
    obj = bpy.data.objects.new("mep_plumbing_pipe_test001", curve)
    obj.data.materials.append(make_material("pipe_mat", (0.75, 0.75, 0.78)))
    collection.objects.link(obj)
    return obj


def get_rect_profile(width_in, height_in, profiles_collection):
    w, h = width_in * 0.0254 / 2, height_in * 0.0254 / 2
    pc = bpy.data.curves.new("duct_profile", type='CURVE')
    pc.dimensions = '2D'
    sp = pc.splines.new('POLY')
    sp.points.add(3)
    for i, (x, y) in enumerate([(-w, -h), (w, -h), (w, h), (-w, h)]):
        sp.points[i].co = (x, y, 0, 1)
    sp.use_cyclic_u = True
    obj = bpy.data.objects.new("duct_profile", pc)
    profiles_collection.objects.link(obj)
    return obj


def build_rect_duct(collection, profiles_collection):
    """POLY spline (mitered, not rounded) + custom rectangular bevel_object — true box cross-section."""
    polyline = [(3, 3, 2.5), (6, 3, 2.5), (6, 5, 2.5)]  # one 90-degree miter
    curve = bpy.data.curves.new("duct_curve", type='CURVE')
    curve.dimensions = '3D'
    spline = curve.splines.new('POLY')
    spline.points.add(len(polyline) - 1)
    for i, (x, y, z) in enumerate(polyline):
        spline.points[i].co = (x, y, z, 1.0)
    curve.bevel_mode = 'OBJECT'
    curve.bevel_object = get_rect_profile(12.0, 8.0, profiles_collection)
    curve.fill_mode = 'FULL'
    obj = bpy.data.objects.new("mep_hvac_duct_test001", curve)
    obj.data.materials.append(make_material("duct_mat", (0.6, 0.62, 0.65)))
    collection.objects.link(obj)
    return obj


def build_sprinkler_fixture(collection, position):
    """Flush-mount disc + deflector cross — stand-in for the real fixture_library.py builder."""
    bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.01, location=position)
    disc = bpy.context.active_object
    disc.name = "fixtures_sprinkler_test001"
    disc.data.materials.append(make_material("sprinkler_mat", (0.85, 0.85, 0.82)))
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.collection.objects.unlink(disc)
    collection.objects.link(disc)

    bar_positions = [(0.02, 0, -0.01), (-0.02, 0, -0.01)]
    for i, offset in enumerate(bar_positions):
        loc = (position[0] + offset[0], position[1] + offset[1], position[2] + offset[2])
        bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
        bar = bpy.context.active_object
        bar.scale = (0.05, 0.005, 0.005)
        bar.name = f"fixtures_sprinkler_deflector{i}_test001"
        bar.data.materials.append(disc.data.materials[0])
        bpy.context.collection.objects.unlink(bar)
        collection.objects.link(bar)
    return disc


def main():
    reset_scene()

    profiles = bpy.data.collections.new("_profiles")
    bpy.context.scene.collection.children.link(profiles)

    arch = bpy.data.collections.new("architecture")
    bpy.context.scene.collection.children.link(arch)
    build_box_mesh(arch)

    plumbing = bpy.data.collections.new("plumbing")
    bpy.context.scene.collection.children.link(plumbing)
    build_round_pipe(plumbing)

    hvac = bpy.data.collections.new("hvac")
    bpy.context.scene.collection.children.link(hvac)
    build_rect_duct(hvac, profiles)

    fixtures = bpy.data.collections.new("fixtures")
    bpy.context.scene.collection.children.link(fixtures)
    build_sprinkler_fixture(fixtures, (4, 4, 3.0))

    # Exclude the helper profile-curve collection from export (it's only a bevel reference).
    view_layer = bpy.context.view_layer
    for lc in view_layer.layer_collection.children:
        if lc.name == "_profiles":
            lc.exclude = True

    out_path = str(__file__).replace("scratch_test.py", "test.glb")
    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format='GLB',
        use_selection=False,
        export_apply=True,
        export_yup=True,
        export_materials='EXPORT',
        export_lights=False,
        export_cameras=False,
    )
    print(f"Exported {out_path}")
    print("Objects in scene:", [o.name for o in bpy.data.objects])


if __name__ == "__main__":
    main()
