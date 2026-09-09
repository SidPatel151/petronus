from __future__ import annotations

import math
from pathlib import Path
import sys

from shapely.geometry import LineString, Point, Polygon


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.constants import BuildingUse, HVACPreference
from app.generators.clash_detector import detect_clashes
from app.generators.floorplan import FloorplanGenerator
from app.generators.mep import MEPRouter, SPRINKLER_COVERAGE_M2
from app.models.schemas import Level, MEPElement, ProjectSpec, Room, SiteInput, Wall


def _room(
    room_id: str,
    room_type: str,
    x0: float,
    z0: float,
    x1: float,
    z1: float,
) -> Room:
    return Room(
        id=room_id,
        type=room_type,
        polygon=[[x0, z0], [x1, z0], [x1, z1], [x0, z1]],
        level=0,
        area_sqft=(x1 - x0) * (z1 - z0) * 10.7639,
    )


def _exterior_walls(vertices: list[tuple[float, float]]) -> list[Wall]:
    return [
        Wall(
            id=f"exterior_{index}",
            start=list(start),
            end=list(end),
            height_ft=10.0,
            level=0,
            is_exterior=True,
        )
        for index, (start, end) in enumerate(zip(vertices, vertices[1:] + vertices[:1]))
    ]


def _rectangular_home() -> tuple[list[Room], list[Wall], list[Level]]:
    rooms = [
        _room("kitchen", "kitchen", 0.0, 0.0, 6.0, 5.0),
        _room("bathroom", "bathroom", 6.0, 0.0, 12.0, 5.0),
        _room("living", "living", 0.0, 5.0, 6.0, 10.0),
        _room("bedroom", "bedroom", 6.0, 5.0, 12.0, 10.0),
    ]
    walls = _exterior_walls([(0.0, 0.0), (12.0, 0.0), (12.0, 10.0), (0.0, 10.0)])
    levels = [Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")]
    return rooms, walls, levels


def _spec(building_use: BuildingUse = BuildingUse.single_family) -> ProjectSpec:
    return ProjectSpec(
        site=SiteInput(address="Regression test site"),
        building_use=building_use,
        bedrooms=1,
        bathrooms=1,
        stories=1,
        target_gross_area_sqft=1292.0,
        hvac_preference=HVACPreference.rooftop,
        fine_details={
            "outlets_per_room": 3,
            "fire_sprinklers": True,
            "exhaust_fans": True,
            "whole_building_ventilation": True,
        },
    )


def _metadata_room_ids(elements: list[MEPElement], *, system: str, element_type: str) -> set[str]:
    return {
        element.metadata["room_id"]
        for element in elements
        if element.system == system
        and element.type == element_type
        and element.metadata
        and element.metadata.get("room_id")
    }


def test_rectangular_home_has_complete_room_system_coverage_and_services() -> None:
    rooms, walls, levels = _rectangular_home()

    elements = MEPRouter().route(rooms, walls, levels, _spec())

    all_room_ids = {room.id for room in rooms}
    wet_room_ids = {"kitchen", "bathroom"}
    assert _metadata_room_ids(elements, system="electrical", element_type="outlet") == all_room_ids
    assert _metadata_room_ids(elements, system="electrical", element_type="lighting_point") == all_room_ids
    assert _metadata_room_ids(elements, system="hvac", element_type="supply_diffuser") == all_room_ids
    # Every room needs a return-air path, but wet rooms take a transfer grille
    # rather than a ducted return — pulling bathroom and kitchen air back into
    # the air handler spreads moisture and odour through the whole system.
    assert (
        _metadata_room_ids(elements, system="hvac", element_type="return_grille")
        | _metadata_room_ids(elements, system="hvac", element_type="transfer_grille")
    ) == all_room_ids
    assert _metadata_room_ids(elements, system="hvac", element_type="transfer_grille") == wet_room_ids
    assert _metadata_room_ids(elements, system="plumbing", element_type="cold_supply") == wet_room_ids
    assert _metadata_room_ids(elements, system="plumbing", element_type="hot_supply") == wet_room_ids
    assert _metadata_room_ids(elements, system="plumbing", element_type="waste_branch") == wet_room_ids

    exhaust_room_ids = {
        element.metadata["room_id"]
        for element in elements
        if element.system == "hvac"
        and element.type in {"range_hood", "exhaust_fan"}
        and element.metadata
    }
    assert exhaust_room_ids == wet_room_ids

    outlets = [element for element in elements if element.type == "outlet"]
    assert outlets
    for axis, boundary in ((0, 0.0), (0, 12.0), (2, 0.0), (2, 10.0)):
        assert any(abs(outlet.start[axis] - boundary) <= 0.10 for outlet in outlets)

    system_types = {(element.system, element.type) for element in elements}
    assert {("electrical", "main_panel"), ("electrical", "service_conduit")} <= system_types
    assert {("plumbing", "water_service"), ("plumbing", "water_meter")} <= system_types
    assert detect_clashes(elements) == []


def test_concave_horizontal_route_is_segmented_inside_footprint() -> None:
    footprint = Polygon(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (4.0, 4.0), (4.0, 10.0), (0.0, 10.0)]
    )
    rooms = [
        _room("living", "living", 0.0, 0.0, 6.0, 4.0),
        _room("kitchen", "kitchen", 6.0, 0.0, 10.0, 4.0),
        _room("bedroom", "bedroom", 0.0, 4.0, 4.0, 10.0),
    ]
    walls = _exterior_walls(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (4.0, 4.0), (4.0, 10.0), (0.0, 10.0)]
    )
    levels = [Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")]
    direct_line = LineString([(8.0, 2.0), (1.0, 7.0)])
    assert not footprint.buffer(0.02, join_style=2).covers(direct_line)

    routed = MEPRouter().route(rooms, walls, levels, _spec())

    rerouted = [
        element
        for element in routed
        if element.metadata and element.metadata.get("route_parent_id")
    ]
    assert rerouted
    allowed = footprint.buffer(0.03, join_style=2)
    horizontal_routes = [
        element
        for element in routed
        if element.end
        # Exempt anything explicitly marked as living outside the building —
        # service laterals, and the refrigerant line set / condensate drain
        # running out to the side-yard condenser.
        and not (element.metadata or {}).get("allow_outside_footprint")
        and (
            abs(element.start[0] - element.end[0]) >= 0.01
            or abs(element.start[2] - element.end[2]) >= 0.01
        )
    ]
    assert horizontal_routes
    assert all(
        allowed.covers(
            LineString(
                [(element.start[0], element.start[2]), (element.end[0], element.end[2])]
            )
        )
        for element in horizontal_routes
    )


def test_elements_marked_outside_footprint_are_retained_outside_it() -> None:
    """Anything flagged allow_outside_footprint survives the containment passes
    and genuinely lands outside the building — the service lateral, and the
    refrigerant line set / condensate drain running to the outdoor condenser."""
    rooms, walls, levels = _rectangular_home()
    footprint = Polygon([(0.0, 0.0), (12.0, 0.0), (12.0, 10.0), (0.0, 10.0)])

    elements = MEPRouter().route(
        rooms,
        walls,
        levels,
        _spec(BuildingUse.single_family),
        power_connection={"dx_m": 0.0, "dz_m": -12.0},
    )

    external = [
        element for element in elements
        if (element.metadata or {}).get("allow_outside_footprint")
    ]
    assert external, "no elements were allowed outside the footprint"
    assert "utility_lateral" in {element.type for element in external}
    # A service lateral legitimately terminates ON the footprint boundary, so
    # test "not strictly inside" rather than shapely's boundary-inclusive covers().
    interior = footprint.buffer(-0.01)
    for element in external:
        if element.end is None:
            continue
        assert not interior.contains(Point(element.end[0], element.end[2]))


def test_clash_detector_uses_true_3d_segments_not_overlapping_aabbs() -> None:
    aabb_only = [
        MEPElement(
            id="diagonal_pipe",
            system="plumbing",
            type="cold_supply",
            start=[0.0, 1.0, 0.0],
            end=[10.0, 1.0, 10.0],
            level=0,
            diameter_in=1.0,
        ),
        MEPElement(
            id="parallel_conduit",
            system="electrical",
            type="conduit_branch",
            start=[0.0, 1.0, 2.0],
            end=[8.0, 1.0, 10.0],
            level=0,
            diameter_in=1.0,
        ),
    ]
    assert detect_clashes(aabb_only) == []

    intersecting = [
        MEPElement(
            id="horizontal_pipe",
            system="plumbing",
            type="cold_supply",
            start=[0.0, 1.0, 0.0],
            end=[2.0, 1.0, 0.0],
            level=0,
            diameter_in=1.0,
        ),
        MEPElement(
            id="vertical_conduit",
            system="electrical",
            type="conduit_branch",
            start=[1.0, 0.0, 0.0],
            end=[1.0, 2.0, 0.0],
            level=0,
            diameter_in=1.0,
        ),
    ]
    issues = detect_clashes(intersecting)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert set(issues[0].elements_involved) == {"horizontal_pipe", "vertical_conduit"}


def test_clash_detector_uses_point_equipment_height_not_width_vertically() -> None:
    separated = [
        MEPElement(
            id="light", system="electrical", type="lighting_point",
            start=[1.0, 2.45, 1.0], level=0,
        ),
        MEPElement(
            id="mini-head", system="hvac", type="mini_split_head",
            start=[1.0, 2.82, 1.0], level=0, width_in=30, height_in=10,
        ),
    ]
    assert detect_clashes(separated) == []

    colliding = [
        separated[0],
        separated[1].model_copy(update={"start": [1.0, 2.55, 1.0]}),
    ]
    assert len(detect_clashes(colliding)) == 1


def test_large_room_sprinkler_layout_scales_past_two_heads() -> None:
    level = Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")
    small_room = _room("small_living", "living", 0.0, 0.0, 4.0, 4.0)
    large_room = _room("large_living", "living", 0.0, 0.0, 12.0, 12.0)
    router = MEPRouter()

    small_elements = router.route(
        [small_room],
        _exterior_walls([(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]),
        [level],
        _spec(),
    )
    large_elements = router.route(
        [large_room],
        _exterior_walls([(0.0, 0.0), (12.0, 0.0), (12.0, 12.0), (0.0, 12.0)]),
        [level],
        _spec(),
    )
    small_heads = [element for element in small_elements if element.type == "sprinkler"]
    large_heads = [element for element in large_elements if element.type == "sprinkler"]

    minimum_large_count = math.ceil(Polygon(large_room.polygon).area / SPRINKLER_COVERAGE_M2)
    assert len(large_heads) >= minimum_large_count
    assert len(large_heads) > 2
    assert len(large_heads) > len(small_heads)
    assert all(
        Polygon(large_room.polygon).covers(Point(head.start[0], head.start[2]))
        for head in large_heads
    )


def test_production_floorplan_routes_waste_to_every_wet_leaf_room() -> None:
    """The real 3BR/3BA floorplan must not strand later wet-room rows."""
    levels = [Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")]
    spec = _spec().model_copy(
        update={
            "bedrooms": 3,
            "bathrooms": 3,
            "target_gross_area_sqft": 1800.0,
        }
    )
    massing_option = {
        "footprint": [
            [-6.0, -7.0],
            [6.0, -7.0],
            [6.0, 7.0],
            [-6.0, 7.0],
            [-6.0, -7.0],
        ]
    }

    rooms, walls = FloorplanGenerator().generate(massing_option, spec, levels)
    wet_leaf_room_ids = {
        room.id
        for room in rooms
        if room.type in {"bathroom", "kitchen", "laundry"} and room.type != "unit"
    }
    wet_leaf_types = [room.type for room in rooms if room.id in wet_leaf_room_ids]
    assert wet_leaf_types.count("bathroom") == 3
    assert wet_leaf_types.count("kitchen") == 1
    assert wet_leaf_types.count("laundry") == 1

    elements = MEPRouter().route(rooms, walls, levels, spec)

    assert _metadata_room_ids(
        elements, system="plumbing", element_type="waste_branch"
    ) == wet_leaf_room_ids


def test_concave_full_bath_keeps_all_fixtures_inside_room_polygon() -> None:
    vertices = [
        (0.0, 0.0),
        (5.0, 0.0),
        (5.0, 2.0),
        (2.0, 2.0),
        (2.0, 5.0),
        (0.0, 5.0),
    ]
    bathroom_polygon = Polygon(vertices)
    bathroom = Room(
        id="concave_full_bath",
        type="bathroom",
        polygon=[list(vertex) for vertex in vertices],
        level=0,
        area_sqft=bathroom_polygon.area * 10.7639,
    )
    levels = [Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")]

    elements = MEPRouter().route(
        [bathroom],
        _exterior_walls(vertices),
        levels,
        _spec(),
    )

    fixtures = {
        element.type: element
        for element in elements
        if element.type in {"toilet", "sink", "shower"}
        and element.metadata
        and element.metadata.get("room_id") == bathroom.id
    }
    assert set(fixtures) == {"toilet", "sink", "shower"}
    assert all(
        bathroom_polygon.covers(Point(fixture.start[0], fixture.start[2]))
        for fixture in fixtures.values()
    )


def test_life_safety_devices_are_explicit_listed_alarms_per_sleeping_zone() -> None:
    rooms = [
        _room("bed_u1", "bedroom", 0.0, 0.0, 3.0, 4.0).model_copy(
            update={"unit_id": "unit_1"}
        ),
        _room("living_u1", "living", 0.0, 4.0, 3.0, 8.0).model_copy(
            update={"unit_id": "unit_1"}
        ),
        _room("bed_u2", "bedroom", 3.0, 0.0, 6.0, 4.0).model_copy(
            update={"unit_id": "unit_2"}
        ),
        _room("living_u2", "living", 3.0, 4.0, 6.0, 8.0).model_copy(
            update={"unit_id": "unit_2"}
        ),
        _room("shared_hall", "corridor", 0.0, 8.0, 6.0, 10.0),
    ]
    levels = [Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")]
    spec = _spec().model_copy(
        update={"fine_details": {**(_spec().fine_details or {}), "fuel_fired_equipment": True}}
    )

    elements = MEPRouter().route(
        rooms,
        _exterior_walls([(0.0, 0.0), (6.0, 0.0), (6.0, 10.0), (0.0, 10.0)]),
        levels,
        spec,
    )

    assert not [element for element in elements if element.type == "fire_alarm"]
    smoke_alarms = [element for element in elements if element.type == "smoke_alarm"]
    inside = [alarm for alarm in smoke_alarms if alarm.metadata.get("inside_sleeping_room")]
    outside = [alarm for alarm in smoke_alarms if alarm.metadata.get("outside_sleeping_area")]
    assert {alarm.metadata["room_id"] for alarm in inside} == {"bed_u1", "bed_u2"}
    assert {alarm.metadata["sleeping_zone_id"] for alarm in outside} == {"unit_1", "unit_2"}
    assert all(
        alarm.metadata.get("hardwired") is True
        and alarm.metadata.get("battery_backup") is True
        and alarm.metadata.get("interconnected") is True
        and alarm.metadata.get("listed") is True
        and alarm.metadata.get("listing_standard") == "UL 217"
        for alarm in smoke_alarms
    )

    co_alarms = [element for element in elements if element.type == "carbon_monoxide_alarm"]
    assert {alarm.metadata["sleeping_zone_id"] for alarm in co_alarms} == {"unit_1", "unit_2"}
    assert all(
        alarm.metadata.get("outside_sleeping_area") is True
        and alarm.metadata.get("hardwired") is True
        and alarm.metadata.get("battery_backup") is True
        and alarm.metadata.get("interconnected") is True
        and alarm.metadata.get("listing_standard") == "UL 2034"
        and "fuel_fired_equipment" in alarm.metadata.get("applicability_triggers", [])
        for alarm in co_alarms
    )


def test_co_alarm_requires_garage_or_explicit_fuel_fired_trigger() -> None:
    rooms, walls, levels = _rectangular_home()

    all_electric = MEPRouter().route(rooms, walls, levels, _spec())
    assert not [element for element in all_electric if element.type == "carbon_monoxide_alarm"]

    garage_rooms = rooms + [_room("garage", "garage", 12.0, 0.0, 18.0, 10.0)]
    garage_elements = MEPRouter().route(
        garage_rooms,
        _exterior_walls([(0.0, 0.0), (18.0, 0.0), (18.0, 10.0), (0.0, 10.0)]),
        levels,
        _spec(),
    )
    garage_alarms = [
        element for element in garage_elements if element.type == "carbon_monoxide_alarm"
    ]
    assert garage_alarms
    assert all("garage" in alarm.metadata["applicability_triggers"] for alarm in garage_alarms)

def test_generated_ventilation_and_outlets_carry_honest_geometry_evidence() -> None:
    rooms, walls, levels = _rectangular_home()
    elements = MEPRouter().route(rooms, walls, levels, _spec())

    ventilators = [
        element
        for element in elements
        if element.type in {"whole_house_ventilator", "erv"}
    ]
    assert ventilators
    assert all(
        element.metadata.get("actual_outdoor_air_cfm", 0) > 0
        and element.metadata.get("required_outdoor_air_cfm", 0) > 0
        and element.metadata.get("ventilation_calculation_reference")
        and element.metadata.get("calculation_verified") is False
        and element.metadata.get("evidence_status") == "conceptual_unverified"
        for element in ventilators
    )

    outlets = [element for element in elements if element.type == "outlet"]
    assert outlets
    assert all(
        element.metadata.get("geometry_derived") is True
        and element.metadata.get("design_spacing_ft", 0) >= 0
        and element.metadata.get("max_spacing_ft") in {4, 12}
        and element.metadata.get("spacing_basis")
        for element in outlets
    )
    assert all(
        outlet.metadata["design_spacing_ft"] <= outlet.metadata["max_spacing_ft"]
        for outlet in outlets
        if outlet.metadata.get("room_id") in {"living", "bedroom"}
    )


def test_every_wet_room_has_linked_hot_cold_waste_and_vent_evidence() -> None:
    rooms = [
        _room("kitchen", "kitchen", 0.0, 0.0, 4.0, 6.0),
        _room("bathroom", "bathroom", 4.0, 0.0, 8.0, 6.0),
        _room("laundry", "laundry", 8.0, 0.0, 12.0, 6.0),
    ]
    walls = _exterior_walls([(0.0, 0.0), (12.0, 0.0), (12.0, 6.0), (0.0, 6.0)])
    levels = [Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")]

    elements = MEPRouter().route(rooms, walls, levels, _spec())
    wet_room_ids = {room.id for room in rooms}
    for element_type in ("cold_supply", "hot_supply", "waste_branch", "vent_branch"):
        assert _metadata_room_ids(
            elements, system="plumbing", element_type=element_type
        ) == wet_room_ids

    element_ids = {element.id for element in elements}
    fixtures = [
        element
        for element in elements
        if element.type in {"toilet", "sink", "shower", "kitchen_sink", "washer_connection"}
    ]
    assert fixtures
    assert all(
        fixture.metadata.get("served_room_id") == fixture.metadata.get("room_id")
        and fixture.metadata.get("served_fixture_types")
        and fixture.metadata.get("cold_supply_branch_id") in element_ids
        and fixture.metadata.get("hot_supply_branch_id") in element_ids
        and fixture.metadata.get("waste_branch_id") in element_ids
        and fixture.metadata.get("vent_branch_id") in element_ids
        for fixture in fixtures
        if fixture.type != "toilet"
    )
    assert all(
        element.metadata.get("connected_stack_id") in element_ids
        and element.metadata.get("served_fixture_types")
        and element.metadata.get("vent_through_roof") is True
        for element in elements
        if element.type == "vent_branch"
    )


def test_library_and_gym_receive_receptacles_and_mini_split_terminals() -> None:
    rooms = [
        _room("library", "library", 0.0, 0.0, 6.0, 8.0),
        _room("gym", "gym", 6.0, 0.0, 12.0, 8.0),
    ]
    walls = _exterior_walls(
        [(0.0, 0.0), (12.0, 0.0), (12.0, 8.0), (0.0, 8.0)]
    )
    levels = [Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")]
    spec = _spec().model_copy(update={"hvac_preference": HVACPreference.mini_split})

    elements = MEPRouter().route(rooms, walls, levels, spec)

    expected_room_ids = {"library", "gym"}
    assert _metadata_room_ids(
        elements, system="electrical", element_type="outlet"
    ) == expected_room_ids
    assert _metadata_room_ids(
        elements, system="electrical", element_type="lighting_point"
    ) == expected_room_ids
    assert _metadata_room_ids(
        elements, system="hvac", element_type="mini_split_head"
    ) == expected_room_ids


def test_sfr_foyer_conduit_clears_large_supply_riser() -> None:
    footprint = [
        [-6.213820282241835, -7.1015088942235],
        [-6.213820282241835, 7.1015088937578374],
        [6.213820282241835, 7.1015088937578374],
        [6.213820282241835, -7.1015088942235],
        [-6.213820282241835, -7.1015088942235],
    ]
    levels = [Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")]
    spec = _spec().model_copy(update={
        "bedrooms": 3,
        "bathrooms": 2.0,
        "target_gross_area_sqft": 1900.0,
        "hvac_preference": HVACPreference.rooftop,
        "fine_details": {
            "outlets_per_room": 4,
            "fire_sprinklers": True,
            "fire_alarms": True,
            "exhaust_fans": True,
            "whole_building_ventilation": True,
            "fuel_fired_equipment": True,
        },
    })
    rooms, walls = FloorplanGenerator().generate(
        {"footprint": footprint}, spec, levels, None
    )
    elements = MEPRouter().route(
        rooms,
        walls,
        levels,
        spec,
        power_connection={"dx_m": 0.0, "dz_m": -45.0},
        archetype=None,
    )
    by_id = {element.id: element for element in elements}
    riser_conduit_issues = [
        issue
        for issue in detect_clashes(elements)
        if {
            by_id[element_id].type for element_id in issue.elements_involved
        } == {"conduit_branch", "supply_riser"}
    ]
    assert riser_conduit_issues == []
    assert not [
        element
        for element in elements
        if (element.metadata or {}).get("coordination_routing_fallback")
    ]

    shell = Polygon(footprint).buffer(0.03, join_style=2)
    assert all(
        (element.metadata or {}).get("allow_outside_footprint")
        or (
            shell.covers(Point(element.start[0], element.start[2]))
            and (
                element.end is None
                or shell.covers(Point(element.end[0], element.end[2]))
            )
        )
        for element in elements
    )


def test_multifamily_vent_drops_and_alarms_avoid_vertical_trade_clashes() -> None:
    """Exact rectangle/U stress footprints retain complete, clash-free MEP."""
    cases = {
        "rectangle": (
            [
                [-11.042248412347911, -12.619712471487587],
                [-11.042248412347911, 12.619712471021925],
                [11.042248412347911, 12.619712471021925],
                [11.042248412347911, -12.619712471487587],
                [-11.042248412347911, -12.619712471487587],
            ],
            12,
            18000.0,
        ),
        "u_shape": (
            [
                [-14.247085373798653, 15.773686873906053],
                [14.247085373798653, 15.773686873906053],
                [14.247085373798653, -15.51533397153756],
                [7.4084843943753, -15.51533397153756],
                [7.4084843943753, -5.502847300995603],
                [-7.4084843943753, -5.502847300995603],
                [-7.4084843943753, -15.51533397153756],
                [-14.247085373798653, -15.51533397153756],
                [-14.247085373798653, 15.773686873906053],
            ],
            18,
            24000.0,
        ),
    }
    levels = [
        Level(index=index, elevation_ft=index * 10.0, height_ft=10.0, label=f"L{index}")
        for index in range(3)
    ]

    for case_name, (footprint, unit_count, target_area) in cases.items():
        spec = _spec(BuildingUse.multi_family).model_copy(update={
            "bedrooms": 2,
            "bathrooms": 1.0,
            "stories": 3,
            "target_gross_area_sqft": target_area,
            "unit_count": unit_count,
            "fine_details": {
                "outlets_per_room": 4,
                "fire_sprinklers": True,
                "fire_alarms": True,
                "exhaust_fans": True,
                "whole_building_ventilation": True,
                "fuel_fired_equipment": True,
            },
        })
        rooms, walls = FloorplanGenerator().generate(
            {"footprint": footprint}, spec, levels, None
        )
        elements = MEPRouter().route(
            rooms,
            walls,
            levels,
            spec,
            power_connection={"dx_m": 0.0, "dz_m": -45.0},
            archetype=None,
        )
        by_id = {element.id: element for element in elements}
        prohibited_pairs = {
            frozenset(("conduit_branch", "vent_branch")),
            frozenset(("smoke_alarm", "supply_riser")),
        }
        targeted_issues = [
            issue
            for issue in detect_clashes(elements)
            if frozenset(by_id[element_id].type for element_id in issue.elements_involved)
            in prohibited_pairs
        ]
        assert targeted_issues == [], case_name

        shell = Polygon(footprint).buffer(0.03, join_style=2)
        assert all(
            (element.metadata or {}).get("allow_outside_footprint")
            or (
                shell.covers(Point(element.start[0], element.start[2]))
                and (
                    element.end is None
                    or shell.covers(Point(element.end[0], element.end[2]))
                )
            )
            for element in elements
        ), case_name
        assert not [
            element
            for element in elements
            if (element.metadata or {}).get("coordination_routing_fallback")
        ], case_name

        wet_room_ids = {
            room.id
            for room in rooms
            if room.type in {"bathroom", "kitchen", "laundry"}
        }
        for element_type in ("cold_supply", "hot_supply", "waste_branch", "vent_branch"):
            assert _metadata_room_ids(
                elements, system="plumbing", element_type=element_type
            ) == wet_room_ids, (case_name, element_type)

        bedroom_room_ids = {room.id for room in rooms if room.type == "bedroom"}
        sleeping_zone_ids = {
            room.unit_id for room in rooms if room.type == "bedroom" and room.unit_id
        }
        inside_alarms = {
            element.metadata.get("room_id")
            for element in elements
            if element.type == "smoke_alarm"
            and element.metadata
            and element.metadata.get("inside_sleeping_room")
        }
        outside_alarm_zones = {
            element.metadata.get("sleeping_zone_id")
            for element in elements
            if element.type == "smoke_alarm"
            and element.metadata
            and element.metadata.get("outside_sleeping_area")
        }
        assert inside_alarms == bedroom_room_ids, case_name
        assert outside_alarm_zones == sleeping_zone_ids, case_name
