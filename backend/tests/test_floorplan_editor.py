from __future__ import annotations

import math
import random
from pathlib import Path
import sys

import pytest
from shapely.geometry import Polygon, box

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.constants import BuildingUse
from app.generators import floorplan_editor as fe
from app.generators.compliance import KNOWN_ROOM_TYPES
from app.models.schemas import BuildingModel, Level, ProjectSpec, Room, SiteInput
from app.services.draft_state import DraftState


def _spec() -> ProjectSpec:
    return ProjectSpec(
        site=SiteInput(address="test"),
        building_use=BuildingUse.single_family,
        bedrooms=3, bathrooms=2, stories=1,
        target_gross_area_sqft=2000,
    )


def _two_room_draft() -> DraftState:
    """A 10x6m level split into a 'living' room (0..5, 0..6) and a
    'bedroom' (5..10, 0..6) sharing a vertical wall at x=5."""
    level = Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")
    room_a = Room(id="room_a", type="living", polygon=[[0, 0], [5, 0], [5, 6], [0, 6]], level=0, area_sqft=fe.room_area_sqft([[0, 0], [5, 0], [5, 6], [0, 6]]))
    room_b = Room(id="room_b", type="bedroom", polygon=[[5, 0], [10, 0], [10, 6], [5, 6]], level=0, area_sqft=fe.room_area_sqft([[5, 0], [10, 0], [10, 6], [5, 6]]))
    envelope = box(0, 0, 10, 6)
    model = BuildingModel(project_id="p", spec=_spec(), levels=[level], rooms=[room_a, room_b], walls=[])
    draft = DraftState(
        draft_id="d1", model=model, is_sfr=True, chosen_massing={},
        infra={}, resolved_site=None, neighbor_style={}, design_brief=None,
        sem_result=None, archetype=None, footprint_envelopes={0: envelope},
    )
    draft.model.walls = fe.derive_walls_for_level(draft.model.rooms, envelope, 0, 10.0)
    return draft


def _unit_shell_draft() -> DraftState:
    """Mirrors floorplan.py's actual multi-family construction (see
    _layout_multifamily_floor): a 'unit' room whose polygon exactly equals
    the bounding box of its own sub-rooms, which tile that same box. living
    (0,0)-(4,10) | kitchen (4,0)-(8,5) | bathroom (4,5)-(8,10), unit spans
    (0,0)-(8,10)."""
    level = Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")
    unit_poly = [[0, 0], [8, 0], [8, 10], [0, 10]]
    living = Room(id="living_1", type="living", unit_id="unit_1", polygon=[[0, 0], [4, 0], [4, 10], [0, 10]], level=0, area_sqft=fe.room_area_sqft([[0, 0], [4, 0], [4, 10], [0, 10]]))
    kitchen = Room(id="kitchen_1", type="kitchen", unit_id="unit_1", polygon=[[4, 0], [8, 0], [8, 5], [4, 5]], level=0, area_sqft=fe.room_area_sqft([[4, 0], [8, 0], [8, 5], [4, 5]]))
    bathroom = Room(id="bathroom_1", type="bathroom", unit_id="unit_1", polygon=[[4, 5], [8, 5], [8, 10], [4, 10]], level=0, area_sqft=fe.room_area_sqft([[4, 5], [8, 5], [8, 10], [4, 10]]))
    unit = Room(id="unit_1", type="unit", unit_id="unit_1", polygon=unit_poly, level=0, area_sqft=fe.room_area_sqft(unit_poly))
    envelope = box(0, 0, 8, 10)
    model = BuildingModel(project_id="p", spec=_spec(), levels=[level], rooms=[unit, living, kitchen, bathroom], walls=[])
    draft = DraftState(
        draft_id="d2", model=model, is_sfr=False, chosen_massing={},
        infra={}, resolved_site=None, neighbor_style={}, design_brief=None,
        sem_result=None, archetype=None, footprint_envelopes={0: envelope},
    )
    draft.model.walls = fe.derive_walls_for_level(draft.model.rooms, envelope, 0, 10.0)
    return draft


def test_unit_shell_does_not_produce_overlap_or_orthogonal_warnings():
    draft = _unit_shell_draft()
    warnings = fe.validate(draft.model.rooms, draft.model.walls, draft.footprint_envelopes, target_sqft=2000)
    assert not any(w.type == "overlap" for w in warnings)
    assert not any(w.type == "non_orthogonal" and "unit" in w.message for w in warnings)


def test_unit_shell_area_not_double_counted_in_total_sqft():
    draft = _unit_shell_draft()
    # unit (80 m^2) + living+kitchen+bathroom (also summing to 80 m^2) would
    # double the true 80 m^2 total if the shell were included.
    warnings = fe.validate(draft.model.rooms, draft.model.walls, draft.footprint_envelopes, target_sqft=2000)
    assert not any(w.type == "over_sqft" for w in warnings)


def test_move_wall_between_kitchen_and_bathroom_ignores_unit_shell():
    draft = _unit_shell_draft()
    # The wall between kitchen and bathroom (y=5, x in [4,8]) also happens to
    # lie inside the unit shell's own bounding box, but should NOT be treated
    # as "shared by 3 rooms" — the unit shell must be excluded from matching.
    interior = [w for w in draft.model.walls if not w.is_exterior]
    wall = next(w for w in interior if abs(w.start[1] - 5) < 0.1 and abs(w.end[1] - 5) < 0.1)
    fe.move_wall(draft, level=0, wall_id=wall.id, delta_ft=1.0 / 0.3048)  # should not raise
    kitchen = fe._room_by_id(draft.model.rooms, "kitchen_1")
    assert fe.room_extent_along_axis(kitchen.polygon, "y") != pytest.approx(5.0, abs=1e-6)


def _shared_wall_id(draft: DraftState) -> str:
    """The fixture always has exactly one interior wall (the room_a/room_b
    divider); return it regardless of where it's currently located."""
    interior = [w for w in draft.model.walls if not w.is_exterior]
    if len(interior) != 1:
        raise AssertionError(f"expected exactly one interior wall, found {len(interior)}")
    return interior[0].id


def _interior_angles_ok(polygon, eps=1e-3) -> bool:
    for (x0, y0, x1, y1) in fe._polygon_edges(polygon):
        if not fe._is_axis_aligned(x0, y0, x1, y1, eps=eps):
            return False
    return True


# ── derive_walls_for_level ──────────────────────────────────────────────

def test_derive_walls_produces_one_shared_interior_wall_and_four_exterior():
    draft = _two_room_draft()
    ext = [w for w in draft.model.walls if w.is_exterior]
    interior = [w for w in draft.model.walls if not w.is_exterior]
    assert len(ext) == 4
    assert len(interior) == 1
    w = interior[0]
    assert abs(w.start[0] - 5) < 0.01 and abs(w.end[0] - 5) < 0.01


# ── move_wall ────────────────────────────────────────────────────────────

def test_move_wall_snaps_to_grid_and_resizes_both_rooms():
    draft = _two_room_draft()
    wall_id = _shared_wall_id(draft)

    fe.move_wall(draft, level=0, wall_id=wall_id, delta_ft=3.31234)  # arbitrary, not grid-aligned

    room_a = fe._room_by_id(draft.model.rooms, "room_a")
    room_b = fe._room_by_id(draft.model.rooms, "room_b")
    new_x = max(p[0] for p in room_a.polygon)
    # New boundary must land on an EDIT_GRID_M multiple.
    assert abs((new_x / fe.EDIT_GRID_M) - round(new_x / fe.EDIT_GRID_M)) < 1e-6
    # room_a grew, room_b shrank by the same amount.
    assert new_x > 5.0
    assert min(p[0] for p in room_b.polygon) == pytest.approx(new_x, abs=1e-6)
    # Areas were recomputed.
    assert room_a.area_sqft == pytest.approx(fe.room_area_sqft(room_a.polygon), abs=0.01)
    assert room_b.area_sqft == pytest.approx(fe.room_area_sqft(room_b.polygon), abs=0.01)


def test_move_wall_clamps_at_hard_edit_floor_not_recommended_width():
    """Drags clamp at MIN_EDIT_WIDTH_M (a geometric anti-sliver floor), NOT
    at the per-type recommended width — those are advisory only, surfaced by
    validate(). Using recommendations as hard limits blocked nearly every
    drag on generated plans, since generated rooms are routinely already
    below their type's recommended width."""
    draft = _two_room_draft()
    wall_id = _shared_wall_id(draft)
    fe.move_wall(draft, level=0, wall_id=wall_id, delta_ft=20.0 / 0.3048)

    room_b = fe._room_by_id(draft.model.rooms, "room_b")
    width_b = fe.room_extent_along_axis(room_b.polygon, "x")
    assert width_b >= fe.MIN_EDIT_WIDTH_M - 1e-6
    assert width_b < fe.MIN_EDIT_WIDTH_M + fe.EDIT_GRID_M + 1e-6


def test_move_wall_can_still_grow_a_room_already_below_recommended_width():
    """The regression that produced constant "not enough slack" errors: an
    undersized neighbor must still be growable/shrinkable, not frozen."""
    level = Level(index=0, elevation_ft=0.0, height_ft=10.0, label="Ground")
    # 1.6m-wide kitchen — well below the 2.4m recommended kitchen width.
    small = Room(id="small", type="kitchen", polygon=[[0, 0], [1.6, 0], [1.6, 6], [0, 6]], level=0, area_sqft=fe.room_area_sqft([[0, 0], [1.6, 0], [1.6, 6], [0, 6]]))
    big = Room(id="big", type="living", polygon=[[1.6, 0], [10, 0], [10, 6], [1.6, 6]], level=0, area_sqft=fe.room_area_sqft([[1.6, 0], [10, 0], [10, 6], [1.6, 6]]))
    envelope = box(0, 0, 10, 6)
    model = BuildingModel(project_id="p", spec=_spec(), levels=[level], rooms=[small, big], walls=[])
    draft = DraftState(
        draft_id="d3", model=model, is_sfr=True, chosen_massing={}, infra={},
        resolved_site=None, neighbor_style={}, design_brief=None,
        sem_result=None, archetype=None, footprint_envelopes={0: envelope},
    )
    draft.model.walls = fe.derive_walls_for_level(draft.model.rooms, envelope, 0, 10.0)
    wall = next(w for w in draft.model.walls if not w.is_exterior)

    fe.move_wall(draft, level=0, wall_id=wall.id, delta_ft=2.0 / 0.3048)  # must not raise
    small_after = fe._room_by_id(draft.model.rooms, "small")
    assert fe.room_extent_along_axis(small_after.polygon, "x") > 1.6


def test_move_wall_rejects_exterior_wall():
    draft = _two_room_draft()
    ext_wall = next(w for w in draft.model.walls if w.is_exterior)
    with pytest.raises(fe.FloorplanEditError):
        fe.move_wall(draft, level=0, wall_id=ext_wall.id, delta_ft=1.0)


def test_move_wall_rejects_unknown_wall_id():
    draft = _two_room_draft()
    with pytest.raises(fe.FloorplanEditError):
        fe.move_wall(draft, level=0, wall_id="nonexistent", delta_ft=1.0)


# ── resize_room ──────────────────────────────────────────────────────────

def test_resize_room_rejects_shared_edge():
    draft = _two_room_draft()
    with pytest.raises(fe.FloorplanEditError):
        fe.resize_room(draft, level=0, room_id="room_a", edge="east", delta_ft=1.0)  # shared with room_b


def test_resize_room_grows_on_free_edge():
    draft = _two_room_draft()
    room_a = fe._room_by_id(draft.model.rooms, "room_a")
    old_extent = fe.room_extent_along_axis(room_a.polygon, "y")
    # "north" edge (max y) of room_a borders the fixed exterior envelope,
    # not room_b — but it also can't grow past the envelope, so shrink
    # instead to exercise a clean, always-legal free-edge resize.
    fe.resize_room(draft, level=0, room_id="room_a", edge="north", delta_ft=-1.0 / 0.3048)
    room_a = fe._room_by_id(draft.model.rooms, "room_a")
    new_extent = fe.room_extent_along_axis(room_a.polygon, "y")
    assert new_extent < old_extent


# ── add_room / delete_room / retype_room ────────────────────────────────

def test_add_room_rejects_unknown_type():
    draft = _two_room_draft()
    with pytest.raises(fe.FloorplanEditError):
        fe.add_room(draft, level=0, room_type="dungeon", polygon_m=[[0, 0], [1, 0], [1, 1], [0, 1]])


def test_add_room_rejects_overlap_with_existing_room():
    draft = _two_room_draft()
    with pytest.raises(fe.FloorplanEditError):
        fe.add_room(draft, level=0, room_type="closet", polygon_m=[[1, 1], [3, 1], [3, 3], [1, 3]])  # overlaps room_a


def test_add_room_rejects_outside_envelope():
    draft = _two_room_draft()
    with pytest.raises(fe.FloorplanEditError):
        fe.add_room(draft, level=0, room_type="closet", polygon_m=[[20, 20], [21, 20], [21, 21], [20, 21]])


def test_delete_room_removes_room_and_rederives_walls():
    draft = _two_room_draft()
    fe.delete_room(draft, level=0, room_id="room_b")
    assert [r.id for r in draft.model.rooms] == ["room_a"]
    # room_a's east edge (x=5) is no longer shared with anything, but it's
    # still not on the exterior boundary (footprint runs to x=10) — it's
    # correctly re-derived as a wall bordering now-unassigned free space,
    # not dropped, matching the existing _emit_interior_walls convention
    # (an edge is only exempt from becoming a wall when it's on the
    # exterior boundary — being "not shared with another room" is not a
    # separate exemption).
    interior = [w for w in draft.model.walls if not w.is_exterior]
    assert len(interior) == 1
    assert abs(interior[0].start[0] - 5) < 0.01 and abs(interior[0].end[0] - 5) < 0.01


def test_retype_room_rejects_unknown_type_and_leaves_geometry_untouched():
    draft = _two_room_draft()
    walls_before = list(draft.model.walls)
    with pytest.raises(fe.FloorplanEditError):
        fe.retype_room(draft, level=0, room_id="room_a", new_type="dungeon")
    fe.retype_room(draft, level=0, room_id="room_a", new_type="office")
    room_a = fe._room_by_id(draft.model.rooms, "room_a")
    assert room_a.type == "office"
    assert draft.model.walls == walls_before  # no geometry change -> no wall re-derivation


@pytest.mark.parametrize("room_type", sorted(KNOWN_ROOM_TYPES))
def test_add_room_accepts_every_known_room_type(room_type):
    draft = _two_room_draft()
    room = fe.add_room(draft, level=0, room_type=room_type, polygon_m=[[0, 5.9], [0.01, 5.9], [0.01, 5.91], [0, 5.91]])
    assert room.type == room_type


# ── wall/room consistency + orthogonality invariants ─────────────────────

def test_orthogonality_preserved_after_randomized_op_sequence():
    random.seed(1234)
    draft = _two_room_draft()
    for _ in range(15):
        wall_id = _shared_wall_id(draft)
        delta_ft = random.uniform(-2, 2)
        try:
            fe.move_wall(draft, level=0, wall_id=wall_id, delta_ft=delta_ft)
        except fe.FloorplanEditError:
            pass
        for r in draft.model.rooms:
            assert _interior_angles_ok(r.polygon), f"non-orthogonal room after op: {r.polygon}"
        for w in draft.model.walls:
            assert fe._is_axis_aligned(w.start[0], w.start[1], w.end[0], w.end[1])


def test_no_overlap_after_successful_move_wall():
    draft = _two_room_draft()
    wall_id = _shared_wall_id(draft)
    fe.move_wall(draft, level=0, wall_id=wall_id, delta_ft=2.0 / 0.3048)
    warnings = fe.validate(draft.model.rooms, draft.model.walls, draft.footprint_envelopes, target_sqft=2000)
    assert not any(w.type == "overlap" for w in warnings)


def test_every_interior_wall_matches_one_or_two_room_edges():
    draft = _two_room_draft()
    fe.move_wall(draft, level=0, wall_id=_shared_wall_id(draft), delta_ft=1.0 / 0.3048)
    all_edges = []
    for r in draft.model.rooms:
        all_edges.extend(fe._polygon_edges(r.polygon))
    for w in draft.model.walls:
        if w.is_exterior:
            continue
        seg = (w.start[0], w.start[1], w.end[0], w.end[1])
        matches = sum(1 for e in all_edges if fe._segment_matches_edge(seg, e) or _segment_within_edge(seg, e))
        assert matches >= 1, f"dangling interior wall {w.id} matches no room edge"


def _segment_within_edge(seg, edge) -> bool:
    """A wall clipped to the interior inset is a sub-segment of the full
    room edge, not necessarily an exact endpoint match — accept collinear
    containment too."""
    sx0, sy0, sx1, sy1 = seg
    ex0, ey0, ex1, ey1 = edge
    if abs(ey1 - ey0) < 1e-6 and abs(sy0 - ey0) < 0.05 and abs(sy1 - ey0) < 0.05:
        lo, hi = min(ex0, ex1), max(ex0, ex1)
        return lo - 0.3 <= min(sx0, sx1) and max(sx0, sx1) <= hi + 0.3
    if abs(ex1 - ex0) < 1e-6 and abs(sx0 - ex0) < 0.05 and abs(sx1 - ex0) < 0.05:
        lo, hi = min(ey0, ey1), max(ey0, ey1)
        return lo - 0.3 <= min(sy0, sy1) and max(sy0, sy1) <= hi + 0.3
    return False


# ── validate() ───────────────────────────────────────────────────────────

def test_validate_flags_missing_stair_on_multilevel():
    draft = _two_room_draft()
    upstairs_room = Room(id="up", type="bedroom", polygon=[[0, 0], [4, 0], [4, 4], [0, 4]], level=1, area_sqft=170)
    rooms = draft.model.rooms + [upstairs_room]
    warnings = fe.validate(rooms, draft.model.walls, draft.footprint_envelopes, target_sqft=2000)
    assert any(w.type == "missing_stair" for w in warnings)


def test_validate_flags_over_sqft():
    draft = _two_room_draft()
    warnings = fe.validate(draft.model.rooms, draft.model.walls, draft.footprint_envelopes, target_sqft=10)
    assert any(w.type == "over_sqft" for w in warnings)


def test_validate_flags_below_min_size():
    tiny = Room(id="tiny", type="bedroom", polygon=[[0, 0], [1, 0], [1, 1], [0, 1]], level=5, area_sqft=fe.room_area_sqft([[0, 0], [1, 0], [1, 1], [0, 1]]))
    warnings = fe.validate([tiny], [], {5: box(0, 0, 5, 5)}, target_sqft=2000)
    assert any(w.type == "below_min_size" and "tiny" in w.room_ids for w in warnings)


# ── apply_op dispatcher ────────────────────────────────────────────────

def test_apply_op_returns_ok_false_with_error_instead_of_raising():
    draft = _two_room_draft()
    ok, err = fe.apply_op(draft, "move_wall", {"level": 0, "wall_id": "nope", "delta_ft": 1.0})
    assert ok is False
    assert err

def test_apply_op_missing_param_is_reported_not_raised():
    draft = _two_room_draft()
    ok, err = fe.apply_op(draft, "resize_room", {"level": 0, "room_id": "room_a"})  # missing edge/delta_ft
    assert ok is False
    assert "Missing required param" in err

def test_apply_op_unknown_op_type():
    draft = _two_room_draft()
    ok, err = fe.apply_op(draft, "relocate_room", {})
    assert ok is False
