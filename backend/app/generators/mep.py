"""
MEPRouter — code-informed preliminary residential MEP systems
All coordinates: local meters, [X, Y_elevation, Z].

Routing zones per floor (floor_h = 3.048m / 10ft default):
  0.00–0.35m  : sub-slab (main drain, foundation drains)
  0.35–2.10m  : wall zone (outlets @0.4m, switches @1.2m, plumbing connections)
  2.10–2.55m  : ceiling zone (electrical conduit, sprinkler branch lines, fire alarm)
  2.55–3.05m  : plenum zone (HVAC supply/return ducts)
  3.05m+      : above ceiling / roof

Routing priority (to avoid clashes): structural → fire → plumbing → HVAC → electrical
Each element carries a bounding box so the ClashDetector can find conflicts.
"""
import uuid
import math
import heapq
from typing import List, Dict, Tuple, Optional, Any, Sequence
from app.models.schemas import MEPElement, Room, Wall, ProjectSpec, Level
from shapely.geometry import Polygon, Point as ShpPoint, LineString
from shapely.ops import polygonize, unary_union

# ── Zone heights relative to floor datum ─────────────────────────────────
ZONE = {
    "sub_slab":      -0.35,   # drain pipes — below slab
    "slab_top":       0.0,    # finished floor
    "outlet":         0.40,   # electrical outlets
    "switch":         1.20,   # light switches
    "supply_pipe":    0.50,   # domestic water supply (in wall)
    "waste_pipe":     0.10,   # waste (just below slab, gravity)
    "ceil_elec":      2.20,   # electrical conduit @ ceiling
    "ceil_fire":      2.30,   # sprinkler branch pipes; separated from return ducts
    "ceil_light":     2.45,   # light fixtures
    "duct_return":    2.65,   # HVAC return air
    "duct_supply":    2.82,   # HVAC supply duct (main)
    "duct_branch":    2.72,   # HVAC branch ducts
}

# ── Preliminary domestic-water planning fixture units ────────────────────
FIXTURE_UNITS = {
    "toilet":   3.0,
    "sink":     2.0,
    "shower":   2.0,
    "bathtub":  2.0,
    "kitchen":  2.0,   # kitchen sink
    "washer":   3.0,
}

# ── Preliminary pipe sizing by fixture units; verify against adopted CPC ─
# (max_wsfu, pipe_size_in)
WATER_PIPE_SIZES = [
    (1.5,  0.50),
    (3.0,  0.75),
    (6.0,  1.00),
    (14.0, 1.25),
    (27.0, 1.50),
    (60.0, 2.00),
]

# ── Preliminary drain sizing by DFU; verify against adopted CPC ──────────
# (max_dfu, pipe_size_in)
DRAIN_PIPE_SIZES = [
    (1,   1.25),
    (3,   1.50),
    (6,   2.00),
    (12,  3.00),
    (20,  4.00),
    (160, 6.00),
]

# ── Conceptual duct sizing by CFM; final design requires loads/Manual D ──
# CFM per room type per 100 sqft (approximate for residential)
CFM_PER_100SQFT = {
    "bedroom": 25, "living": 30, "family_room": 30,
    "office": 25, "library": 25, "gym": 35, "unit": 30,
    "kitchen": 40, "bathroom": 50, "dining": 20,
    "corridor": 15, "laundry": 30,
}

# Preliminary mapping: (max_cfm, width_in, height_in, diameter_in_round)
DUCT_SIZES = [
    (60,   6,  6,  6),
    (120,  8,  6,  8),
    (200, 10,  8, 10),
    (350, 12,  8, 12),
    (600, 14, 10, 14),
    (900, 16, 10, 16),
    (1400,18, 12, 18),
    (2000,20, 12, 20),
]

# ── NEC electrical sizing ─────────────────────────────────────────────────
WATTS_PER_SQFT = 3.0          # NEC 220.12 general lighting load
CIRCUIT_AMPS   = 20           # standard 20A branch circuit
CIRCUIT_VOLTS  = 120          # single-phase
CIRCUIT_VA     = CIRCUIT_AMPS * CIRCUIT_VOLTS   # 2400 VA per circuit

# ── Conceptual residential sprinkler prelayout ───────────────────────────
# A conservative notional cell used only to avoid visibly uncovered rooms.
# Final spacing, obstruction, listing, flow, and pipe sizing require the
# occupancy-specific adopted standard and a hydraulic design.
SPRINKLER_COVERAGE_M2  = 16.7
SPRINKLER_FLOW_GPM     = 13.0   # residential head K=4.9, 10psi → 15.5 gpm
SPRINKLER_PIPE_FLOW = [         # preliminary branch sizing by served heads
    (2,   1.0),   # ≤2 heads: 1" pipe
    (4,   1.25),
    (6,   1.5),
    (12,  2.0),
    (40,  2.5),
    (100, 3.0),
]

# Centreline keep-outs used by the visibility router.  Values include the
# largest expected device radius plus the inter-trade preflight clearance.
ROLE_KEEP_OUT_M = {
    "fire": 0.32,
    "soil": 0.34,
    "cold": 0.31,
    "hot": 0.31,
    "electrical": 0.30,
    "hvac_supply": 0.46,   # includes a 30-inch mini-split head
    "hvac_return": 0.30,
    "hvac_equipment": 0.50,
    "exhaust": 0.16,
    "alarm": 0.12,
    "lighting": 0.12,
    "sprinkler": 0.21,
}


class MEPRouter:

    def route(
        self,
        rooms: List[Room],
        walls: List[Wall],
        levels: List[Level],
        spec: ProjectSpec,
        power_connection: dict = None,
        structural_members: List[Dict] = None,
        archetype: Optional[Dict[str, Any]] = None,
    ) -> List[MEPElement]:
        """Route all MEP systems and return elements sorted by system."""
        fine = self._resolve_mep_profile(spec, archetype)
        floor_h = levels[0].height_ft * 0.3048 if levels else 3.048

        # bathrooms: None / whole number = full baths, x.5 = includes a half bath
        bath_count = getattr(spec, 'bathrooms', None)

        # Polygonize the actual wall network.  Sorting vertices by angle turns
        # concave L/U footprints into the wrong shell and drops valid routes in
        # the building wings.
        fp_poly = self._footprint_polygon(rooms, walls)

        # Rooms are generated from the floorplan footprint and should already
        # be clipped to the interior shell. Do not exclude rooms by footprint
        # test here, as that can incorrectly omit entire wings or stepped massing.
        rooms_inside = list(rooms)
        # Multifamily floorplans can include an enclosing ``unit`` shell plus
        # its programmed child rooms. Route leaf rooms only so loads and device
        # counts are not doubled over the same physical area.
        child_unit_ids = {
            room.unit_id for room in rooms_inside
            if room.unit_id and room.type != "unit"
        }
        rooms_inside = [
            room for room in rooms_inside
            if not (room.type == "unit" and room.id in child_unit_ids)
        ]

        is_adu = getattr(spec, 'building_use', None) in ('adu',)
        try:
            from app.constants import BuildingUse as _BU
            is_adu = is_adu or getattr(spec, 'building_use', None) == _BU.adu
        except Exception:
            pass

        elements = []
        elements.extend(self._route_fire_protection(rooms_inside, levels, floor_h, fine))
        elements.extend(self._route_plumbing(
            rooms_inside, walls, levels, floor_h, bath_count,
            is_adu=is_adu, profile=fine,
        ))
        elements.extend(self._route_hvac(
            rooms_inside, levels, spec.hvac_preference, floor_h, fine,
        ))
        elements.extend(self._route_electrical(rooms_inside, walls, levels, floor_h, power_connection, fine, is_adu=is_adu))
        elements.extend(self._place_furniture(rooms_inside, levels, floor_h))
        if is_adu:
            elements.extend(self._adu_sewer_lateral(rooms_inside, walls))

        # Plumbing is generated before electrical, so sanitary vents do not
        # initially know where receptacle wall drops will land. Feed those
        # final vertical points back into vent routing before containment.
        if fp_poly is not None:
            elements = self._coordinate_vents_around_conduit_drops(
                elements, fp_poly
            )

        # Final containment pass — drop any element whose horizontal footprint
        # (x, z) start or end lands outside the building interior.
        # Vertical risers (same x,z for start and end) are exempt.
        if fp_poly is not None:
            # Include wall-mounted devices placed 5 cm inside the perimeter.
            fp_check = fp_poly.buffer(0.02)
            kept = []
            for el in elements:
                if el.type in {"utility_lateral", "sewer_lateral"}:
                    meta = dict(el.metadata or {})
                    meta["allow_outside_footprint"] = True
                    kept.append(el.model_copy(update={"metadata": meta}))
                    continue
                s = getattr(el, 'start', None)
                e = getattr(el, 'end', None)
                if s:
                    if not fp_check.covers(ShpPoint(s[0], s[2])):
                        continue  # start outside — skip
                if e:
                    # Only reject if end is outside AND it's a horizontal move
                    # (vertical risers have same x,z so they're always inside)
                    same_xz = abs(e[0] - s[0]) < 0.01 and abs(e[2] - s[2]) < 0.01
                    if not same_xz and not fp_check.covers(ShpPoint(e[0], e[2])):
                        continue  # end outside — skip
                kept.append(el)
            elements = self._contain_and_reroute(kept, fp_poly)

        return elements

    # ════════════════════════════════════════════════════════════════════════
    # FIRE PROTECTION (occupancy-specific preliminary layout)
    # ════════════════════════════════════════════════════════════════════════

    def _resolve_mep_profile(
        self, spec: ProjectSpec, archetype: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Merge conservative defaults, archetype guidance, and user choices.

        The image-derived archetype files contain useful system preferences,
        but user selections remain authoritative.  Only fields with a concrete
        generator implementation are promoted into this runtime profile.
        """
        profile: Dict[str, Any] = {
            "outlets_per_room": 3,
            "fire_alarms": True,
            "carbon_monoxide_detectors": True,
            "exhaust_fans": True,
            "fire_sprinklers": True,
            "whole_building_ventilation": True,
            "heat_pump_hvac": True,
            "heat_pump_water_heater": True,
        }
        if archetype:
            electrical = archetype.get("electrical") or {}
            hvac = archetype.get("hvac") or {}
            plumbing = archetype.get("plumbing") or {}
            compliance = archetype.get("california_compliance") or {}
            for key in (
                "outlets_per_room", "fire_alarms",
                "carbon_monoxide_detectors", "exhaust_fans",
            ):
                if key in electrical:
                    profile[key] = electrical[key]
            if "erv_hrv_required" in hvac:
                profile["erv_hrv_required"] = bool(hvac["erv_hrv_required"])
            if "heat_pump_design_default" in hvac:
                profile["heat_pump_hvac"] = bool(hvac["heat_pump_design_default"])
            elif "heat_pump_required" in hvac:  # legacy archetype compatibility
                profile["heat_pump_hvac"] = bool(hvac["heat_pump_required"])
            water_heater = plumbing.get("water_heater") or {}
            if water_heater.get("type"):
                profile["water_heater_type"] = water_heater["type"]
            sprinkler_rule = compliance.get("fire_sprinklers")
            if isinstance(sprinkler_rule, bool):
                profile["fire_sprinklers"] = sprinkler_rule

        # An ADU sprinkler exception is a legal applicability determination,
        # not an inference from whether sprinklers happen to be installed in
        # the primary dwelling.  Require the new explicit determination and a
        # traceable source; the legacy boolean alone must never remove the
        # conservative sprinkler layout.
        building_use = getattr(getattr(spec, "building_use", None), "value", getattr(spec, "building_use", None))
        profile["building_use"] = building_use
        profile["fire_standard"] = (
            "NFPA 13D" if building_use in ("single_family", "adu") else "NFPA 13R"
        )
        profile.update((getattr(spec, "fine_details", None) or {}))
        # This generator creates new residential buildings. Required life-safety
        # systems are code applicability, not cosmetic user preferences.  The
        # statutory ADU exception is the only modeled sprinkler opt-out.
        profile["fire_alarms"] = True
        profile["carbon_monoxide_detectors"] = True
        sprinkler_requirement = getattr(
            spec, "primary_dwelling_sprinkler_requirement", None
        )
        sprinkler_requirement = getattr(
            sprinkler_requirement, "value", sprinkler_requirement
        )
        determination_source = getattr(
            spec, "primary_dwelling_sprinkler_determination_source", None
        )
        documented_adu_exception = (
            building_use == "adu"
            and str(sprinkler_requirement or "").strip().lower() == "not_required"
            and isinstance(determination_source, str)
            and bool(determination_source.strip())
        )
        profile["adu_sprinkler_exception_documented"] = documented_adu_exception
        profile["primary_dwelling_sprinkler_requirement"] = sprinkler_requirement
        profile["primary_dwelling_sprinkler_determination_source"] = determination_source
        profile["fire_sprinklers"] = not documented_adu_exception
        return profile

    def _footprint_polygon(
        self, rooms: List[Room], walls: List[Wall]
    ) -> Optional[Polygon]:
        exterior = [
            LineString([w.start, w.end])
            for w in walls
            if getattr(w, "is_exterior", False) and w.level == 0
            and len(w.start) >= 2 and len(w.end) >= 2
        ]
        try:
            candidates = list(polygonize(unary_union(exterior))) if exterior else []
            if candidates:
                shell = max(candidates, key=lambda p: p.area)
                if shell.is_valid and not shell.is_empty:
                    return shell
        except Exception:
            pass

        # Safe fallback for incomplete wall graphs: union the actual level-zero
        # room polygons.  A tiny closing buffer bridges wall-thickness gaps.
        try:
            room_polys = [
                Polygon(r.polygon)
                for r in rooms if r.level == 0 and len(r.polygon) >= 3
            ]
            merged = unary_union(room_polys).buffer(0.12, join_style=2)
            if not merged.is_empty:
                if merged.geom_type == "MultiPolygon":
                    merged = max(merged.geoms, key=lambda p: p.area)
                return merged if merged.is_valid else merged.buffer(0)
        except Exception:
            pass
        return None

    def _shortest_horizontal_path(
        self, start: Tuple[float, float], end: Tuple[float, float], footprint: Polygon,
        avoid_points: Optional[List[Tuple[float, ...]]] = None,
        clearance_m: float = 0.0,
    ) -> List[Tuple[float, float]]:
        """Visibility-graph path inside the shell and around reserved chases.

        ``avoid_points`` represent vertical risers or ceiling terminals whose
        full 3-D geometry cannot be crossed simply by clipping a route to the
        footprint.  Diamond-shaped keep-outs keep the graph compact while
        still producing deterministic, orthogonal-looking coordination bends.
        """
        allowed_shell = footprint.buffer(0.03, join_style=2)
        direct = LineString([start, end])
        barriers = []
        # A third value on a keep-out is its required centreline radius.  Keep
        # the largest radius when multiple trades reserve the same coordinate.
        keepout_radii: Dict[Tuple[float, float], float] = {}
        for raw_point in avoid_points or []:
            coordinate = (round(float(raw_point[0]), 4), round(float(raw_point[1]), 4))
            radius = (
                float(raw_point[2])
                if len(raw_point) >= 3 and float(raw_point[2]) > 0
                else clearance_m
            )
            if radius > 0:
                keepout_radii[coordinate] = max(radius, keepout_radii.get(coordinate, 0.0))
        for coordinate, radius in keepout_radii.items():
            point = ShpPoint(*coordinate)
            # A route cannot avoid its own endpoint. Callers should choose
            # separated terminals; ignore an accidental endpoint keep-out
            # so generation still returns a visible, diagnosable route.
            if point.distance(ShpPoint(start)) < 0.01 or point.distance(ShpPoint(end)) < 0.01:
                continue
            # Keep every reserved vertical chase. A detour around one obstacle
            # can cross a second chase that was far from the original direct
            # line, so filtering only against that direct line is unsafe.
            barrier = point.buffer(radius, resolution=1)
            if allowed_shell.intersects(barrier):
                barriers.append(barrier)
        allowed = (
            allowed_shell.difference(unary_union(barriers))
            if barriers else allowed_shell
        )
        if allowed.covers(direct):
            return [start, end]

        vertices = list(footprint.exterior.coords[:-1])
        for ring in footprint.interiors:
            vertices.extend(ring.coords[:-1])
        for barrier in barriers:
            clipped = barrier.intersection(allowed_shell)
            if clipped.geom_type == "Polygon":
                vertices.extend(clipped.exterior.coords[:-1])
            elif clipped.geom_type == "MultiPolygon":
                for polygon in clipped.geoms:
                    vertices.extend(polygon.exterior.coords[:-1])
        nodes = [start, end] + [(float(x), float(z)) for x, z in vertices]
        graph: List[List[Tuple[int, float]]] = [[] for _ in nodes]
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                segment = LineString([nodes[i], nodes[j]])
                if allowed.covers(segment):
                    distance = segment.length
                    graph[i].append((j, distance))
                    graph[j].append((i, distance))

        distances = [math.inf] * len(nodes)
        previous = [-1] * len(nodes)
        distances[0] = 0.0
        queue = [(0.0, 0)]
        while queue:
            distance, node = heapq.heappop(queue)
            if distance != distances[node]:
                continue
            if node == 1:
                break
            for neighbor, weight in graph[node]:
                candidate = distance + weight
                if candidate < distances[neighbor]:
                    distances[neighbor] = candidate
                    previous[neighbor] = node
                    heapq.heappush(queue, (candidate, neighbor))
        if not math.isfinite(distances[1]):
            return []
        order = []
        node = 1
        while node != -1:
            order.append(node)
            node = previous[node]
        return [nodes[index] for index in reversed(order)]

    def _contain_and_reroute(
        self, elements: List[MEPElement], footprint: Polygon
    ) -> List[MEPElement]:
        allowed = footprint.buffer(0.02, join_style=2)
        output: List[MEPElement] = []
        external_types = {"utility_lateral", "sewer_lateral"}
        for element in elements:
            metadata = dict(element.metadata or {})
            avoid_points = metadata.pop("_coordination_avoid_points", [])
            clearance_m = float(metadata.pop("_coordination_clearance_m", 0.0) or 0.0)
            element = element.model_copy(update={"metadata": metadata})
            if element.type in external_types or metadata.get("allow_outside_footprint"):
                metadata["allow_outside_footprint"] = True
                output.append(element.model_copy(update={"metadata": metadata}))
                continue

            start = element.start
            end = element.end
            if not start or not allowed.covers(ShpPoint(start[0], start[2])):
                continue
            if not end:
                output.append(element)
                continue
            if not allowed.covers(ShpPoint(end[0], end[2])):
                continue
            if abs(end[0] - start[0]) < 0.01 and abs(end[2] - start[2]) < 0.01:
                output.append(element)
                continue

            path = self._shortest_horizontal_path(
                (start[0], start[2]), (end[0], end[2]), footprint,
                avoid_points=[tuple(point[:3]) for point in avoid_points if len(point) >= 2],
                clearance_m=clearance_m,
            )
            if not path:
                # Dense keep-outs can occasionally disconnect a small room.
                # Preserve the required network branch and fall back to the
                # shortest shell-contained path; the clash preflight will then
                # report any remaining coordination work instead of silently
                # deleting service to the room.
                path = self._shortest_horizontal_path(
                    (start[0], start[2]), (end[0], end[2]), footprint,
                )
                metadata["coordination_routing_fallback"] = True
                element = element.model_copy(update={"metadata": metadata})
            if len(path) <= 2:
                if path:
                    output.append(element)
                continue

            lengths = [
                math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
                for i in range(len(path) - 1)
            ]
            total = sum(lengths) or 1.0
            travelled = 0.0
            for index, ((x0, z0), (x1, z1)) in enumerate(zip(path, path[1:])):
                y0 = start[1] + (end[1] - start[1]) * travelled / total
                travelled += lengths[index]
                y1 = start[1] + (end[1] - start[1]) * travelled / total
                segment_metadata = dict(metadata)
                segment_metadata.update({
                    "route_parent_id": element.id,
                    "route_segment": index + 1,
                    "route_segment_count": len(path) - 1,
                })
                output.append(element.model_copy(update={
                    "id": f"{element.id}_seg{index + 1}",
                    "start": [x0, y0, z0],
                    "end": [x1, y1, z1],
                    "metadata": segment_metadata,
                }))
        return output

    def _coordinate_vents_around_conduit_drops(
        self, elements: List[MEPElement], footprint: Polygon
    ) -> List[MEPElement]:
        """Reserve vertical receptacle drops when routing sanitary vents.

        A wall drop spans the vent elevation, so vertical zoning alone cannot
        resolve a plan crossing. Sanitary vent branches instead receive a
        short horizontal coordination bend. Only drops near a branch's direct
        path are included, keeping large multifamily visibility graphs small.
        """
        drops_by_level: Dict[int, List[Tuple[float, float]]] = {}
        for element in elements:
            if (
                element.system != "electrical"
                or element.type != "conduit_branch"
                or not element.start
                or not element.end
            ):
                continue
            horizontal_run = math.hypot(
                element.end[0] - element.start[0],
                element.end[2] - element.start[2],
            )
            vertical_run = abs(element.end[1] - element.start[1])
            if horizontal_run < 0.02 and vertical_run >= 0.20:
                drops_by_level.setdefault(element.level, []).append(
                    (float(element.start[0]), float(element.start[2]))
                )

        if not drops_by_level:
            return elements

        coordinated: List[MEPElement] = []
        # A 1.5-inch vent, 0.75-inch conduit, and the detector's 5cm trade
        # clearance need roughly 0.079m between centrelines. The visibility
        # router uses a diamond buffer, so 0.14m leaves a small tolerance.
        drop_keepout_radius_m = 0.14
        candidate_distance_m = 0.18
        for element in elements:
            if (
                element.system != "plumbing"
                or element.type != "vent_branch"
                or not element.start
                or not element.end
            ):
                coordinated.append(element)
                continue

            metadata = dict(element.metadata or {})
            existing_avoid_points = list(
                metadata.get("_coordination_avoid_points", [])
            )
            existing_clearance = float(
                metadata.get("_coordination_clearance_m", 0.0) or 0.0
            )
            base_path = self._shortest_horizontal_path(
                (element.start[0], element.start[2]),
                (element.end[0], element.end[2]),
                footprint,
                avoid_points=[
                    tuple(point[:3])
                    for point in existing_avoid_points if len(point) >= 2
                ],
                clearance_m=existing_clearance,
            )
            route_shape = LineString(base_path) if len(base_path) >= 2 else LineString([
                (element.start[0], element.start[2]),
                (element.end[0], element.end[2]),
            ])
            nearby_drops = [
                (x, z)
                for x, z in drops_by_level.get(element.level, [])
                if route_shape.distance(ShpPoint(x, z)) < candidate_distance_m
            ]
            if not nearby_drops:
                coordinated.append(element)
                continue

            avoid_points = existing_avoid_points
            existing = {
                (round(float(point[0]), 4), round(float(point[1]), 4))
                for point in avoid_points if len(point) >= 2
            }
            for x, z in nearby_drops:
                key = (round(x, 4), round(z, 4))
                if key not in existing:
                    avoid_points.append([x, z, drop_keepout_radius_m])
                    existing.add(key)
            metadata["_coordination_avoid_points"] = avoid_points
            metadata["electrical_drop_coordination"] = True
            coordinated.append(element.model_copy(update={"metadata": metadata}))
        return coordinated

    def _route_fire_protection(
        self, rooms: List[Room], levels: List[Level], floor_h: float, fine: dict
    ) -> List[MEPElement]:
        """
        Place a conceptual residential sprinkler layout on every floor.
        The selected NFPA family is metadata for downstream review; final
        applicability, head listing, obstructions, and hydraulics remain an
        AHJ/fire-protection design task.
        """
        do_sprinklers = fine.get("fire_sprinklers", True)   # default ON for new builds
        fire_standard = str(fine.get("fire_standard", "NFPA 13R"))
        elements = []
        total_floors = len(levels)

        if not do_sprinklers:
            return elements

        # ── Riser location: utility/mechanical chase, never through stairwell ──
        rx, rz = self._mep_chase_position(rooms) if rooms else (0.0, 0.0)

        riser_top = total_floors * floor_h

        # Main fire riser (1.5" min, ground slab to roof level)
        elements.append(MEPElement(
            id="fire_riser_main",
            system="fire",
            type="fire_riser",
            start=[rx, 0.0, rz],
            end=[rx, riser_top, rz],
            level=0,
            diameter_in=2.0,
            metadata={"design_standard": fire_standard, "hydraulic_design_required": True},
        ))

        # Backflow preventer at entry (ground level, building perimeter)
        all_pts_flat = [p for r in rooms for p in r.polygon]
        if all_pts_flat:
            min_z = min(p[1] for p in all_pts_flat)
            elements.append(MEPElement(
                id="fire_backflow",
                system="fire",
                type="backflow_preventer",
                start=[rx, 0.9, min_z + 0.3],  # just inside front wall
                level=0,
            ))

        # ── Per-floor sprinkler heads — route directly from riser to each room ──
        # No horizontal trunk across the full building (would cross L/U voids).
        # Each branch drops straight from the riser at ceiling height to the head.
        for level in levels:
            lvl = level.index
            ceil_y = lvl * floor_h + ZONE["ceil_fire"]

            lvl_rooms = [r for r in rooms if r.level == lvl]
            if not lvl_rooms:
                continue

            # Horizontal systems occupy separated elevation zones.  The fire
            # branches therefore reserve only vertical chases; treating every
            # ceiling terminal as a full-height obstacle can disconnect small
            # rooms and force unsafe direct-route fallbacks.
            hvac_keepouts: List[List[float]] = []
            ground_wet_rooms = [
                room for room in rooms
                if room.level == 0 and room.type in ("bathroom", "kitchen", "laundry")
            ]
            for wet_room in ground_wet_rooms[:2]:
                hvac_keepouts.append(self._room_keepout(wet_room, "soil", 0.16))
            if ground_wet_rooms:
                for role in ("cold", "hot"):
                    hvac_keepouts.append(self._room_keepout(ground_wet_rooms[0], role, 0.12))
            central_hvac_x, central_hvac_z = self._central_hvac_position(rooms)
            electrical_x, electrical_z = self._central_hvac_position(rooms, role="electrical")
            hvac_keepouts.extend((
                self._point_keepout(central_hvac_x, central_hvac_z, "hvac_equipment", 0.30),
                self._point_keepout(electrical_x, electrical_z, "electrical", 0.28),
            ))

            # Sprinkler heads per room — route from riser position
            for room in lvl_rooms:
                if not do_sprinklers:
                    break
                head_y = ceil_y + 0.05
                positions = self._sprinkler_positions(room)
                branch_size = self._fire_pipe_size(len(positions))

                for (hx, hz) in positions:
                    elements.append(MEPElement(
                        id=f"sprinkler_{uuid.uuid4().hex[:6]}",
                        system="fire", type="sprinkler",
                        start=[hx, head_y, hz],
                        level=lvl, diameter_in=0.5,
                        metadata={
                            "room_id": room.id,
                            "design_coverage_m2": SPRINKLER_COVERAGE_M2,
                            "design_standard": fire_standard,
                            "listing_and_obstruction_review_required": True,
                        },
                    ))
                    # Vertical drop from riser at ceiling down to head
                    elements.append(MEPElement(
                        id=f"fire_drop_{uuid.uuid4().hex[:5]}",
                        system="fire", type="fire_branch_drop",
                        start=[rx, ceil_y, rz],
                        end=[hx, head_y, hz],
                        level=lvl, diameter_in=branch_size,
                        metadata={
                            "room_id": room.id,
                            "network_id": "fire_sprinkler",
                            "seismic_braced": True,
                            "design_standard": fire_standard,
                            "hydraulic_design_required": True,
                            "_coordination_avoid_points": hvac_keepouts,
                            "_coordination_clearance_m": 0.22,
                        },
                    ))

        return elements

    def _fire_pipe_size(self, n_heads: int) -> float:
        for max_heads, size in SPRINKLER_PIPE_FLOW:
            if n_heads <= max_heads:
                return size
        return 3.0

    # ════════════════════════════════════════════════════════════════════════
    # PLUMBING (preliminary CPC-informed layout)
    # ════════════════════════════════════════════════════════════════════════

    def _route_plumbing(
        self, rooms: List[Room], walls: List[Wall], levels: List[Level], floor_h: float,
        bath_count: Optional[float] = None, is_adu: bool = False,
        profile: Optional[Dict[str, Any]] = None,
    ) -> List[MEPElement]:
        """
        Route domestic water supply (hot + cold) and waste/vent.
        bath_count: whole number = full baths, x.5 includes a half bath (toilet+sink, no shower).
        """
        elements = []
        profile = profile or {}
        total_floors = len(levels)
        # True if spec includes a .5 half bath (toilet+sink only, no shower)
        _has_half_bath = bath_count is not None and (bath_count % 1) == 0.5
        bathroom_rooms = sorted(
            (room for room in rooms if room.type == "bathroom"),
            key=lambda room: (room.area_sqft, room.level, room.id),
        )
        half_bath_room_ids = {bathroom_rooms[0].id} if _has_half_bath and bathroom_rooms else set()
        top_y = total_floors * floor_h   # vent stack ends at roof level

        wet_rooms_by_level = {}
        for r in rooms:
            if r.type in ("bathroom", "kitchen", "laundry"):
                wet_rooms_by_level.setdefault(r.level, []).append(r)

        if not any(wet_rooms_by_level.values()):
            return elements

        # ── Stack location: use level-0 wet room centroid ──
        lvl0_wet = wet_rooms_by_level.get(0, [])
        if not lvl0_wet:
            lvl0_wet = [r for lvs in wet_rooms_by_level.values() for r in lvs][:1]

        fire_x, fire_z = self._mep_chase_position(rooms)
        hvac_x, hvac_z = self._central_hvac_position(rooms)
        electrical_x, electrical_z = self._central_hvac_position(rooms, role="electrical")
        vertical_trade_keepouts = [
            self._point_keepout(fire_x, fire_z, "fire", 0.15),
            self._point_keepout(hvac_x, hvac_z, "hvac_return", 0.34),
            self._point_keepout(electrical_x, electrical_z, "electrical", 0.17),
        ]

        stack_positions = []
        stack_ids_by_position: Dict[Tuple[float, float], str] = {}
        drain_d = 4.0  # default drain diameter
        for room in lvl0_wet[:2]:   # max 2 stacks for small buildings
            sx, sz = self._room_slot(room, "soil")
            stack_positions.append((sx, sz))

            # Soil stack (main waste): ground slab to roof vent
            total_dfu = sum(
                FIXTURE_UNITS.get(r.type, 1.0) * 1.5
                for r in rooms if r.type in ("bathroom", "kitchen", "laundry")
            )
            drain_d = self._drain_pipe_size(total_dfu)

            stack_id = f"stack_{uuid.uuid4().hex[:5]}"
            stack_ids_by_position[(sx, sz)] = stack_id
            elements.append(MEPElement(
                id=stack_id,
                system="plumbing",
                type="soil_stack",
                start=[sx, 0.0, sz],
                end=[sx, top_y, sz],
                level=0,
                diameter_in=drain_d,
                metadata={
                    "network_id": "sanitary_drain_and_vent",
                    "vent_through_roof": True,
                    "terminates_above_roof": True,
                    "design_status": "conceptual_prelayout",
                },
            ))

        # ── Water service entry ──
        all_room_pts = [p for r in rooms for p in r.polygon]
        if all_room_pts:
            service_z = min(p[1] for p in all_room_pts)   # building front wall
            cold_x, cold_z = self._room_slot(lvl0_wet[0], "cold")
            # Water service runs inside building from front wall to stack
            elements.append(MEPElement(
                id="water_service",
                system="plumbing",
                type="water_service",
                start=[cold_x, 0.3, service_z],
                end=[cold_x, 0.3, cold_z],
                level=0,
                diameter_in=1.5,
                metadata={
                    "network_id": "domestic_water",
                    "_coordination_avoid_points": vertical_trade_keepouts,
                    "_coordination_clearance_m": 0.34,
                },
            ))
            elements.append(MEPElement(
                id="water_meter",
                system="plumbing",
                type="water_meter",
                start=[cold_x, 0.3, service_z + 0.3],  # just inside the wall
                level=0,
                metadata={"network_id": "domestic_water"},
            ))
            elements.append(MEPElement(
                id="potable_backflow",
                system="plumbing",
                type="backflow_preventer",
                start=[cold_x, 0.45, service_z + 0.45],
                level=0,
                metadata={"network_id": "domestic_water", "testable": True},
            ))
            elements.append(MEPElement(
                id="building_cleanout",
                system="plumbing",
                type="cleanout",
                start=[stack_positions[0][0], 0.05, service_z + 0.25],
                level=0,
                metadata={"network_id": "sanitary", "access_clearance_in": 24},
            ))

        # ── Hot water heater (in utility or near kitchen, ground floor) ──
        util_rooms = [r for r in rooms if r.type in ("laundry", "utility", "kitchen") and r.level == 0]
        if util_rooms:
            hwh_cx, hwh_cz = self._room_slot(util_rooms[0], "equipment")
        else:
            hwh_cx, hwh_cz = stack_positions[0] if stack_positions else (0.0, 0.0)

        # ADU: prefer heat pump water heater (CA Title 24 / energy compliance)
        configured_hwh = str(profile.get("water_heater_type", "")).lower()
        use_heat_pump_hwh = bool(profile.get("heat_pump_water_heater", True))
        hwh_type = (
            "heat_pump_water_heater"
            if is_adu or use_heat_pump_hwh or "heat_pump" in configured_hwh
            else "water_heater"
        )
        elements.append(MEPElement(
            id="hot_water_heater",
            system="plumbing",
            type=hwh_type,
            start=[hwh_cx, 0.0, hwh_cz],
            level=0,
            metadata={
                "network_id": "domestic_hot_water",
                "heat_pump": hwh_type == "heat_pump_water_heater",
                "anchored": True,
                "service_clearance_in": 30,
            },
        ))

        # Explicit hot/cold risers make upper-floor branches connected rather
        # than appearing to originate in mid-air at the stack coordinates.
        cold_x, cold_z = self._room_slot(lvl0_wet[0], "cold")
        hot_x, hot_z = self._room_slot(lvl0_wet[0], "hot")
        elements.extend([
            MEPElement(
                id="cold_water_riser", system="plumbing", type="cold_water_riser",
                start=[cold_x, 0.3, cold_z], end=[cold_x, top_y - 0.2, cold_z], level=0,
                diameter_in=1.0,
                metadata={"network_id": "domestic_cold_water", "seismic_braced": True},
            ),
            MEPElement(
                id="hot_water_riser", system="plumbing", type="hot_water_riser",
                start=[hot_x, 0.5, hot_z], end=[hot_x, top_y - 0.2, hot_z], level=0,
                diameter_in=0.75,
                metadata={"network_id": "domestic_hot_water", "insulated": True, "seismic_braced": True},
            ),
            MEPElement(
                id="hot_water_header", system="plumbing", type="hot_supply",
                start=[hwh_cx, 0.5, hwh_cz], end=[hot_x, 0.5, hot_z], level=0,
                diameter_in=0.75,
                metadata={
                    "network_id": "domestic_hot_water", "insulated": True,
                    "_coordination_avoid_points": vertical_trade_keepouts,
                    "_coordination_clearance_m": 0.34,
                },
            ),
        ])

        # ── Per wet room: supply branches and fixture connections ──
        for lvl, lvl_rooms in wet_rooms_by_level.items():
            floor_y = lvl * floor_h

            for room in lvl_rooms:
                connection_x, connection_z = self._room_slot(room, "plumbing_terminal")
                waste_x, waste_z = min(
                    stack_positions,
                    key=lambda point: math.hypot(
                        point[0] - connection_x, point[1] - connection_z
                    ),
                )
                bds = self._bounds(room)
                # Route pipes inside the floor/wall zone — visible inside the building
                supply_y = floor_y + 0.15   # in-wall supply height
                waste_y  = floor_y + 0.05   # just above finished floor
                vent_y = floor_y + 1.95     # vent branch in partition zone

                is_half = room.id in half_bath_room_ids
                if room.type == "bathroom":
                    served_fixture_types = ["toilet", "sink"]
                    if not is_half:
                        served_fixture_types.append("shower")
                elif room.type == "kitchen":
                    served_fixture_types = ["kitchen_sink"]
                else:
                    served_fixture_types = ["washer_connection"]
                fixture_group_id = f"fixture_group_{room.id}"
                branch_evidence = {
                    "room_id": room.id,
                    "served_room_id": room.id,
                    "served_room_ids": [room.id],
                    "served_fixture_types": served_fixture_types,
                    "fixture_group_id": fixture_group_id,
                    "design_status": "conceptual_prelayout",
                }

                # Cold supply branch
                total_room_fu = FIXTURE_UNITS.get(room.type, 2.0)
                supply_d = self._water_pipe_size(total_room_fu)
                cold_branch_id = f"cold_{uuid.uuid4().hex[:5]}"
                elements.append(MEPElement(
                    id=cold_branch_id,
                    system="plumbing",
                    type="cold_supply",
                    start=[cold_x, supply_y, cold_z],
                    end=[connection_x, supply_y, connection_z],
                    level=lvl,
                    diameter_in=supply_d,
                    metadata={
                        **branch_evidence, "network_id": "domestic_cold_water",
                        "fixture_units": total_room_fu,
                        "_coordination_avoid_points": vertical_trade_keepouts,
                        "_coordination_clearance_m": 0.34,
                    },
                ))

                # Hot supply branch (from water heater, parallel, slightly offset)
                hot_branch_id = f"hot_{uuid.uuid4().hex[:5]}"
                if room.type in ("bathroom", "kitchen", "laundry"):
                    elements.append(MEPElement(
                        id=hot_branch_id,
                        system="plumbing",
                        type="hot_supply",
                        start=[hot_x, supply_y + 0.04, hot_z],
                        end=[connection_x, supply_y + 0.04, connection_z],
                        level=lvl,
                        diameter_in=supply_d,
                        metadata={
                            **branch_evidence, "network_id": "domestic_hot_water",
                            "insulated": True,
                            "_coordination_avoid_points": vertical_trade_keepouts,
                            "_coordination_clearance_m": 0.34,
                        },
                    ))

                # Waste branch
                waste_branch_id = f"waste_{uuid.uuid4().hex[:5]}"
                vent_branch_id = f"vent_{uuid.uuid4().hex[:5]}"
                connected_stack_id = stack_ids_by_position.get((waste_x, waste_z))
                elements.append(MEPElement(
                    id=waste_branch_id,
                    system="plumbing",
                    type="waste_branch",
                    start=[connection_x, waste_y, connection_z],
                    end=[waste_x, waste_y, waste_z],
                    level=lvl,
                    diameter_in=max(1.5, drain_d - 1.0),
                    metadata={
                        **branch_evidence, "network_id": "sanitary",
                        "slope_pct": 2.1, "vented": True,
                        "vent_branch_id": vent_branch_id,
                        "connected_stack_id": connected_stack_id,
                        "_coordination_avoid_points": vertical_trade_keepouts,
                        "_coordination_clearance_m": 0.34,
                    },
                ))
                elements.append(MEPElement(
                    id=vent_branch_id,
                    system="plumbing",
                    type="vent_branch",
                    start=[connection_x, vent_y, connection_z],
                    end=[waste_x, vent_y, waste_z],
                    level=lvl,
                    diameter_in=1.5,
                    metadata={
                        **branch_evidence,
                        "network_id": "sanitary_vent",
                        "waste_branch_id": waste_branch_id,
                        "connected_stack_id": connected_stack_id,
                        "vent_through_roof": True,
                        "_coordination_avoid_points": vertical_trade_keepouts,
                        "_coordination_clearance_m": 0.24,
                    },
                ))

                # Fixture placement — half bath (small room or last bath when .5 count)
                # gets toilet + sink only; full bath gets toilet + sink + shower
                if room.type == "bathroom":
                    # Only an explicitly requested fractional bath is treated
                    # as a half bath. Compact geometry alone must not silently
                    # remove the tub/shower from a requested full bathroom.
                    elements.append(MEPElement(
                        id=f"toilet_{uuid.uuid4().hex[:5]}",
                        system="plumbing", type="toilet",
                        start=self._fixture_xyz(room, "fixture_toilet", floor_y + 0.01), level=lvl,
                        metadata={
                            **branch_evidence, "fixture_units": 3.0,
                            "trap_seal_in": 2, "vented": True,
                            "cold_supply_branch_id": cold_branch_id,
                            "waste_branch_id": waste_branch_id,
                            "vent_branch_id": vent_branch_id,
                        }))
                    elements.append(MEPElement(
                        id=f"sink_{uuid.uuid4().hex[:5]}",
                        system="plumbing", type="sink",
                        start=self._fixture_xyz(room, "fixture_sink", floor_y + 0.01), level=lvl,
                        metadata={
                            **branch_evidence, "fixture_units": 2.0,
                            "trap_seal_in": 2, "vented": True,
                            "cold_supply_branch_id": cold_branch_id,
                            "hot_supply_branch_id": hot_branch_id,
                            "waste_branch_id": waste_branch_id,
                            "vent_branch_id": vent_branch_id,
                        }))
                    if not is_half:
                        # Full bath: add shower
                        elements.append(MEPElement(
                            id=f"shower_{uuid.uuid4().hex[:5]}",
                            system="plumbing", type="shower",
                            start=self._fixture_xyz(room, "fixture_shower", floor_y + 0.01), level=lvl,
                            metadata={
                                **branch_evidence, "fixture_units": 2.0,
                                "trap_seal_in": 2, "vented": True,
                                "cold_supply_branch_id": cold_branch_id,
                                "hot_supply_branch_id": hot_branch_id,
                                "waste_branch_id": waste_branch_id,
                                "vent_branch_id": vent_branch_id,
                            }))
                elif room.type == "kitchen":
                    elements.append(MEPElement(
                        id=f"ksink_{uuid.uuid4().hex[:5]}",
                        system="plumbing", type="kitchen_sink",
                        start=self._fixture_xyz(room, "fixture_kitchen_sink", floor_y + 0.01), level=lvl,
                        metadata={
                            **branch_evidence, "fixture_units": 2.0,
                            "trap_seal_in": 2, "vented": True,
                            "cold_supply_branch_id": cold_branch_id,
                            "hot_supply_branch_id": hot_branch_id,
                            "waste_branch_id": waste_branch_id,
                            "vent_branch_id": vent_branch_id,
                        }))
                elif room.type == "laundry":
                    elements.append(MEPElement(
                        id=f"washer_box_{uuid.uuid4().hex[:5]}",
                        system="plumbing", type="washer_connection",
                        start=self._fixture_xyz(room, "fixture_laundry", floor_y + 0.9), level=lvl,
                        metadata={
                            **branch_evidence, "fixture_units": 3.0,
                            "trap_seal_in": 2, "vented": True,
                            "cold_supply_branch_id": cold_branch_id,
                            "hot_supply_branch_id": hot_branch_id,
                            "waste_branch_id": waste_branch_id,
                            "vent_branch_id": vent_branch_id,
                        }))

        return elements

    def _water_pipe_size(self, wsfu: float) -> float:
        for max_wsfu, size in WATER_PIPE_SIZES:
            if wsfu <= max_wsfu:
                return size
        return 2.0

    def _drain_pipe_size(self, dfu: float) -> float:
        for max_dfu, size in DRAIN_PIPE_SIZES:
            if dfu <= max_dfu:
                return size
        return 4.0

    def _get_room_bounds_near(self, rooms, cx, cz):
        for r in rooms:
            bds = self._bounds(r)
            if bds[0] <= cx <= bds[2] and bds[1] <= cz <= bds[3]:
                return bds
        return (cx-1, cz-1, cx+1, cz+1)

    # ════════════════════════════════════════════════════════════════════════
    # HVAC
    # ════════════════════════════════════════════════════════════════════════

    def _route_hvac(
        self, rooms: List[Room], levels: List[Level], preference, floor_h: float,
        profile: Optional[Dict[str, Any]] = None,
    ) -> List[MEPElement]:
        """
        Route HVAC systems.
        mini_split: individual wall units per zone.
        rooftop: central RTU + main trunk + branches to each room.
        """
        pref = getattr(preference, 'value', str(preference)).lower()
        profile = profile or {}

        if pref == "mini_split":
            elements = self._hvac_mini_split(rooms, levels, floor_h, profile)
        else:
            elements = self._hvac_central(rooms, levels, floor_h, profile)
        elements.extend(self._route_ventilation_and_exhaust(rooms, levels, floor_h, profile))
        return elements

    def _sprinkler_positions(self, room: Room) -> List[Tuple[float, float]]:
        """Lay out enough heads to keep each notional cell below 180 ft².

        This is a deterministic preliminary layout, not a hydraulic design.
        Intersections with the actual room polygon keep heads out of concave
        notches, which the previous bounding-box placement could not do.
        """
        polygon = Polygon(room.polygon)
        if polygon.is_empty or not polygon.is_valid:
            cx, cz = self._centroid(room)
            return [(cx, cz)]
        target_count = max(1, math.ceil(polygon.area / SPRINKLER_COVERAGE_M2))
        min_x, min_z, max_x, max_z = polygon.bounds
        width = max(max_x - min_x, 0.1)
        depth = max(max_z - min_z, 0.1)
        columns = max(1, math.ceil(math.sqrt(target_count * width / depth)))
        rows = max(1, math.ceil(target_count / columns))
        positions: List[Tuple[float, float]] = []
        reserved = [
            self._room_slot(room, role)
            for role in (
                "fire", "soil", "cold", "hot", "electrical",
                "hvac_supply", "hvac_return", "hvac_equipment", "exhaust", "alarm",
            )
        ]
        for row in range(rows):
            for column in range(columns):
                cell = Polygon([
                    [min_x + width * column / columns, min_z + depth * row / rows],
                    [min_x + width * (column + 1) / columns, min_z + depth * row / rows],
                    [min_x + width * (column + 1) / columns, min_z + depth * (row + 1) / rows],
                    [min_x + width * column / columns, min_z + depth * (row + 1) / rows],
                ])
                clipped = polygon.intersection(cell)
                if clipped.is_empty or clipped.area < 0.05:
                    continue
                point = clipped.representative_point()
                min_cell_x, min_cell_z, max_cell_x, max_cell_z = clipped.bounds
                candidates = [point]
                for fraction_x, fraction_z in (
                    (0.20, 0.20), (0.20, 0.80), (0.80, 0.20), (0.80, 0.80),
                    (0.35, 0.50), (0.65, 0.50), (0.50, 0.35), (0.50, 0.65),
                ):
                    candidate = ShpPoint(
                        min_cell_x + (max_cell_x - min_cell_x) * fraction_x,
                        min_cell_z + (max_cell_z - min_cell_z) * fraction_z,
                    )
                    if clipped.buffer(-0.08).covers(candidate):
                        candidates.append(candidate)
                separation_points = reserved + positions
                best = max(
                    candidates,
                    key=lambda candidate: min(
                        math.hypot(candidate.x - other_x, candidate.y - other_z)
                        for other_x, other_z in separation_points
                    ),
                )
                positions.append((float(best.x), float(best.y)))
        return positions or [self._centroid(room)]

    def _lighting_positions(self, room: Room) -> List[Tuple[float, float]]:
        """Mirror the electrical ceiling-light layout for trade coordination."""
        polygon = Polygon(room.polygon)
        if polygon.is_empty:
            return []
        positions: List[Tuple[float, float]] = []
        reserved = [
            self._room_slot(room, role)
            for role in (
                "fire", "soil", "cold", "hot", "electrical",
                "hvac_supply", "hvac_return", "hvac_equipment", "exhaust", "alarm",
            )
        ]
        for light_x, light_z in self._sprinkler_positions(room):
            candidates = []
            for offset_x, offset_z in (
                (-0.55, 0.0), (0.55, 0.0), (0.0, -0.55), (0.0, 0.55),
                (-0.42, -0.42), (-0.42, 0.42), (0.42, -0.42), (0.42, 0.42),
                (-0.30, 0.0), (0.30, 0.0), (0.0, -0.30), (0.0, 0.30),
                (0.0, 0.0),
            ):
                candidate = ShpPoint(light_x + offset_x, light_z + offset_z)
                if polygon.buffer(-0.08).covers(candidate) or (offset_x == 0 and offset_z == 0):
                    candidates.append(candidate)
            separation_points = reserved + positions + [(light_x, light_z)]
            best = max(
                candidates,
                key=lambda candidate: min(
                    math.hypot(candidate.x - other_x, candidate.y - other_z)
                    for other_x, other_z in separation_points
                ),
            )
            positions.append((float(best.x), float(best.y)))
        return positions

    def _hvac_mini_split(self, rooms, levels, floor_h, profile) -> List[MEPElement]:
        """One indoor head unit per bedroom/living area. Condenser on roof."""
        elements = []
        total_floors = len(levels)
        roof_y = total_floors * floor_h

        # Outdoor condenser units on roof — use weighted centroid so it stays inside footprint
        if rooms:
            roof_cx, roof_cz = self._central_hvac_position(rooms)
        else:
            roof_cx, roof_cz = 0.0, 0.0

        vertical_trade_keepouts: List[List[float]] = []
        ground_wet_rooms = [
            room for room in rooms
            if room.level == 0 and room.type in ("bathroom", "kitchen", "laundry")
        ]
        for wet_room in ground_wet_rooms[:2]:
            vertical_trade_keepouts.append(self._room_keepout(wet_room, "soil"))
        if ground_wet_rooms:
            for role in ("cold", "hot"):
                vertical_trade_keepouts.append(self._room_keepout(ground_wet_rooms[0], role))
        if rooms:
            fire_x, fire_z = self._mep_chase_position(rooms)
            electrical_x, electrical_z = self._central_hvac_position(rooms, role="electrical")
            vertical_trade_keepouts.extend((
                self._point_keepout(fire_x, fire_z, "fire"),
                self._point_keepout(electrical_x, electrical_z, "electrical"),
            ))

        elements.append(MEPElement(
            id="condenser_main",
            system="hvac",
            type="condenser_unit",
            start=[roof_cx, roof_y + 0.15, roof_cz],
            level=total_floors - 1,
            metadata={
                "heat_pump": bool(profile.get("heat_pump_hvac", True)),
                "seer2": 16.0, "hspf2": 8.5,
                "anchored": True, "service_clearance_in": 30,
            },
        ))

        elements.append(MEPElement(
            id="refrigerant_riser_main",
            system="hvac", type="refrigerant_riser",
            start=[roof_cx, 0.25, roof_cz],
            end=[roof_cx, roof_y, roof_cz],
            level=0, diameter_in=2.0,
            metadata={
                "network_id": "refrigerant", "insulated": True,
                "seismic_braced": True, "shared_chase": True,
            },
        ))

        for level in levels:
            lvl = level.index
            for room in rooms:
                if room.level != lvl:
                    continue
                if room.type not in (
                    "bedroom", "living", "family_room", "unit", "dining",
                    "kitchen", "office", "library", "gym", "media_room",
                    "bonus_room", "loft",
                ):
                    continue
                head_x, head_z = self._room_slot_away(
                    room, "hvac_supply", vertical_trade_keepouts
                )
                head_y = lvl * floor_h + ZONE["duct_supply"]
                # Wall-mount head on interior wall (0.1m from wall)
                elements.append(MEPElement(
                    id=f"ms_head_{uuid.uuid4().hex[:5]}",
                    system="hvac",
                    type="mini_split_head",
                    start=[head_x, head_y, head_z],
                    level=lvl,
                    width_in=30,
                    height_in=10,
                    metadata={
                        "room_id": room.id,
                        "capacity_cfm": max(50, round(room.area_sqft * 0.3)),
                        "heat_pump": bool(profile.get("heat_pump_hvac", True)),
                    },
                ))
                # Refrigerant line (slim — 1") up to roof condenser
                elements.append(MEPElement(
                    id=f"refrig_{uuid.uuid4().hex[:5]}",
                    system="hvac",
                    type="refrigerant_line",
                    start=[head_x, head_y, head_z],
                    end=[roof_cx, head_y, roof_cz],
                    level=lvl,
                    diameter_in=1.0,
                    metadata={
                        "room_id": room.id, "network_id": "refrigerant",
                        "insulated": True, "seismic_braced": True,
                        "shared_riser_id": "refrigerant_riser_main",
                        "_coordination_avoid_points": vertical_trade_keepouts,
                        "_coordination_clearance_m": 0.20,
                    },
                ))
        return elements

    def _hvac_central(self, rooms, levels, floor_h, profile) -> List[MEPElement]:
        """Central rooftop unit + main supply trunk + branch ducts to each room."""
        elements = []
        total_floors = len(levels)
        roof_y = total_floors * floor_h

        if not rooms:
            return elements
        # A dedicated service chase prevents the large vertical supply riser
        # from landing at a room centroid, where outlets and other trades tend
        # to be generated. The helper also keeps the chase within the common
        # footprint of stacked levels where one exists.
        bld_cx, bld_cz = self._central_hvac_position(rooms)
        vertical_trade_keepouts: List[List[float]] = []
        ground_wet_rooms = [
            room for room in rooms
            if room.level == 0 and room.type in ("bathroom", "kitchen", "laundry")
        ]
        for wet_room in ground_wet_rooms[:2]:
            vertical_trade_keepouts.append(self._room_keepout(wet_room, "soil"))
        if ground_wet_rooms:
            for role in ("cold", "hot"):
                vertical_trade_keepouts.append(self._room_keepout(ground_wet_rooms[0], role))
        fire_x, fire_z = self._mep_chase_position(rooms)
        electrical_x, electrical_z = self._central_hvac_position(rooms, role="electrical")
        vertical_trade_keepouts.extend((
            self._point_keepout(fire_x, fire_z, "fire"),
            self._point_keepout(electrical_x, electrical_z, "electrical"),
        ))

        # Rooftop unit
        elements.append(MEPElement(
            id="rtu_main",
            system="hvac",
            type="rooftop_unit",
            start=[bld_cx, roof_y + 0.2, bld_cz],
            level=total_floors - 1,
            width_in=48,
            height_in=36,
            metadata={
                "heat_pump": bool(profile.get("heat_pump_hvac", True)),
                "seer2": 16.0, "hspf2": 8.5,
                "anchored": True, "service_clearance_in": 30,
                "duct_r_value": 8, "duct_sealed": True,
            },
        ))

        for level in levels:
            lvl = level.index
            ceil_y = lvl * floor_h + ZONE["duct_supply"]
            ret_y  = lvl * floor_h + ZONE["duct_return"]

            # Vertical riser from this floor up to RTU on roof
            elements.append(MEPElement(
                id=f"hvac_riser_{lvl}",
                system="hvac", type="supply_riser",
                start=[bld_cx, lvl * floor_h + 0.1, bld_cz],
                end=[bld_cx, roof_y, bld_cz],
                level=lvl, diameter_in=16,
                metadata={
                    "network_id": "hvac_supply", "seismic_braced": True,
                    "duct_r_value": 8, "duct_sealed": True,
                },
            ))

            # Direct branch from riser to each room centroid — no spanning trunk
            for room in rooms:
                if room.level != lvl or room.type in ("stair",):
                    continue
                supply_x, supply_z = self._room_slot(room, "hvac_supply")
                return_x, return_z = self._room_slot(room, "hvac_return")
                room_area_m2 = room.area_sqft * 0.0929
                cfm = max(50, int(room_area_m2 * 10.764 *
                          CFM_PER_100SQFT.get(room.type, 20) / 100))
                bw, bh, _ = self._duct_size(cfm)

                elements.append(MEPElement(
                    id=f"hvac_branch_{uuid.uuid4().hex[:5]}",
                    system="hvac", type="supply_branch",
                    start=[bld_cx, ceil_y, bld_cz],
                    end=[supply_x, ceil_y, supply_z],
                    level=lvl, width_in=bw, height_in=bh,
                    metadata={
                        "room_id": room.id, "network_id": "hvac_supply",
                        "capacity_cfm": cfm, "duct_r_value": 8,
                        "duct_sealed": True, "seismic_braced": True,
                        "_coordination_avoid_points": vertical_trade_keepouts,
                        "_coordination_clearance_m": 0.32,
                    },
                ))
                elements.append(MEPElement(
                    id=f"diffuser_{uuid.uuid4().hex[:5]}",
                    system="hvac", type="supply_diffuser",
                    start=[supply_x, lvl * floor_h + ZONE["duct_supply"] - 0.07, supply_z],
                    level=lvl, width_in=bw, height_in=4,
                    metadata={"room_id": room.id, "capacity_cfm": cfm},
                ))
                # A complete central system needs a return/transfer path, not
                # only supply air.  Keep return branches in their own zone.
                elements.append(MEPElement(
                    id=f"return_{uuid.uuid4().hex[:5]}",
                    system="hvac", type="return_branch",
                    start=[return_x, ret_y, return_z], end=[bld_cx, ret_y, bld_cz],
                    level=lvl, width_in=max(8, bw), height_in=max(6, bh),
                    metadata={
                        "room_id": room.id, "network_id": "hvac_return",
                        "capacity_cfm": cfm, "duct_r_value": 8,
                        "duct_sealed": True, "seismic_braced": True,
                        "_coordination_avoid_points": vertical_trade_keepouts,
                        "_coordination_clearance_m": 0.32,
                    },
                ))
                elements.append(MEPElement(
                    id=f"return_grille_{uuid.uuid4().hex[:5]}",
                    system="hvac", type="return_grille",
                    start=[return_x, lvl * floor_h + ZONE["duct_return"] + 0.03, return_z],
                    level=lvl, width_in=max(8, bw), height_in=4,
                    metadata={"room_id": room.id, "capacity_cfm": cfm},
                ))

        return elements

    def _route_ventilation_and_exhaust(
        self, rooms, levels, floor_h: float, profile: Dict[str, Any]
    ) -> List[MEPElement]:
        elements: List[MEPElement] = []
        do_exhaust = bool(profile.get("exhaust_fans", True))
        do_whole_building = bool(profile.get("whole_building_ventilation", True))
        plumbing_keepouts: List[List[float]] = []
        ground_wet_rooms = [
            room for room in rooms
            if room.level == 0 and room.type in ("bathroom", "kitchen", "laundry")
        ]
        for wet_room in ground_wet_rooms[:2]:
            plumbing_keepouts.append(self._room_keepout(wet_room, "soil"))
        if ground_wet_rooms:
            for role in ("cold", "hot"):
                plumbing_keepouts.append(self._room_keepout(ground_wet_rooms[0], role))
        if rooms:
            fire_x, fire_z = self._mep_chase_position(rooms)
            electrical_x, electrical_z = self._central_hvac_position(rooms, role="electrical")
            plumbing_keepouts.extend((
                self._point_keepout(fire_x, fire_z, "fire"),
                self._point_keepout(electrical_x, electrical_z, "electrical"),
            ))
        for level in levels:
            lvl = level.index
            level_rooms = [r for r in rooms if r.level == lvl]
            if not level_rooms:
                continue
            fixture_y = lvl * floor_h + ZONE["ceil_light"] + 0.08
            plenum_y = lvl * floor_h + ZONE["duct_supply"]

            if do_whole_building:
                equipment_rooms = [
                    room for room in level_rooms
                    if room.type in ("mechanical", "utility", "laundry")
                ]
                equipment_room = equipment_rooms[0] if equipment_rooms else max(
                    level_rooms, key=lambda room: room.area_sqft
                )
                cx, cz = self._room_slot(equipment_room, "hvac_equipment")
                # Avoid double-counting MF unit shell rooms that overlap their
                # child rooms when estimating a preliminary outdoor-air rate.
                net_area = sum(r.area_sqft for r in level_rooms if r.type != "unit")
                if net_area <= 0:
                    net_area = sum(r.area_sqft for r in level_rooms)
                # Preliminary only: this area-factor is useful for selecting a
                # visible concept unit, but it is not the project ventilation
                # calculation.  Carry both sides of the comparison and an
                # explicit unverified marker so downstream compliance cannot
                # convert a generated estimate into proof of compliance.
                required_outdoor_cfm = max(30.0, round(net_area * 0.03, 1))
                supplied_actual_cfm = profile.get("actual_outdoor_air_cfm")
                try:
                    actual_outdoor_cfm = float(supplied_actual_cfm)
                    if actual_outdoor_cfm <= 0:
                        raise ValueError
                    actual_cfm_basis = "user_supplied_unverified"
                except (TypeError, ValueError):
                    actual_outdoor_cfm = required_outdoor_cfm
                    actual_cfm_basis = "conceptual_selected_capacity"
                supplied_reference = str(
                    profile.get("ventilation_calculation_reference") or ""
                ).strip()
                calculation_reference = supplied_reference or (
                    "conceptual area-factor prelayout; complete the applicable "
                    "2025 California residential ventilation calculation"
                )
                equipment_type = "erv" if profile.get("erv_hrv_required") else "whole_house_ventilator"
                elements.append(MEPElement(
                    id=f"ventilator_{lvl}", system="hvac", type=equipment_type,
                    start=[cx, plenum_y, cz], level=lvl, width_in=18, height_in=10,
                    metadata={
                        "outdoor_air_cfm": actual_outdoor_cfm,
                        "actual_outdoor_air_cfm": actual_outdoor_cfm,
                        "required_outdoor_air_cfm": required_outdoor_cfm,
                        "design_outdoor_air_cfm": actual_outdoor_cfm,
                        "actual_cfm_basis": actual_cfm_basis,
                        "ventilation_calculation_reference": calculation_reference,
                        "calculation_reference": calculation_reference,
                        "calculation_verified": False,
                        "evidence_status": "conceptual_unverified",
                        "requires_final_ventilation_calculation": True,
                        "concept_capacity_meets_estimated_requirement": (
                            actual_outdoor_cfm >= required_outdoor_cfm
                        ),
                        "level": lvl,
                        "duct_r_value": 8, "duct_sealed": True,
                        "anchored": True, "service_clearance_in": 30,
                    },
                ))

            if do_exhaust:
                for room in level_rooms:
                    if room.type not in ("bathroom", "kitchen", "laundry"):
                        continue
                    cx, cz = self._room_slot(room, "exhaust")
                    bds = self._bounds(room)
                    exhaust_cfm = 100 if room.type in ("kitchen", "laundry") else 50
                    fan_type = "range_hood" if room.type == "kitchen" else "exhaust_fan"
                    exhaust_reference = (
                        "conceptual local-exhaust prelayout; verify the applicable "
                        "2025 California mechanical/energy compliance path"
                    )
                    elements.append(MEPElement(
                        id=f"exhaust_{uuid.uuid4().hex[:5]}",
                        system="hvac", type=fan_type,
                        start=[cx, fixture_y, cz], level=lvl,
                        metadata={
                            "room_id": room.id, "capacity_cfm": exhaust_cfm,
                            "actual_exhaust_cfm": exhaust_cfm,
                            "required_exhaust_cfm": exhaust_cfm,
                            "calculation_reference": exhaust_reference,
                            "calculation_verified": False,
                            "evidence_status": "conceptual_unverified",
                            "terminates_outdoors": True,
                        },
                    ))
                    elements.append(MEPElement(
                        id=f"exhaust_duct_{uuid.uuid4().hex[:5]}",
                        system="hvac", type="exhaust_duct",
                        start=[cx, plenum_y, cz],
                        end=[bds[0] + 0.02, plenum_y, cz],
                        level=lvl, width_in=6, height_in=6,
                        metadata={
                            "room_id": room.id, "capacity_cfm": exhaust_cfm,
                            "actual_exhaust_cfm": exhaust_cfm,
                            "required_exhaust_cfm": exhaust_cfm,
                            "calculation_reference": exhaust_reference,
                            "calculation_verified": False,
                            "evidence_status": "conceptual_unverified",
                            "duct_r_value": 8, "duct_sealed": True,
                            "terminates_outdoors": True,
                            "_coordination_avoid_points": plumbing_keepouts,
                            "_coordination_clearance_m": 0.24,
                        },
                    ))
        return elements

    def _duct_size(self, cfm: int) -> Tuple[int, int, int]:
        """Returns (width_in, height_in, diameter_in)."""
        for max_cfm, w, h, d in DUCT_SIZES:
            if cfm <= max_cfm:
                return w, h, d
        return 20, 12, 20

    # ════════════════════════════════════════════════════════════════════════
    # ELECTRICAL (preliminary CEC-informed layout)
    # ════════════════════════════════════════════════════════════════════════

    def _route_electrical(
        self, rooms: List[Room], walls: List[Wall], levels: List[Level],
        floor_h: float, power_connection: dict, fine: dict, is_adu: bool = False,
    ) -> List[MEPElement]:
        """
        Code-informed preliminary residential electrical layout:
        - Service entry + main panel + sub-panels
        - Branch circuits sized by NEC 220.12
        - Outlets spaced ≤12ft (3.66m) per NEC 210.52
        - GFCI in wet areas, AFCI in bedrooms/living
        - Dedicated circuits for kitchen, laundry, bath
        - Light fixture at ceiling center of each room
        """
        elements: List[MEPElement] = []
        outlets_per_room = max(1, int(fine.get("outlets_per_room", 3)))
        do_alarms = bool(fine.get("fire_alarms", True))
        do_co = bool(fine.get("carbon_monoxide_detectors", True))
        specific_rooms = [r for r in rooms if r.type != "unit"] or rooms
        all_room_pts = [p for r in specific_rooms for p in r.polygon]
        if not all_room_pts:
            return elements

        # CO alarms are applicability-driven.  Utility availability is not an
        # installed fuel-fired source, so only a modeled garage or explicit
        # equipment/fuel selection triggers them.
        co_trigger_reasons: List[str] = []
        if any(room.type == "garage" for room in specific_rooms):
            co_trigger_reasons.append("garage")
        for flag in (
            "fuel_fired_equipment", "fuel_fired_appliance", "gas_appliance",
            "gas_range", "gas_furnace", "gas_fireplace",
        ):
            value = fine.get(flag)
            if value is True or str(value).strip().lower() in {"true", "yes", "installed"}:
                co_trigger_reasons.append(flag)
        for field in (
            "fuel_type", "heating_fuel", "hvac_fuel", "cooking_fuel",
            "water_heater_fuel", "water_heater_type",
        ):
            value = str(fine.get(field) or "").strip().lower().replace("-", "_")
            if value in {
                "gas", "natural_gas", "propane", "lp", "fuel_oil", "oil",
                "fuel_fired", "combustion",
            } or value.startswith(("gas_", "propane_", "fuel_fired_")):
                co_trigger_reasons.append(field)
        co_trigger_reasons = list(dict.fromkeys(co_trigger_reasons))
        co_required = do_co and bool(co_trigger_reasons)

        smoke_listing = {
            "hardwired": True,
            "battery_backup": True,
            "interconnected": True,
            "listed": True,
            "listing_standard": "UL 217",
            "power_source": "building_wiring_with_battery_backup",
        }
        co_listing = {
            "hardwired": True,
            "battery_backup": True,
            "interconnected": True,
            "listed": True,
            "listing_standard": "UL 2034",
            "power_source": "building_wiring_with_battery_backup",
        }

        footprint = unary_union([Polygon(r.polygon) for r in specific_rooms if r.polygon])
        if footprint.geom_type == "MultiPolygon":
            footprint = max(footprint.geoms, key=lambda p: p.area)
        building_point = footprint.representative_point()
        min_z = footprint.bounds[1]
        front_point = footprint.boundary.interpolate(
            footprint.boundary.project(ShpPoint(building_point.x, min_z))
        )
        panel_x, panel_z = self._central_hvac_position(
            specific_rooms, role="electrical"
        )

        # Reserve the deterministic vertical chases used by the earlier
        # plumbing, fire, and central-HVAC passes. Horizontal conduit branches
        # are bent around these points during final footprint routing.
        riser_keepouts: List[List[float]] = []
        ground_wet_rooms = [
            room for room in specific_rooms
            if room.level == 0 and room.type in ("bathroom", "kitchen", "laundry")
        ]
        for wet_room in ground_wet_rooms[:2]:
            riser_keepouts.append(self._room_keepout(wet_room, "soil"))
        if ground_wet_rooms:
            for role in ("cold", "hot"):
                riser_keepouts.append(self._room_keepout(ground_wet_rooms[0], role))
        if specific_rooms:
            fire_x, fire_z = self._mep_chase_position(specific_rooms)
            hvac_x, hvac_z = self._central_hvac_position(specific_rooms)
            riser_keepouts.extend((
                self._point_keepout(fire_x, fire_z, "fire"),
                # The 16-inch supply riser is much larger than a return-line
                # keep-out. Account for its full radius plus electrical trade
                # clearance when the visibility path bends around the chase.
                self._point_keepout(hvac_x, hvac_z, "hvac_supply"),
            ))
        alarm_chase_keepouts = [
            (float(point[0]), float(point[1]))
            for point in riser_keepouts if len(point) >= 2
        ]

        # Service sizing is preliminary until an NEC 220 load calculation is
        # completed.  Do not infer a separate ADU service from floor area alone.
        adu_service = str(fine.get("adu_electrical_service", "sub_panel_from_primary"))
        dedicated_adu_service = is_adu and adu_service == "dedicated_service"
        panel_type = "main_panel" if not is_adu or dedicated_adu_service else "sub_panel"
        panel_amps = int(fine.get("service_amps", 100 if is_adu else 200))
        elements.append(MEPElement(
            id="main_panel", system="electrical", type=panel_type,
            start=[panel_x, 1.2, panel_z], level=0,
            metadata={
                "amps": panel_amps,
                "adu_service": adu_service if is_adu else "standard",
                "load_calculation_required": True,
                "service_clearance_in": 30,
                "anchored": True,
            },
        ))
        elements.append(MEPElement(
            id="service_entry", system="electrical", type="service_conduit",
            start=[float(front_point.x), 1.2, float(front_point.y)],
            end=[panel_x, 1.2, panel_z], level=0, diameter_in=2.0,
            metadata={
                "network_id": "electrical_service", "bonded": True,
                "_coordination_avoid_points": riser_keepouts,
                "_coordination_clearance_m": 0.32,
            },
        ))

        if power_connection:
            pole_dx = float(power_connection.get("dx_m", 0.0))
            pole_dz = float(power_connection.get("dz_m", -8.0))
            distance = max(0.1, math.hypot(pole_dx, pole_dz))
            lateral_length = min(distance, 30.0)
            elements.append(MEPElement(
                id="service_mast", system="electrical", type="service_mast",
                start=[float(front_point.x), 1.2, float(front_point.y)],
                end=[float(front_point.x), 5.5, float(front_point.y)],
                level=0, diameter_in=2.0,
                metadata={
                    "allow_outside_footprint": True,
                    "network_id": "electrical_utility",
                    "bonded": True,
                },
            ))
            elements.append(MEPElement(
                id="utility_lateral", system="electrical", type="utility_lateral",
                start=[float(front_point.x), 5.5, float(front_point.y)],
                end=[
                    float(front_point.x + pole_dx / distance * lateral_length), 5.5,
                    float(front_point.y + pole_dz / distance * lateral_length),
                ],
                level=0, diameter_in=1.0,
                metadata={
                    "allow_outside_footprint": True,
                    "network_id": "electrical_utility",
                    "utility_coordination_required": True,
                },
            ))

        defined_circuits: set = set()

        def ensure_circuit(
            circuit_id: str, level_index: int, panel_position: Tuple[float, float],
            amps: int, purpose: str, *, gfci: bool = False, afci: bool = False,
            room_id: Optional[str] = None,
        ) -> None:
            if circuit_id in defined_circuits:
                return
            defined_circuits.add(circuit_id)
            elements.append(MEPElement(
                id=f"circuit_{circuit_id}", system="electrical", type="branch_circuit",
                start=[panel_position[0], level_index * floor_h + 1.25, panel_position[1]],
                level=level_index,
                metadata={
                    "circuit_id": circuit_id, "amps": amps, "poles": 1,
                    "amperage": amps, "purpose": purpose,
                    "circuit_type": purpose, "gfci": gfci, "afci": afci,
                    "breaker_type": "dual_function" if gfci and afci else (
                        "gfci" if gfci else "afci" if afci else "standard"
                    ),
                    "panel_id": "main_panel" if level_index == 0 else f"sub_panel_{level_index}",
                    "room_id": room_id, "copper_conductors": True,
                },
            ))

        previous_panel = (panel_x, panel_z)
        habitable_types = {
            "bedroom", "living", "family_room", "dining", "office",
            "library", "gym", "media_room", "bonus_room", "loft", "kitchen",
        }
        for level in levels:
            lvl = level.index
            floor_y = lvl * floor_h
            ceil_y_elec = floor_y + ZONE["ceil_elec"]
            ceil_y_light = floor_y + ZONE["ceil_light"]
            lvl_rooms = [r for r in specific_rooms if r.level == lvl]
            if not lvl_rooms:
                continue
            # Stack panels in a dedicated electrical chase so feeders are
            # vertical and cannot cut diagonally across intermediate floors.
            level_panel = (panel_x, panel_z)
            if lvl > 0:
                elements.append(MEPElement(
                    id=f"sub_panel_{lvl}", system="electrical", type="sub_panel",
                    start=[level_panel[0], floor_y + 1.2, level_panel[1]], level=lvl,
                    metadata={
                        "amps": min(panel_amps, 125), "service_clearance_in": 30,
                        "anchored": True, "load_calculation_required": True,
                    },
                ))
                elements.append(MEPElement(
                    id=f"feeder_{lvl}", system="electrical", type="feeder",
                    start=[previous_panel[0], (lvl - 1) * floor_h + 1.2, previous_panel[1]],
                    end=[level_panel[0], floor_y + 1.2, level_panel[1]],
                    level=lvl, diameter_in=1.5,
                    metadata={"network_id": "electrical_feeder", "level_served": lvl},
                ))
            previous_panel = level_panel

            lighting_circuit = f"lighting_l{lvl}"
            ensure_circuit(lighting_circuit, lvl, level_panel, 15, "lighting", afci=True)
            active_rooms = list(lvl_rooms)
            for room_index, room in enumerate(active_rooms):
                cx, cz = self._centroid(room)
                polygon = Polygon(room.polygon)
                if polygon.is_empty:
                    continue
                general_circuit = f"general_l{lvl}_{room_index // 5 + 1}"
                ensure_circuit(general_circuit, lvl, level_panel, 20, "general receptacles", afci=True)
                elements.append(MEPElement(
                    id=f"branch_{uuid.uuid4().hex[:5]}", system="electrical",
                    type="conduit_branch",
                    start=[level_panel[0], ceil_y_elec, level_panel[1]],
                    end=[cx, ceil_y_elec, cz], level=lvl, diameter_in=0.75,
                    metadata={
                        "room_id": room.id, "circuit_id": general_circuit,
                        "_coordination_avoid_points": riser_keepouts,
                        "_coordination_clearance_m": 0.32,
                    },
                ))

                # Provide one lighting point per ~215 ft² and keep it offset
                # from the sprinkler-grid point used by the fire system.
                for light_x, light_z in self._lighting_positions(room):
                    elements.append(MEPElement(
                        id=f"light_{uuid.uuid4().hex[:5]}", system="electrical",
                        type="lighting_point", start=[light_x, ceil_y_light, light_z], level=lvl,
                        metadata={"room_id": room.id, "circuit_id": lighting_circuit},
                    ))

                boundary = polygon.exterior
                inward_point = polygon.representative_point()
                perimeter = max(boundary.length, 0.1)
                if room.type in habitable_types:
                    outlet_count = max(outlets_per_room, math.ceil(perimeter / 3.6576))
                elif room.type in ("bathroom", "laundry", "garage", "utility", "mechanical"):
                    outlet_count = 1
                elif room.type in ("corridor", "hall", "hallway") and perimeter >= 3.0:
                    outlet_count = 1
                else:
                    outlet_count = 0
                outlet_count = min(outlet_count, 24)
                receptacle_positions: List[Tuple[float, float, bool, float, str]] = []
                perimeter_spacing_ft = round(
                    perimeter / outlet_count * 3.28084, 2
                ) if outlet_count else 0.0
                for outlet_index in range(outlet_count):
                    wall_point = boundary.interpolate(perimeter * (outlet_index + 0.5) / outlet_count)
                    move_x = inward_point.x - wall_point.x
                    move_z = inward_point.y - wall_point.y
                    move_length = max(math.hypot(move_x, move_z), 0.001)
                    receptacle_positions.append((
                        float(wall_point.x + move_x / move_length * 0.05),
                        float(wall_point.y + move_z / move_length * 0.05), False,
                        perimeter_spacing_ft, "room_perimeter_even_spacing",
                    ))

                # Kitchen counter wall-line spacing: no point is more than 24
                # inches from a receptacle.  The generated counter is capped at
                # 3.5 m, so three evenly spaced receptacles cover its full run.
                if room.type == "kitchen":
                    min_x, min_room_z, max_x, max_room_z = polygon.bounds
                    counter_length = min((max_room_z - min_room_z) * 0.75, 3.5)
                    counter_count = max(2, math.ceil(counter_length / 1.2192))
                    counter_spacing_ft = round(
                        counter_length / counter_count * 3.28084, 2
                    )
                    for counter_index in range(counter_count):
                        px = min_x + 0.06
                        pz = min_room_z + 0.3 + counter_length * (counter_index + 0.5) / counter_count
                        if polygon.buffer(0.01).covers(ShpPoint(px, pz)):
                            receptacle_positions.append((
                                px, pz, True, counter_spacing_ft,
                                "modeled_counter_run_even_spacing",
                            ))

                for outlet_index, (
                    outlet_x, outlet_z, countertop, design_spacing_ft, spacing_basis
                ) in enumerate(receptacle_positions):
                    is_wet = room.type in ("bathroom", "kitchen", "laundry", "garage")
                    if room.type == "kitchen":
                        circuit_id = f"kitchen_sabc_{room.id}_{outlet_index % 2 + 1}"
                        ensure_circuit(
                            circuit_id, lvl, level_panel, 20, "small_appliance",
                            gfci=True, afci=True, room_id=room.id,
                        )
                    elif room.type == "bathroom":
                        circuit_id = f"bath_{room.id}"
                        ensure_circuit(
                            circuit_id, lvl, level_panel, 20, "bathroom",
                            gfci=True, afci=True, room_id=room.id,
                        )
                    elif room.type == "laundry":
                        circuit_id = f"laundry_{room.id}"
                        ensure_circuit(
                            circuit_id, lvl, level_panel, 20, "laundry",
                            gfci=True, afci=True, room_id=room.id,
                        )
                    else:
                        circuit_id = general_circuit
                    elements.append(MEPElement(
                        id=f"outlet_{uuid.uuid4().hex[:5]}", system="electrical", type="outlet",
                        start=[outlet_x, floor_y + ZONE["outlet"], outlet_z], level=lvl,
                        metadata={
                            "room_id": room.id, "circuit_id": circuit_id,
                            "gfci": is_wet, "afci": room.type in habitable_types,
                            "tamper_resistant": True, "countertop": countertop,
                            "max_spacing_ft": 4 if countertop else 12,
                            "design_spacing_ft": design_spacing_ft,
                            "design_max_distance_to_receptacle_ft": round(
                                design_spacing_ft / 2.0, 2
                            ),
                            "spacing_basis": spacing_basis,
                            "geometry_derived": True,
                            "room_perimeter_ft": round(perimeter * 3.28084, 2),
                        },
                    ))
                    elements.append(MEPElement(
                        id=f"conduit_drop_{uuid.uuid4().hex[:5]}", system="electrical",
                        type="conduit_branch",
                        start=[outlet_x, ceil_y_elec, outlet_z],
                        end=[outlet_x, floor_y + ZONE["outlet"] + 0.05, outlet_z],
                        level=lvl, diameter_in=0.5,
                        metadata={"room_id": room.id, "circuit_id": circuit_id},
                    ))

                switch_point = boundary.interpolate(min(0.45, perimeter * 0.1))
                sx = switch_point.x + (inward_point.x - switch_point.x) * 0.08
                sz = switch_point.y + (inward_point.y - switch_point.y) * 0.08
                elements.append(MEPElement(
                    id=f"switch_{uuid.uuid4().hex[:5]}", system="electrical", type="light_switch",
                    start=[float(sx), floor_y + ZONE["switch"], float(sz)], level=lvl,
                    metadata={
                        "room_id": room.id, "circuit_id": lighting_circuit,
                        "controls_room_lighting": True,
                    },
                ))

                if do_alarms and room.type == "bedroom":
                    alarm_x, alarm_z = self._room_slot_away(
                        room, "alarm", alarm_chase_keepouts
                    )
                    elements.append(MEPElement(
                        id=f"smoke_{uuid.uuid4().hex[:5]}", system="electrical", type="smoke_alarm",
                        start=[alarm_x, ceil_y_light + 0.02, alarm_z],
                        level=lvl,
                        metadata={
                            **smoke_listing,
                            "room_id": room.id,
                            "detector": "smoke",
                            "location_basis": "inside_sleeping_room",
                            "inside_sleeping_room": True,
                            "sleeping_zone_id": room.unit_id or f"level_{lvl}",
                        },
                    ))

            # Produce distinct outside-sleeping-area evidence for every modeled
            # sleeping zone (normally a dwelling unit) on the level.  If there
            # are no bedrooms, retain one story smoke alarm as separate story
            # coverage evidence.
            bedrooms = [room for room in lvl_rooms if room.type == "bedroom"]
            sleeping_zones: Dict[str, List[Room]] = {}
            for bedroom in bedrooms:
                zone_id = bedroom.unit_id or f"level_{lvl}"
                sleeping_zones.setdefault(zone_id, []).append(bedroom)
            if not sleeping_zones:
                sleeping_zones[f"level_{lvl}_no_sleeping_rooms"] = []

            used_safety_points: List[Tuple[float, float]] = list(
                alarm_chase_keepouts
            )
            for zone_id, zone_bedrooms in sleeping_zones.items():
                unit_id = zone_bedrooms[0].unit_id if zone_bedrooms else None
                circulation_rooms = [
                    room for room in lvl_rooms
                    if room.type in ("corridor", "hall", "hallway")
                    and (unit_id is None or room.unit_id in (None, unit_id))
                ]
                non_sleeping_rooms = [
                    room for room in lvl_rooms
                    if room.type != "bedroom"
                    and (unit_id is None or room.unit_id in (None, unit_id))
                ]
                safety_room = (
                    circulation_rooms[0]
                    if circulation_rooms
                    else max(non_sleeping_rooms or lvl_rooms, key=lambda room: room.area_sqft)
                )
                safety_x, safety_z = self._room_slot_away(
                    safety_room, "alarm_outside", used_safety_points
                )
                used_safety_points.append((safety_x, safety_z))
                zone_metadata = {
                    "sleeping_zone_id": zone_id,
                    "unit_id": unit_id,
                    "level_served": lvl,
                    "room_id": safety_room.id,
                    "location_room_id": safety_room.id,
                    "sleeping_room_ids": [room.id for room in zone_bedrooms],
                    "outside_sleeping_area": bool(zone_bedrooms),
                }
                if do_alarms:
                    elements.append(MEPElement(
                        id=f"outside_smoke_{uuid.uuid4().hex[:5]}",
                        system="electrical", type="smoke_alarm",
                        start=[safety_x, ceil_y_light + 0.02, safety_z], level=lvl,
                        metadata={
                            **smoke_listing,
                            **zone_metadata,
                            "detector": "smoke",
                            "location_basis": (
                                "outside_sleeping_area"
                                if zone_bedrooms else "story_without_sleeping_rooms"
                            ),
                            "story_coverage": True,
                        },
                    ))
                if co_required:
                    co_x, co_z = self._room_slot_away(
                        safety_room, "co_alarm", used_safety_points
                    )
                    used_safety_points.append((co_x, co_z))
                    elements.append(MEPElement(
                        id=f"co_alarm_{uuid.uuid4().hex[:5]}",
                        system="electrical", type="carbon_monoxide_alarm",
                        start=[co_x, floor_y + 1.5, co_z], level=lvl,
                        metadata={
                            **co_listing,
                            **zone_metadata,
                            "detector": "carbon_monoxide",
                            "location_basis": (
                                "outside_sleeping_area"
                                if zone_bedrooms else "applicable_story"
                            ),
                            "applicability_triggers": co_trigger_reasons,
                        },
                    ))

        if fine.get("ev_charging"):
            garages = [r for r in specific_rooms if r.type == "garage" and r.level == 0]
            if garages:
                gx, gz = self._centroid(garages[0])
                ensure_circuit("evse", 0, (panel_x, panel_z), 50, "EV charging", gfci=True)
                elements.append(MEPElement(
                    id="evse", system="electrical", type="ev_charger",
                    start=[gx, 1.2, gz], level=0,
                    metadata={"circuit_id": "evse", "amps": 40, "gfci": True},
                ))

                # Garage-specific electrical (NEC 210.52, CEC Title 24)
                if room.type == "garage":
                    # 240V EVSE circuit (NEC 625 / CEC 625.40 — required by CA since 2023)
                    elements.append(MEPElement(
                        id=f"ev_circuit_{uuid.uuid4().hex[:5]}",
                        system="electrical", type="ev_charger_circuit",
                        start=[bds[0]+0.3, floor_y+0.5, bds[1]+0.3],
                        level=lvl,
                    ))
                    # Garage door opener ceiling outlet (NEC 210.52(G)(1))
                    ctr_x = (bds[0] + bds[2]) / 2 if len(bds) >= 3 else bds[0] + 1.5
                    ctr_z = (bds[1] + bds[3]) / 2 if len(bds) >= 4 else bds[1] + 1.5
                    elements.append(MEPElement(
                        id=f"gdo_outlet_{uuid.uuid4().hex[:5]}",
                        system="electrical", type="ceiling_outlet",
                        start=[ctr_x, floor_y + floor_h - 0.15, ctr_z],
                        level=lvl,
                    ))
                    # Wall outlets every 6 ft along garage perimeter (NEC 210.52(G)(2))
                    garage_span_ft = max(bds[2]-bds[0] if len(bds) >= 3 else 3.0, 0.1) * 3.281
                    n_wall_outlets = max(1, int(garage_span_ft / 6))
                    step = (bds[2]-bds[0]) / (n_wall_outlets + 1) if len(bds) >= 3 else 1.0
                    for oi in range(n_wall_outlets):
                        ox = bds[0] + step * (oi + 1)
                        elements.append(MEPElement(
                            id=f"garage_outlet_{uuid.uuid4().hex[:5]}",
                            system="electrical", type="outlet",
                            start=[ox, floor_y + ZONE["outlet"], bds[1] + 0.05],
                            level=lvl,
                        ))

        return elements

    # ════════════════════════════════════════════════════════════════════════
    # FURNITURE (placed as fixtures layer items)
    # ════════════════════════════════════════════════════════════════════════

    def _place_furniture(
        self, rooms: List[Room], levels: List[Level], floor_h: float
    ) -> List[MEPElement]:
        """
        Place furniture in rooms. Uses system='fixtures' so they appear
        on the fixtures layer in the 3D viewer.
        """
        elements = []
        for room in rooms:
            bds = self._bounds(room)
            cx, cz = self._centroid(room)
            floor_y = room.level * floor_h
            w = bds[2] - bds[0]
            d = bds[3] - bds[1]
            area_m2 = w * d

            rtype = room.type

            if rtype == "living":
                # Sofa along rear wall
                elements.append(MEPElement(
                    id=f"sofa_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="sofa",
                    start=[cx, floor_y + 0.01, bds[3] - 0.55],
                    level=room.level, width_in=84, height_in=28,
                ))
                # Coffee table
                elements.append(MEPElement(
                    id=f"coffee_table_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="coffee_table",
                    start=[cx, floor_y + 0.01, bds[3] - 1.6],
                    level=room.level, width_in=48, height_in=18,
                ))
                # TV unit on front wall
                elements.append(MEPElement(
                    id=f"tv_unit_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="tv_unit",
                    start=[cx, floor_y + 0.01, bds[1] + 0.25],
                    level=room.level, width_in=60, height_in=22,
                ))

            elif rtype == "family_room":
                elements.append(MEPElement(
                    id=f"sofa_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="sofa",
                    start=[cx, floor_y + 0.01, bds[3] - 0.55],
                    level=room.level, width_in=96, height_in=28,
                ))
                elements.append(MEPElement(
                    id=f"coffee_table_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="coffee_table",
                    start=[cx, floor_y + 0.01, bds[3] - 1.7],
                    level=room.level, width_in=52, height_in=18,
                ))

            elif rtype == "kitchen":
                counter_len = min(w * 0.75, 3.5)
                # Main counter along left wall
                elements.append(MEPElement(
                    id=f"counter_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="counter",
                    start=[bds[0] + 0.3, floor_y + 0.01, bds[1] + 0.3],
                    end=[bds[0] + 0.3, floor_y + 0.01, bds[1] + 0.3 + counter_len],
                    level=room.level, width_in=24, height_in=36,
                ))
                # Stove next to counter
                elements.append(MEPElement(
                    id=f"stove_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="stove",
                    start=[bds[0] + 0.3, floor_y + 0.01, bds[1] + 0.3],
                    level=room.level, width_in=30, height_in=36,
                ))
                # Refrigerator at corner
                elements.append(MEPElement(
                    id=f"fridge_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="refrigerator",
                    start=[bds[2] - 0.45, floor_y + 0.01, bds[1] + 0.35],
                    level=room.level, width_in=30, height_in=68,
                ))
                # Kitchen island if room is large enough (>10 m²)
                if area_m2 > 10.0:
                    elements.append(MEPElement(
                        id=f"island_{uuid.uuid4().hex[:5]}",
                        system="fixtures", type="kitchen_island",
                        start=[cx, floor_y + 0.01, cz],
                        level=room.level, width_in=48, height_in=36,
                    ))

            elif rtype == "dining":
                elements.append(MEPElement(
                    id=f"dining_table_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="dining_table",
                    start=[cx, floor_y + 0.01, cz],
                    level=room.level, width_in=72, height_in=30,
                ))

            elif rtype == "bedroom":
                is_master = area_m2 > 16.0
                # Bed (king for master, queen for others)
                elements.append(MEPElement(
                    id=f"bed_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="bed",
                    start=[cx, floor_y + 0.01, bds[3] - 1.1],
                    level=room.level,
                    width_in=76 if is_master else 60,
                    height_in=14,
                ))
                # Dresser
                if area_m2 > 10.0:
                    elements.append(MEPElement(
                        id=f"dresser_{uuid.uuid4().hex[:5]}",
                        system="fixtures", type="dresser",
                        start=[bds[0] + 0.25, floor_y + 0.01, bds[1] + 0.3],
                        level=room.level, width_in=48, height_in=48,
                    ))

            elif rtype == "office":
                elements.append(MEPElement(
                    id=f"desk_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="desk",
                    start=[bds[0] + 0.35, floor_y + 0.01, bds[1] + 0.45],
                    level=room.level, width_in=60, height_in=30,
                ))
                elements.append(MEPElement(
                    id=f"bookshelf_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="bookshelf",
                    start=[bds[2] - 0.25, floor_y + 0.01, cz],
                    level=room.level, width_in=36, height_in=72,
                ))

            elif rtype == "laundry":
                elements.append(MEPElement(
                    id=f"washer_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="washer",
                    start=[bds[0] + 0.35, floor_y + 0.01, bds[1] + 0.35],
                    level=room.level, width_in=27, height_in=43,
                ))
                elements.append(MEPElement(
                    id=f"dryer_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="dryer",
                    start=[bds[0] + 1.1, floor_y + 0.01, bds[1] + 0.35],
                    level=room.level, width_in=27, height_in=43,
                ))

            elif rtype in ("media_room", "bonus_room"):
                elements.append(MEPElement(
                    id=f"sofa_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="sofa",
                    start=[cx, floor_y + 0.01, cz + 0.3],
                    level=room.level, width_in=90, height_in=28,
                ))
                elements.append(MEPElement(
                    id=f"tv_unit_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="tv_unit",
                    start=[cx, floor_y + 0.01, bds[1] + 0.3],
                    level=room.level, width_in=72, height_in=24,
                ))

            elif rtype == "loft":
                elements.append(MEPElement(
                    id=f"sofa_{uuid.uuid4().hex[:5]}",
                    system="fixtures", type="sofa",
                    start=[cx, floor_y + 0.01, cz],
                    level=room.level, width_in=84, height_in=28,
                ))

        return elements

    # ── ADU-specific routing ──────────────────────────────────────────────

    def _adu_sewer_lateral(self, rooms: List[Room], walls: List[Wall]) -> List[MEPElement]:
        """
        ADU sewer lateral: exits the ADU and connects to the primary home's existing sewer.
        Uses a conservative notional 2.1% slope. Final size, material, route,
        invert elevation, and slope require adopted CPC and utility review.
        """
        elements = []
        all_pts = [p for r in rooms for p in r.polygon]
        if not all_pts:
            return elements

        # Exit from rear of ADU (max Z = away from street) — typical CA backyard ADU routing
        min_x = min(p[0] for p in all_pts)
        max_x = max(p[0] for p in all_pts)
        max_z = max(p[1] for p in all_pts)
        cx = (min_x + max_x) / 2

        # Lateral exits building at sub-slab level (-0.30m) and runs toward primary house
        # Assume primary home sewer is ~25ft (7.6m) behind the ADU rear wall
        lateral_run_m = 7.6
        slope = 0.021     # 1/4" per foot = 2.1% — just above IPC minimum
        drop = lateral_run_m * slope

        elements.append(MEPElement(
            id="adu_sewer_lateral",
            system="plumbing",
            type="sewer_lateral",
            start=[cx, -0.30, max_z],
            end=[cx, -0.30 - drop, max_z + lateral_run_m],
            level=0,
            diameter_in=4.0,
            metadata={
                "slope_pct": round(slope * 100, 1),
                "run_ft": round(lateral_run_m * 3.281, 1),
                "note": "Ties into primary home sewer — verify invert elevation before permit",
            },
        ))
        return elements

    # ── Geometry helpers ──────────────────────────────────────────────────

    def _central_hvac_position(
        self, rooms: List[Room], role: str = "hvac_equipment"
    ) -> Tuple[float, float]:
        """Choose a contained, trade-specific chase shared by stacked floors."""
        if not rooms:
            return 0.0, 0.0
        lowest_level = min(room.level for room in rooms)
        ground_rooms = [room for room in rooms if room.level == lowest_level]
        priority = {
            "mechanical": 0, "utility": 1, "laundry": 2,
            "garage": 3, "corridor": 4, "hall": 4, "hallway": 4,
        }
        service_room = min(
            ground_rooms,
            key=lambda room: (priority.get(room.type, 10), -room.area_sqft, room.id),
        )
        desired = self._room_slot(service_room, role)

        level_footprints = []
        for level_index in sorted({room.level for room in rooms}):
            polygons = [
                Polygon(room.polygon)
                for room in rooms
                if room.level == level_index and len(room.polygon) >= 3
            ]
            if polygons:
                level_footprints.append(unary_union(polygons))
        if not level_footprints:
            return desired
        common = level_footprints[0]
        for level_footprint in level_footprints[1:]:
            common = common.intersection(level_footprint)
        if common.is_empty:
            return desired
        if common.geom_type == "MultiPolygon":
            common = max(common.geoms, key=lambda polygon: polygon.area)
        elif common.geom_type == "GeometryCollection":
            polygons = [geometry for geometry in common.geoms if geometry.geom_type == "Polygon"]
            if not polygons:
                return desired
            common = max(polygons, key=lambda polygon: polygon.area)
        usable = common.buffer(-0.18, join_style=2)
        if usable.is_empty:
            usable = common
        desired_point = ShpPoint(desired)
        if usable.covers(desired_point):
            return desired
        min_x, min_z, max_x, max_z = usable.bounds
        fallback_fraction = (0.82, 0.55) if role == "electrical" else (0.70, 0.30)
        offset_candidate = ShpPoint(
            min_x + (max_x - min_x) * fallback_fraction[0],
            min_z + (max_z - min_z) * fallback_fraction[1],
        )
        chosen = offset_candidate if usable.covers(offset_candidate) else usable.representative_point()
        return float(chosen.x), float(chosen.y)

    def _room_slot(self, room: Room, role: str) -> Tuple[float, float]:
        """Return a deterministic, contained service point for one trade role.

        Reusing the room centroid for every system creates real riser and
        terminal collisions.  Fractional slots keep trades separated while an
        inward fallback keeps points valid for concave and narrow rooms.
        """
        fractions = {
            "fire": (0.18, 0.18),
            "soil": (0.18, 0.48),
            "cold": (0.18, 0.68),
            "hot": (0.18, 0.84),
            "equipment": (0.82, 0.18),
            "plumbing_terminal": (0.30, 0.38),
            "hvac_supply": (0.72, 0.68),
            "hvac_return": (0.30, 0.70),
            "hvac_equipment": (0.70, 0.30),
            "exhaust": (0.70, 0.35),
            "lighting": (0.30, 0.30),
            "alarm": (0.52, 0.72),
            "alarm_outside": (0.42, 0.72),
            "co_alarm": (0.68, 0.72),
            "electrical": (0.84, 0.52),
            "fixture_toilet": (0.22, 0.22),
            "fixture_sink": (0.72, 0.22),
            "fixture_shower": (0.72, 0.78),
            "fixture_kitchen_sink": (0.22, 0.78),
            "fixture_laundry": (0.22, 0.30),
        }
        polygon = Polygon(room.polygon)
        if polygon.is_empty or not polygon.is_valid:
            return self._centroid(room)
        min_x, min_z, max_x, max_z = polygon.bounds
        fraction_x, fraction_z = fractions.get(role, (0.5, 0.5))
        target = ShpPoint(
            min_x + (max_x - min_x) * fraction_x,
            min_z + (max_z - min_z) * fraction_z,
        )
        inner = polygon.buffer(-0.12, join_style=2)
        allowed = inner if not inner.is_empty else polygon
        if allowed.covers(target):
            return float(target.x), float(target.y)
        representative = allowed.representative_point()
        # Walk toward the guaranteed interior point; this preserves as much of
        # the role-specific offset as the actual room shape permits.
        for step in range(1, 11):
            ratio = step / 10.0
            candidate = ShpPoint(
                target.x + (representative.x - target.x) * ratio,
                target.y + (representative.y - target.y) * ratio,
            )
            if allowed.covers(candidate):
                return float(candidate.x), float(candidate.y)
        return float(representative.x), float(representative.y)

    def _fixture_xyz(self, room: Room, role: str, elevation: float) -> List[float]:
        """Return an ``[x, y, z]`` fixture point contained by its room polygon."""
        x, z = self._room_slot(room, role)
        return [x, elevation, z]

    def _room_slot_away(
        self, room: Room, role: str, avoid_points: Sequence[Sequence[float]]
    ) -> Tuple[float, float]:
        """Choose a contained room slot with maximum distance from vertical chases."""
        polygon = Polygon(room.polygon)
        if polygon.is_empty or not polygon.is_valid:
            return self._room_slot(room, role)
        inner = polygon.buffer(-0.12, join_style=2)
        allowed = inner if not inner.is_empty else polygon
        min_x, min_z, max_x, max_z = allowed.bounds
        preferred = self._room_slot(room, role)
        candidates = [ShpPoint(preferred)]
        for fraction_x in (0.15, 0.30, 0.50, 0.70, 0.85):
            for fraction_z in (0.15, 0.30, 0.50, 0.70, 0.85):
                candidate = ShpPoint(
                    min_x + (max_x - min_x) * fraction_x,
                    min_z + (max_z - min_z) * fraction_z,
                )
                if allowed.covers(candidate):
                    candidates.append(candidate)
        coordinates = [
            (float(point[0]), float(point[1]))
            for point in avoid_points if len(point) >= 2
        ]
        if not coordinates:
            return preferred
        chosen = max(
            candidates,
            key=lambda candidate: (
                min(math.hypot(candidate.x - x, candidate.y - z) for x, z in coordinates),
                -math.hypot(candidate.x - preferred[0], candidate.y - preferred[1]),
            ),
        )
        return float(chosen.x), float(chosen.y)

    def _room_keepout(
        self, room: Room, role: str, radius_m: Optional[float] = None
    ) -> List[float]:
        x, z = self._room_slot(room, role)
        return [x, z, radius_m or ROLE_KEEP_OUT_M.get(role, 0.20)]

    def _point_keepout(
        self, x: float, z: float, role: str, radius_m: Optional[float] = None
    ) -> List[float]:
        return [x, z, radius_m or ROLE_KEEP_OUT_M.get(role, 0.20)]

    def _centroid(self, room: Room) -> Tuple[float, float]:
        pts = room.polygon
        if not pts:
            return 0.0, 0.0
        try:
            polygon = Polygon(pts)
            point = polygon.representative_point()
            return float(point.x), float(point.y)
        except Exception:
            return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)

    def _bounds(self, room: Room) -> Tuple[float, float, float, float]:
        pts = room.polygon
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def _building_centroid(self, rooms: List[Room]) -> Tuple[float, float]:
        """Return a guaranteed interior point for L/U/stepped floorplates."""
        try:
            specific_rooms = [r for r in rooms if r.type != "unit"] or rooms
            merged = unary_union([Polygon(r.polygon) for r in specific_rooms if r.polygon])
            if not merged.is_empty:
                if merged.geom_type == "MultiPolygon":
                    merged = max(merged.geoms, key=lambda p: p.area)
                point = merged.representative_point()
                return float(point.x), float(point.y)
        except Exception:
            pass
        return self._centroid(rooms[0]) if rooms else (0.0, 0.0)

    def _mep_chase_position(self, rooms: List[Room]) -> Tuple[float, float]:
        """Best position for a vertical MEP riser/stack.

        Priority:
          1. Utility / mechanical / laundry room — dedicated service space.
          2. Corridor — wide enough for a wall chase without blocking egress.
          3. Kitchen or bathroom on the ground floor — wet-wall alignment.
          4. Building centroid of all non-stair rooms.

        Stairwells are explicitly excluded: they are open voids and often
        fire-rated enclosures — MEP cannot pass through them.
        """
        CHASE_PREFERRED = ("utility", "mechanical", "laundry")
        CHASE_OK        = ("corridor", "hall", "hallway")
        CHASE_WET       = ("kitchen", "bathroom")

        non_stair = [r for r in rooms if r.type != "stair"]
        if not non_stair:
            return 0.0, 0.0

        for preferred in (CHASE_PREFERRED, CHASE_OK, CHASE_WET):
            candidates = [r for r in non_stair if r.type in preferred and r.level == 0]
            if not candidates:
                candidates = [r for r in non_stair if r.type in preferred]
            if candidates:
                return self._room_slot(candidates[0], "fire")

        return self._room_slot(non_stair[0], "fire")
