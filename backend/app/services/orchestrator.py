"""
GenerationOrchestrator
Ties together all generators in sequence, emitting progress events.
"""
import uuid
import asyncio
import logging
from typing import Callable, Optional
from app.models.schemas import BuildingModel, ProjectSpec, GenerateRequest, Wall
from app.services.site_context import SiteContextService
from app.services.ai_room_program import get_ai_room_program, get_ai_unit_program

logger = logging.getLogger(__name__)
from app.services.ai_semantic_builder import generate_semantic_building
from app.constraints import LIMITS, limits_for_prompt
from app.generators.massing import MassingGenerator
from app.generators.floorplan import FloorplanGenerator
from app.constants import sfr_target_sqft, BuildingUse, FACADE_COLORS, ADU_MAX_SQFT
from app.generators.mep import MEPRouter
from app.generators.compliance import ComplianceEngine
from app.generators.facade import FacadeGenerator, extract_neighbor_style
from app.services.material_scorer import get_override_dict
from app.services.archetype_loader import (
    get_archetype, detect_archetype, load_archetype,
    apply_archetype_to_neighbor_style, apply_archetype_to_design_brief
)


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

        _use_raw = getattr(spec, 'building_use', 'multi_family')
        _use_str = getattr(_use_raw, 'value', str(_use_raw))
        is_sfr = _use_str in ('single_family', 'adu')
        is_adu = _use_str == 'adu'

        # ── Hard platform caps — single source of truth is constraints.py ──
        PLATFORM_MAX_SFR_SQFT  = LIMITS.sfr_max_sqft
        PLATFORM_MAX_MF_SQFT   = LIMITS.mf_max_sqft
        PLATFORM_MAX_STORIES   = LIMITS.max_stories
        PLATFORM_MAX_BEDROOMS  = LIMITS.adu_max_bedrooms if is_adu else LIMITS.sfr_max_bedrooms

        updates: dict = {}

        # Clamp bedrooms
        if is_sfr:
            br = getattr(spec, 'bedrooms', None) or (1 if is_adu else 3)
            max_br = getattr(spec, 'max_bedrooms', None) or (2 if is_adu else PLATFORM_MAX_BEDROOMS)
            br = min(br, max_br, 2 if is_adu else PLATFORM_MAX_BEDROOMS)
            updates['bedrooms'] = br

        # Clamp stories
        stories = spec.stories or 2
        max_floors = getattr(spec, 'max_floors', None) or PLATFORM_MAX_STORIES
        # Also derive a story cap from max_height_ft if provided
        max_h = getattr(spec, 'max_height_ft', None)
        if max_h:
            floor_h = spec.floor_to_floor_height_ft or 10.0
            max_floors = min(max_floors, max(1, int(max_h / floor_h)))
        if is_adu and getattr(spec, 'max_floors', None) is None:
            # Conservative default only. California ADU law permits local
            # objective height standards and some jurisdictions allow a taller
            # form, which can be supplied explicitly through ``max_floors``.
            max_floors = min(max_floors, 2)
        stories = min(stories, max_floors, PLATFORM_MAX_STORIES)
        updates['stories'] = stories

        # For SFR/ADU: derive target area from bedroom count + priority if not set
        pri = getattr(spec.priority, 'value', str(spec.priority))
        br_final = updates.get('bedrooms') or (getattr(spec, 'bedrooms', None) or 3)
        if is_sfr and not spec.target_gross_area_sqft:
            updates['target_gross_area_sqft'] = sfr_target_sqft(br_final, pri)

        # Clamp target area: user max_sqft → then platform cap
        raw_area = updates.get('target_gross_area_sqft') or spec.target_gross_area_sqft or 0
        user_max = getattr(spec, 'max_sqft', None)
        # 1,200 sqft is the conservative statewide detached-ADU default; local
        # ordinances may be less restrictive. ``adu_max_sqft`` lets a verified
        # jurisdiction-specific workflow raise that ceiling without silently
        # discarding the user's selected area.
        adu_cap = int((getattr(spec, 'fine_details', None) or {}).get('adu_max_sqft', ADU_MAX_SQFT))
        adu_cap = max(150, min(adu_cap, PLATFORM_MAX_SFR_SQFT))
        platform_cap = adu_cap if is_adu else (PLATFORM_MAX_SFR_SQFT if is_sfr else PLATFORM_MAX_MF_SQFT)
        if raw_area > 0:
            capped = raw_area
            if user_max:
                capped = min(capped, user_max)
            capped = min(capped, platform_cap)
            updates['target_gross_area_sqft'] = capped

        if updates:
            spec = spec.model_copy(update=updates)

        # Auto-resolve materials from priority + style, then merge user overrides on top
        pri_val  = getattr(spec.priority, 'value', str(spec.priority))
        sty_val  = getattr(spec.style, 'value', str(spec.style)) if getattr(spec, 'style', None) else None
        resolved_overrides = get_override_dict(pri_val, sty_val, spec.material_overrides)
        spec = spec.model_copy(update={"material_overrides": resolved_overrides})

        model = BuildingModel(project_id=project_id, spec=spec)
        log = model.generation_log

        # Step 1: Site context + infrastructure in parallel
        self.progress_cb(5, "Fetching site context and infrastructure…")
        log.append("Fetching site context from OSM + FEMA (parallel)")

        site_context_task = self.site_svc.build_context(
            latlon=spec.site.latlon,
            parcel_polygon=spec.site.parcel_polygon,
            address=spec.site.address,
        )
        if spec.site.latlon is not None:
            site_ctx, infra = await asyncio.gather(
                site_context_task,
                self._safe_infra(spec.site.latlon),
            )
        else:
            # Address-only requests must be geocoded before infrastructure can
            # be queried.  The old parallel call passed None and later crashed
            # while reading spec.site.latlon.lat.
            site_ctx = await site_context_task
            infra = await self._safe_infra(site_ctx.centroid)

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

        # ── Power infrastructure check ─────────────────────────────────────
        from app.models.schemas import ComplianceIssue
        has_power = bool(infra.get("power_lines") or infra.get("power_poles"))
        if not has_power:
            model.issues.append(ComplianceIssue(
                id="UTIL-001",
                type="utility",
                severity="warning",
                message="No utility power infrastructure (poles or lines) detected within 200m. "
                        "Verify electrical service availability before permitting.",
                fix_suggestion="Contact local utility provider to confirm service point location.",
                elements_involved=[],
            ))
            log.append("⚠ No power infrastructure detected near site")

        # ── Sqft guard — surface hard error if request still exceeds cap ──
        raw_req = spec.target_gross_area_sqft or 0
        if raw_req > PLATFORM_MAX_SFR_SQFT and is_sfr:
            model.issues.append(ComplianceIssue(
                id="AREA-001",
                type="compliance",
                severity="error",
                message=f"Requested area {raw_req:,.0f} sqft exceeds the 5,500 sqft SFR platform cap. "
                        f"Design has been clamped to {PLATFORM_MAX_SFR_SQFT:,} sqft.",
                fix_suggestion=f"Reduce target area to {PLATFORM_MAX_SFR_SQFT:,} sqft or below.",
                elements_involved=[],
            ))

        # Extract neighbor buildings — exclude the building being replaced (the one at site center)
        all_buildings = infra.get("buildings", [])
        resolved_site = spec.site.latlon or site_ctx.centroid
        site_lat = resolved_site.lat
        site_lon = resolved_site.lon
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

        # Step 2: Claude — one call that covers design brief + semantic model
        self.progress_cb(18, "Generating AI building model…")
        sem_result   = None
        design_brief = None
        try:
            spec_dict = {
                "stories": spec.stories,
                "structural_system": getattr(spec.structural_system, 'value', str(spec.structural_system)),
                "priority": getattr(spec.priority, 'value', str(spec.priority)),
                "unit_count": spec.unit_count,
                # User inputs — must reach Claude as hard constraints
                "bedrooms": spec.bedrooms or 3,
                "bathrooms": getattr(spec, 'bathrooms', None) or 2,
                "target_gross_area_sqft": spec.target_gross_area_sqft or 2000,
                "building_use": getattr(spec, 'building_use', 'single_family'),
            }
            site_ctx_dict = {
                "area_sqft": site_ctx.area_sqft,
                "flood_zone": site_ctx.flood_zone,
                "seismic_category": site_ctx.seismic_category,
                "terrain": terrain,
                "municipality": site_ctx.municipality or terrain.get("municipality", ""),
                "avg_elevation_m": terrain.get("avg_elevation_m", 0),
                "slope_pct": terrain.get("slope_pct", 0),
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

            # Detect archetype once — shared by both parallel AI calls
            _arch_id_pre = detect_archetype(spec, site_context=site_ctx) or ""
            _arch_display = ""
            if _arch_id_pre:
                _a = load_archetype(_arch_id_pre)
                _arch_display = (_a or {}).get("display_name", _arch_id_pre)

            # ── ONE parallel Claude call instead of two sequential ones ──────
            # semantic_builder replaces ai_brief entirely — same info, one call.
            sem_result = await generate_semantic_building(
                spec_dict, site_ctx_dict, neighbor_analysis,
                archetype_id=_arch_id_pre,
                archetype_display_name=_arch_display,
            )
            log.append(f"Semantic [{sem_result.get('_source','?')}]: {sem_result.get('style_intent','')[:80]}")

            # Derive design_brief from semantic model so the classic facade
            # pipeline still gets real values (no separate ai_brief call)
            s_mat = (sem_result.get("materials") or {}).get("wall_body", "stucco")
            s_roof = (sem_result.get("roof") or {})
            s_fp   = sem_result.get("footprint") or {}
            s_trim = sem_result.get("trim") or {}
            design_brief = {
                "shape":               s_fp.get("shape", "rectangle"),
                "width_m":             s_fp.get("width_m", neighbor_analysis.get("avg_width_m", 12)),
                "depth_m":             s_fp.get("depth_m", neighbor_analysis.get("avg_depth_m", 14)),
                "facade_material":     s_mat,
                "trim_color":          (sem_result.get("materials") or {}).get("trim_color", "#4a4a4a"),
                "horizontal_bands":    bool(s_trim.get("band_height_m", 0) > 0),
                "band_h_frac":         min(0.30, (s_trim.get("band_height_m", 0) / 3.0)),
                "face_offset":         0.09,
                "window_ratio":        0.38,
                "win_h_frac":          0.50,
                "win_w_cap_m":         1.8,
                "balcony_depth_m":     next((p.get("depth_m", 0) for p in (sem_result.get("porches") or []) if p.get("type") == "balcony"), 0.0),
                "balcony_every_n_floors": 2,
                "porch_depth_m":       next((p.get("depth_m", 0) for p in (sem_result.get("porches") or []) if p.get("type") == "entry"), 0.0),
                "roof_type":           s_roof.get("type", "gabled"),
                "roof_pitch_12":       s_roof.get("pitch_12", 5),
                "ground_floor_height_boost_m": 0.3,
                "source":              sem_result.get("_source", "fallback"),
            }

            brief_mat = design_brief.get("facade_material")
            if brief_mat and brief_mat in FACADE_COLORS:
                neighbor_style["dominant_material"] = brief_mat
                neighbor_style["facade_color"] = FACADE_COLORS[brief_mat]
            if design_brief.get("balcony_depth_m", 0) > 0:
                neighbor_style["has_balconies"] = True
            neighbor_style["window_ratio"]           = design_brief["window_ratio"]
            neighbor_style["horizontal_bands"]       = design_brief["horizontal_bands"]
            neighbor_style["balcony_every_n_floors"] = design_brief["balcony_every_n_floors"]

        except Exception as e:
            sem_result   = None
            design_brief = None
            msg = f"⚠ AI semantic builder failed: {e}"
            log.append(msg)
            logger.error(msg, exc_info=True)

        # ── Archetype detection — runs after spec is finalised ────────────────
        archetype = get_archetype(spec, site_context=site_ctx)
        if archetype:
            log.append(f"Archetype detected: {archetype['display_name']}")
            neighbor_style = apply_archetype_to_neighbor_style(archetype, neighbor_style)
            design_brief   = apply_archetype_to_design_brief(archetype, design_brief)

        # Step 3: Massing with neighbor awareness
        self.progress_cb(30, "Generating massing options…")
        log.append("Generating 3 massing options with neighbor context")
        # Archetype arch_style (set in design_brief by apply_archetype_to_design_brief)
        # takes priority over user's raw style choice so the massing generator
        # receives e.g. 'classic_gabled' for Victorian, not whatever the user typed.
        _massing_style = (
            (design_brief.get('arch_style') if design_brief else None)
            or getattr(spec, 'style', None)
        )
        massing_options, levels = self.massing_gen.generate(
            spec, site_ctx,
            neighbor_buildings=neighbor_buildings,
            design_brief=design_brief,
            style=_massing_style,
        )
        model.massing_options = massing_options
        model.levels = levels
        if not massing_options:
            raise RuntimeError("Massing generation returned no buildable options")
        if not 0 <= massing_choice < len(massing_options):
            log.append(f"Massing choice {massing_choice} unavailable; using Option A")
            massing_choice = 0
        model.chosen_massing_index = massing_choice
        chosen = massing_options[massing_choice]
        log.append(f"Chosen massing: Option {chosen['label']} — {chosen['name']}")

        # Step 4a: AI room program — Claude Haiku generates dynamic layout from blueprint index
        self.progress_cb(42, "Generating AI room program…")
        archetype_id_str = (archetype or {}).get('id', '')
        _fp_coords = chosen.get("footprint", [])
        _fp_xs = [c[0] for c in _fp_coords]
        _fp_zs = [c[1] for c in _fp_coords]
        _fp_w  = (max(_fp_xs) - min(_fp_xs)) if _fp_xs else 12.0
        _fp_d  = (max(_fp_zs) - min(_fp_zs)) if _fp_zs else 14.0
        _target_sqft = spec.target_gross_area_sqft or sfr_target_sqft(
            spec.bedrooms or 3, getattr(spec.priority, 'value', 'cost')
        )
        _br = spec.bedrooms or 3

        ai_floor_program = None
        ai_unit_program  = None
        _site_ctx_for_ai = {
            "terrain": terrain,
            "municipality": site_ctx.municipality,
            "weather": site_ctx.weather.dict() if site_ctx.weather else {},
            "seismic_category": site_ctx.seismic_category,
        }

        if is_sfr:
            try:
                ai_floor_program = await get_ai_room_program(
                    footprint_w_m=_fp_w,
                    footprint_d_m=_fp_d,
                    archetype_id=archetype_id_str or "production_tract",
                    bedrooms=_br,
                    stories=spec.stories or 2,
                    target_sqft=_target_sqft,
                    site_ctx=_site_ctx_for_ai,
                    bathrooms=getattr(spec, 'bathrooms', None) or 2.0,
                    archetype_data=archetype,
                )
                if ai_floor_program:
                    log.append(f"AI room program: {sum(len(f['rows']) for f in ai_floor_program)} rows across {len(ai_floor_program)} floors")
                else:
                    log.append("⚠ AI room program: no output — using static fallback")
            except Exception as _e:
                msg = f"⚠ AI room program failed: {_e}"
                log.append(msg)
                logger.error(msg, exc_info=True)
        else:
            # Multi-family: Claude generates unit mix + room templates
            try:
                ai_unit_program = await get_ai_unit_program(
                    footprint_w_m=_fp_w,
                    footprint_d_m=_fp_d,
                    stories=spec.stories or 3,
                    unit_count=getattr(spec, 'unit_count', None),
                    bedrooms_per_unit=_br,
                    site_ctx={
                        **_site_ctx_for_ai,
                        "seismic_category": site_ctx.seismic_category,
                        "municipality": site_ctx.municipality,
                    },
                    target_sqft=_target_sqft,
                    archetype_data=archetype,
                )
                if ai_unit_program:
                    mix = ai_unit_program.get("unit_mix", {})
                    log.append(f"AI unit program: {mix}")
                else:
                    log.append("⚠ AI unit program: no output — using static unit templates")
            except Exception as _e:
                msg = f"⚠ AI unit program failed: {_e}"
                log.append(msg)
                logger.error(msg, exc_info=True)

        # Step 4b: Floorplan — uses AI program if available, else static programs
        self.progress_cb(45, "Generating floorplans…")
        log.append("Generating floorplan layouts")
        rooms, walls = self.floorplan_gen.generate(
            chosen, spec, levels, archetype=archetype,
            ai_room_program=ai_floor_program,
            ai_unit_program=ai_unit_program,
        )
        model.rooms = rooms
        model.walls = walls
        unit_count = len(set(r.unit_id for r in rooms if r.unit_id))
        log.append(f"Generated {len(rooms)} rooms across {len(levels)} levels ({unit_count} units)")

        # Step 5: Facade details
        self.progress_cb(60, "Generating facade details…")
        facade_meshes = self.facade_gen.generate(
            chosen, walls, levels, neighbor_style, design_brief,
            rooms=rooms, semantic_model=sem_result,
        )
        model.neighbor_style = neighbor_style
        model.design_brief = design_brief
        stair_meshes = self._generate_stair_meshes(rooms, levels, spec)
        door_meshes, wall_splits = self._generate_interior_door_meshes(rooms, walls, levels, spec)
        # Replace door-bearing walls with left+right segments to create visual openings
        if wall_splits:
            model.walls = [seg for w in walls
                           for seg in (wall_splits.get(w.id) or [w])]
        model.meshes = facade_meshes + stair_meshes + door_meshes  # type: ignore
        log.append(f"Facade: {len(facade_meshes)} detail meshes + {len(door_meshes)} interior doors")

        # Step 6: MEP routing
        self.progress_cb(72, "Routing MEP systems…")
        log.append("Routing plumbing, electrical, HVAC")
        power_conn = infra.get("power_connection") if infra else None
        # Enrich power_connection with local-meter offsets (dx_m, dz_m) so MEP can draw
        # the utility lateral toward the pole without needing lat/lon inside the generator.
        if power_conn:
            try:
                coords = power_conn.get("geometry", {}).get("coordinates", [])
                if len(coords) == 2:
                    _lat, _lon = resolved_site.lat, resolved_site.lon
                    import math as _m2
                    _dlon = coords[1][0] - _lon
                    _dlat = coords[1][1] - _lat
                    _mpp_lat = 111320.0
                    _mpp_lon = 111320.0 * _m2.cos(_m2.radians(_lat))
                    power_conn = dict(power_conn)
                    power_conn["dx_m"] = round(_dlon * _mpp_lon, 1)
                    power_conn["dz_m"] = round(-_dlat * _mpp_lat, 1)  # Z = south (negative lat)
            except Exception:
                pass
        mep_elements = self.mep_router.route(
            rooms, walls, levels, spec,
            power_connection=power_conn,
            archetype=archetype,
        )
        model.mep_elements = mep_elements
        plumbing = len([e for e in mep_elements if e.system == "plumbing"])
        electrical = len([e for e in mep_elements if e.system == "electrical"])
        hvac = len([e for e in mep_elements if e.system == "hvac"])
        fire = len([e for e in mep_elements if e.system == "fire"])
        log.append(
            f"MEP: {plumbing} plumbing | {electrical} electrical | "
            f"{hvac} HVAC | {fire} fire-protection elements"
        )

        # Step 6b: Structural engineering
        self.progress_cb(76, "Computing structural members…")
        from app.generators.structural_engine import StructuralEngine
        struct_engine = StructuralEngine()
        massing_footprint = [(c[0], c[1]) for c in chosen["footprint"]]
        structural_members = struct_engine.generate(
            footprint_coords=massing_footprint,
            levels=levels,
            structural_system=spec.structural_system,
            site_ctx_dict={
                "seismic_category": site_ctx.seismic_category,
                "wind_speed_mph": site_ctx.wind_speed_mph,
            },
            target_area_m2=chosen.get("total_area_m2", 200.0),
            is_sfr=is_sfr,
        )
        from app.models.schemas import StructuralMember as StructMemberSchema
        model.structural_members = [StructMemberSchema(**m) for m in structural_members]
        log.append(f"Structural: {len(structural_members)} members computed")

        # Step 6c: Clash detection
        self.progress_cb(80, "Running MEP clash detection…")
        from app.generators.clash_detector import detect_clashes, get_routing_summary
        clash_issues = detect_clashes(model.mep_elements)
        model.issues.extend(clash_issues)
        routing_summary = get_routing_summary(model.mep_elements)
        log.append(f"Clash detection: {len(clash_issues)} clashes found")
        for sys_name, stats in routing_summary.items():
            log.append(f"  {sys_name}: {stats['count']} elements")

        # Step 7: Compliance
        self.progress_cb(88, "Running compliance checks…")
        log.append("Running CA compliance rules")
        issues = self.compliance_eng.run(model)
        model.issues = issues
        errors = len([i for i in issues if i.severity == "error"])
        warnings = len([i for i in issues if i.severity == "warning"])
        log.append(f"Compliance: {errors} errors, {warnings} warnings")

        # Semantic model came from the parallel call at the top — attach it here
        model.semantic_model = sem_result if sem_result else None

        self.progress_cb(100, "Done!")
        log.append("Generation complete")
        return model

    def _generate_stair_meshes(self, rooms, levels, spec) -> list:
        """
        Build 3D stair step meshes for every stair room that has a level above it.
        Each stair room polygon (x, z in metres) becomes a set of step boxes rising
        from the floor elevation of its level up to the next level's elevation.
        """
        import uuid as _uuid
        meshes = []
        floor_h_m = spec.floor_to_floor_height_ft * 0.3048
        level_elevations = {lvl.index: lvl.elevation_ft * 0.3048 for lvl in levels}
        max_level = max(level_elevations.keys()) if level_elevations else 0

        # One staircase per level — take the first stair room found on each level
        # (the ground-floor ADU program places two stair fragments; only one set of steps needed).
        seen_levels: set = set()
        stair_rooms = []
        for r in rooms:
            if r.type == "stair" and r.level not in seen_levels:
                seen_levels.add(r.level)
                stair_rooms.append(r)

        for room in stair_rooms:
            lvl = room.level
            if lvl >= max_level:
                continue  # top floor stair landing — no steps needed
            y_bot = level_elevations.get(lvl, lvl * floor_h_m)
            y_top = level_elevations.get(lvl + 1, y_bot + floor_h_m)
            rise_total = y_top - y_bot
            if rise_total <= 0:
                continue

            poly = room.polygon  # [[x, z], ...]
            if len(poly) < 3:
                continue
            xs = [p[0] for p in poly]
            zs = [p[1] for p in poly]
            rx0, rx1 = min(xs), max(xs)
            rz0, rz1 = min(zs), max(zs)
            stair_w = rx1 - rx0
            stair_d = rz1 - rz0
            if stair_w < 0.3 or stair_d < 0.3:
                continue

            # Run steps along the longer axis; use 60% of the cross-dimension,
            # centred, so the stair is visually narrow and stays inside the room.
            run_along_z = stair_d >= stair_w
            span = stair_d if run_along_z else stair_w
            cross = stair_w if run_along_z else stair_d
            tread_w = cross * 0.60        # 60% of room cross-width
            tread_inset = cross * 0.20    # centred gap on each side

            n_steps = max(4, round(rise_total / 0.18))
            step_rise = rise_total / n_steps
            step_run = span / n_steps

            for s in range(n_steps):
                s_y_bot = y_bot
                s_y_top = y_bot + step_rise * (s + 1)
                if run_along_z:
                    sz0 = rz0 + step_run * s
                    sz1 = sz0 + step_run
                    sx0 = rx0 + tread_inset
                    sx1 = rx0 + tread_inset + tread_w
                else:
                    sx0 = rx0 + step_run * s
                    sx1 = sx0 + step_run
                    sz0 = rz0 + tread_inset
                    sz1 = rz0 + tread_inset + tread_w

                sv = [
                    [sx0, s_y_bot, sz0], [sx1, s_y_bot, sz0],
                    [sx1, s_y_bot, sz1], [sx0, s_y_bot, sz1],
                    [sx0, s_y_top, sz0], [sx1, s_y_top, sz0],
                    [sx1, s_y_top, sz1], [sx0, s_y_top, sz1],
                ]
                sf = [
                    [4, 5, 6], [4, 6, 7],  # top tread
                    [0, 1, 5], [0, 5, 4],  # front riser
                    [0, 4, 7], [0, 7, 3],  # left side
                    [1, 2, 6], [1, 6, 5],  # right side
                ]
                meshes.append({
                    "element_id": f"stair_{room.id}_step_{s}_{_uuid.uuid4().hex[:4]}",
                    "element_type": "stair",
                    "vertices": sv, "faces": sf,
                    "level": lvl, "color": "#b8996a",
                })
        return meshes

    def _generate_interior_door_meshes(self, rooms, walls, levels, spec) -> list:
        """
        BFS-based interior door placement.

        'Open' room types (corridor, living, stair, foyer…) are passthrough — no door
        is needed to enter them.  'Closed' rooms (bedroom, bathroom, kitchen…) receive
        exactly ONE door placed on the wall that first connects them to the reachable
        frontier, producing minimum necessary doors while keeping all rooms accessible.

        Algorithm:
          1. For each interior wall, offset its midpoint ±15 cm along the normal and
             ray-cast into room polygons to find the two adjacent rooms.
          2. Build a room adjacency graph from those pairs.
          3. BFS from all open rooms; when we first reach a closed room, record its
             incoming wall for door placement.  Open→open transitions get no door.
        """
        import math as _math
        import uuid as _uuid

        OPEN_TYPES = {
            'corridor', 'hallway', 'living', 'foyer',
            'entry', 'dining', 'unit', 'garage', 'utility', 'laundry',
        }
        NO_DOOR_TYPES = {'attic', 'roof'}  # never need a door (stair removed — gets entry door)

        floor_h_m = spec.floor_to_floor_height_ft * 0.3048
        level_elevations = {lvl.index: lvl.elevation_ft * 0.3048 for lvl in levels}

        # ── Inline ray-cast point-in-polygon (avoids shapely import) ─────────
        def _pip(px: float, pz: float, poly) -> bool:
            inside = False
            n = len(poly)
            j = n - 1
            for i in range(n):
                xi, zi = poly[i][0], poly[i][1]
                xj, zj = poly[j][0], poly[j][1]
                if ((zi > pz) != (zj > pz)):
                    denom = zj - zi
                    if abs(denom) > 1e-12:
                        if px < (xj - xi) * (pz - zi) / denom + xi:
                            inside = not inside
                j = i
            return inside

        meshes: list = []
        wall_splits: dict = {}   # wall.id → [Wall_left, Wall_right] replacement segments
        int_walls = [w for w in walls if not w.is_exterior]
        level_indices = sorted(set(r.level for r in rooms))

        for lvl_idx in level_indices:
            # Sort ascending by area so specific sub-rooms are PIP-tested before
            # enclosing shell rooms (e.g. unit shells in MF buildings).
            lvl_rooms = sorted(
                [r for r in rooms if r.level == lvl_idx],
                key=lambda r: r.area_sqft,
            )
            y_base = level_elevations.get(lvl_idx, lvl_idx * floor_h_m)

            if len(lvl_rooms) < 2:
                continue

            lvl_int_walls = [w for w in int_walls if w.level == lvl_idx]

            # ── Step 1: map each interior wall to its two adjacent rooms ──────
            # Probe ±35 cm along the wall normal so we reliably land inside each
            # room rather than on its edge.  Sort rooms smallest-first so the PIP
            # test hits the most specific (sub-)room before any enclosing shell.
            wall_to_rooms: dict = {}
            _sorted_rooms = sorted(lvl_rooms, key=lambda r: r.area_sqft)
            _room_area    = {r.id: r.area_sqft for r in lvl_rooms}
            MIN_ROOM_SQFT = 10.0   # ignore tiny clipping slivers

            for wall in lvl_int_walls:
                s, e = wall.start, wall.end
                dx = e[0] - s[0]
                dz = e[1] - s[1]
                wl = _math.sqrt(dx * dx + dz * dz)
                if wl < 0.1:
                    continue
                nx, nz = -dz / wl, dx / wl
                mx = (s[0] + e[0]) / 2
                mz = (s[1] + e[1]) / 2
                OFFSET = 0.35   # was 0.15 — deeper probe avoids landing on polygon edge

                sides: list = []
                for sign in (-1, 1):
                    tx, tz = mx + nx * OFFSET * sign, mz + nz * OFFSET * sign
                    hit = None
                    for room in _sorted_rooms:
                        if (room.polygon
                                and _room_area.get(room.id, 0) >= MIN_ROOM_SQFT
                                and _pip(tx, tz, room.polygon)):
                            hit = room.id
                            break
                    sides.append(hit)

                if (sides[0] and sides[1] and sides[0] != sides[1]
                        and _room_area.get(sides[0], 0) >= MIN_ROOM_SQFT
                        and _room_area.get(sides[1], 0) >= MIN_ROOM_SQFT):
                    wall_to_rooms[wall.id] = (sides[0], sides[1], wall)

            # ── Step 2: build room adjacency graph ────────────────────────────
            room_nbrs: dict = {r.id: [] for r in lvl_rooms}
            for wid, (ra, rb, wall) in wall_to_rooms.items():
                room_nbrs[ra].append((rb, wall))
                room_nbrs[rb].append((ra, wall))

            room_by_id = {r.id: r for r in lvl_rooms}

            # ── Step 3: BFS from open rooms ───────────────────────────────────
            open_ids = [r.id for r in lvl_rooms if r.type in OPEN_TYPES]
            if not open_ids:
                # Fallback: start from the largest room on this level
                open_ids = [max(lvl_rooms, key=lambda r: r.area_sqft).id]

            # door_granted[room_id] = True once that room has been given one door.
            # Acts as the per-room weight: False = no door yet, True = door placed.
            door_granted: dict = {}
            reachable: set = set(open_ids)
            queue: list = list(open_ids)
            door_walls: list = []

            while queue:
                cur_id = queue.pop(0)

                for nbr_id, wall in room_nbrs.get(cur_id, []):
                    if nbr_id in reachable:
                        continue  # already accessible — no second door ever

                    reachable.add(nbr_id)
                    queue.append(nbr_id)

                    nbr_room = room_by_id.get(nbr_id)
                    if nbr_room is None or nbr_room.type in NO_DOOR_TYPES:
                        continue  # stair/attic — open passage, no door

                    # Place exactly ONE door the first time we reach a closed room.
                    # Open rooms (corridor, living, hallway…) need no door.
                    if nbr_room.type not in OPEN_TYPES and not door_granted.get(nbr_id):
                        door_walls.append(wall)
                        door_granted[nbr_id] = True

            # ── Step 4: generate door mesh for each recorded wall ──────────────
            for wall in door_walls:
                s, e = wall.start, wall.end
                dx = e[0] - s[0]
                dz = e[1] - s[1]
                wl = _math.sqrt(dx * dx + dz * dz)
                if wl < 1.0:
                    continue

                ux, uz = dx / wl, dz / wl
                nx_d = -dz / wl
                nz_d =  dx / wl

                cx = (s[0] + e[0]) / 2
                cz = (s[1] + e[1]) / 2

                door_w = min(0.92, wl - 0.25)
                if door_w < 0.7:
                    continue
                door_h = 2.05
                hw = door_w / 2

                # ── Split wall into left + right segments around door opening ──
                MIN_SEG = 0.12
                split_lx = cx - ux * hw
                split_lz = cz - uz * hw
                split_rx = cx + ux * hw
                split_rz = cz + uz * hw
                seg_len  = wl / 2 - hw   # symmetric on both sides
                segs = []
                if seg_len > MIN_SEG:
                    segs.append(Wall(
                        id=f"{wall.id}_L",
                        start=list(s),
                        end=[split_lx, split_lz],
                        height_ft=wall.height_ft,
                        level=wall.level,
                        is_exterior=False,
                        is_shear=wall.is_shear,
                    ))
                    segs.append(Wall(
                        id=f"{wall.id}_R",
                        start=[split_rx, split_rz],
                        end=list(e),
                        height_ft=wall.height_ft,
                        level=wall.level,
                        is_exterior=False,
                        is_shear=wall.is_shear,
                    ))
                if segs:
                    wall_splits[wall.id] = segs

                # Door panel sits 5mm proud of each wall face.
                # Interior walls are 0.2m thick (0.1m half-thickness) so
                # FOF = 0.105 places door face just outside both wall surfaces.
                FOF = 0.105
                verts = [
                    [cx - ux*hw + nx_d*FOF, y_base,           cz - uz*hw + nz_d*FOF],  # 0
                    [cx + ux*hw + nx_d*FOF, y_base,           cz + uz*hw + nz_d*FOF],  # 1
                    [cx + ux*hw + nx_d*FOF, y_base + door_h,  cz + uz*hw + nz_d*FOF],  # 2
                    [cx - ux*hw + nx_d*FOF, y_base + door_h,  cz - uz*hw + nz_d*FOF],  # 3
                    [cx - ux*hw - nx_d*FOF, y_base,           cz - uz*hw - nz_d*FOF],  # 4
                    [cx + ux*hw - nx_d*FOF, y_base,           cz + uz*hw - nz_d*FOF],  # 5
                    [cx + ux*hw - nx_d*FOF, y_base + door_h,  cz + uz*hw - nz_d*FOF],  # 6
                    [cx - ux*hw - nx_d*FOF, y_base + door_h,  cz - uz*hw - nz_d*FOF],  # 7
                ]
                faces = [
                    [0, 1, 2], [0, 2, 3],   # front face
                    [7, 6, 5], [7, 5, 4],   # back face
                    [0, 4, 5], [0, 5, 1],   # bottom edge
                    [1, 5, 6], [1, 6, 2],   # right edge
                    [2, 6, 7], [2, 7, 3],   # top edge
                    [3, 7, 4], [3, 4, 0],   # left edge
                ]
                meshes.append({
                    "element_id": f"int_door_{_uuid.uuid4().hex[:6]}",
                    "element_type": "interior_door",
                    "vertices": verts,
                    "faces": faces,
                    "level": lvl_idx,
                    "color": "#8b6f47",
                })

        return meshes, wall_splits

    async def _safe_infra(self, latlon) -> dict:
        """Fetch nearby infrastructure, return empty dict on failure."""
        try:
            return await self.site_svc.get_nearby_infrastructure(latlon, radius_m=200)
        except Exception:
            return {}

