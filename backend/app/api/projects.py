from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from app.models.schemas import ProjectCreate, ProjectResponse, ProjectSpec, BuildingModel, SiteInput
from app.core.persistence import init_db, upsert_project, get_project, list_projects
from typing import Optional
import uuid

_opt_bearer = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

async def _optional_user(token: str = Depends(_opt_bearer)):
    if not token:
        return None
    try:
        from app.api.auth import get_current_user, _oauth2
        return await get_current_user(token)
    except Exception:
        return None

router = APIRouter()

# In-memory cache so generate.py can access specs without a DB round-trip
_projects: dict = {}

# Initialise schema on import
init_db()

# ── Load persisted projects into memory cache on startup ──────────────────────
def _warm_cache() -> None:
    for p in list_projects():
        _projects[p["id"]] = {
            "id":             p["id"],
            "name":           p["name"],
            "address":        p.get("address", ""),
            "status":         p["status"],
            "spec":           p["spec"],   # raw dict — generation uses request-time spec
            "building_model": p["building_model"],
        }

_warm_cache()


# ── CRUD ────────────────────────────────────────────────────────────────────────
@router.post("/", response_model=ProjectResponse)
async def create_project(body: ProjectCreate):
    pid = str(uuid.uuid4())
    address = getattr(body, "address", "") or ""
    _projects[pid] = {
        "id": pid, "name": body.name, "address": address,
        "status": "created", "spec": body.spec, "building_model": None,
    }
    upsert_project(pid, body.name, address, body.spec.dict())
    return ProjectResponse(id=pid, name=body.name, status="created", spec=body.spec)


@router.get("/", response_model=list)
async def list_projects_endpoint(user=Depends(_optional_user)):
    uid = user["id"] if user else None
    rows = list_projects(user_id=uid)
    return [
        {
            "id":      r["id"],
            "name":    r["name"],
            "address": r.get("address", ""),
            "status":  r["status"],
            "stories": r.get("stories", 0),
            "units":   r.get("units", 0),
            "sqft":    r.get("sqft", 0),
            "seismic": r.get("seismic", "D"),
            "flood":   r.get("flood", "X"),
            "updated_at": r.get("updated_at", ""),
        }
        for r in rows
    ]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project_endpoint(project_id: str):
    p = _projects.get(project_id) or get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    if isinstance(p["spec"], ProjectSpec):
        spec = p["spec"]
    else:
        try:
            spec = ProjectSpec(**p["spec"])
        except Exception:
            # Legacy saved specs may be partial (no site field); supply a stub.
            raw = p["spec"] if isinstance(p["spec"], dict) else {}
            spec = ProjectSpec(site=SiteInput(), **{k: v for k, v in raw.items() if k != "site"})
    bm = p.get("building_model")
    return ProjectResponse(
        id=p["id"], name=p["name"], status=p["status"],
        spec=spec,
        building_model=BuildingModel(**bm) if bm else None,
    )


class SaveBody(BaseModel):
    name: str
    address: Optional[str] = ""
    spec: dict
    building_model: Optional[dict] = None


@router.post("/save")
async def save_project(body: SaveBody, user=Depends(_optional_user)):
    """Save or update a project (upsert by generated ID)."""
    pid = str(uuid.uuid4())
    bm = body.building_model or {}
    rooms   = bm.get("rooms", [])
    levels  = bm.get("levels", [])
    stories = len(levels)
    units   = len(set(r.get("unit_id") for r in rooms if r.get("unit_id")))
    sqft    = int(sum(r.get("area_sqft", 0) for r in rooms))
    site    = bm.get("site_context") or {}
    seismic = (site.get("seismic_design_category") or "D")
    flood   = (site.get("flood_zone") or "X")

    upsert_project(
        pid, body.name, body.address or "", body.spec,
        "generated" if body.building_model else "created",
        body.building_model,
        stories, units, sqft, seismic, flood,
        user_id=user["id"] if user else None,
    )
    _projects[pid] = {
        "id": pid, "name": body.name, "address": body.address or "",
        "status": "generated" if body.building_model else "created",
        "spec": body.spec, "building_model": body.building_model,
    }
    return {"id": pid, "status": "saved"}


def get_projects_store() -> dict:
    return _projects
