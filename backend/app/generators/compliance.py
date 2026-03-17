"""
ComplianceEngine
Deterministic rule checks for CA multifamily low-rise.
"""
import uuid
from typing import List
from app.models.schemas import BuildingModel, ComplianceIssue, Room, Wall

RULES = {
    "CA_EGRESS_TRAVEL_DIST": {
        "citation": "CBC Section 1017.2 — Max travel distance 250ft (sprinklered) / 200ft",
        "limit_ft": 200,
    },
    "CA_CORRIDOR_WIDTH": {
        "citation": "CBC Section 1020.2 — Min corridor width 44in (3.67ft)",
        "min_ft": 3.67,
    },
    "CA_DOOR_WIDTH": {
        "citation": "CBC Section 1010.1.1 — Min door clear width 32in",
        "min_in": 32,
    },
    "CA_STORIES": {
        "citation": "Demo constraint — max 3 stories",
        "max": 3,
    },
    "CA_FLOOD_REVIEW": {
        "citation": "FEMA NFIP — Flood zone requires elevation certificate review",
    },
    "CA_SEISMIC_MEP": {
        "citation": "CBC Section 1614 / ASCE 7 Ch.13 — MEP seismic bracing required in SDC D",
    },
    "CA_EGRESS_EXITS": {
        "citation": "CBC Section 1006.3.4 — ≥2 exits required for floor area >500 sqft with >10 occupants",
    },
}


class ComplianceEngine:

    def run(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues = []
        issues.extend(self._check_stories(model))
        issues.extend(self._check_corridor_width(model))
        issues.extend(self._check_flood(model))
        issues.extend(self._check_seismic_mep(model))
        issues.extend(self._check_egress(model))
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

    def _check_egress(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues = []
        for level_idx in set(r.level for r in model.rooms):
            stairs = [r for r in model.rooms if r.type == "stair" and r.level == level_idx]
            unit_rooms = [r for r in model.rooms if r.type == "unit" and r.level == level_idx]
            total_area = sum(r.area_sqft for r in unit_rooms)
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
