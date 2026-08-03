"""Evidence-based California code preflight checks.

This module intentionally distinguishes a *measurable model failure* from a
permit-stage design requirement.  Only failed checks supported by geometry,
elements, or metadata are emitted as ``error``/``warning``.  Requirements that
cannot be proven from the conceptual model are emitted as ``info`` advisories.

The rule set is scoped to the 2025 California Building Standards Code
(Title 24, effective for the 2026-2028 code cycle).  It is a deterministic
preflight, not a substitute for an AHJ review or a licensed design professional.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from app.constants import ADU_MAX_SQFT, BuildingUse
from app.models.schemas import BuildingModel, ComplianceIssue, MEPElement, Room


CODE_CYCLE = "2025"
CODE_CYCLE_LABEL = "2025 California Building Standards Code (Title 24)"

RULES: Dict[str, Dict[str, str]] = {
    "SCOPE-2025": {
        "citation": "2025 California Building Standards Code (Title 24)",
    },
    "BUILDING-STORIES": {
        "citation": "Petronus low-rise generation scope (maximum 3 stories)",
    },
    "CBC-CORRIDOR-WIDTH": {
        "citation": "2025 California Building Code (Title 24, Part 2), means of egress",
    },
    "CBC-EGRESS-PRESENCE": {
        "citation": "2025 California Building Code (Title 24, Part 2), Chapter 10",
    },
    "ADU-AREA": {
        "citation": "California Government Code sections 66314 and 66325; local ADU standards apply",
    },
    "CEC-ELECTRICAL": {
        "citation": "2025 California Electrical Code (Title 24, Part 3), Articles 210, 220 and 408",
    },
    "CMC-MECHANICAL": {
        "citation": "2025 California Mechanical Code (Title 24, Part 4)",
    },
    "CPC-PLUMBING": {
        "citation": "2025 California Plumbing Code (Title 24, Part 5)",
    },
    "ENERGY-TITLE24": {
        "citation": "2025 California Energy Code (Title 24, Part 6)",
    },
    "CBC-FIRE-LIFE-SAFETY": {
        "citation": "2025 California Residential Code R309-R311; California Building Code Section 903 and adopted NFPA standard as applicable",
    },
    "CBC-STRUCTURAL": {
        "citation": "2025 California Building Code (Title 24, Part 2), Chapters 16-23",
    },
    "ASCE7-SEISMIC": {
        "citation": "ASCE 7-22 as adopted by the 2025 California Building Code",
    },
    "FLOOD-REVIEW": {
        "citation": "Applicable local floodplain ordinance and FEMA NFIP requirements",
    },
}


ELECTRICAL_TERMINALS: Set[str] = {
    "outlet", "receptacle", "lighting_point", "light_fixture", "switch", "light_switch",
    "dedicated_circuit", "branch_circuit", "fire_alarm", "smoke_alarm",
}
OUTLET_TYPES: Set[str] = {"outlet", "receptacle", "gfci_outlet", "afci_outlet"}
CIRCUIT_TYPES: Set[str] = {
    "dedicated_circuit", "branch_circuit", "kitchen_circuit",
    "small_appliance_circuit", "bathroom_circuit", "laundry_circuit",
}
PANEL_TYPES: Set[str] = {"main_panel", "sub_panel", "distribution_panel", "load_center"}

PLUMBING_SUPPLY_TYPES: Set[str] = {
    "cold_supply", "hot_supply", "water_supply", "fixture_supply",
    "washer_supply", "washer_box",
}
PLUMBING_WASTE_TYPES: Set[str] = {
    "waste_branch", "drain", "fixture_drain", "soil_stack", "sewer_lateral",
    "washer_drain",
}
PLUMBING_FIXTURE_TYPES: Set[str] = {
    "toilet", "water_closet", "sink", "lavatory", "shower", "bathtub",
    "tub", "kitchen_sink", "bathroom_sink", "washer_box",
    "washer_hookup", "washer_connection",
}

HVAC_TERMINAL_TYPES: Set[str] = {
    "mini_split_head", "supply_diffuser", "supply_register", "fan_coil",
    "radiant_terminal",
}
HVAC_EQUIPMENT_TYPES: Set[str] = {
    "condenser_unit", "rooftop_unit", "heat_pump", "air_handler", "furnace",
}
HVAC_RETURN_TYPES: Set[str] = {
    "return_air", "return_grille", "return_duct", "return_riser",
}
HVAC_VENTILATION_TYPES: Set[str] = {
    "outdoor_air_intake", "whole_building_ventilator", "whole_house_fan",
    "whole_house_ventilator", "erv", "hrv", "fresh_air_duct",
}
HVAC_EXHAUST_TYPES: Set[str] = {
    "exhaust_fan", "bath_exhaust", "kitchen_exhaust", "range_hood",
}

NON_PROGRAM_ROOMS: Set[str] = {"attic", "roof", "void"}
ELECTRICAL_ROOMS: Set[str] = {
    "bedroom", "living", "family_room", "dining", "kitchen", "bathroom",
    "office", "loft", "media_room", "bonus_room", "laundry", "utility",
    "mechanical", "garage", "foyer", "mudroom", "corridor", "hall", "hallway",
    "unit", "walk_in_closet", "library", "gym",
}
OUTLET_ROOMS: Set[str] = {
    "bedroom", "living", "family_room", "dining", "kitchen", "office",
    "loft", "media_room", "bonus_room", "bathroom", "laundry", "garage",
    "library", "gym",
}
CONDITIONED_ROOMS: Set[str] = {
    "bedroom", "living", "family_room", "dining", "kitchen", "office",
    "loft", "media_room", "bonus_room", "unit", "library", "gym",
}
WET_ROOMS: Set[str] = {"bathroom", "kitchen", "laundry"}
SPRINKLER_ROOMS: Set[str] = {
    "bedroom", "living", "family_room", "dining", "kitchen", "office",
    "loft", "media_room", "bonus_room", "bathroom", "laundry", "utility",
    "mechanical", "garage", "unit", "walk_in_closet", "library", "gym",
}

# Room types whose MEP applicability is intentionally classified by this
# preflight.  An unfamiliar program name must not silently fall between the
# electrical, plumbing and HVAC coverage sets.
KNOWN_ROOM_TYPES: Set[str] = (
    ELECTRICAL_ROOMS
    | OUTLET_ROOMS
    | CONDITIONED_ROOMS
    | WET_ROOMS
    | SPRINKLER_ROOMS
    | NON_PROGRAM_ROOMS
    | {
        "stair", "pantry", "closet", "storage", "entry", "open_to_below",
        "walk_in_closet", "library", "gym", "balcony", "patio", "porch", "deck",
    }
)

PLUMBING_COLD_TYPES: Set[str] = {"cold_supply", "cold_water_riser"}
PLUMBING_HOT_TYPES: Set[str] = {"hot_supply", "hot_water_riser"}
PLUMBING_VENT_TYPES: Set[str] = {"vent", "vent_branch", "vent_stack", "plumbing_vent", "soil_stack"}
CO_ALARM_TYPES: Set[str] = {
    "carbon_monoxide_alarm", "carbon_monoxide_detector", "co_alarm", "co_detector",
}


class ComplianceEngine:
    """Run deterministic, evidence-backed checks against a ``BuildingModel``."""

    def run(self, model: BuildingModel) -> List[ComplianceIssue]:
        self._checks: List[Dict[str, Any]] = []
        self._issue_sequences: Dict[str, int] = defaultdict(int)

        # Preserve findings created by upstream validators (for example clash
        # detection).  Compliance findings are regenerated on every run so a
        # second preflight does not duplicate stale rule results.
        preserved_issues = [
            issue for issue in (getattr(model, "issues", None) or [])
            if getattr(issue, "type", None) != "compliance"
        ]

        compliance_issues: List[ComplianceIssue] = []
        compliance_issues.extend(self._check_code_scope(model))
        compliance_issues.extend(self._check_stories(model))
        compliance_issues.extend(self._check_corridor_width(model))
        compliance_issues.extend(self._check_egress(model))
        compliance_issues.extend(self._check_flood(model))

        is_adu = getattr(model.spec, "building_use", None) in ("adu", BuildingUse.adu)
        if is_adu:
            compliance_issues.extend(self._check_adu(model))
        else:
            self._record("ADU-SCOPE", "not_applicable", "Building use is not ADU.")

        compliance_issues.extend(self._check_mep_room_coverage(model))
        compliance_issues.extend(self._check_cec_electrical(model))
        compliance_issues.extend(self._check_cmc_mechanical(model))
        compliance_issues.extend(self._check_cpc_plumbing(model))
        compliance_issues.extend(self._check_fire_life_safety(model))
        compliance_issues.extend(self._check_ca_energy_code(model))
        compliance_issues.extend(self._check_ibc_structural(model))
        compliance_issues.extend(self._check_seismic_safety(model))

        issues = preserved_issues + compliance_issues
        counts = Counter(issue.severity for issue in issues)
        compliance_counts = Counter(issue.severity for issue in compliance_issues)
        preserved_counts = Counter(issue.severity for issue in preserved_issues)
        check_counts = Counter(check["status"] for check in self._checks)
        if counts["error"]:
            status = "failed"
        elif counts["warning"]:
            status = "needs_attention"
        elif check_counts["unverified"] or check_counts["advisory"]:
            status = "unverified"
        else:
            status = "preflight_passed"

        summary: Dict[str, Any] = {
            "code_cycle": CODE_CYCLE,
            "code_cycle_label": CODE_CYCLE_LABEL,
            "requested_code_cycle": str(getattr(model.spec, "code_cycle", CODE_CYCLE)),
            "evaluated_code_cycle": CODE_CYCLE,
            "jurisdiction": {
                "state": getattr(model.spec, "region_state", "CA"),
                "city": getattr(model.spec, "jurisdiction_city", None),
            },
            "status": status,
            "permit_ready": False,
            "issue_counts": {
                "error": counts["error"],
                "warning": counts["warning"],
                "info": counts["info"],
                "total": len(issues),
            },
            "compliance_issue_counts": {
                "error": compliance_counts["error"],
                "warning": compliance_counts["warning"],
                "info": compliance_counts["info"],
                "total": len(compliance_issues),
            },
            "preserved_issue_counts": {
                "error": preserved_counts["error"],
                "warning": preserved_counts["warning"],
                "info": preserved_counts["info"],
                "total": len(preserved_issues),
            },
            "check_counts": dict(check_counts),
            "checks": list(self._checks),
            "limitations": [
                "Concept/design-development preflight only; not a permit approval or stamped design.",
                "Local amendments, utility requirements, product listings, calculations, and field conditions require AHJ and licensed-professional review.",
                "A pass means the modeled evidence satisfied implemented checks; it does not prove compliance with every applicable provision.",
            ],
        }
        # Pydantic models with the new field accept normal assignment.  The
        # fallback keeps the engine usable during migrations and in lightweight
        # test doubles.
        try:
            model.compliance_summary = summary
        except (AttributeError, ValueError):
            object.__setattr__(model, "compliance_summary", summary)
        model.issues = issues
        return issues

    # ------------------------------------------------------------------
    # Result / issue helpers
    # ------------------------------------------------------------------

    def _record(
        self,
        rule_id: str,
        status: str,
        evidence: str,
        *,
        severity: Optional[str] = None,
        elements: Optional[Sequence[str]] = None,
    ) -> None:
        self._checks.append({
            "rule_id": rule_id,
            "status": status,
            "severity": severity,
            "evidence": evidence,
            "elements": list(elements or []),
        })

    def _issue(
        self,
        rule_id: str,
        severity: str,
        message: str,
        fix_suggestion: str,
        *,
        citation_key: str,
        elements: Optional[Sequence[str]] = None,
        status: Optional[str] = None,
    ) -> ComplianceIssue:
        self._issue_sequences[rule_id] += 1
        seq = self._issue_sequences[rule_id]
        element_ids = list(dict.fromkeys(elements or []))
        result_status = status or ("advisory" if severity == "info" else "fail")
        self._record(
            rule_id,
            result_status,
            message,
            severity=severity,
            elements=element_ids,
        )
        return ComplianceIssue(
            id=f"{rule_id}-{seq:02d}",
            type="compliance",
            severity=severity,
            message=message,
            fix_suggestion=fix_suggestion,
            elements_involved=element_ids,
            citation=RULES[citation_key]["citation"],
        )

    def _pass(self, rule_id: str, evidence: str, elements: Optional[Sequence[str]] = None) -> None:
        self._record(rule_id, "pass", evidence, elements=elements)

    # ------------------------------------------------------------------
    # Geometry / metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _metadata(element: MEPElement) -> Dict[str, Any]:
        return dict(getattr(element, "metadata", None) or {})

    @staticmethod
    def _room_polygon(room: Room) -> Optional[Polygon]:
        try:
            polygon = Polygon(room.polygon)
            if polygon.is_empty:
                return None
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            return polygon if not polygon.is_empty else None
        except Exception:
            return None

    def _leaf_rooms(self, model: BuildingModel) -> List[Room]:
        """Exclude enclosing multifamily ``unit`` shells when leaf rooms exist."""
        child_unit_ids = {
            room.unit_id
            for room in model.rooms
            if room.unit_id and room.type != "unit"
        }
        return [
            room for room in model.rooms
            if room.type not in NON_PROGRAM_ROOMS
            and not (room.type == "unit" and room.id in child_unit_ids)
        ]

    def _element_hits_room(self, element: MEPElement, room: Room, tolerance_m: float = 0.18) -> bool:
        if element.level != room.level:
            return False
        metadata = self._metadata(element)
        tagged_room_ids: Set[str] = set()
        has_room_tags = False
        explicit_room_id = metadata.get("room_id")
        if explicit_room_id is not None:
            has_room_tags = True
            tagged_room_ids.add(str(explicit_room_id))
        for key in ("room_ids", "served_room_ids", "served_rooms", "zones_served"):
            served = metadata.get(key)
            if isinstance(served, (list, tuple, set)):
                has_room_tags = True
                tagged_room_ids.update(str(value) for value in served)
        if has_room_tags:
            return room.id in tagged_room_ids
        polygon = self._room_polygon(room)
        if polygon is None:
            return False
        area = polygon.buffer(tolerance_m)
        for coordinates in (element.start, element.end):
            if coordinates and len(coordinates) >= 3:
                try:
                    if area.covers(Point(float(coordinates[0]), float(coordinates[2]))):
                        return True
                except (TypeError, ValueError):
                    continue
        return False

    def _room_elements(
        self,
        model: BuildingModel,
        room: Room,
        *,
        system: Optional[str] = None,
        types: Optional[Set[str]] = None,
    ) -> List[MEPElement]:
        return [
            element for element in model.mep_elements
            if (system is None or element.system == system)
            and (types is None or element.type in types)
            and self._element_hits_room(element, room)
        ]

    @staticmethod
    def _room_ids(rooms: Iterable[Room]) -> List[str]:
        return [room.id for room in rooms]

    @staticmethod
    def _room_list_text(rooms: Sequence[Room], limit: int = 6) -> str:
        labels = [f"{room.type} {room.id}" for room in rooms]
        if len(labels) > limit:
            labels = labels[:limit] + [f"and {len(rooms) - limit} more"]
        return ", ".join(labels)

    @staticmethod
    def _bool_metadata(metadata: Dict[str, Any], *keys: str) -> Optional[bool]:
        for key in keys:
            if key not in metadata:
                continue
            value = metadata[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normal = value.strip().lower()
                if normal in {"true", "yes", "provided", "compliant", "gfci", "afci"}:
                    return True
                if normal in {"false", "no", "missing", "noncompliant"}:
                    return False
        return None

    @classmethod
    def _has_protection(cls, element: MEPElement, protection: str) -> bool:
        metadata = cls._metadata(element)
        direct = cls._bool_metadata(metadata, protection.lower(), f"{protection.lower()}_protected")
        if direct is not None:
            return direct
        raw = metadata.get("protection") or metadata.get("protections") or []
        if isinstance(raw, str):
            raw = [raw]
        return any(protection.lower() in str(item).lower() for item in raw)

    @classmethod
    def _outlet_has_protection(
        cls,
        model: BuildingModel,
        outlet: MEPElement,
        protection: str,
    ) -> bool:
        """Accept device-level or referenced branch-circuit protection."""
        if cls._has_protection(outlet, protection):
            return True
        circuit_id = cls._metadata(outlet).get("circuit_id")
        if not circuit_id:
            return False
        for candidate in model.mep_elements:
            if candidate.system != "electrical" or candidate.type not in CIRCUIT_TYPES:
                continue
            metadata = cls._metadata(candidate)
            if circuit_id in {candidate.id, metadata.get("circuit_id")}:
                if cls._has_protection(candidate, protection):
                    return True
        return False

    @staticmethod
    def _numeric_metadata(metadata: Dict[str, Any], *keys: str) -> Optional[float]:
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return float(value)
        return None

    @staticmethod
    def _valid_climate_zone(value: Any) -> bool:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False
        return numeric.is_integer() and 1 <= int(numeric) <= 16

    @staticmethod
    def _valid_energy_method(value: Any) -> bool:
        normalized = str(value or "").strip().lower().replace("-", "_")
        return normalized in {"prescriptive", "performance", "performance_compliance"}

    @staticmethod
    def _valid_energy_form_reference(value: Any) -> bool:
        # Registration/existence is checked externally.  This only rejects
        # placeholders and malformed identifiers such as ``CF1R-TEST``.
        return bool(re.fullmatch(
            r"CF[123]R-[A-Z0-9]{2,}(?:-[A-Z0-9]{2,})+(?:-[A-Z])?",
            str(value or "").strip().upper(),
        ))

    @classmethod
    def _is_smoke_alarm(cls, element: MEPElement) -> bool:
        if element.type in {"smoke_alarm", "smoke_detector"}:
            return True
        if element.type != "fire_alarm":
            return False
        metadata = cls._metadata(element)
        detector = str(metadata.get("detector", metadata.get("detector_type", ""))).lower()
        # A generic fire-alarm marker is not a dwelling smoke alarm.  A modeled
        # fire-alarm device counts only when it identifies its smoke-detection
        # function and documents the expected dwelling interconnection/power.
        return (
            "smoke" in detector
            and cls._bool_metadata(metadata, "interconnected") is True
            and (
                cls._bool_metadata(metadata, "hardwired") is True
                or cls._bool_metadata(metadata, "listed") is True
            )
        )

    @classmethod
    def _alarm_documentation_gaps(
        cls,
        element: MEPElement,
        listing_standard: str,
        *,
        require_building_power: bool,
    ) -> List[str]:
        """Return permit-evidence fields missing from a modeled alarm device."""
        metadata = cls._metadata(element)
        gaps: List[str] = []
        documented_standard = str(
            metadata.get("listing_standard")
            or metadata.get("listing_reference")
            or ""
        ).upper()
        if cls._bool_metadata(metadata, "listed") is not True:
            gaps.append("listed-product evidence")
        if listing_standard.upper() not in documented_standard:
            gaps.append(f"{listing_standard} standard/reference")
        if cls._bool_metadata(metadata, "interconnected") is not True:
            gaps.append("interconnection")
        if require_building_power:
            if cls._bool_metadata(metadata, "hardwired") is not True:
                gaps.append("building-wiring power")
            if cls._bool_metadata(metadata, "battery_backup") is not True:
                gaps.append("battery backup")
        return gaps

    def _modeled_floor_area_sqft(self, model: BuildingModel) -> float:
        rooms = self._leaf_rooms(model)
        by_level: Dict[int, List[Polygon]] = defaultdict(list)
        for room in rooms:
            polygon = self._room_polygon(room)
            if polygon is not None:
                by_level[room.level].append(polygon)
        if by_level:
            return sum(unary_union(polygons).area * 10.7639 for polygons in by_level.values())
        return sum(max(0.0, room.area_sqft) for room in rooms)

    # ------------------------------------------------------------------
    # Scope, architectural, and site checks
    # ------------------------------------------------------------------

    def _check_code_scope(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        requested_cycle = str(getattr(model.spec, "code_cycle", CODE_CYCLE))
        state = str(getattr(model.spec, "region_state", "CA"))
        country = str(getattr(model.spec, "region_country", "US"))
        if requested_cycle != CODE_CYCLE or state != "CA" or country != "US":
            issues.append(self._issue(
                "SCOPE-2025",
                "info",
                f"Requested scope {country}/{state}, cycle {requested_cycle}, is not implemented; no code pass can be issued.",
                "Use the California 2025 residential workflow or add a validated ruleset for the requested jurisdiction and cycle.",
                citation_key="SCOPE-2025",
                status="unverified",
            ))
        else:
            self._pass("SCOPE-2025", f"Preflight rules are scoped to the {CODE_CYCLE_LABEL}.")

        construction_scope = str(
            getattr(getattr(model.spec, "construction_scope", "new_construction"), "value",
                    getattr(model.spec, "construction_scope", "new_construction"))
        ).lower()
        if construction_scope in {"new", "new_build", "new_construction"}:
            self._pass("SCOPE-CONSTRUCTION", "New-construction rule applicability is selected.")
        else:
            issues.append(self._issue(
                "SCOPE-CONSTRUCTION",
                "info",
                f"Construction scope {construction_scope!r} needs alteration/addition-specific applicability analysis; new-dwelling assumptions cannot be treated as a pass.",
                "Load a validated ruleset for the existing-building, addition, or alteration scope.",
                citation_key="SCOPE-2025",
                status="unverified",
            ))

        # A city name is not a ruleset.  Until adopted amendments have been
        # loaded from an authoritative source and versioned, local compliance
        # remains unresolved for every project.
        issues.append(self._issue(
            "SCOPE-LOCAL-AMENDMENTS",
            "info",
            "No validated local-AHJ amendment ruleset is loaded; jurisdiction_city is descriptive metadata only.",
            "Load and version the applicable city/county amendments and AHJ interpretations before permit use.",
            citation_key="SCOPE-2025",
            status="unverified",
        ))
        return issues

    def _check_stories(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        if model.spec.stories > 3:
            issues.append(self._issue(
                "BUILDING-STORIES",
                "error",
                f"Model has {model.spec.stories} stories, beyond the 3-story generation scope.",
                "Regenerate at 3 stories or less, or use a workflow validated for taller buildings.",
                citation_key="BUILDING-STORIES",
            ))
        else:
            self._pass("BUILDING-STORIES", f"{model.spec.stories} stories is within the validated low-rise scope.")

        if not model.rooms:
            issues.append(self._issue(
                "BUILDING-ROOM-PRESENCE",
                "error",
                "No programmed rooms were generated for the building model.",
                "Generate a floor plan before routing MEP or evaluating building completeness.",
                citation_key="BUILDING-STORIES",
            ))
            return issues

        expected_levels = set(range(model.spec.stories))
        occupied_levels = {room.level for room in self._leaf_rooms(model)}
        missing_levels = sorted(expected_levels - occupied_levels)
        if missing_levels:
            issues.append(self._issue(
                "BUILDING-LEVEL-COVERAGE",
                "error",
                f"Requested stories have no programmed rooms on levels {missing_levels}.",
                "Generate a complete floor plan on every requested story.",
                citation_key="BUILDING-STORIES",
            ))
        else:
            self._pass(
                "BUILDING-LEVEL-COVERAGE",
                f"Programmed rooms are present on all {model.spec.stories} requested level(s).",
            )
        return issues

    def _check_corridor_width(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        # A clear width under 36 inches is a measurable baseline failure for
        # the residential occupancies in scope. Wider requirements depend on
        # occupant load and route classification, which the schema lacks.
        minimum_in = 36.0
        minimum_m = minimum_in * 0.0254
        corridors = [room for room in self._leaf_rooms(model) if room.type in {"corridor", "hall", "hallway"}]
        if not corridors:
            self._record("CBC-CORRIDOR-WIDTH", "not_applicable", "No modeled corridor rooms.")
            return issues

        failures: List[Tuple[Room, float, str]] = []
        unverifiable: List[Room] = []
        for corridor in corridors:
            polygon = self._room_polygon(corridor)
            if polygon is None:
                unverifiable.append(corridor)
                continue
            rectangle = polygon.minimum_rotated_rectangle
            coords = list(rectangle.exterior.coords)
            spans = [LineString([coords[i], coords[i + 1]]).length for i in range(4)]
            width = min((span for span in spans if span > 1e-6), default=0.0)
            if width < minimum_m:
                failures.append((corridor, width, "overall width"))
                continue

            # A bounding rectangle cannot see a narrow neck inside an otherwise
            # wide hourglass-shaped corridor.  Eroding by half the required
            # clear width removes every location that cannot contain the
            # required clearance disc; a split erosion exposes an internal
            # pinch point that interrupts the corridor's usable center path.
            eroded = polygon.buffer(-minimum_m / 2.0, join_style=2)
            eroded_parts = (
                [part for part in getattr(eroded, "geoms", []) if part.area > 1e-6]
                if eroded.geom_type == "MultiPolygon"
                else ([] if eroded.is_empty else [eroded])
            )
            if not eroded_parts or len(eroded_parts) > 1:
                failures.append((corridor, minimum_m, "internal pinch point"))

        if failures:
            details = ", ".join(
                f"{room.id} ({reason}{f'={width / 0.3048:.2f}ft' if reason == 'overall width' else ''})"
                for room, width, reason in failures
            )
            issues.append(self._issue(
                "CBC-CORRIDOR-WIDTH",
                "error",
                f"Modeled corridor clear width is below the {minimum_in:.0f}in residential baseline: {details}.",
                "Widen the listed corridor geometry and rerun compliance.",
                citation_key="CBC-CORRIDOR-WIDTH",
                elements=[room.id for room, _, _ in failures],
            ))
        elif not unverifiable:
            self._pass(
                "CBC-CORRIDOR-WIDTH",
                f"All {len(corridors)} modeled corridors meet the {minimum_in:.0f}in residential baseline.",
                self._room_ids(corridors),
            )
        if unverifiable:
            issues.append(self._issue(
                "CBC-CORRIDOR-WIDTH-GEOMETRY",
                "warning",
                f"Could not measure corridor polygons: {self._room_list_text(unverifiable)}.",
                "Repair the corridor polygons so clear width can be checked.",
                citation_key="CBC-CORRIDOR-WIDTH",
                elements=self._room_ids(unverifiable),
            ))
        return issues

    def _check_egress(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        occupied_levels = sorted({room.level for room in self._leaf_rooms(model)})
        stairs = [room for room in model.rooms if room.type == "stair"]
        if len(occupied_levels) > 1 and not stairs:
            issues.append(self._issue(
                "CBC-EGRESS-PRESENCE",
                "error",
                f"The model has occupied levels {occupied_levels} but no stair/vertical egress space.",
                "Add a connected stair or other code-permitted vertical egress element serving the upper levels.",
                citation_key="CBC-EGRESS-PRESENCE",
            ))
        else:
            self._pass(
                "CBC-EGRESS-PRESENCE",
                "A stair space is present for the multi-level model." if len(occupied_levels) > 1
                else "The model has one occupied level; an interior stair is not required by this presence check.",
                [room.id for room in stairs],
            )

        exterior_doors = [
            mesh for mesh in model.meshes
            if str(mesh.get("element_type", "")).lower() in {"door", "exterior_door", "entry_door"}
        ]
        if not exterior_doors:
            issues.append(self._issue(
                "CBC-EXTERIOR-DOOR-PRESENCE",
                "warning",
                "No exterior entry/egress door is present in the model meshes.",
                "Generate at least one exterior door connected to the interior circulation path.",
                citation_key="CBC-EGRESS-PRESENCE",
            ))
        else:
            self._pass(
                "CBC-EXTERIOR-DOOR-PRESENCE",
                f"Found {len(exterior_doors)} exterior door mesh(es).",
                [str(mesh.get("element_id", "")) for mesh in exterior_doors],
            )

        # Travel distance, exit separation, door maneuvering clearance and an
        # accessible route need an opening-aware navigation graph that the
        # current schema does not yet expose.  They are advisories, not fake
        # violations.
        issues.append(self._issue(
            "CBC-EGRESS-DETAILED-REVIEW",
            "info",
            "Travel distance, exit separation, door maneuvering clearance, and accessible-route continuity are not fully represented by the current geometry schema.",
            "Verify an opening-aware egress graph and accessibility clearances in the permit model.",
            citation_key="CBC-EGRESS-PRESENCE",
        ))
        return issues

    def _check_flood(self, model: BuildingModel) -> List[ComplianceIssue]:
        if model.site_context is None or not model.site_context.flood_zone:
            return [self._issue(
                "FLOOD-REVIEW",
                "info",
                "Mapped flood-zone evidence is absent, so flood applicability is unverified.",
                "Retrieve authoritative floodplain data and compare required elevations before permit.",
                citation_key="FLOOD-REVIEW",
                status="unverified",
            )]
        flood_zone = str(model.site_context.flood_zone or "").strip().upper()
        mapped_hazard = bool(model.site_context.flood_flag) or flood_zone.startswith(("A", "V"))
        if mapped_hazard:
            flood_evidence = dict((model.design_brief or {}).get("flood", {}) or {})
            design_flood = self._numeric_metadata(
                flood_evidence, "design_flood_elevation_ft", "base_flood_elevation_ft",
            )
            lowest_floor = self._numeric_metadata(
                flood_evidence, "lowest_floor_elevation_ft", "design_floor_elevation_ft",
            )
            freeboard = self._numeric_metadata(flood_evidence, "required_freeboard_ft")
            source = flood_evidence.get("determination_source") or flood_evidence.get("map_panel_reference")
            if design_flood is None or lowest_floor is None or freeboard is None or not source:
                return [self._issue(
                    "FLOOD-REVIEW",
                    "info",
                    f"Site context reports mapped flood hazard {flood_zone}; authoritative elevation/freeboard comparison evidence is incomplete.",
                    "Attach the map/determination source, design flood elevation, required freeboard, and lowest-floor/equipment elevation comparison.",
                    citation_key="FLOOD-REVIEW",
                    status="unverified",
                )]
            required_elevation = design_flood + freeboard
            if lowest_floor + 1e-6 < required_elevation:
                return [self._issue(
                    "FLOOD-REVIEW",
                    "error",
                    f"Lowest floor elevation {lowest_floor:.2f}ft is below the documented {required_elevation:.2f}ft flood-design elevation including freeboard.",
                    "Raise/protect the floor and equipment elevations and rerun the floodplain design comparison.",
                    citation_key="FLOOD-REVIEW",
                )]
            self._pass("FLOOD-REVIEW", f"Documented lowest floor elevation meets the mapped flood elevation plus freeboard for zone {flood_zone}.")
            return []
        self._pass("FLOOD-REVIEW", "Site context does not flag a mapped special flood hazard.")
        return []

    def _check_adu(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        total_sqft = self._modeled_floor_area_sqft(model)
        fine = model.spec.fine_details or {}
        configured_area_limit = float(fine.get("adu_max_sqft", ADU_MAX_SQFT))
        area_source = str(fine.get("adu_max_sqft_source", "")).strip()
        if configured_area_limit > ADU_MAX_SQFT and not area_source:
            issues.append(self._issue(
                "ADU-AREA-LOCAL-STANDARD",
                "info",
                f"Configured ADU area limit {configured_area_limit:,.0f} sqft exceeds the statewide default without a cited local less-restrictive ordinance.",
                "Attach adu_max_sqft_source from the applicable adopted local ordinance.",
                citation_key="ADU-AREA",
                status="unverified",
            ))
        elif total_sqft > configured_area_limit + 1.0:
            issues.append(self._issue(
                "ADU-AREA",
                "error",
                f"Modeled ADU floor area is {total_sqft:,.0f} sqft, above the configured {configured_area_limit:,.0f} sqft preflight limit.",
                "Reduce the modeled floor area or set adu_max_sqft from a verified local ordinance that permits a larger unit.",
                citation_key="ADU-AREA",
            ))
        elif configured_area_limit <= ADU_MAX_SQFT or area_source:
            self._pass("ADU-AREA", f"Modeled ADU area is {total_sqft:,.0f} sqft (configured limit {configured_area_limit:,.0f} sqft).")

        configured_story_limit = model.spec.max_floors
        height_source = str(
            fine.get("adu_height_standard_source", fine.get("adu_story_limit_source", ""))
        ).strip()
        if configured_story_limit is None or not height_source:
            issues.append(self._issue(
                "ADU-HEIGHT-LOCAL-STANDARD",
                "info",
                "ADU height/story applicability cannot be verified without a sourced local objective standard; no universal two-story limit is assumed.",
                "Attach max_floors/max_height_ft and adu_height_standard_source from the applicable local ordinance.",
                citation_key="ADU-AREA",
                status="unverified",
            ))
        elif model.spec.stories > configured_story_limit:
            issues.append(self._issue(
                "ADU-STORIES",
                "error",
                f"Modeled ADU has {model.spec.stories} stories, above the configured {configured_story_limit}-story preflight limit.",
                "Reduce the ADU height or set max_floors from verified local objective standards.",
                citation_key="ADU-AREA",
            ))
        else:
            self._pass("ADU-STORIES", f"ADU has {model.spec.stories} stories against the sourced {configured_story_limit}-story local standard.")

        setback = fine.get("adu_setback_evidence")
        if not isinstance(setback, dict) or not setback.get("source"):
            issues.append(self._issue(
                "ADU-SETBACK-EVIDENCE",
                "info",
                "Georeferenced ADU side/rear setback or qualifying conversion-path evidence is absent.",
                "Attach surveyed parcel/building geometry and the applicable setback source, or document the qualifying conversion path.",
                citation_key="ADU-AREA",
                status="unverified",
            ))
        elif bool(setback.get("conversion_path_verified")):
            self._pass("ADU-SETBACK-EVIDENCE", "A sourced qualifying conversion-path determination is documented.")
        else:
            side = self._numeric_metadata(setback, "side_setback_ft")
            rear = self._numeric_metadata(setback, "rear_setback_ft")
            required = self._numeric_metadata(setback, "required_setback_ft")
            if side is None or rear is None or required is None or not setback.get("georeferenced"):
                issues.append(self._issue(
                    "ADU-SETBACK-EVIDENCE",
                    "info",
                    "ADU setback metadata lacks georeferenced side/rear measurements and the applicable required setback.",
                    "Attach georeferenced side_setback_ft, rear_setback_ft, required_setback_ft, and source.",
                    citation_key="ADU-AREA",
                    status="unverified",
                ))
            elif min(side, rear) + 1e-6 < required:
                issues.append(self._issue(
                    "ADU-SETBACK",
                    "error",
                    f"Documented ADU side/rear setback ({side:.2f}ft/{rear:.2f}ft) is below the sourced {required:.2f}ft requirement.",
                    "Revise the siting or document a qualifying conversion/exception path.",
                    citation_key="ADU-AREA",
                ))
            else:
                self._pass("ADU-SETBACK", "Georeferenced side/rear setbacks meet the documented local requirement.")
        return issues

    # ------------------------------------------------------------------
    # Cross-system completeness
    # ------------------------------------------------------------------

    def _check_mep_room_coverage(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        rooms = self._leaf_rooms(model)

        unknown_rooms = [room for room in rooms if room.type not in KNOWN_ROOM_TYPES]
        if unknown_rooms:
            issues.append(self._issue(
                "MEP-ROOM-TYPE-SCOPE",
                "error",
                f"Unknown room types have no validated MEP applicability mapping: {self._room_list_text(unknown_rooms)}.",
                "Map each room type to electrical, plumbing, HVAC, exhaust, alarm, and sprinkler requirements before compliance evaluation.",
                citation_key="SCOPE-2025",
                elements=self._room_ids(unknown_rooms),
            ))

        electrical_rooms = [room for room in rooms if room.type in ELECTRICAL_ROOMS]
        missing_electrical = [
            room for room in electrical_rooms
            if not self._room_elements(model, room, system="electrical", types=ELECTRICAL_TERMINALS)
        ]
        if missing_electrical:
            issues.append(self._issue(
                "MEP-ELECTRICAL-COVERAGE",
                "error",
                f"No terminal electrical device is modeled in {len(missing_electrical)} room(s): {self._room_list_text(missing_electrical)}.",
                "Add a lighting, receptacle, switch, alarm, or circuit terminal to every programmed room.",
                citation_key="CEC-ELECTRICAL",
                elements=self._room_ids(missing_electrical),
            ))
        else:
            self._pass("MEP-ELECTRICAL-COVERAGE", f"Terminal electrical coverage found in all {len(electrical_rooms)} applicable rooms.")

        wet_rooms = [room for room in rooms if room.type in WET_ROOMS]
        missing_plumbing = [
            room for room in wet_rooms
            if not self._room_elements(
                model,
                room,
                system="plumbing",
                types=PLUMBING_SUPPLY_TYPES | PLUMBING_WASTE_TYPES | PLUMBING_FIXTURE_TYPES,
            )
        ]
        if missing_plumbing:
            issues.append(self._issue(
                "MEP-PLUMBING-COVERAGE",
                "error",
                f"No plumbing terminal/branch is modeled in {len(missing_plumbing)} wet room(s): {self._room_list_text(missing_plumbing)}.",
                "Route plumbing and place fixtures in every kitchen, bathroom, and laundry room.",
                citation_key="CPC-PLUMBING",
                elements=self._room_ids(missing_plumbing),
            ))
        else:
            self._pass("MEP-PLUMBING-COVERAGE", f"Plumbing coverage found in all {len(wet_rooms)} wet rooms.")

        conditioned = [room for room in rooms if room.type in CONDITIONED_ROOMS]
        missing_hvac = [
            room for room in conditioned
            if not self._room_elements(model, room, system="hvac", types=HVAC_TERMINAL_TYPES)
        ]
        if missing_hvac:
            issues.append(self._issue(
                "MEP-HVAC-COVERAGE",
                "warning",
                f"No HVAC terminal is modeled in {len(missing_hvac)} conditioned room(s): {self._room_list_text(missing_hvac)}.",
                "Add a supply terminal or zoned indoor unit to every conditioned room, or document an open-plan/shared-zone exception.",
                citation_key="CMC-MECHANICAL",
                elements=self._room_ids(missing_hvac),
            ))
        else:
            self._pass("MEP-HVAC-COVERAGE", f"HVAC terminal coverage found in all {len(conditioned)} conditioned rooms.")
        return issues

    # ------------------------------------------------------------------
    # Electrical
    # ------------------------------------------------------------------

    def _circuit_kind(self, element: MEPElement) -> str:
        metadata = self._metadata(element)
        return " ".join(
            str(value).lower()
            for value in (
                element.type,
                metadata.get("circuit_type", ""),
                metadata.get("load_type", ""),
                metadata.get("name", ""),
            )
        )

    def _circuit_count(self, element: MEPElement) -> int:
        metadata = self._metadata(element)
        value = metadata.get("circuit_count", 1)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1

    def _check_cec_electrical(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        rooms = self._leaf_rooms(model)
        electrical = [element for element in model.mep_elements if element.system == "electrical"]
        panels = [element for element in electrical if element.type in PANEL_TYPES]
        if rooms and not panels:
            issues.append(self._issue(
                "CEC-PANEL-PRESENCE",
                "error",
                "No electrical panel/load center is present in the generated model.",
                "Add a service or distribution panel and document its rating.",
                citation_key="CEC-ELECTRICAL",
            ))
        elif panels:
            self._pass("CEC-PANEL-PRESENCE", f"Found {len(panels)} panel/load-center element(s).", [panel.id for panel in panels])

        outlet_rooms = [room for room in rooms if room.type in OUTLET_ROOMS]
        missing_outlets = [
            room for room in outlet_rooms
            if not self._room_elements(model, room, system="electrical", types=OUTLET_TYPES)
        ]
        if missing_outlets:
            issues.append(self._issue(
                "CEC-RECEPTACLE-COVERAGE",
                "error",
                f"No receptacle is modeled in {len(missing_outlets)} applicable room(s): {self._room_list_text(missing_outlets)}.",
                "Place receptacles from actual wall-segment spacing, accounting for openings and fixed cabinets.",
                citation_key="CEC-ELECTRICAL",
                elements=self._room_ids(missing_outlets),
            ))
        else:
            self._pass("CEC-RECEPTACLE-COVERAGE", f"Receptacles are modeled in all {len(outlet_rooms)} applicable rooms.")

        circuits = [element for element in electrical if element.type in CIRCUIT_TYPES]
        circuit_failures: List[str] = []
        circuit_elements: List[str] = []
        circuit_requirements = {
            "kitchen": (2, ("kitchen", "small appliance", "small_appliance")),
            "bathroom": (1, ("bath", "bathroom")),
            "laundry": (1, ("laundry", "washer")),
        }
        selected_circuits: Set[str] = set()
        for room_type, (minimum, keywords) in circuit_requirements.items():
            for room in [item for item in rooms if item.type == room_type]:
                explicit = [
                    circuit for circuit in circuits
                    if any(keyword in self._circuit_kind(circuit) for keyword in keywords)
                    and self._element_hits_room(circuit, room)
                ]
                matched = list({circuit.id: circuit for circuit in explicit}.values())
                count = sum(self._circuit_count(circuit) for circuit in matched)
                selected_circuits.update(circuit.id for circuit in matched)
                if count < minimum:
                    circuit_failures.append(f"{room.id}: {count}/{minimum} {room_type} circuit(s)")
                circuit_elements.extend(circuit.id for circuit in matched)
        if circuit_failures:
            issues.append(self._issue(
                "CEC-DEDICATED-CIRCUITS",
                "error",
                "Dedicated circuit count is incomplete: " + "; ".join(circuit_failures) + ".",
                "Generate the required dedicated circuits and tag each with room_id, circuit_type, amperage, and breaker/panel assignment.",
                citation_key="CEC-ELECTRICAL",
                elements=circuit_elements,
            ))
        else:
            self._pass("CEC-DEDICATED-CIRCUITS", "Modeled kitchen, bathroom, and laundry rooms have the configured dedicated-circuit counts.")

        unrated = []
        undersized = []
        for circuit in circuits:
            kind = self._circuit_kind(circuit)
            if not any(token in kind for token in ("kitchen", "small", "bath", "laundry", "washer")) and circuit.id not in selected_circuits:
                continue
            amps = self._numeric_metadata(self._metadata(circuit), "amps", "amperage", "breaker_amps")
            if amps is None:
                unrated.append(circuit)
            elif amps < 20:
                undersized.append(circuit)
        if undersized:
            issues.append(self._issue(
                "CEC-CIRCUIT-RATING",
                "error",
                f"{len(undersized)} kitchen/bath/laundry dedicated circuit(s) are rated below 20A.",
                "Increase the circuit/breaker rating and verify conductor ampacity and load calculations.",
                citation_key="CEC-ELECTRICAL",
                elements=[circuit.id for circuit in undersized],
            ))
        if unrated:
            issues.append(self._issue(
                "CEC-CIRCUIT-RATING-METADATA",
                "warning",
                f"{len(unrated)} dedicated circuit(s) do not document amperage metadata.",
                "Populate amps/breaker_amps metadata so circuit sizing can be verified.",
                citation_key="CEC-ELECTRICAL",
                elements=[circuit.id for circuit in unrated],
            ))
        elif circuits:
            self._pass("CEC-CIRCUIT-RATING", "Dedicated-circuit amperage metadata is present and meets the configured 20A threshold.")

        circuit_references: Set[str] = set()
        for circuit in circuits:
            circuit_references.add(circuit.id)
            circuit_id = self._metadata(circuit).get("circuit_id")
            if circuit_id:
                circuit_references.add(str(circuit_id))
        circuit_loads = [
            element for element in electrical
            if element.type in OUTLET_TYPES | {"lighting_point", "light_fixture", "switch", "light_switch"}
        ]
        unassigned_loads: List[MEPElement] = []
        dangling_loads: List[MEPElement] = []
        for load in circuit_loads:
            circuit_id = self._metadata(load).get("circuit_id")
            if not circuit_id:
                unassigned_loads.append(load)
            elif str(circuit_id) not in circuit_references:
                dangling_loads.append(load)
        if unassigned_loads or dangling_loads:
            details: List[str] = []
            if unassigned_loads:
                details.append(f"{len(unassigned_loads)} load(s) have no circuit_id")
            if dangling_loads:
                details.append(f"{len(dangling_loads)} load(s) reference an absent circuit")
            issues.append(self._issue(
                "CEC-CIRCUIT-CONNECTIVITY",
                "warning",
                "Electrical load-to-circuit connectivity is incomplete: " + "; ".join(details) + ".",
                "Assign every receptacle/light/switch to a generated branch circuit and panel schedule.",
                citation_key="CEC-ELECTRICAL",
                elements=[element.id for element in unassigned_loads + dangling_loads],
            ))
        elif circuit_loads:
            self._pass(
                "CEC-CIRCUIT-CONNECTIVITY",
                f"All {len(circuit_loads)} modeled receptacle/light/switch loads reference a generated circuit.",
            )

        excessive_spacing: List[MEPElement] = []
        missing_spacing_evidence: List[MEPElement] = []
        for outlet in [element for element in electrical if element.type in OUTLET_TYPES]:
            metadata = self._metadata(outlet)
            maximum = self._numeric_metadata(metadata, "max_spacing_ft", "design_spacing_ft")
            threshold = 4.0 if metadata.get("countertop") else 12.0
            if maximum is None:
                missing_spacing_evidence.append(outlet)
            elif maximum > threshold + 1e-6:
                excessive_spacing.append(outlet)
        if excessive_spacing:
            issues.append(self._issue(
                "CEC-RECEPTACLE-SPACING-METADATA",
                "error",
                f"{len(excessive_spacing)} receptacle(s) document design spacing beyond the 12ft wall-area / 4ft countertop screening thresholds.",
                "Regenerate receptacle placement and store the corrected max_spacing_ft metadata.",
                citation_key="CEC-ELECTRICAL",
                elements=[element.id for element in excessive_spacing],
            ))
        if missing_spacing_evidence:
            issues.append(self._issue(
                "CEC-RECEPTACLE-SPACING-DOCUMENTATION",
                "info",
                f"{len(missing_spacing_evidence)} receptacle(s) lack wall-segment/countertop spacing evidence.",
                "Store max_spacing_ft/design_spacing_ft from an opening-aware wall-segment layout calculation.",
                citation_key="CEC-ELECTRICAL",
                elements=[element.id for element in missing_spacing_evidence],
                status="unverified",
            ))
        elif not excessive_spacing and any(element.type in OUTLET_TYPES for element in electrical):
            self._pass("CEC-RECEPTACLE-SPACING-METADATA", "Documented receptacle spacing does not exceed the configured screening thresholds.")

        wet_outlets: List[MEPElement] = []
        afci_outlets: List[MEPElement] = []
        for room in rooms:
            outlets = self._room_elements(model, room, system="electrical", types=OUTLET_TYPES)
            if room.type in {"bathroom", "kitchen", "laundry", "garage"}:
                wet_outlets.extend(outlets)
            if room.type in {
                "bedroom", "living", "family_room", "dining", "office",
                "kitchen", "laundry", "corridor", "hall", "hallway",
            }:
                afci_outlets.extend(outlets)
        missing_gfci = [
            outlet for outlet in {item.id: item for item in wet_outlets}.values()
            if not self._outlet_has_protection(model, outlet, "gfci")
        ]
        missing_afci = [
            outlet for outlet in {item.id: item for item in afci_outlets}.values()
            if not self._outlet_has_protection(model, outlet, "afci")
        ]
        if missing_gfci:
            issues.append(self._issue(
                "CEC-GFCI-METADATA",
                "warning",
                f"{len(missing_gfci)} modeled wet/garage-area receptacle(s) lack GFCI protection metadata.",
                "Mark each protected receptacle/circuit with gfci=true or explicit protection metadata.",
                citation_key="CEC-ELECTRICAL",
                elements=[outlet.id for outlet in missing_gfci],
            ))
        elif wet_outlets:
            self._pass("CEC-GFCI-METADATA", "All modeled wet/garage-area receptacles declare GFCI protection.")
        if missing_afci:
            issues.append(self._issue(
                "CEC-AFCI-METADATA",
                "warning",
                f"{len(missing_afci)} modeled dwelling-area receptacle(s) lack AFCI protection metadata.",
                "Mark protected dwelling circuits/receptacles with afci=true or explicit protection metadata.",
                citation_key="CEC-ELECTRICAL",
                elements=[outlet.id for outlet in missing_afci],
            ))
        elif afci_outlets:
            self._pass("CEC-AFCI-METADATA", "All modeled dwelling-area receptacles declare AFCI protection.")
        return issues

    # ------------------------------------------------------------------
    # Mechanical / HVAC
    # ------------------------------------------------------------------

    def _check_cmc_mechanical(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        hvac = [element for element in model.mep_elements if element.system == "hvac"]
        conditioned = [room for room in self._leaf_rooms(model) if room.type in CONDITIONED_ROOMS]
        equipment = [element for element in hvac if element.type in HVAC_EQUIPMENT_TYPES]
        if conditioned and not equipment:
            issues.append(self._issue(
                "CMC-EQUIPMENT-PRESENCE",
                "error",
                "Conditioned rooms are modeled but no HVAC equipment is present.",
                "Add an air-conditioning/heat-pump/air-handler equipment element and connect its terminals.",
                citation_key="CMC-MECHANICAL",
            ))
        elif equipment:
            self._pass("CMC-EQUIPMENT-PRESENCE", f"Found {len(equipment)} HVAC equipment element(s).", [element.id for element in equipment])

        preference = getattr(getattr(model.spec, "hvac_preference", None), "value", getattr(model.spec, "hvac_preference", ""))
        if str(preference).lower() == "rooftop" and conditioned:
            returns = [element for element in hvac if element.type in HVAC_RETURN_TYPES]
            levels = {room.level for room in conditioned}
            return_levels = {element.level for element in returns}
            missing_levels = sorted(levels - return_levels)
            if missing_levels:
                issues.append(self._issue(
                    "CMC-RETURN-AIR",
                    "warning",
                    f"Central HVAC has no modeled return-air terminal/path on levels {missing_levels}.",
                    "Add return grilles/ducts and document return-air transfer paths.",
                    citation_key="CMC-MECHANICAL",
                ))
            else:
                self._pass("CMC-RETURN-AIR", "Central HVAC includes a return-air element on every conditioned level.")
        else:
            self._record("CMC-RETURN-AIR", "not_applicable", "Central rooftop HVAC is not selected.")

        exhaust_enabled = (getattr(model.spec, "fine_details", None) or {}).get("exhaust_fans", True)
        exhaust_rooms = [
            room for room in self._leaf_rooms(model)
            if room.type in {"bathroom", "kitchen", "laundry"}
        ]
        if exhaust_enabled:
            modeled_exhaust: List[MEPElement] = []
            missing_exhaust = [
                room for room in exhaust_rooms
                if not self._room_elements(
                    model, room, system="hvac", types=HVAC_EXHAUST_TYPES,
                )
            ]
            for room in exhaust_rooms:
                modeled_exhaust.extend(
                    self._room_elements(model, room, system="hvac", types=HVAC_EXHAUST_TYPES)
                )
            if missing_exhaust:
                issues.append(self._issue(
                    "CMC-LOCAL-EXHAUST",
                    "warning",
                    f"Local exhaust is enabled but no exhaust terminal is modeled in {len(missing_exhaust)} room(s): {self._room_list_text(missing_exhaust)}.",
                    "Add bathroom exhaust and kitchen range-hood/exhaust elements with airflow and discharge metadata.",
                    citation_key="CMC-MECHANICAL",
                    elements=self._room_ids(missing_exhaust),
                ))
            else:
                self._pass("CMC-LOCAL-EXHAUST-PRESENCE", f"Local exhaust terminals found in all {len(exhaust_rooms)} applicable rooms.")

            unique_exhaust = list({element.id: element for element in modeled_exhaust}.values())
            exhaust_below_required: List[MEPElement] = []
            exhaust_unverified: List[MEPElement] = []
            for element in unique_exhaust:
                metadata = self._metadata(element)
                actual = self._numeric_metadata(
                    metadata, "actual_exhaust_cfm", "capacity_cfm", "airflow_cfm",
                )
                required = self._numeric_metadata(metadata, "required_exhaust_cfm")
                calculation_reference = (
                    metadata.get("exhaust_calculation_reference")
                    or metadata.get("calculation_reference")
                    or metadata.get("design_airflow_source")
                )
                calculation_verified = self._bool_metadata(metadata, "calculation_verified")
                if actual is not None and required is not None and actual + 1e-6 < required:
                    exhaust_below_required.append(element)
                elif (
                    actual is None or required is None or required <= 0
                    or not calculation_reference or calculation_verified is not True
                ):
                    exhaust_unverified.append(element)
            if exhaust_below_required:
                issues.append(self._issue(
                    "CMC-LOCAL-EXHAUST-AIRFLOW",
                    "error",
                    f"{len(exhaust_below_required)} local-exhaust terminal(s) have actual airflow below the documented required airflow.",
                    "Increase exhaust airflow to the calculated requirement and update commissioning evidence.",
                    citation_key="CMC-MECHANICAL",
                    elements=[element.id for element in exhaust_below_required],
                ))
            if exhaust_unverified:
                issues.append(self._issue(
                    "CMC-LOCAL-EXHAUST-CALCULATION",
                    "info",
                    f"{len(exhaust_unverified)} local-exhaust terminal(s) lack verified actual/required CFM calculation evidence.",
                    "Document actual_exhaust_cfm/capacity_cfm, required_exhaust_cfm, a calculation reference, and calculation_verified=true.",
                    citation_key="CMC-MECHANICAL",
                    elements=[element.id for element in exhaust_unverified],
                    status="unverified",
                ))
            elif unique_exhaust and not exhaust_below_required:
                self._pass("CMC-LOCAL-EXHAUST-AIRFLOW", "Verified local-exhaust airflow meets the documented calculated requirements.")

            explicit_indoor_discharge = [
                element for element in unique_exhaust
                if self._bool_metadata(self._metadata(element), "terminates_outdoors", "discharges_outdoors") is False
            ]
            missing_discharge_evidence = [
                element for element in unique_exhaust
                if self._bool_metadata(self._metadata(element), "terminates_outdoors", "discharges_outdoors") is None
            ]
            if explicit_indoor_discharge:
                issues.append(self._issue(
                    "CMC-EXHAUST-DISCHARGE",
                    "warning",
                    f"{len(explicit_indoor_discharge)} local-exhaust terminal(s) explicitly report no outdoor discharge.",
                    "Route exhaust to an approved outdoor termination and update discharge metadata.",
                    citation_key="CMC-MECHANICAL",
                    elements=[element.id for element in explicit_indoor_discharge],
                ))
            if missing_discharge_evidence:
                issues.append(self._issue(
                    "CMC-EXHAUST-DISCHARGE-DOCUMENTATION",
                    "info",
                    f"{len(missing_discharge_evidence)} local-exhaust terminal(s) do not document outdoor discharge.",
                    "Add terminates_outdoors/discharges_outdoors metadata and the permit termination detail.",
                    citation_key="CMC-MECHANICAL",
                    elements=[element.id for element in missing_discharge_evidence],
                    status="unverified",
                ))
            elif unique_exhaust and not explicit_indoor_discharge:
                self._pass("CMC-EXHAUST-DISCHARGE", "All modeled local-exhaust terminals affirmatively document outdoor discharge.")
        else:
            alternative = (getattr(model.spec, "fine_details", None) or {}).get("local_exhaust_alternative")
            alternative_verified = (
                isinstance(alternative, dict)
                and self._bool_metadata(alternative, "verified", "approved") is True
                and bool(alternative.get("reference") or alternative.get("determination_source"))
            )
            if alternative_verified:
                self._pass("CMC-LOCAL-EXHAUST", "A referenced, verified local-exhaust alternative is documented.")
            else:
                issues.append(self._issue(
                    "CMC-LOCAL-EXHAUST-DISABLED",
                    "info",
                    "Kitchen/bathroom local exhaust was disabled without referenced evidence of a compliant alternative.",
                    "Enable local exhaust or attach a verified alternative design and determination source.",
                    citation_key="CMC-MECHANICAL",
                    status="unverified",
                ))

        ventilation = [element for element in hvac if element.type in HVAC_VENTILATION_TYPES]
        ventilation_evidence: List[Tuple[MEPElement, float, float]] = []
        ventilation_incomplete: List[MEPElement] = []
        for element in ventilation:
            metadata = self._metadata(element)
            actual = self._numeric_metadata(
                metadata, "actual_outdoor_air_cfm", "outdoor_air_cfm", "fresh_air_cfm", "airflow_cfm",
            )
            required = self._numeric_metadata(
                metadata, "required_outdoor_air_cfm", "required_fresh_air_cfm", "required_airflow_cfm",
            )
            calculation = (
                metadata.get("ventilation_calculation_id")
                or metadata.get("ventilation_calculation_reference")
                or metadata.get("calculation_reference")
                or metadata.get("design_airflow_source")
            )
            calculation_verified = self._bool_metadata(metadata, "calculation_verified")
            if (
                actual is None or required is None or required <= 0
                or not calculation or calculation_verified is not True
            ):
                ventilation_incomplete.append(element)
            else:
                ventilation_evidence.append((element, actual, required))

        if conditioned and not ventilation:
            issues.append(self._issue(
                "CMC-WHOLE-BUILDING-VENTILATION",
                "error",
                "No whole-building/outdoor-air ventilation system is modeled for conditioned dwelling space.",
                "Add the ventilation system and document calculated actual/required outdoor airflow.",
                citation_key="CMC-MECHANICAL",
            ))
        elif conditioned and ventilation_incomplete:
            issues.append(self._issue(
                "CMC-WHOLE-BUILDING-VENTILATION-DOCUMENTATION",
                "info",
                f"{len(ventilation_incomplete)} ventilation element(s) lack actual airflow, required airflow, or calculation evidence.",
                "Populate actual and required outdoor-air CFM plus a ventilation calculation reference.",
                citation_key="CMC-MECHANICAL",
                elements=[element.id for element in ventilation_incomplete],
                status="unverified",
            ))
        if conditioned and ventilation_evidence:
            below_required = [
                element for element, actual, required in ventilation_evidence
                if actual + 1e-6 < required
            ]
            if below_required:
                issues.append(self._issue(
                    "CMC-WHOLE-BUILDING-VENTILATION-AIRFLOW",
                    "error",
                    f"{len(below_required)} ventilation element(s) have documented airflow below the calculated requirement.",
                    "Increase airflow to the calculated requirement and update commissioning evidence.",
                    citation_key="CMC-MECHANICAL",
                    elements=[element.id for element in below_required],
                ))
            elif not ventilation_incomplete:
                self._pass("CMC-WHOLE-BUILDING-VENTILATION", "Actual ventilation airflow meets documented calculated requirements.")
        elif not conditioned:
            self._record("CMC-WHOLE-BUILDING-VENTILATION", "not_applicable", "No conditioned dwelling rooms are modeled.")

        ductwork = [
            element for element in hvac
            if "duct" in element.type
            or element.type in {
                "supply_branch", "return_branch", "return_air", "return_riser",
                "supply_riser",
            }
        ]
        failed_duct_r: List[MEPElement] = []
        missing_duct_r: List[MEPElement] = []
        for duct in ductwork:
            metadata = self._metadata(duct)
            actual = self._numeric_metadata(metadata, "duct_r_value", "insulation_r_value")
            required = self._numeric_metadata(metadata, "required_duct_r_value")
            if actual is None or required is None or required <= 0:
                missing_duct_r.append(duct)
            elif actual < required:
                failed_duct_r.append(duct)
        if failed_duct_r:
            issues.append(self._issue(
                "CMC-DUCT-INSULATION",
                "warning",
                f"{len(failed_duct_r)} duct element(s) have insulation below their documented required R-value.",
                "Increase duct insulation or revise the documented location-specific requirement.",
                citation_key="CMC-MECHANICAL",
                elements=[duct.id for duct in failed_duct_r],
            ))
        if missing_duct_r:
            issues.append(self._issue(
                "CMC-DUCT-INSULATION-DOCUMENTATION",
                "info",
                f"{len(missing_duct_r)} duct element(s) lack both actual and required location-specific insulation R-value evidence.",
                "Add duct_r_value and required_duct_r_value metadata based on the modeled duct location.",
                citation_key="CMC-MECHANICAL",
                elements=[duct.id for duct in missing_duct_r],
                status="unverified",
            ))
        elif ductwork and not failed_duct_r:
            self._pass("CMC-DUCT-INSULATION", "All duct elements document insulation metadata without a recorded shortfall.")
        return issues

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------

    def _check_cpc_plumbing(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        plumbing = [element for element in model.mep_elements if element.system == "plumbing"]
        rooms = self._leaf_rooms(model)
        bathrooms = [room for room in rooms if room.type == "bathroom"]

        half_bath_ids: Set[str] = set()
        bathroom_spec = getattr(model.spec, "bathrooms", None)
        if bathroom_spec is not None and float(bathroom_spec) % 1 == 0.5 and bathrooms:
            smallest = min(bathrooms, key=lambda room: room.area_sqft)
            half_bath_ids.add(smallest.id)

        missing_fixtures: List[str] = []
        fixture_room_ids: List[str] = []
        for room in rooms:
            if room.type not in WET_ROOMS:
                continue
            room_fixtures = self._room_elements(model, room, system="plumbing", types=PLUMBING_FIXTURE_TYPES)
            present = {fixture.type for fixture in room_fixtures}
            required: List[Set[str]] = []
            if room.type == "bathroom":
                required = [{"toilet", "water_closet"}, {"sink", "lavatory"}]
                if room.id not in half_bath_ids:
                    required.append({"shower", "bathtub", "tub"})
            elif room.type == "kitchen":
                required = [{"sink", "kitchen_sink"}]
            elif room.type == "laundry":
                required = [{"washer_box", "washer_hookup", "washer_connection"}]
            for aliases in required:
                if not (present & aliases):
                    missing_fixtures.append(f"{room.id}: {'/'.join(sorted(aliases))}")
                    fixture_room_ids.append(room.id)
        if missing_fixtures:
            issues.append(self._issue(
                "CPC-FIXTURE-COMPLETENESS",
                "error",
                "Required plumbing fixtures/connections are missing: " + "; ".join(missing_fixtures) + ".",
                "Place the missing fixtures and connect each to modeled supply, waste, trap, and vent paths.",
                citation_key="CPC-PLUMBING",
                elements=fixture_room_ids,
            ))
        else:
            self._pass("CPC-FIXTURE-COMPLETENESS", "All modeled wet rooms contain the expected fixture set.")

        missing_cold: List[Room] = []
        missing_hot: List[Room] = []
        missing_waste: List[Room] = []
        missing_vent: List[Room] = []
        for room in [item for item in rooms if item.type in WET_ROOMS]:
            room_supply = self._room_elements(
                model, room, system="plumbing", types=PLUMBING_SUPPLY_TYPES,
            )
            connected_supply = [element for element in room_supply if element.end is not None]
            connected_cold = [
                element for element in connected_supply
                if element.type in PLUMBING_COLD_TYPES
                or str(self._metadata(element).get("water_temperature", "")).lower() == "cold"
                or str(self._metadata(element).get("supply_kind", "")).lower() == "cold"
            ]
            connected_hot = [
                element for element in connected_supply
                if element.type in PLUMBING_HOT_TYPES
                or str(self._metadata(element).get("water_temperature", "")).lower() == "hot"
                or str(self._metadata(element).get("supply_kind", "")).lower() == "hot"
            ]
            if not connected_cold:
                missing_cold.append(room)
            if room.type in {"bathroom", "kitchen", "laundry"} and not connected_hot:
                missing_hot.append(room)
            room_waste = self._room_elements(
                model, room, system="plumbing", types=PLUMBING_WASTE_TYPES,
            )
            connected_waste = [element for element in room_waste if element.end is not None]
            if not connected_waste:
                missing_waste.append(room)
            vent_evidence = self._room_elements(
                model, room, system="plumbing", types=PLUMBING_VENT_TYPES,
            )
            has_vent_metadata = any(
                self._bool_metadata(self._metadata(element), "vented", "vent_connected") is True
                or bool(self._metadata(element).get("vent_id"))
                for element in room_waste
                + self._room_elements(model, room, system="plumbing", types=PLUMBING_FIXTURE_TYPES)
            )
            if not vent_evidence and not has_vent_metadata:
                missing_vent.append(room)
        if missing_cold or missing_hot:
            details: List[str] = []
            if missing_cold:
                details.append("cold: " + self._room_list_text(missing_cold))
            if missing_hot:
                details.append("hot: " + self._room_list_text(missing_hot))
            issues.append(self._issue(
                "CPC-SUPPLY-COVERAGE",
                "error",
                "Required connected water supplies are incomplete (" + "; ".join(details) + ").",
                "Route separately identifiable cold and hot supplies as applicable to each fixture group.",
                citation_key="CPC-PLUMBING",
                elements=self._room_ids(missing_cold + missing_hot),
            ))
        else:
            self._pass("CPC-SUPPLY-COVERAGE", "Every modeled wet room has connected cold and applicable hot-water supply evidence.")
        if missing_waste:
            issues.append(self._issue(
                "CPC-WASTE-COVERAGE",
                "error",
                f"No connected waste/drain run is modeled in: {self._room_list_text(missing_waste)}.",
                "Route a trapped and vented waste branch from each applicable fixture group.",
                citation_key="CPC-PLUMBING",
                elements=self._room_ids(missing_waste),
            ))
        else:
            self._pass("CPC-WASTE-COVERAGE", "Every modeled wet room has a waste/drain path.")
        if missing_vent:
            issues.append(self._issue(
                "CPC-VENT-COVERAGE",
                "error",
                f"No room-specific plumbing vent connection/evidence is modeled in: {self._room_list_text(missing_vent)}.",
                "Connect each trapped fixture group to a modeled vent path and document vented/vent_id evidence.",
                citation_key="CPC-PLUMBING",
                elements=self._room_ids(missing_vent),
            ))
        else:
            self._pass("CPC-VENT-COVERAGE", "Every modeled wet room has plumbing-vent connection evidence.")

        pipe_types = PLUMBING_SUPPLY_TYPES | PLUMBING_WASTE_TYPES | {"vent", "vent_stack", "soil_stack"}
        pipes = [element for element in plumbing if element.type in pipe_types and element.end]
        unsized = [element for element in pipes if not element.diameter_in or element.diameter_in <= 0]
        if unsized:
            issues.append(self._issue(
                "CPC-PIPE-SIZING-METADATA",
                "warning",
                f"{len(unsized)} plumbing pipe element(s) have no positive diameter.",
                "Populate diameter_in from the calculated fixture-unit demand.",
                citation_key="CPC-PLUMBING",
                elements=[element.id for element in unsized],
            ))
        elif pipes:
            self._pass("CPC-PIPE-SIZING-METADATA", "All modeled plumbing pipe runs have a positive diameter.")

        slope_failures: List[Tuple[MEPElement, str]] = []
        slope_unverified: List[MEPElement] = []
        horizontal_waste: List[MEPElement] = []
        for element in plumbing:
            if element.type not in {"waste_branch", "drain", "fixture_drain", "sewer_lateral", "washer_drain"} or not element.end:
                continue
            dx = element.end[0] - element.start[0]
            dz = element.end[2] - element.start[2]
            run = math.hypot(dx, dz)
            if run < 0.05:
                continue
            horizontal_waste.append(element)
            metadata = self._metadata(element)
            metadata_slope = self._numeric_metadata(metadata, "slope_pct", "actual_slope_pct")
            required_slope = self._numeric_metadata(metadata, "required_slope_pct", "minimum_slope_pct")
            # Drain direction is start (fixture) to end (stack/sewer).  A
            # positive signed geometry slope therefore means vertical drop;
            # using abs() would incorrectly bless an uphill run.
            geometry_slope = (element.start[1] - element.end[1]) / run * 100.0
            actual_slope = metadata_slope if metadata_slope is not None else geometry_slope
            if geometry_slope < -0.01:
                slope_failures.append((element, "modeled geometry rises toward the drain endpoint"))
            elif actual_slope <= 0.01:
                slope_failures.append((element, "actual slope is nonpositive"))
            elif required_slope is None or required_slope <= 0:
                slope_unverified.append(element)
            elif actual_slope + 1e-6 < required_slope:
                slope_failures.append((element, "actual slope is below the documented requirement"))
        if slope_failures:
            issues.append(self._issue(
                "CPC-GRAVITY-DRAIN-SLOPE",
                "error",
                f"{len(slope_failures)} horizontal gravity-drain run(s) are uphill, nonpositive, or below their documented required slope.",
                "Correct drain direction/slope and store signed slope_pct plus the diameter-specific required_slope_pct.",
                citation_key="CPC-PLUMBING",
                elements=[element.id for element, _ in slope_failures],
            ))
        if slope_unverified:
            issues.append(self._issue(
                "CPC-GRAVITY-DRAIN-SLOPE-DOCUMENTATION",
                "info",
                f"{len(slope_unverified)} horizontal gravity-drain run(s) lack a positive documented required slope threshold.",
                "Store required_slope_pct/minimum_slope_pct from the applicable pipe-size and code calculation.",
                citation_key="CPC-PLUMBING",
                elements=[element.id for element in slope_unverified],
                status="unverified",
            ))
        if horizontal_waste and not slope_failures and not slope_unverified:
            self._pass("CPC-GRAVITY-DRAIN-SLOPE", "Signed actual drain slopes meet their documented positive required thresholds.")
        elif not horizontal_waste:
            self._record("CPC-GRAVITY-DRAIN-SLOPE", "not_applicable", "No modeled horizontal gravity-drain runs were found.")

        issues.append(self._issue(
            "CPC-PERMIT-DETAILS",
            "info",
            "Trap seals, vent developed length/sizing, cleanout access, water pressure, and backflow-device selection are not fully encoded in the conceptual element schema.",
            "Complete fixture-unit calculations and permit-level plumbing details before construction documents.",
            citation_key="CPC-PLUMBING",
            status="unverified",
        ))
        return issues

    # ------------------------------------------------------------------
    # Fire / life safety
    # ------------------------------------------------------------------

    def _check_fire_life_safety(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        rooms = self._leaf_rooms(model)
        heads = [
            element for element in model.mep_elements
            if element.system == "fire" and element.type in {"sprinkler", "sprinkler_head"}
        ]
        is_adu = getattr(model.spec, "building_use", None) in ("adu", BuildingUse.adu)
        primary_requirement = str(
            getattr(getattr(model.spec, "primary_dwelling_sprinkler_requirement", None), "value",
                    getattr(model.spec, "primary_dwelling_sprinkler_requirement", ""))
            or ""
        ).lower()
        primary_determination_source = str(
            getattr(model.spec, "primary_dwelling_sprinkler_determination_source", "") or ""
        ).strip()
        valid_adu_exception = (
            is_adu
            and primary_requirement == "not_required"
            and bool(primary_determination_source)
        )
        legacy_unsprinklered = is_adu and getattr(model.spec, "primary_dwelling_sprinklered", None) is False
        construction_scope = str(
            getattr(getattr(model.spec, "construction_scope", "new_construction"), "value",
                    getattr(model.spec, "construction_scope", "new_construction"))
        ).lower()
        new_construction = construction_scope in {"new", "new_build", "new_construction"}

        if legacy_unsprinklered and not valid_adu_exception:
            issues.append(self._issue(
                "FIRE-ADU-SPRINKLER-DETERMINATION",
                "info",
                "Legacy primary_dwelling_sprinklered=False does not establish that sprinklers were legally not required for the primary dwelling, so it cannot establish the ADU exception.",
                "Set primary_dwelling_sprinkler_requirement='not_required' and attach the nonempty AHJ/code determination source.",
                citation_key="CBC-FIRE-LIFE-SAFETY",
                status="unverified",
            ))

        sprinklers_required = new_construction and not valid_adu_exception

        if sprinklers_required and not heads:
            issues.append(self._issue(
                "FIRE-SPRINKLER-SYSTEM",
                "error",
                "No residential sprinkler system is modeled for this new dwelling scope.",
                "Generate the applicable residential sprinkler system and complete listing, obstruction, and hydraulic design with the fire AHJ.",
                citation_key="CBC-FIRE-LIFE-SAFETY",
            ))
        elif heads:
            missing_heads: List[str] = []
            involved: List[str] = []
            for room in [item for item in rooms if item.type in SPRINKLER_ROOMS]:
                room_heads = [head for head in heads if self._element_hits_room(head, room)]
                # 180 sqft/head is a conservative conceptual coverage cell.  A
                # permit design still needs listing, spacing, obstructions and
                # hydraulic calculations.
                expected = max(1, math.ceil(max(room.area_sqft, 1.0) / 180.0))
                if len(room_heads) < expected:
                    missing_heads.append(f"{room.id}: {len(room_heads)}/{expected} head(s)")
                    involved.append(room.id)
            if missing_heads:
                issues.append(self._issue(
                    "FIRE-SPRINKLER-COVERAGE",
                    "warning",
                    "Conceptual sprinkler-head coverage is incomplete: " + "; ".join(missing_heads) + ".",
                    "Lay out heads on the adopted system standard's spacing/coverage rules and complete hydraulic calculations.",
                    citation_key="CBC-FIRE-LIFE-SAFETY",
                    elements=involved,
                ))
            else:
                fire_elements = [element for element in model.mep_elements if element.system == "fire"]
                standards_documented = all(
                    bool(self._metadata(head).get("design_standard")) for head in heads
                )
                listings_documented = all(
                    self._bool_metadata(self._metadata(head), "listed") is True
                    or bool(self._metadata(head).get("listing_reference"))
                    for head in heads
                )
                obstruction_review = all(
                    self._bool_metadata(self._metadata(head), "obstruction_review_complete") is True
                    for head in heads
                )
                hydraulic_evidence = any(
                    self._bool_metadata(self._metadata(element), "hydraulic_design_complete") is True
                    and bool(
                        self._metadata(element).get("hydraulic_calculation_id")
                        or self._metadata(element).get("hydraulic_design_reference")
                    )
                    for element in fire_elements
                )
                if standards_documented and listings_documented and obstruction_review and hydraulic_evidence:
                    self._pass("FIRE-SPRINKLER-COVERAGE", "Head layout, listings, obstruction review, design standard, and hydraulic calculation evidence are documented.")
                else:
                    issues.append(self._issue(
                        "FIRE-SPRINKLER-DESIGN-DOCUMENTATION",
                        "info",
                        "Notional sprinkler head count does not verify product listing, obstruction/spacing compliance, adopted design standard, or hydraulic performance.",
                        "Attach listed-head data, completed obstruction/spacing review, design standard, and referenced hydraulic calculations.",
                        citation_key="CBC-FIRE-LIFE-SAFETY",
                        elements=[head.id for head in heads],
                        status="unverified",
                    ))
        elif valid_adu_exception:
            self._record(
                "FIRE-SPRINKLER-APPLICABILITY",
                "not_applicable",
                "A sourced determination states sprinklers were not legally required for the primary dwelling; the modeled California ADU exception was applied.",
            )
        else:
            issues.append(self._issue(
                "FIRE-SPRINKLER-ALTERATION-APPLICABILITY",
                "info",
                f"Sprinkler applicability for construction scope {construction_scope!r} requires an existing-building and alteration-scope determination.",
                "Attach the AHJ/code applicability determination for the alteration or addition.",
                citation_key="CBC-FIRE-LIFE-SAFETY",
                status="unverified",
            ))

        alarms = [
            element for element in model.mep_elements
            if element.system in {"electrical", "fire"} and self._is_smoke_alarm(element)
        ]
        if alarms:
            bedrooms = [room for room in rooms if room.type == "bedroom"]
            missing_bedrooms = [
                room for room in bedrooms
                if not any(self._element_hits_room(alarm, room) for alarm in alarms)
            ]
            if missing_bedrooms:
                issues.append(self._issue(
                    "FIRE-SMOKE-ALARM-BEDROOM",
                    "error",
                    f"No qualifying smoke alarm/detector is modeled in {len(missing_bedrooms)} bedroom(s): {self._room_list_text(missing_bedrooms)}.",
                    "Add an interconnected smoke alarm in every sleeping room.",
                    citation_key="CBC-FIRE-LIFE-SAFETY",
                    elements=self._room_ids(missing_bedrooms),
                ))
            else:
                self._pass("FIRE-SMOKE-ALARM-BEDROOM", f"Smoke alarms are modeled in all {len(bedrooms)} bedrooms.")

            required_sleeping_zones = {
                (room.level, str(room.unit_id or f"level_{room.level}"))
                for room in bedrooms
            }
            documented_sleeping_zones: Set[Tuple[int, str]] = set()
            for alarm in alarms:
                metadata = self._metadata(alarm)
                is_outside = (
                    self._bool_metadata(metadata, "outside_sleeping_area") is True
                    or str(metadata.get("location_type", "")).lower() == "outside_sleeping_area"
                    or str(metadata.get("location_basis", "")).lower() == "outside_sleeping_area"
                )
                if not is_outside:
                    continue
                zone_id = metadata.get("sleeping_zone_id") or metadata.get("unit_id")
                if zone_id is not None:
                    documented_sleeping_zones.add((alarm.level, str(zone_id)))
                    continue
                # Backward-compatible evidence may omit a zone only when the
                # level contains exactly one sleeping zone; it must never cover
                # multiple dwelling units on the same floor.
                level_zones = {
                    zone for level, zone in required_sleeping_zones
                    if level == alarm.level
                }
                if len(level_zones) == 1:
                    documented_sleeping_zones.add((alarm.level, next(iter(level_zones))))

            missing_outside_zones = sorted(required_sleeping_zones - documented_sleeping_zones)
            if missing_outside_zones:
                issues.append(self._issue(
                    "FIRE-SMOKE-ALARM-OUTSIDE-SLEEPING",
                    "error",
                    "No qualifying smoke alarm is documented outside each sleeping area: "
                    + ", ".join(f"level {level}/{zone}" for level, zone in missing_outside_zones)
                    + ".",
                    "Add an interconnected smoke alarm outside each separate sleeping area and document its location.",
                    citation_key="CBC-FIRE-LIFE-SAFETY",
                ))
            elif bedrooms:
                self._pass("FIRE-SMOKE-ALARM-OUTSIDE-SLEEPING", "Smoke alarms are documented outside every modeled sleeping zone.")

            levels = {room.level for room in rooms}
            missing_alarm_levels = sorted(level for level in levels if not any(alarm.level == level for alarm in alarms))
            if missing_alarm_levels:
                issues.append(self._issue(
                    "FIRE-SMOKE-ALARM-LEVEL",
                    "warning",
                    f"No qualifying smoke-alarm element is modeled on levels {missing_alarm_levels}.",
                    "Provide required alarms on each story and outside sleeping areas.",
                    citation_key="CBC-FIRE-LIFE-SAFETY",
                ))
            else:
                self._pass("FIRE-SMOKE-ALARM-LEVEL", "At least one alarm element is modeled on every occupied level.")

            smoke_documentation_gaps = {
                alarm.id: self._alarm_documentation_gaps(
                    alarm,
                    "UL 217",
                    require_building_power=new_construction,
                )
                for alarm in alarms
            }
            smoke_documentation_gaps = {
                alarm_id: gaps for alarm_id, gaps in smoke_documentation_gaps.items() if gaps
            }
            if smoke_documentation_gaps:
                issues.append(self._issue(
                    "FIRE-SMOKE-ALARM-DOCUMENTATION",
                    "info",
                    f"{len(smoke_documentation_gaps)} smoke alarm(s) lack listing, power, backup-power, or interconnection evidence.",
                    "Attach UL 217 listing evidence and document required power, battery backup, and interconnection.",
                    citation_key="CBC-FIRE-LIFE-SAFETY",
                    elements=list(smoke_documentation_gaps),
                    status="unverified",
                ))
            else:
                self._pass("FIRE-SMOKE-ALARM-DOCUMENTATION", "Smoke-alarm listing, power, backup-power, and interconnection evidence is documented.")
        else:
            issues.append(self._issue(
                "FIRE-SMOKE-ALARM-SYSTEM",
                "error",
                "No dwelling smoke-alarm system is modeled.",
                "Add required alarms in sleeping rooms, outside sleeping areas, and on each story; verify power and interconnection requirements.",
                citation_key="CBC-FIRE-LIFE-SAFETY",
            ))

        fine = getattr(model.spec, "fine_details", None) or {}
        fuel_fired = any(
            str(self._metadata(element).get("fuel_type", "")).lower()
            in {"gas", "natural_gas", "propane", "oil", "fuel_oil", "wood"}
            for element in model.mep_elements
        ) or bool(fine.get("fuel_fired_equipment"))
        fireplace = bool(fine.get("fireplace")) or any(
            str(mesh.get("element_type", "")).lower() in {"fireplace", "fuel_fired_fireplace"}
            for mesh in model.meshes
        )
        attached_garage = bool(fine.get("attached_garage")) or any(
            room.type == "garage" for room in rooms
        )
        co_required = fuel_fired or fireplace or attached_garage
        if co_required:
            co_alarms = [
                element for element in model.mep_elements
                if element.type in CO_ALARM_TYPES and element.system in {"electrical", "fire"}
            ]
            rooms_by_level: Dict[int, List[Room]] = defaultdict(list)
            for room in rooms:
                rooms_by_level[room.level].append(room)
            required_co_zones: Set[Tuple[int, str]] = set()
            bedroom_co_zones = {
                (room.level, str(room.unit_id or f"level_{room.level}"))
                for room in rooms if room.type == "bedroom"
            }
            for level, level_rooms in rooms_by_level.items():
                unit_ids = {str(room.unit_id) for room in level_rooms if room.unit_id}
                level_has_bedrooms = any(room.type == "bedroom" for room in level_rooms)
                if not level_has_bedrooms:
                    # The generator emits one applicable-story CO zone when an
                    # occupied story has no sleeping rooms.  This is distinct
                    # from a sleeping-area placement claim and must retain its
                    # explicit identifier so it cannot be reused on a bedroom
                    # story or another level.
                    required_co_zones.add((level, f"level_{level}_no_sleeping_rooms"))
                elif unit_ids:
                    required_co_zones.update((level, unit_id) for unit_id in unit_ids)
                else:
                    required_co_zones.add((level, f"level_{level}"))

            documented_co_zones: Set[Tuple[int, str]] = set()
            for alarm in co_alarms:
                metadata = self._metadata(alarm)
                zone_id = metadata.get("sleeping_zone_id") or metadata.get("unit_id")
                candidate = (alarm.level, str(zone_id)) if zone_id is not None else None
                if candidate is None:
                    level_zones = {
                        zone for level, zone in required_co_zones if level == alarm.level
                    }
                    if len(level_zones) == 1:
                        candidate = (alarm.level, next(iter(level_zones)))
                if candidate is None:
                    continue
                if candidate in bedroom_co_zones:
                    is_outside = self._bool_metadata(metadata, "outside_sleeping_area") is True
                    if not is_outside:
                        continue
                documented_co_zones.add(candidate)

            missing_co_zones = sorted(required_co_zones - documented_co_zones)
            if not co_alarms or missing_co_zones:
                issues.append(self._issue(
                    "FIRE-CO-ALARM",
                    "error",
                    "A fuel-burning source/fireplace/attached garage triggers CO alarms, but listed alarms outside sleeping areas are missing"
                    + (
                        " for " + ", ".join(
                            f"level {level}/{zone}" for level, zone in missing_co_zones
                        ) + "."
                        if missing_co_zones else "."
                    ),
                    "Add listed CO alarms in every applicable dwelling zone/level and outside each sleeping area.",
                    citation_key="CBC-FIRE-LIFE-SAFETY",
                    elements=[alarm.id for alarm in co_alarms],
                ))
            else:
                co_documentation_gaps = {
                    alarm.id: self._alarm_documentation_gaps(
                        alarm,
                        "UL 2034",
                        require_building_power=new_construction,
                    )
                    for alarm in co_alarms
                }
                co_documentation_gaps = {
                    alarm_id: gaps for alarm_id, gaps in co_documentation_gaps.items() if gaps
                }
                if co_documentation_gaps:
                    issues.append(self._issue(
                        "FIRE-CO-ALARM-DOCUMENTATION",
                        "info",
                        f"{len(co_documentation_gaps)} CO alarm(s) lack listing, power, backup-power, or interconnection evidence.",
                        "Attach UL 2034 listing evidence and document required power, battery backup, and interconnection.",
                        citation_key="CBC-FIRE-LIFE-SAFETY",
                        elements=list(co_documentation_gaps),
                        status="unverified",
                    ))
                else:
                    self._pass("FIRE-CO-ALARM", "Required CO alarm location, listing, power, backup-power, and interconnection evidence is documented.")
        else:
            self._record("FIRE-CO-ALARM", "not_applicable", "No modeled fuel-fired equipment, fireplace, or attached garage triggers the CO-alarm check.")
        return issues

    # ------------------------------------------------------------------
    # 2025 California Energy Code
    # ------------------------------------------------------------------

    def _check_ca_energy_code(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        equipment = [
            element for element in model.mep_elements
            if element.system == "hvac" and element.type in HVAC_EQUIPMENT_TYPES
        ]
        explicit_failures: List[MEPElement] = []
        efficiency_shortfalls: List[MEPElement] = []
        shaped_evidence: List[MEPElement] = []
        malformed_evidence: List[MEPElement] = []
        for element in equipment:
            metadata = self._metadata(element)
            compliant = self._bool_metadata(metadata, "title24_compliant", "energy_code_compliant")
            evidence_reference = (
                metadata.get("compliance_form_id")
                or metadata.get("certificate_reference")
                or metadata.get("approved_calculation_id")
            )
            climate_zone = metadata.get("climate_zone")
            method = metadata.get("compliance_method")
            if compliant is False:
                explicit_failures.append(element)
                continue
            actual = self._numeric_metadata(metadata, "seer2", "seer", "efficiency")
            required = self._numeric_metadata(metadata, "required_seer2", "required_seer", "minimum_efficiency")
            if actual is not None and required is not None and actual < required:
                efficiency_shortfalls.append(element)
            elif (
                actual is not None
                and required is not None
                and self._valid_energy_form_reference(evidence_reference)
                and self._valid_climate_zone(climate_zone)
                and self._valid_energy_method(method)
            ):
                shaped_evidence.append(element)
            else:
                malformed_evidence.append(element)
        if explicit_failures or efficiency_shortfalls:
            failed = list({element.id: element for element in explicit_failures + efficiency_shortfalls}.values())
            issues.append(self._issue(
                "ENERGY-HVAC-EFFICIENCY",
                "warning",
                f"{len(failed)} HVAC equipment element(s) explicitly fail their documented 2025 Title 24 efficiency requirement.",
                "Select compliant equipment and update certified performance/required-efficiency metadata.",
                citation_key="ENERGY-TITLE24",
                elements=[element.id for element in failed],
            ))
        if malformed_evidence:
            issues.append(self._issue(
                "ENERGY-HVAC-DOCUMENTATION",
                "info",
                "HVAC evidence is incomplete or malformed; valid evidence needs quantified actual/required efficiency, climate zone 1-16, a recognized compliance method, and a structured CF1R/CF2R/CF3R form identifier.",
                "Attach certified equipment performance, calculation method, climate zone, and correctly formed compliance-document references.",
                citation_key="ENERGY-TITLE24",
                elements=[element.id for element in malformed_evidence],
                status="unverified",
            ))
        if shaped_evidence:
            issues.append(self._issue(
                "ENERGY-HVAC-EXTERNAL-VERIFICATION",
                "info",
                f"{len(shaped_evidence)} HVAC element(s) have structurally valid evidence metadata, but form registration and CEC-approved software results are not externally verified by this engine.",
                "Verify the registered documents and approved-software output with the authoritative CEC/HERS workflow.",
                citation_key="ENERGY-TITLE24",
                elements=[element.id for element in shaped_evidence],
                status="unverified",
            ))

        energy_metadata = dict((model.design_brief or {}).get("energy", {}) or {})
        envelope_compliant = self._bool_metadata(energy_metadata, "title24_compliant", "envelope_compliant")
        envelope_reference = (
            energy_metadata.get("compliance_form_id")
            or energy_metadata.get("approved_calculation_id")
        )
        envelope_method = energy_metadata.get("compliance_method")
        envelope_climate_zone = energy_metadata.get("climate_zone")
        if envelope_compliant is False:
            issues.append(self._issue(
                "ENERGY-ENVELOPE",
                "warning",
                "Design metadata explicitly marks the envelope as noncompliant with the 2025 California Energy Code.",
                "Revise assemblies/fenestration and rerun the approved compliance-method calculation.",
                citation_key="ENERGY-TITLE24",
            ))
        elif (
            envelope_compliant is True
            and self._valid_energy_form_reference(envelope_reference)
            and self._valid_energy_method(envelope_method)
            and self._valid_climate_zone(envelope_climate_zone)
        ):
            issues.append(self._issue(
                "ENERGY-ENVELOPE-EXTERNAL-VERIFICATION",
                "info",
                "Envelope metadata has a valid climate zone, compliance method, and form-reference shape, but registration and approved-software results are not externally verified.",
                "Verify the registered compliance documents and CEC-approved software output with the authoritative workflow.",
                citation_key="ENERGY-TITLE24",
                status="unverified",
            ))
        else:
            issues.append(self._issue(
                "ENERGY-ENVELOPE-DOCUMENTATION",
                "info",
                "Envelope evidence is incomplete or malformed; climate zone must be 1-16, method must be prescriptive/performance, and the compliance form must have a structured CF1R/CF2R/CF3R identifier.",
                "Complete the 2025 Title 24 workflow and attach correctly structured compliance-document metadata.",
                citation_key="ENERGY-TITLE24",
                status="unverified",
            ))
        return issues

    # ------------------------------------------------------------------
    # Structural / seismic
    # ------------------------------------------------------------------

    def _check_ibc_structural(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        members = list(model.structural_members)
        if model.rooms and not members:
            issues.append(self._issue(
                "STRUCT-SYSTEM-PRESENCE",
                "error",
                "Rooms/building geometry exist but no structural members were generated.",
                "Generate a gravity and lateral structural system before treating the model as complete.",
                citation_key="CBC-STRUCTURAL",
            ))
            return issues

        member_types = {member.type for member in members}
        required_categories = {
            "foundation": {"footing", "grade_beam", "foundation", "pier", "caisson"},
            "vertical": {"column", "bearing_wall", "shear_wall"},
            "horizontal": {"beam", "joist", "slab", "diaphragm"},
        }
        missing = [name for name, aliases in required_categories.items() if not (member_types & aliases)]
        if missing:
            issues.append(self._issue(
                "STRUCT-SYSTEM-COMPONENTS",
                "error",
                f"Generated structural model is missing component categories: {', '.join(missing)}.",
                "Add modeled foundation, vertical, and horizontal load-path members as applicable.",
                citation_key="CBC-STRUCTURAL",
                elements=[member.id for member in members],
            ))
        elif members:
            self._pass(
                "STRUCT-SYSTEM-PRESENCE",
                f"Found {len(members)} members spanning foundation, vertical, and horizontal categories.",
                [member.id for member in members],
            )

        issues.append(self._issue(
            "STRUCT-ENGINEERING-DESIGN",
            "info",
            "Member presence does not prove gravity/lateral capacity, connection design, diaphragm force transfer, foundation adequacy, or construction detailing.",
            "Complete signed structural calculations and drawings for the site hazards and selected material system.",
            citation_key="CBC-STRUCTURAL",
        ))
        return issues

    def _check_seismic_safety(self, model: BuildingModel) -> List[ComplianceIssue]:
        issues: List[ComplianceIssue] = []
        site_context = model.site_context
        if not site_context:
            issues.append(self._issue(
                "SEISMIC-SITE-DATA",
                "info",
                "No site seismic category is attached; seismic component and structural checks are unverified.",
                "Attach site hazard/geotechnical design data before permit-stage analysis.",
                citation_key="ASCE7-SEISMIC",
                status="unverified",
            ))
            return issues
        sdc = str(site_context.seismic_category or "").upper()
        if sdc not in {"C", "D", "E", "F"}:
            self._record("SEISMIC-MEP-BRACING", "not_applicable", f"SDC {sdc or 'unknown'} is outside this preflight's C-F bracing trigger.")
            return issues

        brace_candidates = [
            element for element in model.mep_elements
            if element.system in {"plumbing", "hvac", "fire", "electrical"}
            and max(element.diameter_in or 0.0, element.width_in or 0.0) > 2.5
        ]
        explicit_unbraced: List[MEPElement] = []
        undocumented: List[MEPElement] = []
        for element in brace_candidates:
            state = self._bool_metadata(
                self._metadata(element),
                "seismic_braced", "seismic_bracing", "sway_braced", "anchored",
            )
            if state is False:
                explicit_unbraced.append(element)
            elif state is None:
                undocumented.append(element)
        if explicit_unbraced:
            issues.append(self._issue(
                "SEISMIC-MEP-BRACING",
                "warning",
                f"{len(explicit_unbraced)} MEP component(s) explicitly report no seismic bracing/anchorage in SDC {sdc}.",
                "Design and document component restraints, supports, clearances, and flexible connections.",
                citation_key="ASCE7-SEISMIC",
                elements=[element.id for element in explicit_unbraced],
            ))
        if undocumented:
            issues.append(self._issue(
                "SEISMIC-MEP-BRACING-DOCUMENTATION",
                "info",
                f"{len(undocumented)} MEP component(s) over the conceptual 2.5in screening threshold lack seismic-bracing metadata in SDC {sdc}.",
                "Add seismic_braced/anchored metadata after engineering the applicable ASCE 7 restraints and exemptions.",
                citation_key="ASCE7-SEISMIC",
                elements=[element.id for element in undocumented],
                status="unverified",
            ))
        if brace_candidates and not explicit_unbraced and not undocumented:
            self._pass("SEISMIC-MEP-BRACING", "All screened MEP components affirmatively document seismic restraint/anchorage.")

        member_types = {member.type for member in model.structural_members}
        structural_system = getattr(getattr(model.spec, "structural_system", None), "value", str(getattr(model.spec, "structural_system", "")))
        if str(structural_system).lower() == "wood" and model.structural_members and "shear_wall" not in member_types:
            issues.append(self._issue(
                "SEISMIC-LATERAL-SYSTEM-PRESENCE",
                "warning",
                f"Wood structural model in SDC {sdc} has no modeled shear-wall/lateral-system member.",
                "Add the engineered lateral-force-resisting system and continuous load path.",
                citation_key="ASCE7-SEISMIC",
                elements=[member.id for member in model.structural_members],
            ))
        elif model.structural_members:
            self._pass("SEISMIC-LATERAL-SYSTEM-PRESENCE", "A modeled lateral-system member/path is present for seismic preflight.")

        issues.append(self._issue(
            "SEISMIC-ENGINEERING-REVIEW",
            "info",
            f"SDC {sdc} requires engineered force, drift, anchorage, support-spacing, diaphragm, and connection verification not derivable from member presence alone.",
            "Complete ASCE 7/CBC calculations and construction details with the responsible design professional.",
            citation_key="ASCE7-SEISMIC",
        ))
        return issues


__all__ = ["CODE_CYCLE", "CODE_CYCLE_LABEL", "RULES", "ComplianceEngine"]
