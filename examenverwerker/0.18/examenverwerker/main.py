"""HTTP-laag en samenhangende gebruikersflow van de Examenverwerker.

De browser praat uitsluitend met deze API. Daardoor gelden dezelfde
validatieregels voor handelingen vanuit de interface en voor directe API-
aanroepen. De volgende ontwikkeliteraties kunnen de inhoud van afzonderlijke
workflowstappen uitbreiden zonder de examenbibliotheek of opslag te vervangen.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import fitz
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from .domain import WORKFLOW, STEP_BY_KEY, unmet_requirements, invalidate_dependents
from .metadata import suggest_metadata
from .question_detection import detect_question_starts, validate_review
from .question_fragments import (generate_question_fragments, build_stitched_exam,
                                  propose_stitched_question_selections, normalise_stitched_selections,
                                  cv_content_end_page, cv_model_start)
from .question_analysis import analyse_questions, validate_question_analysis
from .answer_detection import analyse_answers, detect_cv_max_points, validate_answer_review
from .cv_supplement import analyse_supplement, validate_supplement_review
from .context_detection import generate_context_candidates, validate_context_review
from .storage import Store, resolve_shared_data_root
from .learning import (question_start_features, build_learning_profile, learned_adjustment,
                       build_boundary_learning_profile, build_context_learning_profile,
                       apply_context_range_learning, learned_boundary_overrides)

ROOT = Path(__file__).resolve().parent.parent
# De opslag staat buiten de versie-map. Bij de eerste start van 0.17 wordt
# een bestaande 0.13-opslag automatisch gekopieerd als er nog geen gedeelde
# gegevensmap bestaat. Daardoor blijven eerder geïmporteerde examens behouden.
_data_override = __import__("os").environ.get("EXAMENVERWERKER_DATA")
DATA = Path(_data_override).resolve() if _data_override else resolve_shared_data_root(ROOT)
STORE = Store(DATA)
app = FastAPI(title="Examenverwerker", version="0.18.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

def _load_or_build_stitched_exam(
    source_path: Path,
    output_path: Path,
    source_sha256: str,
    *,
    start_page: int = 1,
    end_page: int | None = None,
    start_y: float = 0.0,
) -> dict[str, Any]:
    """Herbruik de lange examenafbeelding met de juiste paginaselectie.

    Het opgavenboekje begint normaal gesproken op PDF-pagina 2, omdat de
    eerste pagina de omslag/instructies bevat. Een uitwerkbijlage en een
    correctievoorschrift beginnen op pagina 1. start_page én end_page zijn
    onderdeel van de cache-identiteit: een afbeelding met een andere
    paginaselectie mag nooit voor deze workflowstap worden hergebruikt.
    De optionele end_page sluit bij CV's de administratieve slotsectie uit.

    De bronhash voorkomt daarnaast dat een oude afbeelding wordt hergebruikt
    wanneer een examenbestand daadwerkelijk is vervangen.
    """
    cache_path = output_path.with_suffix(".metadata.json")
    if output_path.is_file() and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (cached.get("source_sha256") == source_sha256
                    and cached.get("cache_version") == 7
                    and cached.get("start_page") == start_page
                    and cached.get("end_page") == end_page
                    and cached.get("start_y") == start_y
                    and isinstance(cached.get("metadata"), dict)
                    and isinstance(cached.get("white_row_ranges"), list)):
                metadata = dict(cached["metadata"])
                metadata["white_row_ranges"] = cached["white_row_ranges"]
                return metadata
        except (OSError, ValueError, TypeError):
            # Een beschadigde of verouderde cache wordt veilig opnieuw opgebouwd.
            pass

    # Geef de paginakeuze expliciet door aan de renderer. Zonder dit argument
    # zou ook een uitwerkbijlage standaard de eerste pagina overslaan.
    metadata = build_stitched_exam(
        source_path, output_path, start_page=start_page, end_page=end_page,
        start_y=start_y,
    )
    white_rows = _white_row_ranges(output_path)
    cache_payload = {
        "cache_version": 7,
        "source_sha256": source_sha256,
        "start_page": start_page,
        "end_page": end_page,
        "start_y": start_y,
        "metadata": metadata,
        "white_row_ranges": white_rows,
    }
    cache_path.write_text(
        json.dumps(cache_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    metadata["white_row_ranges"] = white_rows
    return metadata


def _stitched_end_page(source_path: Path, document_type: str) -> int | None:
    """Bepaal de laatste pagina die in een lange documentstrook thuishoort.

    Bij een correctievoorschrift hoort de administratieve slotsectie niet bij
    de vraagfragmenten. Gebruik daarom exact dezelfde herkenning als de
    vraagstartdetectie en de fragmentgenerator. Voor andere documenttypen
    blijft de volledige PDF beschikbaar.
    """
    if document_type != "correctievoorschrift":
        return None
    with fitz.open(source_path) as pdf:
        return cv_content_end_page(pdf)


def _stitched_page_selection(source_path: Path, document_type: str) -> tuple[int, int | None, float]:
    """Bepaal de eerste en laatste pagina voor de lange documentafbeelding.

    Voor het CV begint de werkruimte bij de kop '4 Beoordelingsmodel' en
    eindigt zij vóór de administratieve slotsectie. De eerste pagina wordt
    zo nodig ook bovenaan de kop bijgesneden. De uitwerkbijlage begint op
    pagina 1 en gebruikt geen extra verticale startuitsnede.
    """
    if document_type == "correctievoorschrift":
        with fitz.open(source_path) as pdf:
            first_page, first_y = cv_model_start(pdf)
            last_page = cv_content_end_page(pdf)
        return first_page, last_page, first_y
    return 0, None, 0.0


def _stitched_image_fingerprint(image_path: Path) -> str:
    """Return the content hash of the exact long image used for pixel selections.

    Fragment selections are stored as pixel coordinates, not PDF coordinates.
    If rendering or cropping changes, those coordinates can silently point to
    different content. Persisting this fingerprint lets the workflow detect
    that situation and ask for a new visual check instead of producing shifted
    snippets that look plausible but refer to the wrong source region.
    """
    if not image_path.is_file():
        raise HTTPException(409, "De lange examenafbeelding ontbreekt. Open de fragmentcontrole opnieuw.")
    return STORE.sha256(image_path)


def _stitched_selection_matches_image(evidence: dict, image_path: Path) -> bool:
    """Check whether saved pixel selections belong to the current stitched PNG.

    Older project files do not contain a fingerprint. They are deliberately
    treated as stale: without proof of the coordinate system, reusing their
    pixel positions could silently crop the wrong part of the PDF.
    """
    saved_fingerprint = evidence.get("stitched_image_sha256")
    return bool(saved_fingerprint) and saved_fingerprint == _stitched_image_fingerprint(image_path)


def _safe_filename(filename: str) -> str:
    """Normaliseer een uploadnaam zodat deze nooit een pad kan schrijven."""
    name = Path(filename or "document.pdf").name
    name = re.sub(r"[^\w.() -]", "_", name, flags=re.UNICODE).strip(" .")
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, f"Alleen PDF-bestanden zijn toegestaan: {name}")
    return name or "document.pdf"


@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/api/exams")
def list_exams():
    return STORE.list_exams()


@app.post("/api/exams/import")
async def import_exam(files: list[UploadFile] = File(...),
                      replace_exam_id: str | None = Form(None)):
    """Importeer één of meer PDF's als één nieuw examenproject.

    De bestanden worden byte-voor-byte opgeslagen. We leiden alleen
    metadata-voorstellen af; er wordt niets definitief bevestigd tijdens
    import. Een import met een ongeldige PDF wordt volledig teruggedraaid.
    """
    if not files:
        raise HTTPException(400, "Selecteer ten minste één PDF-bestand.")
    exam_id = uuid.uuid4().hex[:12]
    exam_dir = DATA / "exams" / exam_id / "sources"
    exam_dir.mkdir(parents=True, exist_ok=False)
    docs = []
    try:
        for upload in files:
            filename = _safe_filename(upload.filename or "document.pdf")
            target = exam_dir / filename
            if target.exists():
                raise HTTPException(400, f"Bestandsnaam komt dubbel voor: {filename}")
            with target.open("wb") as output:
                shutil.copyfileobj(upload.file, output)
            # PyMuPDF valideert dat het bestand werkelijk als PDF te openen is.
            try:
                with fitz.open(target) as pdf:
                    page_count = pdf.page_count
                    if page_count < 1:
                        raise ValueError("PDF bevat geen pagina's")
            except Exception as exc:
                raise HTTPException(400, f"{filename} is geen leesbare PDF: {exc}") from exc
            relative = str(target.relative_to(DATA))
            docs.append({
                "filename": filename,
                "relative_path": relative,
                "sha256": STORE.sha256(target),
                "metadata": suggest_metadata(target),
                "page_count": page_count,
            })
        # Voorkom dubbele examens op basis van de inhoud van alle PDF's.
        # De controle vindt plaats nadat alle uploads geldig zijn bevonden,
        # maar vóórdat de nieuwe import in de bibliotheek wordt aangemaakt.
        matching_exam = STORE.find_exam_by_document_hashes(
            [document["sha256"] for document in docs]
        )
        if matching_exam and replace_exam_id != matching_exam["id"]:
            raise HTTPException(409, {
                "code": "duplicate_exam",
                "exam_id": matching_exam["id"],
                "title": matching_exam["title"],
                "message": "Dit examen is al geïmporteerd en verwerkt."
            })
        if replace_exam_id and (
            not matching_exam or replace_exam_id != matching_exam["id"]
        ):
            raise HTTPException(409, {
                "code": "replacement_mismatch",
                "message": "De bestaande import is intussen gewijzigd. Herhaal de importcontrole."
            })

        # De examennaam is voorlopig de gemeenschappelijke bestandsstambasis.
        title = Path(docs[0]["filename"]).stem.rsplit("-", 1)[0].replace("_", " ")
        STORE.create_exam(exam_id, title or "Nieuw examen", docs)

        # Verwijder de oude import pas nadat de nieuwe database-import
        # succesvol is aangemaakt. Bij een fout blijft het bestaande examen
        # en alle eerdere verwerking dus intact.
        if matching_exam and replace_exam_id == matching_exam["id"]:
            old_exam_dir = DATA / "exams" / matching_exam["id"]
            STORE.delete_exam(matching_exam["id"])
            shutil.rmtree(old_exam_dir, ignore_errors=True)
    except Exception:
        shutil.rmtree(exam_dir.parent, ignore_errors=True)
        raise
    return {"exam_id": exam_id, "title": title, "documents": docs}


@app.get("/api/exams/{exam_id}")
def get_exam(exam_id: str):
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    return exam


@app.get("/api/exams/{exam_id}/documents/{document_id}/preview/{page_number}")
def preview_page(exam_id: str, document_id: int, page_number: int):
    """Render een originele PDF-pagina voor visuele beoordeling.

    De bron-PDF wordt niet aangepast. De renderer retourneert PNG-bytes met
    een vaste schaalfactor; latere selectietools zullen de bijbehorende
    geometrie expliciet meesturen om schermpixels terug te rekenen.
    """
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    document = next((d for d in exam["documents"] if d["id"] == document_id), None)
    if not document:
        raise HTTPException(404, "Document niet gevonden.")
    path = DATA / document["relative_path"]
    with fitz.open(path) as pdf:
        if page_number < 0 or page_number >= pdf.page_count:
            raise HTTPException(404, "Paginanummer buiten bereik.")
        pix = pdf[page_number].get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False)
        return Response(pix.tobytes("png"), media_type="image/png", headers={"Cache-Control": "no-store"})


def _document_for_type(exam: dict, document_type: str):
    """Vind precies één bevestigd document van het gevraagde type."""
    if document_type not in {"opgaven", "uitwerkbijlage", "correctievoorschrift"}:
        raise HTTPException(404, "Dit documenttype heeft geen vraagstartreview.")
    matches = [doc for doc in exam["documents"]
               if exam["metadata"].get("document_types", {}).get(doc["filename"]) == document_type]
    if len(matches) != 1:
        label = {"opgaven":"opgavendocument", "uitwerkbijlage":"uitwerkbijlage",
                 "correctievoorschrift":"correctievoorschrift"}[document_type]
        raise HTTPException(422, f"Er moet precies één {label} zijn toegewezen.")
    return matches[0]



def _load_document_question_starts(exam_id: str, document_type: str):
    """Deel de detectie- en herstelroute voor alle drie documentsoorten."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    if not exam["confirmed"]:
        raise HTTPException(409, "Bevestig eerst de documenteigenschappen.")
    document = _document_for_type(exam, document_type)
    path = DATA / document["relative_path"]
    if STORE.sha256(path) != document["sha256"]:
        raise HTTPException(409, "Het bronbestand is gewijzigd sinds import.")
    try:
        result = detect_question_starts(str(path), enforce_sequence=(document_type != "correctievoorschrift"), allow_lowercase_text=(document_type == "correctievoorschrift"))
        if document_type == "correctievoorschrift":
            # Het CV bevat vóór het beoordelingsmodel genummerde juridische
            # voorschriften. Die nummers zijn geen examenvragen. Start daarom
            # de detectie pas op de pagina waarop het beoordelingsmodel begint.
            model_heading = None
            with fitz.open(path) as cv_pdf:
                model_pages = []
                for index, page in enumerate(cv_pdf):
                    page_dict = page.get_text("dict")
                    heading_y = None
                    for block in page_dict.get("blocks", []):
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines", []):
                            line_text = " ".join(span.get("text", "") for span in line.get("spans", []))
                            # Het woord "beoordelingsmodel" komt ook in
                            # de juridische toelichting vóór het echte model
                            # voor. Herken uitsluitend de zelfstandige kop,
                            # eventueel voorafgegaan door het hoofdstuknummer.
                            if re.fullmatch(
                                r"\s*(?:\d{1,2}\s+)?beoordelingsmodel\s*",
                                line_text,
                                re.IGNORECASE,
                            ):
                                heading_y = float(line.get("bbox", [0, 0, 0, 0])[1])
                                # Een inhoudsopgave kan dezelfde zelfstandige
                                # kop bevatten. De echte sectiekop staat boven
                                # aan de pagina; vermeldingen lager op de
                                # pagina zijn geen start van het model.
                                if heading_y <= page.rect.height * 0.25:
                                    break
                                heading_y = None
                        if heading_y is not None:
                            break
                    if heading_y is not None:
                        model_pages.append(index)
                        if model_heading is None:
                            model_heading = (index, heading_y)
            if model_pages:
                first_model_page = model_pages[0]
                # Een CV bevat binnen open antwoorden vaak genummerde
                # subonderdelen, bijvoorbeeld "1 onjuist / 2 juist". Die
                # lijken syntactisch op hoofdvraagstarts. In het beoordelings-
                # model zijn hoofdvragen echter herkenbaar aan "maximumscore"
                # of aan de MC-regel met antwoordletter en score. Een los
                # nummer wordt alleen behouden als de eerstvolgende regel
                # zo'n beoordelingsmodelregel bevat.
                cv_valid_candidates = []
                with fitz.open(path) as cv_pdf:
                    for candidate in result["candidates"]:
                        page_index = candidate["page_index"]
                        if page_index < first_model_page:
                            continue
                        if page_index == first_model_page and candidate["pdf_bbox"][1] <= model_heading[1] + 4.0:
                            continue
                        candidate_text = candidate["text"].strip()
                        direct = re.match(r"^\d{1,2}\.?\s+maximumscore\b", candidate_text, re.IGNORECASE)
                        direct_mc = re.match(r"^\d{1,2}\.?\s+[A-F]\s+\d{1,2}\s*$", candidate_text, re.IGNORECASE)
                        if direct or direct_mc:
                            cv_valid_candidates.append(candidate)
                            continue
                        if re.fullmatch(r"\d{1,2}\.?", candidate_text):
                            # Een CV is vaak als tabel opgebouwd. De vraagkolom
                            # staat links, terwijl "maximumscore" of het MC-
                            # antwoord in een andere tekstkolom staat. De PDF-
                            # extractor geeft die kolommen niet altijd in
                            # leesvolgorde terug. Zoek daarom op PDF-coördinaten
                            # rond de vraagstart, niet uitsluitend in de vijf
                            # volgende geëxtraheerde tekstregels.
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

                            # Open-vraagbeoordelingen kunnen tientallen regels
                            # onder het vraagnummer staan. Een vaste marge van
                            # 48 PDF-punten kapt zulke beoordelingsblokken af.
                            # Bepaal daarom de ondergrens aan de hand van de
                            # eerstvolgende kandidaat op dezelfde vraagnummer-
                            # kolom. Genummerde subonderdelen staan doorgaans
                            # ingesprongen en begrenzen het hoofdvraagblok dus
                            # niet. Als er geen volgende hoofdvraagstart op deze
                            # pagina staat, loopt het zoekgebied tot de paginavoet.
                            later_column_starts = [
                                float(other["pdf_bbox"][1])
                                for other in result["candidates"]
                                if other is not candidate
                                and other["page_index"] == page_index
                                and float(other["pdf_bbox"][1]) > candidate_top
                                and abs(float(other["pdf_bbox"][0]) - candidate_left) <= 12.0
                            ]
                            search_bottom = min(
                                later_column_starts,
                                default=float(cv_pdf[page_index].rect.height),
                            ) - 2.0
                            # Een kandidaat kan nooit voorbij het einde van
                            # zijn pagina zoeken; een zeer dicht volgend nummer
                            # krijgt bovendien geen negatief zoekvenster.
                            search_bottom = max(candidate_bottom, search_bottom)

                            nearby_lines = [
                                item["text"] for item in positioned_lines
                                if item["bottom"] >= candidate_top - 8
                                and item["top"] <= search_bottom
                                and not (
                                    abs(item["left"] - float(candidate["pdf_bbox"][0])) < 0.5
                                    and abs(item["top"] - candidate_top) < 0.5
                                )
                            ]
                            has_maximumscore = any(
                                re.search(r"\bmaximumscore\s+\d+", line, re.IGNORECASE)
                                for line in nearby_lines
                            )
                            has_inline_mc_answer = any(
                                re.fullmatch(r"[A-F][.)]?\s+[012]", line, re.IGNORECASE)
                                for line in nearby_lines
                            )
                            # In sommige tabellen zijn antwoordletter en score
                            # afzonderlijke regels. Vergelijk regels op hun
                            # positie, zodat een andere tekstkolom of afwijkende
                            # PDF-leesvolgorde de herkenning niet verhindert.
                            nearby_positioned = [
                                item for item in positioned_lines
                                if item["bottom"] >= candidate_top - 8
                                and item["top"] <= search_bottom
                                and not (
                                    abs(item["left"] - float(candidate["pdf_bbox"][0])) < 0.5
                                    and abs(item["top"] - candidate_top) < 0.5
                                )
                            ]
                            has_split_mc_answer = any(
                                re.fullmatch(r"[A-F][.)]?", item["text"], re.IGNORECASE)
                                and any(
                                    re.fullmatch(r"[012]", other["text"])
                                    and abs(other["top"] - item["top"]) <= 24
                                    for other in nearby_positioned
                                )
                                for item in nearby_positioned
                            )
                            if has_maximumscore or has_inline_mc_answer or has_split_mc_answer:
                                cv_valid_candidates.append(candidate)
                # Sluit kandidaten uit administratieve slotpagina's. De
                # fragmentgenerator kapt het CV vóór "5 Aanleveren scores"
                # af; een vraagstart ná die grens zou anders een leeg
                # fragment opleveren en later een interne stitchfout geven.
                # Open de PDF opnieuw voor de slotsectiecontrole. De
                # eerdere contextmanager is bewust al gesloten nadat de
                # vraagregels zijn gelezen; een gesloten PyMuPDF-document mag
                # niet worden hergebruikt voor paginatoegang.
                with fitz.open(path) as cv_end_pdf:
                    cv_content_end_page_index = cv_content_end_page(cv_end_pdf)
                cv_valid_candidates = [
                    candidate for candidate in cv_valid_candidates
                    if candidate["page_index"] <= cv_content_end_page_index
                ]
                # Pas de oplopende nummerreeks pas toe nadat de CV-inleiding
                # en genummerde antwoordonderdelen zijn uitgesloten.
                ordered_cv = sorted(cv_valid_candidates, key=lambda item: (item["page_index"], item["pdf_bbox"][1]))
                result["candidates"] = []
                last_question_number = 0
                for candidate in ordered_cv:
                    if candidate["question_number"] > last_question_number:
                        result["candidates"].append(candidate)
                        last_question_number = candidate["question_number"]
                counts: dict[int, int] = {}
                for item in result["candidates"]:
                    counts[item["question_number"]] = counts.get(item["question_number"], 0) + 1
                for item in result["candidates"]:
                    item["duplicate_number"] = counts[item["question_number"]] > 1
                for page in result["pages"]:
                    if page["page_index"] < first_model_page:
                        page["candidates"] = []
                    else:
                        valid_ids = {item["id"] for item in result["candidates"]}
                        page["candidates"] = [item for item in page["candidates"]
                                              if item["id"] in valid_ids and
                                              (item["page_index"] > first_model_page or
                                               item["pdf_bbox"][1] > (model_heading[1] + 4.0))]
                    page["candidate_count"] = len(page["candidates"])
                result["candidate_count"] = len(result["candidates"])
    except Exception as exc:
        raise HTTPException(422, f"Vraagstarts konden niet worden herkend: {exc}") from exc
    if document_type == "correctievoorschrift":
        # Pas de CV-slotgrens ook ná het herstellen van eerder opgeslagen
        # handmatige kandidaten toe. Anders kan een oude handmatige start op
        # een administratieve pagina opnieuw een leeg CV-fragment veroorzaken.
        with fitz.open(path) as cv_end_pdf:
            cv_content_end_page_index = cv_content_end_page(cv_end_pdf)
        result["candidates"] = [
            item for item in result["candidates"]
            if item["page_index"] <= cv_content_end_page_index
        ]
        valid_candidate_ids = {item["id"] for item in result["candidates"]}
        for page in result["pages"]:
            page["candidates"] = [
                item for item in page["candidates"]
                if item["id"] in valid_candidate_ids
            ]
            page["candidate_count"] = len(page["candidates"])
        result["candidate_count"] = sum(
            not item.get("removed", False) for item in result["candidates"]
        )
    result["document"] = {"id": document["id"], "filename": document["filename"],
                          "sha256": document["sha256"]}
    step_key = {"opgaven":"opgaven_starts", "uitwerkbijlage":"uitwerk_starts",
                "correctievoorschrift":"cv_starts"}[document_type]
    previous = exam["steps"].get(step_key, {}).get("evidence", {})
    if previous.get("candidates"):
        # Hergebruik menselijke beslissingen zolang de bronhash gelijk blijft.
        # De opgeslagen pagina/coördinaten zijn leidend: een docent kan een
        # start immers naar een andere pagina of positie hebben verplaatst.
        decisions = {item["id"]: item for item in previous["candidates"]}
        automatic_ids = {item["id"] for item in result["candidates"]}
        for candidate in result["candidates"]:
            if candidate["id"] in decisions:
                saved = decisions[candidate["id"]]
                candidate.update({k: saved[k] for k in
                                  ("accepted", "question_number", "page_index", "pdf_bbox") if k in saved})
                candidate["removed"] = bool(saved.get("removed", False))
        for saved in previous["candidates"]:
            if saved.get("source") == "manual" and saved["id"] not in automatic_ids:
                manual = dict(saved)
                manual["text"] = manual.get("text") or "Handmatig toegevoegde vraagstart"
                result["candidates"].append(manual)
        # Herbouw paginalijsten zodat verplaatste en verwijderde kandidaten
        # ook na opnieuw openen op de juiste manier zichtbaar blijven.
        for page in result["pages"]:
            page["candidates"] = []
        for candidate in result["candidates"]:
            page = result["pages"][candidate["page_index"]]
            x0, y0, x1, y1 = candidate["pdf_bbox"]
            candidate["preview_bbox"] = [round(x0 * page["scale_x"], 2),
                                         round(y0 * page["scale_y"], 2),
                                         round(x1 * page["scale_x"], 2),
                                         round(y1 * page["scale_y"], 2)]
            if not candidate.get("removed"):
                page["candidates"].append(candidate)
        for page in result["pages"]:
            page["candidate_count"] = len(page["candidates"])
        result["candidate_count"] = sum(not item.get("removed") for item in result["candidates"])
    # Pas uitsluitend een uitlegbare rangschikkingshint toe op basis van
    # eerdere, expliciet afgeronde reviews van hetzelfde documenttype.
    # De bestaande acceptatiebeslissing, nummerreeksfilter en visuele review
    # blijven volledig intact; leren kan dus geen kandidaat stilzwijgend
    # goedkeuren of verwijderen.
    training_examples = []
    for record in STORE.list_fragment_feedback(f"question_starts:{document_type}"):
        training_examples.extend(record["accepted"].get("examples", []))
    learning_profile = build_learning_profile(training_examples)
    for candidate in result["candidates"]:
        page = result["pages"][candidate["page_index"]]
        features = question_start_features(candidate, page)
        adjustment = learned_adjustment(features, learning_profile)
        candidate["learning_score_adjustment"] = adjustment["score_adjustment"]
        candidate["learning_evidence"] = adjustment["evidence"]
        candidate["learning_active"] = adjustment["learning_active"]

    result["learning_profile"] = {
        "examples": learning_profile["example_count"],
        "active_features": learning_profile["active_feature_count"],
        "minimum_examples_per_feature": learning_profile["minimum_examples"],
    }
    result["document_type"] = document_type
    result["step_key"] = step_key
    return result


def _save_document_question_start_review(exam_id: str, document_type: str, payload: dict):
    """Valideer en bewaar correcties voor een opgaven-, uitwerk- of CV-PDF."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    if not exam["confirmed"]:
        raise HTTPException(409, "Bevestig eerst de documenteigenschappen.")
    document = _document_for_type(exam, document_type)
    source_path = DATA / document["relative_path"]
    if STORE.sha256(source_path) != document["sha256"]:
        raise HTTPException(409, "Het bronbestand is gewijzigd sinds import.")
    with fitz.open(source_path) as source_pdf:
        page_sizes = [(page.rect.width, page.rect.height) for page in source_pdf]
    try:
        review = validate_review(payload, document["page_count"], page_sizes)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    review["document_sha256"] = document["sha256"]
    review["detector_version"] = "0.18"
    step_key = {"opgaven":"opgaven_starts", "uitwerkbijlage":"uitwerk_starts",
                "correctievoorschrift":"cv_starts"}[document_type]

    # Een autosave kan pas aankomen nadat de gebruiker de stap al heeft
    # goedgekeurd. De opslaglaag vergelijkt de inhoud daarom binnen één
    # SQLite-schrijftransactie. Zo kan een identieke late autosave de status
    # 'complete' niet terugzetten naar 'pending'; echte wijzigingen doen dat
    # nadrukkelijk wel en vragen opnieuw om visuele goedkeuring.
    saved_as_draft = STORE.save_step_draft_preserving_identical_complete(
        exam_id,
        step_key,
        review,
        identity_fields=("candidates", "document_sha256"),
    )
    same_approved_candidates = not saved_as_draft

    return {"ok": True, "review": review,
            "complete": bool(same_approved_candidates),
            "message": ("Bestaande goedkeuring behouden; er zijn geen inhoudelijke wijzigingen."
                        if same_approved_candidates else
                        "Review opgeslagen. Rond de stap pas af nadat alle pagina's visueel zijn gecontroleerd.")}


@app.get("/api/exams/{exam_id}/question-starts")
def get_question_starts(exam_id: str):
    """Compatibele route voor de vraagstarts van het opgavendocument."""
    return _load_document_question_starts(exam_id, "opgaven")


@app.post("/api/exams/{exam_id}/question-starts/review")
def save_question_start_review(exam_id: str, payload: dict):
    """Compatibele reviewroute voor de vraagstarts van het opgavendocument."""
    return _save_document_question_start_review(exam_id, "opgaven", payload)


@app.get("/api/exams/{exam_id}/document-question-starts/{document_type}")
def get_document_question_starts(exam_id: str, document_type: str):
    """Vraagstarts detecteren in opgaven, uitwerkbijlage of CV."""
    return _load_document_question_starts(exam_id, document_type)


@app.post("/api/exams/{exam_id}/document-question-starts/{document_type}/review")
def save_document_question_start_review(exam_id: str, document_type: str, payload: dict):
    """Menselijke vraagstartcorrecties voor de gekozen documentsoort bewaren."""
    return _save_document_question_start_review(exam_id, document_type, payload)


def _white_row_ranges(image_path: str | Path) -> list[list[int]]:
    """Geef intervallen terug van volledig zuiver witte horizontale beeldrijen.

    Een grensrij is alleen geldig als iedere pixel van links tot rechts exact
    RGB(255, 255, 255) is. Er wordt bewust niet naar grijswaarden omgerekend:
    daardoor kan een zeer lichte grijze of gekleurde pixel nooit onbedoeld
    als witte grens worden geaccepteerd. Intervallen houden de API-respons
    compact, ook bij lange examenafbeeldingen.
    """
    with Image.open(image_path) as source:
        rgb = source.convert("RGB")
        width, height = rgb.size
        raw = rgb.tobytes()
        bytes_per_row = width * 3

    ranges: list[list[int]] = []
    range_start: int | None = None
    for y in range(height):
        # In RGB zijn drie bytes per pixel nodig. Een zuiver witte rij bevat
        # uitsluitend de bytewaarde 255, dus precies 3 * breedte bytes.
        row = raw[y * bytes_per_row:(y + 1) * bytes_per_row]
        is_fully_white = row.count(255) == bytes_per_row
        if is_fully_white and range_start is None:
            range_start = y
        elif not is_fully_white and range_start is not None:
            ranges.append([range_start, y - 1])
            range_start = None
    if range_start is not None:
        ranges.append([range_start, height - 1])
    return ranges


def _extract_stitched_selection_text(
    pdf_path: str | Path,
    page_metadata: list[dict[str, Any]],
    top: float,
    bottom: float,
    *,
    render_scale: float = 1.25,
) -> str:
    """Haal de tekst op uit exact het geselecteerde gebied van de stitchafbeelding.

    De vraagafbeelding is leidend voor de grenzen. Voor de automatische
    type-/puntenvoorstellen halen we daarnaast de selecteerbare PDF-tekst op
    uit precies hetzelfde verticale bereik. De coördinaten worden teruggezet
    via de crop-, render- en stitchmetadata; zo wordt niet per ongeluk de tekst
    van de volledige pagina of van de volgende vraag meegenomen.
    """
    if bottom <= top:
        return ""

    text_parts: list[str] = []
    with fitz.open(pdf_path) as pdf:
        for page_info in page_metadata:
            page_number = int(page_info["page_number"])
            if page_number < 1 or page_number > pdf.page_count:
                continue

            # Alleen het overlappende deel van deze bronpagina wordt uitgelezen.
            page_top = float(page_info["top"])
            page_bottom = float(page_info["bottom"])
            overlap_top = max(float(top), page_top)
            overlap_bottom = min(float(bottom), page_bottom)
            if overlap_bottom <= overlap_top:
                continue

            # De lange afbeelding is per pagina eerst gecropt en daarna
            # eventueel proportioneel geschaald naar de gemeenschappelijke
            # stitchbreedte. Draai beide stappen in omgekeerde volgorde terug.
            crop_pixels = page_info.get("crop_pixels", [0, 0, 0, 0])
            crop_top = float(crop_pixels[1])
            rendered_width = max(1.0, float(page_info.get("render_width", 1)))
            stitched_width = max(1.0, float(page_info.get("stitched_width", rendered_width)))
            resize_factor = stitched_width / rendered_width

            render_y0 = (overlap_top - page_top) / resize_factor + crop_top
            render_y1 = (overlap_bottom - page_top) / resize_factor + crop_top
            pdf_y0 = max(0.0, render_y0 / render_scale)
            pdf_y1 = min(float(page_info["source_height"]), render_y1 / render_scale)
            if pdf_y1 <= pdf_y0:
                continue

            page = pdf[page_number - 1]
            clip = fitz.Rect(0, pdf_y0, page.rect.width, pdf_y1)
            extracted = page.get_text("text", clip=clip, sort=True).strip()
            if extracted:
                text_parts.append(extracted)

    return "\n".join(text_parts)


def _first_nonempty_text_line(text: str) -> str:
    """Geef de eerste zichtbare tekstregel terug voor de titel van een contextgroep.

    De volgorde uit de PDF-tekstextractie blijft leidend. Lege regels en regels
    met uitsluitend witruimte worden overgeslagen; de inhoud wordt niet
    herschreven of inhoudelijk samengevat.
    """
    return next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")


def _context_title_for_selection(
    pdf_path: str | Path,
    page_metadata: list[dict[str, Any]],
    selection: dict[str, Any],
) -> str:
    """Leid de contexttitel af uit de eerste tekstregel binnen het fragment."""
    extracted = _extract_stitched_selection_text(
        pdf_path, page_metadata,
        float(selection.get("top", 0)),
        float(selection.get("bottom", 0)),
    )
    return _first_nonempty_text_line(extracted)


def _nearest_white_row(y: float, ranges: list[list[int]]) -> int:
    """Rond een voorgestelde grens af op de dichtstbijzijnde volledig witte rij."""
    if not ranges:
        raise ValueError("In de lange afbeelding is geen volledig witte horizontale rij gevonden.")
    target = max(0.0, float(y))
    nearest = min(
        (max(start, min(end, round(target))) for start, end in ranges),
        key=lambda candidate: abs(candidate - target),
    )
    return int(nearest)


def _is_white_boundary(y: float, ranges: list[list[int]]) -> bool:
    """Controleer of een opgeslagen integergrens op een volledig witte rij ligt.

    Afronden is hier niet toegestaan: een coördinaat van bijvoorbeeld 12,4 px
    is niet dezelfde grens als de witte pixelrij 12. De browser stuurt
    integerpixelrijen; de server dwingt diezelfde afspraak af.
    """
    try:
        value = float(y)
    except (TypeError, ValueError):
        return False
    if not value.is_integer():
        return False
    row = int(value)
    return any(start <= row <= end for start, end in ranges)


def _fragment_step_keys(document_type: str) -> tuple[str, str]:
    """Koppel documentsoort aan de start- en fragmentreviewstap."""
    mapping = {
        "opgaven": ("opgaven_starts", "opgaven_fragments"),
        "uitwerkbijlage": ("uitwerk_starts", "uitwerk_fragments"),
        "correctievoorschrift": ("cv_starts", "cv_fragments"),
    }
    if document_type not in mapping:
        raise HTTPException(404, "Dit documenttype heeft geen fragmentreview.")
    return mapping[document_type]


def _load_document_fragments(exam_id: str, document_type: str):
    """Genereer of herbouw de fragmentvoorstellen voor een documentsoort."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    starts_step_key, fragments_step_key = _fragment_step_keys(document_type)
    starts_step = exam["steps"].get(starts_step_key, {})
    if starts_step.get("status") != "complete":
        raise HTTPException(409, "Rond eerst de controle van de vraagstarts af.")
    document = _document_for_type(exam, document_type)
    source_path = DATA / document["relative_path"]
    if STORE.sha256(source_path) != document["sha256"]:
        raise HTTPException(409, "Het bronbestand is gewijzigd sinds import.")
    accepted = [item for item in starts_step["evidence"].get("candidates", []) if item.get("accepted") and not item.get("removed")]
    output_dir = DATA / "exams" / exam_id / "derived" / f"{document_type}_fragments"
    previous = exam["steps"].get(fragments_step_key, {}).get("evidence", {})
    boundary_overrides = {int(item["question_number"]): item
                          for item in previous.get("boundary_overrides", [])}
    # Geleerde grensoffsets worden alleen als voorlopig voorstel gebruikt.
    # Een handmatig opgeslagen override wordt daarna samengevoegd en wint dus
    # altijd van het leerprofiel.
    if accepted:
        boundary_profile = build_boundary_learning_profile(
            STORE.list_fragment_feedback()
        ).get(document_type, {})
        if boundary_profile.get("active"):
            with fitz.open(source_path) as learning_pdf:
                page_heights = [float(page.rect.height) for page in learning_pdf]
                if document_type == "correctievoorschrift":
                    # Gebruik dezelfde inhoudsgrens als de fragmentgenerator:
                    # de administratieve slotpagina mag geen leergrens worden.
                    page_heights = page_heights[:cv_content_end_page(learning_pdf) + 1]
            learned = learned_boundary_overrides(
                accepted, page_heights, boundary_profile
            )
            for number, override in learned.items():
                boundary_overrides.setdefault(number, override)
    try:
        proposals = generate_question_fragments(source_path, accepted, output_dir,
                                                document_type=document_type,
                                                boundary_overrides=boundary_overrides)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    # Voor opgaven zijn de handmatig geselecteerde fragmenten op de lange
    # examenstrook leidend. Zo gebruikt de analyse exact dezelfde grenzen als
    # de docent in stap 3 heeft vastgesteld; de oude automatische voorstellen
    # blijven alleen als terugval beschikbaar voor oudere examendossiers.
    if document_type in {"opgaven", "uitwerkbijlage", "correctievoorschrift"} and previous.get("stitched_selections"):
        # Zowel de opgaven als de uitwerkbijlage gebruiken nu de visueel
        # goedgekeurde lange afbeelding als bron voor definitieve vraag-PNG's.
        # De selectiecoördinaten zijn daardoor exact gelijk aan de grenzen die
        # de docent in de interactieve fragmentreview heeft gecontroleerd.
        stitched_dir = DATA / "exams" / exam_id / "derived" / f"{document_type}_stitched"
        stitched_path = stitched_dir / "exam-long.png"
        # Bouw de metadata opnieuw op naast de afbeelding. Die metadata is
        # nodig om de geselecteerde pixelstrook terug te rekenen naar de
        # exacte bronpagina's en PDF-tekstcoördinaten.
        # Opgaven slaan de omslag over; uitwerkbijlagen en CV's beginnen
        # op pagina 1. De cache gebruikt dezelfde paginakeuze als de review.
        stitched_metadata = _load_or_build_stitched_exam(
            source_path, stitched_path, document["sha256"],
            start_page=1 if document_type == "opgaven" else _stitched_page_selection(source_path, document_type)[0],
            end_page=_stitched_page_selection(source_path, document_type)[1],
            start_y=_stitched_page_selection(source_path, document_type)[2],
        )
        if not _stitched_selection_matches_image(previous, stitched_path):
            step_label = {
                "opgaven": "stap 3 (Vraagfragmenten opgaven)",
                "uitwerkbijlage": "stap 6 (Fragmenten uitwerkbijlage)",
                "correctievoorschrift": "stap 8 (Correctievoorschrift verwerken)",
            }[document_type]
            raise HTTPException(
                409,
                f"De opgeslagen fragmentgrenzen horen bij een oudere versie van de lange afbeelding. "
                f"Heropen {step_label}, controleer de grenzen opnieuw en sla ze op. "
                "Het examen hoeft niet opnieuw geïmporteerd te worden."
            )
        stitched_questions = [item for item in previous["stitched_selections"] if item.get("type") == "vraag"]
        stitched_contexts = [item for item in previous["stitched_selections"] if item.get("type") == "context"]
        question_map = {int(item["question_number"]): item for item in accepted}
        rebuilt_questions = []
        with Image.open(stitched_path) as stitched_image:
            for selection_index, selection in enumerate(stitched_questions, 1):
                top = max(0, min(stitched_image.height, int(selection["top"])))
                bottom = max(top + 1, min(stitched_image.height, int(selection["bottom"])))
                crop = stitched_image.crop((0, top, stitched_image.width, bottom))
                filename = f"selected-question-{selection_index:02d}.png"
                crop.save(output_dir / filename, format="PNG", optimize=True)
                crop.close()
                url = f"/api/question-fragment-images/{exam_id}/{document_type}/{filename}"
                # Een selectie kan alleen een definitief vraagfragment opleveren
                # wanneer het nummer ook voorkomt in de goedgekeurde vraagstarts.
                # Sla een ontbrekende koppeling niet stilzwijgend over: dan lijkt
                # de CV-verwerking compleet terwijl bijvoorbeeld vraag 28 of 30
                # volledig uit de fragmenten verdwenen is.
                for number in selection.get("question_numbers", []):
                    normalised_number = int(number)
                    start = question_map.get(normalised_number)
                    if not start:
                        raise HTTPException(
                            409,
                            f"CV-fragment gekoppeld aan vraag {normalised_number}, "
                            "maar voor dit nummer bestaat geen goedgekeurde vraagstart. "
                            "Heropen stap 7 (Vraagstarts correctievoorschrift), "
                            "controleer de detectie en sla de goedgekeurde vraagstarts opnieuw op."
                        )
                    rebuilt_questions.append({
                        "question_number": int(number), "start_id": start["id"],
                        "first_page": next(
                            (page["page_number"] for page in stitched_metadata["pages"]
                             if float(page["top"]) <= top < float(page["bottom"])),
                            start["page_index"] + 1,
                        ),
                        "last_page": next(
                            (page["page_number"] for page in reversed(stitched_metadata["pages"])
                             if float(page["top"]) < bottom and float(page["bottom"]) > top),
                            start["page_index"] + 1,
                        ),
                        "segments": [{"page_number": start["page_index"] + 1, "filename": filename, "url": url}],
                        "source_segments": None, "stitched": True,
                        # Analyseer uitsluitend de tekst binnen de goedgekeurde
                        # visuele selectie. Het label is alleen een omschrijving
                        # en mag nooit als vervanging voor vraagtekst dienen.
                        "extracted_text": _extract_stitched_selection_text(
                            source_path, stitched_metadata["pages"], top, bottom
                        ),
                        "reviewed": True,
                        "selection_id": selection.get("id"),
                    })
        if rebuilt_questions:
            proposals["questions"] = sorted(rebuilt_questions, key=lambda item: item["question_number"])
            proposals["question_count"] = len(proposals["questions"])
        if document_type == "opgaven":
            proposals["selected_contexts"] = stitched_contexts
    proposals["document"] = {"id": document["id"], "filename": document["filename"],
                             "sha256": document["sha256"]}
    proposals["document_type"] = document_type
    proposals["step_key"] = fragments_step_key
    raw_reviewed_numbers = previous.get("reviewed_question_numbers", [])
    # Oudere 0.17-builds konden hier per ongeluk een integer (het aantal
    # gecontroleerde vragen) opslaan. Dat getal is geen lijst met vraag-ID's;
    # behandel zulke records veilig als nog niet individueel gecontroleerd.
    reviewed_numbers = set(raw_reviewed_numbers) if isinstance(raw_reviewed_numbers, list) else set()
    for question in proposals["questions"]:
        question["reviewed"] = question["question_number"] in reviewed_numbers
    # Geef het fragmentenscherm de historische grenscorrecties mee. Deze
    # worden nog niet automatisch op een bestaande selectie toegepast; ze
    # zijn een uitlegbare referentie voor de volgende voorstelgeneratie.
    boundary_profiles = build_boundary_learning_profile(STORE.list_fragment_feedback())
    proposals["learning_boundary_profile"] = boundary_profiles.get(document_type, {
        "examples": 0, "active": False,
        "median_start_offset": None, "median_end_offset": None,
    })
    return proposals


def _save_document_fragment_review(exam_id: str, document_type: str, payload: dict):
    """Valideer en bewaar de fragmentcontrole van een documentsoort."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    starts_step_key, fragments_step_key = _fragment_step_keys(document_type)
    starts_step = exam["steps"].get(starts_step_key, {})
    if starts_step.get("status") != "complete":
        raise HTTPException(409, "Vraagstarts zijn nog niet goedgekeurd.")
    expected = {item["question_number"] for item in starts_step["evidence"].get("candidates", [])
                if item.get("accepted") and not item.get("removed")}
    reviewed = payload.get("reviewed_question_numbers")
    if not isinstance(reviewed, list) or any(not isinstance(number, int) for number in reviewed):
        raise HTTPException(422, "De lijst met gecontroleerde vraagnummers is ongeldig.")
    if not isinstance(reviewed, list):
        raise HTTPException(422, "De lijst met gecontroleerde vraagnummers moet een lijst zijn.")
    reviewed_set = set(reviewed)
    if not reviewed_set.issubset(expected):
        raise HTTPException(422, "Er is een vraagnummer aangeleverd dat niet bij de goedgekeurde starts hoort.")
    # Grenzen zijn in PDF-punten uitgedrukt. Valideer ze tegen de echte
    # eerste en laatste pagina van iedere vraag voordat ze als override worden
    # opgeslagen. Dit voorkomt lege uitsneden of uitsneden buiten de pagina.
    boundaries = payload.get("boundary_overrides", [])
    if not isinstance(boundaries, list):
        raise HTTPException(422, "De lijst met aangepaste fragmentgrenzen is ongeldig.")
    starts_by_number = {item["question_number"]: item for item in starts_step["evidence"].get("candidates", [])
                        if item.get("accepted") and not item.get("removed")}
    source_path = DATA / _document_for_type(exam, document_type)["relative_path"]
    with fitz.open(source_path) as source_pdf:
        page_sizes = [(page.rect.width, page.rect.height) for page in source_pdf]
        cv_content_end_page_index = (
            cv_content_end_page(source_pdf)
            if document_type == "correctievoorschrift"
            else len(page_sizes) - 1
        )
    ordered_starts = sorted(starts_by_number.values(),
                            key=lambda value: (value["page_index"], value["pdf_bbox"][1]))
    clean_boundaries = []
    seen_boundaries = set()
    for item in boundaries:
        if not isinstance(item, dict):
            raise HTTPException(422, "Een fragmentgrens heeft een ongeldig formaat.")
        number = item.get("question_number")
        if not isinstance(number, int) or number not in expected or number in seen_boundaries:
            raise HTTPException(422, "Een fragmentgrens hoort niet bij een unieke goedgekeurde vraag.")
        seen_boundaries.add(number)
        start = starts_by_number[number]
        index = ordered_starts.index(start)
        next_start = ordered_starts[index + 1] if index + 1 < len(ordered_starts) else None
        first_page = start["page_index"]
        last_page = next_start["page_index"] if next_start else (
            cv_content_end_page_index
        )
        start_y = float(item.get("start_y"))
        end_y = float(item.get("end_y"))
        first_height = page_sizes[first_page][1]
        last_height = page_sizes[last_page][1]
        if not (0 <= start_y < first_height and 0 < end_y <= last_height):
            raise HTTPException(422, f"Fragmentgrenzen vallen buiten de pagina bij vraag {number}.")
        if first_page == last_page and start_y >= end_y:
            raise HTTPException(422, f"De boven- en ondergrens kruisen elkaar bij vraag {number}.")
        clean_boundaries.append({"question_number": number, "start_y": start_y, "end_y": end_y})
    # Bewaar aanvullende stitchselecties wanneer de compatibele grensreview
    # de bestaande workflowvelden bijwerkt. Zonder deze merge zouden de
    # context-/vraagselecties verdwijnen zodra de stap wordt goedgekeurd.
    previous_evidence = exam["steps"].get(fragments_step_key, {}).get("evidence", {})
    evidence = {**previous_evidence,
                "reviewed_question_numbers": sorted(reviewed_set),
                "expected_question_numbers": sorted(expected),
                "reviewed_all_questions": bool(payload.get("reviewed_all_questions")),
                "boundary_overrides": clean_boundaries,
                "document_sha256": starts_step["evidence"].get("document_sha256")}
    # Een autosave die na de afrondactie aankomt, mag een identieke goedkeuring
    # niet terugzetten naar 'pending'. Bij een echte inhoudelijke wijziging
    # wordt de bestaande goedkeuring juist wel ingetrokken.
    STORE.save_step_draft_preserving_identical_complete(
        exam_id, fragments_step_key, evidence, identity_fields=tuple(evidence.keys())
    )
    return {"ok": True, "reviewed_count": len(reviewed_set), "expected_count": len(expected),
            "complete": evidence["reviewed_all_questions"] and reviewed_set == expected}


@app.get("/api/exams/{exam_id}/question-fragments")
def get_question_fragments(exam_id: str):
    """Compatibele fragmentroute voor het opgavendocument."""
    return _load_document_fragments(exam_id, "opgaven")


@app.post("/api/exams/{exam_id}/question-fragments/review")
def save_question_fragment_review(exam_id: str, payload: dict):
    """Compatibele reviewroute voor vraagfragmenten van de opgaven."""
    return _save_document_fragment_review(exam_id, "opgaven", payload)


def _repair_automatic_context_links(selections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Herstel oude automatische contextkoppelingen bij het laden van stap 3.

    Een eerdere versie koppelde een context tussen twee vragen aan alleen de
    voorafgaande vraag; een nog oudere versie koppelde hem aan alleen de
    eerstvolgende vraag. In werkelijkheid hoort de context als zelfstandig
    fragment bij de daaropvolgende vragen, tot aan het volgende contextblok.
    Herstel daarom alleen herkenbare oude automatische voorstellen. Bewuste
    handmatige koppelingen en de nieuwe groepskoppelingen blijven ongemoeid.
    """
    repaired = [dict(item) for item in selections]
    question_items = sorted(
        (item for item in repaired if item.get("type") == "vraag"),
        key=lambda item: float(item.get("top", 0)),
    )
    automatic_contexts = sorted(
        (
            item for item in repaired
            if item.get("type") == "context"
            and str(item.get("label", "")).startswith("Automatisch contextvoorstel")
            and (
                re.fullmatch(r"auto-context-between-\d+-\d+", str(item.get("id", "")))
                or re.fullmatch(r"auto-context-before-\d+", str(item.get("id", "")))
            )
        ),
        key=lambda item: float(item.get("top", 0)),
    )

    for index, context in enumerate(automatic_contexts):
        label = str(context.get("label", ""))
        current_numbers = context.get("question_numbers", [])
        identifier = str(context.get("id", ""))
        between = re.fullmatch(r"auto-context-between-(\d+)-(\d+)", identifier)
        leading = re.fullmatch(r"auto-context-before-(\d+)", identifier)

        # Alleen de bekende oude standaardlabels en enkelvoudige oude
        # koppelingen worden gemigreerd. Een docent die de vraagkoppeling
        # handmatig heeft uitgebreid, behoudt die keuze.
        legacy_link = False
        if between:
            previous_number, following_number = map(int, between.groups())
            legacy_link = (
                current_numbers in ([previous_number], [following_number])
                and label in {
                    "Automatisch contextvoorstel — ruimte tussen vraagfragmenten",
                    "Automatisch contextvoorstel — inhoud na de voorafgaande vraag",
                }
            )
        elif leading:
            first_number = int(leading.group(1))
            legacy_link = (
                current_numbers == [first_number]
                and label in {
                    "Automatisch contextvoorstel — zichtbare inhoud vóór de eerste vraag",
                    "Automatisch contextvoorstel — inhoud vóór de eerste vraag",
                }
            )

        if not legacy_link:
            continue

        # De volgende automatische context markeert het einde van de huidige
        # gedeelde contextgroep. Neem alle vraagfragmenten in het tussenliggende
        # documentgebied op, in plaats van slechts één vraagnummer.
        next_context_top = (
            float(automatic_contexts[index + 1].get("top", float("inf")))
            if index + 1 < len(automatic_contexts)
            else float("inf")
        )
        context_bottom = float(context.get("bottom", context.get("top", 0)))
        group_numbers = sorted({
            int(number)
            for question in question_items
            if context_bottom <= float(question.get("top", 0)) < next_context_top
            for number in question.get("question_numbers", [])
        })

        if group_numbers:
            context["question_numbers"] = group_numbers
            context["label"] = (
                "Automatisch contextvoorstel — inhoud vóór de bijbehorende vragen"
            )

    return repaired


@app.get("/api/exams/{exam_id}/stitched-opgaven")
def get_stitched_opgaven(exam_id: str):
    """Lever het lange selectiewerkvlak voor stap 3 van de opgaven."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    document = _document_for_type(exam, "opgaven")
    source = DATA / document["relative_path"]
    if STORE.sha256(source) != document["sha256"]:
        raise HTTPException(409, "Het bronbestand is gewijzigd sinds import.")
    output_dir = DATA / "exams" / exam_id / "derived" / "opgaven_stitched"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "exam-long.png"
    try:
        metadata = _load_or_build_stitched_exam(source, target, document["sha256"])
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    previous = exam["steps"].get("opgaven_fragments", {}).get("evidence", {})
    # Bestaande docentselecties blijven altijd leidend. Alleen bij een nieuw
    # examen worden automatische voorstellen gemaakt op basis van de al
    # goedgekeurde hoofdvraagstarts; opgeslagen werk wordt nooit overschreven.
    # Herstel bij het laden ook reeds opgeslagen automatische contexten uit
    # oudere versies. Zo blijft een context tussen vraag 37 en 38 gekoppeld
    # aan vraag 37, ook wanneer de gebruiker het examen eerder al had bewaard.
    saved_selections = _repair_automatic_context_links(
        previous.get("stitched_selections", [])
    )
    current_image_fingerprint = _stitched_image_fingerprint(target)
    selection_warning = None
    if saved_selections and not _stitched_selection_matches_image(previous, target):
        # BELANGRIJK: verwijder oude docentgrenzen nooit stilzwijgend.
        # De nieuwe renderer kan per pagina een andere verticale witmarge
        # wegsnijden. Daardoor kunnen de bewaarde pixelcoördinaten verschoven
        # zijn. We tonen ze daarom als herstelvoorstel op de nieuwe afbeelding,
        # met een duidelijke waarschuwing. De docent kan ze gericht corrigeren
        # in plaats van alle fragmenten opnieuw vanaf nul te tekenen.
        selection_warning = (
            "Je eerder opgeslagen fragmentgrenzen zijn behouden als herstelvoorstel. "
            "Door de vernieuwde uitsnedes kunnen sommige grenzen verticaal verschoven "
            "zijn. Controleer alle fragmenten op de afbeelding, corrigeer waar nodig "
            "en klik op ‘Nu opslaan’ voordat je de controle goedkeurt."
        )
    starts_evidence = exam["steps"].get("opgaven_starts", {}).get("evidence", {})
    accepted_starts = [
        item for item in starts_evidence.get("candidates", [])
        if item.get("accepted") and not item.get("removed")
    ]
    proposed = propose_stitched_question_selections(
        metadata.get("pages", []),
        accepted_starts,
        render_scale=1.25,
        image_height=int(metadata["height"]),
        pdf_path=source,
    ) if not saved_selections else []

    # Bereken de enige toegestane grensposities op basis van de werkelijk
    # gerenderde afbeelding. Automatische voorstellen worden naar de dichtstbijzijnde
    # volledig witte rij verschoven voordat ze aan de browser worden geleverd.
    white_rows = metadata.get("white_row_ranges") or _white_row_ranges(target)
    if proposed:
        # Normaliseer vraagfragmenten vóórdat de browser ze ziet. Daardoor
        # overlappen twee vragen nooit en worden lege witruimtes geen context.
        proposed = normalise_stitched_selections(
            proposed,
            white_rows,
            target,
            image_height=int(metadata["height"]),
            leading_top=min((float(page["top"]) for page in metadata.get("pages", [])), default=0.0),
            context_candidates_only=True,
        )

    # De titel van ieder contextdeel wordt uit de oorspronkelijke PDF gelezen.
    # De afbeelding blijft leidend voor de grenzen; de tekstlaag levert alleen
    # de eerste tekstregel die als titel in de contextgroep wordt getoond.
    for selection in [*saved_selections, *proposed]:
        if selection.get("type") == "context":
            selection["context_title"] = _context_title_for_selection(
                source, metadata.get("pages", []), selection
            )

    # De voorstelgenerator levert nu zowel vraagfragmenten als contexten.
    # Contexten zijn exacte uitsneden tussen vraagfragmenten; de docent kan
    # hun onderlinge samenhang daarna expliciet leggen via overlappende vragen.

    metadata.update({
        "image_url": f"/api/stitched-opgaven-images/{exam_id}/exam-long.png",
        "document_sha256": document["sha256"],
        "stitched_image_sha256": current_image_fingerprint,
        "selection_warning": selection_warning,
        "selections": saved_selections,
        "proposed_selections": proposed,
        "white_row_ranges": white_rows,
        "segmentation_mode": "saved" if saved_selections else "automatic_proposal",
    })
    return metadata


@app.get("/api/exams/{exam_id}/stitched-document/{document_type}")
def get_stitched_document(exam_id: str, document_type: str):
    """Lever een doorlopende afbeelding voor de fragmentreview van een document.

    De route wordt gebruikt voor de uitwerkbijlage (stap 6) en het
    correctievoorschrift (stap 8). Beide documenten gebruiken dezelfde
    doorlopende, paginabrede selectiewerkruimte als de opgaven (stap 3).
    Alleen vraagfragmenten worden voorgesteld; contextfragmenten zijn hier
    niet van toepassing. Bij CV's eindigt de afbeelding vóór de administratieve
    slotsectie, zodat die nooit in het laatste vraagfragment terechtkomt.
    """
    if document_type not in {"uitwerkbijlage", "correctievoorschrift"}:
        raise HTTPException(404, "Deze doorlopende fragmentreview is niet beschikbaar voor dit documenttype.")
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    document = _document_for_type(exam, document_type)
    source = DATA / document["relative_path"]
    if STORE.sha256(source) != document["sha256"]:
        raise HTTPException(409, "Het bronbestand is gewijzigd sinds import.")

    output_dir = DATA / "exams" / exam_id / "derived" / f"{document_type}_stitched"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "exam-long.png"
    try:
        start_page, end_page, start_y = _stitched_page_selection(source, document_type)
        metadata = _load_or_build_stitched_exam(
            source, target, document["sha256"], start_page=start_page,
            end_page=end_page, start_y=start_y,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc

    starts_step_key, fragments_step_key = _fragment_step_keys(document_type)
    previous = exam["steps"].get(fragments_step_key, {}).get("evidence", {})
    saved = previous.get("stitched_selections", [])
    current_image_fingerprint = _stitched_image_fingerprint(target)
    selection_warning = None
    if saved and not _stitched_selection_matches_image(previous, target):
        # Bewaar oude docentgrenzen als herstelvoorstel. De nieuwe renderer
        # kan verticale witmarges per pagina anders afsnijden; pixelcoördinaten
        # kunnen daardoor verschoven zijn. De waarschuwing vraagt om visuele
        # controle en expliciet opnieuw opslaan voordat de stap wordt afgerond.
        selection_warning = (
            "Je eerder opgeslagen fragmentgrenzen zijn behouden als herstelvoorstel. "
            "Door de vernieuwde uitsnedes kunnen sommige grenzen verticaal verschoven "
            "zijn. Controleer alle fragmenten op de afbeelding, corrigeer waar nodig "
            "en klik op ‘Nu opslaan’ voordat je de controle goedkeurt."
        )
    starts = exam["steps"].get(starts_step_key, {}).get("evidence", {})
    accepted = [
        item for item in starts.get("candidates", [])
        if item.get("accepted") and not item.get("removed")
    ]
    proposed = []
    if not saved:
        proposed = propose_stitched_question_selections(
            metadata.get("pages", []), accepted,
            render_scale=1.25, image_height=int(metadata["height"]),
            pdf_path=source,
        )
        # Uitwerkbijlage en CV bestaan hier uitsluitend uit vraagfragmenten;
        # contextselecties zijn niet van toepassing in deze documenttypen.
        proposed = [item for item in proposed if item.get("type") == "vraag"]

    white_rows = metadata.get("white_row_ranges") or _white_row_ranges(target)
    if proposed:
        # Net als in stap 3 worden automatische grenzen vóór weergave op
        # volledig witte pixelrijen gelegd. De docent kan ze daarna verfijnen.
        proposed = normalise_stitched_selections(
            proposed, white_rows, target,
            image_height=int(metadata["height"]),
            leading_top=min(
                (float(page["top"]) for page in metadata.get("pages", [])),
                default=0.0,
            ),
            context_candidates_only=True,
        )
    metadata.update({
        "image_url": f"/api/stitched-document-images/{exam_id}/{document_type}/exam-long.png",
        "document_sha256": document["sha256"],
        "stitched_image_sha256": current_image_fingerprint,
        "selection_warning": selection_warning,
        "selections": saved,
        "proposed_selections": proposed,
        "white_row_ranges": white_rows,
        "segmentation_mode": "saved" if saved else "automatic_proposal",
    })
    return metadata


@app.get("/api/stitched-document-images/{exam_id}/{document_type}/{filename}")
def stitched_document_image(exam_id: str, document_type: str, filename: str):
    """Serveer de afgeleide lange afbeelding voor de geselecteerde documentsoort."""
    if document_type not in {"uitwerkbijlage", "correctievoorschrift"} or filename != "exam-long.png":
        raise HTTPException(404, "Afbeelding niet gevonden.")
    if not re.fullmatch(r"[a-f0-9]{12}", exam_id) or not STORE.get_exam(exam_id):
        raise HTTPException(404, "Examen niet gevonden.")
    path = DATA / "exams" / exam_id / "derived" / f"{document_type}_stitched" / filename
    if not path.is_file():
        raise HTTPException(404, "Afbeelding niet gevonden.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/exams/{exam_id}/stitched-document/{document_type}/review")
def save_stitched_document_review(exam_id: str, document_type: str, payload: dict):
    """Bewaar vraagfragmenten van de doorlopende uitwerkbijlage of het CV."""
    if document_type not in {"uitwerkbijlage", "correctievoorschrift"}:
        raise HTTPException(404, "Deze fragmentreview is niet beschikbaar voor dit documenttype.")
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    starts_step_key, fragments_step_key = _fragment_step_keys(document_type)
    starts = exam["steps"].get(starts_step_key, {})
    if starts.get("status") != "complete":
        raise HTTPException(409, "Rond eerst de vraagstartcontrole van dit document af.")
    selections = payload.get("selections")
    if not isinstance(selections, list):
        raise HTTPException(422, "De fragmentselecties ontbreken.")

    stitched_path = DATA / "exams" / exam_id / "derived" / f"{document_type}_stitched" / "exam-long.png"
    if not stitched_path.is_file():
        document = _document_for_type(exam, document_type)
        source_path = DATA / document["relative_path"]
        start_page, end_page, start_y = _stitched_page_selection(source_path, document_type)
        _load_or_build_stitched_exam(
            source_path, stitched_path, document["sha256"],
            start_page=start_page, end_page=end_page, start_y=start_y,
        )
    with Image.open(stitched_path) as image:
        stitched_height = image.height
    white_rows = _white_row_ranges(stitched_path)

    clean = []
    for index, item in enumerate(selections):
        if not isinstance(item, dict):
            raise HTTPException(422, "Een fragmentselectie heeft een ongeldig formaat.")
        top, bottom = item.get("top"), item.get("bottom")
        numbers = item.get("question_numbers")
        if (item.get("type") != "vraag"
                or not isinstance(top, (int, float)) or not isinstance(bottom, (int, float))
                or not float(top).is_integer() or not float(bottom).is_integer()
                or top < 0 or bottom <= top or bottom >= stitched_height):
            raise HTTPException(422, "Een vraagfragment moet een geldige selectie met gehele pixelgrenzen binnen de lange afbeelding zijn.")
        if not _is_white_boundary(top, white_rows) or not _is_white_boundary(bottom, white_rows):
            raise HTTPException(422, "Plaats beide fragmentgrenzen op een volledig witte horizontale regel over de volledige paginabreedte.")
        if (not isinstance(numbers, list) or not numbers
                or any(not isinstance(number, int) or not 1 <= number <= 60 for number in numbers)):
            raise HTTPException(422, "Koppel ieder vraagfragment aan minimaal één geldig vraagnummer.")
        clean.append({
            "id": str(item.get("id") or f"fragment-{index + 1}"),
            "type": "vraag", "top": int(top), "bottom": int(bottom),
            "question_numbers": sorted(set(numbers)),
            "label": str(item.get("label") or "")[:160],
        })

    if payload.get("reviewed"):
        expected = {
            item["question_number"] for item in starts["evidence"].get("candidates", [])
            if item.get("accepted") and not item.get("removed")
        }
        covered = {number for item in clean for number in item["question_numbers"]}
        missing = sorted(expected - covered)
        if missing:
            raise HTTPException(422, "Selecteer nog vraagfragmenten voor vraag: " +
                                ", ".join(map(str, missing)))

    evidence = {
        **exam["steps"].get(fragments_step_key, {}).get("evidence", {}),
        "stitched_selections": clean,
        "stitched_reviewed": bool(payload.get("reviewed")),
        # Verwijder eventuele oude PDF-puntgrenzen uit de eerdere stap-8-
        # interface. De nieuwe review bewaart uitsluitend pixelgrenzen van
        # de volledige lange afbeelding; oude overrides horen niet meer in
        # het nieuwe coördinatenstelsel thuis.
        "boundary_overrides": [],
        "document_sha256": starts.get("evidence", {}).get("document_sha256"),
        "stitched_image_sha256": _stitched_image_fingerprint(stitched_path),
    }
    saved_as_draft = STORE.save_step_draft_preserving_identical_complete(
        exam_id, fragments_step_key, evidence,
        identity_fields=("stitched_selections", "document_sha256", "stitched_image_sha256"),
    )
    return {"ok": True, "selection_count": len(clean),
            "reviewed": evidence["stitched_reviewed"],
            "complete": not saved_as_draft}


@app.get("/api/stitched-opgaven-images/{exam_id}/{filename}")
def stitched_opgaven_image(exam_id: str, filename: str):
    """Serveer uitsluitend de gegenereerde lange afbeelding van dit examen."""
    if filename != "exam-long.png" or not re.fullmatch(r"[a-f0-9]{12}", exam_id):
        raise HTTPException(404, "Afbeelding niet gevonden.")
    if not STORE.get_exam(exam_id):
        raise HTTPException(404, "Examen niet gevonden.")
    path = DATA / "exams" / exam_id / "derived" / "opgaven_stitched" / filename
    if not path.is_file():
        raise HTTPException(404, "Afbeelding niet gevonden.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/exams/{exam_id}/stitched-opgaven/review")
def save_stitched_opgaven_review(exam_id: str, payload: dict):
    """Bewaar docentselecties als context- of vraagfragmenten op het stitchwerkvlak."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    starts = exam["steps"].get("opgaven_starts", {})
    if starts.get("status") != "complete":
        raise HTTPException(409, "Rond eerst de vraagstartcontrole af.")
    selections = payload.get("selections")
    if not isinstance(selections, list):
        raise HTTPException(422, "De fragmentselecties ontbreken.")
    # Valideer de grenzen tegen de werkelijk gegenereerde afbeelding; zo kan
    # een foutieve of verouderde browsercoördinaat nooit buiten de bron vallen.
    stitched_path = DATA / "exams" / exam_id / "derived" / "opgaven_stitched" / "exam-long.png"
    document = _document_for_type(exam, "opgaven")
    source_path = DATA / document["relative_path"]
    # Laad ook de stitchmetadata wanneer de PNG al bestaat. De metadata bevat
    # de omzetting van pixelgrenzen naar PDF-gebieden die nodig is om de
    # actuele contexttitel betrouwbaar uit de bron te kunnen uitlezen.
    stitched_metadata = _load_or_build_stitched_exam(
        source_path, stitched_path, document["sha256"]
    )
    with Image.open(stitched_path) as stitched_image:
        stitched_height = stitched_image.height
    # De server herhaalt de pixelcontrole. Zo kunnen verouderde browsers of
    # handmatig aangepaste API-verzoeken nooit een grens op tekstpixels opslaan.
    white_rows = _white_row_ranges(stitched_path)
    clean = []
    for index, item in enumerate(selections):
        if not isinstance(item, dict):
            raise HTTPException(422, "Een fragmentselectie heeft een ongeldig formaat.")
        kind = item.get("type")
        top, bottom = item.get("top"), item.get("bottom")
        numbers = item.get("question_numbers")
        if (kind not in {"context", "vraag"}
                or not isinstance(top, (int, float)) or not isinstance(bottom, (int, float))
                or not float(top).is_integer() or not float(bottom).is_integer()
                or top < 0 or bottom <= top or bottom >= stitched_height):
            raise HTTPException(422, "Een fragmenttype of fragmentgrens is ongeldig. Gebruik gehele pixelrijen binnen de lange afbeelding.")
        if not _is_white_boundary(top, white_rows) or not _is_white_boundary(bottom, white_rows):
            raise HTTPException(422, "Plaats beide fragmentgrenzen op een volledig witte horizontale regel van links tot rechts.")
        if not isinstance(numbers, list) or not numbers or any(not isinstance(n, int) or not 1 <= n <= 60 for n in numbers):
            raise HTTPException(422, "Koppel ieder fragment aan minimaal één geldig vraagnummer.")
        clean.append({"id": str(item.get("id") or f"fragment-{index+1}"), "type": kind,
                      "top": round(float(top), 2), "bottom": round(float(bottom), 2),
                      "question_numbers": sorted(set(numbers)),
                      "label": str(item.get("label") or "")[:160]})
    if payload.get("reviewed"):
        expected_numbers = {item["question_number"] for item in starts["evidence"].get("candidates", [])
                            if item.get("accepted") and not item.get("removed")}
        covered_numbers = {number for item in clean if item["type"] == "vraag"
                           for number in item["question_numbers"]}
        missing_numbers = sorted(expected_numbers - covered_numbers)
        if missing_numbers:
            raise HTTPException(422, "Selecteer nog vraagfragmenten voor: " + ", ".join(map(str, missing_numbers)))
    evidence = exam["steps"].get("opgaven_fragments", {}).get("evidence", {})
    evidence.update({"stitched_selections": clean,
                     "stitched_reviewed": bool(payload.get("reviewed")),
                     "document_sha256": starts.get("evidence", {}).get("document_sha256"),
                     "stitched_image_sha256": _stitched_image_fingerprint(stitched_path)})

    # Ook voor de fragmentreview kan een autosave vanaf pagehide of
    # visibilitychange pas na de afrondactie aankomen. Een identieke
    # momentopname mag de complete stap niet terugzetten naar pending; een
    # daadwerkelijk gewijzigde selectie moet de goedkeuring juist intrekken.
    saved_as_draft = STORE.save_step_draft_preserving_identical_complete(
        exam_id,
        "opgaven_fragments",
        evidence,
        identity_fields=("stitched_selections", "document_sha256", "stitched_image_sha256"),
    )
    # Geef de titels terug bij iedere opslag. Wanneer de docent een
    # fragmentgrens verplaatst, wordt de titel dus opnieuw bepaald op basis
    # van de tekst die nu werkelijk binnen de uitsnede valt.
    context_titles = {
        item["id"]: _context_title_for_selection(
            source_path, stitched_metadata.get("pages", []), item
        )
        for item in clean if item["type"] == "context"
    }
    return {"ok": True, "selection_count": len(clean),
            "reviewed": evidence["stitched_reviewed"],
            "complete": not saved_as_draft,
            "context_titles": context_titles}


@app.get("/api/exams/{exam_id}/document-question-fragments/{document_type}")
def get_document_question_fragments(exam_id: str, document_type: str):
    """Vraagfragmenten genereren voor opgaven, uitwerkbijlage of CV."""
    return _load_document_fragments(exam_id, document_type)


@app.post("/api/exams/{exam_id}/document-question-fragments/{document_type}/review")
def save_document_question_fragment_review(exam_id: str, document_type: str, payload: dict):
    """Visuele controle van fragmenten voor de gekozen documentsoort opslaan."""
    return _save_document_fragment_review(exam_id, document_type, payload)


@app.get("/api/question-fragment-images/{exam_id}/{document_type}/{filename}")
def question_fragment_image(exam_id: str, document_type: str, filename: str):
    """Serveer alleen PNG-bestanden uit de juiste afgeleide fragmentwerkmap."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.png", filename):
        raise HTTPException(400, "Ongeldige bestandsnaam.")
    if document_type not in {"opgaven", "uitwerkbijlage", "correctievoorschrift"}:
        raise HTTPException(404, "Documenttype niet gevonden.")
    if not re.fullmatch(r"[a-f0-9]{12}", exam_id) or not STORE.get_exam(exam_id):
        raise HTTPException(404, "Examen niet gevonden.")
    path = DATA / "exams" / exam_id / "derived" / f"{document_type}_fragments" / filename
    if not path.is_file():
        raise HTTPException(404, "Fragmentafbeelding niet gevonden.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


def _merge_saved_question_analysis(question: dict[str, Any], saved: dict[str, Any]) -> None:
    """Behoud docentcorrecties zonder nieuwe automatische herkenning te blokkeren.

    Een eerdere versie bewaarde ook onvoltooide automatische voorstellen als
    concept. Als die oude voorstellen bij het heropenen blind werden teruggezet,
    kon een later verbeterde OCR-herkenning nooit zichtbaar worden. Definitief
    beoordeelde vragen blijven volledig leidend; bij open concepten vullen we
    ontbrekende gegevens aan met de actuele herkenning en behouden we bestaande
    handmatige antwoordteksten per letter.
    """
    if saved.get("reviewed"):
        # Een expliciet gecontroleerde vraag is een docentbeslissing en mag
        # nooit door een nieuwe automatische analyse worden overschreven.
        question.update({
            key: saved[key]
            for key in ("question_type", "max_points", "options", "options_reviewed", "reviewed")
            if key in saved
        })
        return

    saved_type = saved.get("question_type")
    detected_type = question.get("question_type")
    if saved_type:
        # Een oud concept met type 'open' of 'onbekend' mag een nieuwe sterke
        # meerkeuze-/gesloten herkenning niet blokkeren. Een eerder expliciet
        # gekozen meerkeuze- of gesloten type blijft wel behouden.
        if saved_type in {"meerkeuze", "gesloten"} or detected_type not in {"meerkeuze", "gesloten"}:
            question["question_type"] = saved_type

    # Een handmatig ingevulde score blijft behouden. Een leeg oud veld wordt
    # aangevuld met de actuele PDF-/OCR-herkenning.
    if saved.get("max_points") is not None:
        question["max_points"] = saved["max_points"]

    # Voeg de actuele OCR-opties samen met bestaande docentcorrecties. Een
    # handmatig aangepaste tekst heeft voorrang; nieuwe letters die eerder
    # ontbraken worden vanuit de actuele herkenning toegevoegd.
    if saved.get("options_reviewed"):
        # Zodra de docent de antwoordoptielijst zelf heeft aangepast, is die
        # lijst expliciet leidend. Anders zou een verwijderde OCR-optie bij
        # het opnieuw openen van stap 4 ongemerkt terug kunnen verschijnen.
        question["options"] = saved.get("options", [])
        question["options_reviewed"] = True
    else:
        # Zolang de docent de optielijst nog niet heeft aangepast, vullen we
        # actuele OCR-herkenning aan met eerder opgeslagen handmatige teksten
        # en beelduitsneden. Een opgeslagen beeldoptie krijgt voorrang.
        current_options = {
            item.get("letter"): item
            for item in question.get("options", [])
            if item.get("letter")
        }
        saved_options = {
            item.get("letter"): item
            for item in saved.get("options", [])
            # Een optie met alleen een afbeelding heeft bewust geen tekst.
            # Behoud daarom ook zulke opties bij het opnieuw openen van stap 4.
            if item.get("letter") and (item.get("text", "").strip() or item.get("image_data"))
        }
        if saved_options or current_options:
            question["options"] = [
                saved_options.get(letter) or current_options[letter]
                for letter in "ABCDEF"
                if letter in saved_options or letter in current_options
            ]
        question["options_reviewed"] = False

    # Een concept blijft een concept totdat de docent de vraag expliciet
    # heeft gecontroleerd; alleen de voorstellen worden hier bijgewerkt.
    question["reviewed"] = False


@app.get("/api/exams/{exam_id}/question-analysis")
def get_question_analysis(exam_id: str):
    """Maak type-, punten- en antwoordoptievoorstellen per vraag."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    fragments = get_question_fragments(exam_id)

    # Koppel ieder vraagfragment aan het werkelijk gegenereerde PNG-bestand.
    # Stap 4 kan daardoor, wanneer de selecteerbare PDF-tekstlaag tekortschiet,
    # de zichtbare vraag inclusief antwoordopties lokaal met OCR uitlezen.
    # De bestandspaden blijven intern: analyse_questions neemt ze niet op in
    # de API-respons en de browser ontvangt alleen de herkende voorstellen.
    fragment_image_dir = DATA / "exams" / exam_id / "derived" / "opgaven_fragments"
    for question in fragments.get("questions", []):
        question["image_paths"] = [
            str(fragment_image_dir / segment["filename"])
            for segment in question.get("segments", [])
            if segment.get("filename") and (fragment_image_dir / segment["filename"]).is_file()
        ]

    result = analyse_questions(fragments)
    result["document"] = fragments["document"]
    previous = exam["steps"].get("opgaven_analyse", {}).get("evidence", {})
    saved_questions = {item["question_number"]: item for item in previous.get("questions", [])}
    for question in result["questions"]:
        saved = saved_questions.get(question["question_number"])
        if saved:
            _merge_saved_question_analysis(question, saved)
    return result


@app.post("/api/exams/{exam_id}/question-analysis/review")
def save_question_analysis_review(exam_id: str, payload: dict):
    """Bewaar type-/puntenvoorstellen en docentcorrecties als concept."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    fragments = get_question_fragments(exam_id)
    expected = {item["question_number"] for item in fragments["questions"]}
    try:
        review = validate_question_analysis(payload, expected)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    review["document_sha256"] = fragments["document"]["sha256"]
    # Bewaar conceptwijzigingen, maar laat een identieke late autosave een
    # reeds afgeronde stap niet onbedoeld terugzetten naar 'pending'.
    STORE.save_step_draft_preserving_identical_complete(
        exam_id, "opgaven_analyse", review, identity_fields=tuple(review.keys())
    )
    return {"ok": True, **review, "complete": review["reviewed_all_questions"]}



@app.get("/api/exams/{exam_id}/cv-supplement")
def get_cv_supplement(exam_id: str):
    """Toon een eventuele aanvulling afzonderlijk van het oorspronkelijke CV."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    documents = [doc for doc in exam["documents"]
                 if (exam["metadata"].get("document_types", {}).get(doc["filename"]) == "aanvulling_correctievoorschrift"
                     or doc.get("metadata", {}).get("document_type") == "aanvulling_correctievoorschrift")]
    if not documents:
        return {"not_required": True, "items": [], "page_count": 0}
    if len(documents) != 1:
        raise HTTPException(422, "Er moet precies één aanvulling op het correctievoorschrift zijn toegewezen.")
    document = documents[0]
    path = DATA / document["relative_path"]
    if STORE.sha256(path) != document["sha256"]:
        raise HTTPException(409, "De PDF-aanvulling is gewijzigd sinds import.")
    result = analyse_supplement(str(path))
    result["document"] = {"id": document["id"], "filename": document["filename"],
                           "sha256": document["sha256"]}
    previous = exam["steps"].get("cv_aanvulling", {}).get("evidence", {})
    saved = {item["page_number"]: item for item in previous.get("items", [])}
    for item in result["items"]:
        if item["page_number"] in saved:
            item.update({k: saved[item["page_number"]][k] for k in ("action", "question_numbers", "reviewed") if k in saved[item["page_number"]]})
    return result


@app.post("/api/exams/{exam_id}/cv-supplement/review")
def save_cv_supplement_review(exam_id: str, payload: dict):
    """Bewaar keuzes per supplementpagina; voeg niets stilzwijgend samen."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    result = get_cv_supplement(exam_id)
    if result.get("not_required"):
        raise HTTPException(409, "Dit examen heeft geen aanvulling op het correctievoorschrift.")
    expected = {item["page_number"] for item in result["items"]}
    try:
        review = validate_supplement_review(payload, expected)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    opgaven_numbers = {item["question_number"] for item in
                       exam["steps"].get("opgaven_starts", {}).get("evidence", {}).get("candidates", [])
                       if item.get("accepted") and not item.get("removed")}
    for item in review["items"]:
        unknown = set(item["question_numbers"]) - opgaven_numbers
        if unknown:
            raise HTTPException(422, f"Supplementpagina {item['page_number']} verwijst naar onbekende examenvragen: {sorted(unknown)}.")
    review["document_sha256"] = result["document"]["sha256"]
    # Een identieke autosave na afronden behoudt de bestaande goedkeuring.
    STORE.save_step_draft_preserving_identical_complete(
        exam_id, "cv_aanvulling", review, identity_fields=tuple(review.keys())
    )
    return {"ok": True, **review, "complete": review["reviewed_all_pages"]}


@app.get("/api/exams/{exam_id}/answers")
def get_answers(exam_id: str):
    """Maak antwoordvoorstellen vanuit het CV, naast de volledige CV-afbeelding."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    cv_fragments = get_document_question_fragments(exam_id, "correctievoorschrift")
    analysis = get_question_analysis(exam_id)
    result = analyse_answers(cv_fragments, analysis)
    # Verwerk eerst de expliciet beoordeelde aanvulling. Een vervanging wordt
    # als vervangend antwoordvoorstel getoond; een toevoeging blijft naast het
    # oorspronkelijke CV-antwoord zichtbaar. Geen enkele pagina wordt zonder
    # de eerdere docentreview toegepast.
    supplement = get_cv_supplement(exam_id)
    supplement_evidence = exam["steps"].get("cv_aanvulling", {}).get("evidence", {})
    supplement_items = {item["page_number"]: item for item in supplement_evidence.get("items", [])}
    supplement_pages = {item["page_number"]: item for item in supplement.get("items", [])}
    for question in result["questions"]:
        matched_pages = []
        for page_number, decision in supplement_items.items():
            if question["question_number"] not in decision.get("question_numbers", []):
                continue
            action = decision.get("action")
            if action == "negeren":
                continue
            page = supplement_pages.get(page_number, {})
            page_text = page.get("question_texts", {}).get(str(question["question_number"]), page.get("text", ""))
            matched_pages.append({"page_number": page_number, "action": action,
                                  "text": page_text,
                                  "url": (f"/api/exams/{exam_id}/documents/{supplement['document']['id']}/preview/{page_number - 1}")
                                         if supplement.get("document") else None})
            if action == "vervangen":
                question["answer_text"] = page_text
                # Als de aanvulling zelf een nieuwe maximumscore vermeldt,
                # gebruik die als effectieve CV-score. Zonder expliciete score
                # blijft de oorspronkelijke score staan; de app gokt niet.
                replacement_score = detect_cv_max_points(page_text, question["question_number"])
                if replacement_score is not None:
                    question["cv_max_points"] = replacement_score
                    question["points_match"] = (replacement_score == question.get("opgaven_max_points")) if question.get("opgaven_max_points") is not None else None
                question["answer_kind"] = "handmatig"
                question["confidence"] = "laag"
                question["reason"] = "De aanvulling is als vervanging gemarkeerd; controleer de volledige vervangende tekst."
            elif action in {"toevoegen", "handmatig"}:
                question["answer_text"] = (question["answer_text"] + "\n\nAanvulling (pagina " +
                                            str(page_number) + "): \n" + page_text).strip()
                if action == "handmatig":
                    question["answer_kind"] = "handmatig"
                    question["confidence"] = "laag"
        question["supplement_pages"] = matched_pages
    previous = exam["steps"].get("antwoorden", {}).get("evidence", {})
    saved = {item["question_number"]: item for item in previous.get("questions", [])}
    for question in result["questions"]:
        if question["question_number"] in saved:
            question.update({k: saved[question["question_number"]][k]
                             for k in ("answer_kind", "answer_text", "cv_max_points", "opgaven_max_points", "points_match", "supplement_pages", "reviewed")})
    return result


@app.post("/api/exams/{exam_id}/answers/review")
def save_answers_review(exam_id: str, payload: dict):
    """Sla handmatig gecontroleerde antwoorden op als conceptbewijs."""
    result = get_answers(exam_id)
    expected = {item["question_number"] for item in result["questions"]}
    # Supplementpagina's worden door de server gekoppeld aan de goedgekeurde
    # pagina-/vraagbeslissingen. Neem die herkomstinformatie niet over uit een
    # browserpayload die de gebruiker zelf kan aanpassen.
    supplement_by_number = {item["question_number"]: item.get("supplement_pages", [])
                            for item in result["questions"]}
    payload = {**payload, "questions": [
        {**item, "supplement_pages": supplement_by_number.get(item.get("question_number"), [])}
        for item in payload.get("questions", []) if isinstance(item, dict)
    ]}
    try:
        review = validate_answer_review(payload, expected)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    review["cv_sha256"] = result.get("document", {}).get("sha256")
    # Antwoordvelden worden automatisch opgeslagen. Als een al gestarte
    # autosave pas na de afrondactie aankomt, mag identieke inhoud de status
    # 'complete' niet terugzetten naar 'pending'.
    STORE.save_step_draft_preserving_identical_complete(
        exam_id, "antwoorden", review, identity_fields=tuple(review.keys())
    )
    return {"ok": True, **review, "complete": review["reviewed_all_questions"]}


@app.get("/api/exams/{exam_id}/relations")
def get_relations(exam_id: str):
    """Maak een controlelijst voor de koppeling van vragen tussen documenten."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    def numbers(step_key: str) -> set[int]:
        evidence = exam["steps"].get(step_key, {}).get("evidence", {})
        if step_key.endswith("_starts"):
            return {item["question_number"] for item in evidence.get("candidates", [])
                    if item.get("accepted") and not item.get("removed")}
        return {item["question_number"] for item in evidence.get("questions", [])}
    opgaven = numbers("opgaven_starts")
    cv = numbers("cv_starts")
    uitwerk = numbers("uitwerk_starts")
    analysis = exam["steps"].get("opgaven_analyse", {}).get("evidence", {}).get("questions", [])
    answer_evidence = exam["steps"].get("antwoorden", {}).get("evidence", {}).get("questions", [])
    cv_scores = {item["question_number"]: item for item in answer_evidence}
    saved = {item["question_number"]: item for item in
             exam["steps"].get("relaties", {}).get("evidence", {}).get("questions", [])}
    questions = []
    for number in sorted(opgaven):
        question_analysis = next((item for item in analysis if item["question_number"] == number), {})
        cv_score = cv_scores.get(number, {}).get("cv_max_points")
        opgaven_score = question_analysis.get("max_points")
        questions.append({"question_number": number, "has_opgaven": True,
                          "has_cv": number in cv, "has_uitwerkbijlage": number in uitwerk,
                          "max_points": opgaven_score, "cv_max_points": cv_score,
                          "points_match": (cv_score == opgaven_score) if cv_score is not None and opgaven_score is not None else None,
                          "reviewed": saved.get(number, {}).get("reviewed", False)})
    score_mismatches = [
        {"question_number": item["question_number"],
         "opgaven_max_points": item["max_points"],
         "cv_max_points": item["cv_max_points"]}
        for item in questions if item["points_match"] is False
    ]
    answer_numbers = set(cv_scores)
    # De vraaganalyse en antwoordherkenning leveren ook onzekerheden op die
    # eerder al inhoudelijk zijn goedgekeurd. Toon ze hier nogmaals als
    # aandachtspunt, zodat de integriteitscontrole niets stilzwijgend verbergt.
    uncertain_analysis = sorted(
        item["question_number"] for item in analysis
        if item.get("question_type") == "onbekend" or item.get("max_points") is None
    )
    uncertain_answers = sorted(
        item["question_number"] for item in answer_evidence
        if item.get("answer_kind") == "handmatig" or not str(item.get("answer_text", "")).strip()
    )
    return {"question_count": len(questions), "questions": questions,
            "missing_cv": sorted(opgaven - cv), "extra_cv": sorted(cv - opgaven),
            "missing_answers": sorted((opgaven & cv) - answer_numbers),
            "extra_answers": sorted(answer_numbers - opgaven),
            "score_mismatches": score_mismatches,
            "uncertain_analysis": uncertain_analysis,
            "uncertain_answers": uncertain_answers,
            "uitwerk_questions": sorted(uitwerk)}


@app.post("/api/exams/{exam_id}/relations/review")
def save_relations_review(exam_id: str, payload: dict):
    """Bewaar alleen inhoudelijke uitzonderingen; normale koppelingen zijn automatisch akkoord.

    De vraagnummerkoppeling tussen de documenten is deterministisch. Daarom
    hoeft de docent niet iedere normale vraag afzonderlijk af te vinken.
    De lijst met vragen blijft wel als controlebewijs bestaan. Alleen een
    afwijking kan een toelichting krijgen en blijft zichtbaar in stap 11.
    """
    result = get_relations(exam_id)
    exam = STORE.get_exam(exam_id)
    previous = exam["steps"].get("relaties", {}).get("evidence", {})
    previous_by_number = {
        item["question_number"]: item for item in previous.get("questions", [])
    }
    submitted = payload.get("questions", [])
    if not isinstance(submitted, list):
        raise HTTPException(422, "De uitzonderingen bij de vraagkoppelingen hebben een ongeldig formaat.")
    submitted_by_number = {}
    for item in submitted:
        number = item.get("question_number") if isinstance(item, dict) else None
        if not isinstance(number, int) or number not in {q["question_number"] for q in result["questions"]}:
            raise HTTPException(422, "Een vraagnummer bij de koppelingen is ongeldig.")
        submitted_by_number[number] = item

    # Alle gewone vraagkoppelingen worden automatisch als gecontroleerd
    # geregistreerd. Handmatige toelichtingen blijven behouden, ook wanneer
    # de gebruiker alleen de knop 'opslaan' gebruikt.
    cleaned = []
    for question in result["questions"]:
        number = question["question_number"]
        item = submitted_by_number.get(number, previous_by_number.get(number, {}))
        cleaned.append({
            "question_number": number,
            "reviewed": True,
            "note": str(item.get("note", ""))[:1000],
        })

    evidence = {
        "questions": cleaned,
        "reviewed_count": len(cleaned),
        "reviewed_all_questions": bool(cleaned),
        "missing_cv": result["missing_cv"],
        "extra_cv": result["extra_cv"],
        "score_mismatches": result["score_mismatches"],
    }
    # Ook toelichtingen worden automatisch opgeslagen. Behoud een afgeronde
    # status wanneer een vertraagde autosave exact hetzelfde bewijs bevat.
    STORE.save_step_draft_preserving_identical_complete(
        exam_id, "relaties", evidence, identity_fields=tuple(evidence.keys())
    )
    unresolved_scores = [
        item["question_number"] for item in result["score_mismatches"]
        if not next((row["note"].strip() for row in cleaned
                     if row["question_number"] == item["question_number"]), "")
    ]
    return {
        "ok": True, **evidence,
        "unresolved_score_mismatches": unresolved_scores,
        "complete": not result["missing_cv"] and not result["extra_cv"] and not result["missing_answers"] and not result["extra_answers"] and not unresolved_scores,
    }




@app.post("/api/exams/{exam_id}/skip-optional-workbook")
def skip_optional_workbook(exam_id: str):
    """Rond de twee uitwerkbijlagestappen af wanneer dit examen geen bijlage heeft."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    has_uitwerk = any(
        exam["metadata"].get("document_types", {}).get(doc["filename"]) == "uitwerkbijlage" or
        doc.get("metadata", {}).get("document_type") == "uitwerkbijlage"
        for doc in exam["documents"]
    )
    if has_uitwerk:
        raise HTTPException(409, "Er is wel een uitwerkbijlage toegewezen; verwerk die normaal.")
    if not exam["confirmed"]:
        raise HTTPException(409, "Bevestig eerst de documenteigenschappen.")
    completed = [key for key, value in exam["steps"].items() if value["status"] == "complete"]
    missing = unmet_requirements("uitwerk_starts", completed)
    if missing:
        raise HTTPException(409, {"message":"Eerdere stappen zijn nog niet afgerond.","missing":missing})
    changed_keys = []
    if STORE.complete_step(
        exam_id, "uitwerk_starts",
        {"not_applicable": True, "reviewed": True},
    ):
        changed_keys.append("uitwerk_starts")
    if STORE.complete_step(
        exam_id, "uitwerk_fragments",
        {"not_applicable": True, "reviewed": True},
    ):
        changed_keys.append("uitwerk_fragments")
    if changed_keys:
        dependents = {
            dependent
            for key in changed_keys
            for dependent in invalidate_dependents(key)
        }
        STORE.invalidate_steps(
            exam_id,
            [step.key for step in WORKFLOW if step.key in dependents],
        )
    return {"ok": True, "not_applicable": True}


@app.get("/api/exams/{exam_id}/snippets")
def get_snippets(exam_id: str):
    """Maak de definitieve snippetset en contextvoorstellen voor eindcontrole."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    starts = exam["steps"].get("opgaven_starts", {}).get("evidence", {}).get("candidates", [])
    accepted = [item for item in starts if item.get("accepted") and not item.get("removed")]
    opgaven_doc = _document_for_type(exam, "opgaven")
    source = DATA / opgaven_doc["relative_path"]
    if STORE.sha256(source) != opgaven_doc["sha256"]:
        raise HTTPException(409, "Het opgavendocument is gewijzigd sinds import.")
    output = DATA / "exams" / exam_id / "derived" / "contexts"
    contexts = generate_context_candidates(source, accepted, output)
    # Als de docent contexten op de lange examenstrook heeft geselecteerd,
    # vervangt die selectie de tekstgebaseerde contextvoorstellen. De context-
    # en vraagfragmenten komen dan aantoonbaar uit hetzelfde coördinatenstelsel.
    fragment_evidence = exam["steps"].get("opgaven_fragments", {}).get("evidence", {})
    selected_contexts = fragment_evidence.get("stitched_selections", [])
    selected_contexts = [item for item in selected_contexts if item.get("type") == "context"]
    if selected_contexts:
        stitched_path = DATA / "exams" / exam_id / "derived" / "opgaven_stitched" / "exam-long.png"
        stitched_metadata = _load_or_build_stitched_exam(
            source, stitched_path, opgaven_doc["sha256"]
        )
        if not _stitched_selection_matches_image(fragment_evidence, stitched_path):
            raise HTTPException(
                409,
                "De opgeslagen fragmentgrenzen horen bij een oudere versie van de lange examenafbeelding. "
                "Heropen stap 3 (Vraagfragmenten opgaven), controleer de grenzen opnieuw en sla ze op. "
                "Het examen hoeft niet opnieuw geïmporteerd te worden."
            )
        selected_output = DATA / "exams" / exam_id / "derived" / "contexts"
        selected_output.mkdir(parents=True, exist_ok=True)
        selected_items = []
        with Image.open(stitched_path) as stitched_image:
            for index, selection in enumerate(selected_contexts, 1):
                top = max(0, min(stitched_image.height, int(selection["top"])))
                bottom = max(top + 1, min(stitched_image.height, int(selection["bottom"])))
                crop = stitched_image.crop((0, top, stitched_image.width, bottom))
                filename = f"selected-context-{index:02d}.png"
                crop.save(selected_output / filename, format="PNG", optimize=True)
                crop.close()
                numbers = sorted(set(
                    int(n) for n in selection.get("question_numbers", [])
                    if isinstance(n, int) and 1 <= n <= 60
                ))
                if not numbers:
                    raise HTTPException(
                        422,
                        f"Contextfragment '{selection.get('label') or selection.get('id')}' "
                        "heeft geen geldige vraagkoppeling. Herstel de koppeling in stap 3."
                    )
                source_page = next((page["page_number"] for page in stitched_metadata["pages"]
                                    if page["top"] <= top <= page["bottom"]), 0)
                selected_items.append({
                    "id": selection.get("id", f"selected-context-{index}"),
                    "page_number": source_page, "from_question": min(numbers), "to_question": max(numbers),
                    "suggested_from_question": min(numbers), "label": selection.get("label") or "Handmatig geselecteerde context",
                    "url": f"/api/context-images/{exam_id}/{filename}", "text": "", "reviewed": False,
                })
        contexts = {"context_count": len(selected_items), "contexts": selected_items}
    previous = exam["steps"].get("snippets", {}).get("evidence", {})
    # Pas correcties uit eerdere contextreviews alleen toe op nieuwe,
    # tekstgebaseerde voorstellen. Handmatig op de stitch geselecteerde
    # contexten en eerder opgeslagen docentbeslissingen blijven onaangeroerd.
    if not selected_contexts:
        context_learning = build_context_learning_profile(STORE.list_fragment_feedback())
        contexts["contexts"] = apply_context_range_learning(
            contexts["contexts"], context_learning,
            {int(item["question_number"]) for item in accepted},
        )
    saved = {item["id"]: item for item in previous.get("contexts", [])}
    for context in contexts["contexts"]:
        if context["id"] in saved:
            context.update({k: saved[context["id"]][k] for k in ("from_question", "to_question", "reviewed") if k in saved[context["id"]]})
    opgaven = _load_document_fragments(exam_id, "opgaven")
    reviewed_questions = set(previous.get("reviewed_question_numbers", []))
    for question in opgaven["questions"]:
        question["reviewed"] = question["question_number"] in reviewed_questions
    has_uitwerk = any(exam["metadata"].get("document_types", {}).get(doc["filename"]) == "uitwerkbijlage"
                      for doc in exam["documents"])
    uitwerk = (_load_document_fragments(exam_id, "uitwerkbijlage") if has_uitwerk
               else {"question_count": 0, "questions": [], "document": None})
    cv = _load_document_fragments(exam_id, "correctievoorschrift")
    reviewed_uitwerk = set(previous.get("reviewed_uitwerk_numbers", []))
    reviewed_cv = set(previous.get("reviewed_cv_numbers", []))
    for question in uitwerk["questions"]:
        question["reviewed"] = question["question_number"] in reviewed_uitwerk
    for question in cv["questions"]:
        question["reviewed"] = question["question_number"] in reviewed_cv
    return {"contexts": contexts["contexts"], "context_count": contexts["context_count"],
            "opgaven": opgaven, "uitwerkbijlage": uitwerk, "correctievoorschrift": cv,
            "question_count": opgaven["question_count"]}


@app.post("/api/exams/{exam_id}/snippets/review")
def save_snippets_review(exam_id: str, payload: dict):
    """Bewaar contextbereiken en de visuele controle van alle vraagfragmenten."""
    result = get_snippets(exam_id)
    expected_questions = {item["question_number"] for item in result["opgaven"]["questions"]}
    reviewed_questions = payload.get("reviewed_question_numbers")
    if not isinstance(reviewed_questions, list) or any(not isinstance(n, int) for n in reviewed_questions):
        raise HTTPException(422, "De gecontroleerde vraagfragmenten ontbreken.")
    reviewed_set = set(reviewed_questions)
    if len(reviewed_set) != len(reviewed_questions):
        raise HTTPException(422, "Een vraagfragment is dubbel aangevinkt.")
    if not reviewed_set.issubset(expected_questions):
        raise HTTPException(422, "Een gecontroleerd vraagnummer hoort niet bij dit examen.")
    expected_uitwerk = {item["question_number"] for item in result["uitwerkbijlage"]["questions"]}
    expected_cv = {item["question_number"] for item in result["correctievoorschrift"]["questions"]}
    reviewed_uitwerk = payload.get("reviewed_uitwerk_numbers", [])
    reviewed_cv = payload.get("reviewed_cv_numbers", [])
    if (not isinstance(reviewed_uitwerk, list) or any(not isinstance(n, int) for n in reviewed_uitwerk) or
            len(set(reviewed_uitwerk)) != len(reviewed_uitwerk) or
            not set(reviewed_uitwerk).issubset(expected_uitwerk)):
        raise HTTPException(422, "De gecontroleerde uitwerkbijlagefragmenten zijn ongeldig.")
    if (not isinstance(reviewed_cv, list) or any(not isinstance(n, int) for n in reviewed_cv) or
            len(set(reviewed_cv)) != len(reviewed_cv) or
            not set(reviewed_cv).issubset(expected_cv)):
        raise HTTPException(422, "De gecontroleerde CV-fragmenten zijn ongeldig.")
    # Handmatige opslag zonder contexten vereist expliciete bevestiging.
    # Alleen de automatische conceptopslag mag deze keuze nog open laten.
    if (not result["contexts"] and not payload.get("confirmed_no_contexts")
            and not payload.get("draft")):
        raise HTTPException(422, "Er zijn geen contextvoorstellen. Bevestig na visuele controle dat er geen afzonderlijke contexten gekoppeld hoeven te worden.")
    try:
        context_review = validate_context_review(
            {"contexts": payload.get("contexts", [])},
            {item["id"] for item in result["contexts"]}, expected_questions)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    evidence = {**context_review,
                "confirmed_no_contexts": bool(payload.get("confirmed_no_contexts")),
                "reviewed_question_numbers": sorted(reviewed_set),
                "expected_question_numbers": sorted(expected_questions),
                "reviewed_all_questions": reviewed_set == expected_questions,
                "reviewed_uitwerk_numbers": sorted(set(reviewed_uitwerk)),
                "expected_uitwerk_numbers": sorted(expected_uitwerk),
                "reviewed_all_uitwerk": set(reviewed_uitwerk) == expected_uitwerk,
                "reviewed_cv_numbers": sorted(set(reviewed_cv)),
                "expected_cv_numbers": sorted(expected_cv),
                "reviewed_all_cv": set(reviewed_cv) == expected_cv,
                "document_sha256": result["opgaven"]["document"]["sha256"]}
    # De snippetset kan groot zijn en wordt automatisch opgeslagen. Een
    # identieke late request mag de afgeronde stap niet opnieuw openen.
    STORE.save_step_draft_preserving_identical_complete(
        exam_id, "snippets", evidence, identity_fields=tuple(evidence.keys())
    )
    # Leg een leervoorbeeld vast wanneer alle fragmenttypen expliciet zijn
    # gecontroleerd. De automatische voorstellen en de geaccepteerde review
    # blijven naast elkaar bewaard, zodat latere regelverbeteringen toetsbaar zijn.
    if (not payload.get("draft") and evidence["reviewed_all_questions"]
            and evidence["reviewed_all_contexts"] and evidence["reviewed_all_uitwerk"]
            and evidence["reviewed_all_cv"]):
        automatic = {
            "context_candidates": result["contexts"],
            "question_fragment_candidates": result["opgaven"]["questions"],
            "worksheet_candidates": result["uitwerkbijlage"]["questions"],
            "cv_candidates": result["correctievoorschrift"]["questions"],
        }
        accepted = {
            "reviewed_context_ranges": evidence["contexts"],
            "reviewed_question_numbers": evidence["reviewed_question_numbers"],
            "reviewed_worksheet_numbers": evidence["reviewed_uitwerk_numbers"],
            "reviewed_cv_numbers": evidence["reviewed_cv_numbers"],
        }
        summary = {
            "context_range_changes": [
                {"id": item["id"], "suggested_from": next((candidate.get("from_question")
                    for candidate in result["contexts"] if candidate["id"] == item["id"]), None),
                 "suggested_to": next((candidate.get("to_question")
                    for candidate in result["contexts"] if candidate["id"] == item["id"]), None),
                 "accepted_from": item["from_question"], "accepted_to": item["to_question"]}
                for item in evidence["contexts"]],
            "manual_review_confirmed": True,
        }
        STORE.record_fragment_feedback(exam_id, "fragment_review", evidence["document_sha256"],
                                      automatic, accepted, summary)
    return {"ok": True, **evidence,
            "complete": (evidence["reviewed_all_questions"] and evidence["reviewed_all_contexts"]
                         and evidence["reviewed_all_uitwerk"] and evidence["reviewed_all_cv"]
                         and (bool(result["contexts"]) or evidence["confirmed_no_contexts"]))}




@app.get("/api/exams/{exam_id}/learning-profile")
def get_learning_profile(exam_id: str):
    """Toon transparant wat de detectie uit eerdere reviews heeft geleerd."""
    if not STORE.get_exam(exam_id):
        raise HTTPException(404, "Examen niet gevonden.")
    examples = []
    for record in STORE.list_fragment_feedback():
        if not record["stage"].startswith("question_starts:"):
            continue
        examples.extend(record["accepted"].get("examples", []))
    profile = build_learning_profile(examples)
    all_feedback = STORE.list_fragment_feedback()
    boundary_profile = build_boundary_learning_profile(all_feedback)
    context_profile = build_context_learning_profile(all_feedback)
    return {
        **profile,
        "fragment_boundaries": boundary_profile,
        "context_groups": context_profile,
        "learning_policy": {
            "automatic_approval": False,
            "minimum_examples_per_feature": profile["minimum_examples"],
            "description": (
                "Feedback beïnvloedt alleen de rangschikking van detectievoorstellen. "
                "Er worden geen vraagstarts automatisch goedgekeurd en bestaande "
                "docentbeslissingen worden nooit overschreven."
            ),
        },
    }


@app.get("/api/exams/{exam_id}/fragment-learning-status")
def fragment_learning_status(exam_id: str):
    """Expose counts of approved examples, not raw learner data."""
    if not STORE.get_exam(exam_id):
        raise HTTPException(404, "Examen niet gevonden.")
    records = STORE.list_fragment_feedback()
    question_examples = sum(
        len(record["accepted"].get("examples", []))
        for record in records if record["stage"].startswith("question_starts:")
    )
    boundary_examples = sum(
        len(record["accepted"].get("examples", []))
        for record in records if record["stage"].startswith("fragment_boundaries:")
    )
    context_examples = sum(
        len(record["summary"].get("context_range_changes", []))
        for record in records if record["stage"] == "fragment_review"
    )
    return {
        "examples": question_examples + boundary_examples + context_examples,
        "question_start_examples": question_examples,
        "fragment_boundary_examples": boundary_examples,
        "context_group_examples": context_examples,
        "learning_active": bool(question_examples or boundary_examples or context_examples),
        "automatic_approval": False,
        "message": (
            "Gecontroleerde correcties worden gebruikt om nieuwe detectievoorstellen "
            "te verbeteren. Een detectie wordt nooit automatisch goedgekeurd."
        ),
    }

@app.get("/api/exams/{exam_id}/final-review")
def get_final_review(exam_id: str):
    """Toon per vraag de volledige set gekoppelde bronnen en controlepunten."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    snippets = get_snippets(exam_id)
    analysis = exam["steps"].get("opgaven_analyse", {}).get("evidence", {}).get("questions", [])
    answers = exam["steps"].get("antwoorden", {}).get("evidence", {}).get("questions", [])
    relations = exam["steps"].get("relaties", {}).get("evidence", {}).get("questions", [])
    previous = exam["steps"].get("eindcontrole", {}).get("evidence", {}).get("questions", [])
    analysis_by = {item["question_number"]: item for item in analysis}
    answers_by = {item["question_number"]: item for item in answers}
    relations_by = {item["question_number"]: item for item in relations}
    previous_by = {item["question_number"]: item for item in previous}
    questions = []
    for question in snippets["opgaven"]["questions"]:
        number = question["question_number"]
        answer = answers_by.get(number, {})
        relation = relations_by.get(number, {})
        points = analysis_by.get(number, {}).get("max_points")
        cv_points = answer.get("cv_max_points")
        questions.append({
            "question_number": number,
            "context": [item for item in snippets["contexts"]
                        if item["from_question"] <= number <= item["to_question"]],
            "opgaven": question.get("segments", []),
            "uitwerkbijlage": next((item.get("segments", []) for item in snippets["uitwerkbijlage"]["questions"]
                                    if item["question_number"] == number), []),
            "correctievoorschrift": next((item.get("segments", []) for item in snippets["correctievoorschrift"]["questions"]
                                          if item["question_number"] == number), []),
            "question_type": analysis_by.get(number, {}).get("question_type", "onbekend"),
            "options": analysis_by.get(number, {}).get("options", []),
            "max_points": points, "cv_max_points": cv_points,
            "points_match": (points == cv_points) if points is not None and cv_points is not None else None,
            "answer_kind": answer.get("answer_kind", "handmatig"),
            "answer_text": answer.get("answer_text", ""),
            "supplement_pages": answer.get("supplement_pages", []),
            "relation_note": relation.get("note", ""),
            "reviewed": previous_by.get(number, {}).get("reviewed", False),
            "resolution_note": previous_by.get(number, {}).get("resolution_note", ""),
        })
    return {"question_count": len(questions), "questions": questions}


@app.post("/api/exams/{exam_id}/final-review/review")
def save_final_review(exam_id: str, payload: dict):
    """Bewaar de integrale controle; scoreverschillen vragen een toelichting."""
    # Autosaves from the final-review screen must be cheap. Calling
    # get_final_review() here used to rebuild every context/question/CV image
    # on each POST, making ordinary note edits and navigation unnecessarily
    # slow. Validate against the already-persisted snippet review and the
    # lightweight score evidence instead.
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    snippet_evidence = exam["steps"].get("snippets", {}).get("evidence", {})
    expected_values = snippet_evidence.get("expected_question_numbers")
    if not isinstance(expected_values, list) or not expected_values:
        expected_values = exam["steps"].get("opgaven_fragments", {}).get("evidence", {}).get("expected_question_numbers", [])
    if not isinstance(expected_values, list) or not expected_values:
        previous_review = exam["steps"].get("eindcontrole", {}).get("evidence", {}).get("questions", [])
        expected_values = [item.get("question_number") for item in previous_review if isinstance(item, dict)]
    expected = {number for number in expected_values if isinstance(number, int) and number > 0}
    if not expected:
        raise HTTPException(409, "De vraaglijst voor de integrale eindcontrole ontbreekt. Rond eerst de snippetcontrole af.")

    analysis = exam["steps"].get("opgaven_analyse", {}).get("evidence", {}).get("questions", [])
    answers = exam["steps"].get("antwoorden", {}).get("evidence", {}).get("questions", [])
    analysis_by = {item.get("question_number"): item for item in analysis if isinstance(item, dict)}
    answers_by = {item.get("question_number"): item for item in answers if isinstance(item, dict)}
    mismatched_numbers = set()
    for number in expected:
        points = analysis_by.get(number, {}).get("max_points")
        cv_points = answers_by.get(number, {}).get("cv_max_points")
        if points is not None and cv_points is not None and points != cv_points:
            mismatched_numbers.add(number)

    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise HTTPException(422, "De integrale vraagcontrole ontbreekt.")
    seen = set()
    cleaned = []
    for item in questions:
        number = item.get("question_number") if isinstance(item, dict) else None
        if not isinstance(number, int) or number not in expected or number in seen:
            raise HTTPException(422, "Een vraagnummer in de eindcontrole is ongeldig of dubbel.")
        seen.add(number)
        note = str(item.get("resolution_note", ""))[:2000]
        # Een lege toelichting is alleen toegestaan bij een automatische
        # conceptopslag. Een handmatige opslag of afronding moet de afwijking
        # inhoudelijk toelichten. De afwijking wordt uit de bewaarde score-
        # gegevens afgeleid; er hoeft geen afbeelding opnieuw te worden gebouwd.
        if number in mismatched_numbers and not note.strip() and not payload.get("draft"):
            raise HTTPException(422, f"Leg het verschil tussen de opgave- en CV-score bij vraag {number} vast.")
        cleaned.append({"question_number": number, "reviewed": bool(item.get("reviewed")),
                        "resolution_note": note})
    if seen != expected:
        raise HTTPException(422, "Controleer alle vragen in de integrale eindcontrole.")
    reviewed = sum(item["reviewed"] for item in cleaned)
    evidence = {"questions": cleaned, "reviewed_count": reviewed,
                "reviewed_all_questions": reviewed == len(cleaned)}
    # Voorkom dat een identieke autosave die na het afronden arriveert de
    # eindcontrole weer op 'pending' zet. Gewijzigde vraagnotities of inhoud
    # trekken de goedkeuring nog steeds in.
    STORE.save_step_draft_preserving_identical_complete(
        exam_id, "eindcontrole", evidence, identity_fields=tuple(evidence.keys())
    )
    unresolved = any(
        number in mismatched_numbers and
        not next(item for item in cleaned if item["question_number"] == number)["resolution_note"].strip()
        for number in expected
    )
    return {"ok": True, **evidence,
            "complete": evidence["reviewed_all_questions"] and not unresolved}


@app.get("/api/context-images/{exam_id}/{filename}")
def context_image(exam_id: str, filename: str):
    """Serveer uitsluitend gegenereerde context-PNG's uit de examenwerkmap."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.png", filename):
        raise HTTPException(400, "Ongeldige bestandsnaam.")
    if not re.fullmatch(r"[a-f0-9]{12}", exam_id) or not STORE.get_exam(exam_id):
        raise HTTPException(404, "Examen niet gevonden.")
    path = DATA / "exams" / exam_id / "derived" / "contexts" / filename
    if not path.is_file():
        raise HTTPException(404, "Contextafbeelding niet gevonden.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control":"no-store"})


@app.post("/api/exams/{exam_id}/metadata/draft")
def save_metadata_draft(exam_id: str, payload: dict):
    """Bewaar onvolledige metadata als concept zonder het examen te bevestigen.

    De docent kan de metadata in meerdere sessies invullen. Een leeg of nog
    onvolledig veld is daarom toegestaan; definitieve validatie gebeurt pas
    bij de afzonderlijke bevestigingsactie.
    """
    if not STORE.get_exam(exam_id):
        raise HTTPException(404, "Examen niet gevonden.")
    if not isinstance(payload, dict):
        raise HTTPException(422, "De metadata-invoer heeft een ongeldig formaat.")
    STORE.save_step_draft(exam_id, "metadata_draft", payload)
    return {"ok": True, "saved": True}


@app.post("/api/exams/{exam_id}/metadata/confirm")
def confirm_metadata(exam_id: str, payload: dict):
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    required = ("subject", "level", "year", "period")
    missing = [field for field in required if payload.get(field) in (None, "")]
    if missing:
        raise HTTPException(422, "Vul de verplichte metadata in: " + ", ".join(missing))
    # Documenttypen worden per bestand bevestigd; de app voorkomt dat een
    # suffixherkenning ongemerkt wordt overschreven of vergeten.
    types = payload.get("document_types", {})
    for doc in exam["documents"]:
        if doc["filename"] not in types or not types[doc["filename"]]:
            raise HTTPException(422, f"Bevestig het documenttype van {doc['filename']}.")
    metadata = {**{k: payload[k] for k in required}, "document_types": types}
    metadata_changed = STORE.confirm_metadata(exam_id, metadata)
    # Alleen een daadwerkelijke wijziging maakt de vervolggoedkeuringen
    # ongeldig. Het opnieuw openen en ongewijzigd bevestigen van metadata
    # laat eerder gecontroleerde stappen dus intact.
    if metadata_changed:
        STORE.invalidate_steps(exam_id, invalidate_dependents("metadata"))
    # Het concept is niet meer nodig zodra de definitieve metadata is bevestigd.
    STORE.invalidate_steps(exam_id, ["metadata_draft"])
    return {"ok": True, "metadata": metadata}


@app.post("/api/exams/{exam_id}/steps/{step_key}/complete")
def complete_step(exam_id: str, step_key: str, payload: dict):
    """Sla een stap pas op als alle voorgangers afgerond zijn en bewijs bestaat."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    if step_key not in STEP_BY_KEY:
        raise HTTPException(404, "Onbekende workflowstap.")
    if step_key == "publicatie":
        raise HTTPException(409, "Gebruik de afzonderlijke publicatieactie nadat de eindcontrole is afgerond.")
    completed = [key for key, value in exam["steps"].items() if value["status"] == "complete"]
    missing = unmet_requirements(step_key, completed)
    if step_key == "relaties":
        # Een document dat niet is geïmporteerd, kan geen openstaande
        # verwerkingsstap opleveren. Dit blijft ook gelden voor oudere examens
        # die vóór de automatische 'niet van toepassing'-afhandeling zijn
        # aangemaakt.
        document_types = exam["metadata"].get("document_types", {})
        has_workbook = (
            any(value == "uitwerkbijlage" for value in document_types.values()) or
            any(doc.get("metadata", {}).get("document_type") == "uitwerkbijlage"
                for doc in exam["documents"])
        )
        has_supplement = (
            any(value == "aanvulling_correctievoorschrift" for value in document_types.values()) or
            any(doc.get("metadata", {}).get("document_type") == "aanvulling_correctievoorschrift"
                for doc in exam["documents"])
        )
        if not has_workbook:
            missing = [key for key in missing if key != "uitwerk_fragments"]
        if not has_supplement:
            missing = [key for key in missing if key != "cv_aanvulling"]
    if missing:
        raise HTTPException(409, {"message": "Eerdere stappen zijn nog niet afgerond.", "missing": missing})
    if not payload or not payload.get("reviewed"):
        raise HTTPException(422, "Een stap kan alleen worden afgerond met expliciet controlebewijs.")
    previous = exam["steps"].get(step_key, {}).get("evidence", {})
    if step_key in {"opgaven_starts", "uitwerk_starts", "cv_starts"}:
        if not payload.get("reviewed_all_pages") or not previous.get("candidates"):
            raise HTTPException(422, "Controleer alle pagina's en sla de vraagstarts eerst op.")
        accepted_numbers = [item["question_number"] for item in previous["candidates"]
                            if item.get("accepted") and not item.get("removed")]
        if not accepted_numbers:
            raise HTTPException(422, "Er moet ten minste één vraagstart zijn goedgekeurd.")
        if len(accepted_numbers) != len(set(accepted_numbers)):
            duplicates = sorted(number for number in set(accepted_numbers)
                                if accepted_numbers.count(number) > 1)
            raise HTTPException(422, "Los eerst de dubbele hoofdvraagstarts op: " + str(duplicates))
    # De vraaganalyse wordt als complete set opgeslagen. De docent bevestigt
    # de set met de afrondactie; reviewed=True wordt intern voor alle vragen
    # vastgelegd zodat geen administratieve vinkjes per vraag nodig zijn.
    if step_key == "opgaven_analyse":
        questions = previous.get("questions", [])
        if (not previous.get("reviewed_all_questions") or not questions
                or any(not item.get("reviewed") for item in questions)):
            raise HTTPException(422, "Controleer vraagtype, punten en antwoordopties voor iedere vraag.")
    # De visuele fragmentset wordt als één geheel goedgekeurd. De browser zet
    # de interne reviewed-markeringen bij de expliciete afrondactie; de gebruiker
    # hoeft niet ieder fragment afzonderlijk af te vinken.
    if step_key in {"opgaven_fragments", "uitwerk_fragments", "cv_fragments"}:
        expected = set(previous.get("expected_question_numbers", []))
        reviewed_numbers = set(previous.get("reviewed_question_numbers", []))
        if (not previous.get("reviewed_all_questions") or not expected
                or reviewed_numbers != expected):
            raise HTTPException(422, "Controleer eerst alle vraagfragmenten en sla die controle op.")
    if step_key == "cv_aanvulling":
        # Een ontbrekende aanvulling is een geldige, expliciete uitkomst; een
        # aanwezige aanvulling moet per pagina zijn beoordeeld.
        has_supplement = any(exam["metadata"].get("document_types", {}).get(doc["filename"]) == "aanvulling_correctievoorschrift"
                             for doc in exam["documents"])
        if has_supplement and (not previous.get("reviewed_all_pages") or
                               any(not item.get("reviewed") for item in previous.get("items", []))):
            raise HTTPException(422, "Controleer iedere pagina van de CV-aanvulling.")
        if not has_supplement and not payload.get("not_required"):
            raise HTTPException(422, "Bevestig dat er geen CV-aanvulling bij dit examen hoort.")
    if step_key == "antwoorden":
        questions = previous.get("questions", [])
        if not previous.get("reviewed_all_questions") or not questions:
            raise HTTPException(422, "Sla de complete antwoordset op voordat je doorgaat.")
    if step_key == "relaties":
        questions = previous.get("questions", [])
        if not previous.get("reviewed_all_questions") or not questions:
            raise HTTPException(422, "Voer eerst de automatische document- en vraagkoppelingen uit.")
        if previous.get("missing_cv"):
            raise HTTPException(422, "Er ontbreken correctievoorschriftvragen: " + str(previous["missing_cv"]))
        if previous.get("extra_cv"):
            raise HTTPException(422, "Er zijn CV-vragen zonder overeenkomstige opgave: " + str(previous["extra_cv"]))
        if previous.get("missing_answers"):
            raise HTTPException(422, "Er ontbreken antwoordrecords bij vraag/vraagvragen: " + str(previous["missing_answers"]))
        if previous.get("extra_answers"):
            raise HTTPException(422, "Er zijn antwoordrecords zonder overeenkomstige opgave: " + str(previous["extra_answers"]))
        # Een scoreverschil is geen automatische fout: het kan bijvoorbeeld
        # ontstaan door een gewijzigde beoordelingsregel. Wel moet stap 11
        # vastleggen waarom de twee maximumscores bewust niet gelijk zijn.
        notes_by_number = {
            item["question_number"]: str(item.get("note", "")).strip()
            for item in questions
        }
        mismatches = previous.get("score_mismatches", [])
        unresolved = [
            str(item["question_number"]) for item in mismatches
            if not notes_by_number.get(item["question_number"])
        ]
        if unresolved:
            raise HTTPException(
                422,
                "Licht de afwijkende maximumscore toe bij vraag/vraagvragen: " + ", ".join(unresolved)
            )
    if step_key == "snippets":
        if (not previous.get("reviewed_all_questions") or not previous.get("reviewed_all_contexts")
                or not previous.get("reviewed_all_uitwerk") or not previous.get("reviewed_all_cv")
                or not previous.get("expected_question_numbers")
                or (not previous.get("contexts") and not previous.get("confirmed_no_contexts"))):
            raise HTTPException(422, "Controleer alle vraag- en contextsnippets voordat je doorgaat.")
    if step_key == "eindcontrole":
        questions = previous.get("questions", [])
        if not previous.get("reviewed_all_questions") or not questions or any(not item.get("reviewed") for item in questions):
            raise HTTPException(422, "Controleer alle vragen in de integrale eindcontrole.")
        # Conceptopslag mag een nog ontbrekende toelichting bewaren; definitief
        # afronden mag niet zolang een scoreverschil onverklaard blijft.
        # Gebruik de opgeslagen score-evidence: ook deze laatste knop hoeft
        # geen context-/vraag-/CV-afbeeldingen opnieuw te genereren.
        analysis = exam["steps"].get("opgaven_analyse", {}).get("evidence", {}).get("questions", [])
        answers = exam["steps"].get("antwoorden", {}).get("evidence", {}).get("questions", [])
        analysis_by = {item.get("question_number"): item for item in analysis if isinstance(item, dict)}
        answers_by = {item.get("question_number"): item for item in answers if isinstance(item, dict)}
        mismatched = {
            number for number in analysis_by.keys() & answers_by.keys()
            if analysis_by[number].get("max_points") is not None
            and answers_by[number].get("cv_max_points") is not None
            and analysis_by[number].get("max_points") != answers_by[number].get("cv_max_points")
        }
        unresolved = [item["question_number"] for item in questions
                      if item["question_number"] in mismatched and not item.get("resolution_note", "").strip()]
        if unresolved:
            raise HTTPException(422, "Leg het scoreverschil nog toe bij vraag/vraagvragen: " + ", ".join(map(str, unresolved)))
    # Vergelijk de definitieve review met de goedgekeurde nulmeting die
    # bij het heropenen is opgeslagen. Alleen een echte inhoudelijke wijziging
    # maakt afhankelijke stappen opnieuw controleplichtig.
    # Vraagstartreviews worden pas als leervoorbeeld vastgelegd wanneer de
    # docent de volledige detectiestap expliciet afrondt. Autosaves leveren
    # dus geen dubbele of onvolledige trainingsvoorbeelden op.
    if step_key in {"opgaven_starts", "uitwerk_starts", "cv_starts"}:
        prior_status = exam["steps"].get(step_key, {}).get("status")
        reviewed_evidence = {**previous, **payload}
        if prior_status != "complete" and reviewed_evidence.get("reviewed"):
            document_type = {
                "opgaven_starts": "opgaven",
                "uitwerk_starts": "uitwerkbijlage",
                "cv_starts": "correctievoorschrift",
            }[step_key]
            document = _document_for_type(exam, document_type)
            source_path = DATA / document["relative_path"]
            with fitz.open(source_path) as reviewed_pdf:
                page_sizes = [
                    {"width": page.rect.width, "height": page.rect.height}
                    for page in reviewed_pdf
                ]
            examples = []
            for candidate in reviewed_evidence.get("candidates", []):
                page_index = int(candidate.get("page_index", -1))
                if not 0 <= page_index < len(page_sizes):
                    continue
                examples.append({
                    "accepted": bool(candidate.get("accepted")),
                    "features": question_start_features(candidate, page_sizes[page_index]),
                    "question_number": candidate.get("question_number"),
                    "source": candidate.get("source", "automatic"),
                })
            STORE.record_detection_examples(
                exam_id, f"question_starts:{document_type}",
                document["sha256"], examples,
            )

    # Bewaar ook handmatig gecorrigeerde fragmentgrenzen als numerieke
    # leervoorbeelden. De offset wordt berekend ten opzichte van de
    # oorspronkelijke vraagstart en de volgende vraag/pagina-eindgrens.
    # Alleen een expliciet afgeronde fragmentreview telt mee.
    if step_key in {"opgaven_fragments", "uitwerk_fragments", "cv_fragments"}:
        prior_status = exam["steps"].get(step_key, {}).get("status")
        fragment_evidence = {**previous, **payload}
        overrides = fragment_evidence.get("boundary_overrides", [])
        if prior_status != "complete" and fragment_evidence.get("reviewed_all_questions") and overrides:
            document_type = {
                "opgaven_fragments": "opgaven",
                "uitwerk_fragments": "uitwerkbijlage",
                "cv_fragments": "correctievoorschrift",
            }[step_key]
            document = _document_for_type(exam, document_type)
            starts_key = {
                "opgaven": "opgaven_starts",
                "uitwerkbijlage": "uitwerk_starts",
                "correctievoorschrift": "cv_starts",
            }[document_type]
            starts_evidence = exam["steps"].get(starts_key, {}).get("evidence", {})
            starts = sorted(
                [item for item in starts_evidence.get("candidates", [])
                 if item.get("accepted") and not item.get("removed")],
                key=lambda item: (item["page_index"], item["pdf_bbox"][1]),
            )
            start_by_number = {int(item["question_number"]): item for item in starts}
            source_path = DATA / document["relative_path"]
            with fitz.open(source_path) as boundary_pdf:
                page_heights = [float(page.rect.height) for page in boundary_pdf]
            boundary_examples = []
            for override in overrides:
                start = start_by_number.get(int(override["question_number"]))
                if not start:
                    continue
                start_index = starts.index(start)
                next_start = starts[start_index + 1] if start_index + 1 < len(starts) else None
                last_page = next_start["page_index"] if next_start else len(page_heights) - 1
                default_end = (
                    float(next_start["pdf_bbox"][1])
                    if next_start and next_start["page_index"] == last_page
                    else page_heights[last_page]
                )
                boundary_examples.append({
                    "question_number": int(override["question_number"]),
                    "start_offset": round(float(override["start_y"]) - float(start["pdf_bbox"][1]), 2),
                    "end_offset": round(float(override["end_y"]) - default_end, 2),
                })
            STORE.record_fragment_feedback(
                exam_id, f"fragment_boundaries:{document_type}", document["sha256"],
                {"automatic_boundary_reference": "question_start_and_next_question"},
                {"examples": boundary_examples},
                {"reviewed_boundary_count": len(boundary_examples), "reviewed_by_user": True},
            )

    changed = STORE.complete_step(exam_id, step_key, {**previous, **payload})
    if changed:
        STORE.invalidate_steps(exam_id, invalidate_dependents(step_key))
    return {"ok": True, "step": step_key, "changed": changed}


@app.post("/api/exams/{exam_id}/steps/{step_key}/reopen")
def reopen_step(exam_id: str, step_key: str):
    """Heropen een stap en vergelijk pas na afronding met de oude goedkeuring.

    Dit is de herstelroute wanneer een docent bijvoorbeeld een vraagstart wil
    verplaatsen. De huidige stap wordt een bewerkbaar concept; de bestaande
    vervolggoedkeuringen blijven voorlopig staan. Bij de nieuwe afronding
    vergelijkt de opslag de inhoud met de goedgekeurde nulmeting. Alleen bij
    een echte wijziging worden afhankelijke stappen opnieuw controleplichtig.
    """
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    if step_key not in STEP_BY_KEY:
        raise HTTPException(404, "Onbekende workflowstap.")
    if step_key == "publicatie":
        raise HTTPException(409, "Een gepubliceerde versie kan niet als verwerkingsstap worden heropend.")
    evidence = exam["steps"].get(step_key, {}).get("evidence", {})
    if step_key == "metadata":
        # Metadata heeft daarnaast een bevestigingsvlag op de examenrij.
        # De goedgekeurde metadata wordt als nulmeting bewaard; vervolgstappen
        # blijven geldig totdat de nieuwe metadata werkelijk anders blijkt.
        STORE.reopen_metadata(exam_id, exam.get("metadata", {}))
    else:
        # Bewaar zowel de conceptinvoer als de goedgekeurde nulmeting.
        # Pas bij opnieuw afronden vergelijken we beide versies en invalidëren
        # we uitsluitend de stappen die van een echte wijziging afhangen.
        STORE.reopen_step(exam_id, step_key, evidence)
    return {
        "ok": True,
        "reopened": step_key,
        "invalidated": [],
        "deferred_invalidation": True,
    }


@app.post("/api/exams/{exam_id}/steps/{step_key}/invalidate")
def invalidate_step(exam_id: str, step_key: str):
    """Maak een stap en haar afhankelijkheden expliciet opnieuw controleplichtig.

    In tegenstelling tot de normale heropenroute is dit een directe
    invalidatieactie. Eerder reviewbewijs blijft wel bewaard als concept.
    """
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    if step_key not in STEP_BY_KEY:
        raise HTTPException(404, "Onbekende workflowstap.")
    dependents = invalidate_dependents(step_key)
    STORE.invalidate_steps(exam_id, [step_key, *dependents])
    return {"ok": True, "invalidated": [step_key, *dependents]}



@app.post("/api/exams/{exam_id}/publish")
def publish_exam(exam_id: str):
    """Publiceer alleen wanneer de integrale eindcontrole volledig is afgerond."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    if exam["steps"].get("eindcontrole", {}).get("status") != "complete":
        raise HTTPException(409, "Rond eerst de integrale eindcontrole volledig af.")
    completed = [key for key, value in exam["steps"].items() if value["status"] == "complete"]
    missing = unmet_requirements("publicatie", completed)
    if missing:
        raise HTTPException(409, {"message":"Eerdere stappen zijn nog niet afgerond.","missing":missing})
    STORE.publish_exam(exam_id)
    return {"ok": True, "published": True}




@app.get("/api/exams/{exam_id}/publication-versions")
def get_publication_versions(exam_id: str):
    """Toon de bewaarde publicatieversies als read-only historie."""
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    versions = STORE.publication_versions(exam_id)
    return [{"version": item["version"], "published_at": item["published_at"]}
            for item in versions]


@app.post("/api/exams/{exam_id}/reopen-published")
def reopen_published_exam(exam_id: str):
    """Open een gepubliceerd examen opnieuw als gecontroleerde bewerkingsversie.

    De laatst gepubliceerde snapshot blijft in publication_versions staan.
    De inhoudelijke workflow-evidence wordt behouden, maar snippets, eindcontrole
    en publicatie worden opnieuw gecontroleerd. De docent kan daarna via de
    bestaande werkruimte de gewenste upstream stap opnieuw openen.
    """
    exam = STORE.get_exam(exam_id)
    if not exam:
        raise HTTPException(404, "Examen niet gevonden.")
    if not exam.get("published"):
        raise HTTPException(409, "Dit examen is niet momenteel gepubliceerd.")
    STORE.invalidate_steps(exam_id, ["snippets", "eindcontrole", "publicatie"])
    return {"ok": True, "reopened": True,
            "message": "Examen opnieuw geopend. De eerdere publicatie blijft bewaard."}


@app.get("/api/workflow")
def workflow():
    return [{"key": s.key, "title": s.title, "description": s.description, "requires": list(s.requires)} for s in WORKFLOW]
