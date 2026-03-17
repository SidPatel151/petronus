"""
MEPRouter — all coords in local meters (X, Y=elevation, Z)
All elements are connected: risers → branches → fixtures,
panel → feeder → trunk → branch drops → lights.
"""
import uuid
from typing import List, Dict, Tuple, Optional
from app.models.schemas import MEPElement, Room, Wall, ProjectSpec, Level


class MEPRouter:

    def route(self, rooms: List[Room], walls: List[Wall], levels: List[Level], spec: ProjectSpec) -> List[MEPElement]:
        elements = []
        elements.extend(self._route_plumbing(rooms, levels))
        elements.extend(self._route_electrical(rooms, levels))
        elements.extend(self._route_hvac(rooms, levels, spec.hvac_preference))
        return elements

    # ── Plumbing ──────────────────────────────────────────────────────────────
    def _route_plumbing(self, rooms: List[Room], levels: List[Level]) -> List[MEPElement]:
        elements = []
        floor_h = levels[0].height_ft * 0.3048 if levels else 3.0
        top_y = len(levels) * floor_h - 0.4

        all_wet = [r for r in rooms if r.type in ("bathroom", "kitchen")]
        if not all_wet:
            return elements

        # One shared riser per unique XZ cluster (group by unit — use level-0 wet rooms)
        level0_wet = [r for r in all_wet if r.level == 0] or all_wet[:1]
        # Build one riser per wet room on level 0; upper-level rooms branch off it
        riser_positions: List[Tuple[float, float]] = []
        for room in level0_wet:
            rx, rz = self._centroid(room)
            riser_positions.append((rx, rz))
            elements.append(MEPElement(
                id=f"riser_{uuid.uuid4().hex[:6]}", system="plumbing", type="riser",
                start=[rx, 0.3, rz], end=[rx, top_y, rz], level=0, diameter_in=4.0))

        # For each wet room on every level, draw a horizontal branch FROM nearest riser TO room
        for room in all_wet:
            lvl_idx = room.level
            if lvl_idx >= len(levels):
                continue
            branch_y = lvl_idx * floor_h + 0.4
            cx, cz = self._centroid(room)
            # Nearest riser
            rx, rz = min(riser_positions, key=lambda p: (p[0]-cx)**2 + (p[1]-cz)**2)
            # Horizontal supply branch: riser → room centroid
            elements.append(MEPElement(
                id=f"supply_{uuid.uuid4().hex[:6]}", system="plumbing", type="supply_branch",
                start=[rx, branch_y, rz], end=[cx, branch_y, cz],
                level=lvl_idx, diameter_in=1.5))
            # Waste branch drops below floor
            elements.append(MEPElement(
                id=f"waste_{uuid.uuid4().hex[:6]}", system="plumbing", type="waste_branch",
                start=[cx, branch_y - 0.1, cz], end=[rx, branch_y - 0.1, rz],
                level=lvl_idx, diameter_in=3.0))
            elements.append(MEPElement(
                id=f"fixture_{room.type}_{uuid.uuid4().hex[:4]}", system="plumbing", type="fixture",
                start=[cx, branch_y, cz], level=lvl_idx))

        return elements

    # ── Electrical ────────────────────────────────────────────────────────────
    def _route_electrical(self, rooms: List[Room], levels: List[Level]) -> List[MEPElement]:
        elements = []
        floor_h = levels[0].height_ft * 0.3048 if levels else 3.0

        # Main panel at left edge of ground-floor corridor
        corrs_0 = [r for r in rooms if r.type == "corridor" and r.level == 0]
        if corrs_0:
            bds0 = self._bounds(corrs_0[0])
            panel_x = bds0[0] + 0.3
            panel_z = (bds0[1] + bds0[3]) / 2
        else:
            panel_x, panel_z = 0.0, 0.0

        elements.append(MEPElement(
            id="panel_main", system="electrical", type="panel",
            start=[panel_x, 1.5, panel_z], level=0))

        for level in levels:
            lvl = level.index
            elev_y = lvl * floor_h
            ceil_y = elev_y + floor_h - 0.3

            # Sub-panel at this floor (same XZ column)
            elements.append(MEPElement(
                id=f"panel_{lvl}", system="electrical", type="panel",
                start=[panel_x, elev_y + 1.5, panel_z], level=lvl))

            # Feeder riser between floors
            if lvl > 0:
                elements.append(MEPElement(
                    id=f"feeder_{lvl}", system="electrical", type="feeder",
                    start=[panel_x, (lvl - 1) * floor_h + 1.5, panel_z],
                    end=[panel_x, elev_y + 1.5, panel_z], level=lvl))

            # Corridor trunk along ceiling
            lvl_corrs = [r for r in rooms if r.type == "corridor" and r.level == lvl]
            trunk_z = panel_z  # default
            for corr in lvl_corrs:
                bds = self._bounds(corr)
                trunk_z = bds[1] + 0.3
                # Trunk: panel → end of corridor
                elements.append(MEPElement(
                    id=f"trunk_{lvl}_{uuid.uuid4().hex[:4]}", system="electrical", type="conduit_trunk",
                    start=[panel_x, ceil_y, trunk_z], end=[bds[2], ceil_y, trunk_z], level=lvl))

            # Branch drops: trunk → each room's light (panel_x side of trunk → room centroid)
            for room in rooms:
                if room.level != lvl or room.type in ("stair", "corridor"):
                    continue
                cx, cz = self._centroid(room)
                # Drop from trunk (at cx, same height) down to light
                elements.append(MEPElement(
                    id=f"branch_{uuid.uuid4().hex[:6]}", system="electrical", type="conduit_trunk",
                    start=[cx, ceil_y, trunk_z], end=[cx, ceil_y, cz], level=lvl))
                elements.append(MEPElement(
                    id=f"light_{uuid.uuid4().hex[:6]}", system="electrical", type="lighting_point",
                    start=[cx, ceil_y, cz], level=lvl))

        return elements

    # ── HVAC ──────────────────────────────────────────────────────────────────
    def _route_hvac(self, rooms: List[Room], levels: List[Level], preference: str) -> List[MEPElement]:
        elements = []
        floor_h = levels[0].height_ft * 0.3048 if levels else 3.0

        if preference == "mini_split":
            unit_ids = set(r.unit_id for r in rooms if r.unit_id and r.type == "unit")
            for uid in unit_ids:
                unit = next((r for r in rooms if r.unit_id == uid and r.type == "unit"), None)
                if not unit or unit.level >= len(levels):
                    continue
                cx, cz = self._centroid(unit)
                ceil_y = unit.level * floor_h + floor_h - 0.3
                # Head unit only — refrigerant lines are inside the wall cavity
                elements.append(MEPElement(
                    id=f"head_{uuid.uuid4().hex[:6]}", system="hvac", type="mini_split_head",
                    start=[cx, ceil_y, cz], level=unit.level))
        else:
            # Rooftop unit
            roof_y = len(levels) * floor_h
            elements.append(MEPElement(
                id="rtu", system="hvac", type="rooftop_unit",
                start=[0, roof_y, 0], level=len(levels) - 1))

            # Main duct drops from roof to corridor ceiling on each floor, then branches to rooms
            for level in levels:
                lvl = level.index
                ceil_y = lvl * floor_h + floor_h - 0.4
                lvl_corrs = [r for r in rooms if r.type == "corridor" and r.level == lvl]
                for corr in lvl_corrs:
                    bds = self._bounds(corr)
                    trunk_z = bds[1] + 0.2
                    # Main duct along corridor
                    elements.append(MEPElement(
                        id=f"duct_{lvl}_{uuid.uuid4().hex[:4]}", system="hvac", type="supply_duct",
                        start=[bds[0], ceil_y, trunk_z], end=[bds[2], ceil_y, trunk_z],
                        level=lvl, width_in=18.0, height_in=10.0))
                    # Drops to each unit room
                    for room in rooms:
                        if room.level != lvl or room.type not in ("unit", "living", "bedroom"):
                            continue
                        cx, cz = self._centroid(room)
                        elements.append(MEPElement(
                            id=f"drop_{uuid.uuid4().hex[:6]}", system="hvac", type="supply_duct",
                            start=[cx, ceil_y, trunk_z], end=[cx, ceil_y, cz], level=lvl))

        return elements

    def _centroid(self, room: Room) -> Tuple[float, float]:
        pts = room.polygon
        if not pts:
            return 0.0, 0.0
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)

    def _bounds(self, room: Room) -> Tuple[float, float, float, float]:
        pts = room.polygon
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def _bounds_multi(self, rooms: List[Room]) -> Tuple[float, float, float, float]:
        all_pts = [p for r in rooms for p in r.polygon]
        xs, ys = [p[0] for p in all_pts], [p[1] for p in all_pts]
        return min(xs), min(ys), max(xs), max(ys)
