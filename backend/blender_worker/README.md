# Blender render worker

Isolated Python 3.13 subprocess worker that turns a finished `BuildingModel`'s
geometry into a photorealistic GLB via headless Blender (`bpy`). Runs as its own
venv, entirely separate from the main FastAPI app's Python 3.11 environment —
`bpy` is never added to `backend/requirements.txt` or `requirements-prod.txt`.

## Setup

```bash
cd backend/blender_worker
python3.13 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## Manual test (no FastAPI involved)

```bash
./venv/bin/python scratch_test.py
# produces test.glb — open in any glTF viewer to sanity-check geometry
```

## Invocation contract

Called by `app/services/blender_render.py` as:

```
venv/bin/python render_building.py < payload.json
```

- stdin: JSON payload built by `app/services/render_payload.py::build_render_payload`
- stdout: `{"ok": true, "glb_b64": "<base64 GLB>"}` or `{"ok": false, "error": "...", "traceback": "..."}`
- exit code 0 on success, 1 on failure

No shared temp files between the caller and this worker — everything travels over
stdin/stdout, since the deployment environment isn't guaranteed to share a
persistent filesystem between processes.

## Files

- `render_building.py` — subprocess entrypoint
- `scene_builder.py` — imports existing triangle meshes, extrudes room/wall
  polygons, orchestrates MEP sweeps and fixture placement, groups everything into
  `LayerKey`-named Collections
- `mep_sweep.py` — MEP polyline → swept curve geometry (round pipes via Bezier
  bevel, rectangular ducts via a custom bevel profile)
- `fixture_library.py` — procedural fixture models (sprinkler, panel, toilet,
  etc.), instanced via linked duplicates
- `materials.py` — element_type/color → Principled BSDF material lookup
- `coords.py` — Y-up (app convention) ↔ Blender Z-up axis conversion

## Coordinate convention

The app's geometry is Y-up: `(x, y=height, z=depth)`. Blender is Z-up internally.
`coords.to_blender()` converts every point before it enters bpy; `export_yup=True`
on export converts back, so the final GLB is Y-up again, matching what the
frontend already expects.
