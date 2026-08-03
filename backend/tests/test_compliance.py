from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.constants import BuildingUse
from app.generators.compliance import CODE_CYCLE, ComplianceEngine
from app.models.schemas import (
    BuildingModel,
    ComplianceIssue,
    LatLon,
    MEPElement,
    ProjectSpec,
    Room,
    SiteContext,
    SiteInput,
    StructuralMember,
)


def _room(
    room_id: str,
    room_type: str,
    x0: float,
    z0: float,
    x1: float,
    z1: float,
    *,
    level: int = 0,
    unit_id: str | None = None,
) -> Room:
    return Room(
        id=room_id,
        type=room_type,
        polygon=[[x0, z0], [x1, z0], [x1, z1], [x0, z1]],
        level=level,
        unit_id=unit_id,
        area_sqft=(x1 - x0) * (z1 - z0) * 10.7639,
    )


def _element(
    element_id: str,
    system: str,
    element_type: str,
    room_id: str | None = None,
    *,
    level: int = 0,
    end: list[float] | None = None,
    diameter_in: float | None = None,
    width_in: float | None = None,
    metadata: dict | None = None,
) -> MEPElement:
    element_metadata = dict(metadata or {})
    if room_id is not None:
        element_metadata["room_id"] = room_id
    return MEPElement(
        id=element_id,
        system=system,
        type=element_type,
        start=[0.5, 0.5, 0.5],
        end=end,
        level=level,
        diameter_in=diameter_in,
        width_in=width_in,
        metadata=element_metadata,
    )


def _member(member_id: str, member_type: str) -> StructuralMember:
    return StructuralMember(
        id=member_id,
        type=member_type,
        start=[0.0, 0.0, 0.0],
        end=[1.0, 1.0, 1.0],
        section="test section",
        material="wood",
    )


def _complete_model() -> BuildingModel:
    rooms = [
        _room("kitchen-1", "kitchen", 0.0, 0.0, 4.0, 4.0),
        _room("bath-1", "bathroom", 4.0, 0.0, 6.0, 3.0),
        _room("bed-1", "bedroom", 0.0, 4.0, 4.0, 8.0),
    ]
    spec = ProjectSpec(
        site=SiteInput(latlon=LatLon(lat=37.0, lon=-122.0)),
        building_use=BuildingUse.single_family,
        bedrooms=1,
        bathrooms=1,
        stories=1,
        fine_details={
            "exhaust_fans": True,
        },
    )

    elements = [
        _element("panel", "electrical", "main_panel", metadata={"amps": 200}),
        # This untagged 15A lighting circuit is geometrically inside the
        # kitchen. It must not be misclassified as a 20A kitchen circuit.
        _element(
            "circuit-lighting",
            "electrical",
            "branch_circuit",
            metadata={
                "circuit_id": "lighting",
                "circuit_type": "lighting",
                "amps": 15,
                "panel_id": "panel",
            },
        ),
        _element("light-kitchen", "electrical", "lighting_point", "kitchen-1", metadata={"circuit_id": "lighting"}),
        _element("light-bath", "electrical", "lighting_point", "bath-1", metadata={"circuit_id": "lighting"}),
        _element("light-bed", "electrical", "lighting_point", "bed-1", metadata={"circuit_id": "lighting"}),
        _element(
            "outlet-kitchen",
            "electrical",
            "outlet",
            "kitchen-1",
            metadata={"circuit_id": "kitchen-1", "gfci": True, "afci": True, "max_spacing_ft": 4.0, "countertop": True},
        ),
        _element(
            "outlet-bath",
            "electrical",
            "outlet",
            "bath-1",
            metadata={"circuit_id": "bath", "gfci": True, "max_spacing_ft": 8.0},
        ),
        _element(
            "outlet-bed",
            "electrical",
            "outlet",
            "bed-1",
            metadata={"circuit_id": "lighting", "afci": True, "max_spacing_ft": 10.0},
        ),
        _element(
            "circuit-kitchen-1",
            "electrical",
            "branch_circuit",
            "kitchen-1",
            metadata={
                "circuit_id": "kitchen-1",
                "circuit_type": "kitchen small-appliance",
                "amps": 20,
                "panel_id": "panel",
            },
        ),
        _element(
            "circuit-kitchen-2",
            "electrical",
            "branch_circuit",
            "kitchen-1",
            metadata={
                "circuit_id": "kitchen-2",
                "circuit_type": "kitchen small-appliance",
                "amps": 20,
                "panel_id": "panel",
            },
        ),
        _element(
            "circuit-bath",
            "electrical",
            "branch_circuit",
            "bath-1",
            metadata={
                "circuit_id": "bath",
                "circuit_type": "bathroom receptacle",
                "amps": 20,
                "panel_id": "panel",
            },
        ),
        _element("kitchen-sink", "plumbing", "kitchen_sink", "kitchen-1"),
        _element("toilet", "plumbing", "toilet", "bath-1"),
        _element("lavatory", "plumbing", "sink", "bath-1"),
        _element("shower", "plumbing", "shower", "bath-1"),
        _element(
            "cold-kitchen",
            "plumbing",
            "cold_supply",
            "kitchen-1",
            end=[1.0, 0.5, 1.0],
            diameter_in=0.75,
        ),
        _element(
            "waste-kitchen",
            "plumbing",
            "waste_branch",
            "kitchen-1",
            end=[1.0, 0.45, 1.0],
            diameter_in=2.0,
            metadata={
                "slope_pct": 2.0, "required_slope_pct": 1.0,
                "seismic_braced": True, "vented": True,
            },
        ),
        _element(
            "hot-kitchen",
            "plumbing",
            "hot_supply",
            "kitchen-1",
            end=[1.0, 0.55, 1.0],
            diameter_in=0.75,
        ),
        _element(
            "cold-bath",
            "plumbing",
            "cold_supply",
            "bath-1",
            end=[1.0, 0.5, 1.0],
            diameter_in=0.75,
        ),
        _element(
            "waste-bath",
            "plumbing",
            "waste_branch",
            "bath-1",
            end=[1.0, 0.45, 1.0],
            diameter_in=3.0,
            metadata={
                "slope_pct": 2.0, "required_slope_pct": 1.0,
                "seismic_braced": True, "vented": True,
            },
        ),
        _element(
            "hot-bath",
            "plumbing",
            "hot_supply",
            "bath-1",
            end=[1.0, 0.55, 1.0],
            diameter_in=0.75,
        ),
        _element(
            "condenser",
            "hvac",
            "condenser_unit",
            metadata={
                "title24_compliant": True,
                "seer2": 16.0,
                "required_seer2": 15.2,
                "climate_zone": 3,
                "compliance_method": "performance",
                "compliance_form_id": "CF1R-PRF-01-E",
                "anchored": True,
            },
        ),
        _element("head-kitchen", "hvac", "mini_split_head", "kitchen-1"),
        _element("head-bedroom", "hvac", "mini_split_head", "bed-1"),
        _element(
            "ventilator",
            "hvac",
            "whole_house_ventilator",
            metadata={
                "outdoor_air_cfm": 35,
                "required_outdoor_air_cfm": 30,
                "ventilation_calculation_id": "ASHRAE62.2-CALC-1",
                "calculation_verified": True,
            },
        ),
        _element(
            "exhaust-kitchen", "hvac", "range_hood", "kitchen-1",
            metadata={
                "capacity_cfm": 100, "required_exhaust_cfm": 100,
                "calculation_reference": "LOCAL-EXHAUST-KITCHEN-1",
                "calculation_verified": True, "terminates_outdoors": True,
            },
        ),
        _element(
            "exhaust-bath", "hvac", "bath_exhaust", "bath-1",
            metadata={
                "capacity_cfm": 50, "required_exhaust_cfm": 50,
                "calculation_reference": "LOCAL-EXHAUST-BATH-1",
                "calculation_verified": True, "terminates_outdoors": True,
            },
        ),
        _element("sprinkler-kitchen", "fire", "sprinkler", "kitchen-1", metadata={"design_standard": "NFPA 13D", "listed": True, "obstruction_review_complete": True}),
        _element("sprinkler-bath", "fire", "sprinkler", "bath-1", metadata={"design_standard": "NFPA 13D", "listed": True, "obstruction_review_complete": True}),
        _element("sprinkler-bedroom", "fire", "sprinkler", "bed-1", metadata={"design_standard": "NFPA 13D", "listed": True, "obstruction_review_complete": True}),
        _element("sprinkler-riser", "fire", "sprinkler_riser", end=[0.5, 3.0, 0.5], metadata={"hydraulic_design_complete": True, "hydraulic_calculation_id": "HYD-001"}),
        _element(
            "alarm-bedroom",
            "electrical",
            "smoke_alarm",
            "bed-1",
            metadata={
                "hardwired": True,
                "battery_backup": True,
                "interconnected": True,
                "listed": True,
                "listing_standard": "UL 217",
            },
        ),
        _element(
            "alarm-outside-sleeping",
            "electrical",
            "smoke_alarm",
            metadata={
                "outside_sleeping_area": True,
                "hardwired": True,
                "battery_backup": True,
                "interconnected": True,
                "listed": True,
                "listing_standard": "UL 217",
            },
        ),
    ]

    return BuildingModel(
        project_id="compliance-test",
        spec=spec,
        site_context=SiteContext(
            parcel_polygon={"type": "Polygon", "coordinates": []},
            buildable_envelope_2d={"type": "Polygon", "coordinates": []},
            area_sqft=5000,
            centroid=LatLon(lat=37.0, lon=-122.0),
            flood_zone="X",
            flood_flag=False,
        ),
        rooms=rooms,
        mep_elements=elements,
        structural_members=[
            _member("footing", "footing"),
            _member("column", "column"),
            _member("beam", "beam"),
            _member("shear-wall", "shear_wall"),
        ],
        meshes=[{"element_id": "front-door", "element_type": "exterior_door"}],
        design_brief={"energy": {
            "envelope_compliant": True,
            "climate_zone": 3,
            "compliance_method": "performance",
            "compliance_form_id": "CF1R-PRF-01-E",
        }},
    )


def _rule_ids(issues: list[ComplianceIssue]) -> set[str]:
    return {issue.id.rsplit("-", 1)[0] for issue in issues}


def test_complete_evidence_model_has_no_manufactured_failures() -> None:
    model = _complete_model()

    issues = ComplianceEngine().run(model)

    assert not [issue for issue in issues if issue.severity in {"error", "warning"}]
    assert model.compliance_summary["code_cycle"] == CODE_CYCLE == "2025"
    assert model.compliance_summary["status"] == "unverified"
    assert model.compliance_summary["permit_ready"] is False
    assert model.compliance_summary["issue_counts"]["total"] == len(issues)
    assert all(issue.severity == "info" for issue in issues)


def test_missing_systems_fail_room_coverage_and_structure_checks() -> None:
    model = _complete_model()
    model.mep_elements = []
    model.structural_members = []

    issues = ComplianceEngine().run(model)
    ids = _rule_ids(issues)

    assert {
        "MEP-ELECTRICAL-COVERAGE",
        "MEP-PLUMBING-COVERAGE",
        "MEP-HVAC-COVERAGE",
        "STRUCT-SYSTEM-PRESENCE",
    } <= ids
    assert model.compliance_summary["status"] == "failed"


def test_empty_floorplan_is_a_measurable_completion_error() -> None:
    model = _complete_model()
    model.rooms = []

    issues = ComplianceEngine().run(model)

    assert "BUILDING-ROOM-PRESENCE" in _rule_ids(issues)
    assert next(
        issue for issue in issues if issue.id.startswith("BUILDING-ROOM-PRESENCE")
    ).severity == "error"


def test_actual_circuit_and_fixture_evidence_is_counted_per_room() -> None:
    model = _complete_model()
    model.mep_elements = [
        element
        for element in model.mep_elements
        if element.id not in {"circuit-kitchen-2", "shower"}
    ]

    issues = ComplianceEngine().run(model)
    ids = _rule_ids(issues)

    assert "CEC-DEDICATED-CIRCUITS" in ids
    assert "CPC-FIXTURE-COMPLETENESS" in ids
    assert next(issue for issue in issues if issue.id.startswith("CEC-DEDICATED-CIRCUITS")).severity == "error"
    assert next(issue for issue in issues if issue.id.startswith("CPC-FIXTURE-COMPLETENESS")).severity == "error"


def test_unverified_seismic_design_is_information_not_a_fake_violation() -> None:
    model = _complete_model()
    model.site_context = SiteContext(
        parcel_polygon={"type": "Polygon", "coordinates": []},
        buildable_envelope_2d={"type": "Polygon", "coordinates": []},
        area_sqft=5000,
        centroid=LatLon(lat=37.0, lon=-122.0),
        seismic_category="D",
    )
    model.mep_elements.append(
        _element(
            "return-without-brace-documentation",
            "hvac",
            "return_branch",
            "bed-1",
            end=[1.0, 0.5, 1.0],
            width_in=8.0,
            metadata={"duct_r_value": 8},
        )
    )

    issues = ComplianceEngine().run(model)
    seismic_documentation = next(
        issue for issue in issues
        if issue.id.startswith("SEISMIC-MEP-BRACING-DOCUMENTATION")
    )

    assert seismic_documentation.severity == "info"
    assert not [
        issue for issue in issues
        if issue.severity in {"error", "warning"} and issue.id.startswith("SEISMIC-")
    ]


def test_explicit_energy_failure_is_a_warning() -> None:
    model = _complete_model()
    condenser = next(element for element in model.mep_elements if element.id == "condenser")
    condenser.metadata["title24_compliant"] = False

    issues = ComplianceEngine().run(model)
    energy_issue = next(issue for issue in issues if issue.id.startswith("ENERGY-HVAC-EFFICIENCY"))

    assert energy_issue.severity == "warning"
    assert energy_issue.elements_involved == ["condenser"]


def test_upstream_non_compliance_issues_survive_reruns_without_duplication() -> None:
    model = _complete_model()
    clash = ComplianceIssue(
        id="clash-existing",
        type="clash",
        severity="error",
        message="Existing routed-system clash.",
        fix_suggestion="Reroute one element.",
        elements_involved=["a", "b"],
    )
    model.issues = [clash]
    engine = ComplianceEngine()

    first = engine.run(model)
    second = engine.run(model)

    assert [issue.id for issue in first].count("clash-existing") == 1
    assert [issue.id for issue in second].count("clash-existing") == 1
    assert [issue.id for issue in model.issues].count("clash-existing") == 1
    assert model.compliance_summary["preserved_issue_counts"]["error"] == 1
    assert model.compliance_summary["status"] == "failed"


def test_served_room_ids_can_document_a_shared_hvac_zone() -> None:
    model = _complete_model()
    model.mep_elements = [
        element for element in model.mep_elements if element.id != "head-kitchen"
    ]
    bedroom_head = next(element for element in model.mep_elements if element.id == "head-bedroom")
    bedroom_head.metadata["served_room_ids"] = ["bed-1", "kitchen-1"]

    issues = ComplianceEngine().run(model)

    assert "MEP-HVAC-COVERAGE" not in _rule_ids(issues)


def test_required_fire_systems_cannot_be_disabled_into_a_pass() -> None:
    model = _complete_model()
    model.spec.fine_details = {"fire_sprinklers": False, "fire_alarms": False}
    model.mep_elements = [
        element for element in model.mep_elements
        if element.system != "fire" and element.type not in {"fire_alarm", "smoke_alarm", "smoke_detector"}
    ]

    issues = ComplianceEngine().run(model)

    assert {"FIRE-SPRINKLER-SYSTEM", "FIRE-SMOKE-ALARM-SYSTEM"} <= _rule_ids(issues)
    assert model.compliance_summary["status"] == "failed"


def test_legacy_unsprinklered_primary_dwelling_boolean_cannot_exempt_adu() -> None:
    model = _complete_model()
    model.spec = ProjectSpec(
        site=model.spec.site,
        building_use=BuildingUse.adu,
        bedrooms=1,
        bathrooms=1,
        stories=1,
        primary_dwelling_sprinklered=False,
    )
    model.mep_elements = [element for element in model.mep_elements if element.system != "fire"]

    issues = ComplianceEngine().run(model)

    assert {"FIRE-ADU-SPRINKLER-DETERMINATION", "FIRE-SPRINKLER-SYSTEM"} <= _rule_ids(issues)
    assert model.compliance_summary["status"] == "failed"


def test_sourced_primary_dwelling_requirement_can_establish_adu_exception() -> None:
    model = _complete_model()
    model.spec = ProjectSpec(
        site=model.spec.site,
        building_use=BuildingUse.adu,
        bedrooms=1,
        bathrooms=1,
        stories=1,
        primary_dwelling_sprinkler_requirement="not_required",
        primary_dwelling_sprinkler_determination_source="AHJ determination ADU-2026-001",
    )
    model.mep_elements = [element for element in model.mep_elements if element.system != "fire"]

    issues = ComplianceEngine().run(model)

    assert "FIRE-SPRINKLER-SYSTEM" not in _rule_ids(issues)
    applicability = next(
        check for check in model.compliance_summary["checks"]
        if check["rule_id"] == "FIRE-SPRINKLER-APPLICABILITY"
    )
    assert applicability["status"] == "not_applicable"


def test_earlier_code_cycle_needs_matching_filing_date_and_is_unverified() -> None:
    model = _complete_model()
    model.spec = ProjectSpec(
        site=model.spec.site,
        building_use=BuildingUse.single_family,
        code_cycle="2022",
        permit_application_date=date(2025, 12, 31),
        bedrooms=1,
        bathrooms=1,
        stories=1,
    )

    issues = ComplianceEngine().run(model)

    assert "SCOPE-2025" in _rule_ids(issues)
    assert model.compliance_summary["status"] == "unverified"

    with pytest.raises(ValidationError):
        ProjectSpec(
            site=SiteInput(latlon=LatLon(lat=37.0, lon=-122.0)),
            building_use=BuildingUse.single_family,
            code_cycle="2022",
            permit_application_date=date(2026, 1, 1),
        )


@pytest.mark.parametrize(
    ("filing_date", "code_cycle"),
    [
        (date(2022, 12, 31), "2022"),
        (date(2029, 1, 1), "2025"),
    ],
)
def test_filing_dates_outside_implemented_code_cycles_are_rejected(
    filing_date: date,
    code_cycle: str,
) -> None:
    with pytest.raises(ValidationError, match="outside the supported California code-cycle"):
        ProjectSpec(
            site=SiteInput(latlon=LatLon(lat=37.0, lon=-122.0)),
            building_use=BuildingUse.single_family,
            code_cycle=code_cycle,
            permit_application_date=filing_date,
        )


def test_bare_energy_compliance_booleans_remain_unverified() -> None:
    model = _complete_model()
    condenser = next(element for element in model.mep_elements if element.id == "condenser")
    condenser.metadata = {"title24_compliant": True, "seer2": 16.0}
    model.design_brief = {"energy": {"envelope_compliant": True}}

    issues = ComplianceEngine().run(model)

    assert {"ENERGY-HVAC-DOCUMENTATION", "ENERGY-ENVELOPE-DOCUMENTATION"} <= _rule_ids(issues)
    assert model.compliance_summary["status"] == "unverified"


def test_mapped_flood_hazard_without_elevation_comparison_is_unverified() -> None:
    model = _complete_model()
    model.site_context.flood_zone = "AE"
    model.site_context.flood_flag = True

    issues = ComplianceEngine().run(model)

    flood = next(issue for issue in issues if issue.id.startswith("FLOOD-REVIEW"))
    assert flood.severity == "info"
    assert next(
        check["status"] for check in model.compliance_summary["checks"]
        if check["rule_id"] == "FLOOD-REVIEW"
    ) == "unverified"


def test_internal_corridor_pinch_point_fails_exact_36in_screen() -> None:
    model = _complete_model()
    pinch_polygon = [
        [0.0, 0.0], [3.0, 0.0], [3.0, 1.25], [5.0, 1.25],
        [5.0, 0.0], [8.0, 0.0], [8.0, 3.0], [5.0, 3.0],
        [5.0, 1.75], [3.0, 1.75], [3.0, 3.0], [0.0, 3.0],
    ]
    model.rooms.append(Room(
        id="pinched-hall",
        type="corridor",
        polygon=pinch_polygon,
        level=0,
        area_sqft=210.0,
    ))
    model.mep_elements.append(
        _element("pinched-hall-light", "electrical", "lighting_point", "pinched-hall", metadata={"circuit_id": "lighting"})
    )

    issues = ComplianceEngine().run(model)

    corridor = next(issue for issue in issues if issue.id.startswith("CBC-CORRIDOR-WIDTH-"))
    assert corridor.severity == "error"
    assert "internal pinch point" in corridor.message


def test_unknown_room_type_cannot_bypass_mep_applicability() -> None:
    model = _complete_model()
    model.rooms.append(_room("nursery-1", "nursery", 7.0, 0.0, 10.0, 3.0))

    issues = ComplianceEngine().run(model)

    issue = next(issue for issue in issues if issue.id.startswith("MEP-ROOM-TYPE-SCOPE"))
    assert issue.severity == "error"
    assert issue.elements_involved == ["nursery-1"]


def test_disabled_local_exhaust_without_verified_alternative_is_unverified() -> None:
    model = _complete_model()
    model.spec.fine_details = {"exhaust_fans": False}
    model.mep_elements = [
        element for element in model.mep_elements
        if element.type not in {"range_hood", "bath_exhaust", "exhaust_fan"}
    ]

    issues = ComplianceEngine().run(model)

    assert "CMC-LOCAL-EXHAUST-DISABLED" in _rule_ids(issues)
    assert model.compliance_summary["status"] == "unverified"


def test_tiny_whole_building_ventilation_airflow_cannot_pass() -> None:
    model = _complete_model()
    ventilator = next(element for element in model.mep_elements if element.id == "ventilator")
    ventilator.metadata.update({
        "actual_outdoor_air_cfm": 0.1,
        "outdoor_air_cfm": 0.1,
        "required_outdoor_air_cfm": 30.0,
        "calculation_verified": True,
    })

    issues = ComplianceEngine().run(model)

    issue = next(issue for issue in issues if issue.id.startswith("CMC-WHOLE-BUILDING-VENTILATION-AIRFLOW"))
    assert issue.severity == "error"


def test_unverified_ventilation_calculation_cannot_pass() -> None:
    model = _complete_model()
    ventilator = next(element for element in model.mep_elements if element.id == "ventilator")
    ventilator.metadata["calculation_verified"] = False

    issues = ComplianceEngine().run(model)

    assert "CMC-WHOLE-BUILDING-VENTILATION-DOCUMENTATION" in _rule_ids(issues)
    assert model.compliance_summary["status"] == "unverified"


def test_cold_only_supply_and_missing_plumbing_vent_fail() -> None:
    model = _complete_model()
    model.mep_elements = [
        element for element in model.mep_elements
        if element.type != "hot_supply"
    ]
    for element in model.mep_elements:
        if element.type in {"waste_branch", "drain", "fixture_drain"}:
            element.metadata.pop("vented", None)
            element.metadata.pop("vent_id", None)

    issues = ComplianceEngine().run(model)

    ids = _rule_ids(issues)
    assert {"CPC-SUPPLY-COVERAGE", "CPC-VENT-COVERAGE"} <= ids
    assert all(
        next(issue for issue in issues if issue.id.startswith(rule_id)).severity == "error"
        for rule_id in {"CPC-SUPPLY-COVERAGE", "CPC-VENT-COVERAGE"}
    )


def test_generic_fire_alarm_is_not_accepted_as_smoke_alarm() -> None:
    model = _complete_model()
    model.mep_elements = [element for element in model.mep_elements if element.type != "smoke_alarm"]
    model.mep_elements.extend([
        _element("generic-fire-alarm-bedroom", "electrical", "fire_alarm", "bed-1"),
        _element("generic-fire-alarm-story", "electrical", "fire_alarm", metadata={"outside_sleeping_area": True}),
    ])

    issues = ComplianceEngine().run(model)

    assert "FIRE-SMOKE-ALARM-SYSTEM" in _rule_ids(issues)
    assert next(
        issue for issue in issues if issue.id.startswith("FIRE-SMOKE-ALARM-SYSTEM")
    ).severity == "error"


def test_missing_outside_sleeping_area_alarm_fails() -> None:
    model = _complete_model()
    model.mep_elements = [
        element for element in model.mep_elements
        if element.id != "alarm-outside-sleeping"
    ]

    issues = ComplianceEngine().run(model)

    assert "FIRE-SMOKE-ALARM-OUTSIDE-SLEEPING" in _rule_ids(issues)


def test_smoke_alarm_listing_power_and_interconnection_are_required_evidence() -> None:
    model = _complete_model()
    alarm = next(element for element in model.mep_elements if element.id == "alarm-bedroom")
    # A generic listed=True flag is not evidence of the smoke-alarm product
    # standard.  Keep every other field complete and remove only UL 217.
    alarm.metadata.pop("listing_standard", None)

    issues = ComplianceEngine().run(model)

    issue = next(
        item for item in issues
        if item.id.startswith("FIRE-SMOKE-ALARM-DOCUMENTATION")
    )
    assert issue.severity == "info"
    assert model.compliance_summary["status"] == "unverified"


def test_outside_sleeping_alarm_is_required_per_dwelling_zone_not_just_level() -> None:
    model = _complete_model()
    bedroom = next(room for room in model.rooms if room.id == "bed-1")
    bedroom.unit_id = "unit-a"
    outside = next(element for element in model.mep_elements if element.id == "alarm-outside-sleeping")
    outside.metadata["sleeping_zone_id"] = "unit-a"
    model.rooms.append(_room("bed-2", "bedroom", 6.0, 4.0, 8.0, 8.0, unit_id="unit-b"))
    model.mep_elements.append(_element(
        "alarm-bedroom-2", "electrical", "smoke_alarm", "bed-2",
        metadata={
            "hardwired": True, "battery_backup": True,
            "interconnected": True, "listed": True,
            "listing_standard": "UL 217",
        },
    ))

    issues = ComplianceEngine().run(model)

    assert "FIRE-SMOKE-ALARM-OUTSIDE-SLEEPING" in _rule_ids(issues)


def test_conditional_carbon_monoxide_alarm_requirement_is_enforced() -> None:
    model = _complete_model()
    model.spec.fine_details = {"exhaust_fans": True, "attached_garage": True}

    issues = ComplianceEngine().run(model)

    co = next(issue for issue in issues if issue.id.startswith("FIRE-CO-ALARM"))
    assert co.severity == "error"


def test_carbon_monoxide_alarm_requires_listing_power_and_interconnection_evidence() -> None:
    model = _complete_model()
    model.spec.fine_details = {"exhaust_fans": True, "attached_garage": True}
    model.mep_elements.append(_element(
        "co-level-0", "electrical", "carbon_monoxide_alarm",
        metadata={
            "outside_sleeping_area": True,
            "hardwired": True, "battery_backup": True,
            "interconnected": True, "listed": True,
        },
    ))

    issues = ComplianceEngine().run(model)

    issue = next(
        item for item in issues
        if item.id.startswith("FIRE-CO-ALARM-DOCUMENTATION")
    )
    assert issue.severity == "info"
    assert model.compliance_summary["status"] == "unverified"


def test_carbon_monoxide_alarm_is_required_per_dwelling_zone() -> None:
    model = _complete_model()
    model.spec.fine_details = {"exhaust_fans": True, "attached_garage": True}
    for room in model.rooms:
        room.unit_id = "unit-a"
    model.rooms.append(_room("bed-unit-b", "bedroom", 6.0, 4.0, 8.0, 8.0, unit_id="unit-b"))
    model.mep_elements.append(_element(
        "co-unit-a", "electrical", "carbon_monoxide_alarm",
        metadata={
            "unit_id": "unit-a", "outside_sleeping_area": True,
            "hardwired": True, "battery_backup": True,
            "interconnected": True, "listed": True,
            "listing_standard": "UL 2034",
        },
    ))

    issues = ComplianceEngine().run(model)

    co = next(issue for issue in issues if issue.id.startswith("FIRE-CO-ALARM-01"))
    assert co.severity == "error"


def test_absent_receptacle_spacing_evidence_is_unverified() -> None:
    model = _complete_model()
    for element in model.mep_elements:
        if element.type in {"outlet", "receptacle", "gfci_outlet", "afci_outlet"}:
            element.metadata.pop("max_spacing_ft", None)
            element.metadata.pop("design_spacing_ft", None)

    issues = ComplianceEngine().run(model)

    assert "CEC-RECEPTACLE-SPACING-DOCUMENTATION" in _rule_ids(issues)
    assert model.compliance_summary["status"] == "unverified"


def test_arbitrary_energy_identifiers_and_climate_zone_cannot_pass() -> None:
    model = _complete_model()
    condenser = next(element for element in model.mep_elements if element.id == "condenser")
    condenser.metadata.update({"compliance_form_id": "CF1R-TEST", "climate_zone": 99})
    model.design_brief["energy"].update({
        "compliance_form_id": "CF1R-TEST",
        "climate_zone": 99,
    })

    issues = ComplianceEngine().run(model)

    assert {"ENERGY-HVAC-DOCUMENTATION", "ENERGY-ENVELOPE-DOCUMENTATION"} <= _rule_ids(issues)
    assert not [
        check for check in model.compliance_summary["checks"]
        if check["rule_id"] in {"ENERGY-HVAC-EFFICIENCY", "ENERGY-ENVELOPE"}
        and check["status"] == "pass"
    ]


def test_sprinkler_head_count_without_design_evidence_is_unverified() -> None:
    model = _complete_model()
    model.mep_elements = [
        element for element in model.mep_elements if element.id != "sprinkler-riser"
    ]
    for element in model.mep_elements:
        if element.type in {"sprinkler", "sprinkler_head"}:
            element.metadata = {"room_id": element.metadata["room_id"]}

    issues = ComplianceEngine().run(model)

    assert "FIRE-SPRINKLER-DESIGN-DOCUMENTATION" in _rule_ids(issues)
    assert not [
        check for check in model.compliance_summary["checks"]
        if check["rule_id"] == "FIRE-SPRINKLER-COVERAGE" and check["status"] == "pass"
    ]


def test_addition_scope_does_not_apply_new_dwelling_sprinkler_assumption() -> None:
    model = _complete_model()
    model.spec.construction_scope = "addition"
    model.mep_elements = [element for element in model.mep_elements if element.system != "fire"]

    issues = ComplianceEngine().run(model)

    assert "FIRE-SPRINKLER-SYSTEM" not in _rule_ids(issues)
    assert "FIRE-SPRINKLER-ALTERATION-APPLICABILITY" in _rule_ids(issues)
    assert model.compliance_summary["status"] == "unverified"


def test_adu_local_area_height_and_setbacks_require_sourced_evidence() -> None:
    model = _complete_model()
    model.spec = ProjectSpec(
        site=model.spec.site,
        building_use=BuildingUse.adu,
        bedrooms=1,
        bathrooms=1,
        stories=1,
        max_floors=2,
        fine_details={"exhaust_fans": True, "adu_max_sqft": 1400},
    )

    issues = ComplianceEngine().run(model)

    assert {
        "ADU-AREA-LOCAL-STANDARD",
        "ADU-HEIGHT-LOCAL-STANDARD",
        "ADU-SETBACK-EVIDENCE",
    } <= _rule_ids(issues)
    assert model.compliance_summary["status"] == "unverified"


def test_fire_citation_uses_current_2025_crc_sections() -> None:
    model = _complete_model()
    model.mep_elements = [element for element in model.mep_elements if element.system != "fire"]

    issues = ComplianceEngine().run(model)
    fire_issue = next(issue for issue in issues if issue.id.startswith("FIRE-SPRINKLER-SYSTEM"))

    assert "R309-R311" in fire_issue.citation
    assert "R313-R315" not in fire_issue.citation


def test_generator_room_types_are_classified_not_rejected_as_unknown() -> None:
    model = _complete_model()
    model.rooms.extend([
        _room("closet-1", "walk_in_closet", 7.0, 0.0, 8.0, 2.0),
        _room("library-1", "library", 8.0, 0.0, 10.0, 2.0),
        _room("gym-1", "gym", 10.0, 0.0, 12.0, 2.0),
    ])

    issues = ComplianceEngine().run(model)

    assert "MEP-ROOM-TYPE-SCOPE" not in _rule_ids(issues)
    electrical = next(issue for issue in issues if issue.id.startswith("MEP-ELECTRICAL-COVERAGE"))
    assert {"closet-1", "library-1", "gym-1"} <= set(electrical.elements_involved)
    hvac = next(issue for issue in issues if issue.id.startswith("MEP-HVAC-COVERAGE"))
    assert {"library-1", "gym-1"} <= set(hvac.elements_involved)


def test_co_applicable_story_identifier_covers_level_without_bedrooms() -> None:
    model = _complete_model()
    bedroom = next(room for room in model.rooms if room.id == "bed-1")
    bedroom.type = "living"
    model.spec.fine_details = {"exhaust_fans": True, "fuel_fired_equipment": True}
    model.mep_elements.append(_element(
        "co-no-sleeping-level-0",
        "electrical",
        "carbon_monoxide_alarm",
        metadata={
            "sleeping_zone_id": "level_0_no_sleeping_rooms",
            "location_basis": "applicable_story",
            "hardwired": True,
            "battery_backup": True,
            "interconnected": True,
            "listed": True,
            "listing_standard": "UL 2034",
        },
    ))

    issues = ComplianceEngine().run(model)

    assert not [issue for issue in issues if issue.id.startswith("FIRE-CO-ALARM")]
    assert next(
        check["status"] for check in model.compliance_summary["checks"]
        if check["rule_id"] == "FIRE-CO-ALARM"
    ) == "pass"


def test_local_exhaust_actual_airflow_below_requirement_fails() -> None:
    model = _complete_model()
    exhaust = next(element for element in model.mep_elements if element.id == "exhaust-bath")
    exhaust.metadata["capacity_cfm"] = 20
    exhaust.metadata["required_exhaust_cfm"] = 50

    issues = ComplianceEngine().run(model)

    issue = next(issue for issue in issues if issue.id.startswith("CMC-LOCAL-EXHAUST-AIRFLOW"))
    assert issue.severity == "error"
    assert issue.elements_involved == ["exhaust-bath"]


def test_local_exhaust_requires_verified_calculation_before_pass() -> None:
    model = _complete_model()
    exhaust = next(element for element in model.mep_elements if element.id == "exhaust-bath")
    exhaust.metadata["calculation_verified"] = False

    issues = ComplianceEngine().run(model)

    assert "CMC-LOCAL-EXHAUST-CALCULATION" in _rule_ids(issues)
    assert not [
        check for check in model.compliance_summary["checks"]
        if check["rule_id"] == "CMC-LOCAL-EXHAUST-AIRFLOW" and check["status"] == "pass"
    ]


def test_duct_insulation_needs_actual_and_required_r_values() -> None:
    model = _complete_model()
    duct = _element(
        "duct-1", "hvac", "supply_branch", "bed-1",
        end=[1.0, 2.3, 1.0], width_in=8.0,
        metadata={"duct_r_value": 8.0},
    )
    model.mep_elements.append(duct)

    issues = ComplianceEngine().run(model)
    assert "CMC-DUCT-INSULATION-DOCUMENTATION" in _rule_ids(issues)

    duct.metadata["required_duct_r_value"] = 8.0
    issues = ComplianceEngine().run(model)
    assert "CMC-DUCT-INSULATION-DOCUMENTATION" not in _rule_ids(issues)
    assert next(
        check["status"] for check in model.compliance_summary["checks"]
        if check["rule_id"] == "CMC-DUCT-INSULATION"
    ) == "pass"


def test_uphill_gravity_drain_fails_even_with_positive_metadata_slope() -> None:
    model = _complete_model()
    drain = next(element for element in model.mep_elements if element.id == "waste-kitchen")
    drain.end = [1.0, drain.start[1] + 0.2, 1.0]
    drain.metadata.update({"slope_pct": 2.0, "required_slope_pct": 1.0})

    issues = ComplianceEngine().run(model)

    issue = next(issue for issue in issues if issue.id.startswith("CPC-GRAVITY-DRAIN-SLOPE-"))
    assert issue.severity == "error"
    assert issue.elements_involved == ["waste-kitchen"]


def test_gravity_drain_requires_documented_slope_threshold_before_pass() -> None:
    model = _complete_model()
    for element in model.mep_elements:
        if element.type == "waste_branch":
            element.metadata.pop("required_slope_pct", None)

    issues = ComplianceEngine().run(model)

    assert "CPC-GRAVITY-DRAIN-SLOPE-DOCUMENTATION" in _rule_ids(issues)
    assert not [
        check for check in model.compliance_summary["checks"]
        if check["rule_id"] == "CPC-GRAVITY-DRAIN-SLOPE" and check["status"] == "pass"
    ]
