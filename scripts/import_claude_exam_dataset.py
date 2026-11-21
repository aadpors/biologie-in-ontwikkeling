#!/usr/bin/env python3
"""Validate and stage the Claude exam dataset without touching the live exam data.

Usage:
  python scripts/import_claude_exam_dataset.py dataset.zip --output-dir /tmp/exam-stage
  python scripts/import_claude_exam_dataset.py dataset.zip --output-dir exam-data/claude-2024-2026

The importer is deliberately non-destructive: it refuses to overwrite an existing
output directory. It validates the archive manifest, SHA-256 checksums, JSON
structure, question IDs, question-to-snippet links, and image signatures before
copying anything into the destination.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

ROOT_NAME = "biologie-examens-havo-vwo-2024-2026"
EXPECTED_EXAMS = {
    f"{level}-{year}-t{period}"
    for level in ("havo", "vwo")
    for year in (2024, 2025, 2026)
    for period in (1, 2)
}
REQUIRED_QUESTION_FIELDS = {
    "id", "number", "main_question_number", "type", "context_ids",
    "snippet_file", "snippet_size_px", "max_points_exam", "source_fragments",
    "answer_data", "quality_check",
}


class DatasetError(Exception):
    """Raised when source data is incomplete, inconsistent, or unsafe."""


def sha256(data: bytes) -> str:
    """Return the lowercase SHA-256 digest used by the supplied manifest."""
    return hashlib.sha256(data).hexdigest()


def safe_archive_path(name: str) -> PurePosixPath:
    """Reject absolute paths, parent traversal, and platform-specific escapes."""
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise DatasetError(f"Unsafe path in ZIP: {name!r}")
    if re.match(r"^[A-Za-z]:", name):
        raise DatasetError(f"Drive-qualified path in ZIP: {name!r}")
    return path


def validate_and_stage(zip_path: Path, output_dir: Path) -> dict:
    """Validate all declared files first; only then stage a clean dataset copy."""
    if output_dir.exists():
        raise DatasetError(f"Output directory already exists; refusing overwrite: {output_dir}")
    if not zipfile.is_zipfile(zip_path):
        raise DatasetError(f"Not a valid ZIP archive: {zip_path}")

    with zipfile.ZipFile(zip_path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise DatasetError(f"ZIP CRC check failed for {bad_member}")

        names = archive.namelist()
        prefix = ROOT_NAME + "/"
        if not any(name.startswith(prefix) for name in names):
            raise DatasetError(f"Expected top-level directory {ROOT_NAME}/")

        manifest_path = prefix + "manifest.json"
        if manifest_path not in names:
            raise DatasetError("manifest.json is missing")
        manifest = json.loads(archive.read(manifest_path))
        if manifest.get("complete") is not True:
            raise DatasetError("Manifest does not mark the dataset as complete")
        if manifest.get("exams_expected") != 12:
            raise DatasetError("Manifest does not declare all 12 expected exams")
        if set(manifest.get("exams_included", [])) != EXPECTED_EXAMS:
            raise DatasetError("Exam list differs from the expected havo/vwo 2024–2026 set")
        if manifest.get("exams_not_included"):
            raise DatasetError("Manifest reports exams that were not included")

        declared = {}
        for item in manifest.get("files", []):
            rel = safe_archive_path(item["path"]).as_posix()
            if rel in declared:
                raise DatasetError(f"Duplicate manifest path: {rel}")
            declared[rel] = item

        actual = {
            name[len(prefix):] for name in names
            if name.startswith(prefix) and not name.endswith("/")
            and name[len(prefix):] != "manifest.json"
        }
        if actual != set(declared):
            missing, extra = sorted(set(declared) - actual), sorted(actual - set(declared))
            raise DatasetError(f"Manifest/file mismatch; missing={missing[:5]}, extra={extra[:5]}")

        payloads = {}
        for rel, item in declared.items():
            data = archive.read(prefix + rel)
            if len(data) != item.get("bytes"):
                raise DatasetError(f"Byte-size mismatch: {rel}")
            if sha256(data) != item.get("sha256"):
                raise DatasetError(f"SHA-256 mismatch: {rel}")
            payloads[rel] = data

        exam_ids, question_ids, snippet_refs = set(), set(), set()
        type_counts = Counter()
        total_questions = 0
        for exam_id in sorted(EXPECTED_EXAMS):
            rel = f"data/{exam_id}.json"
            if rel not in payloads:
                raise DatasetError(f"Missing exam JSON: {rel}")
            data = json.loads(payloads[rel])
            if data.get("schema_version") != "1.0":
                raise DatasetError(f"Unsupported schema version in {rel}")
            exam = data.get("exam", {})
            expected_level, expected_year, expected_period = exam_id.split("-")
            if (exam.get("level"), str(exam.get("year")), str(exam.get("period"))) != (
                expected_level, expected_year, expected_period.removeprefix("t")
            ):
                raise DatasetError(f"Exam metadata does not match filename: {rel}")
            exam_ids.add(exam_id)
            for question in data.get("questions", []):
                missing_fields = REQUIRED_QUESTION_FIELDS - set(question)
                if missing_fields:
                    raise DatasetError(f"{rel}: {question.get('id')} missing {sorted(missing_fields)}")
                qid = question["id"]
                if qid in question_ids:
                    raise DatasetError(f"Duplicate question ID: {qid}")
                question_ids.add(qid)
                if question["type"] not in ("open", "mcq"):
                    raise DatasetError(f"Unknown question type {question['type']!r}: {qid}")
                if not isinstance(question["number"], int) or question["number"] < 1:
                    raise DatasetError(f"Invalid question number: {qid}")
                if not isinstance(question["source_fragments"], list) or not question["source_fragments"]:
                    raise DatasetError(f"Missing source provenance: {qid}")
                snippet = safe_archive_path(question["snippet_file"]).as_posix()
                if not snippet.startswith("snippets/") or snippet not in payloads:
                    raise DatasetError(f"Missing/invalid snippet reference: {qid} -> {snippet}")
                if not payloads[snippet].startswith(b"\x89PNG\r\n\x1a\n"):
                    raise DatasetError(f"Snippet is not a PNG image: {snippet}")
                snippet_refs.add(snippet)
                type_counts[question["type"]] += 1
                total_questions += 1

        if total_questions != manifest.get("questions_included"):
            raise DatasetError(
                f"Question count mismatch: JSON={total_questions}, manifest={manifest.get('questions_included')}"
            )
        if total_questions != manifest.get("questions_expected_total"):
            raise DatasetError("Dataset does not contain the expected total number of questions")
        if len(question_ids) != total_questions:
            raise DatasetError("Question IDs are not unique")
        if len(snippet_refs) != total_questions:
            # One question must resolve to one image; duplicate image reuse needs
            # explicit review instead of being silently accepted.
            raise DatasetError("Question snippets are reused; expected one unique snippet per question")

        # Keep original source layout below this directory. No old files are
        # deleted, renamed, or replaced by this importer.
        output_dir.mkdir(parents=True)
        try:
            for rel, data in payloads.items():
                target = output_dir / Path(*PurePosixPath(rel).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            (output_dir / "manifest.json").write_bytes(archive.read(manifest_path))
        except Exception:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise

    return {
        "exams": len(exam_ids),
        "questions": total_questions,
        "types": dict(type_counts),
        "snippets": len(snippet_refs),
        "output": str(output_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_file", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = validate_and_stage(args.zip_file, args.output_dir)
    except (DatasetError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"DATASET IMPORT FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
