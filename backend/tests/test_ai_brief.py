from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ai_brief import _default_brief, _normalize_brief


def test_design_brief_provider_values_are_constrained() -> None:
    spec = {"stories": 3}
    neighbors = {"dominant_shape": "unknown", "dominant_material": "vinyl"}

    fallback = _default_brief(spec, neighbors)
    assert fallback["shape"] == "rectangle"
    assert fallback["facade_material"] == "stucco"

    normalized = _normalize_brief(
        {
            "shape": "spaceship",
            "width_m": -50,
            "depth_m": "900",
            "window_ratio": 4,
            "balcony_depth_m": -1,
            "balcony_every_n_floors": "99",
            "facade_material": "plastic",
            "horizontal_bands": "false",
            "roof_type": "dome",
            "ground_floor_height_boost_m": "bad",
            "penthouse_setback": "yes",
            "rationale": "x" * 500,
        },
        spec,
        neighbors,
    )

    assert normalized["shape"] == "rectangle"
    assert normalized["facade_material"] == "stucco"
    assert normalized["width_m"] == 4.0
    assert normalized["depth_m"] == 80.0
    assert normalized["window_ratio"] == 0.70
    assert normalized["balcony_depth_m"] == 0.0
    assert normalized["balcony_every_n_floors"] == 10
    assert normalized["horizontal_bands"] is False
    assert normalized["roof_type"] == "flat"
    assert normalized["penthouse_setback"] is True
    assert len(normalized["rationale"]) == 300
