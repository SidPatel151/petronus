"""
MEPRouter — all coords in local meters (X, Y=elevation, Z)
All elements are connected: risers → branches → fixtures,
panel → feeder → trunk → branch drops → lights.
"""
import uuid
from typing import List, Dict, Tuple, Optional
from app.models.schemas import MEPElement, Room, Wall, ProjectSpec, Level


class MEPRouter:

    def route(self, rooms: List[Room], walls: List[Wall], levels: List[Level], spec: ProjectSpec, power_connection: dict = None) -> List[MEPElement]:
        fine = (spec.fine_details or {}) if hasattr(spec, 'fine_details') else {}
        elements = []
        elements.extend(self._route_plumbing(rooms, walls, levels))
        elements.extend(self._route_electrical(rooms, levels, power_connection))
        elements.extend(self._route_hvac(rooms, levels, spec.hvac_preference))
        elements.extend(self._route_fixtures(rooms, levels, fine))
        return elements

    # ── Plumbing ──────────────────────────────────────────────────────────────
    def _route_plumbing(self, rooms: List[Room], walls: List[Wall], levels: List[Level]) -> List[MEPElement]:
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

        # Main building drain exits through the south wall (toward street)
        if riser_positions:
            avg_rx = sum(p[0] for p in riser_positions) / len(riser_positions)
            avg_rz = sum(p[1] for p in riser_positions) / len(riser_positions)
            # Find southernmost point (most negative z = front of building)
            ext_walls = [w for w in walls if hasattr(w, 'is_exterior') and w.is_exterior]
            south_z = min((w.start[1] for w in ext_walls), default=avg_rz - 8.0)
            elements.append(MEPElement(
                id="main_drain", system="plumbing", type="main_drain",
                start=[avg_rx, -0.5, avg_rz],
                end=[avg_rx, -0.5, south_z - 1.5],
                level=0, diameter_in=6.0))

        return elements

    # ── Electrical ────────────────────────────────────────────────────────────
    def _route_electrical(self, rooms: List[Room], levels: List[Level], power_connection: dict = None) -> List[MEPElement]:
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

        # Service entry: run conduit from panel to nearest exterior wall face, then to power connection
        if power_connection:
            try:
                coords = power_connection.get("geometry", {}).get("coordinates", [])
                if coords and len(coords) == 2:
                    # Site-edge point (where the power line meets the site boundary)
                    entry_x = coords[0][0]  # these are lat/lon but we want local meters
                    entry_z = coords[0][1]
                    # Use the panel position as start, and the edge of building as end
                    # Just route to the nearest exterior wall edge (approx -bw/2 in x)
                    entry_y = 1.5  # service entry height
                    # Draw service conduit from panel to building exterior face
                    elements.append(MEPElement(
                        id="service_entry", system="electrical", type="service_conduit",
                        start=[panel_x, entry_y, panel_z],
                        end=[panel_x - 8.0, entry_y, panel_z],  # toward street
                        level=0))
            except Exception:
                pass

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

    def _route_fixtures(self, rooms: List[Room], levels: List[Level], fine: dict) -> List[MEPElement]:
        """Place detailed fixtures: outlets, fire alarms, exhaust fans, plumbing fixtures."""
        elements = []
        floor_h = levels[0].height_ft * 0.3048 if levels else 3.0
        outlets_per_room = int(fine.get("outlets_per_room", 3))
        do_alarms = fine.get("fire_alarms", True)
        do_exhaust = fine.get("exhaust_fans", True)
        do_sprinklers = fine.get("fire_sprinklers", False)

        for room in rooms:
            lvl = room.level
            if lvl >= len(levels):
                continue
            floor_y = lvl * floor_h
            cx, cz = self._centroid(room)
            bds = self._bounds(room)

            # ── Electrical outlets along walls (evenly spaced around perimeter) ──
            pts = room.polygon
            if outlets_per_room > 0 and len(pts) >= 2:
                step = max(1, len(pts) // outlets_per_room)
                for i in range(0, len(pts), step):
                    ox = (pts[i][0] + pts[(i+1) % len(pts)][0]) / 2
                    oz = (pts[i][1] + pts[(i+1) % len(pts)][1]) / 2
                    elements.append(MEPElement(
                        id=f"outlet_{uuid.uuid4().hex[:6]}", system="electrical", type="outlet",
                        start=[ox, floor_y + 0.4, oz], level=lvl))

            # ── Fire alarm in each corridor + unit ──
            if do_alarms and room.type in ("corridor", "unit", "bedroom", "living"):
                elements.append(MEPElement(
                    id=f"alarm_{uuid.uuid4().hex[:6]}", system="electrical", type="fire_alarm",
                    start=[cx, floor_y + floor_h - 0.15, cz], level=lvl))

            # ── Sprinkler heads in all rooms ──
            if do_sprinklers:
                elements.append(MEPElement(
                    id=f"sprinkler_{uuid.uuid4().hex[:6]}", system="plumbing", type="sprinkler",
                    start=[cx, floor_y + floor_h - 0.12, cz], level=lvl))

            # ── Bathroom fixtures: toilet + sink + shower ──
            if room.type == "bathroom":
                w = bds[2] - bds[0]
                d = bds[3] - bds[1]
                # Toilet near corner
                elements.append(MEPElement(
                    id=f"toilet_{uuid.uuid4().hex[:5]}", system="plumbing", type="toilet",
                    start=[bds[0] + 0.45, floor_y + 0.01, bds[1] + 0.45], level=lvl))
                # Sink along wall
                elements.append(MEPElement(
                    id=f"sink_{uuid.uuid4().hex[:5]}", system="plumbing", type="sink",
                    start=[bds[0] + w*0.7, floor_y + 0.01, bds[1] + 0.35], level=lvl))
                # Shower in opposite corner
                elements.append(MEPElement(
                    id=f"shower_{uuid.uuid4().hex[:5]}", system="plumbing", type="shower",
                    start=[bds[2] - 0.6, floor_y + 0.01, bds[3] - 0.6], level=lvl))
                # Exhaust fan
                if do_exhaust:
                    elements.append(MEPElement(
                        id=f"exhaust_{uuid.uuid4().hex[:5]}", system="hvac", type="exhaust_fan",
                        start=[cx, floor_y + floor_h - 0.2, cz], level=lvl))

            # ── Kitchen fixture: sink ──
            if room.type == "kitchen":
                bds = self._bounds(room)
                elements.append(MEPElement(
                    id=f"kitchen_sink_{uuid.uuid4().hex[:5]}", system="plumbing", type="sink",
                    start=[bds[0] + 0.5, floor_y + 0.01, bds[3] - 0.45], level=lvl))
                if do_exhaust:
                    elements.append(MEPElement(
                        id=f"range_hood_{uuid.uuid4().hex[:5]}", system="hvac", type="exhaust_fan",
                        start=[cx, floor_y + floor_h - 0.3, cz], level=lvl))

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
