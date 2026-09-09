"""Regressions for the 2D blueprint stage: per-floor programs, stair cores,
and wall-drag direction.

Each test here pins a bug that shipped and was visible in the product:
upper floors rendering as copies of the ground floor, stair bands eating whole
rooms, and wall drags moving opposite to the cursor.
"""
from __future__ import annotations

from pathlib import Path
import sys

from shapely.geometry import box

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.constants import BuildingUse
from app.generators import floorplan_editor as fe
from app.generators.floorplan import (
    SFR_GROUND_ROWS, SFR_UPPER_ROWS, FloorplanGenerator,
)
from app.models.schemas import (
    BuildingModel, Level, ProjectSpec, Room, SiteInput,
)
from app.services.draft_state import DraftState


def _levels(n: int = 2) -> list[Level]:
    return [
        Level(index=i, elevation_ft=i * 10.0, height_ft=10.0, label=f"Level {i + 1}")
        for i in range(n)
    ]


# ── Upper floors must not duplicate the ground floor ────────────────────────

def test_upper_rows_share_no_row_with_ground_rows() -> None:
    """SFR_UPPER_ROWS used to be bypassed for 2-story plans in favour of the
    full SFR_PROGRAMS, whose first two rows ARE SFR_GROUND_ROWS — so floor 1
    came out as a pixel-copy of floor 0."""
    for br in SFR_GROUND_ROWS:
        ground = [tuple(r["type"] for r in row["rooms"]) for row in SFR_GROUND_ROWS[br]]
        upper = [tuple(r["type"] for r in row["rooms"]) for row in SFR_UPPER_ROWS[br]]
        overlap = set(ground) & set(upper)
        assert not overlap, f"{br}BR upper floor repeats ground-floor row(s): {overlap}"


def test_two_story_floors_have_different_room_programs() -> None:
    fg = FloorplanGenerator()
    levels = _levels(2)
    # Both a small plate (below LARGE_HOUSE_THRESHOLD_M2) and a large one.
    for w, d in [(9.0, 8.0), (12.0, 11.0)]:
        footprint = box(0, 0, w, d)
        rooms = []
        for level in levels:
            got, _ = fg._layout_sfr_floor(
                footprint, footprint.bounds, w, d, level, levels, 3,
                {"staircase": {"location": "left_spine_or_center"}},
            )
            rooms += got
        f0 = sorted(r.type for r in rooms if r.level == 0)
        f1 = sorted(r.type for r in rooms if r.level == 1)
        assert f0 != f1, f"{w}x{d} produced identical programs on both floors: {f0}"
        assert "bedroom" not in f0, f"{w}x{d} put bedrooms on the ground floor"
        assert "bedroom" in f1, f"{w}x{d} upper floor has no bedrooms"


# ── Stair core ──────────────────────────────────────────────────────────────

def test_stair_band_does_not_span_the_footprint() -> None:
    """The stair rectangle's right edge was pinned to the footprint's far wall
    regardless of where its left edge started, so 'left'/'spine'/'center'
    archetypes emitted a stair spanning the whole (or half the) building."""
    fg = FloorplanGenerator()
    levels = _levels(2)
    w, d = 12.0, 10.0
    footprint = box(0, 0, w, d)
    for location in ("left_spine_or_center", "entry_foyer_or_center_hall", "rear_right"):
        rooms, _ = fg._layout_sfr_floor(
            footprint, footprint.bounds, w, d, levels[0], levels, 3,
            {"staircase": {"location": location}},
        )
        stairs = [r for r in rooms if r.type == "stair"]
        assert stairs, f"{location}: no stair emitted on a 2-story plan"
        for stair in stairs:
            xs = [p[0] for p in stair.polygon]
            assert max(xs) - min(xs) <= 2.0, (
                f"{location}: stair is {max(xs) - min(xs):.2f} m wide — it is "
                "spanning the footprint again"
            )


def test_stair_core_opens_the_floor_above() -> None:
    """A flight rising from level N needs a hole in level N+1's slab. Cores
    used to be carved only out of rooms on their own level, so the upper floor
    sealed over the staircase."""
    fg = FloorplanGenerator()
    stair_poly = [[8.0, 3.0], [9.5, 3.0], [9.5, 6.0], [8.0, 6.0]]
    rooms = [
        Room(id="stair0", type="stair", unit_id="h", level=0,
             polygon=stair_poly, area_sqft=48.0),
        Room(id="bed1", type="bedroom", unit_id="h", level=1,
             polygon=[[6.0, 2.0], [11.0, 2.0], [11.0, 7.0], [6.0, 7.0]], area_sqft=269.0),
    ]
    carved = fg._carve_vertical_cores(rooms)
    upper = next(r for r in carved if r.id == "bed1")
    assert upper.area_sqft < 269.0, "upper-floor room was not opened for the stair below"


# ── A floor is never just circulation ───────────────────────────────────────

def test_tight_plate_never_yields_a_circulation_only_building() -> None:
    """On a small plate every unit room can fail its minimum-size filter while
    the separately-generated corridor and stair survive, so the build came back
    as "2 rooms across 2 levels (0 units)" — a staircase and nothing else — with
    no error logged anywhere."""
    import json
    from pathlib import Path as _Path

    from app.models.schemas import SiteInput

    archetype = json.loads(
        (_Path(__file__).resolve().parents[1]
         / "app" / "data" / "archetypes" / "victorian_narrow_lot.json").read_text()
    )
    archetype["id"] = "victorian_narrow_lot"
    levels = _levels(2)
    fg = FloorplanGenerator()
    spec = ProjectSpec(
        site=SiteInput(address="t"), building_use=BuildingUse.multi_family,
        bedrooms=3, bathrooms=2, stories=2,
    )
    for w, d in [(4.0, 6.0), (4.5, 6.0), (5.0, 7.0)]:
        chosen = {"footprint": [[0, 0], [w, 0], [w, d], [0, d]], "height_ft": 20}
        rooms, _ = fg.generate(
            chosen, spec, levels, archetype=archetype,
            ai_room_program=None,
            ai_unit_program={"unit_mix": {"3br": 1}, "templates": {}},
        )
        circulation = {"stair", "corridor", "hall", "hallway", "unit"}
        habitable = [r for r in rooms if r.type not in circulation]
        assert habitable, (
            f"{w}x{d} plate produced a circulation-only building: "
            f"{sorted(r.type for r in rooms)}"
        )


# ── Door traversal ──────────────────────────────────────────────────────────

def test_every_room_is_reachable_through_a_door() -> None:
    """Doors form a spanning tree rooted at the entry, so every room has exactly
    one way in. The old multi-source BFS seeded every 'open' room as a root at
    once, which merely assumed the corridor/living/foyer were connected — no
    door was cut between them — and left rooms in a disconnected component, or
    rooms whose chosen wall was too short, with no door at all."""
    from shapely.geometry import Point, Polygon as _Poly

    from app.services.orchestrator import GenerationOrchestrator

    levels = _levels(2)
    fg = FloorplanGenerator()
    spec = ProjectSpec(
        site=SiteInput(address="t"), building_use=BuildingUse.single_family,
        bedrooms=3, bathrooms=2, stories=2,
    )
    orch = GenerationOrchestrator.__new__(GenerationOrchestrator)

    for w, d in [(12.0, 10.0), (9.0, 8.0), (14.0, 11.0)]:
        footprint = box(0, 0, w, d)
        rooms, walls = [], []
        for level in levels:
            got_rooms, got_walls = fg._layout_sfr_floor(
                footprint, footprint.bounds, w, d, level, levels, 3,
                {"staircase": {"location": "rear_right"}},
            )
            rooms += got_rooms
            walls += got_walls
        rooms = fg._carve_vertical_cores(rooms)
        meshes, _ = orch._generate_interior_door_meshes(rooms, walls, levels, spec)
        assert meshes, f"{w}x{d} produced no interior doors at all"

        served = set()
        for mesh in meshes:
            verts = mesh["vertices"]
            cx = sum(p[0] for p in verts) / len(verts)
            cz = sum(p[2] for p in verts) / len(verts)
            for room in rooms:
                if room.level == mesh["level"] and len(room.polygon) >= 3:
                    if _Poly(room.polygon).buffer(0.4).contains(Point(cx, cz)):
                        served.add(room.id)

        # Roots of each level's tree are entered directly (the front door on the
        # ground floor, the stair landing above) and need no interior door.
        for level_index in (0, 1):
            level_rooms = [r for r in rooms if r.level == level_index]
            doorless = [
                r for r in level_rooms
                if r.id not in served and r.type not in ("stair", "foyer", "entry")
            ]
            assert not doorless, (
                f"{w}x{d} level {level_index}: no way into "
                f"{[r.type for r in doorless]}"
            )


# ── Wall drag direction ─────────────────────────────────────────────────────

def _two_room_draft() -> DraftState:
    """Rooms A (y 0.2-4.0) and B (y 4.0-7.8) sharing a wall at y=4.0."""
    spec = ProjectSpec(
        site=SiteInput(address="t"), building_use=BuildingUse.single_family,
        bedrooms=3, bathrooms=2, stories=1,
    )
    rooms = [
        Room(id="A", type="living", unit_id="h", level=0,
             polygon=[[0.2, 0.2], [9.8, 0.2], [9.8, 4.0], [0.2, 4.0]], area_sqft=392.7),
        Room(id="B", type="kitchen", unit_id="h", level=0,
             polygon=[[0.2, 4.0], [9.8, 4.0], [9.8, 7.8], [0.2, 7.8]], area_sqft=392.7),
    ]
    envelope = box(0, 0, 10, 8)
    levels = _levels(1)
    model = BuildingModel(
        project_id="p", spec=spec, levels=levels, rooms=rooms, walls=[], massing_options=[],
    )
    model.walls = fe.derive_walls_for_level(rooms, envelope, 0, 10.0)
    return DraftState(
        draft_id="d", model=model, footprint_envelopes={0: envelope}, is_sfr=True,
        chosen_massing={}, infra={}, resolved_site={}, neighbor_style={},
        design_brief={}, sem_result={}, archetype={},
    )


def _shared_wall(draft: DraftState):
    return next(
        w for w in draft.model.walls
        if not w.is_exterior and abs(w.start[1] - 4.0) < 1e-6 and abs(w.end[1] - 4.0) < 1e-6
    )


def _y_span(draft: DraftState, room_id: str) -> tuple[float, float]:
    poly = next(r for r in draft.model.rooms if r.id == room_id).polygon
    ys = [p[1] for p in poly]
    return min(ys), max(ys)


def test_move_wall_follows_the_drag_direction() -> None:
    """delta_ft is a signed world-axis displacement. The client used to predict
    a grow/shrink sign from a vertex-average centroid while the server used an
    area centroid; where they disagreed the wall moved opposite to the cursor
    and the room the user was enlarging shrank instead."""
    for delta_ft, expected_y in [(2.0, 4.6), (-2.0, 3.4)]:
        draft = _two_room_draft()
        fe.move_wall(draft, 0, _shared_wall(draft).id, delta_ft)
        assert _y_span(draft, "A")[1] == expected_y
        assert _y_span(draft, "B")[0] == expected_y, "a gap opened between the rooms"


def test_move_wall_clamps_instead_of_folding_the_room() -> None:
    draft = _two_room_draft()
    fe.move_wall(draft, 0, _shared_wall(draft).id, 40.0)
    b_lo, b_hi = _y_span(draft, "B")
    assert b_hi - b_lo >= fe.MIN_EDIT_WIDTH_M - 1e-6
    assert _y_span(draft, "A")[1] == b_lo, "rooms separated instead of staying contiguous"


def test_interior_wall_ids_are_stable_for_identical_geometry() -> None:
    """Ids were a fresh uuid4 per rebuild, so after every drag the wall under
    the cursor no longer existed and a follow-up drag hit 'Wall not found'."""
    assert _shared_wall(_two_room_draft()).id == _shared_wall(_two_room_draft()).id


def test_axis_aligned_tolerance_matches_the_editor_tolerance() -> None:
    """validate() called geometry non-orthogonal at 1 mm while every other
    check in the module treated 30 mm as coincident, so nearly every generated
    room reported a spurious 'non-orthogonal edge' warning."""
    assert fe._is_axis_aligned(0.0, 0.0, 1.0, fe.COORD_EPS_M * 0.9)
    assert not fe._is_axis_aligned(0.0, 0.0, 1.0, fe.COORD_EPS_M * 2)
