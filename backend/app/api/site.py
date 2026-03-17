from fastapi import APIRouter, HTTPException
from app.models.schemas import LatLon
from app.services.site_context import SiteContextService
from typing import Optional
from pydantic import BaseModel

router = APIRouter()
svc = SiteContextService()

class SiteRequest(BaseModel):
    lat: float
    lon: float
    address: Optional[str] = None
    parcel_polygon: Optional[dict] = None

@router.post("/context")
async def get_site_context(body: SiteRequest):
    try:
        ctx = await svc.build_context(latlon=LatLon(lat=body.lat, lon=body.lon))
        return ctx
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/infrastructure")
async def get_infrastructure(body: SiteRequest):
    try:
        data = await svc.get_nearby_infrastructure(LatLon(lat=body.lat, lon=body.lon), radius_m=400)
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/neighbors")
async def get_neighbors(body: SiteRequest):
    try:
        if not body.parcel_polygon:
            ctx = await svc.build_context(latlon=LatLon(lat=body.lat, lon=body.lon))
            parcel = ctx.parcel_polygon
        else:
            parcel = body.parcel_polygon
        data = await svc.get_neighbor_constraints(LatLon(lat=body.lat, lon=body.lon), parcel)
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/feasibility")
async def get_legal_feasibility(body: SiteRequest):
    try:
        if not body.parcel_polygon:
            ctx = await svc.build_context(latlon=LatLon(lat=body.lat, lon=body.lon))
            parcel = ctx.parcel_polygon
        else:
            parcel = body.parcel_polygon
        data = await svc.get_legal_feasibility(LatLon(lat=body.lat, lon=body.lon), parcel)
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/geocode")
async def geocode(address: str):
    try:
        latlon = await svc._geocode(address)
        return {"lat": latlon.lat, "lon": latlon.lon}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))