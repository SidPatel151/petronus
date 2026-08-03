from __future__ import annotations

import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts import generate_training_data as generator
from scripts.validate_training_data import validate_dataset


def _label(source_file: str, *, confidence: float = 0.9, notes: str = "fixture") -> dict:
    return {
        "image_type": "floor_plan",
        "building_type": "adu",
        "bedrooms": 1,
        "bathrooms": 1,
        "half_baths": 0,
        "floors": 1,
        "total_sqft": 400,
        "footprint_ft": {"width": 20.0, "depth": 20.0},
        "style": "modern",
        "facade_material": None,
        "rooms": [
            {
                "type": "kitchen",
                "floor": 0,
                "approx_sqft": 100,
                "position": "rear_right",
            }
        ],
        "stair": {"present": False, "location": None, "direction": None},
        "wet_wall_location": "rear_right",
        "has_garage": False,
        "entry_side": "front",
        "confidence": confidence,
        "notes": notes,
        "source_file": source_file,
    }


def _manifest_entry(
    source_file: str,
    *,
    dataset_id: str = "adu_001",
    label_file: str | None = None,
    confidence: float = 0.9,
) -> dict:
    return {
        "id": dataset_id,
        "source_file": source_file,
        "label_file": label_file or f"training/adu/{dataset_id}_label.json",
        "building_type": "adu",
        "image_type": "floor_plan",
        "bedrooms": 1,
        "floors": 1,
        "confidence": confidence,
    }


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_manifest(data_dir: Path, entries: list[dict]) -> Path:
    manifest_path = data_dir / "training" / "manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )
    return manifest_path


def _read_manifest(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _run_generator(monkeypatch, data_dir: Path, *, force: bool = False) -> None:
    class FakeExtractor:
        def __init__(self, **_kwargs):
            pass

        def extract(self, _image_path, source_label=None):
            return _label(source_label)

    monkeypatch.setattr(generator, "BlueprintExtractor", FakeExtractor)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    argv = ["generate_training_data.py", "--data-dir", str(data_dir)]
    if force:
        argv.append("--force")
    monkeypatch.setattr(sys, "argv", argv)
    generator.main()


def test_new_ids_continue_after_existing_maximum_and_manifest_is_atomic(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    existing_source = "ADUs/a_existing.png"
    new_source = "ADUs/z_new.png"
    for source in (existing_source, new_source):
        path = data_dir.joinpath(*source.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")

    existing = _manifest_entry(existing_source, dataset_id="adu_007")
    existing["source_file"] = r"ADUs\a_existing.png"
    manifest_path = _write_manifest(data_dir, [existing])
    _write_json(data_dir / existing["label_file"], _label(existing_source))

    real_replace = generator.os.replace
    replace_destinations: list[Path] = []

    def replace_spy(source, destination):
        replace_destinations.append(Path(destination))
        return real_replace(source, destination)

    monkeypatch.setattr(generator.os, "replace", replace_spy)
    _run_generator(monkeypatch, data_dir)

    rows = _read_manifest(manifest_path)
    assert [row["source_file"] for row in rows] == [existing_source, new_source]
    assert rows[0]["id"] == "adu_007"
    assert rows[1]["id"] == "adu_008"
    assert rows[1]["label_file"] == "training/adu/adu_008_label.json"
    assert (data_dir / "training" / "adu" / "adu_008_label.json").is_file()
    assert manifest_path in replace_destinations
    assert not list(data_dir.rglob("*.tmp"))


def test_force_replaces_source_row_and_is_deterministic(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    source = "ADUs/sample.png"
    image_path = data_dir.joinpath(*source.split("/"))
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"image")

    existing = _manifest_entry(source, dataset_id="adu_005")
    manifest_path = _write_manifest(data_dir, [existing])
    label_path = data_dir / existing["label_file"]
    _write_json(label_path, _label(source, notes="old"))

    _run_generator(monkeypatch, data_dir, force=True)
    first_manifest = manifest_path.read_text(encoding="utf-8")
    rows = _read_manifest(manifest_path)
    assert len(rows) == 1
    assert rows[0]["id"] == "adu_005"
    assert json.loads(label_path.read_text(encoding="utf-8"))["notes"] == "fixture"

    _run_generator(monkeypatch, data_dir, force=True)
    assert manifest_path.read_text(encoding="utf-8") == first_manifest
    assert len(_read_manifest(manifest_path)) == 1


def test_force_allocates_new_ids_for_collided_legacy_rows(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    sources = ["ADUs/a.png", "ADUs/b.png"]
    for source in sources:
        image_path = data_dir.joinpath(*source.split("/"))
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"image")

    collided_label = "training/adu/adu_001_label.json"
    manifest_path = _write_manifest(
        data_dir,
        [
            _manifest_entry(sources[0], dataset_id="adu_001", label_file=collided_label),
            _manifest_entry(sources[1], dataset_id="adu_001", label_file=collided_label),
        ],
    )
    _write_json(data_dir / collided_label, _label(sources[1]))

    _run_generator(monkeypatch, data_dir, force=True)

    rows = _read_manifest(manifest_path)
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {"adu_002", "adu_003"}
    assert len({row["label_file"] for row in rows}) == 2
    assert all((data_dir / row["label_file"]).is_file() for row in rows)


def test_validator_accepts_consistent_dataset_with_gold_sample(tmp_path):
    data_dir = tmp_path / "data"
    source = "ADUs/sample.png"
    image_path = data_dir.joinpath(*source.split("/"))
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"image")

    entry = _manifest_entry(source)
    _write_manifest(data_dir, [entry])
    _write_json(data_dir / entry["label_file"], _label(source))
    (data_dir / "training" / "gold_manifest.jsonl").write_text(
        json.dumps({"source_file": source}) + "\n", encoding="utf-8"
    )

    report = validate_dataset(data_dir)

    assert report.ok
    assert not report.errors
    assert not report.warnings
    assert report.stats == {
        "manifest_entries": 1,
        "raw_images": 1,
        "label_files": 1,
        "errors": 0,
        "warnings": 0,
    }


def test_validator_reports_integrity_and_quality_failures(tmp_path):
    data_dir = tmp_path / "data"
    for source in ("ADUs/a.png", "ADUs/b.png"):
        image_path = data_dir.joinpath(*source.split("/"))
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"image")

    shared_label = "training/adu/adu_001_label.json"
    invalid_label = "training/adu/adu_002_label.json"
    entries = [
        _manifest_entry(
            "ADUs/a.png", dataset_id="adu_001", label_file=shared_label, confidence=0.5
        ),
        _manifest_entry(
            "ADUs/missing.png", dataset_id="adu_001", label_file=shared_label
        ),
        _manifest_entry("ADUs/b.png", dataset_id="adu_002", label_file=invalid_label),
        {"id": ""},
    ]
    manifest_path = _write_manifest(data_dir, entries)
    with manifest_path.open("a", encoding="utf-8") as handle:
        handle.write("{not-json}\n")
    _write_json(data_dir / shared_label, _label("ADUs/someone-else.png"))
    invalid_path = data_dir / invalid_label
    invalid_path.parent.mkdir(parents=True, exist_ok=True)
    invalid_path.write_text("{not-json}", encoding="utf-8")

    report = validate_dataset(data_dir)
    error_codes = {finding.code for finding in report.errors}
    warning_codes = {finding.code for finding in report.warnings}

    assert {
        "INVALID_MANIFEST_JSON",
        "MANIFEST_SCHEMA",
        "DUPLICATE_ID",
        "DUPLICATE_LABEL",
        "MISSING_SOURCE",
        "LABEL_SOURCE_MISMATCH",
        "INVALID_LABEL_JSON",
    } <= error_codes
    assert {"LOW_CONFIDENCE", "GOLD_SET_MISSING"} <= warning_codes
