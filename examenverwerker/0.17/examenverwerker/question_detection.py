"""Herkenning van hoofdvraagstarts in examen-PDF's.

De detector werkt op tekstregels met hun oorspronkelijke PDF-coördinaten.
Hij is nadrukkelijk een voorstelgenerator: de visuele review blijft leidend.
De conservatieve regex accepteert alleen een kaal hoofdnummer aan het begin
van een regel (bijvoorbeeld '12' of '12.'). Subvragen als '12a', genummerde
beweringen als '1.' midden in een zin en paginavoeten worden niet als
hoofdvragen aangemerkt. Een vervolgiteratie kan lay-out- en OCR-signalen
gebruiken zonder het API-contract te wijzigen.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import fitz

# Een hoofdvraag begint meestal met een los nummer; bij sommige examens staat
# er een punt achter. Geen letters toestaan voorkomt dat 12a als hoofdvraag
# wordt behandeld. We verwerken de volledige regel om paginanummers onderaan
# de pagina en getallen in lopende tekst te kunnen uitsluiten.
QUESTION_LINE = re.compile(r"^\s*(?P<number>\d{1,2})\s*\.?\s*$")
# Sommige examenopgaven zetten het nummer en de eerste woorden van de vraag op
# dezelfde regel. Deze tweede vorm wordt eveneens aangeboden, maar blijft een
# kandidaat en krijgt geen automatische inhoudelijke goedkeuring.
# Een nummer met tekst erachter is alleen kandidaat als het nummer ook
# typografisch als opsomming/vraagstart is gemarkeerd, of als de tekst erna
# met een hoofdletter begint. Zo wordt bijvoorbeeld "6 kPa" niet herkend.
QUESTION_WITH_TEXT = re.compile(r"^\s*(?P<number>\d{1,2})[.)]?\s+(?P<rest>\S.*)$")

# Cito-opgaven drukken het puntenaantal vaak direct vóór het vraagnummer af:
# bijvoorbeeld "1p 1 Geef ..." of "2p 17 Via welk bloedvat ...". De oude
# detector keek alleen naar een regel die met het vraagnnummer begon en miste
# daardoor juist deze veelvoorkomende layout. Deze regex herkent de score als
# prefix, maar gebruikt het daaropvolgende getal als het echte vraagnummer.
QUESTION_WITH_SCORE = re.compile(
    r"^\s*\d{1,2}\s*p\s+(?P<number>\d{1,2})\s+(?P<rest>\S.*)$",
    re.IGNORECASE,
)


def _text_lines(page: fitz.Page) -> list[dict[str, Any]]:
    """Haal regels met PDF-puntcoördinaten op, zonder tekst te reconstrueren."""
    lines: list[dict[str, Any]] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            # Tekst uit verschillende PDF-spans kan zonder spatie worden
            # samengevoegd, ook wanneer er visueel wel ruimte tussen staat.
            # Herstel daarom alleen een spatie bij een zichtbare horizontale
            # tussenruimte; letterdelen die tegen elkaar staan blijven aaneen.
            ordered_spans = sorted(spans, key=lambda span: span.get("bbox", [0, 0, 0, 0])[0])
            pieces: list[str] = []
            previous_right = None
            for span in ordered_spans:
                span_text = str(span.get("text", ""))
                span_bbox = span.get("bbox", [0, 0, 0, 0])
                current_left = float(span_bbox[0]) if len(span_bbox) == 4 else None
                if pieces and current_left is not None and previous_right is not None:
                    if current_left - previous_right > 1.5 and not pieces[-1].endswith(" "):
                        pieces.append(" ")
                pieces.append(span_text)
                previous_right = float(span_bbox[2]) if len(span_bbox) == 4 else previous_right
            text = "".join(pieces).strip()
            if not text:
                continue
            bbox = line.get("bbox")
            if not bbox:
                continue
            # Bewaar gemiddelde lettergrootte als aanvullend signaal voor
            # latere ranking; de eerste detector gebruikt dit niet als harde eis.
            sizes = [float(span.get("size", 0)) for span in spans if span.get("text", "").strip()]
            lines.append({"text": text, "bbox": [round(float(v), 2) for v in bbox],
                          "font_size": round(sum(sizes) / len(sizes), 2) if sizes else 0.0,
                          # De spans blijven beschikbaar om het vraagnummer
                          # los van het voorafgaande puntenlabel te markeren.
                          "spans": spans})
    return sorted(lines, key=lambda item: (item["bbox"][1], item["bbox"][0]))


def detect_question_starts(pdf_path: str, *, render_scale: float = 1.35, enforce_sequence: bool = True, allow_lowercase_text: bool = False) -> dict[str, Any]:
    """Geef kandidaat-hoofdvraagstarts terug met zowel PDF- als previewposities.

    De paginafooterzone (onderste 5,5% van de pagina) wordt uitgesloten.
    Dit voorkomt dat het gedrukte paginanummer als vraagstart wordt gezien.
    Alle kandidaten starten standaard als ``accepted=True`` zodat de docent
    alleen uitzonderingen hoeft af te wijzen; de interface maakt dit expliciet.
    """
    pages: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf):
            rect = page.rect
            # Leg de werkelijke PNG-afmetingen vast. PyMuPDF rondt de
            # pixelafmetingen af; die kunnen fracties afwijken van
            # rect * render_scale. De overlay gebruikt daarom per pagina de
            # gemeten x/y-schaal in plaats van een theoretische factor.
            preview_pixmap = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=False)
            scale_x = preview_pixmap.width / rect.width
            scale_y = preview_pixmap.height / rect.height
            lines = _text_lines(page)
            page_candidates = []
            for line in lines:
                match = QUESTION_LINE.fullmatch(line["text"])
                number_bbox = None
                if not match:
                    match = QUESTION_WITH_SCORE.fullmatch(line["text"])
                    if match:
                        # Gebruik de bbox van het vraagnnummer zelf wanneer
                        # PyMuPDF dit als afzonderlijke tekstspan rapporteert.
                        # Zo markeren we niet het puntenlabel links ervan.
                        spans = line.get("spans", [])
                        score_seen = False
                        for span in spans:
                            span_text = str(span.get("text", "")).strip()
                            if not score_seen and re.fullmatch(r"\d{1,2}p", span_text, re.IGNORECASE):
                                score_seen = True
                                continue
                            if score_seen and span_text == match.group("number"):
                                number_bbox = [float(value) for value in span.get("bbox", [])]
                                break
                if not match:
                    match = QUESTION_WITH_TEXT.fullmatch(line["text"])
                    if match and not allow_lowercase_text:
                        # Een hoofdvraag begint doorgaans met een hoofdletter.
                        # Een regel als "6 kPa" of "1, 2 of 3" is daarmee geen
                        # vraagstart, ook al begint de regel met een getal.
                        rest = match.group("rest").lstrip()
                        if not rest or not rest[0].isupper():
                            match = None
                if not match:
                    continue
                number = int(match.group("number"))
                candidate_bbox = number_bbox if number_bbox and len(number_bbox) == 4 else line["bbox"]
                x0, y0, x1, y1 = candidate_bbox
                # Hoofdvraagnummering begint bij 1; 0 is vrijwel altijd
                # onderdeel van paginering, een code of een ander label.
                if number < 1 or number > 60:
                    continue
                if y1 >= rect.height * 0.945:
                    continue
                # Vraagstarts staan doorgaans in de linkerkolom. De grens is
                # ruim gehouden voor examens met een inspringende nummerkolom.
                if x0 > rect.width * 0.42:
                    continue
                item = {
                    "id": f"p{page_index + 1}-q{number}-{len(candidates) + 1}",
                    "question_number": number,
                    "page_index": page_index,
                    "text": line["text"],
                    "pdf_bbox": [round(float(value), 2) for value in candidate_bbox],
                    "preview_bbox": [round(candidate_bbox[0] * scale_x, 2),
                                     round(candidate_bbox[1] * scale_y, 2),
                                     round(candidate_bbox[2] * scale_x, 2),
                                     round(candidate_bbox[3] * scale_y, 2)],
                    "font_size": line["font_size"],
                    "accepted": True,
                    "source": "automatic",
                }
                page_candidates.append(item)
                candidates.append(item)
            # De nummerkolom wordt per pagina beoordeeld, maar niet meer
            # teruggebracht tot één dominante x-positie. Examenpagina's kunnen
            # wisselende inspringingen, twee kolommen of afwijkende posities
            # voor vervolgvragen hebben. Een dominante-kolomfilter verwijderde
            # daardoor soms echte vraagstarts. De ruimere linkermargefilter
            # hierboven blijft de belangrijkste bescherming tegen lopende tekst.
            # Geef ook de werkelijk geëxtraheerde woorden mee. De handmatige
            # plaatsfunctie kan daarmee het nummer onder het door de docent
            # geplaatste vakje uitlezen, in plaats van zelf een vrij nummer te
            # verzinnen. De woordcoördinaten zijn PDF-punten, net als pdf_bbox.
            page_words = []
            for word in page.get_text("words"):
                if len(word) >= 5 and str(word[4]).strip():
                    page_words.append({
                        "text": str(word[4]).strip(),
                        "bbox": [round(float(value), 2) for value in word[:4]],
                    })

            pages.append({"page_index": page_index, "width": rect.width,
                          "height": rect.height, "render_width": preview_pixmap.width,
                          "render_height": preview_pixmap.height, "scale_x": scale_x,
                          "scale_y": scale_y, "candidate_count": len(page_candidates),
                          "words": page_words, "candidates": page_candidates})
            # De kandidaatverzameling wordt pas na alle pagina's globaal
            # gefilterd op nummerverloop; een sprong vooruit mag, teruglopen
            # niet. Dit sluit bijvoorbeeld een toevallige "1" na vraag 12 uit.
            candidates.extend([])  # expliciet: paginaresultaten worden hieronder verzameld

    # Verzamel de pagina-kandidaten opnieuw in documentvolgorde en bewaak
    # één oplopende hoofdvraagreeks. De docent kan afwijkingen nog handmatig
    # toevoegen in de reviewstap.
    ordered = [item for page in pages for item in page["candidates"]]
    if enforce_sequence:
        # Hoofdvraagnummering loopt normaal strikt op. Stellingen en subvragen
        # kunnen geometrisch op een hoofdvraag lijken, maar vallen vaak buiten
        # die reeks. Bepaal daarom de langste strikt oplopende deelreeks.
        # Kandidaten buiten die reeks blijven zichtbaar voor menselijke review,
        # maar worden niet automatisch als hoofdvraag geaccepteerd.
        # Bij gelijke lengtes wint de vroegste reeks, zodat een latere 1,2,3
        # na vraag 8 niet de echte hoofdvraagreeks verdringt.
        lengths = [1] * len(ordered)
        previous = [-1] * len(ordered)
        for index, item in enumerate(ordered):
            number = int(item["question_number"])
            for earlier in range(index):
                if (int(ordered[earlier]["question_number"]) < number
                        and lengths[earlier] + 1 > lengths[index]):
                    lengths[index] = lengths[earlier] + 1
                    previous[index] = earlier

        if ordered:
            best = max(range(len(ordered)), key=lambda index: lengths[index])
            main_indices = set()
            while best >= 0:
                main_indices.add(best)
                best = previous[best]

            for index, item in enumerate(ordered):
                if index not in main_indices:
                    item["sequence_warning"] = True
                    item["sequence_reason"] = (
                        "Nummer past niet in de oplopende hoofdvraagreeks; "
                        "mogelijk een stelling, subvraag of ander genummerd onderdeel."
                    )
                    item["accepted"] = False
                else:
                    item["sequence_warning"] = False
        candidates = ordered
    else:
        candidates = ordered
    # Houd ook de paginaweergave gelijk aan de gefilterde documentlijst.
    accepted_ids = {item["id"] for item in candidates}
    for page in pages:
        page["candidates"] = [item for item in page["candidates"] if item["id"] in accepted_ids]
        page["candidate_count"] = len(page["candidates"])

    # Een nummer dat herhaald wordt op meerdere pagina's kan legitiem zijn
    # wanneer een examen een nieuwe sectie begint. We signaleren dit, maar
    # verwijderen nooit automatisch een kandidaat.
    counts: dict[int, int] = defaultdict(int)
    for item in candidates:
        counts[item["question_number"]] += 1
    for item in candidates:
        item["duplicate_number"] = counts[item["question_number"]] > 1
    return {"page_count": len(pages), "candidate_count": len(candidates),
            "pages": pages, "candidates": candidates, "render_scale": render_scale}


def validate_review(
    review: dict[str, Any],
    page_count: int,
    page_sizes: list[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Valideer docentcorrecties voordat ze als bewijs worden opgeslagen.

    ``page_sizes`` bevat de echte PDF-paginaformaten in punten. Als deze
    beschikbaar zijn, weigert de API coördinaten buiten de betreffende pagina.
    Dit is vooral belangrijk voor handmatig geplaatste vraagstarts: een foutieve
    browsercoördinaat mag geen fragment buiten de bronpagina veroorzaken.
    """
    candidates = review.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("De lijst met vraagstarts ontbreekt.")
    cleaned = []
    seen_ids = set()
    for item in candidates:
        if not isinstance(item, dict):
            raise ValueError("Een vraagstart heeft een ongeldig formaat.")
        candidate_id = str(item.get("id", ""))
        if not candidate_id or candidate_id in seen_ids:
            raise ValueError("Iedere vraagstart moet een unieke identificatie hebben.")
        seen_ids.add(candidate_id)
        number = item.get("question_number")
        page_index = item.get("page_index")
        bbox = item.get("pdf_bbox")
        if not isinstance(number, int) or not 1 <= number <= 60:
            raise ValueError(f"Ongeldig vraagnummer bij {candidate_id}.")
        if not isinstance(page_index, int) or not 0 <= page_index < page_count:
            raise ValueError(f"Ongeldig paginanummer bij {candidate_id}.")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError(f"Ongeldige positie bij {candidate_id}.")
        x0, y0, x1, y1 = [float(value) for value in bbox]
        if not (0 <= x0 < x1 and 0 <= y0 < y1):
            raise ValueError(f"Ongeldige rechthoek bij {candidate_id}.")
        if page_sizes is not None:
            page_width, page_height = page_sizes[page_index]
            if x1 > page_width or y1 > page_height:
                raise ValueError(f"Vraagstart {candidate_id} valt buiten de paginagrenzen.")
        cleaned.append({**item, "question_number": number, "page_index": page_index,
                        "pdf_bbox": [x0, y0, x1, y1], "accepted": bool(item.get("accepted"))})
    accepted = [item for item in cleaned if item["accepted"]]
    # Een dubbele nummering blijft zichtbaar als waarschuwing; ze wordt niet
    # stilzwijgend opgelost omdat alleen een mens de examenstructuur kent.
    number_counts: dict[int, int] = defaultdict(int)
    for item in accepted:
        number_counts[item["question_number"]] += 1
    duplicates = sorted(number for number, count in number_counts.items() if count > 1)
    return {"candidates": cleaned, "accepted_count": len(accepted),
            "rejected_count": len(cleaned) - len(accepted),
            "duplicate_question_numbers": duplicates, "reviewed": True}
