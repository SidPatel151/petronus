"""DraftState — everything GenerationOrchestrator.run_finalize() needs to
resume the pipeline after floorplan generation.

run_draft() returns one of these instead of continuing straight into
facade/MEP/structural/compliance/render. The blueprint editor mutates
draft.model.rooms / draft.model.walls between run_draft() and
run_finalize() (via app.generators.floorplan_editor); run_finalize() picks
up whatever rooms/walls are on the draft at the time it's called, so a
zero-edit round trip produces the same output as the old one-shot run().
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shapely.geometry import Polygon

from app.models.schemas import BuildingModel, LatLon


@dataclass
class DraftState:
    draft_id: str
    model: BuildingModel
    is_sfr: bool
    chosen_massing: Dict[str, Any]
    infra: Dict[str, Any]
    resolved_site: LatLon
    neighbor_style: Dict[str, Any]
    design_brief: Optional[Dict[str, Any]]
    sem_result: Optional[Dict[str, Any]]
    archetype: Optional[Dict[str, Any]]
    footprint_envelopes: Dict[int, Polygon] = field(default_factory=dict)
    edit_history: List[Dict[str, Any]] = field(default_factory=list)
