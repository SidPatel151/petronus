"""
build_blueprint_index.py
One-time script: runs BlueprintExtractor (Claude Haiku vision) over every
image in backend/app/data/ and saves a compact index to:
  backend/app/data/blueprint_index.json

Run once; re-run only when you add new blueprints.
Cost estimate: ~43 images × ~$0.002 each ≈ $0.09 total (Haiku vision).

Usage:
  cd backend
  python scripts/build_blueprint_index.py
"""
import json
import os
import sys
from pathlib import Path

# Make sure app is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ml.blueprint_extractor import BlueprintExtractor

# Folders to scan (relative to backend/app/data/)
_DATA_ROOT = Path(__file__).parent.parent / "app" / "data"
_OUT_FILE  = _DATA_ROOT / "blueprint_index.json"

# Map folder name → archetype_id (matches archetype JSON filenames)
_FOLDER_TO_ARCHETYPE = {
    "Hillside-homes":        "hillside_stepped",
    "High-End-Custom":       "high_end_custom",
    "High-Density-Townhomes":"high_density_townhome",
    "Mid-Century":           "mid_century_modern",
    "Prefab-Modern":         "prefab_modern",
    "Production-Tract_homes":"production_tract",
    "ADUs":                  "adu_compact",
    "victorian-house":       "victorian_narrow_lot",
    "UrbanInfill-Zero-Lot":  "urban_infill_zero_lot",
    "training/adu":          "adu_compact",
    "training/victorian":    "victorian_narrow_lot",
    "training/townhouse":    "high_density_townhome",
    "training/sfr":          "production_tract",
    "training/other":        None,
}

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _compact_entry(label: dict, archetype_id: str | None) -> dict:
    """Strip full base64 data, keep only what the room program service needs."""
    return {
        "archetype":    archetype_id or label.get("building_type", "unknown"),
        "image_type":   label.get("image_type", "unknown"),
        "building_type":label.get("building_type", "unknown"),
        "bedrooms":     label.get("bedrooms"),
        "bathrooms":    label.get("bathrooms"),
        "floors":       label.get("floors"),
        "total_sqft":   label.get("total_sqft"),
        "footprint_ft": label.get("footprint_ft"),
        "style":        label.get("style"),
        "facade_material": label.get("facade_material"),
        "has_garage":   label.get("has_garage", False),
        "rooms":        label.get("rooms", []),          # [{type, floor, approx_sqft, position}]
        "stair":        label.get("stair"),
        "wet_wall_location": label.get("wet_wall_location"),
        "entry_side":   label.get("entry_side"),
        "confidence":   label.get("confidence", 0.0),
        "notes":        label.get("notes", ""),
        "source_file":  label.get("source_file", ""),
    }


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    # Use Haiku for cheaper vision extraction
    extractor = BlueprintExtractor(api_key=api_key, model="claude-haiku-4-5-20251001")

    index: list = []
    skipped = 0

    for folder_rel, archetype_id in _FOLDER_TO_ARCHETYPE.items():
        folder = _DATA_ROOT / folder_rel
        if not folder.exists():
            continue
        images = [p for p in folder.iterdir() if p.suffix.lower() in _IMAGE_EXTS]
        for img in sorted(images):
            print(f"  extracting {img.relative_to(_DATA_ROOT)} …", end=" ", flush=True)
            label = extractor.extract(img, source_label=str(img.relative_to(_DATA_ROOT)))
            if label.get("confidence", 0) < 0.2:
                print(f"skip (confidence {label['confidence']:.2f})")
                skipped += 1
                continue
            entry = _compact_entry(label, archetype_id)
            index.append(entry)
            br  = entry.get("bedrooms", "?")
            sqft = entry.get("total_sqft", "?")
            rooms = len(entry.get("rooms", []))
            print(f"ok — {br}BR {sqft}sqft {rooms} rooms (conf={label['confidence']:.2f})")

    _OUT_FILE.write_text(json.dumps(index, indent=2))
    print(f"\nDone. {len(index)} blueprints indexed, {skipped} skipped → {_OUT_FILE}")


if __name__ == "__main__":
    main()
