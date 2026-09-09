"""2D blueprint editor API.

Draft/finalize split of the generation pipeline: /draft runs everything
through floorplan generation and hands back an editable draft (rooms/walls
per level, no facade/MEP/compliance/render yet); /finalize resumes the
pipeline (door meshes -> facade -> MEP -> structural -> compliance -> render)
on whatever rooms/walls are on the draft at that point, exactly like the
one-shot /generate/quick would have produced if the user made no edits.

/edit applies one manual edit op through app.generators.floorplan_editor —
the same dispatcher AI chat edits will use in a later phase, so manual and
AI-driven edits always go through one validated code path.
"""
import traceback
import uuid
from typing import Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.generators.floorplan_editor import apply_op, validate as validate_blueprint
from app.models.schemas import (
    BlueprintDraftRequest, BlueprintDraftResponse, JobStatus,
    BlueprintEditRequest, BlueprintEditResponse,
)
from app.services.draft_state import DraftState
from app.services.job_store import JOBS
from app.services.orchestrator import GenerationOrchestrator

router = APIRouter()

# In-memory draft store — mirrors JOBS/_projects (in-process, non-durable).
# A draft is short-lived: created by /draft, mutated by /edit (later phase),
# consumed and evicted by /finalize.
_drafts: Dict[str, DraftState] = {}


def get_drafts_store() -> Dict[str, DraftState]:
    return _drafts


def _draft_response(draft: DraftState) -> BlueprintDraftResponse:
    envelopes = {}
    for lvl_idx, poly in draft.footprint_envelopes.items():
        try:
            envelopes[str(lvl_idx)] = [list(c) for c in poly.exterior.coords]
        except Exception:
            continue
    target_sqft = draft.model.spec.target_gross_area_sqft or 0.0
    warnings = validate_blueprint(draft.model.rooms, draft.model.walls, draft.footprint_envelopes, target_sqft)
    return BlueprintDraftResponse(
        draft_id=draft.draft_id,
        levels=draft.model.levels,
        rooms=draft.model.rooms,
        walls=draft.model.walls,
        footprint_envelopes=envelopes,
        warnings=warnings,
        target_sqft=target_sqft,
        massing_options=draft.model.massing_options,
        chosen_massing_index=draft.model.chosen_massing_index,
        spec=draft.model.spec,
    )


@router.post("/draft", response_model=BlueprintDraftResponse)
async def create_draft(body: BlueprintDraftRequest):
    """Run the pipeline through floorplan generation and hand back an
    editable draft. No project needs to exist first — mirrors
    /generate/quick's no-project ergonomics."""
    try:
        orch = GenerationOrchestrator()
        draft = await orch.run_draft(body.spec, body.massing_choice)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    draft.draft_id = str(uuid.uuid4())
    _drafts[draft.draft_id] = draft
    return _draft_response(draft)


@router.get("/{draft_id}", response_model=BlueprintDraftResponse)
async def get_draft(draft_id: str):
    draft = _drafts.get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _draft_response(draft)


@router.post("/{draft_id}/edit", response_model=BlueprintEditResponse)
async def edit_draft(draft_id: str, body: BlueprintEditRequest):
    """Apply one manual edit op. Validation failures return 200 {ok:false,
    error:...} — edits are rejectable by design, not server errors. 4xx is
    reserved for a malformed request or an unknown draft."""
    draft = _drafts.get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    ok, error = apply_op(draft, body.op.op_type, dict(body.op.params))

    target_sqft = draft.model.spec.target_gross_area_sqft or 0.0
    warnings = validate_blueprint(draft.model.rooms, draft.model.walls, draft.footprint_envelopes, target_sqft)
    return BlueprintEditResponse(
        ok=ok, rooms=draft.model.rooms, walls=draft.model.walls,
        warnings=warnings, error=error,
    )


async def _run_finalize(job_id: str, draft_id: str):
    def progress(p, s):
        JOBS[job_id]["progress"] = p
        JOBS[job_id]["current_step"] = s
        JOBS[job_id]["status"] = "running"

    draft = _drafts.get(draft_id)
    if not draft:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = "Draft not found (may have already been finalized)"
        return

    try:
        orch = GenerationOrchestrator(progress_cb=progress)
        model = await orch.run_finalize(draft)
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["progress"] = 100
        JOBS[job_id]["result"] = model.dict()
        _drafts.pop(draft_id, None)
    except Exception as e:
        traceback.print_exc()
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(e)


@router.post("/{draft_id}/finalize", response_model=JobStatus)
async def finalize_draft(draft_id: str, background_tasks: BackgroundTasks):
    """Resume the pipeline (door meshes -> facade -> MEP -> structural ->
    compliance -> render) on the draft's current rooms/walls, in the
    background. Returns a job_id for polling via the existing
    GET /api/generate/status/{job_id} — no separate polling endpoint needed.
    Evicts the draft on success: no further edits once 3D generation begins."""
    draft = _drafts.get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "job_id": job_id, "status": "pending",
        "progress": 0, "current_step": "Queued",
        "result": None, "error": None,
    }
    background_tasks.add_task(_run_finalize, job_id, draft_id)
    return JobStatus(**JOBS[job_id])
