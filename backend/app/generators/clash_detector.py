"""
ClashDetector
Finds spatial conflicts between MEP systems and structural members.
Reports clashes as ComplianceIssue objects.

A clash is defined as two elements whose axis-aligned bounding boxes overlap
by more than CLASH_TOLERANCE_M in all three dimensions.
"""
import math
import uuid
from typing import List, Dict, Tuple, Optional
from app.models.schemas import MEPElement, ComplianceIssue, BBox

CLASH_TOLERANCE_M = 0.05    # 5cm — below this overlap is acceptable (flush)
CLEARANCE_RULES = {
    # (system_a, system_b): min_clearance_m
    ("electrical", "plumbing"): 0.05,
    ("electrical", "hvac"):     0.03,
    ("plumbing",   "hvac"):     0.05,
    ("fire",       "hvac"):     0.03,
    ("fire",       "plumbing"): 0.03,
    ("fire",       "electrical"):0.03,
}

# System routing zones (Y ranges relative to floor datum, for zone conflicts)
SYSTEM_ZONES = {
    "fire":       (2.30, 2.55),   # sprinkler lines at ceiling
    "hvac":       (2.55, 3.10),   # ducts in plenum
    "plumbing":   (-0.40, 0.60),  # supply/waste in wall + sub-slab
    "electrical": (2.10, 2.50),   # conduit at ceiling edge
}


def _get_bbox(el: MEPElement, default_radius: float = 0.08) -> Optional[Tuple[float,float,float,float,float,float]]:
    """Returns (min_x, min_y, min_z, max_x, max_y, max_z) for an element."""
    if not el.start:
        return None
    r = max(
        (el.diameter_in or 2.0) * 0.0254 / 2 + 0.01,
        (el.width_in or 4.0) * 0.0254 / 2 + 0.01,
    )
    x0, y0, z0 = el.start[0], el.start[1], el.start[2]
    if el.end:
        x1, y1, z1 = el.end[0], el.end[1], el.end[2]
    else:
        x1, y1, z1 = x0, y0 + 0.3, z0

    return (
        min(x0, x1) - r, min(y0, y1) - r, min(z0, z1) - r,
        max(x0, x1) + r, max(y0, y1) + r, max(z0, z1) + r,
    )


def _boxes_overlap(a, b) -> float:
    """Returns overlap volume if boxes overlap, else 0."""
    if not a or not b:
        return 0.0
    ox = min(a[3], b[3]) - max(a[0], b[0])
    oy = min(a[4], b[4]) - max(a[1], b[1])
    oz = min(a[5], b[5]) - max(a[2], b[2])
    if ox > CLASH_TOLERANCE_M and oy > CLASH_TOLERANCE_M and oz > CLASH_TOLERANCE_M:
        return ox * oy * oz
    return 0.0


def detect_clashes(mep_elements: List[MEPElement]) -> List[ComplianceIssue]:
    """Find all spatial clashes between MEP elements of different systems."""
    issues = []

    # Group by system
    by_system: Dict[str, List[MEPElement]] = {}
    for el in mep_elements:
        by_system.setdefault(el.system, []).append(el)

    systems = list(by_system.keys())

    for i in range(len(systems)):
        for j in range(i+1, len(systems)):
            sys_a = systems[i]
            sys_b = systems[j]
            min_clear = CLEARANCE_RULES.get((sys_a, sys_b),
                        CLEARANCE_RULES.get((sys_b, sys_a), CLASH_TOLERANCE_M))

            for el_a in by_system[sys_a]:
                bbox_a = _get_bbox(el_a)
                if not bbox_a:
                    continue
                for el_b in by_system[sys_b]:
                    bbox_b = _get_bbox(el_b)
                    overlap = _boxes_overlap(bbox_a, bbox_b)
                    if overlap > 0:
                        cx = (bbox_a[0] + bbox_a[3] + bbox_b[0] + bbox_b[3]) / 4
                        cy = (bbox_a[1] + bbox_a[4] + bbox_b[1] + bbox_b[4]) / 4
                        cz = (bbox_a[2] + bbox_a[5] + bbox_b[2] + bbox_b[5]) / 4
                        issues.append(ComplianceIssue(
                            id=f"clash_{uuid.uuid4().hex[:6]}",
                            type="clash",
                            severity="error" if overlap > 0.001 else "warning",
                            message=f"{sys_a.upper()} / {sys_b.upper()} clash: "
                                    f"{el_a.type} vs {el_b.type} "
                                    f"({overlap*1e6:.1f} cm³ overlap)",
                            fix_suggestion=f"Reroute {el_b.type} with ≥{min_clear*100:.0f}cm clearance "
                                           f"from {el_a.type}",
                            elements_involved=[el_a.id, el_b.id],
                            location=BBox(
                                min_x=cx-0.3, min_y=cy-0.3, min_z=cz-0.3,
                                max_x=cx+0.3, max_y=cy+0.3, max_z=cz+0.3,
                            ),
                        ))

    return issues


def get_routing_summary(mep_elements: List[MEPElement]) -> Dict:
    """Return summary stats for each system."""
    summary = {}
    for el in mep_elements:
        s = summary.setdefault(el.system, {"count": 0, "types": {}})
        s["count"] += 1
        s["types"][el.type] = s["types"].get(el.type, 0) + 1
    return summary
