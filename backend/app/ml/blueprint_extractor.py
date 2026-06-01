"""
BlueprintExtractor
Sends a blueprint / exterior photo to Claude vision and returns a structured
label dict that matches the archetype schema used by the rest of the pipeline.

Returned schema:
{
  "source_file": str,          relative path from data/ root
  "image_type": str,           "floor_plan" | "exterior_photo" | "3d_render" | "sketch"
  "building_type": str,        "adu" | "sfr" | "victorian" | "townhouse" | "unknown"
  "bedrooms": int | null,
  "bathrooms": int | null,
  "half_baths": int | null,
  "floors": int | null,
  "total_sqft": int | null,
  "footprint_ft": { "width": float, "depth": float } | null,
  "style": str,                dominant_arch_style value
  "facade_material": str | null,
  "rooms": [
    { "type": str, "floor": int, "approx_sqft": int|null, "position": str|null }
  ],
  "stair": { "present": bool, "location": str|null, "direction": str|null } | null,
  "wet_wall_location": str | null,
  "has_garage": bool,
  "entry_side": str | null,    "front" | "side" | "rear"
  "confidence": float,         0.0 – 1.0
  "notes": str
}
"""
import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, Optional


_EXTRACT_PROMPT = """You are an expert architectural analyst. Examine this image and extract structured information about the building or floor plan.

Return ONLY valid JSON matching this exact schema (use null for fields you cannot determine):

{
  "image_type": "<floor_plan | exterior_photo | 3d_render | sketch>",
  "building_type": "<adu | sfr | victorian | townhouse | unknown>",
  "bedrooms": <integer or null>,
  "bathrooms": <integer or null>,
  "half_baths": <integer or null>,
  "floors": <integer or null>,
  "total_sqft": <integer or null>,
  "footprint_ft": { "width": <float or null>, "depth": <float or null> },
  "style": "<contemporary_box | classic_gabled | victorian | craftsman | colonial | modern | unknown>",
  "facade_material": "<wood_painted | fiber_cement | stucco | brick | concrete | unknown or null>",
  "rooms": [
    {
      "type": "<living | kitchen | bedroom | bathroom | dining | stair | corridor | foyer | garage | laundry | closet | hall | utility | office | other>",
      "floor": <0-based integer>,
      "approx_sqft": <integer or null>,
      "position": "<front_left | front_right | front_center | rear_left | rear_right | rear_center | center | left_spine | right_spine | null>"
    }
  ],
  "stair": {
    "present": <true | false>,
    "location": "<left_spine | right_spine | center | front | rear | null>",
    "direction": "<front_to_rear | side_to_side | null>"
  },
  "wet_wall_location": "<rear_right | rear_left | rear_center | right_spine | left_spine | null>",
  "has_garage": <true | false>,
  "entry_side": "<front | side | rear | null>",
  "confidence": <0.0 to 1.0>,
  "notes": "<one sentence summary of what you see>"
}

Be concise. If the image is an exterior photo extract style/material/floors. If it is a floor plan extract the full room breakdown. Do not add any text outside the JSON."""


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    mapping = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return mapping.get(suffix, "image/jpeg")


class BlueprintExtractor:
    """Extract structured labels from blueprint / house images using Claude vision."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-6"):
        self.model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def extract(self, image_path: str | Path, source_label: Optional[str] = None) -> Dict[str, Any]:
        """
        Run extraction on a single image file.
        Returns the structured label dict (always — on error returns a skeleton with confidence=0).
        """
        import anthropic

        path = Path(image_path)
        if not path.exists():
            return self._error_skeleton(str(image_path), f"file not found: {image_path}")

        raw = path.read_bytes()
        b64 = base64.standard_b64encode(raw).decode("utf-8")
        media_type = _media_type(path)

        client = anthropic.Anthropic(api_key=self._api_key)
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": b64,
                                },
                            },
                            {"type": "text", "text": _EXTRACT_PROMPT},
                        ],
                    }
                ],
            )
            raw_text = response.content[0].text.strip()

            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                raw_text = "\n".join(
                    l for l in lines if not l.startswith("```")
                ).strip()

            label = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            return self._error_skeleton(str(image_path), f"JSON parse error: {exc}")
        except Exception as exc:
            return self._error_skeleton(str(image_path), f"API error: {exc}")

        label["source_file"] = source_label or str(image_path)
        return label

    @staticmethod
    def _error_skeleton(source: str, reason: str) -> Dict[str, Any]:
        return {
            "source_file": source,
            "image_type": "unknown",
            "building_type": "unknown",
            "bedrooms": None,
            "bathrooms": None,
            "half_baths": None,
            "floors": None,
            "total_sqft": None,
            "footprint_ft": None,
            "style": "unknown",
            "facade_material": None,
            "rooms": [],
            "stair": None,
            "wet_wall_location": None,
            "has_garage": False,
            "entry_side": None,
            "confidence": 0.0,
            "notes": reason,
        }
