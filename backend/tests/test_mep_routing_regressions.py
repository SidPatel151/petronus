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
    assert _metadata_room_ids(elements, system="hvac", element_type="return_grille") == all_room_ids
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
        and element.type not in {"utility_lateral", "sewer_lateral"}
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


def test_exterior_utility_and_adu_sewer_laterals_are_retained() -> None:
    rooms, walls, levels = _rectangular_home()
    footprint = Polygon([(0.0, 0.0), (12.0, 0.0), (12.0, 10.0), (0.0, 10.0)])

    elements = MEPRouter().route(
        rooms,
        walls,
        levels,
        _spec(BuildingUse.adu),
        power_connection={"dx_m": 0.0, "dz_m": -12.0},
    )

    laterals = {
        element.type: element
        for element in elements
        if element.type in {"utility_lateral", "sewer_lateral"}
    }
    assert set(laterals) == {"utility_lateral", "sewer_lateral"}
    for lateral in laterals.values():
        assert lateral.end is not None
        assert not footprint.covers(Point(lateral.end[0], lateral.end[2]))
        assert lateral.metadata and lateral.metadata.get("allow_outside_footprint") is True


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
