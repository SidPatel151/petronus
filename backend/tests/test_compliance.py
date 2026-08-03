from __future__ import annotations

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
) -> Room:
    return Room(
        id=room_id,
        type=room_type,
        polygon=[[x0, z0], [x1, z0], [x1, z1], [x0, z1]],
        level=level,
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
            "exhaust_fans": False,
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
            metadata={"circuit_id": "kitchen-1", "gfci": True, "afci": True},
        ),
        _element(
            "outlet-bath",
            "electrical",
            "outlet",
            "bath-1",
            metadata={"circuit_id": "bath", "gfci": True},
        ),
        _element(
            "outlet-bed",
            "electrical",
            "outlet",
            "bed-1",
            metadata={"circuit_id": "lighting", "afci": True},
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
            metadata={"slope_pct": 2.0, "seismic_braced": True},
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
            metadata={"slope_pct": 2.0, "seismic_braced": True},
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
                "compliance_form_id": "CF1R-TEST",
                "anchored": True,
            },
        ),
        _element("head-kitchen", "hvac", "mini_split_head", "kitchen-1"),
        _element("head-bedroom", "hvac", "mini_split_head", "bed-1"),
        _element(
            "ventilator",
            "hvac",
            "whole_house_ventilator",
            metadata={"outdoor_air_cfm": 35},
        ),
        _element("sprinkler-kitchen", "fire", "sprinkler", "kitchen-1"),
        _element("sprinkler-bath", "fire", "sprinkler", "bath-1"),
        _element("sprinkler-bedroom", "fire", "sprinkler", "bed-1"),
        _element(
            "alarm-bedroom",
            "electrical",
            "fire_alarm",
            "bed-1",
            metadata={"hardwired": True, "interconnected": True},
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
            "compliance_form_id": "CF1R-TEST",
        }},
    )


def _rule_ids(issues: list[ComplianceIssue]) -> set[str]:
    return {issue.id.rsplit("-", 1)[0] for issue in issues}


def test_complete_evidence_model_has_no_manufactured_failures() -> None:
    model = _complete_model()

    issues = ComplianceEngine().run(model)

    assert not [issue for issue in issues if issue.severity in {"error", "warning"}]
    assert model.compliance_summary["code_cycle"] == CODE_CYCLE == "2025"
    assert model.compliance_summary["status"] == "preflight_passed"
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
        if element.system != "fire" and element.type != "fire_alarm"
    ]

    issues = ComplianceEngine().run(model)

    assert {"FIRE-SPRINKLER-SYSTEM", "FIRE-SMOKE-ALARM-SYSTEM"} <= _rule_ids(issues)
    assert model.compliance_summary["status"] == "failed"


def test_unsprinklered_primary_dwelling_adu_exception_is_modeled() -> None:
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

    assert "FIRE-SPRINKLER-SYSTEM" not in _rule_ids(issues)


def test_unsupported_code_cycle_is_rejected_at_input_boundary() -> None:
    with pytest.raises(ValidationError):
        ProjectSpec(
            site=SiteInput(latlon=LatLon(lat=37.0, lon=-122.0)),
            building_use=BuildingUse.single_family,
            code_cycle="2022",
        )


def test_bare_energy_compliance_booleans_remain_unverified() -> None:
    model = _complete_model()
    condenser = next(element for element in model.mep_elements if element.id == "condenser")
    condenser.metadata = {"title24_compliant": True, "seer2": 16.0}
    model.design_brief = {"energy": {"envelope_compliant": True}}

    issues = ComplianceEngine().run(model)

    assert {"ENERGY-HVAC-DOCUMENTATION", "ENERGY-ENVELOPE-DOCUMENTATION"} <= _rule_ids(issues)
    assert model.compliance_summary["status"] == "unverified"
