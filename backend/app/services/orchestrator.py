"""
GenerationOrchestrator
Ties together all generators in sequence, emitting progress events.
"""
import uuid
import asyncio
from typing import Callable, Optional
from app.models.schemas import BuildingModel, ProjectSpec, GenerateRequest
from app.services.site_context import SiteContextService
from app.services.ai_brief import get_design_brief
from app.generators.massing import MassingGenerator
from app.generators.floorplan import FloorplanGenerator
from app.generators.mep import MEPRouter
from app.generators.compliance import ComplianceEngine
from app.generators.facade import FacadeGenerator, extract_neighbor_style


class GenerationOrchestrator:

    def __init__(self, progress_cb: Optional[Callable[[int, str], None]] = None):
        self.progress_cb = progress_cb or (lambda p, s: None)
        self.site_svc = SiteContextService()
        self.massing_gen = MassingGenerator()
        self.floorplan_gen = FloorplanGenerator()
        self.mep_router = MEPRouter()
        self.compliance_eng = ComplianceEngine()
        self.facade_gen = FacadeGenerator()

    async def run(self, spec: ProjectSpec, massing_choice: int = 0) -> BuildingModel:
        project_id = str(uuid.uuid4())
        model = BuildingModel(project_id=project_id, spec=spec)
        log = model.generation_log

        # Step 1: Site context + infrastructure in parallel
        self.progress_cb(5, "Fetching site context and infrastructure…")
        log.append("Fetching site context from OSM + FEMA (parallel)")

        site_ctx, infra = await asyncio.gather(
            self.site_svc.build_context(
                latlon=spec.site.latlon,
                parcel_polygon=spec.site.parcel_polygon,
                address=spec.site.address,
            ),
            self._safe_infra(spec),
        )

        model.site_context = site_ctx
        terrain = site_ctx.terrain or {}
        slope_msg = (
            f"Slope: {terrain.get('slope_pct', 0):.1f}% ({terrain.get('slope_degrees', 0):.1f}°)"
            if terrain.get("is_sloped") else "Slope: flat"
        )
        log.append(
            f"Site area: {site_ctx.area_sqft:.0f} sqft | "
            f"Flood zone: {site_ctx.flood_zone} | "
            f"Seismic: {site_ctx.seismic_category} | {slope_msg}"
        )

        # Extract neighbor buildings — exclude the building being replaced (the one at site center)
        all_buildings = infra.get("buildings", [])
        site_lat = spec.site.latlon.lat
        site_lon = spec.site.latlon.lon
        import math as _math

        def _dist_to_site(b):
            coords = b.get("geometry", {}).get("coordinates", [[]])[0]
            if not coords:
                return 9999
            cx = sum(c[0] for c in coords) / len(coords)
            cy = sum(c[1] for c in coords) / len(coords)
            dx = (cx - site_lon) * 111320 * _math.cos(_math.radians(site_lat))
            dy = (cy - site_lat) * 111320
            return _math.sqrt(dx*dx + dy*dy)

        # If user clicked on an existing building (parcel has one), exclude it from neighbors
        # A building within 8m of the site click is the one being replaced
        neighbor_buildings = [b for b in all_buildings if _dist_to_site(b) > 8]
        neighbor_style = extract_neighbor_style(all_buildings)  # style from all including replaced
        replaced_count = len(all_buildings) - len(neighbor_buildings)

        log.append(
            f"Neighbors: {len(neighbor_buildings)} buildings ({replaced_count} excluded as replaced) | "
            f"Dominant material: {neighbor_style.get('dominant_material', 'unknown')} | "
            f"Avg height: {neighbor_style.get('avg_neighbor_height_m', 0):.1f}m"
        )

        # Step 2: Claude design brief from neighbor context
        self.progress_cb(18, "Generating AI design brief…")
        log.append("Calling Claude for architectural design brief")
        try:
            spec_dict = {
                "stories": spec.stories,
                "structural_system": getattr(spec.structural_system, 'value', str(spec.structural_system)),
                "priority": spec.priority,
                "unit_count": spec.unit_count,
            }
            site_ctx_dict = {
                "area_sqft": site_ctx.area_sqft,
                "flood_zone": site_ctx.flood_zone,
                "seismic_category": site_ctx.seismic_category,
                "terrain": terrain,
            }
            neighbor_analysis = {
                "count": len(neighbor_buildings),
                "dominant_material": neighbor_style.get("dominant_material", "stucco"),
                "dominant_shape": neighbor_style.get("dominant_shape", "rectangle"),
                "has_balconies": neighbor_style.get("has_balconies", False),
                "avg_height_m": neighbor_style.get("avg_neighbor_height_m", 6),
                "avg_stories": neighbor_style.get("avg_stories", 2),
                "avg_width_m": neighbor_style.get("avg_width_m", 12),
                "avg_depth_m": neighbor_style.get("avg_depth_m", 14),
            }

            design_brief = await get_design_brief(spec_dict, site_ctx_dict, neighbor_analysis)
            log.append(f"Design brief: shape={design_brief.get('shape')} mat={design_brief.get('facade_material')} w={design_brief.get('width_m')}m d={design_brief.get('depth_m')}m | source={design_brief.get('source')}")

            # Merge brief's facade_material back into neighbor_style so the
            # facade generator and frontend both use the Claude-recommended material
            FACADE_COLORS = {
                "brick": "#b5651d", "concrete": "#9ca3af", "glass": "#bfdbfe",
                "wood": "#a67c52", "stone": "#b8a99a", "metal": "#94a3b8",
                "stucco": "#d6cbb8", "plaster": "#e8dcc8",
            }
            brief_mat = design_brief.get("facade_material")
            if brief_mat and brief_mat in FACADE_COLORS:
                neighbor_style["dominant_material"] = brief_mat
                neighbor_style["facade_color"] = FACADE_COLORS[brief_mat]
            if design_brief.get("balcony_depth_m", 0) > 0:
                neighbor_style["has_balconies"] = True
                neighbor_style["balcony_depth_m"] = design_brief["balcony_depth_m"]
            neighbor_style["window_ratio"] = design_brief.get("window_ratio", 0.35)
            neighbor_style["horizontal_bands"] = design_brief.get("horizontal_bands", True)
            neighbor_style["balcony_every_n_floors"] = design_brief.get("balcony_every_n_floors", 1)

        except Exception as e:
            design_brief = None
            log.append(f"Design brief failed ({str(e)[:60]}) — using neighbor dims directly")

        # Step 3: Massing with neighbor awareness
        self.progress_cb(30, "Generating massing options…")
        log.append("Generating 3 massing options with neighbor context")
        massing_options, levels = self.massing_gen.generate(
            spec, site_ctx,
            neighbor_buildings=neighbor_buildings,
            design_brief=design_brief,
        )
        model.massing_options = massing_options
        model.levels = levels
        model.chosen_massing_index = massing_choice
        chosen = massing_options[massing_choice]
        log.append(f"Chosen massing: Option {chosen['label']} — {chosen['name']}")

        # Step 4: Floorplan
        self.progress_cb(45, "Generating floorplans…")
        log.append("Generating floorplan layouts")
        rooms, walls = self.floorplan_gen.generate(chosen, spec, levels)
        model.rooms = rooms
        model.walls = walls
        unit_count = len(set(r.unit_id for r in rooms if r.unit_id))
        log.append(f"Generated {len(rooms)} rooms across {len(levels)} levels ({unit_count} units)")

        # Step 5: Facade details
        self.progress_cb(60, "Generating facade details…")
        facade_meshes = self.facade_gen.generate(chosen, walls, levels, neighbor_style, design_brief)
        model.neighbor_style = neighbor_style
        model.design_brief = design_brief
        model.meshes = facade_meshes  # type: ignore
        log.append(f"Facade: {len(facade_meshes)} detail meshes (windows, balconies, parapet)")

        # Step 6: MEP routing
        self.progress_cb(72, "Routing MEP systems…")
        log.append("Routing plumbing, electrical, HVAC")
        mep_elements = self.mep_router.route(rooms, walls, levels, spec)
        model.mep_elements = mep_elements
        plumbing = len([e for e in mep_elements if e.system == "plumbing"])
        electrical = len([e for e in mep_elements if e.system == "electrical"])
        hvac = len([e for e in mep_elements if e.system == "hvac"])
        log.append(f"MEP: {plumbing} plumbing | {electrical} electrical | {hvac} HVAC elements")

        # Step 7: Compliance
        self.progress_cb(88, "Running compliance checks…")
        log.append("Running CA compliance rules")
        issues = self.compliance_eng.run(model)
        model.issues = issues
        errors = len([i for i in issues if i.severity == "error"])
        warnings = len([i for i in issues if i.severity == "warning"])
        log.append(f"Compliance: {errors} errors, {warnings} warnings")

        self.progress_cb(100, "Done!")
        log.append("Generation complete")
        return model

    async def _safe_infra(self, spec: ProjectSpec) -> dict:
        """Fetch nearby infrastructure, return empty dict on failure."""
        try:
            return await self.site_svc.get_nearby_infrastructure(spec.site.latlon, radius_m=200)
        except Exception:
            return {}

