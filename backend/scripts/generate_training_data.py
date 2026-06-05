"""
generate_training_data.py
Scans backend/app/data/ for all image files, runs BlueprintExtractor on each,
and writes structured labels into backend/app/data/training/.

Output layout:
  backend/app/data/training/
    manifest.jsonl          one JSON object per line: {id, source_file, label_file, building_type, ...}
    adu/
      adu_001_label.json
    victorian/
      victorian_001_label.json
    sfr/
      sfr_001_label.json
    other/
      other_001_label.json

Usage:
  cd backend
  python scripts/generate_training_data.py [--data-dir app/data] [--force]
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Allow running from backend/ or project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ml.blueprint_extractor import BlueprintExtractor

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Map folder names to building type hints (extractor can override)
FOLDER_TYPE_HINTS: dict[str, str] = {
    "adus": "adu",
    "adu": "adu",
    "victorian-house": "victorian",
    "victorian": "victorian",
    "sfr": "sfr",
    "single-family": "sfr",
    "mid-century": "mid_century",
    "hillside-homes": "hillside",
    "high-density-townhomes": "townhouse",
    "urban-infill": "urban_infill",
    "urbaninfill-zero-lot": "urban_infill",
    "production-tract_homes": "tract",
    "high-end-custom": "high_end_custom",
    "prefab-modern": "prefab",
}


def find_images(data_dir: Path) -> list[Path]:
    images = []
    for p in data_dir.rglob("*"):
        if p.suffix.lower() in IMAGE_SUFFIXES and "training" not in p.parts:
            images.append(p)
    return sorted(images)


def bucket_for(label: dict, folder_hint: str) -> str:
    bt = label.get("building_type", "unknown") or "unknown"
    if bt not in ("adu", "sfr", "victorian", "townhouse"):
        bt = folder_hint if folder_hint != "unknown" else "other"
    return bt


def main():
    parser = argparse.ArgumentParser(description="Generate blueprint training labels")
    parser.add_argument("--data-dir", default="app/data",
                        help="Root data directory (default: app/data)")
    parser.add_argument("--force", action="store_true",
                        help="Re-extract even if label file already exists")
    parser.add_argument("--model", default="claude-sonnet-4-6",
                        help="Claude model to use for extraction")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    training_dir = data_dir / "training"
    training_dir.mkdir(exist_ok=True)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    extractor = BlueprintExtractor(api_key=api_key, model=args.model)
    images = find_images(data_dir)

    if not images:
        print(f"No images found under {data_dir}")
        sys.exit(0)

    print(f"Found {len(images)} image(s) under {data_dir}")

    manifest_path = training_dir / "manifest.jsonl"
    existing_manifest: dict[str, dict] = {}
    if manifest_path.exists():
        for line in manifest_path.read_text().splitlines():
            line = line.strip()
            if line:
                entry = json.loads(line)
                existing_manifest[entry["source_file"]] = entry

    counters: dict[str, int] = {}
    new_entries: list[dict] = []

    for img_path in images:
        rel = str(img_path.relative_to(data_dir))

        if not args.force and rel in existing_manifest:
            print(f"  skip (cached)  {rel}")
            continue

        # Determine folder hint for bucket
        folder_name = img_path.parent.name.lower()
        folder_hint = FOLDER_TYPE_HINTS.get(folder_name, "unknown")

        print(f"  extracting     {rel} ...", end=" ", flush=True)
        label = extractor.extract(img_path, source_label=rel)

        bucket = bucket_for(label, folder_hint)
        counters.setdefault(bucket, 0)
        counters[bucket] += 1
        idx = counters[bucket]

        # Write label JSON
        bucket_dir = training_dir / bucket
        bucket_dir.mkdir(exist_ok=True)
        label_filename = f"{bucket}_{idx:03d}_label.json"
        label_path = bucket_dir / label_filename
        label_path.write_text(json.dumps(label, indent=2))

        entry = {
            "id": f"{bucket}_{idx:03d}",
            "source_file": rel,
            "label_file": str(label_path.relative_to(data_dir)),
            "building_type": label.get("building_type", "unknown"),
            "image_type": label.get("image_type", "unknown"),
            "bedrooms": label.get("bedrooms"),
            "floors": label.get("floors"),
            "confidence": label.get("confidence", 0.0),
        }
        new_entries.append(entry)
        print(f"→ {bucket}/{label_filename}  (conf={label.get('confidence', 0):.2f})")

    # Append new entries to manifest
    if new_entries:
        with manifest_path.open("a") as f:
            for entry in new_entries:
                f.write(json.dumps(entry) + "\n")
        print(f"\nWrote {len(new_entries)} new label(s) to {training_dir}")
    else:
        print("\nNothing new to process.")

    # Summary
    all_entries = list(existing_manifest.values()) + new_entries
    print(f"\nDataset size: {len(all_entries)} total examples")
    buckets: dict[str, int] = {}
    for e in all_entries:
        bt = e.get("building_type", "unknown")
        buckets[bt] = buckets.get(bt, 0) + 1
    for bt, count in sorted(buckets.items()):
        print(f"  {bt}: {count}")


if __name__ == "__main__":
    main()
