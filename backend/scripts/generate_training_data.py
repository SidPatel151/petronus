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
from collections import Counter
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Allow running from backend/ or project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ml.blueprint_extractor import BlueprintExtractor

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_DATASET_ID_RE = re.compile(r"^(?P<bucket>.+)_(?P<index>\d+)$")

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


def _normalise_relative_path(value: str) -> str:
    """Use one manifest path representation on every operating system."""
    normalised = value.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def load_manifest(manifest_path: Path) -> list[dict]:
    """Load rows without silently discarding duplicate IDs or sources."""
    if not manifest_path.exists():
        return []

    entries: list[dict] = []
    for line_number, raw_line in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON in {manifest_path} at line {line_number}: {exc}"
            ) from exc
        if not isinstance(entry, dict):
            raise ValueError(
                f"Invalid manifest row at {manifest_path}:{line_number}: expected object"
            )
        if not isinstance(entry.get("source_file"), str) or not entry["source_file"].strip():
            raise ValueError(
                f"Invalid manifest row at {manifest_path}:{line_number}: "
                "source_file must be a non-empty string"
            )
        entry["source_file"] = _normalise_relative_path(entry["source_file"])
        if isinstance(entry.get("label_file"), str):
            entry["label_file"] = _normalise_relative_path(entry["label_file"])
        entries.append(entry)
    return entries


def existing_counter_maxima(entries: list[dict]) -> dict[str, int]:
    """Return the greatest numeric suffix already allocated in each bucket."""
    maxima: dict[str, int] = {}
    for entry in entries:
        dataset_id = entry.get("id")
        if not isinstance(dataset_id, str):
            continue
        match = _DATASET_ID_RE.fullmatch(dataset_id)
        if not match:
            continue
        bucket = match.group("bucket")
        maxima[bucket] = max(maxima.get(bucket, 0), int(match.group("index")))
    return maxima


def _allocate_identity(bucket: str, counters: dict[str, int]) -> tuple[str, str]:
    counters[bucket] = counters.get(bucket, 0) + 1
    dataset_id = f"{bucket}_{counters[bucket]:03d}"
    return dataset_id, f"training/{bucket}/{dataset_id}_label.json"


def _can_reuse_identity(
    entry: dict,
    bucket: str,
    id_counts: Counter,
    label_counts: Counter,
) -> bool:
    """Reuse a forced row only when it cannot overwrite another sample."""
    dataset_id = entry.get("id")
    label_file = entry.get("label_file")
    if not isinstance(dataset_id, str) or not isinstance(label_file, str):
        return False
    match = _DATASET_ID_RE.fullmatch(dataset_id)
    if not match or match.group("bucket") != bucket:
        return False
    expected = f"training/{bucket}/{dataset_id}_label.json"
    return (
        _normalise_relative_path(label_file) == expected
        and id_counts[dataset_id] == 1
        and label_counts[expected] == 1
    )


def _atomic_write_text(path: Path, content: str) -> None:
    """Write a complete file via an atomic same-directory replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_manifest_atomic(manifest_path: Path, entries: list[dict]) -> None:
    """Atomically write stable JSONL ordered by canonical source path."""
    ordered = sorted(
        entries,
        key=lambda entry: (
            str(entry.get("source_file", "")).casefold(),
            str(entry.get("source_file", "")),
        ),
    )
    content = "".join(
        json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        for entry in ordered
    )
    _atomic_write_text(manifest_path, content)


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
    try:
        existing_entries = load_manifest(manifest_path)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    existing_manifest: dict[str, dict] = {
        entry["source_file"]: entry
        for entry in existing_entries
        if isinstance(entry.get("source_file"), str)
    }
    counters = existing_counter_maxima(existing_entries)
    id_counts = Counter(
        entry.get("id")
        for entry in existing_entries
        if isinstance(entry.get("id"), str)
    )
    label_counts = Counter(
        _normalise_relative_path(entry["label_file"])
        for entry in existing_entries
        if isinstance(entry.get("label_file"), str)
    )
    new_entries: list[dict] = []

    for img_path in images:
        rel = img_path.relative_to(data_dir).as_posix()

        if not args.force and rel in existing_manifest:
            print(f"  skip (cached)  {rel}")
            continue

        # Determine folder hint for bucket
        folder_name = img_path.parent.name.lower()
        folder_hint = FOLDER_TYPE_HINTS.get(folder_name, "unknown")

        print(f"  extracting     {rel} ...", end=" ", flush=True)
        label = extractor.extract(img_path, source_label=rel)

        bucket = bucket_for(label, folder_hint)
        previous = existing_manifest.get(rel)
        if previous and _can_reuse_identity(previous, bucket, id_counts, label_counts):
            dataset_id = previous["id"]
            label_rel = _normalise_relative_path(previous["label_file"])
        else:
            dataset_id, label_rel = _allocate_identity(bucket, counters)

        # A collided legacy identity is never reused, because doing so could
        # overwrite the label belonging to a different source image.
        label_path = data_dir.joinpath(*label_rel.split("/"))
        _atomic_write_text(
            label_path,
            json.dumps(label, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

        entry = {
            "id": dataset_id,
            "source_file": rel,
            "label_file": label_rel,
            "building_type": label.get("building_type", "unknown"),
            "image_type": label.get("image_type", "unknown"),
            "bedrooms": label.get("bedrooms"),
            "floors": label.get("floors"),
            "confidence": label.get("confidence", 0.0),
        }
        new_entries.append(entry)
        existing_manifest[rel] = entry
        print(f"-> {label_rel}  (conf={label.get('confidence', 0):.2f})")

    # Replace the manifest as one deterministic snapshot. In --force mode a
    # source row is replaced in existing_manifest instead of being appended.
    if new_entries:
        write_manifest_atomic(manifest_path, list(existing_manifest.values()))
        print(f"\nWrote or updated {len(new_entries)} label(s) in {training_dir}")
    else:
        print("\nNothing new to process.")

    # Summary
    all_entries = list(existing_manifest.values())
    print(f"\nDataset size: {len(all_entries)} total examples")
    buckets: dict[str, int] = {}
    for e in all_entries:
        bt = e.get("building_type", "unknown")
        buckets[bt] = buckets.get(bt, 0) + 1
    for bt, count in sorted(buckets.items()):
        print(f"  {bt}: {count}")


if __name__ == "__main__":
    main()
