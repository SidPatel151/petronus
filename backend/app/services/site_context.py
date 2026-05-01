"""
SiteContextService - OSM + FEMA + neighbor buildings + constraints
"""
import asyncio
import hashlib
import json as _json
import httpx
import math
import urllib.parse
from shapely.geometry import shape, Polygon, mapping
from shapely.ops import transform
import pyproj
from typing import Dict, Any, Optional, Tuple, List
from app.models.schemas import SiteContext, LatLon
from app.services.hazard_lookup import HazardLookupService

# Optional Redis cache for Overpass results (24h TTL)
try:
    import redis.asyncio as _aioredis
    from app.core.config import settings as _settings
    _redis_client = _aioredis.from_url(_settings.REDIS_URL, decode_responses=True)
except Exception:
    _redis_client = None

_OVERPASS_TTL = 86400  # 24 hours

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
FEMA_URL     = "https://msc.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"

# California Energy Commission ArcGIS — confirmed working 2025
CEC_BASE     = "https://services3.arcgis.com/bWPjFyq029ChCGur/arcgis/rest/services"
CEC_PLANTS   = f"{CEC_BASE}/Power_Plant/FeatureServer/0/query"
CEC_GAS_AREA = f"{CEC_BASE}/Natural_Gas_Service_Area/FeatureServer/0/query"
DEFAULT_SETBACKS = {"front": 15.0, "rear": 20.0, "left": 5.0, "right": 5.0}


class SiteContextService:

    async def build_context(self, latlon=None, parcel_polygon=None, address=None) -> SiteContext:
        if latlon is None and address:
            latlon = await self._geocode(address)
        if latlon is None:
            raise ValueError("Must provide latlon or address")
        if parcel_polygon is None:
            parcel_polygon = await self._get_parcel_from_osm(latlon)
        parcel_shape = shape(parcel_polygon)
        # Heal self-intersecting polygons (e.g. bowtie from wrong vertex order)
        # convex_hull always returns a valid convex polygon.
        if not parcel_shape.is_valid or parcel_shape.geom_type != 'Polygon':
            parcel_shape = parcel_shape.convex_hull
        if not parcel_shape.is_valid or parcel_shape.is_empty:
            raise ValueError("Parcel polygon is invalid — check vertex coordinates")
        area_sqft = self._area_sqft(parcel_shape, latlon)
        buildable = self._apply_setbacks(parcel_shape, DEFAULT_SETBACKS, latlon)
        centroid = self._centroid(parcel_shape)

        # Parallelize all three independent async calls
        hazard_svc = HazardLookupService()
        (flood_zone, flood_flag), hazards, terrain = await asyncio.gather(
            self._get_flood_zone(latlon),
            hazard_svc.get_all(latlon.lat, latlon.lon),
            self.get_terrain_data(latlon, parcel_polygon or mapping(parcel_shape)),
        )
        seismic_cat = hazards["seismic"]["sdc"]
        wind_speed  = hazards["wind"]["vult_mph"]

        return SiteContext(
            parcel_polygon=mapping(parcel_shape),
            buildable_envelope_2d=mapping(buildable),
            area_sqft=area_sqft,
            centroid=LatLon(lat=centroid[1], lon=centroid[0]),
            flood_zone=flood_zone,
            flood_flag=flood_flag,
            seismic_category=seismic_cat,
            wind_speed_mph=wind_speed,
            setbacks=DEFAULT_SETBACKS,
            hazard_detail=hazards,
            terrain=terrain,
        )

    async def get_nearby_infrastructure(self, latlon: LatLon, radius_m: int = 150) -> Dict[str, Any]:
        bbox = self._latlon_to_bbox(latlon, radius_m)
        query = f"""
        [out:json][timeout:25];
        (
          node["emergency"="fire_hydrant"]({bbox});
          way["man_made"="pipeline"]({bbox});
          way["power"="line"]({bbox});
          way["power"="minor_line"]({bbox});
          node["power"="pole"]({bbox});
          node["power"="tower"]({bbox});
          way["highway"]({bbox});
          node["man_made"="manhole"]({bbox});
          way["waterway"]({bbox});
          way["building"]({bbox});
          node["amenity"]({bbox});
          node["shop"]({bbox});
        );
        out body geom;
        """
        result = {"fire_hydrants": [], "pipelines": [], "power_lines": [],
                  "roads": [], "manholes": [], "waterways": [], "buildings": [],
                  "places": [], "power_poles": []}
        overpass_ok = False
        data = {"elements": []}

        # Check Redis cache first (key = hash of bbox string, TTL 24h)
        _cache_key = f"overpass:{hashlib.md5(bbox.encode()).hexdigest()}"
        _cached = None
        if _redis_client:
            try:
                _cached = await _redis_client.get(_cache_key)
            except Exception:
                pass

        if _cached:
            data = _json.loads(_cached)
            overpass_ok = True
        else:
            try:
                async with httpx.AsyncClient(timeout=28) as client:
                    resp = await client.post(
                        OVERPASS_URL,
                        content=urllib.parse.urlencode({"data": query}).encode("utf-8"),
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    if resp.status_code == 200 and resp.content:
                        data = resp.json()
                        overpass_ok = True
                        if _redis_client:
                            try:
                                await _redis_client.set(_cache_key, _json.dumps(data), ex=_OVERPASS_TTL)
                            except Exception:
                                pass
            except Exception:
                pass  # continue to CEC queries below

        for el in data.get("elements", []):
            tags = el.get("tags", {})
            if tags.get("emergency") == "fire_hydrant":
                result["fire_hydrants"].append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                    "properties": tags,
                })
            elif tags.get("man_made") == "pipeline":
                f = self._way_to_feature(el, tags)
                if f: result["pipelines"].append(f)
            elif tags.get("power") in ("line", "minor_line"):
                f = self._way_to_feature(el, tags)
                if f: result["power_lines"].append(f)
            elif tags.get("power") in ("pole", "tower"):
                result["power_poles"].append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                    "properties": tags,
                })
            elif "highway" in tags:
                f = self._way_to_feature(el, tags)
                if f: result["roads"].append(f)
            elif tags.get("man_made") == "manhole":
                result["manholes"].append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                    "properties": tags,
                })
            elif "waterway" in tags:
                f = self._way_to_feature(el, tags)
                if f: result["waterways"].append(f)
            elif "building" in tags and "geometry" in el and len(el.get("geometry", [])) >= 3:
                coords = [[n["lon"], n["lat"]] for n in el["geometry"]]
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                height_m = self._parse_building_height(tags)
                levels = int(tags.get("building:levels", 0))
                if levels and not height_m:
                    height_m = levels * 3.0
                result["buildings"].append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                    "properties": {
                        **tags,
                        "height_m": height_m or 6.0,
                        "levels": levels or 2,
                        "osm_id": el.get("id"),
                        # Architectural style hints
                        "roof_shape":    tags.get("roof:shape", "flat"),
                        "roof_material": tags.get("roof:material", ""),
                        "arch_style":    tags.get("building:architecture", tags.get("building:style", "")),
                        "facade_mat":    tags.get("building:material", tags.get("material", "")),
                        "facade_color":  tags.get("building:colour", tags.get("building:color", "")),
                        "has_balconies": tags.get("building:balconies", "") or tags.get("balcony", ""),
                        "window_ratio":  tags.get("building:window_ratio", ""),
                    },
                })
            elif "amenity" in tags or "shop" in tags:
                place_type = tags.get("amenity") or tags.get("shop", "shop")
                name = tags.get("name", place_type)
                result["places"].append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                    "properties": {**tags, "place_type": place_type, "display_name": name},
                })

        result["power_connection"] = self._get_power_connection(latlon, result["power_lines"]) if overpass_ok else None

        # CEC real data — run in parallel
        plants, gas_utility = await asyncio.gather(
            self._get_nearby_power_plants(latlon, radius_m),
            self._get_gas_utility(latlon),
        )
        result["power_plants"] = plants
        result["gas_utility"]  = gas_utility   # e.g. {"name": "Pacific Gas & Electric", "abbr": "PG&E"}

        return result

    async def _get_nearby_power_plants(self, latlon: LatLon, radius_m: int) -> List[Dict]:
        """
        Query CEC ArcGIS for power plants within radius.
        Source: California Energy Commission — real, updated annually.
        """
        deg = (radius_m * 5) / 111320  # wider radius for plants — nearest may be km away
        bbox = {
            "xmin": latlon.lon - deg, "ymin": latlon.lat - deg,
            "xmax": latlon.lon + deg, "ymax": latlon.lat + deg,
            "spatialReference": {"wkid": 4326},
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(CEC_PLANTS, params={
                    "geometry":     str(bbox).replace("'", '"'),
                    "geometryType": "esriGeometryEnvelope",
                    "inSR":         "4326",
                    "spatialRel":   "esriSpatialRelIntersects",
                    "outFields":    "PlantName,PriEnergySource,Capacity_Latest,County,CECPlantID",
                    "outSR":        "4326",
                    "f":            "json",
                })
                if resp.status_code != 200:
                    return []
                features = resp.json().get("features", [])
                plants = []
                for f in features:
                    a = f.get("attributes", {})
                    g = f.get("geometry", {})
                    if not g:
                        continue
                    plants.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [g["x"], g["y"]]},
                        "properties": {
                            "name":     a.get("PlantName", "Unknown Plant"),
                            "fuel":     a.get("PriEnergySource", ""),
                            "capacity_mw": a.get("Capacity_Latest"),
                            "county":   a.get("County", ""),
                            "source":   "CEC",
                        },
                    })
                return plants
        except Exception:
            return []

    async def _get_gas_utility(self, latlon: LatLon) -> Optional[Dict]:
        """
        Query CEC ArcGIS for the gas utility serving this location.
        Source: California Energy Commission — real service territory polygons.
        Returns e.g. {"name": "Pacific Gas & Electric", "abbr": "PG&E", "category": "IOU"}
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(CEC_GAS_AREA, params={
                    "geometry":     f"{latlon.lon},{latlon.lat}",
                    "geometryType": "esriGeometryPoint",
                    "inSR":         "4326",
                    "spatialRel":   "esriSpatialRelIntersects",
                    "outFields":    "SERVICE,ABR,CATEGORY",
                    "returnGeometry": "false",
                    "f":            "json",
                })
                if resp.status_code != 200:
                    return None
                features = resp.json().get("features", [])
                if not features:
                    return None
                a = features[0].get("attributes", {})
                return {
                    "name":     a.get("SERVICE", "Unknown"),
                    "abbr":     a.get("ABR", ""),
                    "category": a.get("CATEGORY", ""),
                    "source":   "CEC",
                }
        except Exception:
            return None

    def _get_power_connection(self, latlon: LatLon, power_lines: list) -> Optional[Dict]:
        """Find nearest point on any power line and return a GeoJSON LineString connector."""
        from shapely.geometry import Point, LineString as SLineString
        site_pt = Point(latlon.lon, latlon.lat)
        best_dist = float("inf")
        best_conn = None
        for line_feature in power_lines:
            coords = line_feature.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            try:
                ls = SLineString(coords)
                nearest = ls.interpolate(ls.project(site_pt))
                dist = site_pt.distance(nearest)
                if dist < best_dist:
                    best_dist = dist
                    dist_m = round(dist * 111320 * math.cos(math.radians(latlon.lat)), 1)
                    best_conn = {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [latlon.lon, latlon.lat],
                                [nearest.x, nearest.y],
                            ],
                        },
                        "properties": {"type": "power_connection", "distance_m": dist_m},
                    }
            except Exception:
                continue
        return best_conn

    async def get_legal_feasibility(self, latlon: LatLon, parcel_polygon: Dict) -> Dict[str, Any]:
        """Fetch OSM landuse, historic, zoning tags and assess demolition feasibility."""
        query = f"""
        [out:json][timeout:15];
        (
          way["landuse"](around:100,{latlon.lat},{latlon.lon});
          way["historic"](around:60,{latlon.lat},{latlon.lon});
          node["historic"](around:60,{latlon.lat},{latlon.lon});
          way["boundary"="protected_area"](around:60,{latlon.lat},{latlon.lon});
        );
        out body geom;
        """
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    OVERPASS_URL,
                    content=urllib.parse.urlencode({"data": query}).encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                data = resp.json() if resp.status_code == 200 and resp.content else {"elements": []}
        except Exception:
            data = {"elements": []}

        landuse = None
        historic_flag = False
        historic_type = None
        protected_flag = False

        for el in data.get("elements", []):
            tags = el.get("tags", {})
            if "landuse" in tags and not landuse:
                landuse = tags["landuse"]
            if "historic" in tags:
                historic_flag = True
                historic_type = tags.get("historic")
            if tags.get("boundary") == "protected_area":
                protected_flag = True

        issues, warnings = [], []
        if historic_flag:
            issues.append(f"Historic designation ({historic_type or 'unknown'}) — demolition requires SHPO review")
        if protected_flag:
            issues.append("Protected area boundary — demolition likely prohibited")
        non_residential = {"industrial", "commercial", "retail", "office", "military", "cemetery"}
        if landuse in non_residential:
            warnings.append(f"Landuse tagged '{landuse}' — verify residential rezoning requirements")
        protected_land = {"conservation", "nature_reserve", "national_park"}
        if landuse in protected_land:
            issues.append(f"Protected land ({landuse}) — demolition likely prohibited")

        flood_zone, flood_flag = await self._get_flood_zone(latlon)
        if flood_flag:
            warnings.append(f"FEMA flood zone {flood_zone} — demolition/rebuild requires floodplain permit")

        return {
            "landuse": landuse,
            "historic": historic_flag,
            "historic_type": historic_type,
            "protected": protected_flag,
            "flood_zone": flood_zone,
            "flood_flag": flood_flag,
            "demolition_feasible": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "note": "Based on OpenStreetMap data — verify with local planning department",
        }

    async def get_terrain_data(self, latlon: LatLon, parcel_polygon: Dict) -> Dict[str, Any]:
        """Sample USGS 3DEP elevation at parcel corners + center to determine slope."""
        coords = parcel_polygon.get("coordinates", [[]])[0]
        if len(coords) >= 4:
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            min_lon, max_lon = min(lons), max(lons)
            min_lat, max_lat = min(lats), max(lats)
        else:
            d = 0.0002
            min_lon, max_lon = latlon.lon - d, latlon.lon + d
            min_lat, max_lat = latlon.lat - d, latlon.lat + d

        sample_points = {
            "center": (latlon.lon, latlon.lat),
            "sw":     (min_lon, min_lat),
            "se":     (max_lon, min_lat),
            "nw":     (min_lon, max_lat),
            "ne":     (max_lon, max_lat),
        }

        async def _fetch_elev(name: str, lon: float, lat: float) -> tuple:
            try:
                async with httpx.AsyncClient(timeout=8) as client:
                    resp = await client.get(
                        "https://epqs.nationalmap.gov/v1/json",
                        params={"x": lon, "y": lat, "wkid": "4326", "units": "Meters", "includeDate": "false"},
                    )
                    val = resp.json().get("value")
                    if val is not None and float(val) > -1000:
                        return name, float(val)
            except Exception:
                pass
            return name, None

        # All 5 elevation samples in parallel
        results = await asyncio.gather(*[_fetch_elev(n, lon, lat) for n, (lon, lat) in sample_points.items()])
        elevations: Dict[str, float] = {n: v for n, v in results if v is not None}

        if not elevations:
            return {"slope_pct": 0.0, "slope_degrees": 0.0, "is_sloped": False,
                    "elevation_range_m": 0.0, "avg_elevation_m": 0.0,
                    "grad_x": 0.0, "grad_z": 0.0, "source": "unavailable"}

        elev_vals = list(elevations.values())
        avg_elev = sum(elev_vals) / len(elev_vals)
        min_elev = min(elev_vals)
        max_elev = max(elev_vals)
        elev_range = max_elev - min_elev

        # Parcel diagonal in meters
        dx_m = (max_lon - min_lon) * 111320 * math.cos(math.radians(latlon.lat))
        dz_m = (max_lat - min_lat) * 111320
        diag_m = math.sqrt(dx_m ** 2 + dz_m ** 2) or 1.0
        slope_pct = (elev_range / diag_m) * 100

        # Gradient: how much Y rises per local meter in X and Z directions
        # X axis = east-west, Z axis = north-south (local space)
        elev_e = (elevations.get("ne", avg_elev) + elevations.get("se", avg_elev)) / 2
        elev_w = (elevations.get("nw", avg_elev) + elevations.get("sw", avg_elev)) / 2
        elev_n = (elevations.get("ne", avg_elev) + elevations.get("nw", avg_elev)) / 2
        elev_s = (elevations.get("se", avg_elev) + elevations.get("sw", avg_elev)) / 2
        grad_x = (elev_e - elev_w) / max(dx_m, 1.0)   # rise per meter east
        grad_z = (elev_n - elev_s) / max(dz_m, 1.0)   # rise per meter north

        return {
            "elevations_m": elevations,
            "avg_elevation_m": round(avg_elev, 2),
            "min_elevation_m": round(min_elev, 2),
            "max_elevation_m": round(max_elev, 2),
            "elevation_range_m": round(elev_range, 2),
            "slope_pct": round(slope_pct, 1),
            "slope_degrees": round(math.degrees(math.atan(slope_pct / 100)), 1),
            "is_sloped": slope_pct > 3.0,
            "grad_x": grad_x,   # local-space gradient (Y rise per local X meter)
            "grad_z": grad_z,   # local-space gradient (Y rise per local Z meter)
            "source": "USGS 3DEP",
        }

    async def get_neighbor_constraints(self, latlon: LatLon, parcel_polygon: Dict, radius_m: int = 80) -> Dict[str, Any]:
        infra = await self.get_nearby_infrastructure(latlon, radius_m)
        buildings = infra.get("buildings", [])
        parcel = shape(parcel_polygon)
        proj = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
        parcel_m = transform(proj, parcel)

        existing_on_parcel = None
        neighbors = []
        min_gap_m = float("inf")

        for b in buildings:
            try:
                bshape = shape(b["geometry"])
                bshape_m = transform(proj, bshape)
                props = b["properties"]
                intersection = parcel.intersection(bshape)
                overlap_ratio = intersection.area / bshape.area if bshape.area > 0 else 0

                if overlap_ratio > 0.3:
                    existing_on_parcel = {
                        "footprint": b["geometry"],
                        "height_m": props.get("height_m", 6.0),
                        "levels": props.get("levels", 2),
                        "area_sqft": bshape_m.area * 10.764,
                        "overlap_ratio": overlap_ratio,
                        "osm_id": props.get("osm_id"),
                    }
                else:
                    gap_m = parcel_m.exterior.distance(bshape_m)
                    min_gap_m = min(min_gap_m, gap_m)
                    bc = bshape.centroid
                    pc = parcel.centroid
                    dx = bc.x - pc.x
                    dy = bc.y - pc.y
                    direction = ("east" if dx > 0 else "west") if abs(dx) > abs(dy) else ("north" if dy > 0 else "south")
                    neighbors.append({
                        "footprint": b["geometry"],
                        "height_m": props.get("height_m", 6.0),
                        "levels": props.get("levels", 2),
                        "gap_m": round(gap_m, 1),
                        "gap_ft": round(gap_m * 3.281, 1),
                        "direction": direction,
                        "osm_id": props.get("osm_id"),
                    })
            except Exception:
                continue

        neighbors.sort(key=lambda x: x["gap_m"])

        issues, warnings = [], []
        for n in neighbors:
            g = n["gap_m"]
            d = n["direction"]
            if g < 0.9:
                issues.append(f"Neighbor to the {d} is only {n['gap_ft']}ft away — fire separation violation")
            elif g < 1.5:
                warnings.append(f"Neighbor to the {d} is {n['gap_ft']}ft away — very tight, check fire separation")
            elif g < 3.0:
                warnings.append(f"Neighbor to the {d} is {n['gap_ft']}ft away — limited construction access")

        parcel_w = parcel_m.bounds[2] - parcel_m.bounds[0]
        parcel_d = parcel_m.bounds[3] - parcel_m.bounds[1]

        return {
            "min_neighbor_gap_ft": round(min_gap_m * 3.281, 1) if min_gap_m != float("inf") else None,
            "neighbor_count": len(neighbors),
            "closest_neighbors": neighbors[:6],
            "existing_building": existing_on_parcel,
            "all_neighbor_buildings": buildings,
            "feasibility": {
                "feasible": len(issues) == 0,
                "issues": issues,
                "warnings": warnings,
                "parcel_width_ft": round(parcel_w * 3.281, 1),
                "parcel_depth_ft": round(parcel_d * 3.281, 1),
            },
        }

    # helpers
    async def _geocode(self, address: str) -> LatLon:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": address + ", California, USA", "format": "json", "limit": 1}
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Petronus/0.1"}) as client:
            resp = await client.get(url, params=params)
            results = resp.json()
        if not results:
            raise ValueError(f"Could not geocode: {address}")
        return LatLon(lat=float(results[0]["lat"]), lon=float(results[0]["lon"]))

    async def _get_parcel_from_osm(self, latlon: LatLon) -> Dict[str, Any]:
        query = f"""
        [out:json][timeout:15];
        (way["landuse"](around:50,{latlon.lat},{latlon.lon});
         way["building"](around:30,{latlon.lat},{latlon.lon}););
        out body geom;
        """
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    OVERPASS_URL,
                    content=urllib.parse.urlencode({"data": query}).encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code != 200 or not resp.content:
                    return self._box_polygon(latlon, 30, 30)
                data = resp.json()
            for el in data.get("elements", []):
                if "geometry" in el and len(el["geometry"]) >= 3:
                    coords = [[n["lon"], n["lat"]] for n in el["geometry"]]
                    if coords[0] != coords[-1]:
                        coords.append(coords[0])
                    return {"type": "Polygon", "coordinates": [coords]}
        except Exception:
            pass
        return self._box_polygon(latlon, 30, 30)

    async def _get_flood_zone(self, latlon: LatLon) -> Tuple[Optional[str], bool]:
        try:
            params = {"geometry": f"{latlon.lon},{latlon.lat}", "geometryType": "esriGeometryPoint",
                      "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
                      "outFields": "FLD_ZONE", "returnGeometry": "false", "f": "json"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(FEMA_URL, params=params)
                data = resp.json()
            features = data.get("features", [])
            if features:
                zone = features[0]["attributes"].get("FLD_ZONE", "X")
                return zone, zone in ("A", "AE", "AO", "AH", "V", "VE")
        except Exception:
            pass
        return "X", False

    def _parse_building_height(self, tags: Dict) -> Optional[float]:
        h = tags.get("height") or tags.get("building:height")
        if not h:
            return None
        try:
            return float(str(h).lower().replace("m", "").replace("ft", "").strip())
        except Exception:
            return None

    def _area_sqft(self, polygon: Polygon, latlon: LatLon) -> float:
        proj = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
        return transform(proj, polygon).area * 10.7639

    def _apply_setbacks(self, polygon: Polygon, setbacks: Dict, latlon: LatLon) -> Polygon:
        avg_m = (sum(setbacks.values()) / len(setbacks)) * 0.3048
        proj = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
        inv = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform
        projected = transform(proj, polygon)
        buffered = projected.buffer(-avg_m)
        if buffered.is_empty:
            buffered = projected.buffer(-1)
        return transform(inv, buffered)

    def _centroid(self, polygon: Polygon):
        c = polygon.centroid
        return (c.x, c.y)

    def _latlon_to_bbox(self, latlon: LatLon, radius_m: int) -> str:
        deg = radius_m / 111320
        return f"{latlon.lat-deg},{latlon.lon-deg},{latlon.lat+deg},{latlon.lon+deg}"

    def _box_polygon(self, latlon: LatLon, w: float, h: float) -> Dict[str, Any]:
        dlat = h / 111320
        dlon = w / (111320 * math.cos(math.radians(latlon.lat)))
        lat, lon = latlon.lat, latlon.lon
        return {"type": "Polygon", "coordinates": [[
            [lon-dlon, lat-dlat], [lon+dlon, lat-dlat],
            [lon+dlon, lat+dlat], [lon-dlon, lat+dlat], [lon-dlon, lat-dlat]
        ]]}

    def _way_to_feature(self, el: Dict, tags: Dict) -> Optional[Dict]:
        if "geometry" in el:
            return {"type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[n["lon"], n["lat"]] for n in el["geometry"]]},
                    "properties": tags}
        return None