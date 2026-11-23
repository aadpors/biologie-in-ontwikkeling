#!/usr/bin/env python3
"""Non-destructive content QA for the staged Claude biology-exam dataset.

This audit deliberately does not rewrite extracted questions or answer keys.
It detects suspicious extraction artefacts so a reviewer can compare each
finding with the original question booklet and official marking scheme.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

# These phrases belong to the administrative pages after the marking scheme,
# not to an individual candidate answer or scoring rubric.
TAIL_MARKERS = (
    "Aanleveren scores",
    "Bronvermeldingen",
    "Cito gebruikt deze gegevens",
    "►►►",
)

# A one-character answer in an open question is unusual. It may be a wrongly
# classified multiple-choice question, or an OCR/extraction error; never guess.
SINGLE_LETTER = re.compile(r"^\s*(?:\(alleen de letter\)\s*)?[A-Z]\s*$", re.IGNORECASE)


def audit_dataset(data_dir: Path) -> tuple[list[dict], dict]:
    """Inspect all exam JSON files and return findings plus aggregate counts."""
    findings: list[dict] = []
    totals = Counter()
    json_files = sorted(data_dir.glob("*.json"))

    for json_path in json_files:
        exam = json.loads(json_path.read_text(encoding="utf-8"))
        exam_name = json_path.stem
        questions = exam.get("questions", [])
        totals["exams"] += 1
        totals["questions"] += len(questions)

        # Check that question numbering is complete and remains in document order.
        numbers = [q.get("number") for q in questions]
        expected = list(range(1, len(questions) + 1))
        if numbers != expected:
            findings.append({
                "severity": "error", "exam": exam_name, "question": None,
                "code": "QUESTION_SEQUENCE",
                "detail": f"Vraagnummering/order wijkt af: {numbers[:8]} …",
            })

        context_ids = {c.get("id") for c in exam.get("contexts", [])}
        source_names = {
            d.get("filename") for d in exam.get("source_documents", [])
            if d.get("filename")
        }

        for question in questions:
            qid = question.get("id", f"{exam_name}-?")
            totals[f"type:{question.get('type', 'missing')}"] += 1
            answer = question.get("answer_data") or {}
            raw_text = str(answer.get("raw_text") or "")
            model_answer = str(answer.get("model_answer") or "")

            # Context references must resolve to a context declared by this exam.
            missing_contexts = sorted(set(question.get("context_ids", [])) - context_ids)
            if missing_contexts:
                findings.append({
                    "severity": "error", "exam": exam_name, "question": qid,
                    "code": "UNKNOWN_CONTEXT",
                    "detail": f"Niet-bestaande context-ID(s): {', '.join(missing_contexts)}",
                })

            # Each source fragment must refer to a declared PDF and a valid page.
            for fragment in question.get("source_fragments", []):
                if fragment.get("source_pdf") not in source_names:
                    findings.append({
                        "severity": "error", "exam": exam_name, "question": qid,
                        "code": "UNKNOWN_SOURCE_PDF",
                        "detail": f"Bron-PDF ontbreekt in metadata: {fragment.get('source_pdf')}",
                    })
                    break
                coordinates = fragment.get("coordinates") or {}
                x, y = coordinates.get("x"), coordinates.get("y")
                width, height = coordinates.get("width"), coordinates.get("height")
                if all(isinstance(v, (int, float)) for v in (x, y, width, height)):
                    if min(x, y, width, height) < 0 or x + width > 1.001 or y + height > 1.001:
                        findings.append({
                            "severity": "error", "exam": exam_name, "question": qid,
                            "code": "INVALID_CROP_COORDINATES",
                            "detail": f"Fragment valt buiten de pagina: {coordinates}",
                        })
                        break

            # Administrative tail text indicates that extraction crossed the
            # boundary between the final marking-scheme answer and end matter.
            marker = next((m for m in TAIL_MARKERS if m.lower() in raw_text.lower()), None)
            if marker:
                findings.append({
                    "severity": "warning", "exam": exam_name, "question": qid,
                    "code": "ANSWER_TAIL_CONTAMINATION",
                    "detail": f"raw_text bevat documenteinde/administratieve tekst vanaf marker '{marker}'.",
                })

            # Open answers must contain both the full source text and a usable model answer.
            if question.get("type") == "open":
                if not raw_text.strip() or not model_answer.strip():
                    findings.append({
                        "severity": "error", "exam": exam_name, "question": qid,
                        "code": "OPEN_ANSWER_MISSING",
                        "detail": "Open vraag mist raw_text of model_answer.",
                    })

            # The question's score and the extracted marking-scheme maximum must agree.
            question_max = question.get("max_points_exam")
            answer_max = answer.get("maximum_score")
            if isinstance(question_max, (int, float)) and isinstance(answer_max, (int, float)):
                if question_max != answer_max:
                    findings.append({
                        "severity": "error", "exam": exam_name, "question": qid,
                        "code": "MAXIMUM_SCORE_MISMATCH",
                        "detail": f"Vraagmetadata={question_max}, antwoordgegevens={answer_max}.",
                    })

            # Fragment order is the intended reading order in the assembled image.
            fragment_orders = [f.get("order") for f in question.get("source_fragments", [])]
            if fragment_orders and fragment_orders != list(range(1, len(fragment_orders) + 1)):
                findings.append({
                    "severity": "error", "exam": exam_name, "question": qid,
                    "code": "FRAGMENT_ORDER",
                    "detail": f"Bronfragmentvolgorde is niet opeenvolgend: {fragment_orders}.",
                })

            # Every image reference must resolve relative to the dataset root.
            snippet_path = question.get("snippet_file")
            if snippet_path and not (data_dir.parent / snippet_path).is_file():
                findings.append({
                    "severity": "error", "exam": exam_name, "question": qid,
                    "code": "MISSING_SNIPPET_FILE",
                    "detail": f"PNG-bestand niet gevonden: {snippet_path}.",
                })

            # Open questions with a single-letter key need manual verification.
            if question.get("type") == "open" and SINGLE_LETTER.fullmatch(model_answer):
                findings.append({
                    "severity": "warning", "exam": exam_name, "question": qid,
                    "code": "SINGLE_LETTER_OPEN_ANSWER",
                    "detail": f"Open vraag heeft enkelletterig modelantwoord '{model_answer.strip()}'; controleer vraagtype en antwoordsleutel.",
                })

            # An MCQ without an explicit key cannot be scored reliably.
            if question.get("type") == "mcq" and answer.get("correct_answer") is None:
                findings.append({
                    "severity": "error", "exam": exam_name, "question": qid,
                    "code": "MCQ_WITHOUT_CORRECT_ANSWER",
                    "detail": "Meerkeuzevraag heeft geen expliciet correct_answer.",
                })

    totals["findings"] = len(findings)
    totals["errors"] = sum(f["severity"] == "error" for f in findings)
    totals["warnings"] = sum(f["severity"] == "warning" for f in findings)
    return findings, dict(totals)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("exam-data/claude-2024-2026/data"))
    parser.add_argument("--output", type=Path, help="Optioneel Markdown-rapportbestand.")
    args = parser.parse_args()

    findings, totals = audit_dataset(args.data_dir)
    lines = [
        "# Geautomatiseerde inhoudelijke dataset-audit",
        "",
        "Dit rapport signaleert verdachte extracties; het vervangt geen vergelijking met de originele PDF's.",
        "",
        f"- Examens: {totals.get('exams', 0)}",
        f"- Vragen: {totals.get('questions', 0)}",
        f"- Fouten: {totals.get('errors', 0)}",
        f"- Waarschuwingen: {totals.get('warnings', 0)}",
        "",
        "| Ernst | Examen | Vraag | Code | Bevinding |",
        "|---|---|---|---|---|",
    ]
    for item in findings:
        detail = item["detail"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {item['severity']} | {item['exam']} | {item['question'] or '—'} "
            f"| {item['code']} | {detail} |"
        )
    if not findings:
        lines.append("| — | — | — | — | Geen structurele afwijkingen gevonden. |")

    report = "\n".join(lines) + "\n"
    print(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    # Warnings remain visible without making an unreviewed dataset look like a
    # failed software build. Structural errors do fail the command.
    return 1 if totals.get("errors", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
