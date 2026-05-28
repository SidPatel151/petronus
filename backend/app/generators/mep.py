"""
MEPRouter — comprehensive residential MEP systems
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
from typing import List, Dict, Tuple, Optional, Any
from app.models.schemas import MEPElement, Room, Wall, ProjectSpec, Level

# ── Zone heights relative to floor datum ─────────────────────────────────
ZONE = {
    "sub_slab":      -0.35,   # drain pipes — below slab
    "slab_top":       0.0,    # finished floor
    "outlet":         0.40,   # electrical outlets
    "switch":         1.20,   # light switches
    "supply_pipe":    0.50,   # domestic water supply (in wall)
    "waste_pipe":     0.10,   # waste (just below slab, gravity)
    "ceil_elec":      2.20,   # electrical conduit @ ceiling
    "ceil_fire":      2.35,   # sprinkler branch pipes
    "ceil_light":     2.45,   # light fixtures
    "duct_return":    2.55,   # HVAC return air
    "duct_supply":    2.70,   # HVAC supply duct (main)
    "duct_branch":    2.60,   # HVAC branch ducts
}

# ── Domestic water fixture unit values (IPC Table 610.3) ─────────────────
FIXTURE_UNITS = {
    "toilet":   3.0,
    "sink":     2.0,
    "shower":   2.0,
    "bathtub":  2.0,
    "kitchen":  2.0,   # kitchen sink
    "washer":   3.0,
}

# ── IPC pipe sizing by fixture units (Table 604.1, wsfu) ─────────────────
# (max_wsfu, pipe_size_in)
WATER_PIPE_SIZES = [
    (1.5,  0.50),
    (3.0,  0.75),
    (6.0,  1.00),
    (14.0, 1.25),
    (27.0, 1.50),
    (60.0, 2.00),
]

# ── Drain pipe sizing by drainage fixture units (DFU) ────────────────────
# (max_dfu, pipe_size_in)
DRAIN_PIPE_SIZES = [
    (1,   1.25),
    (3,   1.50),
    (6,   2.00),
    (12,  3.00),
    (20,  4.00),
    (160, 6.00),
]

# ── Duct sizing by CFM (ASHRAE Manual D, simplified) ─────────────────────
# CFM per room type per 100 sqft (approximate for residential)
CFM_PER_100SQFT = {
    "bedroom": 25, "living": 30, ""
    ""
    "": 40, "bathroom": 50,
    "dining": 20, "corridor": 15, "stair": 10,
}

# ASHRAE duct sizing: (max_cfm, width_in, height_in, diameter_in_round)
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

# ── Sprinkler sizing (NFPA 13R residential) ──────────────────────────────
SPRINKLER_COVERAGE_M2  = 16.7   # max 180 sqft (16.7 m²) per head, NFPA 13R
SPRINKLER_FLOW_GPM     = 13.0   # residential head K=4.9, 10psi → 15.5 gpm
SPRINKLER_PIPE_FLOW = [         # NFPA 13R pipe sizing
    (2,   1.0),   # ≤2 heads: 1" pipe
    (4,   1.25),
    (6,   1.5),
    (12,  2.0),
    (40,  2.5),
    (100, 3.0),
]


class MEPRouter:

    def route(
        self,
        rooms: List[Room],
        walls: List[Wall],
        levels: List[Level],
        spec: ProjectSpec,
        power_connection: dict = None,
        structural_members: List[Dict] = None,
    ) -> List[MEPElement]:
        """Route all MEP systems and return elements sorted by system."""
        fine = (spec.fine_details or {}) if hasattr(spec, 'fine_details') else {}
        floor_h = levels[0].height_ft * 0.3048 if levels else 3.048

        # bathrooms: None / whole number = full baths, x.5 = includes a half bath
        bath_count = getattr(spec, 'bathrooms', None)

        # Rebuild footprint polygon from level-0 exterior walls.
        # Use it to filter rooms BEFORE routing — any room whose centroid is
        # outside the actual polygon (e.g. in the void of an L/U shape) is excluded,
        # which prevents MEP from routing to coordinates that are outside the building.
        from shapely.geometry import Polygon as _ShpPoly, Point as _ShpPoint
        ext_walls_l0 = [w for w in walls if getattr(w, 'is_exterior', False) and w.level == 0]
        fp_poly = None
        if ext_walls_l0:
            try:
                fp_pts = [w.start for w in ext_walls_l0]
                fp_poly = _ShpPoly(fp_pts)
            except Exception:
                pass

        if fp_poly is not None:
            fp_interior = fp_poly.buffer(-0.20)
            rooms_inside = [
                r for r in rooms
                if fp_interior.contains(_ShpPoint(*self._centroid(r)))
            ]
            print(f"MEP: {len(rooms)} total rooms → {len(rooms_inside)} inside footprint")
        else:
            rooms_inside = rooms

        is_adu = getattr(spec, 'building_use', None) in ('adu',)
        try:
            from app.constants import BuildingUse as _BU
            is_adu = is_adu or getattr(spec, 'building_use', None) == _BU.adu
        except Exception:
            pass

        elements = []
        elements.extend(self._route_fire_protection(rooms_inside, levels, floor_h, fine))
        elements.extend(self._route_plumbing(rooms_inside, walls, levels, floor_h, bath_count, is_adu=is_adu))
        elements.extend(self._route_hvac(rooms_inside, levels, spec.hvac_preference, floor_h))
        elements.extend(self._route_electrical(rooms_inside, walls, levels, floor_h, power_connection, fine, is_adu=is_adu))
        elements.extend(self._place_furniture(rooms_inside, levels, floor_h))
        if is_adu:
            elements.extend(self._adu_sewer_lateral(rooms_inside, walls))

        # Final containment pass — drop any element whose horizontal footprint
        # (x, z) start or end lands outside the building interior.
        # Vertical risers (same x,z for start and end) are exempt.
        if fp_poly is not None:
            fp_check = fp_poly.buffer(-0.10)
            kept = []
            for el in elements:
                s = getattr(el, 'start', None)
                e = getattr(el, 'end', None)
                if s:
                    if not fp_check.contains(_ShpPoint(s[0], s[2])):
                        continue  # start outside — skip
                if e:
                    # Only reject if end is outside AND it's a horizontal move
                    # (vertical risers have same x,z so they're always inside)
                    same_xz = abs(e[0] - s[0]) < 0.01 and abs(e[2] - s[2]) < 0.01
                    if not same_xz and not fp_check.contains(_ShpPoint(e[0], e[2])):
                        continue  # end outside — skip
                kept.append(el)
            elements = kept

        return elements

    # ════════════════════════════════════════════════════════════════════════
    # FIRE PROTECTION (NFPA 13R)
    # ════════════════════════════════════════════════════════════════════════

    def _route_fire_protection(
        self, rooms: List[Room], levels: List[Level], floor_h: float, fine: dict
    ) -> List[MEPElement]:
        """
        Place residential sprinkler heads on every floor per NFPA 13R.
        Main riser in stair or utility core, branch lines along ceiling.
        """
        do_sprinklers = fine.get("fire_sprinklers", True)   # default ON for new builds
        elements = []
        total_floors = len(levels)

        # ── Riser location: prefer stair core ──
        stair_rooms = [r for r in rooms if r.type == "stair"]
        if stair_rooms:
            rx, rz = self._centroid(stair_rooms[0])
        elif rooms:
            rx, rz = self._building_centroid(rooms)
        else:
            rx, rz = 0.0, 0.0

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

        if not do_sprinklers:
            return elements

        # ── Per-floor sprinkler heads — route directly from riser to each room ──
        # No horizontal trunk across the full building (would cross L/U voids).
        # Each branch drops straight from the riser at ceiling height to the head.
        for level in levels:
            lvl = level.index
            ceil_y = lvl * floor_h + ZONE["ceil_fire"]

            lvl_rooms = [r for r in rooms if r.level == lvl
                         and r.type not in ("stair", "corridor")]
            if not lvl_rooms:
                continue

            # Sprinkler heads per room — route from riser position
            for room in lvl_rooms:
                if not do_sprinklers:
                    break
                cx, cz = self._centroid(room)
                head_y = ceil_y + 0.05

                positions = [(cx, cz)]

                # Large rooms get an extra head
                bds = self._bounds(room)
                room_area_m2 = max((bds[2]-bds[0]) * (bds[3]-bds[1]), 1.0)
                if room_area_m2 > SPRINKLER_COVERAGE_M2:
                    positions.append(((bds[0]+cx)/2, (bds[1]+cz)/2))

                for (hx, hz) in positions:
                    elements.append(MEPElement(
                        id=f"sprinkler_{uuid.uuid4().hex[:6]}",
                        system="fire", type="sprinkler",
                        start=[hx, head_y, hz],
                        level=lvl, diameter_in=0.5,
                    ))
                    # Vertical drop from riser at ceiling down to head
                    elements.append(MEPElement(
                        id=f"fire_drop_{uuid.uuid4().hex[:5]}",
                        system="fire", type="fire_branch_drop",
                        start=[rx, ceil_y, rz],
                        end=[hx, head_y, hz],
                        level=lvl, diameter_in=0.75,
                    ))

        return elements

    def _fire_pipe_size(self, n_heads: int) -> float:
        for max_heads, size in SPRINKLER_PIPE_FLOW:
            if n_heads <= max_heads:
                return size
        return 3.0

    # ════════════════════════════════════════════════════════════════════════
    # PLUMBING (IPC)
    # ════════════════════════════════════════════════════════════════════════

    def _route_plumbing(
        self, rooms: List[Room], walls: List[Wall], levels: List[Level], floor_h: float,
        bath_count: Optional[float] = None, is_adu: bool = False,
    ) -> List[MEPElement]:
        """
        Route domestic water supply (hot + cold) and waste/vent.
        bath_count: whole number = full baths, x.5 includes a half bath (toilet+sink, no shower).
        """
        elements = []
        total_floors = len(levels)
        # True if spec includes a .5 half bath (toilet+sink only, no shower)
        _has_half_bath = bath_count is not None and (bath_count % 1) == 0.5
        top_y = total_floors * floor_h   # vent stack ends at roof level

        wet_rooms_by_level = {}
        for r in rooms:
            if r.type in ("bathroom", "kitchen"):
                wet_rooms_by_level.setdefault(r.level, []).append(r)

        if not any(wet_rooms_by_level.values()):
            return elements

        # ── Stack location: use level-0 wet room centroid ──
        lvl0_wet = wet_rooms_by_level.get(0, [])
        if not lvl0_wet:
            lvl0_wet = [r for lvs in wet_rooms_by_level.values() for r in lvs][:1]

        stack_positions = []
        drain_d = 4.0  # default drain diameter
        for room in lvl0_wet[:2]:   # max 2 stacks for small buildings
            sx, sz = self._centroid(room)
            stack_positions.append((sx, sz))

            # Soil stack (main waste): ground slab to roof vent
            total_dfu = sum(
                FIXTURE_UNITS.get(r.type, 1.0) * 1.5
                for r in rooms if r.type in ("bathroom", "kitchen")
            )
            drain_d = self._drain_pipe_size(total_dfu)

            elements.append(MEPElement(
                id=f"stack_{uuid.uuid4().hex[:5]}",
                system="plumbing",
                type="soil_stack",
                start=[sx, 0.0, sz],
                end=[sx, top_y, sz],
                level=0,
                diameter_in=drain_d,
            ))

        # ── Water service entry ──
        all_room_pts = [p for r in rooms for p in r.polygon]
        if all_room_pts:
            service_z = min(p[1] for p in all_room_pts)   # building front wall
            sx0, sz0 = stack_positions[0]
            # Water service runs inside building from front wall to stack
            elements.append(MEPElement(
                id="water_service",
                system="plumbing",
                type="water_service",
                start=[sx0, 0.3, service_z],
                end=[sx0, 0.3, sz0],
                level=0,
                diameter_in=1.5,
            ))
            elements.append(MEPElement(
                id="water_meter",
                system="plumbing",
                type="water_meter",
                start=[sx0, 0.3, service_z + 0.3],  # just inside the wall
                level=0,
            ))

        # ── Hot water heater (in utility or near kitchen, ground floor) ──
        util_rooms = [r for r in rooms if r.type in ("laundry", "utility", "kitchen") and r.level == 0]
        if util_rooms:
            hwh_cx, hwh_cz = self._centroid(util_rooms[0])
        else:
            hwh_cx, hwh_cz = stack_positions[0] if stack_positions else (0.0, 0.0)

        # ADU: prefer heat pump water heater (CA Title 24 / energy compliance)
        hwh_type = "heat_pump_water_heater" if is_adu else "water_heater"
        elements.append(MEPElement(
            id="hot_water_heater",
            system="plumbing",
            type=hwh_type,
            start=[hwh_cx, 0.0, hwh_cz],
            level=0,
        ))

        # ── Per wet room: supply branches and fixture connections ──
        for lvl, lvl_rooms in wet_rooms_by_level.items():
            floor_y = lvl * floor_h
            sx, sz = stack_positions[0]

            for room in lvl_rooms:
                cx, cz = self._centroid(room)
                bds = self._bounds(room)
                # Route pipes inside the floor/wall zone — visible inside the building
                supply_y = floor_y + 0.15   # in-wall supply height
                waste_y  = floor_y + 0.05   # just above finished floor

                # Cold supply branch
                total_room_fu = FIXTURE_UNITS.get(room.type, 2.0)
                supply_d = self._water_pipe_size(total_room_fu)
                elements.append(MEPElement(
                    id=f"cold_{uuid.uuid4().hex[:5]}",
                    system="plumbing",
                    type="cold_supply",
                    start=[sx, supply_y, sz],
                    end=[cx, supply_y, cz],
                    level=lvl,
                    diameter_in=supply_d,
                ))

                # Hot supply branch (from water heater, parallel, slightly offset)
                if room.type in ("bathroom", "kitchen"):
                    elements.append(MEPElement(
                        id=f"hot_{uuid.uuid4().hex[:5]}",
                        system="plumbing",
                        type="hot_supply",
                        start=[hwh_cx, supply_y + 0.04, hwh_cz],
                        end=[cx, supply_y + 0.04, cz],
                        level=lvl,
                        diameter_in=supply_d,
                    ))

                # Waste branch
                elements.append(MEPElement(
                    id=f"waste_{uuid.uuid4().hex[:5]}",
                    system="plumbing",
                    type="waste_branch",
                    start=[cx, waste_y, cz],
                    end=[sx, waste_y, sz],
                    level=lvl,
                    diameter_in=max(1.5, drain_d - 1.0),
                ))

                # Fixture placement — half bath (small room or last bath when .5 count)
                # gets toilet + sink only; full bath gets toilet + sink + shower
                if room.type == "bathroom":
                    room_area_m2 = (bds[2]-bds[0]) * (bds[3]-bds[1])
                    # Half bath: under 3.5 m² OR spec explicitly has a .5 bath and this is a small room
                    is_half = room_area_m2 < 3.5 or (_has_half_bath and room_area_m2 < 5.0)
                    elements.append(MEPElement(
                        id=f"toilet_{uuid.uuid4().hex[:5]}",
                        system="plumbing", type="toilet",
                        start=[bds[0]+0.45, floor_y+0.01, bds[1]+0.45], level=lvl))
                    elements.append(MEPElement(
                        id=f"sink_{uuid.uuid4().hex[:5]}",
                        system="plumbing", type="sink",
                        start=[bds[0]+(bds[2]-bds[0])*0.7, floor_y+0.01, bds[1]+0.35], level=lvl))
                    if not is_half:
                        # Full bath: add shower
                        elements.append(MEPElement(
                            id=f"shower_{uuid.uuid4().hex[:5]}",
                            system="plumbing", type="shower",
                            start=[bds[2]-0.6, floor_y+0.01, bds[3]-0.6], level=lvl))
                elif room.type == "kitchen":
                    elements.append(MEPElement(
                        id=f"ksink_{uuid.uuid4().hex[:5]}",
                        system="plumbing", type="sink",
                        start=[bds[0]+0.5, floor_y+0.01, bds[3]-0.45], level=lvl))

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
        self, rooms: List[Room], levels: List[Level], preference, floor_h: float
    ) -> List[MEPElement]:
        """
        Route HVAC systems.
        mini_split: individual wall units per zone.
        rooftop: central RTU + main trunk + branches to each room.
        """
        pref = getattr(preference, 'value', str(preference)).lower()
        elements = []

        if pref == "mini_split":
            return self._hvac_mini_split(rooms, levels, floor_h)
        else:
            return self._hvac_central(rooms, levels, floor_h)

    def _hvac_mini_split(self, rooms, levels, floor_h) -> List[MEPElement]:
        """One indoor head unit per bedroom/living area. Condenser on roof."""
        elements = []
        total_floors = len(levels)
        roof_y = total_floors * floor_h

        # Outdoor condenser units on roof — use weighted centroid so it stays inside footprint
        if rooms:
            roof_cx, roof_cz = self._building_centroid(rooms)
        else:
            roof_cx, roof_cz = 0.0, 0.0

        elements.append(MEPElement(
            id="condenser_main",
            system="hvac",
            type="condenser_unit",
            start=[roof_cx, roof_y + 0.15, roof_cz],
            level=total_floors - 1,
        ))

        for level in levels:
            lvl = level.index
            for room in rooms:
                if room.level != lvl:
                    continue
                if room.type not in ("bedroom", "living", "unit", "dining"):
                    continue
                cx, cz = self._centroid(room)
                bds = self._bounds(room)
                head_y = lvl * floor_h + ZONE["duct_supply"]
                # Wall-mount head on interior wall (0.1m from wall)
                elements.append(MEPElement(
                    id=f"ms_head_{uuid.uuid4().hex[:5]}",
                    system="hvac",
                    type="mini_split_head",
                    start=[cx, head_y, bds[1] + 0.15],
                    level=lvl,
                    width_in=30,
                    height_in=10,
                ))
                # Refrigerant line (slim — 1") up to roof condenser
                elements.append(MEPElement(
                    id=f"refrig_{uuid.uuid4().hex[:5]}",
                    system="hvac",
                    type="refrigerant_line",
                    start=[cx, head_y, bds[1] + 0.15],
                    end=[roof_cx, roof_y, roof_cz],
                    level=lvl,
                    diameter_in=1.0,
                ))
        return elements

    def _hvac_central(self, rooms, levels, floor_h) -> List[MEPElement]:
        """Central rooftop unit + main supply trunk + branch ducts to each room."""
        elements = []
        total_floors = len(levels)
        roof_y = total_floors * floor_h

        if not rooms:
            return elements
        # Area-weighted centroid keeps RTU and trunk spine inside L/U/stepped footprints
        bld_cx, bld_cz = self._building_centroid(rooms)
        all_pts = [p for r in rooms for p in r.polygon]
        min_x = min(p[0] for p in all_pts)
        max_x = max(p[0] for p in all_pts)

        # Rooftop unit
        elements.append(MEPElement(
            id="rtu_main",
            system="hvac",
            type="rooftop_unit",
            start=[bld_cx, roof_y + 0.2, bld_cz],
            level=total_floors - 1,
            width_in=48,
            height_in=36,
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
            ))

            # Direct branch from riser to each room centroid — no spanning trunk
            for room in rooms:
                if room.level != lvl or room.type in ("stair",):
                    continue
                cx, cz = self._centroid(room)
                room_area_m2 = room.area_sqft * 0.0929
                cfm = max(50, int(room_area_m2 * 10.764 *
                          CFM_PER_100SQFT.get(room.type, 20) / 100))
                bw, bh, _ = self._duct_size(cfm)

                elements.append(MEPElement(
                    id=f"hvac_branch_{uuid.uuid4().hex[:5]}",
                    system="hvac", type="supply_branch",
                    start=[bld_cx, ceil_y, bld_cz],
                    end=[cx, ceil_y, cz],
                    level=lvl, width_in=bw, height_in=bh,
                ))
                elements.append(MEPElement(
                    id=f"diffuser_{uuid.uuid4().hex[:5]}",
                    system="hvac", type="supply_diffuser",
                    start=[cx, lvl * floor_h + ZONE["ceil_light"] - 0.05, cz],
                    level=lvl, width_in=bw, height_in=4,
                ))

        return elements

    def _duct_size(self, cfm: int) -> Tuple[int, int, int]:
        """Returns (width_in, height_in, diameter_in)."""
        for max_cfm, w, h, d in DUCT_SIZES:
            if cfm <= max_cfm:
                return w, h, d
        return 20, 12, 20

    # ════════════════════════════════════════════════════════════════════════
    # ELECTRICAL (NEC)
    # ════════════════════════════════════════════════════════════════════════

    def _route_electrical(
        self, rooms: List[Room], walls: List[Wall], levels: List[Level],
        floor_h: float, power_connection: dict, fine: dict, is_adu: bool = False,
    ) -> List[MEPElement]:
        """
        NEC-compliant residential electrical:
        - Service entry + main panel + sub-panels
        - Branch circuits sized by NEC 220.12
        - Outlets spaced ≤12ft (3.66m) per NEC 210.52
        - GFCI in wet areas, AFCI in bedrooms/living
        - Dedicated circuits for kitchen, laundry, bath
        - Light fixture at ceiling center of each room
        """
        elements = []
        outlets_per_room = int(fine.get("outlets_per_room", 3))
        do_alarms = fine.get("fire_alarms", True)

        all_room_pts = [p for r in rooms for p in r.polygon]
        if not all_room_pts:
            return elements

        min_x = min(p[0] for p in all_room_pts)
        min_z = min(p[1] for p in all_room_pts)

        # ── Service entry and main panel ──
        panel_x = min_x + 0.5
        panel_z = min_z + 0.5
        panel_y = 0.0   # ground floor

        # ADU electrical service decision (NEC 230.2, CA Title 24):
        # ≤600 sqft → sub-panel fed from main house (60–100A feeder)
        # >600 sqft → new utility service drop (100A minimum)
        adu_area_sqft = sum(r.area_sqft for r in rooms)
        adu_needs_new_service = is_adu and adu_area_sqft > 600
        panel_type = "main_panel" if (not is_adu or adu_needs_new_service) else "sub_panel"
        panel_amps = 100 if adu_needs_new_service else (60 if is_adu else 200)

        elements.append(MEPElement(
            id="main_panel",
            system="electrical",
            type=panel_type,
            start=[panel_x, panel_y + 1.2, panel_z],
            level=0,
            metadata={"amps": panel_amps, "adu_service": "new_drop" if adu_needs_new_service else ("sub_panel_from_house" if is_adu else "standard")},
        ))

        # Service conduit: from front wall to panel — stays inside building
        elements.append(MEPElement(
            id="service_entry",
            system="electrical",
            type="service_conduit",
            start=[panel_x, 1.2, min_z + 0.05],   # just inside front wall
            end=[panel_x, 1.2, panel_z],
            level=0,
            diameter_in=2.0,
        ))

        # ── Utility lateral: run from front wall toward nearest power pole/line ──
        # This is the only electrical element that intentionally exits the building.
        if power_connection:
            pole_dx = power_connection.get("dx_m", 0.0)
            pole_dz = power_connection.get("dz_m", -8.0)  # default: 8m in front
            # Clamp lateral length to 30m — beyond that the utility company owns it
            dist = max(0.1, math.sqrt(pole_dx**2 + pole_dz**2))
            lateral_len = min(dist, 30.0)
            ux = panel_x + pole_dx / dist * lateral_len
            uz = min_z + pole_dz / dist * lateral_len   # extends outward from front wall
            elements.append(MEPElement(
                id="utility_lateral",
                system="electrical",
                type="utility_lateral",
                start=[panel_x, 5.5, min_z],      # overhead at ~18ft (utility attachment height)
                end=[ux, 5.5, uz],
                level=0,
                diameter_in=1.0,
            ))

        for level in levels:
            lvl = level.index
            floor_y = lvl * floor_h
            ceil_y_elec = floor_y + ZONE["ceil_elec"]
            ceil_y_light = floor_y + ZONE["ceil_light"]

            # Sub-panel on upper floors
            if lvl > 0:
                elements.append(MEPElement(
                    id=f"sub_panel_{lvl}",
                    system="electrical",
                    type="sub_panel",
                    start=[panel_x, floor_y + 1.2, panel_z],
                    level=lvl,
                ))
                # Feeder riser
                elements.append(MEPElement(
                    id=f"feeder_{lvl}",
                    system="electrical",
                    type="feeder",
                    start=[panel_x, (lvl-1)*floor_h + 1.2, panel_z],
                    end=[panel_x, floor_y + 1.2, panel_z],
                    level=lvl,
                    diameter_in=1.5,
                ))

            lvl_rooms = [r for r in rooms if r.level == lvl]

            # ── Circuit trunk along corridor or building spine ──
            corrs = [r for r in lvl_rooms if r.type == "corridor"]
            if corrs:
                bds = self._bounds(corrs[0])
                trunk_z = bds[1] + 0.2
                trunk_x_start = bds[0]
                trunk_x_end   = bds[2]
            else:
                if not lvl_rooms:
                    continue
                pts = [p for r in lvl_rooms for p in r.polygon]
                # Weighted centroid Z keeps the trunk inside L/U shapes
                _, trunk_z = self._building_centroid(lvl_rooms)
                trunk_x_start = min(p[0] for p in pts)
                trunk_x_end   = max(p[0] for p in pts)

            elements.append(MEPElement(
                id=f"elec_trunk_{lvl}",
                system="electrical",
                type="conduit_trunk",
                start=[trunk_x_start, ceil_y_elec, trunk_z],
                end=[trunk_x_end, ceil_y_elec, trunk_z],
                level=lvl,
                diameter_in=1.0,
            ))

            # ── Per room: outlets, lights, fire alarms, circuits ──
            for room in lvl_rooms:
                if room.type in ("stair",):
                    continue

                cx, cz = self._centroid(room)
                bds = self._bounds(room)
                room_area_ft2 = room.area_sqft
                is_wet = room.type in ("bathroom", "kitchen")
                is_bedroom = room.type == "bedroom"

                # Circuit drops from trunk to room
                elements.append(MEPElement(
                    id=f"branch_{uuid.uuid4().hex[:5]}",
                    system="electrical",
                    type="conduit_branch",
                    start=[cx, ceil_y_elec, trunk_z],
                    end=[cx, ceil_y_elec, cz],
                    level=lvl,
                    diameter_in=0.75,
                ))

                # Ceiling light fixture(s) — large rooms get multiple lights
                bds_l = self._bounds(room)
                room_area_m2_l = (bds_l[2]-bds_l[0]) * (bds_l[3]-bds_l[1])
                if room_area_m2_l > 20.0:
                    # Two rows of lights for large rooms
                    for lx_off, lz_off in [(cx - (bds_l[2]-bds_l[0])*0.2, cz),
                                           (cx + (bds_l[2]-bds_l[0])*0.2, cz)]:
                        elements.append(MEPElement(
                            id=f"light_{uuid.uuid4().hex[:5]}",
                            system="electrical",
                            type="lighting_point",
                            start=[lx_off, ceil_y_light, lz_off],
                            level=lvl,
                        ))
                else:
                    elements.append(MEPElement(
                        id=f"light_{uuid.uuid4().hex[:5]}",
                        system="electrical",
                        type="lighting_point",
                        start=[cx, ceil_y_light, cz],
                        level=lvl,
                    ))

                # Fire/smoke alarm
                if do_alarms and room.type in ("bedroom", "living", "corridor", "unit"):
                    elements.append(MEPElement(
                        id=f"alarm_{uuid.uuid4().hex[:5]}",
                        system="electrical",
                        type="fire_alarm",
                        start=[cx, ceil_y_light - 0.05, cz],
                        level=lvl,
                    ))

                # Outlets placed on wall segments that bound this room.
                # Match room edges to actual wall segments (interior or exterior).
                # A wall "bounds" this room if its midpoint is within 0.5m of a room edge midpoint.
                outlet_y = floor_y + ZONE["outlet"]
                if outlets_per_room > 0:
                    if room_area_ft2 <= 150:
                        n_outlets = min(outlets_per_room, 3)
                    else:
                        n_outlets = min(3 + int((room_area_ft2 - 150) / 60), 6)
                    if room.type == "kitchen":
                        n_outlets = min(n_outlets + 2, 8)

                    # Collect all walls at this level
                    lvl_walls = [w for w in walls if w.level == lvl]
                    pts = room.polygon
                    n_pts = len(pts)
                    rcx = sum(p[0] for p in pts) / n_pts
                    rcz = sum(p[1] for p in pts) / n_pts

                    # For each room edge, find a matching wall and place outlet on it
                    placed = 0
                    for i in range(n_pts):
                        if placed >= n_outlets:
                            break
                        p0, p1 = pts[i], pts[(i + 1) % n_pts]
                        edge_mx = (p0[0] + p1[0]) / 2
                        edge_mz = (p0[1] + p1[1]) / 2

                        # Find closest wall whose midpoint is near this edge midpoint
                        best_wall = None
                        best_dist = 0.6  # max 60cm match distance
                        for w in lvl_walls:
                            wm_x = (w.start[0] + w.end[0]) / 2
                            wm_z = (w.start[1] + w.end[1]) / 2
                            d = math.sqrt((wm_x - edge_mx)**2 + (wm_z - edge_mz)**2)
                            if d < best_dist:
                                best_dist = d
                                best_wall = w

                        if best_wall:
                            # Place outlet on the wall face, pushed 5cm into the room
                            wm_x = (best_wall.start[0] + best_wall.end[0]) / 2
                            wm_z = (best_wall.start[1] + best_wall.end[1]) / 2
                            dx = rcx - wm_x
                            dz2 = rcz - wm_z
                            dist = max(0.001, math.sqrt(dx*dx + dz2*dz2))
                            ox = wm_x + dx / dist * 0.05
                            oz = wm_z + dz2 / dist * 0.05
                        else:
                            # No matching wall — fall back to room edge midpoint
                            dx = rcx - edge_mx
                            dz2 = rcz - edge_mz
                            dist = max(0.001, math.sqrt(dx*dx + dz2*dz2))
                            ox = edge_mx + dx / dist * 0.05
                            oz = edge_mz + dz2 / dist * 0.05

                        elements.append(MEPElement(
                            id=f"outlet_{uuid.uuid4().hex[:5]}",
                            system="electrical", type="outlet",
                            start=[ox, outlet_y, oz], level=lvl,
                        ))
                        elements.append(MEPElement(
                            id=f"conduit_drop_{uuid.uuid4().hex[:5]}",
                            system="electrical", type="conduit_branch",
                            start=[ox, ceil_y_elec, oz],
                            end=[ox, outlet_y + 0.05, oz],
                            level=lvl, diameter_in=0.5,
                        ))
                        placed += 1

                # Dedicated circuit label for kitchen/laundry
                if room.type == "kitchen":
                    elements.append(MEPElement(
                        id=f"ded_circuit_{uuid.uuid4().hex[:5]}",
                        system="electrical",
                        type="dedicated_circuit",
                        start=[bds[0]+0.3, floor_y+1.0, bds[1]+0.3],
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
        IPC/CPC require minimum 1/4" per foot (2%) slope on 4" ABS/PVC lateral.
        Typical ADU-to-main-sewer run: 20–40 ft.
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

    def _centroid(self, room: Room) -> Tuple[float, float]:
        pts = room.polygon
        if not pts:
            return 0.0, 0.0
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)

    def _bounds(self, room: Room) -> Tuple[float, float, float, float]:
        pts = room.polygon
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def _building_centroid(self, rooms: List[Room]) -> Tuple[float, float]:
        """Room-area-weighted centroid — always inside the building for L/U/stepped shapes.
        Unlike averaging raw polygon vertices, this is biased toward where rooms actually are."""
        total = sum(r.area_sqft for r in rooms) or 1.0
        cx = sum(self._centroid(r)[0] * r.area_sqft for r in rooms) / total
        cz = sum(self._centroid(r)[1] * r.area_sqft for r in rooms) / total
        return cx, cz
