from __future__ import annotations

from pathlib import Path
import sys

from shapely.geometry import box

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.constants import BuildingUse
from app.generators.floorplan import FloorplanGenerator
from app.models.schemas import Level, ProjectSpec, SiteInput


def _spec() -> ProjectSpec:
    return ProjectSpec(
        site=SiteInput(address="test"),
        building_use=BuildingUse.multi_family,
        bedrooms=3, bathrooms=2, stories=2,
    )


def _level() -> Level:
    return Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")


def test_narrow_shallow_footprint_still_produces_a_unit() -> None:
    """A narrow-lot multi-family floor (double-loaded corridor + a 3x5m stair core)
    used to collapse to zero units whenever the footprint was too shallow for both
    front and back bands to clear their minimum depth — the corridor and stair
    survived, every actual room got filtered out, and floorplan generation silently
    produced a near-empty building. Every one of these footprints reproduced that
    collapse before the single-loaded fallback was added."""
    fg = FloorplanGenerator()
    spec = _spec()
    level = _level()

    for w, d in [(7, 6.5), (7, 6.0), (6, 6.0), (7, 7.0), (7, 5.5)]:
        footprint = box(0, 0, w, d)
        rooms, walls = fg._layout_multifamily_floor(footprint, footprint.bounds, w, d, level, spec)
        unit_rooms = [r for r in rooms if r.unit_id]
        assert unit_rooms, f"{w}x{d} footprint produced zero unit rooms — corridor collapse regression"
        assert any(r.type == "unit" for r in rooms), f"{w}x{d} footprint has no 'unit' bounding room"


def test_wider_footprint_still_uses_double_loaded_corridor() -> None:
    """Once there's genuinely enough depth for two bands, the normal
    apartment-style double-loaded corridor plan should still be used —
    the single-loaded fallback must not fire when it isn't needed."""
    fg = FloorplanGenerator()
    spec = _spec()
    level = _level()

    footprint = box(0, 0, 7, 8)
    rooms, walls = fg._layout_multifamily_floor(footprint, footprint.bounds, 7.0, 8.0, level, spec)
    assert any(r.type == "corridor" for r in rooms)
    assert any(r.unit_id for r in rooms)


def test_tiny_footprint_degrades_without_crashing() -> None:
    """Below any usable size (can't even fit the stair core), the function should
    return whatever partial rooms it can rather than raising."""
    fg = FloorplanGenerator()
    spec = _spec()
    level = _level()

    footprint = box(0, 0, 3, 3)
    rooms, walls = fg._layout_multifamily_floor(footprint, footprint.bounds, 3.0, 3.0, level, spec)
    assert isinstance(rooms, list)
    assert isinstance(walls, list)
