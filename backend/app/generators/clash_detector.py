"""Geometric MEP coordination checks.

The original detector compared axis-aligned boxes around entire routes.  A
diagonal pipe and duct could therefore appear to occupy the same large box even
when their centerlines never met.  This module measures the closest points on
the actual 3D segments and applies physical radii plus coordination clearance.
"""
import math
import uuid
from typing import Dict, List, Optional, Tuple

from app.models.schemas import BBox, ComplianceIssue, MEPElement


CLEARANCE_RULES = {
    ("electrical", "plumbing"): 0.05,
    ("electrical", "hvac"): 0.03,
    ("plumbing", "hvac"): 0.05,
    ("fire", "hvac"): 0.03,
    ("fire", "plumbing"): 0.03,
    ("fire", "electrical"): 0.03,
}
COORDINATED_SYSTEMS = {system for pair in CLEARANCE_RULES for system in pair}


def _dot(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _subtract(a, b) -> Tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _add_scaled(a, direction, scale) -> Tuple[float, float, float]:
    return (
        a[0] + direction[0] * scale,
        a[1] + direction[1] * scale,
        a[2] + direction[2] * scale,
    )


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _closest_segment_points(
    p1: Tuple[float, float, float], q1: Tuple[float, float, float],
    p2: Tuple[float, float, float], q2: Tuple[float, float, float],
) -> Tuple[float, Tuple[float, float, float], Tuple[float, float, float]]:
    """Return distance and closest points for two finite 3D segments."""
    d1 = _subtract(q1, p1)
    d2 = _subtract(q2, p2)
    relative = _subtract(p1, p2)
    a = _dot(d1, d1)
    e = _dot(d2, d2)
    epsilon = 1e-12

    if a <= epsilon and e <= epsilon:
        first, second = p1, p2
    elif a <= epsilon:
        s = 0.0
        t = _clamp(_dot(d2, relative) / e)
        first, second = p1, _add_scaled(p2, d2, t)
    else:
        c = _dot(d1, relative)
        if e <= epsilon:
            t = 0.0
            s = _clamp(-c / a)
        else:
            b = _dot(d1, d2)
            f = _dot(d2, relative)
            denominator = a * e - b * b
            s = _clamp((b * f - c * e) / denominator) if abs(denominator) > epsilon else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = _clamp(-c / a)
            elif t > 1.0:
                t = 1.0
                s = _clamp((b - c) / a)
        first = _add_scaled(p1, d1, s)
        second = _add_scaled(p2, d2, t)

    delta = _subtract(first, second)
    return math.sqrt(_dot(delta, delta)), first, second


def _segment(element: MEPElement) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    if not element.start or len(element.start) < 3:
        return None
    start = tuple(float(value) for value in element.start[:3])
    end_values = element.end if element.end and len(element.end) >= 3 else element.start
    end = tuple(float(value) for value in end_values[:3])
    return start, end


def _is_vertical_segment(
    segment: Tuple[Tuple[float, float, float], Tuple[float, float, float]]
) -> bool:
    start, end = segment
    horizontal_run = math.hypot(end[0] - start[0], end[2] - start[2])
    return horizontal_run < 0.02 and abs(end[1] - start[1]) >= 0.05


def _physical_radius(element: MEPElement) -> float:
    """Conservative centerline radius in metres for clearance measurement."""
    dimensions = []
    if element.diameter_in:
        dimensions.append(float(element.diameter_in) * 0.0254 / 2.0)
    if element.width_in:
        dimensions.append(float(element.width_in) * 0.0254 / 2.0)
    if element.height_in:
        dimensions.append(float(element.height_in) * 0.0254 / 2.0)
    if dimensions:
        return max(dimensions)
    point_radii = {
        "main_panel": 0.20, "sub_panel": 0.18,
        "rooftop_unit": 0.45, "condenser_unit": 0.35,
        "whole_house_ventilator": 0.20, "erv": 0.20,
        "lighting_point": 0.05, "fire_alarm": 0.04,
        "carbon_monoxide_detector": 0.04, "outlet": 0.03,
        "light_switch": 0.03, "sprinkler": 0.025,
    }
    return point_radii.get(element.type, 0.05)


def _axis_radii(element: MEPElement) -> Tuple[float, float]:
    """Return conservative horizontal and vertical half-extents in metres."""
    round_radius = float(element.diameter_in or 0.0) * 0.0254 / 2.0
    horizontal = max(round_radius, float(element.width_in or 0.0) * 0.0254 / 2.0)
    vertical = max(round_radius, float(element.height_in or 0.0) * 0.0254 / 2.0)
    if horizontal <= 0:
        horizontal = _physical_radius(element)
    if vertical <= 0:
        vertical = {
            "lighting_point": 0.02,
            "fire_alarm": 0.02,
            "carbon_monoxide_detector": 0.02,
            "outlet": 0.03,
            "light_switch": 0.03,
            "sprinkler": 0.025,
        }.get(element.type, _physical_radius(element))
    return horizontal, vertical


def _is_point_segment(
    segment: Tuple[Tuple[float, float, float], Tuple[float, float, float]]
) -> bool:
    return math.dist(segment[0], segment[1]) < 1e-6


def _axis_gaps_for_point_pair(
    element_a: MEPElement,
    segment_a: Tuple[Tuple[float, float, float], Tuple[float, float, float]],
    element_b: MEPElement,
    segment_b: Tuple[Tuple[float, float, float], Tuple[float, float, float]],
) -> Optional[Tuple[float, float]]:
    """Axis-aware gaps when at least one element is point-like.

    Wide, shallow terminals must not be modeled as spheres whose horizontal
    width extends through a floor or ceiling plane.
    """
    point_a = _is_point_segment(segment_a)
    point_b = _is_point_segment(segment_b)
    if not point_a and not point_b:
        return None
    if point_b and not point_a:
        element_a, element_b = element_b, element_a
        segment_a, segment_b = segment_b, segment_a
        point_a, point_b = True, False

    point = segment_a[0]
    horizontal_a, vertical_a = _axis_radii(element_a)
    horizontal_b, vertical_b = _axis_radii(element_b)
    if point_b:
        other = segment_b[0]
        horizontal_distance = math.hypot(point[0] - other[0], point[2] - other[2])
        vertical_distance = abs(point[1] - other[1])
    else:
        start, end = segment_b
        dx = end[0] - start[0]
        dz = end[2] - start[2]
        denominator = dx * dx + dz * dz
        projection = (
            _clamp(((point[0] - start[0]) * dx + (point[2] - start[2]) * dz) / denominator)
            if denominator > 1e-12 else 0.0
        )
        closest_x = start[0] + dx * projection
        closest_z = start[2] + dz * projection
        horizontal_distance = math.hypot(point[0] - closest_x, point[2] - closest_z)
        low_y, high_y = sorted((start[1], end[1]))
        vertical_distance = (
            low_y - point[1] if point[1] < low_y
            else point[1] - high_y if point[1] > high_y
            else 0.0
        )
    return (
        horizontal_distance - horizontal_a - horizontal_b,
        vertical_distance - vertical_a - vertical_b,
    )


def detect_clashes(mep_elements: List[MEPElement]) -> List[ComplianceIssue]:
    """Find physical intersections and clearance deficits between MEP systems."""
    issues: List[ComplianceIssue] = []
    # Utility laterals and exterior service masts are interface geometry, not
    # internal distribution. They require utility review but should not create
    # false floor-to-floor clashes against the building's interior systems.
    candidates = [
        element for element in mep_elements
        if element.system in COORDINATED_SYSTEMS
        and not (element.metadata or {}).get("allow_outside_footprint")
    ]
    by_system: Dict[str, List[MEPElement]] = {}
    for element in candidates:
        by_system.setdefault(element.system, []).append(element)

    systems = sorted(by_system)
    for index, system_a in enumerate(systems):
        for system_b in systems[index + 1:]:
            rule_key = (system_a, system_b)
            reverse_key = (system_b, system_a)
            if rule_key not in CLEARANCE_RULES and reverse_key not in CLEARANCE_RULES:
                continue
            clearance = (
                CLEARANCE_RULES[rule_key]
                if rule_key in CLEARANCE_RULES
                else CLEARANCE_RULES[reverse_key]
            )
            for element_a in by_system[system_a]:
                segment_a = _segment(element_a)
                if segment_a is None:
                    continue
                for element_b in by_system[system_b]:
                    segment_b = _segment(element_b)
                    if segment_b is None:
                        continue
                    # Horizontal/point systems on different logical stories
                    # are separated by the floor assembly. Wide equipment must
                    # not be treated as a sphere extending into the next story.
                    # Vertical risers remain eligible for cross-story checks.
                    if (
                        element_a.level != element_b.level
                        and not _is_vertical_segment(segment_a)
                        and not _is_vertical_segment(segment_b)
                    ):
                        continue
                    distance, point_a, point_b = _closest_segment_points(*segment_a, *segment_b)
                    axis_gaps = _axis_gaps_for_point_pair(
                        element_a, segment_a, element_b, segment_b
                    )
                    if axis_gaps is not None:
                        horizontal_gap, vertical_gap = axis_gaps
                        # Axis-aligned volumes are clear when either separating
                        # axis meets the required distance.
                        if horizontal_gap >= clearance or vertical_gap >= clearance:
                            continue
                        physical_gap = max(horizontal_gap, vertical_gap)
                    else:
                        radius_a = _physical_radius(element_a)
                        radius_b = _physical_radius(element_b)
                        physical_gap = distance - radius_a - radius_b
                        if physical_gap >= clearance:
                            continue
                    center = tuple((point_a[i] + point_b[i]) / 2.0 for i in range(3))
                    overlap = max(0.0, -physical_gap)
                    severity = "error" if overlap > 0.002 else "warning"
                    description = (
                        f"{overlap * 100:.1f} cm physical overlap"
                        if overlap > 0 else f"{max(0.0, physical_gap) * 100:.1f} cm clear"
                    )
                    issues.append(ComplianceIssue(
                        id=f"clash_{uuid.uuid4().hex[:6]}", type="clash", severity=severity,
                        message=(
                            f"{system_a.upper()} / {system_b.upper()} coordination: "
                            f"{element_a.type} vs {element_b.type} ({description})"
                        ),
                        fix_suggestion=(
                            f"Reroute {element_b.type} to maintain at least "
                            f"{clearance * 100:.0f} cm clear from {element_a.type}."
                        ),
                        elements_involved=[element_a.id, element_b.id],
                        location=BBox(
                            min_x=center[0] - 0.3, min_y=center[1] - 0.3, min_z=center[2] - 0.3,
                            max_x=center[0] + 0.3, max_y=center[1] + 0.3, max_z=center[2] + 0.3,
                        ),
                        citation="MEP coordination preflight; verify trade and AHJ clearances",
                    ))
    return issues


def get_routing_summary(mep_elements: List[MEPElement]) -> Dict:
    """Return summary stats for each system."""
    summary: Dict = {}
    for element in mep_elements:
        system = summary.setdefault(element.system, {"count": 0, "types": {}})
        system["count"] += 1
        system["types"][element.type] = system["types"].get(element.type, 0) + 1
    return summary
