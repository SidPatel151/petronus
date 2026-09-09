"""
Subprocess entrypoint. Invoked as:
    venv/bin/python render_building.py < payload.json

Reads the render payload JSON from stdin, builds the bpy scene, exports GLB, and
writes a single JSON line to stdout: {"ok": true, "glb_b64": "..."} on success, or
{"ok": false, "error": "...", "traceback": "..."} on failure (nonzero exit code).

Communicates purely via stdin/stdout — no shared temp files with the caller, since
the deployment environment isn't guaranteed to have a persistent/shared filesystem
between the main app process and this subprocess.
"""
import base64
import json
import sys
import tempfile
import traceback
import os

import bpy

from scene_builder import build_scene


def _silence_stdout() -> int:
    """Blender (and the glTF exporter addon) write INFO/WARNING lines straight to
    the OS-level stdout file descriptor, bypassing Python's sys.stdout — a plain
    `contextlib.redirect_stdout` would not catch them. Redirect fd 1 -> fd 2 for the
    duration of scene build/export so nothing lands on stdout except our own final
    JSON line, which the caller parses as the entire stdout content."""
    saved_fd = os.dup(1)
    os.dup2(2, 1)
    return saved_fd


def _restore_stdout(saved_fd: int) -> None:
    os.dup2(saved_fd, 1)
    os.close(saved_fd)


def export_glb() -> bytes:
    fd, path = tempfile.mkstemp(suffix=".glb")
    os.close(fd)
    try:
        bpy.ops.export_scene.gltf(
            filepath=path,
            export_format="GLB",
            use_selection=False,
            export_apply=True,
            export_yup=True,
            export_materials="EXPORT",
            export_lights=False,
            export_cameras=False,
        )
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.unlink(path)


def main() -> None:
    payload = json.loads(sys.stdin.read())
    saved_fd = _silence_stdout()
    try:
        build_scene(payload)
        glb_bytes = export_glb()
    finally:
        _restore_stdout(saved_fd)
    sys.stdout.write(json.dumps({"ok": True, "glb_b64": base64.b64encode(glb_bytes).decode("ascii")}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stdout.write(json.dumps({
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }))
        sys.exit(1)
