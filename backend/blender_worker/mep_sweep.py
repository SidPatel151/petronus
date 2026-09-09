"""
Builds one continuous swept bpy Curve object per reconstructed MEP run (a run is a
polyline already regrouped server-side from route_parent_id-chained MEPElement
segments — see app/services/render_payload.py:group_mep_runs).

Round pipes/conduit: Bezier spline with AUTO handles + bevel_depth — Blender rounds
elbow bends automatically, which is the actual visual win over the old per-segment
straight-cylinder rendering.

Rectangular ducts: real ductwork has mitered (sharp), not rounded, elbows, so these
use a straight POLY spline + a custom rectangular bevel_object profile instead of the
built-in round bevel — a round bevel_depth cannot produce a box cross-section.
"""
import bpy
from materials import get_material
from coords import to_blender_all

INCH_TO_M = 0.0254

_rect_profile_cache: dict = {}


def get_or_create_rect_profile(width_in: float, height_in: float) -> "bpy.types.Object":
    """Never linked into any collection — bevel_object references work via the ID
    pointer alone, and an unlinked object is automatically excluded from export
    (verified: a plain bpy.data.objects.new() with 0 users_collection produces zero
    export nodes), so this profile curve simply never appears in the output GLB."""
    key = (round(width_in, 1), round(height_in, 1))
    if key in _rect_profile_cache:
        return _rect_profile_cache[key]

    w, h = (width_in * INCH_TO_M) / 2, (height_in * INCH_TO_M) / 2
    pc = bpy.data.curves.new(f"duct_profile_{key}", type='CURVE')
    pc.dimensions = '2D'
    sp = pc.splines.new('POLY')
    sp.points.add(3)
    for i, (x, y) in enumerate([(-w, -h), (w, -h), (w, h), (-w, h)]):
        sp.points[i].co = (x, y, 0, 1)
    sp.use_cyclic_u = True
    obj = bpy.data.objects.new(f"duct_profile_{key}", pc)
    _rect_profile_cache[key] = obj
    return obj


def build_round_run(run: dict, collection) -> "bpy.types.Object":
    polyline = to_blender_all(run["polyline"])
    curve = bpy.data.curves.new(f'{run["type"]}_{run["parent_id"]}', type='CURVE')
    curve.dimensions = '3D'
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(len(polyline) - 1)
    for i, (x, y, z) in enumerate(polyline):
        bp = spline.bezier_points[i]
        bp.co = (x, y, z)
        bp.handle_left_type = bp.handle_right_type = 'AUTO'

    radius_m = max((run.get("diameter_in") or 0.5) / 2 * INCH_TO_M, 0.005)
    curve.bevel_depth = radius_m
    # 4 gives a visibly faceted (near-octagonal) cross-section up close — 8 is a
    # cheap bump (still nowhere near enough extra geometry to matter) that reads
    # as a genuinely round pipe instead of a chamfered rod.
    curve.bevel_resolution = 8
    curve.fill_mode = 'FULL'

    obj = bpy.data.objects.new(f'{run["layer"]}_{run["type"]}_{run["parent_id"]}', curve)
    obj.data.materials.append(get_material(run["type"], system=run["system"]))
    collection.objects.link(obj)
    return obj


def build_rect_run(run: dict, collection) -> "bpy.types.Object":
    polyline = to_blender_all(run["polyline"])
    curve = bpy.data.curves.new(f'{run["type"]}_{run["parent_id"]}', type='CURVE')
    curve.dimensions = '3D'
    spline = curve.splines.new('POLY')
    spline.points.add(len(polyline) - 1)
    for i, (x, y, z) in enumerate(polyline):
        spline.points[i].co = (x, y, z, 1.0)

    curve.bevel_mode = 'OBJECT'
    curve.bevel_object = get_or_create_rect_profile(
        run.get("width_in") or 8.0, run.get("height_in") or 8.0
    )
    curve.fill_mode = 'FULL'

    obj = bpy.data.objects.new(f'{run["layer"]}_{run["type"]}_{run["parent_id"]}', curve)
    obj.data.materials.append(get_material(run["type"], system=run["system"]))
    collection.objects.link(obj)
    return obj


def build_mep_run(run: dict, collection) -> "bpy.types.Object":
    """run: {"parent_id","system","type","layer","diameter_in","width_in","height_in","polyline"}
    A run needs at least 2 points to form a curve; degenerate single-point runs are
    skipped by the caller (render_payload.group_mep_runs already routes those to
    mep_points instead)."""
    if len(run["polyline"]) < 2:
        return None
    is_round = run.get("diameter_in") is not None
    if is_round:
        return build_round_run(run, collection)
    return build_rect_run(run, collection)


def reset_cache():
    _rect_profile_cache.clear()
