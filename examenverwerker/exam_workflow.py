"""Workflow gates for complete, traceable exam-PDF processing.

The workflow is deliberately data-driven and backward compatible: old projects keep
all their source files and confirmed fragment geometry. A stage advances only when
its required evidence is present; automatic proposals never count as human approval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from structure import (
    validate_exam_structure, validate_cv_fragment, missing_question_regions,
)


WORKFLOW_STAGES = (
    "import", "documenttype", "metadata", "vraagstarts", "ontbrekende_vragen", "opgaven_fragmenten",
    "vraaganalyse", "uitwerkbijlage_starts", "uitwerkbijlage_fragmenten",
    "cv_starts", "cv_fragmenten", "aanvulling", "antwoorden",
    "volledigheid", "snippets", "eindcontrole", "export", "voltooid",
)


def restore_import_batch(examens_root, current_folder, data: dict,
                        project_file: str = "project.json"):
    """Safely restore a batch queue from the manifest linked to an exam project."""
    manifest_name = data.get("import_batch_manifest")
    if not manifest_name:
        return None
    root = Path(examens_root).resolve()
    manifest_path = root / Path(str(manifest_name)).name
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema") != "biologie-examenimport-v1":
            return None
        entries = manifest.get("projecten", [])
        if not isinstance(entries, list):
            return None
        paths = []
        for entry in entries:
            if not isinstance(entry, dict):
                return None
            relative_path = entry.get("pad")
            if not isinstance(relative_path, str) or not relative_path:
                return None
            candidate = (root / relative_path).resolve()
            if not candidate.is_relative_to(root):
                return None
            if (candidate / project_file).is_file():
                paths.append(candidate)
        current = Path(current_folder).resolve()
        if current not in paths:
            return None
        return {"paths": paths, "index": paths.index(current),
                "manifest_path": manifest_path}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def exam_export_fingerprint(data: dict) -> str:
    """Hash every reviewed source and derived field on which export depends."""
    keys = (
        "documenten", "exam_metadata", "vraagkandidaten", "exam_structures",
        "exam_structure", "cv_regions", "cv_amendment_regions",
        "uitwerkbijlage_regions", "vraagrecords", "answer_reviews",
        "consolidated_cv", "completeness_review", "final_visual_review",
    )
    payload = {key: data.get(key) for key in keys}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def exam_review_fingerprint(data: dict, include_snippets: bool = False) -> str:
    """Fingerprint reviewed content while excluding approval and review metadata."""
    keys=("documenten","exam_metadata","vraagkandidaten","exam_structures",
          "exam_structure","cv_regions","uitwerkbijlage_regions","consolidated_cv")
    records=[]
    for source in data.get("vraagrecords",[]) or []:
        record=dict(source)
        for key in ("approved_by_human","status","approved_at","approval_method",
                    "record_review_checklist","approval_revoked_reason"):
            record.pop(key,None)
        if not include_snippets:
            for key in ("snippet_file","snippet_files","question_region_snippet_file",
                        "question_region_snippet_sha256","cv_snippet_file","cv_snippet_files",
                        "cv_source_region_file","cv_source_region_sha256",
                        "cv_amendment_snippet_file","cv_amendment_snippet_files",
                        "context_region_snippet_files"):
                record.pop(key,None)
            if isinstance(record.get("context_asset_files"),list):
                record["context_asset_files"]=[
                    asset for asset in record["context_asset_files"]
                    if not (asset.get("type")=="context" and
                            asset.get("caption")=="Handmatig afgebakend contextfragment")]
        records.append(record)
    payload={key:data.get(key) for key in keys}
    payload["vraagrecords"]=records
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,
                       separators=(",",":"),default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _result(stage, label, action, **details):
    return {"stage": stage, "label": label, "action": action, **details}


def _documents(data, role):
    return [d for d in (data.get("documenten") or [])
            if d.get("type_voorstel") == role]


def _document_type_confirmed(doc):
    return bool(doc.get("documenttype_handmatig") == doc.get("type_voorstel")
                and doc.get("status") == "handmatig_bevestigd")


def _metadata_confirmed(data):
    meta = data.get("exam_metadata") or {}
    return (meta.get("source") == "handmatig_bevestigd"
            and meta.get("level") in ("Havo", "Vwo")
            and str(meta.get("year", "")).isdigit()
            and meta.get("period") in ("1", "2", "3"))


def _confirmed_candidates(data, document_id):
    return [r for r in (data.get("vraagkandidaten") or [])
            if r.get("document_id") == document_id and r.get("human_decision") is True]


def _candidate_review_complete(data, document):
    rows = [r for r in (data.get("vraagkandidaten") or [])
            if r.get("document_id") == document.get("id")]
    return bool(rows) and all(r.get("human_decision") in (True, False) for r in rows)


def _structure_for(data, doc):
    structures = data.get("exam_structures") or {}
    structure = structures.get(doc.get("id"))
    legacy = data.get("exam_structure") or {}
    if structure is None and legacy.get("document_id") == doc.get("id"):
        structure = legacy
    return structure


def _records_for(data, document_id):
    return [r for r in (data.get("vraagrecords") or [])
            if r.get("candidate_document_id") == document_id]


def _record_for(records, candidate):
    for record in records:
        try:
            if (int(record.get("number")) == int(candidate.get("number"))
                    and int(record.get("source_page")) == int(candidate.get("page"))):
                return record
        except (TypeError, ValueError):
            continue
    return None


def _cv_region_ready(region, doc, number, role):
    if not region:
        return False
    try:
        return not validate_cv_fragment(region, doc, number, role)
    except (KeyError, TypeError, ValueError):
        return False


def _has_file(record, *keys):
    return any(bool(record.get(key)) for key in keys)


def _completeness_issues(data):
    """Structural checks only; no guessed biological or content judgements."""
    issues = []
    docs = data.get("documenten") or []
    opgaven = _documents(data, "opgaven")
    for doc in opgaven:
        candidates = [r for r in (data.get("vraagkandidaten") or [])
                      if r.get("document_id") == doc.get("id")
                      and r.get("human_decision") is True]
        numbers = [int(r["number"]) for r in candidates if r.get("number") is not None]
        duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
        if duplicates:
            issues.append({"code": "dubbele_vraagnummering", "document_id": doc.get("id"),
                           "numbers": duplicates})
        if numbers:
            gaps=sorted(set(range(min(numbers),max(numbers)+1))-set(numbers))
            if gaps:
                issues.append({"code":"vraagnummer_ontbreekt","document_id":doc.get("id"),
                               "numbers":gaps})
        structure = _structure_for(data, doc)
        if structure:
            missing = missing_question_regions(structure, numbers)
            if missing:
                issues.append({"code": "vraagfragment_ontbreekt",
                               "document_id": doc.get("id"), "numbers": missing})
        elif numbers:
            issues.append({"code": "structuur_ontbreekt", "document_id": doc.get("id")})
    records = data.get("vraagrecords") or []
    for record in records:
        if record.get("source_analysis_invalidated") or record.get("exam_structure_invalidated"):
            issues.append({"code": "verouderde_vraagbron", "record_id": record.get("id")})
        if record.get("cv_region_invalidated"):
            issues.append({"code": "verouderde_cv_regio", "record_id": record.get("id")})
    return issues


def exam_completeness_issues(data: dict) -> list[dict]:
    """Public read-only structural completeness report for the review UI."""
    issues = list(_completeness_issues(data))
    records = data.get("vraagrecords") or []
    for record in records:
        points = (record.get("exam") or {}).get("points")
        if points in (None, ""):
            issues.append({"code": "puntenaantal_ontbreekt",
                           "record_id": record.get("id"), "question_number": record.get("number")})
    for doc in _documents(data, "opgaven"):
        structure = _structure_for(data, doc)
        if not structure:
            continue
        valid_numbers = {int(r["number"]) for r in _confirmed_candidates(data, doc.get("id"))
                         if r.get("number") is not None}
        for fragment in structure.get("fragments", []):
            if fragment.get("type") == "context":
                links = {int(n) for n in fragment.get("question_numbers", [])}
                if not links or not links.issubset(valid_numbers):
                    issues.append({"code": "los_contextfragment",
                                   "document_id": doc.get("id"), "fragment_id": fragment.get("id")})
    return issues


def exam_workflow_state(data: dict) -> dict:

    """Return the next uncompleted processing stage and its evidence requirements."""
    documents = data.get("documenten") or []
    if not documents:
        return _result("import", "Documenten toevoegen", "Importeer de examen-PDF's.")

    unconfirmed_types = [d for d in documents if d.get("type_voorstel") in
                         ("opgaven", "correctievoorschrift", "uitwerkbijlage", "aanvulling", "onbekend")
                         and not _document_type_confirmed(d)]
    if unconfirmed_types:
        return _result("documenttype",
                       f"Documenttypen bevestigen ({len(unconfirmed_types)} open)",
                       "Bevestig per PDF het documenttype en de examenidentiteit.",
                       document_ids=[d.get("id") for d in unconfirmed_types])

    opgaven_docs = _documents(data, "opgaven")
    if not opgaven_docs:
        return _result("documenttype", "Opgaven-PDF aanwijzen",
                       "Wijs het juiste document aan als opgaven-PDF.")
    if not _metadata_confirmed(data):
        return _result("metadata", "Examengegevens bevestigen",
                       "Controleer niveau, jaar en tijdvak aan de hand van de eerste pagina.")

    for doc in opgaven_docs:
        if not _candidate_review_complete(data, doc):
            rows = [r for r in (data.get("vraagkandidaten") or [])
                    if r.get("document_id") == doc.get("id")]
            if not rows:
                return _result("vraagstarts", "Vraagstarts analyseren",
                               "Detecteer de vraagstarts in de opgaven-PDF.",
                               document_id=doc.get("id"))
            open_count = sum(r.get("human_decision") not in (True, False) for r in rows)
            return _result("vraagstarts", f"Vraagstarts beoordelen ({open_count} open)",
                           "Beoordeel alle gevonden vraagstarts en voeg ontbrekende vraagstarts toe.",
                           document_id=doc.get("id"), open_candidates=open_count)

    for doc in opgaven_docs:
        confirmed_rows = _confirmed_candidates(data, doc.get("id"))
        if not confirmed_rows:
            return _result("ontbrekende_vragen", "Ontbrekende vraagstarts toevoegen",
                           "Er zijn geen vraagstarts bevestigd. Markeer de echte vraagstarts handmatig op de originele PDF.",
                           document_id=doc.get("id"))
        numbers = sorted({int(r["number"]) for r in confirmed_rows
                          if r.get("number") is not None})
        structure = _structure_for(data, doc)
        errors = (validate_exam_structure(structure, doc.get("id"), doc.get("sha256"), numbers)
                  if structure else ["structuur_ontbreekt"])
        if errors:
            return _result("opgaven_fragmenten", "Context- en vraagfragmenten controleren",
                           "Baken alle context- en vraagfragmenten af en controleer de koppelingen.",
                           document_id=doc.get("id"), errors=errors)

    # Create/reuse a lightweight record from each confirmed, manually delimited
    # question fragment. The record editor is the human review surface for type,
    # points, wording and options; no second fragment-confirmation round is added.
    records = data.get("vraagrecords") or []
    all_candidates = [(doc, row) for doc in opgaven_docs
                      for row in _confirmed_candidates(data, doc.get("id"))]
    for doc, candidate in all_candidates:
        record = _record_for(_records_for(data, doc.get("id")), candidate)
        if record is None:
            return _result("vraaganalyse", "Vraaggegevens samenstellen",
                           "Maak de conceptvraag automatisch vanuit de bevestigde fragmentgrenzen.",
                           document_id=doc.get("id"), question_number=candidate.get("number"))
        if record.get("question_type_status") != "handmatig_gecontroleerd":
            return _result("vraaganalyse", "Vraagtype, punten en opties controleren",
                           "Controleer in het vraagrecord het vraagtype, puntenaantal, vraagtekst en eventuele antwoordopties.",
                           document_id=doc.get("id"), question_number=candidate.get("number"),
                           record_id=record.get("id"))

    appendix_docs = _documents(data, "uitwerkbijlage")
    for doc in appendix_docs:
        if (doc.get("vraagstarts_detectie") or {}).get("status") != "visueel_bevestigd":
            return _result("uitwerkbijlage_starts", "Vraagstarts uitwerkbijlage controleren",
                           "Detecteer en beoordeel de vraagankers in de uitwerkbijlage; bevestig expliciet wanneer er geen aparte ankers zijn.",
                           document_id=doc.get("id"))
    for doc in appendix_docs:
        detection=doc.get("vraagstarts_detectie") or {}
        if detection.get("review_note","").startswith("Geen afzonderlijke vraagstarts"):
            continue
        reviewed_starts=_confirmed_candidates(data,doc.get("id"))
        expected_numbers=sorted({int(row["number"]) for row in reviewed_starts
                                 if row.get("number") is not None})
        if not expected_numbers:
            expected_numbers=sorted({int(row["number"]) for _source,row in all_candidates
                                     if row.get("number") is not None})
        regions = (data.get("uitwerkbijlage_regions") or {}).get(doc.get("id"), {})
        missing = [n for n in expected_numbers if str(n) not in regions
                   or not regions[str(n)].get("page_spans")]
        if missing:
            return _result("uitwerkbijlage_fragmenten", "Uitwerkbijlagefragmenten controleren",
                           "Baken per vraag de bijbehorende uitwerkbijlage af en controleer de koppeling.",
                           document_id=doc.get("id"), question_numbers=missing)

    cv_docs = _documents(data, "correctievoorschrift")
    if not cv_docs:
        return _result("cv_starts", "Correctievoorschrift toevoegen",
                       "Voeg het officiële correctievoorschrift toe en bevestig het documenttype.")
    cv_regions = data.get("cv_regions") or {}
    for doc in cv_docs:
        if (doc.get("vraagstarts_detectie") or {}).get("status") != "visueel_bevestigd":
            return _result("cv_starts", "Vraagstarts correctievoorschrift controleren",
                           "Detecteer en beoordeel de vraagankers in het correctievoorschrift; bevestig expliciet wanneer er geen aparte ankers zijn.",
                           document_id=doc.get("id"))
    for doc in cv_docs:
        for _source_doc, candidate in all_candidates:
            number = int(candidate["number"])
            if not _cv_region_ready(cv_regions.get(doc.get("id"), {}).get(str(number)),
                                    doc, number, "correctievoorschrift"):
                return _result("cv_fragmenten", "CV-fragmenten controleren",
                               "Baken per vraag het volledige correctievoorschrift af.",
                               document_id=doc.get("id"), question_number=number)

    addenda = _documents(data, "aanvulling")
    if addenda:
        allowed_changes = {"toevoeging", "wijziging", "vervanging", "intrekking", "ongewijzigd"}
        for record in records:
            change = record.get("cv_amendment_change_type")
            if change not in allowed_changes:
                return _result("aanvulling", "Wijziging per vraag classificeren",
                               "Classificeer per vraag of de aanvulling een toevoeging, wijziging, vervanging, intrekking of geen wijziging bevat.",
                               record_id=record.get("id"), question_number=record.get("number"))
            if change == "ongewijzigd":
                continue
            number = int(record.get("number"))
            for doc in addenda:
                if not _cv_region_ready(cv_regions.get(doc.get("id"), {}).get(str(number)),
                                        doc, number, "aanvulling"):
                    return _result("aanvulling", "Aanvulling CV-fragmenten afbakenen",
                                   "Baken voor deze gewijzigde vraag het volledige fragment uit iedere toepasselijke CV-aanvulling af.",
                                   document_id=doc.get("id"), question_number=number)
        consolidated = data.get("consolidated_cv") or {}
        if consolidated.get("status") != "visueel_bevestigd":
            return _result("aanvulling", "Geconsolideerd correctievoorschrift controleren",
                           "Bekijk de samengevoegde CV-weergave met herleidbare verwijzingen naar beide bron-PDF's en bevestig deze.")

    # Correct answers must be reviewed, including non-MCQ binary/comparative forms.
    for record in records:
        answer = record.get("answer_review") or {}
        if answer.get("status") != "visueel_bevestigd":
            return _result("antwoorden", "Correcte antwoorden controleren",
                           "Controleer de voorgestelde antwoorden in het officiële CV.",
                           record_id=record.get("id"), question_number=record.get("number"))

    issues = _completeness_issues(data)
    if issues:
        return _result("volledigheid", f"Volledigheidscontrole ({len(issues)} aandachtspunten)",
                       "Los ontbrekende nummers, fragmenten, koppelingen of verouderde bronregio's op.",
                       issues=issues)
    completeness_review=data.get("completeness_review") or {}
    if (completeness_review.get("status") != "visueel_bevestigd" or
            completeness_review.get("fingerprint") != exam_review_fingerprint(data,False)):
        return _result("volledigheid", "Volledigheid bevestigen",
                       "Bevestig dat alle vragen, bronnen, punten en fragmentkoppelingen compleet zijn.")

    for record in records:
        if not _has_file(record, "question_region_snippet_file", "snippet_file",
                         "question_region_snippet_sha256"):
            return _result("snippets", "Vraagfragmenten uitsnijden",
                           "Genereer de definitieve uitsneden vanuit de bevestigde fragmentgrenzen.",
                           record_id=record.get("id"), question_number=record.get("number"))
    final_review=data.get("final_visual_review") or {}
    if (final_review.get("status") != "visueel_bevestigd" or
            final_review.get("fingerprint") != exam_review_fingerprint(data,True) or
            any(record.get("approved_by_human") is not True for record in records)):
        return _result("eindcontrole", "Visuele eindcontrole per vraag",
                       "Controleer per vraag de context, vraag, opties, bijlage en geconsolideerde CV.")

    fingerprint = exam_export_fingerprint(data)
    export_status = data.get("export_status") or {}
    if export_status.get("fingerprint") == fingerprint:
        return _result("voltooid", "Exportpakket gecontroleerd",
                       "Het gecontroleerde exportpakket is aangemaakt; er is niets gepubliceerd.")
    return _result("export", "Exportpakket maken",
                   "Maak het gecontroleerde exportpakket.")
