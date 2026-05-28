"""
ComplianceEngine
Deterministic rule checks for CA multifamily low-rise.
Covers CEC/CMC/CPC, California Energy Code, IBC Structural, and Seismic Safety.
"""
import uuid
from typing import List
from app.models.schemas import BuildingModel, ComplianceIssue, Room, Wall

RULES = {
    # ── Building & Life Safety (IBC / CBC) ──
    "CA_STORIES": {
        "citation": "Demo constraint — max 3 stories",
        "max": 3,
    },
    "CA_CORRIDOR_WIDTH": {
        "citation": "CBC Section 1020.2 — Min corridor width 44in (3.67ft)",
        "min_ft": 3.67,
    },
    "CA_DOOR_WIDTH": {
        "citation": "CBC Section 1010.1.1 — Min door clear width 32in",
        "min_in": 32,
    },
    "CA_EGRESS_TRAVEL_DIST": {
        "citation": "CBC Section 1017.2 — Max travel distance 250ft (sprinklered) / 200ft",
        "limit_ft": 200,
    },
    "CA_EGRESS_EXITS": {
        "citation": "CBC Section 1006.3.4 — ≥2 exits required for floor area >500 sqft with >10 occupants",
    },
    "CA_FLOOD_REVIEW": {
        "citation": "FEMA NFIP — Flood zone requires elevation certificate review",
    },
    # ── CEC (California Electrical Code) ──
    "CEC_OUTLET_SPACING": {
        "citation": "CEC Article 210 — Max 6ft spacing between outlets in living areas",
        "max_spacing_ft": 6,
    },
    "CEC_KITCHEN_CIRCUIT": {
        "citation": "CEC Article 210 — ≥2 x 20A dedicated circuits for kitchen countertop",
        "min_circuits": 2,
    },
    "CEC_BATHROOM_CIRCUIT": {
        "citation": "CEC Article 210 — 20A dedicated circuit per bathroom group",
        "min_per_bathroom": 1,
    },
    "CEC_GFCI_PROTECTION": {
        "citation": "CEC Article 210.8 — GFCI protection required on all wet-area outlets",
    },
    # ── CMC (California Mechanical Code) ──
    "CMC_DUCTWORK_INSULATION": {
        "citation": "CMC Section 601 — Ductwork R-value ≥8 (or R-4.2 min in occupied space)",
        "min_r_value": 8,
    },
    "CMC_VENTILATION_RATE": {
        "citation": "CMC Section 402 — Min 0.35 CFM/sqft or 15 CFM/person outdoor air",
        "min_cfm_per_sqft": 0.35,
    },
    "CMC_DUCT_SEALING": {
        "citation": "CMC Section 601 — All ductwork must be sealed and tested for leakage",
    },
    "CMC_ACCESS_CLEARANCE": {
        "citation": "CMC Section 305 — Min 30in clearance for equipment inspection/maintenance",
        "min_clearance_in": 30,
    },
    # ── CPC (California Plumbing Code) ──
    "CPC_FIXTURE_UNITS": {
        "citation": "CPC Table 422.1 — Fixture unit calculation per IPC (toilet=3, sink=1, shower=2)",
    },
    "CPC_TRAP_SEAL": {
        "citation": "CPC Section 418.3 — Min 2in trap seal; max 10ft from vent",
        "min_trap_seal_in": 2,
        "max_vent_distance_ft": 10,
    },
    "CPC_CLEANOUT_ACCESS": {
        "citation": "CPC Section 410 — Cleanouts every 100ft of pipe run; 24in access minimum",
        "max_run_ft": 100,
        "min_access_in": 24,
    },
    "CPC_BACKFLOW_PREVENTION": {
        "citation": "CPC Section 608.1 — Backflow prevention required on all potable water lines",
    },
    # ── California Energy Code ──
    "CA_ENERGY_HVAC_EFFICIENCY": {
        "citation": "CA Energy Code Title 24 — HVAC SEER ≥16 (cooling), AFUE ≥95% (heating)",
    },
    "CA_ENERGY_ENVELOPE": {
        "citation": "CA Energy Code Title 24 — Insulation R-19 walls, R-30 attic, U-0.30 windows",
    },
    "CA_ENERGY_SOLAR_READY": {
        "citation": "CA Energy Code Title 24 — Solar-ready roof required for low-rise multifamily",
    },
    "CA_ENERGY_COOL_ROOF": {
        "citation": "CA Energy Code Title 24 — Roof SRI ≥75 (cool roof or green roof)",
        "min_sri": 75,
    },
    # ── IBC Structural (Lateral Force Resistance) ──
    "IBC_LATERAL_LOAD": {
        "citation": "IBC Section 1613 / ASCE 7 — Seismic design category per site hazard",
    },
    "IBC_FOUNDATION_DESIGN": {
        "citation": "IBC Section 1817 — Foundations must accommodate lateral forces & liquefaction potential",
    },
    "IBC_SHEAR_WALL_CONTINUITY": {
        "citation": "IBC Section 2305 — Shear walls must be continuous to foundation or diaphragm",
    },
    "IBC_MOMENT_FRAME_DUCTILITY": {
        "citation": "IBC Section 1913 — Steel/concrete moment frames in SDC D+ require special ductile detailing",
    },
    # ── Seismic Safety (CBC / ASCE 7) ──
    "CA_SEISMIC_MEP": {
        "citation": "CBC Section 1614 / ASCE 7 Ch.13 — Seismic bracing required for MEP >2.5in diameter in SDC D+",
    },
    "CA_SEISMIC_EQUIPMENT_ANCHORING": {
        "citation": "ASCE 7-22 Section 13.1 — All equipment >100 lbs must be anchored per ASCE 7 Chapter 13",
    },
    "CA_SEISMIC_PIPE_SUPPORT": {
        "citation": "CBC / ASCE 7 — Piping ≤21 lbs/ft: ≤12ft spacing; >21 lbs/ft: ≤8ft spacing",
        "light_pipe_spacing_ft": 12,
        "heavy_pipe_spacing_ft": 8,
    },
    "CA_SEISMIC_STRUT_BRACING": {
        "citation": "ASCE 7-22 — Diagonal strut bracing required for ductwork in seismic zones",
    },
    "CA_SOFT_STORY_CHECK": {
        "citation": "CBC / ASCE 7 — First story strength ≥80% of average upper story; no soft stories allowed",
        "min_strength_ratio": 0.80,
    },
    "CA_DIAPHRAGM_CONTINUITY": {
        "citation": "IBC Section 2305 — Floor diaphragms must be continuous and well-connected to lateral system",
    },
}


class ComplianceEngine:

    def run(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues = []
        # Life Safety
        issues.extend(self._check_stories(model))
        issues.extend(self._check_corridor_width(model))
        issues.extend(self._check_egress(model))
        issues.extend(self._check_flood(model))
        # MEP & Utilities
        issues.extend(self._check_cec_electrical(model))
        issues.extend(self._check_cmc_mechanical(model))
        issues.extend(self._check_cpc_plumbing(model))
        # Energy
        issues.extend(self._check_ca_energy_code(model))
        # Structural & Seismic
        issues.extend(self._check_ibc_structural(model))
        issues.extend(self._check_seismic_safety(model))
        return issues

    def _check_stories(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues = []
        if model.spec.stories > 3:
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="error",
                message=f"Building has {model.spec.stories} stories — demo limit is 3",
                fix_suggestion="Reduce to 3 stories or upgrade to full permit set mode",
                citation=RULES["CA_STORIES"]["citation"],
            ))
        return issues

    def _check_corridor_width(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues = []
        MIN_WIDTH_M = RULES["CA_CORRIDOR_WIDTH"]["min_ft"] * 0.3048
        corridors = [r for r in model.rooms if r.type == "corridor"]
        for corr in corridors:
            pts = corr.polygon
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            width = min(max(xs) - min(xs), max(ys) - min(ys))
            if width < MIN_WIDTH_M:
                issues.append(ComplianceIssue(
                    id=f"issue_{uuid.uuid4().hex[:6]}",
                    type="compliance",
                    severity="error",
                    message=f"Corridor on level {corr.level} is {width * 3.281:.1f}ft wide — min is 3.67ft",
                    fix_suggestion="Widen corridor to minimum 44 inches (3.67ft)",
                    elements_involved=[corr.id],
                    citation=RULES["CA_CORRIDOR_WIDTH"]["citation"],
                ))
        return issues

    def _check_flood(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues = []
        if model.site_context and model.site_context.flood_flag:
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message=f"Site is in FEMA flood zone {model.site_context.flood_zone} — elevation review required",
                fix_suggestion="Obtain elevation certificate and design to BFE + freeboard requirements",
                citation=RULES["CA_FLOOD_REVIEW"]["citation"],
            ))
        return issues

    def _check_seismic_mep(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues = []
        if model.site_context and model.site_context.seismic_category in ("C", "D", "E", "F"):
            mep_count = len([e for e in model.mep_elements if e.system in ("plumbing", "hvac")])
            if mep_count > 0:
                issues.append(ComplianceIssue(
                    id=f"issue_{uuid.uuid4().hex[:6]}",
                    type="compliance",
                    severity="warning",
                    message=f"SDC {model.site_context.seismic_category}: seismic bracing required on MEP systems >2.5in diameter",
                    fix_suggestion="Add seismic sway bracing to all suspended MEP per ASCE 7 Chapter 13",
                    citation=RULES["CA_SEISMIC_MEP"]["citation"],
                ))
        return issues

    # ── CEC (California Electrical Code) ──
    def _check_cec_electrical(self, model: BuildingModel) -> List[ComplianceIssue]:
        """CEC Article 210 — outlet spacing, circuits, GFCI protection."""
        issues = []
        
        # Check for at least 1 kitchen and bathroom
        has_kitchen = any(r.type in ("kitchen", "living") for r in model.rooms)
        has_bathroom = any(r.type == "bathroom" for r in model.rooms)
        
        if not has_kitchen:
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="error",
                message="No kitchen identified — CEC requires ≥2 x 20A dedicated circuits for kitchen countertop",
                fix_suggestion="Ensure kitchen space is designated with dedicated electrical circuits",
                citation=RULES["CEC_KITCHEN_CIRCUIT"]["citation"],
            ))
        
        if not has_bathroom:
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="error",
                message="No bathroom identified — CEC requires 20A dedicated circuit per bathroom",
                fix_suggestion="Ensure bathroom spaces are present and wired per CEC Article 210",
                citation=RULES["CEC_BATHROOM_CIRCUIT"]["citation"],
            ))
        
        # Check outlet spacing in living areas
        living_rooms = [r for r in model.rooms if r.type in ("living", "bedroom")]
        for room in living_rooms:
            # Simplified check: warn if room is very wide (>12ft likely needs more outlets)
            if hasattr(room, 'polygon') and room.polygon:
                pts = room.polygon
                xs = [p[0] for p in pts]
                room_width = max(xs) - min(xs) if xs else 0
                if room_width > 12:  # 12ft = 2x max spacing
                    issues.append(ComplianceIssue(
                        id=f"issue_{uuid.uuid4().hex[:6]}",
                        type="compliance",
                        severity="warning",
                        message=f"Living area ({room_width*3.281:.1f}ft wide) may require additional outlets per CEC spacing rules",
                        fix_suggestion="Space outlets max 6ft apart in living areas; add wall outlets as needed",
                        elements_involved=[room.id] if hasattr(room, 'id') else [],
                        citation=RULES["CEC_OUTLET_SPACING"]["citation"],
                    ))
        
        # GFCI protection warning
        issues.append(ComplianceIssue(
            id=f"issue_{uuid.uuid4().hex[:6]}",
            type="compliance",
            severity="warning",
            message="CEC Article 210.8 — GFCI protection required on all wet-area outlets (kitchen, bathroom, exterior)",
            fix_suggestion="Specify GFCI-protected circuits for wet areas during MEP design",
            citation=RULES["CEC_GFCI_PROTECTION"]["citation"],
        ))
        
        return issues

    # ── CMC (California Mechanical Code) ──
    def _check_cmc_mechanical(self, model: BuildingModel) -> List[ComplianceIssue]:
        """CMC Sections 601, 402, 305 — ductwork, ventilation, access clearance."""
        issues = []
        
        hvac_elements = [e for e in model.mep_elements if e.system == "hvac"]
        
        if hvac_elements:
            # Ductwork insulation
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message="CMC Section 601 — Ductwork must maintain R-8 insulation (or R-4.2 min in occupied space)",
                fix_suggestion="Specify insulated ductwork with R-8 wrap; test for leakage per ASHRAE 52.2",
                citation=RULES["CMC_DUCTWORK_INSULATION"]["citation"],
            ))
            
            # Ventilation rate (outdoor air)
            total_area = sum(r.area_sqft for r in model.rooms)
            required_cfm = max(total_area * 0.35, len(model.rooms) * 15)  # 0.35 CFM/sqft or 15/person
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message=f"CMC Section 402 — Ventilation requires ≥{required_cfm:.0f} CFM outdoor air (0.35 CFM/sqft minimum)",
                fix_suggestion="Size outdoor air intake and distribution to meet continuous ventilation requirement",
                citation=RULES["CMC_VENTILATION_RATE"]["citation"],
            ))
            
            # Duct sealing and testing
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message="CMC Section 601 — All ductwork must be sealed and undergo pressure testing",
                fix_suggestion="Use mastic or tape to seal all joints; test at 25 Pa per ASHRAE 52.2",
                citation=RULES["CMC_DUCT_SEALING"]["citation"],
            ))
            
            # Equipment clearance
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message="CMC Section 305 — Mechanical equipment requires 30in clearance minimum for inspection",
                fix_suggestion="Plan HVAC equipment location with 30in access on all service sides",
                citation=RULES["CMC_ACCESS_CLEARANCE"]["citation"],
            ))
        
        return issues

    # ── CPC (California Plumbing Code) ──
    def _check_cpc_plumbing(self, model: BuildingModel) -> List[ComplianceIssue]:
        """CPC Sections 418, 410, 608 — trap seals, cleanout access, backflow prevention."""
        issues = []
        
        plumbing_elements = [e for e in model.mep_elements if e.system == "plumbing"]
        bathroom_count = len([r for r in model.rooms if r.type == "bathroom"])
        
        if plumbing_elements or bathroom_count > 0:
            # Trap seal distance from vent
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message="CPC Section 418.3 — Drain traps must maintain 2in seal; max 10ft from vent",
                fix_suggestion="Size vent stacks to keep all fixtures within 10ft; verify trap seal maintenance",
                citation=RULES["CPC_TRAP_SEAL"]["citation"],
            ))
            
            # Cleanout access
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message="CPC Section 410 — Cleanouts required every 100ft of horizontal run; 24in access clearance",
                fix_suggestion="Place cleanout plugs at each change of direction and every 100ft; keep accessible",
                citation=RULES["CPC_CLEANOUT_ACCESS"]["citation"],
            ))
            
            # Backflow prevention
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message="CPC Section 608.1 — Backflow prevention required on all potable water supply lines",
                fix_suggestion="Install backflow preventer (double check valve or reduced pressure principle device)",
                citation=RULES["CPC_BACKFLOW_PREVENTION"]["citation"],
            ))
        
        return issues

    # ── California Energy Code (Title 24) ──
    def _check_ca_energy_code(self, model: BuildingModel) -> List[ComplianceIssue]:
        """CA Energy Code Title 24 — HVAC efficiency, envelope, solar-ready, cool roofs."""
        issues = []
        
        # HVAC efficiency
        issues.append(ComplianceIssue(
            id=f"issue_{uuid.uuid4().hex[:6]}",
            type="compliance",
            severity="warning",
            message="CA Energy Code Title 24 — HVAC must meet SEER ≥16 (cooling), AFUE ≥95% (heating)",
            fix_suggestion="Specify high-efficiency equipment; use mini-split or efficient rooftop units",
            citation=RULES["CA_ENERGY_HVAC_EFFICIENCY"]["citation"],
        ))
        
        # Building envelope
        issues.append(ComplianceIssue(
            id=f"issue_{uuid.uuid4().hex[:6]}",
            type="compliance",
            severity="warning",
            message="CA Energy Code Title 24 — Insulation R-19 (walls), R-30 (attic), U-0.30 (windows)",
            fix_suggestion="Specify insulation and window performance to meet Title 24 minimum requirements",
            citation=RULES["CA_ENERGY_ENVELOPE"]["citation"],
        ))
        
        # Solar-ready roof
        issues.append(ComplianceIssue(
            id=f"issue_{uuid.uuid4().hex[:6]}",
            type="compliance",
            severity="warning",
            message="CA Energy Code Title 24 — Low-rise multifamily must have solar-ready roof",
            fix_suggestion="Design roof to accommodate future solar PV (structural & electrical readiness)",
            citation=RULES["CA_ENERGY_SOLAR_READY"]["citation"],
        ))
        
        # Cool roof
        issues.append(ComplianceIssue(
            id=f"issue_{uuid.uuid4().hex[:6]}",
            type="compliance",
            severity="warning",
            message="CA Energy Code Title 24 — Roof must have SRI ≥75 (cool roof or green roof)",
            fix_suggestion="Use light-colored roofing (SRI 75+) or vegetative roof; avoid dark materials",
            citation=RULES["CA_ENERGY_COOL_ROOF"]["citation"],
        ))
        
        return issues

    # ── IBC Structural Requirements ──
    def _check_ibc_structural(self, model: BuildingModel) -> List[ComplianceIssue]:
        """IBC Sections 1613, 1817, 2305, 1913 — Lateral force, foundations, continuity."""
        issues = []
        
        if model.site_context:
            sdc = model.site_context.seismic_category
            
            # Lateral load design
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="error",
                message=f"IBC Section 1613 — Building must be designed for seismic forces (SDC {sdc})",
                fix_suggestion="Engage structural engineer; design lateral system per ASCE 7-22 for your seismic category",
                citation=RULES["IBC_LATERAL_LOAD"]["citation"],
            ))
            
            # Foundation design
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message="IBC Section 1817 — Foundations must resist lateral forces and account for liquefaction risk",
                fix_suggestion="Perform soil boring; design foundation to resist shear & moment per IBC 1817",
                citation=RULES["IBC_FOUNDATION_DESIGN"]["citation"],
            ))
            
            # Shear wall continuity
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message="IBC Section 2305 — Shear walls must be continuous from roof to foundation diaphragm",
                fix_suggestion="Verify shear wall line runs uninterrupted; detail connections at each floor",
                citation=RULES["IBC_SHEAR_WALL_CONTINUITY"]["citation"],
            ))
            
            # Moment frame ductility
            if model.spec.structural_system in ("steel", "concrete"):
                issues.append(ComplianceIssue(
                    id=f"issue_{uuid.uuid4().hex[:6]}",
                    type="compliance",
                    severity="warning",
                    message=f"IBC Section 1913 — Moment frames in SDC {sdc} require special ductile detailing",
                    fix_suggestion="Use intermediate moment frame (IMF) or special moment frame (SMF) per AISC 341",
                    citation=RULES["IBC_MOMENT_FRAME_DUCTILITY"]["citation"],
                ))
        
        return issues

    # ── Seismic Safety (CBC / ASCE 7) ──
    def _check_seismic_safety(self, model: BuildingModel) -> List[ComplianceIssue]:
        """CBC / ASCE 7-22 — Equipment anchoring, pipe support, strut bracing, soft story, diaphragm."""
        issues = []
        
        if model.site_context and model.site_context.seismic_category in ("C", "D", "E", "F"):
            sdc = model.site_context.seismic_category
            
            # Equipment anchoring
            mep_count = len([e for e in model.mep_elements if hasattr(e, 'weight_lbs') and e.weight_lbs > 100])
            if mep_count > 0 or len(model.mep_elements) > 5:
                issues.append(ComplianceIssue(
                    id=f"issue_{uuid.uuid4().hex[:6]}",
                    type="compliance",
                    severity="error",
                    message=f"ASCE 7-22 Section 13.1 — All MEP equipment >100 lbs must be seismically anchored in SDC {sdc}",
                    fix_suggestion="Anchor rooftop units, fans, tanks to building via bolted connections or welded brackets",
                    citation=RULES["CA_SEISMIC_EQUIPMENT_ANCHORING"]["citation"],
                ))
            
            # Piping support spacing
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message="ASCE 7-22 — Light pipe (≤21 lbs/ft): ≤12ft spacing; heavy pipe: ≤8ft spacing",
                fix_suggestion="Install seismic supports at max 12ft (light) or 8ft (heavy) intervals; use flexible connectors",
                citation=RULES["CA_SEISMIC_PIPE_SUPPORT"]["citation"],
            ))
            
            # Diagonal strut bracing for ductwork
            hvac_elements = [e for e in model.mep_elements if e.system == "hvac"]
            if hvac_elements:
                issues.append(ComplianceIssue(
                    id=f"issue_{uuid.uuid4().hex[:6]}",
                    type="compliance",
                    severity="error",
                    message=f"ASCE 7-22 — Ductwork in SDC {sdc} must have diagonal strut bracing",
                    fix_suggestion="Add diagonal struts (angle iron or tube) at 45° to resist torsion and shear",
                    citation=RULES["CA_SEISMIC_STRUT_BRACING"]["citation"],
                ))
            
            # Soft story check
            if model.spec.stories > 1:
                issues.append(ComplianceIssue(
                    id=f"issue_{uuid.uuid4().hex[:6]}",
                    type="compliance",
                    severity="error",
                    message=f"CBC / ASCE 7 — First story must have ≥80% lateral strength of upper stories (no soft story)",
                    fix_suggestion="Ensure ground floor shear walls & frames are at least 80% as strong as upper floors",
                    citation=RULES["CA_SOFT_STORY_CHECK"]["citation"],
                ))
            
            # Diaphragm continuity
            issues.append(ComplianceIssue(
                id=f"issue_{uuid.uuid4().hex[:6]}",
                type="compliance",
                severity="warning",
                message="IBC Section 2305 — Floor diaphragms must be continuous and tied to lateral system",
                fix_suggestion="Ensure floor deck is continuous and well-fastened to shear walls; use diaphragm blocking at corners",
                citation=RULES["CA_DIAPHRAGM_CONTINUITY"]["citation"],
            ))
        
        return issues
        return issues

    def _check_egress(self, model: BuildingModel) -> List[ComplianceIssue]:
        """Check for required exits and occupant egress per floor."""
        issues = []
        for level_idx in set(r.level for r in model.rooms):
            stairs = [r for r in model.rooms if r.type == "stair" and r.level == level_idx]
            unit_rooms = [r for r in model.rooms if r.type == "unit" and r.level == level_idx]
            total_area = sum(getattr(r, 'area_sqft', 0) for r in unit_rooms)
            occupant_load = int(total_area / 200)  # IBC residential: 200 sqft/person
            if occupant_load > 10 and len(stairs) < 2:
                issues.append(ComplianceIssue(
                    id=f"issue_{uuid.uuid4().hex[:6]}",
                    type="compliance",
                    severity="error",
                    message=f"Level {level_idx}: estimated {occupant_load} occupants requires ≥2 exit stairways — only {len(stairs)} found",
                    fix_suggestion="Add a second stair enclosure at the opposite end of the corridor",
                    citation=RULES["CA_EGRESS_EXITS"]["citation"],
                ))
        return issues
