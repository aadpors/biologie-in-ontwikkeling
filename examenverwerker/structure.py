"""Manual, page-wide exam structure segmentation. Coordinates are normalized and source PDFs stay untouched."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

STRUCTURE_SCHEMA = "biologie-examenstructuur-v1"
FRAGMENT_TYPES = {"context_intro", "vraagcontext", "vraag", "tussenliggende_context"}


def normalize_boundary(value: Any) -> float:
    """Validate and clamp a page-relative vertical coordinate to [0, 1]."""
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError("Een paginagrens moet tussen 0 en 1 liggen.")
    return round(number, 6)


def make_page_span(page: int, top: Any, bottom: Any) -> dict:
    page_no = int(page)
    if page_no < 1:
        raise ValueError("Paginanummers beginnen bij 1.")
    y0, y1 = normalize_boundary(top), normalize_boundary(bottom)
    if y1 - y0 < 0.005:
        raise ValueError("Het geselecteerde fragment is te klein; vergroot de afstand tussen de lijnen.")
    return {"page": page_no, "top": y0, "bottom": y1}


def default_question_links(fragment_type: str, confirmed_question_numbers: list[int]) -> list[int]:
    if fragment_type not in FRAGMENT_TYPES:
        raise ValueError("Onbekend fragmenttype.")
    numbers = sorted({int(n) for n in confirmed_question_numbers})
    return numbers if fragment_type == "context_intro" else []


def make_fragment(fragment_type: str, page_span: dict, question_numbers: list[int],
                  confirmed_question_numbers: list[int], fragment_id: str) -> dict:
    if fragment_type not in FRAGMENT_TYPES:
        raise ValueError("Onbekend fragmenttype.")
    confirmed = sorted({int(n) for n in confirmed_question_numbers})
    links = sorted({int(n) for n in question_numbers})
    if any(n not in confirmed for n in links):
        raise ValueError("Een fragment mag alleen aan bevestigde vraagstarts worden gekoppeld.")
    if fragment_type == "context_intro" and not links:
        links = default_question_links(fragment_type, confirmed)
    if fragment_type == "vraag" and len(links) != 1:
        raise ValueError("Een vraagfragment moet aan precies één bevestigd vraagnummer gekoppeld zijn.")
    return {
        "id": str(fragment_id),
        "type": fragment_type,
        "page_spans": [make_page_span(page_span["page"], page_span["top"], page_span["bottom"])],
        "question_numbers": links,
        "status": "handmatig_afgebakend_nog_te_bevestigen",
    }


def append_page_span(fragment: dict, page_span: dict) -> dict:
    updated = deepcopy(fragment)
    span = make_page_span(page_span["page"], page_span["top"], page_span["bottom"])
    if any(int(item["page"]) == span["page"] for item in updated.get("page_spans", [])):
        raise ValueError("Deze pagina is al onderdeel van het fragment.")
    if updated.get("page_spans") and span["page"] <= max(int(x["page"]) for x in updated["page_spans"]):
        raise ValueError("Voeg pagina's in oplopende volgorde toe.")
    updated.setdefault("page_spans", []).append(span)
    return updated


def validate_exam_structure(structure: dict, document_id: str, source_sha256: str,
                            confirmed_question_numbers: list[int]) -> list[str]:
    errors = []
    if structure.get("schema") != STRUCTURE_SCHEMA:
        errors.append("ongeldig_schema")
    if structure.get("document_id") != document_id:
        errors.append("verkeerd_bron_document")
    if structure.get("source_sha256") != source_sha256:
        errors.append("bronbestand_gewijzigd")
    if structure.get("status") == "verouderd":
        errors.append("structuur_verouderd")
    if structure.get("nummering_bevestigd") is not True:
        errors.append("vraagnummering_niet_bevestigd")
    allowed = set(int(n) for n in confirmed_question_numbers)
    seen_ids = set()
    for fragment in structure.get("fragments", []):
        fid = fragment.get("id")
        if not fid or fid in seen_ids:
            errors.append("fragment_id_ontbreekt_of_dubbel")
        seen_ids.add(fid)
        if fragment.get("type") not in FRAGMENT_TYPES:
            errors.append("ongeldig_fragmenttype")
        links = fragment.get("question_numbers", [])
        if any(int(n) not in allowed for n in links):
            errors.append("ongeldige_vraagkoppeling")
        if fragment.get("type") == "vraag" and len(links) != 1:
            errors.append("vraagfragment_moet_een_vraagnummer_hebben")
        spans = fragment.get("page_spans", [])
        if not spans:
            errors.append("fragment_zonder_paginagrenzen")
        previous_page = 0
        for span in spans:
            try:
                clean = make_page_span(span["page"], span["top"], span["bottom"])
            except (KeyError, TypeError, ValueError):
                errors.append("ongeldige_paginagrens")
                continue
            if clean["page"] <= previous_page:
                errors.append("paginagrenzen_niet_oplopend")
            previous_page = clean["page"]
    return sorted(set(errors))


def make_exam_structure(document: dict, fragments: list[dict], confirmed_question_numbers: list[int]) -> dict:
    return {
        "schema": STRUCTURE_SCHEMA,
        "document_id": document["id"],
        "source_sha256": document["sha256"],
        "nummering_bevestigd": True,
        "vraag_nummers": sorted({int(n) for n in confirmed_question_numbers}),
        "fragments": deepcopy(fragments),
        "status": "concept_handmatige_controle",
    }


def mark_structure_stale(structure: dict | None, reason: str) -> dict | None:
    if structure is None:
        return None
    updated = deepcopy(structure)
    updated["status"] = "verouderd"
    updated["verouderingsreden"] = str(reason)
    return updated


def fragments_for_question(structure: dict | None, question_number: int) -> dict:
    """Return the manually defined question region and every context fragment linked to it."""
    if not structure or structure.get("status") == "verouderd" or structure.get("nummering_bevestigd") is not True:
        return {"question_fragment": None, "context_fragments": [], "status": "structuur_niet_beschikbaar"}
    number = int(question_number)
    linked = [fragment for fragment in structure.get("fragments", [])
              if number in [int(x) for x in fragment.get("question_numbers", [])]]
    question = next((x for x in linked if x.get("type") == "vraag"), None)
    contexts = [x for x in linked if x.get("type") in {"context_intro", "vraagcontext", "tussenliggende_context"}]
    return {
        "question_fragment": question,
        "context_fragments": contexts,
        "status": "gekoppeld" if question or contexts else "geen_fragmenten_gekoppeld",
    }
