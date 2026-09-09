from __future__ import annotations

from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import json

import pytest

from app.models.schemas import (
    BuildingModel,
    Level,
    MEPElement,
    ProjectSpec,
    Room,
    SiteInput,
    Wall,
)
from app.services.render_payload import build_render_payload, group_mep_runs


def _mesh(element_id: str, element_type: str, level: int = 0) -> dict:
    return {
        "vertices": [[0, 0, 0], [4, 0, 0], [4, 3, 0], [0, 3, 0]],
        "faces": [[0, 1, 2], [0, 2, 3]],
        "element_id": element_id,
        "element_type": element_type,
        "level": level,
        "color": "#b5651d",
    }


def _pipe_run(parent_id: str, n_segments: int, diameter_in: float = 1.0) -> list[MEPElement]:
    """Mirrors app/generators/mep.py:_contain_and_reroute's actual output shape:
    one MEPElement per segment, chained via route_parent_id/route_segment."""
    segs = []
    for i in range(n_segments):
        segs.append(MEPElement(
            id=f"{parent_id}_seg{i + 1}",
            system="plumbing", type="cold_supply",
            start=[float(i), 0.3, 0.0], end=[float(i + 1), 0.3, 0.0],
            level=0, diameter_in=diameter_in,
            metadata={"route_parent_id": parent_id, "route_segment": i + 1, "route_segment_count": n_segments},
        ))
    return segs


def _building_model() -> BuildingModel:
    spec = ProjectSpec(site=SiteInput(address="123 Test St"), bedrooms=3, bathrooms=2, stories=2)

    rooms = [
        Room(id="kitchen-1", type="kitchen", polygon=[[0, 0], [4, 0], [4, 4], [0, 4]], level=0, area_sqft=180),
        Room(id="bath-1", type="bathroom", polygon=[[4, 0], [6, 0], [6, 3], [4, 3]], level=0, area_sqft=95),
        Room(id="bed-1", type="bedroom", polygon=[[0, 0], [5, 0], [5, 5], [0, 5]], level=1, area_sqft=200),
    ]
    walls = [
        Wall(id="w1", start=[0, 0], end=[6, 0], height_ft=9.0, level=0, is_exterior=True),
        Wall(id="w2", start=[6, 0], end=[6, 4], height_ft=9.0, level=0, is_exterior=True),
        Wall(id="w3", start=[0, 0], end=[5, 0], height_ft=9.0, level=1, is_exterior=True),
        Wall(id="w4", start=[3, 0], end=[3, 4], height_ft=9.0, level=0, is_exterior=False),
    ]
    mep_elements = [
        *_pipe_run("hot_run_1", 3, diameter_in=0.75),
        MEPElement(
            id="duct_seg1", system="hvac", type="supply_branch",
            start=[1, 2.5, 1], end=[3, 2.5, 1], level=0,
            width_in=10.0, height_in=6.0,
            metadata={"route_parent_id": "duct_run_1", "route_segment": 1, "route_segment_count": 1},
        ),
        MEPElement(
            id="conduit1", system="electrical", type="feeder",
            start=[0.2, 0.2, 0.2], end=[0.2, 8.0, 0.2], level=0, diameter_in=1.25,
        ),
        MEPElement(id="spr1", system="fire", type="sprinkler", start=[2, 2.6, 2], end=None, level=0),
        MEPElement(id="outlet1", system="electrical", type="outlet", start=[0.1, 1.2, 3.5], end=None, level=0),
        MEPElement(id="sofa1", system="fixtures", type="sofa", start=[2, 0.4, 3], end=None, level=0),
    ]
    massing_meshes = [
        _mesh("shell1", "massing"),
        _mesh("roof1", "roof"),
        _mesh("fp1", "footprint_ok"),   # debug overlay — must be skipped
        _mesh("terrain1", "terrain"),   # debug overlay — must be skipped
    ]
    facade_meshes = [_mesh("door1", "door"), _mesh("win1", "window")]

    return BuildingModel(
        project_id="test-render-payload",
        spec=spec,
        levels=[
            Level(index=0, elevation_ft=0.0, height_ft=9.0, label="Ground"),
            Level(index=1, elevation_ft=9.0, height_ft=9.0, label="Second"),
        ],
        massing_options=[{"meshes": massing_meshes}],
        chosen_massing_index=0,
        rooms=rooms,
        walls=walls,
        mep_elements=mep_elements,
        meshes=facade_meshes,
    )


def test_group_mep_runs_reconstructs_ordered_polyline() -> None:
    elements = _pipe_run("hot_run_1", 3)
    runs, points = group_mep_runs(elements)
    assert len(runs) == 1
    assert points == []
    run = runs[0]
    assert run["parent_id"] == "hot_run_1"
    assert run["polyline"] == [[0.0, 0.3, 0.0], [1.0, 0.3, 0.0], [2.0, 0.3, 0.0], [3.0, 0.3, 0.0]]
    assert run["diameter_in"] == 1.0
    assert run["layer"] == "plumbing"


def test_group_mep_runs_separates_point_fixtures() -> None:
    elements = [
        MEPElement(id="spr1", system="fire", type="sprinkler", start=[1, 2, 3], end=None, level=0),
        MEPElement(id="p1", system="plumbing", type="cold_supply", start=[0, 0, 0], end=[1, 0, 0], level=0, diameter_in=0.5),
    ]
    runs, points = group_mep_runs(elements)
    assert len(runs) == 1
    assert len(points) == 1
    assert points[0]["id"] == "spr1"
    assert points[0]["position"] == [1, 2, 3]
    assert points[0]["layer"] == "fire"


def test_group_mep_runs_handles_unchained_single_segment() -> None:
    """A segment with no route_parent_id metadata still becomes a valid 2-point run."""
    elements = [MEPElement(id="lone", system="hvac", type="exhaust_duct",
                            start=[0, 0, 0], end=[2, 0, 0], level=0, width_in=8, height_in=8)]
    runs, points = group_mep_runs(elements)
    assert len(runs) == 1
    assert runs[0]["polyline"] == [[0, 0, 0], [2, 0, 0]]
    assert runs[0]["layer"] == "hvac"


def test_build_render_payload_shape_and_json_serializable() -> None:
    model = _building_model()
    payload = build_render_payload(model)

    assert json.dumps(payload)  # must round-trip through JSON cleanly

    assert len(payload["rooms"]) == 3
    # Interior walls only — the massing shell and the facade meshes already draw
    # every exterior surface, so exporting exterior walls too drew each one
    # three times over and z-fought.
    assert {w["id"] for w in payload["walls"]} == {"w4"}
    assert len(payload["levels"]) == 2
    # 4 massing meshes minus 2 skipped debug types, plus 2 facade meshes.
    assert len(payload["meshes"]) == 4
    mesh_ids = {m["element_id"] for m in payload["meshes"]}
    assert mesh_ids == {"shell1", "roof1", "door1", "win1"}


def test_build_render_payload_skips_debug_overlay_meshes() -> None:
    payload = build_render_payload(_building_model())
    element_types = {m["element_type"] for m in payload["meshes"]}
    assert "footprint_ok" not in element_types
    assert "terrain" not in element_types


def test_build_render_payload_mesh_layers() -> None:
    payload = build_render_payload(_building_model())
    by_id = {m["element_id"]: m["layer"] for m in payload["meshes"]}
    assert by_id["roof1"] == "roof"
    # The opaque outer shell gets its own layer so the viewer can fade it
    # without also fading the interior plan drawn under "architecture".
    assert by_id["shell1"] == "shell"
    assert by_id["door1"] == "architecture"


def test_build_render_payload_mep_runs_and_points() -> None:
    payload = build_render_payload(_building_model())
    run_parent_ids = {r["parent_id"] for r in payload["mep_runs"]}
    # hot_run_1/duct_run_1 are route_parent_id-chained; conduit1 has a real
    # start+end with no chaining metadata, so it becomes its own single-segment run.
    assert run_parent_ids == {"hot_run_1", "duct_run_1", "conduit1"}

    point_ids = {p["id"] for p in payload["mep_points"]}
    assert point_ids == {"spr1", "outlet1", "sofa1"}

    layers = {p["id"]: p["layer"] for p in payload["mep_points"]}
    assert layers["spr1"] == "fire"
    assert layers["outlet1"] == "electrical"
    assert layers["sofa1"] == "fixtures"


def test_build_render_payload_no_massing_options_is_safe() -> None:
    model = _building_model()
    model.massing_options = []
    payload = build_render_payload(model)
    # Only the 2 facade meshes remain — no crash on an empty massing_options list.
    assert len(payload["meshes"]) == 2
