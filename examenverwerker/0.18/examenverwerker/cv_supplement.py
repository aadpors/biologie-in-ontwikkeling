"""Voorbereiden van een veilige, controleerbare CV-aanvulling.

Een aanvulling wordt nooit automatisch over het oorspronkelijke CV heen
geplaatst. De module maakt per pagina een voorstel en vraagt de docent om
ieder wijzigingsonderdeel als toevoegen, vervangen of handmatig beoordelen
te classificeren. De bron-PDF en het oorspronkelijke correctievoorschrift
blijven altijd afzonderlijk bewaard.
"""
from __future__ import annotations

import re
from typing import Any

import fitz

QUESTION_REFERENCE = re.compile(r"\b(?:vraag|vragen)\s*(\d{1,2})\b", re.IGNORECASE)
REPLACE_SIGNALS = ("vervangt", "vervangen", "in plaats van", "komt te vervallen", "vervalt", "moet worden gelezen als")
ADD_SIGNALS = ("toevoegen", "toegevoegd", "extra", "aanvullend")


def analyse_supplement(pdf_path: str) -> dict[str, Any]:
    """Lees alle pagina's en maak controle-items zonder iets samen te voegen."""
    items = []
    with fitz.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf):
            text = page.get_text("text").strip()
            if not text:
                # Scans blijven zichtbaar als pagina-item, maar krijgen geen
                # automatisch voorstel. OCR mag later als afzonderlijke
                # herkenningslaag worden toegevoegd.
                items.append({"page_index": page_index, "page_number": page_index + 1,
                              "question_numbers": [], "text": "",
                              "action": "handmatig", "reason": "Geen tekstlaag; visuele controle nodig.",
                              "reviewed": False})
                continue
            references = list(QUESTION_REFERENCE.finditer(text))
            numbers = sorted({int(match.group(1)) for match in references})
            # Wanneer één supplementpagina meerdere vragen behandelt, wordt
            # de tekst vanaf iedere expliciete vraagverwijzing tot de volgende
            # verwijzing apart bewaard. Zo krijgt vraag 12 niet per ongeluk de
            # volledige tekst van de wijziging voor vraag 13 erbij.
            question_texts: dict[str, str] = {}
            for index, match in enumerate(references):
                number = int(match.group(1))
                end = references[index + 1].start() if index + 1 < len(references) else len(text)
                section = text[match.start():end].strip()
                question_texts[str(number)] = (question_texts.get(str(number), "") + "\n\n" + section).strip()
            lowered = text.casefold()
            replace = any(signal in lowered for signal in REPLACE_SIGNALS)
            add = any(signal in lowered for signal in ADD_SIGNALS)
            if replace and not add:
                action, reason = "vervangen", "De tekst bevat een expliciete vervangingsformulering; controleer de reikwijdte."
            elif add and not replace:
                action, reason = "toevoegen", "De tekst lijkt een aanvulling te beschrijven; controleer de koppeling."
            else:
                action, reason = "handmatig", "Geen eenduidige toevoeging of vervanging herkend."
            items.append({"page_index": page_index, "page_number": page_index + 1,
                          "question_numbers": numbers, "question_texts": question_texts, "text": text,
                          "action": action, "reason": reason, "reviewed": False})
    return {"page_count": len(items), "items": items}


def validate_supplement_review(payload: dict[str, Any], expected_pages: set[int]) -> dict[str, Any]:
    """Bewaar expliciete keuzes per supplementpagina; nooit automatisch toepassen."""
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("De controle van de aanvulling ontbreekt.")
    cleaned = []
    seen = set()
    allowed = {"toevoegen", "vervangen", "handmatig", "negeren"}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Een aanvulling-item heeft een ongeldig formaat.")
        page = item.get("page_number")
        if not isinstance(page, int) or page not in expected_pages or page in seen:
            raise ValueError("Een paginanummer ontbreekt, is dubbel of hoort niet bij de aanvulling.")
        seen.add(page)
        action = item.get("action")
        if action not in allowed:
            raise ValueError(f"Ongeldige verwerkingskeuze op pagina {page}.")
        question_numbers = item.get("question_numbers", [])
        if (not isinstance(question_numbers, list) or
                any(not isinstance(number, int) or not 1 <= number <= 60 for number in question_numbers) or
                len(set(question_numbers)) != len(question_numbers)):
            raise ValueError(f"Ongeldige vraagkoppeling op supplementpagina {page}.")
        if action in {"toevoegen", "vervangen"} and not question_numbers:
            raise ValueError(f"Koppel supplementpagina {page} aan ten minste één vraag.")
        cleaned.append({"page_number": page, "action": action,
                        "question_numbers": sorted(question_numbers),
                        "reviewed": bool(item.get("reviewed"))})
    if seen != expected_pages:
        raise ValueError("Controleer iedere pagina van de aanvulling.")
    reviewed = sum(item["reviewed"] for item in cleaned)
    return {"items": cleaned, "reviewed_count": reviewed,
            "reviewed_all_pages": reviewed == len(cleaned),
            "merge_policy": "reviewed_decisions_only"}
