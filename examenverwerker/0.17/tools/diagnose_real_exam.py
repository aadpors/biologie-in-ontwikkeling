"""Maak een visueel diagnosepakket van een echt examen uit de repository.

Dit script draait uitsluitend in CI. Het verandert geen examenbronbestanden en
schrijft de samengestelde afbeelding en detectie-uitvoer naar een aparte
diagnosemap die als workflow-artifact beschikbaar wordt gemaakt.
"""
from __future__ import annotations

import json
import os
import re
import sys

import fitz
from pathlib import Path

# Scriptbestanden worden door Python met hun eigen map als sys.path[0]
# gestart. Voeg daarom expliciet de versiehoofdmap toe om dezelfde package
# te importeren als de normale applicatiestart.
VERSION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VERSION_ROOT))

from examenverwerker.question_detection import detect_question_starts
from examenverwerker.question_fragments import (
    build_stitched_exam,
    propose_stitched_question_selections,
    normalise_stitched_selections,
)
from examenverwerker.main import _nearest_white_row, _white_row_ranges

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "examens" / "vw-1018-a-26-2-o.pdf"
OUTPUT = Path(os.environ.get("EXAM_DIAGNOSTIC_OUTPUT", "/tmp/exam-diagnostic"))
OUTPUT.mkdir(parents=True, exist_ok=True)

if not SOURCE.is_file():
    raise SystemExit(f"Het echte testexamen ontbreekt: {SOURCE}")

# Gebruik de daadwerkelijke vraagstartdetector, niet een handmatig gemaakte lijst.
start_result = detect_question_starts(str(SOURCE))
accepted = [
    item for item in start_result["candidates"]
    if item.get("accepted") and not item.get("removed")
]

# Bouw dezelfde lange afbeelding die stap 3 in de applicatie toont.
stitched_path = OUTPUT / "vw-1018-a-26-2-o-stitched.png"
metadata = build_stitched_exam(SOURCE, stitched_path)
proposals = propose_stitched_question_selections(
    metadata.get("pages", []),
    accepted,
    render_scale=1.25,
    image_height=int(metadata["height"]),
    pdf_path=SOURCE,
)
white_rows = _white_row_ranges(stitched_path)

# Dezelfde witregeluitlijning als de API toepassen en alle broncoördinaten
# bewaren, zodat een menselijke controle precies kan terugvinden wat is voorgesteld.
proposals = normalise_stitched_selections(
    proposals,
    white_rows,
    stitched_path,
    image_height=int(metadata["height"]),
    leading_top=min((float(page["top"]) for page in metadata.get("pages", [])), default=0.0),
)

# Laat de echte examenrun falen wanneer een hoofdvraag ontbreekt,
# vraagfragmenten elkaar overlappen of een grens niet op een volledig witte
# horizontale pixelrij ligt. Dit maakt de diagnose ook een echte regressietest.
question_proposals = sorted(
    (item for item in proposals if item.get("type") == "vraag"),
    key=lambda item: item["top"],
)
expected_numbers = sorted(item["question_number"] for item in accepted)
proposed_numbers = sorted(
    number for item in question_proposals for number in item["question_numbers"]
)
if proposed_numbers != expected_numbers:
    raise SystemExit(
        f"Niet alle echte examenvragen hebben precies één fragment: "
        f"verwacht {expected_numbers}, gevonden {proposed_numbers}"
    )
for previous, following in zip(question_proposals, question_proposals[1:]):
    if previous["bottom"] > following["top"]:
        raise SystemExit(
            f"Vraagfragmenten overlappen: {previous['question_numbers']} en "
            f"{following['question_numbers']}"
        )
for item in proposals:
    for edge in ("top", "bottom"):
        row = int(round(item[edge]))
        if not any(start <= row <= end for start, end in white_rows):
            raise SystemExit(
                f"Fragmentgrens {edge}={row} van {item['id']} ligt niet op een volledig witte rij"
            )

report = {
    "source_pdf": SOURCE.name,
    "page_count": len(metadata["pages"]),
    "stitched_width": metadata["width"],
    "stitched_height": metadata["height"],
    "detected_question_starts": [
        {
            "number": item["question_number"],
            "page": item["page_index"] + 1,
            "bbox": item["pdf_bbox"],
            "text": item["text"],
        }
        for item in accepted
    ],
    "white_row_range_count": len(white_rows),
    "white_row_ranges": white_rows,
    "proposals": proposals,
}
(OUTPUT / "diagnostics.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
# Diagnoseer ook het officiële correctievoorschrift van hetzelfde examen.
# Deze extra uitvoer maakt zichtbaar welke open-vraagregels door de algemene
# detector worden gevonden en welke inhoudsregels direct bij die regels staan.
CV_SOURCE = ROOT / "examens" / "vw-1018-a-26-2-c.pdf"
if CV_SOURCE.is_file():
    cv_result = detect_question_starts(
        str(CV_SOURCE), enforce_sequence=False, allow_lowercase_text=True
    )
    cv_debug = []
    with fitz.open(CV_SOURCE) as cv_pdf:
        model_page = None
        for page_index, page in enumerate(cv_pdf):
            # Zoek de zelfstandige hoofdstukkop; een gewone verwijzing
            # naar het beoordelingsmodel in de inleiding is geen startpunt.
            has_model_heading = any(
                re.fullmatch(
                    r"\s*(?:\d{1,2}\s+)?beoordelingsmodel\s*",
                    " ".join(
                        span.get("text", "")
                        for span in line.get("spans", [])
                    ),
                    re.IGNORECASE,
                )
                and float(line.get("bbox", [0, 0, 0, 0])[1]) <= page.rect.height * 0.25
                for block in page.get_text("dict").get("blocks", [])
                if block.get("type") == 0
                for line in block.get("lines", [])
            )
            if has_model_heading:
                model_page = page_index
                break
        for candidate in cv_result["candidates"]:
            if model_page is not None and candidate["page_index"] < model_page:
                continue
            page = cv_pdf[candidate["page_index"]]
            # Gebruik de originele PDF-regels met hun y-coördinaten; zo
            # blijft de diagnose betrouwbaar bij herhaalde korte regels zoals
            # "1", "2" en "juist".
            positioned_lines = []
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    line_text = " ".join(
                        span.get("text", "") for span in line.get("spans", [])
                    ).strip()
                    if line_text:
                        positioned_lines.append((
                            float(line.get("bbox", [0, 0, 0, 0])[1]),
                            line_text,
                        ))
            positioned_lines.sort(key=lambda item: item[0])
            candidate_y = float(candidate["pdf_bbox"][1])
            line_index = min(
                range(len(positioned_lines)),
                key=lambda index: abs(positioned_lines[index][0] - candidate_y),
                default=0,
            )
            cv_debug.append({
                "page": candidate["page_index"] + 1,
                "y": candidate_y,
                "candidate_text": candidate["text"],
                "nearby_lines": [
                    text for _, text in
                    positioned_lines[max(0, line_index - 1):line_index + 7]
                ],
            })
    (OUTPUT / "cv-candidates.json").write_text(
        json.dumps({
            "source_pdf": CV_SOURCE.name,
            "model_page": (model_page + 1) if model_page is not None else None,
            "candidate_count": len(cv_debug),
            "candidates": cv_debug,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "cv_source": CV_SOURCE.name,
        "cv_model_page": (model_page + 1) if model_page is not None else None,
        "cv_candidate_count": len(cv_debug),
        "cv_candidates": cv_debug,
    }, ensure_ascii=False))

print(json.dumps({
    "source": SOURCE.name,
    "pages": report["page_count"],
    "detected_question_numbers": [item["question_number"] for item in accepted],
    "white_row_ranges": len(white_rows),
    "proposals": [
        {"type": item["type"], "questions": item["question_numbers"],
         "top": item["top"], "bottom": item["bottom"],
         "source": item.get("source", "normalised_visual_boundaries")}
        for item in proposals
    ],
    "diagnostic_output": str(OUTPUT),
}, ensure_ascii=False))
