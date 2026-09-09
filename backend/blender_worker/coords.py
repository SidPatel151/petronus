"""
Coordinate conversion between the app's existing geometry convention and Blender's
native frame.

The app's Mesh/Room/Wall/MEPElement data is all Y-up: (x, y=height, z=depth) — the
same convention Three.js/glTF use. Blender is Z-up internally regardless of any
export flag, so geometry must be built in Blender's frame and only converted back to
Y-up at export time via `export_yup=True`.

Empirically confirmed (see backend/blender_worker task notes): with export_yup=True,
Blender (x, y, z) -> glTF (x, z, -y). Solving for the Blender-frame point that
round-trips a given Y-up source point (sx, sy, sz) back out as (sx, sy, sz):
    gltf_x = blender_x = sx
    gltf_y = blender_z = sy
    gltf_z = -blender_y = sz  =>  blender_y = -sz
So: to_blender(sx, sy, sz) = (sx, -sz, sy)
"""


def to_blender(point) -> tuple:
    x, y, z = point
    return (x, -z, y)


def to_blender_all(points) -> list:
    return [to_blender(p) for p in points]
