from fastapi import APIRouter, HTTPException
from app.models.schemas import ProjectCreate, ProjectResponse, ProjectSpec
import uuid

router = APIRouter()

# In-memory store for demo (replace with DB)
_projects: dict = {}

@router.post("/", response_model=ProjectResponse)
async def create_project(body: ProjectCreate):
    pid = str(uuid.uuid4())
    _projects[pid] = {
        "id": pid,
        "name": body.name,
        "status": "created",
        "spec": body.spec,
        "building_model": None,
    }
    return ProjectResponse(id=pid, name=body.name, status="created", spec=body.spec)

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    if project_id not in _projects:
        raise HTTPException(status_code=404, detail="Project not found")
    p = _projects[project_id]
    return ProjectResponse(**p)

@router.get("/")
async def list_projects():
    return [{"id": p["id"], "name": p["name"], "status": p["status"]} for p in _projects.values()]

def get_projects_store():
    return _projects
