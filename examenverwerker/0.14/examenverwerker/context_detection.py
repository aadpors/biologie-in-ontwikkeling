"""Voorstellen voor contextfragmenten die bij meerdere examenvragen horen.

Contexten staan doorgaans vóór de eerste vraag van een nieuw onderwerp. Deze
module zoekt daarom per pagina naar inhoud boven de eerste hoofdvraag. Dat is
slechts een voorstel: de docent controleert de afbeelding en past het bereik
van de contextgroep aan. Een context wordt nooit stilzwijgend aan vragen
gekoppeld zonder expliciete review.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from .question_fragments import _trim_whitespace


def generate_context_candidates(
    pdf_path: str | Path,
    accepted_starts: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    render_scale: float = 1.5,
    top_margin: float = 38.0,
    question_margin: float = 12.0,
) -> dict[str, Any]:
    """Maak contextvoorstellen boven de eerste vraagstart op iedere pagina.

    De werkwijze is bewust conservatief: alleen pagina's met voldoende
    selecteerbare tekst boven een goedgekeurde vraagstart leveren een voorstel
    op. Afbeeldingen blijven behouden doordat de uitsnede uit de originele
    PDF-pagina wordt gerenderd, niet uit de tekstlaag wordt opgebouwd.
    """
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for old in destination.glob("context-*.png"):
        old.unlink()

    starts_by_page: dict[int, list[dict[str, Any]]] = {}
    for start in accepted_starts:
        starts_by_page.setdefault(int(start["page_index"]), []).append(start)
    candidates = []
    with fitz.open(pdf_path) as pdf:
        for page_index, starts in sorted(starts_by_page.items()):
            page = pdf[page_index]
            first_start = min(starts, key=lambda item: (item["pdf_bbox"][1], item["pdf_bbox"][0]))
            # Een contextvoorstel begint onder de vaste documentkop en eindigt
            # net boven het vraagnummer. Daardoor wordt het nummer niet dubbel
            # opgenomen in zowel context als vraagfragment.
            y0 = min(top_margin, page.rect.height - 1)
            y1 = max(y0 + 1, min(page.rect.height, float(first_start["pdf_bbox"][1]) - question_margin))
            clip = fitz.Rect(0, y0, page.rect.width, y1)
            extracted = page.get_text("text", clip=clip).strip()
            words = [word for word in extracted.split() if word.strip()]
            # Een paar losse kopregels of een paginanummer zijn geen context.
            # Twintig woorden is een voorzichtige ondergrens die korte
            # betekenisvolle contexten niet automatisch goedkeurt, maar wel
            # voorkomt dat elke lege bovenmarge als context wordt aangeboden.
            if len(words) < 20:
                continue
            pixmap = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale),
                                     clip=clip, alpha=False, annots=True)
            filename = f"context-page-{page_index + 1:03d}.png"
            target = destination / filename
            pixmap.save(target)
            _trim_whitespace(target, padding=22)
            first_line = next((line.strip() for line in extracted.splitlines() if line.strip()), "Context")
            candidates.append({
                "id": f"context-p{page_index + 1}",
                "page_index": page_index,
                "page_number": page_index + 1,
                "suggested_from_question": int(first_start["question_number"]),
                "from_question": int(first_start["question_number"]),
                "to_question": None,
                "label": first_line[:120],
                "extracted_text": extracted,
                "filename": filename,
                "url": f"/api/context-images/{target.parent.parent.parent.name}/{filename}",
                "pdf_clip": [round(clip.x0, 2), round(clip.y0, 2), round(clip.x1, 2), round(clip.y1, 2)],
                "reviewed": False,
            })

    # Een context loopt als voorstel door tot de vraag vóór het volgende
    # contextbegin. Dit is een startpunt voor menselijke correctie, geen
    # definitieve semantische koppeling.
    candidates.sort(key=lambda item: item["from_question"])
    for index, item in enumerate(candidates):
        if index + 1 < len(candidates):
            item["to_question"] = candidates[index + 1]["from_question"] - 1
        else:
            item["to_question"] = max((int(start["question_number"]) for start in accepted_starts), default=item["from_question"])
        item["to_question"] = max(item["from_question"], item["to_question"])
    return {"context_count": len(candidates), "contexts": candidates,
            "question_count": len({int(item["question_number"]) for item in accepted_starts})}


def validate_context_review(payload: dict[str, Any], expected_ids: set[str], question_numbers: set[int]) -> dict[str, Any]:
    """Controleer unieke, sluitende contextbereiken en expliciete review."""
    contexts = payload.get("contexts")
    if not isinstance(contexts, list):
        raise ValueError("De contextcontrole ontbreekt.")
    cleaned = []
    seen = set()
    for item in contexts:
        if not isinstance(item, dict):
            raise ValueError("Een contextgroep heeft een ongeldig formaat.")
        context_id = item.get("id")
        start = item.get("from_question")
        end = item.get("to_question")
        if context_id not in expected_ids or context_id in seen:
            raise ValueError("Een contextgroep ontbreekt of is dubbel.")
        if not isinstance(start, int) or not isinstance(end, int) or start > end:
            raise ValueError(f"Ongeldig vraagbereik voor context {context_id}.")
        if not set(range(start, end + 1)).issubset(question_numbers):
            raise ValueError(f"Context {context_id} verwijst naar een niet-bestaand vraagnummer.")
        seen.add(context_id)
        cleaned.append({"id": context_id, "from_question": start, "to_question": end,
                        "reviewed": bool(item.get("reviewed"))})
    if seen != expected_ids:
        raise ValueError("Controleer alle voorgestelde contexten.")
    reviewed = sum(item["reviewed"] for item in cleaned)
    return {"contexts": cleaned, "reviewed_count": reviewed,
            "reviewed_all_contexts": reviewed == len(cleaned)}
