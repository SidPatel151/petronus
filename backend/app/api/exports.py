from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.api.projects import get_projects_store
import json, os, tempfile

router = APIRouter()

@router.get("/{project_id}/json")
async def export_json(project_id: str):
    projects = get_projects_store()
    if project_id not in projects or not projects[project_id].get("building_model"):
        raise HTTPException(status_code=404, detail="No generated model found")
    return projects[project_id]["building_model"]

@router.get("/{project_id}/ifc")
async def export_ifc(project_id: str):
    # Stub: returns JSON with IFC note until ifcopenshell is wired
    return {"message": "IFC export coming soon — wire ifcopenshell exporter here", "project_id": project_id}

@router.get("/{project_id}/dxf")
async def export_dxf(project_id: str):
    return {"message": "DXF export coming soon — wire ezdxf exporter here", "project_id": project_id}
