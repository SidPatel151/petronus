"""
Invokes the isolated Blender render worker (backend/blender_worker/, its own Python
3.13 venv with `bpy` installed) as a subprocess. Never raises — any failure degrades
to (None, "fallback") so a Blender crash can never break building generation; the
orchestrator's Step 8 also wraps its own call in a try/except as a second layer of
defense (see app/services/orchestrator.py).
"""
import asyncio
import json
import logging
import pathlib
import subprocess
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_WORKER_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "blender_worker"
_WORKER_PYTHON = _WORKER_DIR / "venv" / "bin" / "python"
_WORKER_SCRIPT = _WORKER_DIR / "render_building.py"
RENDER_TIMEOUT_S = 90


async def render_building_glb(payload: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Returns (base64-encoded GLB, "blender") on success, or (None, "fallback")."""
    if not _WORKER_PYTHON.exists():
        logger.warning("Blender worker venv not found at %s — skipping GLB render", _WORKER_PYTHON)
        return None, "fallback"

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [str(_WORKER_PYTHON), str(_WORKER_SCRIPT)],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=RENDER_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        logger.error("Blender worker timed out after %ss", RENDER_TIMEOUT_S)
        return None, "fallback"
    except Exception:
        logger.exception("Blender worker invocation failed")
        return None, "fallback"

    try:
        out = json.loads(result.stdout.decode("utf-8"))
    except Exception:
        logger.error(
            "Blender worker produced non-JSON stdout (exit=%s): %s",
            result.returncode, result.stderr.decode("utf-8", errors="replace")[-2000:],
        )
        return None, "fallback"

    if not out.get("ok"):
        logger.error("Blender worker reported failure: %s", out.get("traceback") or out.get("error"))
        return None, "fallback"

    return out["glb_b64"], "blender"
