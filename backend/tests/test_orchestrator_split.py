from __future__ import annotations

import asyncio
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.constants import BuildingUse
from app.models.schemas import ProjectSpec, SiteInput
from app.services.draft_state import DraftState
from app.services.orchestrator import GenerationOrchestrator


def _spec() -> ProjectSpec:
    return ProjectSpec(
        site=SiteInput(address="test"),
        building_use=BuildingUse.single_family,
        bedrooms=3, bathrooms=2, stories=2,
    )


def test_run_composes_draft_then_finalize(monkeypatch) -> None:
    """run() must be exactly run_draft() followed by run_finalize() on its
    result — this is the seam the blueprint editor's draft/edit/finalize API
    is built on, so a caller who never edits anything must see identical
    behavior to the old one-shot run()."""
    orch = GenerationOrchestrator()

    spec = _spec()
    sentinel_draft = DraftState(
        draft_id="", model=object(), is_sfr=True, chosen_massing={},
        infra={}, resolved_site=None, neighbor_style={}, design_brief=None,
        sem_result=None, archetype=None,
    )
    sentinel_result = object()

    calls = []

    async def fake_run_draft(spec_arg, massing_choice=0):
        calls.append(("draft", spec_arg, massing_choice))
        return sentinel_draft

    async def fake_run_finalize(draft_arg):
        calls.append(("finalize", draft_arg))
        return sentinel_result

    monkeypatch.setattr(orch, "run_draft", fake_run_draft)
    monkeypatch.setattr(orch, "run_finalize", fake_run_finalize)

    result = asyncio.run(orch.run(spec, massing_choice=1))

    assert result is sentinel_result
    assert calls == [
        ("draft", spec, 1),
        ("finalize", sentinel_draft),
    ]


def test_run_finalize_uses_rooms_and_walls_currently_on_the_draft(monkeypatch) -> None:
    """This is the mechanism the blueprint editor relies on: mutating
    draft.model.rooms/draft.model.walls between run_draft() and
    run_finalize() must flow into the finalized BuildingModel — finalize
    must not silently regenerate its own rooms/walls."""
    from app.models.schemas import BuildingModel, Level, Room, SiteContext, LatLon

    orch = GenerationOrchestrator()
    spec = _spec()

    edited_room = Room(
        id="edited_room", type="bedroom", polygon=[[0, 0], [3, 0], [3, 3], [0, 3]],
        level=0, area_sqft=100.0,
    )
    model = BuildingModel(
        project_id="p1", spec=spec,
        site_context=SiteContext(
            parcel_polygon={}, buildable_envelope_2d={}, area_sqft=5000,
            centroid=LatLon(lat=0, lon=0),
        ),
        levels=[Level(index=0, elevation_ft=0, height_ft=10, label="Ground")],
        rooms=[edited_room], walls=[],
    )
    draft = DraftState(
        draft_id="d1", model=model, is_sfr=True,
        chosen_massing={"footprint": [[0, 0], [3, 0], [3, 3], [0, 3]], "total_area_m2": 30},
        infra={}, resolved_site=LatLon(lat=0, lon=0), neighbor_style={},
        design_brief=None, sem_result=None, archetype=None,
    )

    # Stub every downstream generator so this test exercises only the
    # rooms/walls plumbing, not the real facade/MEP/compliance pipeline.
    monkeypatch.setattr(orch.facade_gen, "generate", lambda *a, **k: [])
    monkeypatch.setattr(orch.mep_router, "route", lambda *a, **k: [])
    monkeypatch.setattr(orch.compliance_eng, "run", lambda m: [])
    monkeypatch.setattr(orch, "_generate_stair_meshes", lambda *a, **k: [])
    monkeypatch.setattr(orch, "_generate_interior_door_meshes", lambda *a, **k: ([], {}))

    from app.core.config import settings
    monkeypatch.setattr(settings, "BLENDER_RENDER_ENABLED", False)

    result = asyncio.run(orch.run_finalize(draft))

    assert [r.id for r in result.rooms] == ["edited_room"]
