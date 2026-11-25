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
from PIL import Image
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
    cv_model_start,
    cv_content_end_page,
)
from examenverwerker.main import _nearest_white_row, _white_row_ranges
from examenverwerker import main as exam_main
from examenverwerker.storage import Store
from fastapi.testclient import TestClient

def assert_question_number_visible(
    pdf_path: Path,
    stitched_path: Path,
    page_metadata: list[dict],
    candidate: dict,
    question_number: int,
) -> dict:
    """Controleer de daadwerkelijke pixels van een vraagnummer in de stitch.

    De tekstlaag alleen is niet voldoende: de regressie die we willen vangen
    ontstaat juist wanneer de footeropschoning pixels uit de afbeelding wist.
    Daarom rekenen we de PDF-glyphbox terug naar de uiteindelijke lange PNG en
    eisen we daar zichtbare donkere pixels.
    """
    page_number = int(candidate["page_index"]) + 1
    page_info = next(
        (item for item in page_metadata if int(item["page_number"]) == page_number),
        None,
    )
    if page_info is None:
        raise SystemExit(
            f"Vraag {question_number} staat op PDF-pagina {page_number}, "
            "maar die pagina ontbreekt in de lange afbeelding."
        )

    # De glyphbox komt uit PyMuPDF in PDF-punten. crop_pixels bevat de
    # oorspronkelijke renderpixels die na het verticale bijsnijden overbleven.
    bbox = [float(value) for value in candidate["pdf_bbox"]]
    crop_pixels = page_info["crop_pixels"]
    render_scale_x = float(page_info["render_width"]) / float(page_info["source_width"])
    render_scale_y = float(page_info["render_width"]) / float(page_info["source_width"])
    resize_x = float(page_info["stitched_width"]) / float(page_info["render_width"])
    resize_y = float(page_info["stitched_height"]) / float(page_info["render_height"])

    left = int(round((bbox[0] * render_scale_x - crop_pixels[0]) * resize_x)) - 8
    right = int(round((bbox[2] * render_scale_x - crop_pixels[0]) * resize_x)) + 8
    top = int(round(
        page_info["top"]
        + (bbox[1] * render_scale_y - crop_pixels[1]) * resize_y
    )) - 8
    bottom = int(round(
        page_info["top"]
        + (bbox[3] * render_scale_y - crop_pixels[1]) * resize_y
    )) + 8

    with Image.open(stitched_path) as stitched:
        region = stitched.crop((
            max(0, left), max(0, top),
            min(stitched.width, right), min(stitched.height, bottom),
        )).convert("L")
        visible_pixels = sum(1 for value in region.getdata() if value < 180)

    if visible_pixels < 2:
        raise SystemExit(
            f"Vraagnummer {question_number} is wel als PDF-tekst gevonden, "
            "maar ontbreekt in de uiteindelijke lange afbeelding."
        )
    return {
        "question_number": question_number,
        "pdf_page": page_number,
        "visible_dark_pixels": visible_pixels,
        "stitched_region": [left, top, right, bottom],
    }


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

# Controleer vraag 30 op de uiteindelijke afbeelding. Dit is het
# vraagnnummer dat eerder bij de footeropschoning uit de examenstrook verdween.
question_30_candidate = next(
    item for item in accepted if int(item["question_number"]) == 30
)
question_30_pixel_check = assert_question_number_visible(
    SOURCE, stitched_path, metadata["pages"], question_30_candidate, 30
)

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
    # Bouw ook de echte CV-stitch met exact dezelfde functie als stap 8.
    # Daarmee controleren we vraag 28 in de pixels, niet alleen als tekst.
    with fitz.open(CV_SOURCE) as cv_pdf_for_stitch:
        cv_start_page, cv_start_y = cv_model_start(cv_pdf_for_stitch)
        cv_end_page = cv_content_end_page(cv_pdf_for_stitch)
    cv_stitched_path = OUTPUT / "vw-1018-a-26-2-c-stitched.png"
    cv_stitched_metadata = build_stitched_exam(
        CV_SOURCE,
        cv_stitched_path,
        start_page=cv_start_page,
        end_page=cv_end_page,
        start_y=cv_start_y,
    )

    cv_result = detect_question_starts(
        str(CV_SOURCE), enforce_sequence=False, allow_lowercase_text=True
    )
    cv_debug = []
    # Zoek de echte CV-vraag 28 en controleer of de glyph na opschonen nog
    # zichtbaar is in de uiteindelijke lange afbeelding.
    cv_question_28 = next(
        item for item in cv_result["candidates"]
        if int(item["question_number"]) == 28
    )
    cv_question_28_pixel_check = assert_question_number_visible(
        CV_SOURCE, cv_stitched_path, cv_stitched_metadata["pages"], cv_question_28, 28
    )
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

# Leg per kandidaat vast waarom de CV-specifieke filter hem wel of niet
# behoudt. De ruwe detector kan immers correct zijn terwijl een latere
# geometrische controle een echte open vraag afwijst.
cv_filter_debug = []
if CV_SOURCE.is_file():
    with fitz.open(CV_SOURCE) as cv_pdf:
        for candidate in cv_result["candidates"]:
            page_index = candidate["page_index"]
            if model_page is not None and page_index < model_page:
                continue
            candidate_text = candidate["text"].strip()
            debug_item = {
                "page": page_index + 1,
                "number": candidate["question_number"],
                "text": candidate_text,
                "pdf_bbox": candidate["pdf_bbox"],
                "accepted_by_filter": False,
                "reason": "geen passend vraagstartpatroon",
            }
            direct = re.match(r"^\d{1,2}\.?\s+maximumscore\b", candidate_text, re.IGNORECASE)
            direct_mc = re.match(r"^\d{1,2}\.?\s+[A-E]\s+\d{1,2}\s*$", candidate_text, re.IGNORECASE)
            if direct or direct_mc:
                debug_item["accepted_by_filter"] = True
                debug_item["reason"] = "directe CV-regel"
                cv_filter_debug.append(debug_item)
                continue
            if re.fullmatch(r"\d{1,2}\.?", candidate_text):
                positioned_lines = []
                for block in cv_pdf[page_index].get_text("dict").get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        line_text = " ".join(
                            span.get("text", "") for span in line.get("spans", [])
                        ).strip()
                        bbox = line.get("bbox", [])
                        if line_text and len(bbox) == 4:
                            positioned_lines.append({
                                "text": line_text,
                                "left": float(bbox[0]),
                                "top": float(bbox[1]),
                                "right": float(bbox[2]),
                                "bottom": float(bbox[3]),
                            })
                candidate_top = float(candidate["pdf_bbox"][1])
                candidate_bottom = float(candidate["pdf_bbox"][3])
                candidate_left = float(candidate["pdf_bbox"][0])
                later_column_starts = [
                    float(other["pdf_bbox"][1])
                    for other in cv_result["candidates"]
                    if other is not candidate
                    and other["page_index"] == page_index
                    and float(other["pdf_bbox"][1]) > candidate_top
                    and abs(float(other["pdf_bbox"][0]) - candidate_left) <= 12.0
                ]
                search_bottom = min(
                    later_column_starts,
                    default=float(cv_pdf[page_index].rect.height),
                ) - 2.0
                search_bottom = max(candidate_bottom, search_bottom)
                nearby = [
                    item for item in positioned_lines
                    if item["bottom"] >= candidate_top - 8
                    and item["top"] <= search_bottom
                    and not (
                        abs(item["left"] - candidate_left) < 0.5
                        and abs(item["top"] - candidate_top) < 0.5
                    )
                ]
                has_maximumscore = any(
                    re.search(r"\bmaximumscore\s+\d+", item["text"], re.IGNORECASE)
                    for item in nearby
                )
                has_inline_mc_answer = any(
                    re.fullmatch(r"[A-E][.)]?\s+[012]", item["text"], re.IGNORECASE)
                    for item in nearby
                )
                has_split_mc_answer = any(
                    re.fullmatch(r"[A-E][.)]?", item["text"], re.IGNORECASE)
                    and any(
                        re.fullmatch(r"[012]", other["text"])
                        and abs(other["top"] - item["top"]) <= 24
                        for other in nearby
                    )
                    for item in nearby
                )
                debug_item.update({
                    "candidate_top": candidate_top,
                    "search_bottom": search_bottom,
                    "later_column_starts": later_column_starts,
                    "has_maximumscore": has_maximumscore,
                    "has_inline_mc_answer": has_inline_mc_answer,
                    "has_split_mc_answer": has_split_mc_answer,
                    "nearby_lines": [
                        {"text": item["text"], "left": round(item["left"], 2),
                         "top": round(item["top"], 2), "bottom": round(item["bottom"], 2)}
                        for item in nearby
                    ],
                })
                if has_maximumscore or has_inline_mc_answer or has_split_mc_answer:
                    debug_item["accepted_by_filter"] = True
                    debug_item["reason"] = "beoordelingsregel binnen zoekvenster"
                else:
                    debug_item["reason"] = "geen score-/antwoordregel binnen zoekvenster"
            cv_filter_debug.append(debug_item)
(OUTPUT / "cv-filter-debug.json").write_text(
    json.dumps(cv_filter_debug, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(json.dumps({
    "cv_filter_candidates": len(cv_filter_debug),
    "cv_filter_accepted": sum(item["accepted_by_filter"] for item in cv_filter_debug),
    "cv_filter_rejected_examples": [
        {"page": item["page"], "number": item["number"], "text": item["text"],
         "reason": item["reason"], "nearby_lines": item.get("nearby_lines", [])[:8]}
        for item in cv_filter_debug if not item["accepted_by_filter"]
    ][:12],
}, ensure_ascii=False))

# Controleer ook de volledige API-route van stap 7 op het echte CV.
# De losse detector hierboven is niet voldoende: de applicatie past daarna
# nog CV-specifieke filters toe om juridische nummering en subonderdelen uit
# te sluiten. Juist die laatste stap bepaalt wat de gebruiker werkelijk ziet.
if CV_SOURCE.is_file():
    cv_workspace = OUTPUT / "cv-api-workspace"
    cv_workspace.mkdir(parents=True, exist_ok=True)
    exam_main.DATA = cv_workspace
    exam_main.STORE = Store(cv_workspace)
    with TestClient(exam_main.app) as client:
        imported = client.post(
            "/api/exams/import",
            files=[("files", (CV_SOURCE.name, CV_SOURCE.read_bytes(), "application/pdf"))],
        )
        if imported.status_code != 200:
            raise SystemExit(f"CV-import voor eindcontrole mislukt: {imported.text}")
        exam_id = imported.json()["exam_id"]
        confirmed = client.post(
            f"/api/exams/{exam_id}/metadata/confirm",
            json={
                "subject": "biologie",
                "level": "vwo",
                "year": 2026,
                "period": 2,
                "document_types": {CV_SOURCE.name: "correctievoorschrift"},
            },
        )
        if confirmed.status_code != 200:
            raise SystemExit(f"CV-metadata bevestigen mislukt: {confirmed.text}")
        starts_response = client.get(
            f"/api/exams/{exam_id}/document-question-starts/correctievoorschrift"
        )
        if starts_response.status_code != 200:
            raise SystemExit(f"CV-vraagstarts via API mislukt: {starts_response.text}")
        api_starts = starts_response.json()["candidates"]

    # Iedere hoofdvraag uit het opgavenboekje moet ook in de CV-review
    # aanwezig zijn. Dit controleert zowel open als meerkeuzevragen en voorkomt
    # dat een detector die alleen de MC-vragen vindt ten onrechte slaagt.
    expected_cv_numbers = sorted({int(item["question_number"]) for item in accepted})
    actual_cv_numbers = sorted({int(item["question_number"]) for item in api_starts
                                if not item.get("removed", False)})
    if actual_cv_numbers != expected_cv_numbers:
        missing = sorted(set(expected_cv_numbers) - set(actual_cv_numbers))
        unexpected = sorted(set(actual_cv_numbers) - set(expected_cv_numbers))
        raise SystemExit(
            "CV-vraagstarts via de volledige stap-7-route zijn onvolledig: "
            f"ontbrekend={missing}, onverwacht={unexpected}, "
            f"verwacht={expected_cv_numbers}, gevonden={actual_cv_numbers}"
        )
    (OUTPUT / "cv-api-question-starts.json").write_text(
        json.dumps({
            "source_pdf": CV_SOURCE.name,
            "expected_question_numbers": expected_cv_numbers,
            "detected_question_numbers": actual_cv_numbers,
            "candidate_count": len(api_starts),
            "candidates": api_starts,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

print(json.dumps({
    "question_30_pixel_check": question_30_pixel_check,
    "cv_question_28_pixel_check": cv_question_28_pixel_check,
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
