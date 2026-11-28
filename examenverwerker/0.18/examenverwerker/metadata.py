"""Voorstellen voor documentmetadata.

De bestandsnaam is leidend voor het documenttype. De eerste PDF-pagina wordt
alleen gebruikt voor aanvullende metadata; de applicatie vraagt één keer om
bevestiging en bewaart daarna de bevestigde waarden bij het examen.
"""
from __future__ import annotations

import re
from pathlib import Path
import fitz

TYPE_SUFFIXES = {
    "-o": "opgaven",
    "-u": "uitwerkbijlage",
    "-c": "correctievoorschrift",
    "-a": "aanvulling_correctievoorschrift",
}


def extract_first_page_text(pdf_path: str | Path) -> str:
    """Lees uitsluitend de eerste pagina als tekstuele metadata-bron."""
    with fitz.open(pdf_path) as document:
        return document[0].get_text("text") if document.page_count else ""


def suggest_metadata(pdf_path: str | Path) -> dict:
    """Leid voorzichtig metadata af; onbekende waarden blijven leeg.

    De bestandsnaamconventie die in de blauwdruk is vastgelegd, wordt als
    eerste bron gebruikt. Voor vak, niveau, jaar en tijdvak worden herkenbare
    patronen uit bestandsnaam en eerste pagina gecombineerd. Onzekere velden
    worden niet ingevuld met een gok.
    """
    path = Path(pdf_path)
    stem = path.stem.lower()
    first_page = extract_first_page_text(path)
    combined = f"{path.stem} {first_page[:5000]}".lower()

    document_type = next((kind for suffix, kind in TYPE_SUFFIXES.items() if stem.endswith(suffix)), "")
    subject = "biologie" if re.search(r"\bbiologie\b|\bbio\b", combined) else ""
    level_match = re.search(r"\b(vwo|havo|vmbo[- ]?(?:tl|gl|kb|bb))\b", combined)
    year_match = re.search(r"\b(20\d{2})\b", path.stem)
    if not year_match:
        year_match = re.search(r"\b(20\d{2})\b", first_page[:2500])
    period_match = re.search(r"(?:tijdvak|tv)\s*([123])", combined)

    return {
        "subject": subject,
        "level": level_match.group(1).replace(" ", "-") if level_match else "",
        "year": int(year_match.group(1)) if year_match else None,
        "period": int(period_match.group(1)) if period_match else None,
        "document_type": document_type,
        "needs_confirmation": True,
    }
