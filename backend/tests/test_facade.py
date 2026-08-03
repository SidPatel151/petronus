from __future__ import annotations

from pathlib import Path
import sys

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.generators.facade import FacadeGenerator
from app.models.schemas import Level


@pytest.mark.parametrize(
    "arch_style",
    ["modern_linear", "contemporary_box", "minimalist"],
)
def test_modern_strip_window_facade_always_keeps_one_front_entry_door(
    arch_style: str,
) -> None:
    footprint = [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]]
    meshes = FacadeGenerator().generate(
        {"footprint": footprint},
        walls=[],
        levels=[
            Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground"),
            Level(index=1, elevation_ft=10.0, height_ft=10.0, label="Level 2"),
        ],
        neighbor_style={
            "dominant_arch_style": arch_style,
            "window_style": "wide",
            "facade_color": "#d6cbb8",
        },
    )

    doors = [mesh for mesh in meshes if mesh.get("element_type") == "door"]
    strip_windows = [
        mesh for mesh in meshes
        if str(mesh.get("element_id", "")).startswith("strip_win_")
    ]

    assert len(doors) == 1
    assert strip_windows, "The modern horizontal strip window must be preserved."
    assert doors[0]["level"] == 0
    average_door_z = sum(vertex[2] for vertex in doors[0]["vertices"]) / 4
    assert average_door_z < 0.25, "The entry door must stay on the minimum-Z front wall."

    door_min_x = min(vertex[0] for vertex in doors[0]["vertices"])
    door_max_x = max(vertex[0] for vertex in doors[0]["vertices"])
    ground_strips = [mesh for mesh in strip_windows if mesh["level"] == 0]
    upper_strips = [mesh for mesh in strip_windows if mesh["level"] == 1]
    assert ground_strips
    assert upper_strips
    for strip in ground_strips:
        strip_min_x = min(vertex[0] for vertex in strip["vertices"])
        strip_max_x = max(vertex[0] for vertex in strip["vertices"])
        overlap = min(strip_max_x, door_max_x) - max(strip_min_x, door_min_x)
        assert overlap <= 0.0, "Ground-floor strip glazing must clear the entry opening."
    assert any(
        min(vertex[0] for vertex in strip["vertices"]) < door_min_x
        and max(vertex[0] for vertex in strip["vertices"]) > door_max_x
        for strip in upper_strips
    ), "Upper-floor strip glazing should remain continuous."


@pytest.mark.parametrize("arch_style", ["classic_gabled", "victorian"])
def test_victorian_ground_floor_bay_does_not_conflict_with_entry(
    arch_style: str,
) -> None:
    meshes = FacadeGenerator().generate(
        {"footprint": [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]]},
        walls=[],
        levels=[
            Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground"),
            Level(index=1, elevation_ft=10.0, height_ft=10.0, label="Level 2"),
        ],
        neighbor_style={
            "dominant_arch_style": arch_style,
            "window_style": "tall_narrow",
            "facade_color": "#d6cbb8",
        },
    )

    doors = [mesh for mesh in meshes if mesh.get("element_type") == "door"]
    bay_meshes = [
        mesh for mesh in meshes
        if str(mesh.get("element_id", "")).startswith("bay_")
    ]

    assert len(doors) == 1
    assert bay_meshes, "The upper-floor Victorian bay should be preserved."
    assert not [
        mesh for mesh in bay_meshes
        if min(vertex[1] for vertex in mesh["vertices"]) < 3.0
    ], "No bay projection may occupy the ground-floor entry wall."
    assert any(
        min(vertex[1] for vertex in mesh["vertices"]) >= 3.0
        for mesh in bay_meshes
    )
