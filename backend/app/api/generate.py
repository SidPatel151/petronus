from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from app.models.schemas import GenerateRequest, JobStatus, ProjectSpec, SiteInput, LatLon
from app.services.orchestrator import GenerationOrchestrator
from app.services.job_store import JOBS as _jobs
from app.api.projects import get_projects_store
import uuid
import traceback

router = APIRouter()


def _validated_massing_choice(choice: int | None) -> int:
    """Normalize the default choice and reject indexes the generator cannot produce."""
    resolved = 0 if choice is None else choice
    if resolved not in (0, 1, 2):
        raise HTTPException(
            status_code=422,
            detail="massing_choice must be one of 0 (A), 1 (B), or 2 (C)",
        )
    return resolved

@router.post("/", response_model=JobStatus)
async def start_generation(body: GenerateRequest, background_tasks: BackgroundTasks):
    projects = get_projects_store()
    if body.project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    massing_choice = _validated_massing_choice(body.massing_choice)

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "progress": 0,
        "current_step": "Queued",
        "result": None,
        "error": None,
    }

    background_tasks.add_task(
        _run_generation,
        job_id,
        body.project_id,
        projects[body.project_id]["spec"],
        massing_choice,
    )

    return JobStatus(**_jobs[job_id])

@router.get("/status/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(**_jobs[job_id])

@router.post("/quick")
async def quick_generate(
    spec: ProjectSpec,
    massing_choice: int = Query(default=0, ge=0, le=2),
):
    """One-shot generate without project creation — good for demo"""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id, "status": "running",
        "progress": 0, "current_step": "Starting",
        "result": None, "error": None,
    }

    def progress(p, s):
        _jobs[job_id]["progress"] = p
        _jobs[job_id]["current_step"] = s

    try:
        orch = GenerationOrchestrator(progress_cb=progress)
        model = await orch.run(spec, massing_choice)
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["result"] = model.dict()
        return _jobs[job_id]
    except Exception as e:
        tb = traceback.format_exc()
        print("GENERATION ERROR:", tb)
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))


async def _run_generation(job_id, project_id, spec, massing_choice):
    projects = get_projects_store()

    def progress(p, s):
        _jobs[job_id]["progress"] = p
        _jobs[job_id]["current_step"] = s
        _jobs[job_id]["status"] = "running"

    try:
        orch = GenerationOrchestrator(progress_cb=progress)
        model = await orch.run(spec, massing_choice)
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["progress"] = 100
        _jobs[job_id]["result"] = model.dict()
        projects[project_id]["building_model"] = model.dict()
        projects[project_id]["status"] = "generated"
    except Exception as e:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)
