"""Genereren van visuele vraagfragmenten uit goedgekeurde vraagstarts.

De fragmenten worden altijd opnieuw uit het oorspronkelijke PDF-bestand
rendered. Een eerder gegenereerde PNG is dus nooit de bron voor een volgende
bewerking. Iedere vraag kan uit meerdere deelafbeeldingen bestaan wanneer de
vraag over een paginaovergang loopt. De grenzen zijn voorstellen en moeten
visueel worden gecontroleerd voordat de workflow verder mag.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import fitz
from PIL import Image, ImageDraw


def _trim_whitespace(image_path: Path, *, padding: int = 18) -> None:
    """Snijd uitsluitend buitenste witte randen weg, met behoud van marge.

    De renderclip bepaalt de inhoudelijke bovengrens en ondergrens. Deze
    tweede stap verwijdert alleen overbodige witte ruimte binnen die clip.
    Een lichte drempel voorkomt dat anti-aliasing of een vrijwel witte
    achtergrond als harde inhoudsgrens wordt behandeld.
    """
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        # Een pixel telt als inhoud zodra één kanaal duidelijk afwijkt van wit.
        # Het witte referentievlak en de drempel zijn bewust ruim: grijze
        # tekst, dunne lijnen en lichte illustraties moeten behouden blijven.
        # Een zuiver witte paginaachtergrond krijgt waarde 0; pixels die
        # donkerder zijn dan 252 worden als inhoud gemarkeerd. Hierdoor wordt
        # wit niet per ongeluk als een verschil met een bijna-witte referentie
        # gezien, terwijl lichte grijstinten nog wel behouden blijven.
        mask = Image.eval(image.convert("L"), lambda value: 255 if value < 252 else 0)
        bbox = mask.getbbox()
        if not bbox:
            return
        left, top, right, bottom = bbox
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(image.width, right + padding)
        bottom = min(image.height, bottom + padding)
        image.crop((left, top, right, bottom)).save(image_path, format="PNG", optimize=True)



def _repeated_marginal_boxes(pdf: fitz.Document) -> list[list[list[float]]]:
    """Vind herhaalde kop-/voettekstregels in de buitenste paginamarges.

    Alleen regels die in de bovenste 6% of onderste 6% van een pagina staan
    worden onderzocht. Een identieke regel moet op ten minste twee pagina's
    voorkomen voordat deze als niet-inhoudelijke herhaling wordt gemaskeerd.
    Losse paginanummers in de marge worden eveneens herkend.
    """
    occurrences: dict[str, set[int]] = {}
    boxes_by_page: list[list[tuple[str, list[float]]]] = [[] for _ in pdf]
    page_number_pattern = re.compile(r"^\d{1,3}$")
    for page_index, page in enumerate(pdf):
        height = page.rect.height
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if not text:
                    continue
                bbox = [float(value) for value in line.get("bbox", [])]
                if len(bbox) != 4:
                    continue
                in_margin = bbox[1] <= height * 0.06 or bbox[3] >= height * 0.94
                if not in_margin:
                    continue
                key = " ".join(text.casefold().split())
                boxes_by_page[page_index].append((key, bbox))
                if not page_number_pattern.fullmatch(text):
                    occurrences.setdefault(key, set()).add(page_index)
    repeated = {key for key, pages in occurrences.items() if len(pages) >= 2}
    result: list[list[list[float]]] = []
    for page_lines in boxes_by_page:
        result.append([bbox for key, bbox in page_lines if key in repeated or page_number_pattern.fullmatch(key)])
    return result


def _mask_marginal_boxes(image_path: Path, boxes: list[list[float]], clip: fitz.Rect,
                         scale_x: float, scale_y: float) -> None:
    """Bedek uitsluitend herhaalde kop-/voettekst buiten de vraaginhoud."""
    if not boxes:
        return
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        for x0, y0, x1, y1 in boxes:
            # De box wordt naar de lokale renderuitsnede teruggerekend.
            # Regels buiten de vraagclip vallen vanzelf buiten de afbeelding.
            left = max(0, int((x0 - clip.x0) * scale_x) - 2)
            top = max(0, int((y0 - clip.y0) * scale_y) - 2)
            right = min(image.width, int((x1 - clip.x0) * scale_x) + 2)
            bottom = min(image.height, int((y1 - clip.y0) * scale_y) + 2)
            if left < right and top < bottom:
                draw.rectangle((left, top, right, bottom), fill="white")
        image.save(image_path, format="PNG", optimize=True)


def _stitch_vertical(segment_paths: list[Path], output_path: Path, *, gap: int = 24) -> None:
    """Stitch CV-paginadelen verticaal tot één doorlopend vraagfragment."""
    images: list[Image.Image] = []
    try:
        for path in segment_paths:
            with Image.open(path) as source:
                images.append(source.convert("RGB"))
        if not images:
            raise ValueError("Er zijn geen CV-paginadelen om samen te voegen.")
        width = max(image.width for image in images)
        height = sum(image.height for image in images) + gap * (len(images) - 1)
        stitched = Image.new("RGB", (width, height), "white")
        y = 0
        for image in images:
            stitched.paste(image, (0, y))
            y += image.height + gap
        stitched.save(output_path, format="PNG", optimize=True)
    finally:
        for image in images:
            image.close()


def build_stitched_exam(pdf_path: str | Path, output_path: str | Path, *,
                        render_scale: float = 1.25, page_gap: int = 32,
                        start_page: int = 1) -> dict[str, Any]:
    """Maak één lange, opgeschoonde werkafbeelding van het examen.

    Pagina 1 wordt standaard overgeslagen omdat dit de omslag/instructiepagina
    is. Elke volgende pagina wordt eerst gerenderd, herhaalde kop- en
    voetteksten worden gemaskeerd en vervolgens wordt alleen de inhoudelijke
    bounding box met een kleine marge behouden. De pagina's worden daarna
    op gelijke breedte verticaal gestitcht. De oorspronkelijke PDF blijft
    volledig onaangeraakt; deze PNG is uitsluitend een selectiewerkvlak.

    De metadata bevat per bronpagina de positie in de lange afbeelding.
    Daardoor kunnen geselecteerde fragmenten later altijd naar de bronpagina
    worden terugvertaald en blijven de uitsneden herleidbaar.
    """
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    page_images: list[Image.Image] = []
    page_meta: list[dict[str, Any]] = []
    try:
        with fitz.open(pdf_path) as pdf:
            if len(pdf) <= start_page:
                raise ValueError("Het opgavenboekje bevat na de eerste pagina geen inhoudspagina's.")
            marginal_boxes = _repeated_marginal_boxes(pdf)
            for page_index in range(start_page, len(pdf)):
                page = pdf[page_index]
                pix = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=False)
                page_path = destination.parent / f"_stitch-page-{page_index + 1:03d}.png"
                pix.save(page_path)
                clip = fitz.Rect(0, 0, page.rect.width, page.rect.height)
                _mask_marginal_boxes(page_path, marginal_boxes[page_index], clip,
                                     pix.width / clip.width, pix.height / clip.height)
                # Paginanummers zijn losse tekstelementen in de onderste
                # paginamarge. Maskeer alleen een geïsoleerde numerieke regel
                # onderaan; getallen in de inhoud blijven daardoor behouden.
                footer_numbers = []
                for block in page.get_text("dict").get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        line_text = " ".join(
                            span.get("text", "") for span in line.get("spans", [])
                        ).strip()
                        line_bbox = line.get("bbox")
                        if not line_bbox:
                            continue
                        lower_text = line_text.casefold()
                        # Veel examen-PDF's combineren de documentcode,
                        # paginering ("2 / 19") en "lees verder" in één regel.
                        # Dat is geen geïsoleerd getal, maar wel een footer.
                        is_page_counter = bool(re.search(r"\b\d{1,3}\s*/\s*\d{1,3}\b", line_text))
                        is_read_on_footer = "lees verder" in lower_text or "►" in line_text
                        is_isolated_number = bool(re.fullmatch(r"[-–—]?\s*\d{1,3}\s*[-–—]?", line_text))
                        if (float(line_bbox[1]) >= page.rect.height * 0.90
                                and (is_page_counter or is_read_on_footer or
                                     (is_isolated_number and float(line_bbox[1]) >= page.rect.height * 0.93))):
                            footer_numbers.append(line_bbox)
                if footer_numbers:
                    with Image.open(page_path) as rendered:
                        cleaned = rendered.convert("RGB")
                        draw = ImageDraw.Draw(cleaned)
                        scale_x = cleaned.width / page.rect.width
                        scale_y = cleaned.height / page.rect.height
                        for x0, y0, x1, y1 in footer_numbers:
                            # Extra witruimte voorkomt restpixels door antialiasing.
                            draw.rectangle((
                                max(0, int(x0 * scale_x) - 5),
                                max(0, int(y0 * scale_y) - 5),
                                min(cleaned.width, int(x1 * scale_x) + 5),
                                min(cleaned.height, int(y1 * scale_y) + 5),
                            ), fill="white")
                        cleaned.save(page_path, format="PNG", optimize=True)
                with Image.open(page_path) as source:
                    image = source.convert("RGB")
                    # Snij grote lege boven-, onder- en zijmarges weg. De
                    # drempel behoudt ook lichte lijnen, kleine labels en
                    # dunne illustraties die inhoudelijk bij de pagina horen.
                    mask = Image.eval(image.convert("L"), lambda value: 255 if value < 246 else 0)
                    bbox = mask.getbbox()
                    if bbox:
                        left, top, right, bottom = bbox
                        pad = max(12, int(render_scale * 8))
                        bbox = (max(0, left-pad), max(0, top-pad),
                                min(image.width, right+pad), min(image.height, bottom+pad))
                        image = image.crop(bbox)
                    page_images.append(image.copy())
                    page_meta.append({
                        "page_number": page_index + 1,
                        "source_width": page.rect.width,
                        "source_height": page.rect.height,
                        "crop_pixels": list(bbox) if bbox else [0, 0, image.width, image.height],
                        "render_width": image.width,
                        "render_height": image.height,
                    })
                page_path.unlink(missing_ok=True)
        if not page_images:
            raise ValueError("Er konden geen inhoudspagina's worden gerenderd.")
        # De breedte van de langste pagina is de gemeenschappelijke maat.
        # Afwijkende paginaformaten worden proportioneel aangepast, nooit
        # uitgerekt, zodat tekst en figuren hun oorspronkelijke verhoudingen houden.
        target_width = max(image.width for image in page_images)
        normalized: list[Image.Image] = []
        for image, meta in zip(page_images, page_meta):
            if image.width != target_width:
                target_height = max(1, round(image.height * target_width / image.width))
                resized = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
                normalized.append(resized)
                meta["stitched_height"] = target_height
                meta["stitched_width"] = target_width
            else:
                normalized.append(image.copy())
                meta["stitched_height"] = image.height
                meta["stitched_width"] = image.width
        total_height = sum(image.height for image in normalized) + page_gap * (len(normalized)-1)
        stitched = Image.new("RGB", (target_width, total_height), "white")
        y = 0
        for image, meta in zip(normalized, page_meta):
            stitched.paste(image, (0, y))
            meta["top"] = y
            meta["bottom"] = y + image.height
            y += image.height + page_gap
            image.close()
        stitched.save(destination, format="PNG", optimize=True)
        stitched.close()
        return {"filename": destination.name, "width": target_width,
                "height": total_height, "page_gap": page_gap,
                "pages": page_meta}
    finally:
        for image in page_images:
            image.close()



def propose_stitched_question_selections(
    page_metadata: list[dict[str, Any]],
    accepted_starts: list[dict[str, Any]],
    *,
    render_scale: float = 1.25,
    image_height: int,
    pdf_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Maak vraagfragmentvoorstellen op de lange examenafbeelding.

    De goedgekeurde vraagstarts zijn het anker voor de automatische indeling.
    PDF-puntcoördinaten worden met de crop- en schaalmetadata omgerekend naar
    pixels op de stitched afbeelding. Iedere vraag loopt tot vlak vóór de
    volgende hoofdvraag, ook wanneer die op een volgende pagina begint.

    De voorstellen zijn nadrukkelijk niet definitief: de docent kan iedere
    grens verslepen, een fragment verwijderen of contexten handmatig toevoegen.
    """
    pages_by_number = {int(page["page_number"]): page for page in page_metadata}
    mapped: list[tuple[float, dict[str, Any]]] = []

    for start in accepted_starts:
        page_number = int(start["page_index"]) + 1
        page = pages_by_number.get(page_number)
        bbox = start.get("pdf_bbox")
        if not page or not isinstance(bbox, list) or len(bbox) != 4:
            continue

        # De crop-bovenrand is uitgedrukt in de oorspronkelijke renderpixels.
        # Na het croppen kan een pagina bovendien proportioneel zijn verkleind
        # of vergroot om alle pagina's op dezelfde stitchbreedte te krijgen.
        crop = page.get("crop_pixels", [0, 0, 0, 0])
        crop_top = float(crop[1])
        cropped_width = max(1.0, float(page.get("render_width", 1)))
        stitched_width = max(1.0, float(page.get("stitched_width", cropped_width)))
        resize_factor = stitched_width / cropped_width

        # crop_pixels bevat alleen de inhoudsbounding-box en dus niet de
        # volledige paginahoogte. De renderfactor moet daarom de schaal zijn
        # waarmee de PDF-pagina werkelijk is gerenderd, niet crop_height /
        # source_height (dat laatste verkleint de coördinaten onterecht).
        local_y = (float(bbox[1]) * render_scale - crop_top) * resize_factor
        absolute_y = float(page["top"]) + local_y
        absolute_y = max(float(page["top"]), min(float(page["bottom"]) - 1, absolute_y))
        mapped.append((absolute_y, start))

    mapped.sort(key=lambda pair: pair[0])

    # Compatibiliteit voor oudere aanroepers en geometrische unit-tests die
    # geen bron-PDF meegeven. De productie-API levert altijd pdf_path aan en
    # gebruikt daardoor de nauwkeuriger witregel-/kadersegmentatie hieronder.
    if pdf_path is None:
        legacy: list[dict[str, Any]] = []
        for index, (start_y, start) in enumerate(mapped):
            has_next = index + 1 < len(mapped)
            next_y = mapped[index + 1][0] if has_next else float(image_height)
            top = max(0.0, start_y - 8.0)
            proposed_bottom = next_y - 4.0 if has_next else float(image_height)
            bottom = min(float(image_height), max(top + 12.0, proposed_bottom))
            if bottom > top:
                number = int(start["question_number"])
                legacy.append({
                    "id": f"auto-vraag-{number}-{index + 1}",
                    "type": "vraag", "top": round(top, 2), "bottom": round(bottom, 2),
                    "question_numbers": [number],
                    "label": "Automatisch voorstel — visueel controleren",
                    "source": "automatic",
                })
        return legacy

    # Verzamel de horizontale visuele scheidingen op de originele PDF-pagina's.
    # Een scheiding kan een duidelijke witregel tussen tekstregels zijn of de
    # boven-/onderrand van een breed kader. De coördinaten worden direct naar
    # dezelfde lange afbeelding vertaald als waarin de docent straks werkt.
    separators: list[float] = []
    page_limits: dict[int, tuple[float, float]] = {}
    if pdf_path is not None:
        with fitz.open(pdf_path) as pdf:
            for page_info in page_metadata:
                page_number = int(page_info["page_number"])
                if page_number < 1 or page_number > pdf.page_count:
                    continue
                page = pdf[page_number - 1]
                crop = page_info.get("crop_pixels", [0, 0, 0, 0])
                crop_top = float(crop[1])
                resize_factor = float(page_info.get("stitched_width", page_info["render_width"])) / max(
                    1.0, float(page_info["render_width"])
                )

                def to_stitch_y(pdf_y: float) -> float:
                    # De PDF is vóór het croppen op render_scale gerenderd.
                    # Gebruik dezelfde schaal bij het terugrekenen van alle
                    # witregel- en kadergrenzen naar de lange afbeelding.
                    return float(page_info["top"]) + (pdf_y * render_scale - crop_top) * resize_factor

                page_top = float(page_info["top"])
                page_bottom = float(page_info["bottom"])
                page_limits[page_number] = (page_top, page_bottom)

                # Witregels: vergelijk de verticale afstand tussen opeenvolgende
                # tekstregels met de normale regelhoogte op deze pagina.
                lines: list[tuple[float, float]] = []
                for block in page.get_text("dict").get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                        bbox = line.get("bbox")
                        if line_text and bbox:
                            lines.append((float(bbox[1]), float(bbox[3])))
                lines.sort()
                if len(lines) >= 2:
                    heights = sorted(max(1.0, bottom - top) for top, bottom in lines)
                    typical_height = heights[len(heights) // 2]
                    for previous, following in zip(lines, lines[1:]):
                        gap = following[0] - previous[1]
                        # Een echte witregel is duidelijk groter dan de normale regelafstand.
                        # De oude grens van 0,85 regelhoogte markeerde ook gewone
                        # tekstregels en sneed daardoor vragen en contexten doormidden.
                        if gap >= max(14.0, typical_height * 1.6):
                            separators.append(to_stitch_y((previous[1] + following[0]) / 2.0))

                # Kadergrenzen: rechthoeken die een substantieel deel van de
                # tekstbreedte beslaan, leveren een duidelijke fragmentgrens.
                for drawing in page.get_drawings():
                    rect = drawing.get("rect")
                    if rect and rect.width >= page.rect.width * 0.22 and rect.height >= 8:
                        separators.extend([to_stitch_y(float(rect.y0)), to_stitch_y(float(rect.y1))])

    separators = sorted({
        round(max(0.0, min(float(image_height), value)), 2)
        for value in separators
    })

    # Ieder vraagfragment is het gebied tussen de dichtstbijzijnde visuele
    # scheiding boven en onder de vraagstart. Daardoor wordt niet automatisch
    # alles tot de volgende vraagstart in één groot vraagfragment opgenomen.
    question_selections: list[dict[str, Any]] = []
    for index, (start_y, start) in enumerate(mapped):
        number = int(start["question_number"])
        page_number = int(start["page_index"]) + 1
        page_top, page_bottom = page_limits.get(page_number, (0.0, float(image_height)))
        # De bovengrens hoort op dezelfde pagina te liggen als de vraagstart.
        # De ondergrens mag op een volgende pagina liggen: zo blijft een vraag
        # die over een paginaovergang doorloopt één doorlopend vraagfragment.
        local_before = [value for value in separators
                        if page_top <= value < start_y]
        global_after = [value for value in separators if value > start_y]
        # Als er vóór de vraagstart geen expliciete witregel/kader is,
        # gebruik dan de vraagstart zelf als scheiding. Zo blijft tekst die
        # aantoonbaar vóór de eerste vraag staat als context beschikbaar.
        # De vraag begint bij het goedgekeurde vraagstartanker, niet bij de
        # dichtstbijzijnde eerdere witregel. Die witregel kan midden in de
        # context of in de vorige vraag liggen. Door het anker te gebruiken
        # blijft alle inhoud tussen het vorige fragment en dit vraagnummer
        # beschikbaar als contextkandidaat.
        top_boundary = start_y - 8.0
        top = max(page_top, top_boundary)
        bottom = min(float(image_height), global_after[0] if global_after else float(image_height))

        # De boven- en ondergrens vallen net buiten de witregel/kaderlijn.
        # De marge voorkomt dat antialiasing of de lijn zelf wordt afgesneden.
        top = max(page_top, top - 2.0)
        bottom = min(page_bottom, bottom + 2.0)
        if bottom - top < 12:
            # Bij een ongebruikelijke PDF-layout liever het vraagstartanker
            # behouden dan een onbruikbaar fragment met vrijwel nul hoogte.
            top = max(page_top, start_y - 8.0)
            bottom = min(float(image_height), start_y + 80.0)
        question_selections.append({
            "id": f"auto-vraag-{number}-{index + 1}",
            "type": "vraag",
            "top": round(top, 2),
            "bottom": round(bottom, 2),
            "question_numbers": [number],
            "label": "Automatisch voorstel — begrensd door witregel/kader",
            "source": "automatic_visual_boundaries",
        })

    # Context vóór de eerste vraag en de niet-geselecteerde ruimte tussen
    # opeenvolgende vraagfragmenten vormen contextfragmenten. Koppel ieder
    # contextfragment aan de eerstvolgende vraag, zodat de leesvolgorde
    # context → vraag → context → vraag ontstaat.
    context_selections: list[dict[str, Any]] = []
    ordered_questions = sorted(question_selections, key=lambda item: item["top"])

    if ordered_questions:
        first_question = ordered_questions[0]
        first_number = int(first_question["question_numbers"][0])
        first_page_number = next(
            (int(start["page_index"]) + 1 for _, start in mapped
             if int(start["question_number"]) == first_number),
            None,
        )
        if first_page_number in page_limits:
            leading_top = page_limits[first_page_number][0]
            first_start_y = next(
                (position for position, start in mapped
                 if int(start["question_number"]) == first_number),
                float(first_question["top"]),
            )
            # Een kaderlijn kan samenvallen met de bovenrand van de crop.
            # Gebruik dan de herkende vraagstart als scheiding tussen de
            # voorafgaande context en het eerste vraagfragment.
            leading_bottom = max(
                float(first_question["top"]),
                first_start_y - 8.0,
            )
            if leading_bottom - leading_top >= 24:
                first_question["top"] = round(leading_bottom, 2)
                context_selections.append({
                    "id": f"auto-context-before-{first_number}",
                    "type": "context",
                    "top": round(leading_top, 2),
                    "bottom": round(leading_bottom, 2),
                    "question_numbers": [first_number],
                    "label": "Automatisch contextvoorstel — inhoud vóór de eerste vraag",
                    "source": "automatic_leading_context",
                })

    for index, question in enumerate(ordered_questions[:-1]):
        following = ordered_questions[index + 1]
        gap_top = float(question["bottom"])
        gap_bottom = float(following["top"])
        if gap_bottom - gap_top < 24:
            continue
        following_number = int(following["question_numbers"][0])
        context_selections.append({
            "id": f"auto-context-between-{question['question_numbers'][0]}-{following_number}",
            "type": "context",
            "top": round(gap_top, 2),
            "bottom": round(gap_bottom, 2),
            "question_numbers": [following_number],
            "label": "Automatisch contextvoorstel — ruimte tussen vraagfragmenten",
            "source": "automatic_inter_question_gap",
        })

    return sorted(
        [*question_selections, *context_selections],
        key=lambda item: (item["top"], 0 if item["type"] == "context" else 1),
    )

def normalise_stitched_selections(
    selections: list[dict[str, Any]],
    white_row_ranges: list[list[int]],
    image_path: str | Path,
    *,
    image_height: int,
    leading_top: float = 0.0,
) -> list[dict[str, Any]]:
    """Maak automatische vraag/contextvoorstellen visueel sluitend.

    De oudere voorstelgenerator kon vraagfragmenten laten overlappen wanneer
    meerdere vragen op één pagina stonden. Ook maakte hij soms een context van
    alleen witruimte. Deze normalisatie gebruikt de goedgekeurde vraagstarts
    als vaste volgorde en de volledige witte beeldrijen als enige grenslijnen.

    De ondergrens van een vraag wordt nooit voorbij de bovengrens van de
    volgende vraag geplaatst. Als de eerste heuristische ondergrens vóór die
    grens valt (bijvoorbeeld midden in een meerregelige vraag), loopt het
    vraagfragment door tot de eerstvolgende vraaggrens. Tussen twee vragen
    wordt alleen een context voorgesteld wanneer daar daadwerkelijk tekst,
    een afbeelding of een ander niet-wit element zichtbaar is.
    """
    if not selections:
        return []
    if not white_row_ranges:
        # Zonder ook maar één volledig witte beeldrij bestaat geen veilige
        # fragmentgrens. Stop daarom met een duidelijke fout in plaats van
        # stilzwijgend een tekstregel of willekeurige pixel als grens te kiezen.
        raise ValueError(
            "De examenafbeelding bevat geen volledig zuiver witte horizontale rij. "
            "De fragmentgrenzen kunnen daarom niet veilig automatisch worden bepaald."
        )

    def snap_before(y: float) -> int:
        """Kies de laatste zuiver witte rij op of vóór een vraaganker.

        Een vraagstart is een inhoudsanker, geen grens zelf. Door de grens
        uitsluitend ervoor te leggen blijft het vraagnummer en de eerste
        tekstregel behouden. Als een wit interval het anker bevat, is het
        anker zelf ook een geldige grenspositie.
        """
        target = max(0, int(round(y)))
        candidates = [
            min(target, end)
            for start, end in white_row_ranges
            if start <= target
        ]
        if not candidates:
            raise ValueError(
                "Vóór een herkende vraagstart is geen volledig zuiver witte "
                "horizontale grensrij gevonden. Controleer de pagina-afsnede."
            )
        return int(max(candidates))

    # De afbeeldingsbron wordt één keer geopend; alle pixelcontroles gebeuren
    # op uitsneden daarvan en niet op opnieuw gerenderde PDF-pagina's.
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        width, height = image.size

        def has_visible_content(top: float, bottom: float) -> bool:
            """True wanneer het gebied ten minste één niet-witte pixel bevat."""
            y0 = max(0, min(height, int(round(top))))
            y1 = max(y0, min(height, int(round(bottom))))
            if y1 <= y0:
                return False
            crop = image.crop((0, y0, width, y1))
            rgb_crop = crop.convert("RGB")
            # Ook een bijna-witte gekleurde pixel is beeldinhoud. Gebruik
            # daarom dezelfde exacte RGB-definitie als bij de grenscontrole
            # en niet grijswaarden, die subtiele kleurverschillen afronden.
            has_content = any(value != 255 for value in rgb_crop.tobytes())
            crop.close()
            rgb_crop.close()
            return has_content

        # Vraagfragmenten zijn de ankers. Sorteer ze op hun visuele positie,
        # zodat ook meerdere vragen op dezelfde pagina in leesvolgorde staan.
        questions = [
            {**item, "top": snap_before(item["top"]), "bottom": snap_before(item["bottom"])}
            for item in selections if item.get("type") == "vraag"
        ]
        questions.sort(key=lambda item: (item["top"], item["bottom"]))

        cleaned_questions: list[dict[str, Any]] = []
        for index, question in enumerate(questions):
            next_top = questions[index + 1]["top"] if index + 1 < len(questions) else None

            # Gebruik voor iedere vraag behalve de laatste de laatste zuiver
            # witte rij vóór de volgende goedgekeurde vraagstart. De eerdere
            # detector kan een witregel midden in een vraag hebben aangezien
            # voor een fragmentgrens. Die voorspelling wordt daarom niet als
            # ondergrens vertrouwd: alle inhoud tot de volgende vraagstart
            # blijft behouden. Eventuele context in dit tussenstuk kan de
            # docent daarna expliciet afsplitsen in de fragmenteditor.
            if next_top is not None:
                question["bottom"] = next_top
            else:
                # De laatste vraag loopt door tot de laatste volledig witte
                # rij in de lange afbeelding. Een interne witregel in de
                # laatste vraag mag dus evenmin als eindgrens worden gebruikt.
                question["bottom"] = white_row_ranges[-1][1]

            if question["bottom"] <= question["top"]:
                number = question.get("question_numbers", ["?"])[0]
                following_number = (
                    questions[index + 1].get("question_numbers", ["?"])[0]
                    if index + 1 < len(questions) else "het einde van het document"
                )
                raise ValueError(
                    f"Tussen vraag {number} en {following_number} is geen "
                    "volledig zuiver witte horizontale grensrij gevonden. "
                    "De fragmenten zijn niet veilig automatisch te scheiden."
                )
            if not has_visible_content(question["top"], question["bottom"]):
                # Een geaccepteerde vraagstart zonder zichtbare inhoud mag
                # niet ongemerkt uit de resultaten verdwijnen. Dat zou een
                # onvolledig examen kunnen opleveren zonder waarschuwing.
                number = question.get("question_numbers", ["?"])[0]
                raise ValueError(
                    f"Voor vraag {number} is in het voorgestelde fragment "
                    "geen zichtbare inhoud gevonden. Controleer de vraagstart."
                )
            cleaned_questions.append(question)

        if not cleaned_questions:
            return []

        # Contexten worden opnieuw opgebouwd uit de zichtbare ruimte tussen
        # de nu niet-overlappende vraagfragmenten. De oude contextvoorstellen
        # worden bewust niet hergebruikt: die konden lege witstroken bevatten.
        contexts: list[dict[str, Any]] = []
        first_question = cleaned_questions[0]
        first_top = snap_before(leading_top)
        first_bottom = first_question["top"]
        if first_bottom - first_top >= 12 and has_visible_content(first_top, first_bottom):
            first_number = int(first_question["question_numbers"][0])
            contexts.append({
                "id": f"auto-context-before-{first_number}",
                "type": "context",
                "top": first_top,
                "bottom": first_bottom,
                "question_numbers": [first_number],
                "label": "Automatisch contextvoorstel — zichtbare inhoud vóór de eerste vraag",
                "source": "automatic_leading_context",
            })

        for previous, following in zip(cleaned_questions, cleaned_questions[1:]):
            gap_top = int(previous["bottom"])
            gap_bottom = int(following["top"])
            if gap_bottom - gap_top < 12 or not has_visible_content(gap_top, gap_bottom):
                continue
            following_number = int(following["question_numbers"][0])
            contexts.append({
                "id": f"auto-context-between-{previous['question_numbers'][0]}-{following_number}",
                "type": "context",
                "top": gap_top,
                "bottom": gap_bottom,
                "question_numbers": [following_number],
                "label": "Automatisch contextvoorstel — zichtbare inhoud tussen vraagfragmenten",
                "source": "automatic_inter_question_gap",
            })

        return sorted(
            [*cleaned_questions, *contexts],
            key=lambda item: (item["top"], 0 if item["type"] == "context" else 1),
        )


def _first_visual_break(page: fitz.Page, start_y: float, end_limit: float) -> float | None:
    """Schat de eerste witregel of kadergrens na een vraagstart.

    De tekstregels leveren een witregelindicatie: een duidelijk grotere
    verticale afstand dan de normale regelafstand markeert het einde van een
    tekstblok. Daarnaast worden zichtbare rechthoekige kaders onderzocht.
    Dit is bewust een voorstel; de docent kan de blauwe grenslijn verslepen.
    """
    lines: list[tuple[float, float]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            bbox = line.get("bbox")
            if text and bbox and start_y <= float(bbox[1]) < end_limit:
                lines.append((float(bbox[1]), float(bbox[3])))
    lines.sort()
    blank_break = None
    if len(lines) >= 2:
        heights = [bottom - top for top, bottom in lines]
        typical_height = sorted(heights)[len(heights) // 2]
        for previous, following in zip(lines, lines[1:]):
            gap = following[0] - previous[1]
            # Kleine interlinie-variaties zijn geen witregel. Een duidelijke
            # extra regelhoogte is dat meestal wel.
            # Gebruik dezelfde conservatieve witregelgrens als de stitchsegmentatie.
            # Zo wordt een normale regelafstand niet als vraaggrens gezien.
            if gap >= max(14.0, typical_height * 1.6):
                blank_break = previous[1] + 2.0
                break
    frame_break = None
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if not rect or rect.width < page.rect.width * 0.22 or rect.height < 8:
            continue
        if rect.y0 >= start_y and rect.y1 < end_limit:
            if frame_break is None or rect.y1 < frame_break:
                frame_break = float(rect.y1) + 2.0
    options = [value for value in (blank_break, frame_break) if value is not None]
    return min(options) if options else None


def generate_question_fragments(
    pdf_path: str | Path,
    accepted_starts: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    document_type: str = "opgaven",
    render_scale: float = 1.5,
    margin_points: float = 10.0,
    boundary_overrides: dict[int, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Maak per geaccepteerde hoofdvraag een reeks pagina-afbeeldingen.

    De eerste pagina begint bij de y-coördinaat van de vraagstart. De laatste
    pagina eindigt vlak vóór de volgende hoofdvraag. Tussenliggende pagina's
    worden volledig opgenomen. De horizontale breedte blijft de volledige
    pagina zodat afbeeldingen, kolommen en antwoordopties niet verloren gaan.
    """
    if not accepted_starts:
        raise ValueError("Er zijn geen goedgekeurde vraagstarts om fragmenten te maken.")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    starts = sorted(accepted_starts, key=lambda item: (item["page_index"], item["pdf_bbox"][1], item["pdf_bbox"][0]))
    proposals: list[dict[str, Any]] = []
    # Bewaarde grenzen worden per hoofdvraag opgezocht. Ze veranderen alleen
    # de afgeleide uitsnede; de bron-PDF en de goedgekeurde vraagstart blijven
    # ongewijzigd. Een ontbrekende override betekent: automatische grens.
    boundary_overrides = boundary_overrides or {}

    with fitz.open(pdf_path) as pdf:
        # Bij CV's verwijderen we alleen aantoonbaar herhaalde kop-/voettekst.
        # De opgaven en uitwerkbijlage blijven ongewijzigd gerenderd.
        marginal_boxes = _repeated_marginal_boxes(pdf) if document_type == "correctievoorschrift" else [[] for _ in pdf]
        # Correctievoorschriften bevatten na het beoordelingsmodel vaak nog
        # administratieve instructies en bronvermeldingen. Die horen niet bij
        # het antwoord van de laatste examenvraag. Als zo'n afsluitende sectie
        # herkenbaar is, eindigt het laatste CV-fragment op de pagina ervoor.
        cv_content_end_page = pdf.page_count - 1
        if document_type == "correctievoorschrift":
            for page_index, page in enumerate(pdf):
                page_text = page.get_text("text").casefold()
                if re.search(r"(?m)^\s*5\s+aanleveren scores\b", page_text):
                    cv_content_end_page = max(0, page_index - 1)
                    break
        # Verwijder alleen oude gegenereerde PNG's in deze eigen werkmap.
        # Bronbestanden staan elders en worden nooit gewijzigd of verwijderd.
        for old_file in destination.glob("question-*.png"):
            old_file.unlink()

        for index, start in enumerate(starts):
            next_start = starts[index + 1] if index + 1 < len(starts) else None
            first_page = int(start["page_index"])
            last_page = int(next_start["page_index"]) if next_start else (
                cv_content_end_page if document_type == "correctievoorschrift" else pdf.page_count - 1
            )
            segments = []
            extracted_text_parts: list[str] = []

            for page_index in range(first_page, last_page + 1):
                page = pdf[page_index]
                page_rect = page.rect
                override = boundary_overrides.get(int(start["question_number"]), {})
                y0 = float(start["pdf_bbox"][1]) - margin_points if page_index == first_page else 0.0
                y1 = (float(next_start["pdf_bbox"][1]) - margin_points
                      if next_start and page_index == last_page else page_rect.height)
                # Neem de volledige ruimte tussen twee goedgekeurde
                # hoofdvraagstarts op. Een tweede automatische witregel- of
                # kaderheuristiek mag de vraag hier niet alsnog afkappen:
                # zulke witregels kunnen midden in een meerregelige vraag,
                # antwoordoptie of afbeelding voorkomen. Voor de opgaven is
                # de visueel gecontroleerde selectie uit stap 3 leidend; voor
                # andere documenten blijft de volgende goedgekeurde vraagstart
                # de veilige bovengrens. De docent kan die grens daarna zelf
                # verfijnen in de documentgerichte fragmentreview.
                if page_index == first_page and override.get("start_y") is not None:
                    y0 = float(override["start_y"])
                if page_index == last_page and override.get("end_y") is not None:
                    y1 = float(override["end_y"])
                # Bescherm tegen negatieve/lege uitsneden bij afwijkende PDF-layouts.
                y0 = max(0.0, min(y0, page_rect.height))
                y1 = max(y0 + 1.0, min(y1, page_rect.height))
                clip = fitz.Rect(0, y0, page_rect.width, y1)
                # De tekstlaag is uitsluitend een hulpmiddel voor voorstellen.
                # De reviewinterface toont altijd de bijbehorende PDF-afbeelding;
                # tekstherkenning alleen is nooit voldoende om goed te keuren.
                page_text = page.get_text("text", clip=clip).strip()
                if page_text:
                    extracted_text_parts.append(page_text)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale),
                                          clip=clip, alpha=False, annots=True)
                filename = f"question-{index + 1:02d}-{start['question_number']:02d}-page-{page_index + 1:03d}.png"
                target = destination / filename
                pixmap.save(target)
                if document_type == "correctievoorschrift":
                    _mask_marginal_boxes(target, marginal_boxes[page_index], clip,
                                         pixmap.width / clip.width, pixmap.height / clip.height)
                _trim_whitespace(target)
                # De daadwerkelijke hoogte na trimmen is de maat die in de
                # gestitchte afbeelding wordt gebruikt; gebruik dus niet de
                # oorspronkelijke pixmaphoogte voor de sleepberekening.
                with Image.open(target) as rendered_image:
                    rendered_height = rendered_image.height
                segments.append({
                    "page_index": page_index,
                    "page_number": page_index + 1,
                    "filename": filename,
                    "url": f"/api/question-fragment-images/{target.parent.parent.parent.name}/{document_type}/{filename}",
                    "pdf_clip": [round(clip.x0, 2), round(clip.y0, 2),
                                 round(clip.x1, 2), round(clip.y1, 2)],
                    # Bewaar de pixelhoogte vóór het stitchen. Die is nodig
                    # om sleepbewegingen op één samengestelde CV-afbeelding
                    # terug te rekenen naar de eerste en laatste PDF-pagina.
                    "render_height": rendered_height,
                })

            # Het correctievoorschrift wordt per vraag als één verticale
            # afbeelding samengesteld. De bronpaginadelen blijven als interne
            # afgeleiden bestaan voor herleidbaarheid en foutopsporing.
            if document_type == "correctievoorschrift":
                source_segments = list(segments)
                stitched_filename = f"question-{index + 1:02d}-{start['question_number']:02d}-stitched.png"
                stitched_path = destination / stitched_filename
                _stitch_vertical([destination / segment["filename"] for segment in source_segments], stitched_path)
                segments = [{
                    "page_index": first_page,
                    "page_number": first_page + 1,
                    "page_range": [first_page + 1, last_page + 1],
                    "filename": stitched_filename,
                    "url": f"/api/question-fragment-images/{destination.parent.parent.name}/{document_type}/{stitched_filename}",
                    "boundary_info": {
                        "start_clip": source_segments[0]["pdf_clip"],
                        "end_clip": source_segments[-1]["pdf_clip"],
                        "first_height": source_segments[0]["render_height"],
                        "last_height": source_segments[-1]["render_height"],
                        "total_height": sum(item["render_height"] for item in source_segments) + 24 * (len(source_segments) - 1),
                    },
                }]
            else:
                source_segments = list(segments)

            proposals.append({
                "question_number": int(start["question_number"]),
                "start_id": start["id"],
                "first_page": first_page + 1,
                "last_page": last_page + 1,
                "segments": segments,
                "source_segments": source_segments if document_type == "correctievoorschrift" else None,
                "stitched": document_type == "correctievoorschrift",
                "extracted_text": "\n".join(extracted_text_parts),
                "reviewed": False,
            })

    return {"question_count": len(proposals), "questions": proposals,
            "render_scale": render_scale, "margin_points": margin_points}
