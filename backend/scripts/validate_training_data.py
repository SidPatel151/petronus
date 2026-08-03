"""Validate the blueprint-image training dataset without modifying it.

Usage from ``backend/``::

    python scripts/validate_training_data.py --data-dir app/data

Integrity failures return exit code 1. Quality warnings (low confidence or a
missing/incomplete human-reviewed gold set) are reported but do not fail the
command unless ``--warnings-as-errors`` is supplied.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Iterable, Optional


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_IMAGE_TYPES = {"floor_plan", "exterior_photo", "3d_render", "sketch", "unknown"}
ALLOWED_BUILDING_TYPES = {"adu", "sfr", "victorian", "townhouse", "unknown"}
MANIFEST_REQUIRED_FIELDS = {
    "id",
    "source_file",
    "label_file",
    "building_type",
    "image_type",
    "confidence",
}
LABEL_REQUIRED_FIELDS = {
    "source_file",
    "image_type",
    "building_type",
    "rooms",
    "confidence",
}


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    path: Optional[str] = None
    line: Optional[int] = None

    def render(self) -> str:
        location = self.path or "dataset"
        if self.line is not None:
            location = f"{location}:{self.line}"
        return f"{self.severity.upper()} [{self.code}] {location}: {self.message}"


@dataclass
class ValidationReport:
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(
        self, code: str, message: str, *, path: Optional[str] = None, line: Optional[int] = None
    ) -> None:
        self.errors.append(Finding("error", code, message, path, line))

    def warning(
        self, code: str, message: str, *, path: Optional[str] = None, line: Optional[int] = None
    ) -> None:
        self.warnings.append(Finding("warning", code, message, path, line))


def _normalise_relative_path(value: str) -> str:
    normalised = value.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def _resolve_relative(root: Path, value: Any) -> Optional[Path]:
    if not isinstance(value, str) or not value.strip():
        return None
    normalised = _normalise_relative_path(value)
    relative = PurePosixPath(normalised)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        return None
    if relative.parts and ":" in relative.parts[0]:
        return None
    candidate = root.joinpath(*relative.parts).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _load_jsonl(
    path: Path,
    report: ValidationReport,
    *,
    missing_code: str,
    invalid_code: str,
) -> list[tuple[int, dict]]:
    if not path.is_file():
        report.error(missing_code, "file does not exist", path=str(path))
        return []

    rows: list[tuple[int, dict]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        report.error(invalid_code, f"cannot read file: {exc}", path=str(path))
        return rows

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            report.error(invalid_code, f"invalid JSON: {exc.msg}", path=str(path), line=line_number)
            continue
        if not isinstance(value, dict):
            report.error(invalid_code, "row must be a JSON object", path=str(path), line=line_number)
            continue
        rows.append((line_number, value))
    return rows


def _validate_manifest_schema(
    entry: dict, line_number: int, manifest_path: Path, report: ValidationReport
) -> None:
    missing = sorted(MANIFEST_REQUIRED_FIELDS - entry.keys())
    if missing:
        report.error(
            "MANIFEST_SCHEMA",
            f"missing required fields: {', '.join(missing)}",
            path=str(manifest_path),
            line=line_number,
        )

    for field_name in ("id", "source_file", "label_file", "building_type", "image_type"):
        if field_name in entry and (
            not isinstance(entry[field_name], str) or not entry[field_name].strip()
        ):
            report.error(
                "MANIFEST_SCHEMA",
                f"{field_name} must be a non-empty string",
                path=str(manifest_path),
                line=line_number,
            )

    confidence = entry.get("confidence")
    if "confidence" in entry and (
        not _is_number(confidence) or not 0 <= confidence <= 1
    ):
        report.error(
            "MANIFEST_SCHEMA",
            "confidence must be a number between 0 and 1",
            path=str(manifest_path),
            line=line_number,
        )
    if entry.get("image_type") not in ALLOWED_IMAGE_TYPES:
        report.error(
            "MANIFEST_SCHEMA",
            f"unsupported image_type {entry.get('image_type')!r}",
            path=str(manifest_path),
            line=line_number,
        )
    if entry.get("building_type") not in ALLOWED_BUILDING_TYPES:
        report.error(
            "MANIFEST_SCHEMA",
            f"unsupported building_type {entry.get('building_type')!r}",
            path=str(manifest_path),
            line=line_number,
        )


def _validate_label_schema(label: Any, label_rel: str, report: ValidationReport) -> None:
    if not isinstance(label, dict):
        report.error("LABEL_SCHEMA", "label must be a JSON object", path=label_rel)
        return

    missing = sorted(LABEL_REQUIRED_FIELDS - label.keys())
    if missing:
        report.error(
            "LABEL_SCHEMA", f"missing required fields: {', '.join(missing)}", path=label_rel
        )

    if label.get("image_type") not in ALLOWED_IMAGE_TYPES:
        report.error(
            "LABEL_SCHEMA", f"unsupported image_type {label.get('image_type')!r}", path=label_rel
        )
    if label.get("building_type") not in ALLOWED_BUILDING_TYPES:
        report.error(
            "LABEL_SCHEMA",
            f"unsupported building_type {label.get('building_type')!r}",
            path=label_rel,
        )
    if not isinstance(label.get("source_file"), str) or not label.get("source_file"):
        report.error("LABEL_SCHEMA", "source_file must be a non-empty string", path=label_rel)

    confidence = label.get("confidence")
    if not _is_number(confidence) or not 0 <= confidence <= 1:
        report.error(
            "LABEL_SCHEMA", "confidence must be a number between 0 and 1", path=label_rel
        )

    rooms = label.get("rooms")
    if not isinstance(rooms, list):
        report.error("LABEL_SCHEMA", "rooms must be a list", path=label_rel)
    else:
        for index, room in enumerate(rooms):
            if not isinstance(room, dict):
                report.error(
                    "LABEL_SCHEMA", f"rooms[{index}] must be an object", path=label_rel
                )
                continue
            if not isinstance(room.get("type"), str) or not room.get("type"):
                report.error(
                    "LABEL_SCHEMA", f"rooms[{index}].type must be a string", path=label_rel
                )
            floor = room.get("floor")
            if not isinstance(floor, int) or isinstance(floor, bool) or floor < 0:
                report.error(
                    "LABEL_SCHEMA",
                    f"rooms[{index}].floor must be a non-negative integer",
                    path=label_rel,
                )

    footprint = label.get("footprint_ft")
    if footprint is not None:
        if not isinstance(footprint, dict):
            report.error("LABEL_SCHEMA", "footprint_ft must be an object or null", path=label_rel)
        else:
            for dimension in ("width", "depth"):
                value = footprint.get(dimension)
                if value is not None and (not _is_number(value) or value <= 0):
                    report.error(
                        "LABEL_SCHEMA",
                        f"footprint_ft.{dimension} must be positive or null",
                        path=label_rel,
                    )


def _report_duplicates(
    rows: Iterable[tuple[int, dict]],
    field_name: str,
    code: str,
    manifest_path: Path,
    report: ValidationReport,
) -> None:
    locations: dict[str, list[int]] = defaultdict(list)
    for line_number, entry in rows:
        value = entry.get(field_name)
        if isinstance(value, str) and value:
            if field_name in ("source_file", "label_file"):
                value = _normalise_relative_path(value)
            locations[value].append(line_number)
    for value, line_numbers in sorted(locations.items()):
        if len(line_numbers) > 1:
            report.error(
                code,
                f"{field_name} {value!r} occurs on lines {line_numbers}",
                path=str(manifest_path),
            )


def _validate_gold_set(
    gold_path: Path,
    manifest_rows: list[tuple[int, dict]],
    confidence_threshold: float,
    report: ValidationReport,
) -> None:
    if not gold_path.is_file():
        report.warning(
            "GOLD_SET_MISSING",
            "no human-reviewed gold manifest; create JSONL rows containing id or source_file",
            path=str(gold_path),
        )
        return

    gold_rows = _load_jsonl(
        gold_path,
        report,
        missing_code="GOLD_SET_MISSING",
        invalid_code="INVALID_GOLD_JSON",
    )
    if not gold_rows:
        report.warning("GOLD_SET_EMPTY", "gold manifest contains no valid rows", path=str(gold_path))
        return

    by_id = {entry.get("id"): entry for _, entry in manifest_rows if isinstance(entry.get("id"), str)}
    by_source = {
        _normalise_relative_path(entry["source_file"]): entry
        for _, entry in manifest_rows
        if isinstance(entry.get("source_file"), str)
    }
    matched: list[dict] = []
    for line_number, gold_entry in gold_rows:
        sample = None
        if isinstance(gold_entry.get("source_file"), str):
            sample = by_source.get(_normalise_relative_path(gold_entry["source_file"]))
        elif isinstance(gold_entry.get("id"), str):
            sample = by_id.get(gold_entry["id"])
        else:
            report.error(
                "GOLD_REFERENCE_INVALID",
                "gold row must contain id or source_file",
                path=str(gold_path),
                line=line_number,
            )
            continue
        if sample is None:
            report.error(
                "GOLD_REFERENCE_MISSING",
                "gold row does not match a manifest sample",
                path=str(gold_path),
                line=line_number,
            )
            continue
        matched.append(sample)
        confidence = sample.get("confidence")
        if _is_number(confidence) and confidence < confidence_threshold:
            report.warning(
                "GOLD_LOW_CONFIDENCE",
                f"gold sample {sample.get('id')!r} has confidence {confidence:.2f}",
                path=str(gold_path),
                line=line_number,
            )

    if matched and not any(entry.get("image_type") == "floor_plan" for entry in matched):
        report.warning(
            "GOLD_SET_COVERAGE", "gold set contains no floor-plan sample", path=str(gold_path)
        )
    manifest_types = {
        entry.get("building_type")
        for _, entry in manifest_rows
        if entry.get("building_type") in ALLOWED_BUILDING_TYPES - {"unknown"}
    }
    gold_types = {entry.get("building_type") for entry in matched}
    missing_types = sorted(manifest_types - gold_types)
    if matched and missing_types:
        report.warning(
            "GOLD_SET_COVERAGE",
            f"gold set has no samples for: {', '.join(missing_types)}",
            path=str(gold_path),
        )


def validate_dataset(
    data_dir: Path,
    *,
    confidence_threshold: float = 0.75,
    gold_manifest: Optional[Path] = None,
) -> ValidationReport:
    """Return all dataset errors and warnings without writing to disk."""
    data_dir = data_dir.resolve()
    training_dir = data_dir / "training"
    manifest_path = training_dir / "manifest.jsonl"
    report = ValidationReport()

    rows = _load_jsonl(
        manifest_path,
        report,
        missing_code="MANIFEST_MISSING",
        invalid_code="INVALID_MANIFEST_JSON",
    )
    report.stats["manifest_entries"] = len(rows)
    for line_number, entry in rows:
        _validate_manifest_schema(entry, line_number, manifest_path, report)

    _report_duplicates(rows, "id", "DUPLICATE_ID", manifest_path, report)
    _report_duplicates(rows, "label_file", "DUPLICATE_LABEL", manifest_path, report)
    _report_duplicates(rows, "source_file", "DUPLICATE_SOURCE", manifest_path, report)

    raw_images = {
        path.relative_to(data_dir).as_posix()
        for path in data_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in IMAGE_SUFFIXES
        and "training" not in path.relative_to(data_dir).parts
    }
    report.stats["raw_images"] = len(raw_images)
    manifest_sources: set[str] = set()
    referenced_labels: set[str] = set()
    label_cache: dict[str, Optional[dict]] = {}

    for line_number, entry in rows:
        source_rel = entry.get("source_file")
        label_rel = entry.get("label_file")

        if isinstance(source_rel, str):
            source_rel = _normalise_relative_path(source_rel)
            manifest_sources.add(source_rel)
            source_path = _resolve_relative(data_dir, source_rel)
            if source_path is None:
                report.error(
                    "INVALID_SOURCE_PATH",
                    f"source_file is not a safe relative path: {source_rel!r}",
                    path=str(manifest_path),
                    line=line_number,
                )
            elif not source_path.is_file():
                report.error(
                    "MISSING_SOURCE",
                    f"source image does not exist: {source_rel}",
                    path=str(manifest_path),
                    line=line_number,
                )

        confidence = entry.get("confidence")
        if _is_number(confidence) and confidence < confidence_threshold:
            report.warning(
                "LOW_CONFIDENCE",
                f"sample {entry.get('id')!r} confidence {confidence:.2f} is below "
                f"{confidence_threshold:.2f}",
                path=str(manifest_path),
                line=line_number,
            )

        if not isinstance(label_rel, str):
            continue
        label_rel = _normalise_relative_path(label_rel)
        referenced_labels.add(label_rel)
        label_path = _resolve_relative(data_dir, label_rel)
        if label_path is None:
            report.error(
                "INVALID_LABEL_PATH",
                f"label_file is not a safe relative path: {label_rel!r}",
                path=str(manifest_path),
                line=line_number,
            )
            continue
        if not label_path.is_file():
            report.error(
                "MISSING_LABEL",
                f"label file does not exist: {label_rel}",
                path=str(manifest_path),
                line=line_number,
            )
            continue

        if label_rel not in label_cache:
            try:
                value = json.loads(label_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                report.error("INVALID_LABEL_JSON", f"cannot parse label: {exc}", path=label_rel)
                label_cache[label_rel] = None
            else:
                label_cache[label_rel] = value
                _validate_label_schema(value, label_rel, report)
        label = label_cache[label_rel]
        if not isinstance(label, dict):
            continue

        label_source = label.get("source_file")
        if isinstance(source_rel, str) and (
            not isinstance(label_source, str)
            or _normalise_relative_path(label_source) != source_rel
        ):
            report.error(
                "LABEL_SOURCE_MISMATCH",
                f"manifest source {source_rel!r} != label source {label_source!r}",
                path=label_rel,
            )
        for field_name in ("building_type", "image_type"):
            if entry.get(field_name) != label.get(field_name):
                report.error(
                    "MANIFEST_LABEL_MISMATCH",
                    f"{field_name} differs: manifest={entry.get(field_name)!r}, "
                    f"label={label.get(field_name)!r}",
                    path=label_rel,
                )
        manifest_confidence = entry.get("confidence")
        label_confidence = label.get("confidence")
        if (
            _is_number(manifest_confidence)
            and _is_number(label_confidence)
            and abs(manifest_confidence - label_confidence) > 1e-9
        ):
            report.error(
                "MANIFEST_LABEL_MISMATCH",
                f"confidence differs: manifest={manifest_confidence!r}, "
                f"label={label_confidence!r}",
                path=label_rel,
            )

    for source_rel in sorted(raw_images - manifest_sources):
        report.warning(
            "UNMANIFESTED_SOURCE", "raw image has no manifest row", path=source_rel
        )

    physical_labels = {
        path.relative_to(data_dir).as_posix()
        for path in training_dir.rglob("*_label.json")
        if path.is_file()
    } if training_dir.is_dir() else set()
    report.stats["label_files"] = len(physical_labels)
    for label_rel in sorted(physical_labels - referenced_labels):
        report.warning("ORPHAN_LABEL", "label file is not referenced by the manifest", path=label_rel)

    gold_path = gold_manifest or (training_dir / "gold_manifest.jsonl")
    if not gold_path.is_absolute():
        gold_path = data_dir / gold_path
    _validate_gold_set(gold_path, rows, confidence_threshold, report)

    report.stats["errors"] = len(report.errors)
    report.stats["warnings"] = len(report.warnings)
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate blueprint training data")
    parser.add_argument(
        "--data-dir", default="app/data", help="Root data directory (default: app/data)"
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.75,
        help="Warn below this confidence value (default: 0.75)",
    )
    parser.add_argument(
        "--gold-manifest",
        type=Path,
        default=None,
        help="Optional human-reviewed gold JSONL (default: training/gold_manifest.jsonl)",
    )
    parser.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Return failure when quality warnings are present",
    )
    args = parser.parse_args(argv)
    if not 0 <= args.confidence_threshold <= 1:
        parser.error("--confidence-threshold must be between 0 and 1")

    report = validate_dataset(
        Path(args.data_dir),
        confidence_threshold=args.confidence_threshold,
        gold_manifest=args.gold_manifest,
    )
    print(
        "Dataset: "
        f"{report.stats.get('raw_images', 0)} images, "
        f"{report.stats.get('manifest_entries', 0)} manifest rows, "
        f"{report.stats.get('label_files', 0)} label files"
    )
    for finding in report.errors:
        print(finding.render())
    for finding in report.warnings:
        print(finding.render())
    print(f"Result: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return 1 if report.errors or (args.warnings_as_errors and report.warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
