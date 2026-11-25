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


def cv_content_end_page(pdf: fitz.Document) -> int:
    """Bepaal de laatste inhoudspagina vóór de echte CV-slotsectie.

    Een inhoudsopgave kan de regel '5 Aanleveren scores' letterlijk noemen.
    De oude tekstzoekactie behandelde zo'n vermelding als het begin van de
    administratieve slotpagina en verwijderde daardoor alle vraagstarts uit
    het beoordelingsmodel. We accepteren de grens daarom alleen wanneer de
    volledige regel als zelfstandige kop in het bovenste deel van de pagina
    staat. De originele PDF blijft uiteraard ongewijzigd.
    """
    for page_index, page in enumerate(pdf):
        page_dict = page.get_text("dict")
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                # Maak de regel op dezelfde manier als de overige CV-koppen:
                # spans worden samengevoegd, waarna alleen de volledige kop
                # mag matchen. Een verwijzing met extra tekst telt niet mee.
                line_text = " ".join(
                    span.get("text", "") for span in line.get("spans", [])
                ).strip()
                bbox = line.get("bbox", [])
                if len(bbox) != 4:
                    continue
                heading_top = float(bbox[1])
                if (
                    heading_top <= page.rect.height * 0.20
                    and re.fullmatch(
                        r"5\s+aanleveren scores",
                        line_text,
                        re.IGNORECASE,
                    )
                ):
                    # De slotsectie begint op deze pagina; de laatste
                    # inhoudspagina is dus de voorgaande pagina.
                    return max(0, page_index - 1)
    # Sommige correctievoorschriften hebben geen afzonderlijke slotsectie.
    # In dat geval blijft het volledige document beschikbaar.
    return max(0, len(pdf) - 1)



def cv_model_start(pdf: fitz.Document) -> tuple[int, float]:
    """Vind de echte start van hoofdstuk 4, het beoordelingsmodel.

    De eerdere pagina's van een correctievoorschrift bevatten onder meer
    toelichting, correctieregels en soms een inhoudsopgave. Die horen niet in
    de fragmentwerkruimte van stap 8. Herken daarom de zelfstandige kop
    '4 Beoordelingsmodel' als volledige tekstregel in het bovenste kwart van
    de pagina. De functie retourneert de nulgebaseerde pagina-index en de
    verticale PDF-coördinaat van de kop.
    """
    candidates: list[tuple[float, int, float]] = []
    for page_index, page in enumerate(pdf):
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = " ".join(
                    span.get("text", "") for span in line.get("spans", [])
                ).strip()
                bbox = line.get("bbox", [])
                if len(bbox) != 4:
                    continue
                top = float(bbox[1])
                if (top <= page.rect.height * 0.25
                        and re.fullmatch(r"4\s+beoordelingsmodel", text, re.IGNORECASE)):
                    # Een inhoudsopgave kan dezelfde regel bevatten. De echte
                    # hoofdstukkop heeft doorgaans een grotere lettergrootte;
                    # bewaar daarom de maximale span-grootte als extra signaal.
                    font_size = max(
                        (float(span.get("size", 0)) for span in line.get("spans", [])),
                        default=0.0,
                    )
                    candidates.append((font_size, page_index, top))
    if candidates:
        # Kies de meest opvallende zelfstandige kop, niet de kleinere
        # verwijzing in de inhoudsopgave.
        _, page_index, top = max(candidates, key=lambda item: (item[0], item[1]))
        return page_index, top
    # Niet ieder correctievoorschrift gebruikt exact deze hoofdstuknummering.
    # Als de kop ontbreekt, laat de volledige PDF beschikbaar in plaats van
    # mogelijk inhoudelijke beoordelingsregels stilzwijgend weg te laten.
    return 0, 0.0


def _trim_whitespace(image_path: Path, *, padding: int = 18) -> None:
    """Verklein alleen verticale witmarges en behoud de volledige paginabreedte.

    De renderclip bepaalt al de inhoudelijke bovengrens en ondergrens. Deze
    tweede stap verwijdert alleen extra witruimte boven en onder de fragment-
    afbeelding. De linker- en rechterrand blijven altijd gelijk aan de
    oorspronkelijke pagina, zodat geen kolommen, figuren of bijschriften
    buiten beeld raken. Een lichte drempel voorkomt dat anti-aliasing of een
    vrijwel witte achtergrond als harde inhoudsgrens wordt behandeld.
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
        # Fragmenten blijven altijd paginabreed. Alleen de verticale
        # witruimte binnen de al bepaalde fragmentclip wordt verkleind.
        # Horizontaal bijsnijden kan anders kolommen, figuren, bijschriften of
        # uitwerkingen aan de linker- of rechterzijde onzichtbaar maken.
        _, top, _, bottom = bbox
        top = max(0, top - padding)
        bottom = min(image.height, bottom + padding)
        image.crop((0, top, image.width, bottom)).save(
            image_path, format="PNG", optimize=True
        )



def _repeated_marginal_boxes(pdf: fitz.Document) -> list[list[list[float]]]:
    """Vind herhaalde marge-elementen zonder losse vraagnummers te wissen.

    Een los getal in de boven- of ondermarge is niet automatisch een
    paginanummer: examen-PDF's kunnen daar ook een vraagnummer plaatsen.
    Daarom verwijderen we numerieke spans alleen als ze op meerdere pagina's
    op vrijwel exact dezelfde relatieve positie terugkeren. Niet-numerieke
    korte kop- en voetteksten worden alleen verwijderd als dezelfde tekst op
    ten minste twee pagina's voorkomt.
    """
    text_occurrences: dict[str, set[int]] = {}
    # Bewaar bij losse getallen óók de waarde en de bronpaginapositie.
    # Alleen dezelfde plaats op meerdere pagina's is onvoldoende bewijs:
    # een vraagnummer kan toevallig op de plaats van een paginanummer staan.
    numeric_positions: dict[
        tuple[float, float], list[tuple[int, int, list[float]]]
    ] = {}
    spans_by_page: list[
        list[tuple[str, list[float], tuple[float, float] | None]]
    ] = [[] for _ in pdf]
    page_number_pattern = re.compile(r"^\d{1,3}$")

    for page_index, page in enumerate(pdf):
        page_width = float(page.rect.width) or 1.0
        page_height = float(page.rect.height) or 1.0
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_spans = [
                    span for span in line.get("spans", [])
                    if str(span.get("text", "")).strip()
                ]
                for span in line_spans:
                    text = " ".join(str(span.get("text", "")).split())
                    bbox = span.get("bbox", [])
                    if not text or len(bbox) != 4:
                        continue
                    coordinates = [float(value) for value in bbox]
                    in_margin = (
                        coordinates[1] <= page_height * 0.06
                        or coordinates[3] >= page_height * 0.88
                    )
                    if not in_margin:
                        continue

                    if page_number_pattern.fullmatch(text):
                        # De relatieve positie vangt kleine verschillen in
                        # fontmetrics en paginagrootte op. De waarde blijft
                        # apart bewaard om een echte paginatellerrij te kunnen
                        # onderscheiden van een vraagnummer op diezelfde plek.
                        center_x = ((coordinates[0] + coordinates[2]) / 2) / page_width
                        center_y = ((coordinates[1] + coordinates[3]) / 2) / page_height
                        position = (round(center_x, 1), round(center_y, 2))
                        spans_by_page[page_index].append((text, coordinates, position))
                        numeric_positions.setdefault(position, []).append(
                            (page_index, int(text), coordinates)
                        )
                        continue

                    key = text.casefold()
                    # Een gemengde span zoals 'Vraag 30 2 / 19' bevat
                    # inhoudelijke tekst en mag nooit als geheel verdwijnen.
                    if (
                        len(key) <= 48
                        and not re.search(r"\b(?:vraag|opgave|antwoord)\s*\d+", key)
                    ):
                        spans_by_page[page_index].append((key, coordinates, None))
                        text_occurrences.setdefault(key, set()).add(page_index)

    repeated_text = {
        key for key, pages in text_occurrences.items() if len(pages) >= 2
    }

    # Een echt paginanummer loopt mee met de bronpaginavolgorde: het verschil
    # tussen het afgedrukte nummer en de nulgebaseerde PDF-pagina-index blijft
    # gelijk (bijvoorbeeld PDF-pagina 1 -> nummer 1, pagina 2 -> nummer 2).
    # We markeren alleen de concrete getallen die zo'n reeks ondersteunen.
    # Een afwijkend getal op dezelfde plek, zoals een vraagnummer 28, blijft
    # daardoor staan en bepaalt ook de ondergrens van de paginacrop.
    repeated_numeric_entries: set[tuple[int, tuple[float, float], int]] = set()
    for position, occurrences in numeric_positions.items():
        offsets: dict[int, set[int]] = {}
        for page_index, number, _coordinates in occurrences:
            offsets.setdefault(number - page_index, set()).add(page_index)
        valid_offsets = {
            offset for offset, pages in offsets.items() if len(pages) >= 2
        }
        for page_index, number, _coordinates in occurrences:
            if number - page_index in valid_offsets:
                repeated_numeric_entries.add((page_index, position, number))

    result: list[list[list[float]]] = []
    for page_index, page_spans in enumerate(spans_by_page):
        page_boxes = []
        for key, coordinates, position in page_spans:
            is_repeated_page_number = (
                position is not None
                and (page_index, position, int(key)) in repeated_numeric_entries
            )
            if is_repeated_page_number or (position is None and key in repeated_text):
                page_boxes.append(coordinates)
        result.append(page_boxes)
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
                        start_page: int = 1,
                        end_page: int | None = None,
                        start_y: float = 0.0) -> dict[str, Any]:
    """Maak één lange, opgeschoonde werkafbeelding van het examen.

    Pagina 1 wordt standaard overgeslagen omdat dit bij opgaven vaak de
    omslag/instructiepagina is. Voor documenten die op pagina 1 beginnen,
    wordt start_page=0 meegegeven. end_page is optioneel en inclusief; hiermee
    kan een CV-strook eindigen vóór de administratieve slotsectie.
    Elke pagina wordt gerenderd en de herhaalde kop-/voettekst wordt gemaskeerd.
    Alleen verticale witmarges worden verkleind: de volledige paginabreedte
    blijft behouden. De pagina's worden daarna verticaal gestitcht. De oorspronkelijke PDF blijft
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
            last_page = len(pdf) - 1 if end_page is None else min(int(end_page), len(pdf) - 1)
            if start_page < 0 or start_page > last_page:
                raise ValueError("De gekozen paginagrens bevat geen renderbare inhoudspagina's.")
            marginal_boxes = _repeated_marginal_boxes(pdf)
            for page_index in range(start_page, last_page + 1):
                page = pdf[page_index]
                pix = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=False)
                page_path = destination.parent / f"_stitch-page-{page_index + 1:03d}.png"
                pix.save(page_path)
                clip = fitz.Rect(0, 0, page.rect.width, page.rect.height)
                _mask_marginal_boxes(page_path, marginal_boxes[page_index], clip,
                                     pix.width / clip.width, pix.height / clip.height)
                # Gebruik de individuele glyph-coördinaten uit rawdict.
                # Een PDF-export kan "Vraag 28  2 / 19  lees verder" als één
                # tekstspan opslaan. De span-box omvat dan óók het vraagnummer.
                # Door de tekst op tekenposities te mappen, maskeren we alleen
                # de herkenbare footer-substrings en blijft de vraagtekst staan.
                footer_boxes: list[list[float]] = []
                footer_patterns = [
                    re.compile(r"\b\d{1,3}\s*/\s*\d{1,3}\b"),
                    re.compile(r"(?i)\blees\s+verder\b"),
                    re.compile(r"(?:►|·){1,3}"),  # PyMuPDF kan de pijl als middot extraheren.
                    re.compile(r"(?i)\b(?:VW|VMBO|HAVO|VWO)[- ]?\d{3,}(?:[- ][\w-]+)*\b"),
                ]
                raw_page = page.get_text("rawdict")
                for block in raw_page.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        chars: list[dict[str, Any]] = []
                        line_text_parts: list[str] = []
                        for span in line.get("spans", []):
                            for char in span.get("chars", []):
                                value = str(char.get("c", ""))
                                if value:
                                    chars.append(char)
                                    line_text_parts.append(value)
                        line_text = "".join(line_text_parts)
                        line_bbox = line.get("bbox", [])
                        if len(line_bbox) != 4 or float(line_bbox[1]) < page.rect.height * 0.85:
                            continue
                        # Markeer alleen de exacte tekens die bij een footerpatroon horen.
                        for pattern in footer_patterns:
                            for match in pattern.finditer(line_text):
                                matched_chars = chars[match.start():match.end()]
                                if matched_chars:
                                    x0 = min(float(char["bbox"][0]) for char in matched_chars)
                                    y0 = min(float(char["bbox"][1]) for char in matched_chars)
                                    x1 = max(float(char["bbox"][2]) for char in matched_chars)
                                    y1 = max(float(char["bbox"][3]) for char in matched_chars)
                                    footer_boxes.append([x0, y0, x1, y1])
                        # Een zelfstandige documentcode mag worden verwijderd.
                        # Een los getal wordt hier nadrukkelijk niet gemaskeerd:
                        # het kan het vraagnummer 28/30 zijn. Echte losse
                        # paginanummers worden herkend via herhaalde positie in
                        # _repeated_marginal_boxes; samengestelde tellers zoals
                        # '2 / 19' worden hierboven teken voor teken verwijderd.
                        stripped = line_text.strip()
                        if re.fullmatch(
                            r"(?:VW|VMBO|HAVO|VWO)[- ]?\d{3,}(?:[- ][\w-]+)*",
                            stripped,
                            re.IGNORECASE,
                        ):
                            footer_boxes.extend([
                                [float(value) for value in char["bbox"]]
                                for char in chars if str(char.get("c", "")).strip()
                            ])
                if footer_boxes:
                    with Image.open(page_path) as rendered:
                        cleaned = rendered.convert("RGB")
                        draw = ImageDraw.Draw(cleaned)
                        scale_x = cleaned.width / page.rect.width
                        scale_y = cleaned.height / page.rect.height
                        for x0, y0, x1, y1 in footer_boxes:
                            draw.rectangle((
                                max(0, int(x0 * scale_x) - 2),
                                max(0, int(y0 * scale_y) - 2),
                                min(cleaned.width, int(x1 * scale_x) + 2),
                                min(cleaned.height, int(y1 * scale_y) + 2),
                            ), fill="white")
                        cleaned.save(page_path, format="PNG", optimize=True)
                with Image.open(page_path) as source:
                    image = source.convert("RGB")
                    # Bij het CV begint de werkstrook midden in het document:
                    # snij op de eerste pagina alles boven de echte kop
                    # '4 Beoordelingsmodel' weg. De offset blijft bewaard in
                    # crop_pixels zodat latere fragmenten exact naar de
                    # oorspronkelijke PDF-coördinaten terug te rekenen zijn.
                    crop_origin_y = (
                        max(0, min(image.height, round(float(start_y) * render_scale)))
                        if page_index == start_page else 0
                    )
                    if crop_origin_y:
                        image = image.crop((0, crop_origin_y, image.width, image.height))

                    # Verwijder daarna alleen de lege verticale marges. De
                    # volledige paginabreedte blijft bewust behouden.
                    mask = Image.eval(image.convert("L"), lambda value: 255 if value < 246 else 0)
                    bbox = mask.getbbox()
                    if bbox:
                        _, top, _, bottom = bbox
                        pad = max(12, int(render_scale * 8))
                        bbox = (0, max(0, top-pad), image.width,
                                min(image.height, bottom+pad))
                        image = image.crop(bbox)
                    else:
                        bbox = (0, 0, image.width, image.height)
                    page_images.append(image.copy())
                    page_meta.append({
                        "page_number": page_index + 1,
                        "source_width": page.rect.width,
                        "source_height": page.rect.height,
                        "crop_pixels": [
                            0, crop_origin_y + bbox[1],
                            image.width, crop_origin_y + bbox[3]
                        ],
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



def _looks_like_context_region(
    pdf: fitz.Document,
    page_metadata: list[dict[str, Any]],
    top: float,
    bottom: float,
    *,
    render_scale: float,
) -> bool:
    """Herken een context aan inhoudelijke tekst- of afbeeldingssignalen.

    Een willekeurige zichtbare tussenruimte is niet automatisch context: het
    kan ook het vervolg of slot van de voorafgaande vraag zijn. Daarom worden
    contexten alleen voorgesteld wanneer de strook expliciete verwijzingen
    naar gedeelde informatie bevat, een zelfstandig tekstblok vormt of een
    substantieel figuurblok met een tekstanker bevat. Bij twijfel blijft de
    inhoud bij de vraag en kan de docent haar handmatig als context markeren.
    """
    cues = re.compile(
        r"\b(?:gebruik de informatie|gebruik de gegevens|gebruik onderstaande|gebruik de tekst|"
        r"lees de tekst|bekijk de afbeelding|onderstaande afbeelding|"
        r"de volgende informatie|de volgende tekst|in de tekst hieronder|"
        r"bij de volgende vragen|voor de volgende vragen|"
        r"een onderzoek naar|bij dit onderzoek|de onderzoekers|"
        r"een experiment|de proefpersonen|in deze situatie|"
        r"de afbeelding hieronder|de tabel hieronder|context)\b",
        re.IGNORECASE,
    )
    for info in page_metadata:
        page_top = float(info.get("top", 0))
        page_bottom = float(info.get("bottom", 0))
        overlap_top = max(float(top), page_top)
        overlap_bottom = min(float(bottom), page_bottom)
        if overlap_bottom - overlap_top < 18:
            continue
        page_number = int(info["page_number"])
        if not 1 <= page_number <= pdf.page_count:
            continue
        page = pdf[page_number - 1]
        crop = info.get("crop_pixels", [0, 0, 0, 0])
        resize_factor = float(info.get("stitched_width", info.get("render_width", 1))) / max(
            1.0, float(info.get("render_width", 1))
        )
        # Zet de strook uit de lange afbeelding terug naar PDF-coördinaten.
        local_top = (overlap_top - page_top) / resize_factor + float(crop[1])
        local_bottom = (overlap_bottom - page_top) / resize_factor + float(crop[1])
        pdf_top = max(0.0, local_top / render_scale)
        pdf_bottom = min(page.rect.height, local_bottom / render_scale)
        if pdf_bottom <= pdf_top:
            continue
        clip = fitz.Rect(0, pdf_top, page.rect.width, pdf_bottom)
        text = page.get_text("text", clip=clip).strip()
        words = re.findall(r"\w+", text, flags=re.UNICODE)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(words) >= 6 and cues.search(text):
            return True
        sentence_count = len(re.findall(r"[.!?](?:\s|$)", text))
        if len(words) >= 8 and len(lines) >= 2 and sentence_count >= 2:
            return True
        # Een figuur kan zelfstandig context zijn; een klein icoon of
        # decoratief plaatje is daarvoor niet voldoende.
        for image_info in page.get_image_info():
            bbox = image_info.get("bbox")
            if not bbox:
                continue
            image_rect = fitz.Rect(bbox)
            overlaps = image_rect.y1 > pdf_top and image_rect.y0 < pdf_bottom
            if (overlaps and image_rect.width >= page.rect.width * 0.22
                    and image_rect.height >= 36 and len(words) >= 5):
                return True
    return False


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
        # De vraagstart is het vaste beginanker. Voor de ondergrens zoeken
        # we de eerste duidelijke visuele scheiding vóór de volgende
        # hoofdvraag. De normalisatiestap controleert vervolgens of ná die
        # scheiding nog zichtbare inhoud staat: zo wordt een lege interne
        # witregel genegeerd, maar een werkelijk contextblok afgesplitst.
        next_start_y = mapped[index + 1][0] if index + 1 < len(mapped) else float(image_height)
        separators_before_next = [
            value for value in separators
            if start_y < value < next_start_y
        ]
        top_boundary = start_y - 8.0
        top = max(page_top, top_boundary)
        bottom_boundary = separators_before_next[0] if separators_before_next else next_start_y
        bottom = min(float(image_height), bottom_boundary)

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

    # Contextfragmenten staan vóór de vragen waarop ze betrekking hebben.
    # Verzamel eerst alle zichtbare tussenruimtes; daarna kan ieder contextblok
    # worden gekoppeld aan de daaropvolgende vraaggroep tot het volgende blok.
    context_selections: list[dict[str, Any]] = []
    ordered_questions = sorted(question_selections, key=lambda item: item["top"])
    context_gaps: list[dict[str, Any]] = []

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
            # Gebruik de herkende vraagstart als scheiding tussen de
            # voorafgaande context en het eerste vraagfragment.
            leading_bottom = max(
                float(first_question["top"]),
                first_start_y - 8.0,
            )
            with fitz.open(pdf_path) as source_pdf:
                leading_is_context = _looks_like_context_region(
                    source_pdf, page_metadata, leading_top, leading_bottom,
                    render_scale=render_scale,
                )
            if leading_bottom - leading_top >= 24 and leading_is_context:
                first_question["top"] = round(leading_bottom, 2)
                context_selections.append({
                    "id": f"auto-context-before-{first_number}",
                    "type": "context",
                    "top": round(leading_top, 2),
                    "bottom": round(leading_bottom, 2),
                    "question_numbers": [first_number],
                    "label": "Automatisch contextvoorstel — inhoud vóór de eerste vragen",
                    "source": "automatic_leading_context",
                })

    with fitz.open(pdf_path) as source_pdf:
        for question_index, question in enumerate(ordered_questions[:-1]):
            following = ordered_questions[question_index + 1]
            gap_top = float(question["bottom"])
            gap_bottom = float(following["top"])
            if gap_bottom - gap_top < 24:
                continue
            # Classificeer een tussenblok pas als context wanneer de oorspronkelijke
            # PDF concrete aanwijzingen voor gedeelde achtergrondinformatie bevat.
            # Anders blijft de inhoud bij de voorafgaande vraag horen.
            is_context = _looks_like_context_region(
                source_pdf, page_metadata, gap_top, gap_bottom,
                render_scale=render_scale,
            )
            if not is_context:
                continue
            context_gaps.append({
                "question_index": question_index,
                "top": round(gap_top, 2),
                "bottom": round(gap_bottom, 2),
                "previous_number": int(question["question_numbers"][0]),
                "following_number": int(following["question_numbers"][0]),
            })

    for gap_index, gap in enumerate(context_gaps):
        next_context_question_index = (
            context_gaps[gap_index + 1]["question_index"]
            if gap_index + 1 < len(context_gaps)
            else len(ordered_questions) - 1
        )
        group = ordered_questions[
            gap["question_index"] + 1 : next_context_question_index + 1
        ]
        numbers = [int(item["question_numbers"][0]) for item in group]
        context_selections.append({
            "id": f"auto-context-between-{gap['previous_number']}-{gap['following_number']}",
            "type": "context",
            "top": gap["top"],
            "bottom": gap["bottom"],
            "question_numbers": numbers or [gap["following_number"]],
            "label": "Automatisch contextvoorstel — inhoud vóór de bijbehorende vragen",
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
    context_candidates_only: bool = False,
) -> list[dict[str, Any]]:
    """Maak automatische vraag/contextvoorstellen visueel sluitend.

    De oudere voorstelgenerator kon vraagfragmenten laten overlappen wanneer
    meerdere vragen op één pagina stonden. Ook maakte hij soms een context van
    alleen witruimte. Deze normalisatie gebruikt de goedgekeurde vraagstarts
    als vaste volgorde en de volledige witte beeldrijen als enige grenslijnen.

    De goedgekeurde vraagstarts bepalen de leesvolgorde; voorgestelde
    visuele scheidingen worden op volledige witte pixelrijen geplaatst. Een
    zichtbaar contextblok tussen twee vraagfragmenten blijft een zelfstandig
    fragment en wordt gekoppeld aan de daaropvolgende vragen tot aan het
    volgende contextblok. Daardoor komt de context niet in de afbeelding van
    de eerste vraag terecht en kan hij wel met meerdere vragen worden gedeeld.
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
        """Kies de onderste rij van de dichtstbijzijnde witte strook vóór inhoud.

        De bovengrens van een fragment moet op de onderste volledig witte
        pixelrij vallen. Ligt het doelpunt midden in een witte strook, dan
        gebruiken we dus de onderkant van die strook en niet een willekeurige
        rij in het midden ervan. Ligt het doelpunt tussen stroken, dan nemen
        we de onderste rij van de dichtstbijzijnde strook erboven.
        """
        target = max(0, int(round(y)))
        preceding = [end for start, end in white_row_ranges if start <= target]
        if preceding:
            containing = [
                end for start, end in white_row_ranges
                if start <= target <= end
            ]
            return int(containing[0] if containing else max(preceding))
        # Aan het begin van de afbeelding kan het doelpunt vóór de eerste
        # bruikbare strook liggen. Gebruik dan de eerste veilige grensrij.
        return int(white_row_ranges[0][1])

    def snap_after(y: float) -> int:
        """Kies de bovenste rij van de dichtstbijzijnde witte strook na inhoud.

        De ondergrens van een fragment moet op de bovenste volledig witte
        pixelrij vallen. Daarmee blijft de volledige laatste inhoudsregel
        behouden, zonder de rest van de witte tussenruimte mee te nemen.
        """
        target = max(0, int(round(y)))
        following = [
            start for start, end in white_row_ranges
            if end >= target
        ]
        if following:
            containing = [
                start for start, end in white_row_ranges
                if start <= target <= end
            ]
            return int(containing[0] if containing else min(following))
        # Aan het einde van de afbeelding gebruiken we de bovenrand van de
        # laatste beschikbare witte strook als veilige terugvalgrens.
        return int(white_row_ranges[-1][0])

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

        def last_content_boundary(top: int, bottom: int) -> int:
            """Plaats de ondergrens direct na de laatste niet-witte beeldrij.

            Zoek binnen het vraagbereik van onder naar boven naar de laatste
            zichtbare pixel. De grens wordt de eerste volledig witte rij
            erna. Zo blijft de laatste tekstregel behouden, maar verdwijnt
            overtollige witruimte onder het antwoordfragment.
            """
            y0 = max(0, min(height, int(top)))
            y1 = max(y0, min(height, int(bottom)))
            if y1 <= y0:
                return int(bottom)
            gray = image.crop((0, y0, width, y1)).convert("L")
            # Laat Pillow de pixelmaskering uitvoeren in plaats van per pixel
            # door Python te itereren; dit blijft efficiënt bij lange examens.
            mask = Image.eval(gray, lambda value: 255 if value < 252 else 0)
            bbox = mask.getbbox()
            gray.close()
            mask.close()
            if not bbox:
                return int(bottom)
            last_content_y = y0 + bbox[3] - 1
            next_white = next(
                (start for start, end in white_row_ranges if start > last_content_y),
                None,
            )
            return int(next_white if next_white is not None else last_content_y + 1)
        # Vraagfragmenten zijn de ankers. Sorteer ze op hun visuele positie,
        # zodat ook meerdere vragen op dezelfde pagina in leesvolgorde staan.
        questions = [
            {**item, "top": snap_before(item["top"]), "bottom": snap_after(item["bottom"])}
            for item in selections if item.get("type") == "vraag"
        ]
        questions.sort(key=lambda item: (item["top"], item["bottom"]))

        cleaned_questions: list[dict[str, Any]] = []
        for index, question in enumerate(questions):
            next_top = questions[index + 1]["top"] if index + 1 < len(questions) else None

            # Gebruik de voorgestelde ondergrens zodra deze na de
            # bovengrens en vóór de volgende vraag ligt. Ook wanneer er geen
            # contextinhoud achter staat, blijft de lijn op de eerste witte
            # rij na de vraag staan; een lege witte strook wordt niet in het
            # vraagfragment opgenomen.
            if next_top is not None:
                proposed_bottom = int(question["bottom"])
                if question["top"] < proposed_bottom < next_top:
                    question["bottom"] = proposed_bottom
                else:
                    # Een overlappende of onbruikbare voorstelgrens mag nooit
                    # over de volgende vraag heen lopen.
                    question["bottom"] = next_top
            else:
                # De laatste vraag eindigt op de bovenste rij van de laatste
                # volledig witte strook na de laatste inhoudsregel.
                question["bottom"] = snap_after(height - 1)

            # Scherp de automatische voorstelgrens aan tot de eerste volledig
            # witte rij na de laatste niet-witte pixel. De volledige breedte
            # wordt onderzocht, zodat ook figuren en rechterkolommen meetellen.
            question["bottom"] = min(
                int(question["bottom"]),
                last_content_boundary(int(question["top"]), int(question["bottom"])),
            )

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
        #
        # Een context staat vóór de vragen waarop hij betrekking heeft. Daarom
        # koppelen we een context aan de daaropvolgende vragen, tot aan het
        # volgende contextblok. Zo kan één context bijvoorbeeld bij vraag 38
        # én 39 horen, zonder dat de contextafbeelding onderdeel wordt van
        # vraag 38 zelf.
        contexts: list[dict[str, Any]] = []
        context_gaps: list[dict[str, Any]] = []
        # Wanneer de PDF-analyse contextkandidaten heeft aangeleverd, zijn die
        # kandidaten leidend. Zonder zo'n kandidaat wordt de ruimte aan de
        # vorige vraag toegevoegd in plaats van automatisch context te worden.
        proposed_contexts = [
            item for item in selections if item.get("type") == "context"
        ]

        for question_index, (previous, following) in enumerate(
            zip(cleaned_questions, cleaned_questions[1:])
        ):
            gap_top = int(previous["bottom"])
            gap_bottom = int(following["top"])
            if gap_bottom - gap_top < 12 or not has_visible_content(gap_top, gap_bottom):
                continue
            if context_candidates_only:
                has_candidate = any(
                    min(gap_bottom, float(candidate.get("bottom", 0)))
                    - max(gap_top, float(candidate.get("top", 0))) >= 12
                    for candidate in proposed_contexts
                )
                if not has_candidate:
                    # Dit is geen betrouwbaar herkend contextblok. Neem de
                    # tussenliggende inhoud op in de voorafgaande vraag zodat
                    # vraagtekst nooit ongemerkt uit de fragmenten verdwijnt.
                    previous["bottom"] = gap_bottom
                    continue

            # Leg eerst alleen de fysieke positie van het contextblok vast.
            # De vraagkoppeling wordt pas bepaald nadat alle contextblokken
            # bekend zijn, zodat de volgende contextgrens de gedeelde groep
            # vragen betrouwbaar kan afbakenen.
            context_gaps.append({
                "question_index": question_index,
                "top": gap_top,
                "bottom": gap_bottom,
                "previous_number": int(previous["question_numbers"][0]),
                "following_number": int(following["question_numbers"][0]),
            })

        # Context vóór de eerste vraag hoort bij de eerste reeks vragen tot
        # aan het eerstvolgende contextblok. Daardoor kan ook een voorblad-
        # of inleidend contextfragment aan meerdere vragen gekoppeld worden.
        first_question = cleaned_questions[0]
        first_top = snap_before(leading_top)
        first_bottom = first_question["top"]
        leading_context_detected = (
            not context_candidates_only or any(
                min(first_bottom, float(candidate.get("bottom", 0)))
                - max(first_top, float(candidate.get("top", 0))) >= 12
                for candidate in proposed_contexts
            )
        )
        if first_bottom - first_top >= 12 and has_visible_content(first_top, first_bottom) and leading_context_detected:
            first_group_end = (
                context_gaps[0]["question_index"] + 1
                if context_gaps else len(cleaned_questions)
            )
            first_group_numbers = [
                int(item["question_numbers"][0])
                for item in cleaned_questions[:first_group_end]
            ]
            contexts.append({
                "id": f"auto-context-before-{first_group_numbers[0]}",
                "type": "context",
                "top": first_top,
                "bottom": first_bottom,
                "question_numbers": first_group_numbers,
                "label": "Automatisch contextvoorstel — zichtbare inhoud vóór de eerste vragen",
                "source": "automatic_leading_context",
            })
        elif first_bottom - first_top >= 12 and has_visible_content(first_top, first_bottom):
            # De ruimte vóór de eerste vraag bevat geen contextsignalen; houd
            # deze inhoud daarom bij de eerste vraag in plaats van haar weg te laten.
            first_question["top"] = first_top

        # Een context tussen vraag A en vraag B hoort bij B en de vragen
        # daarna, zolang er geen nieuw contextblok verschijnt. De volgende
        # contextgrens bepaalt dus het einde van de gedeelde contextgroep.
        for gap_index, gap in enumerate(context_gaps):
            next_context_question_index = (
                context_gaps[gap_index + 1]["question_index"]
                if gap_index + 1 < len(context_gaps)
                else len(cleaned_questions) - 1
            )
            group = cleaned_questions[
                gap["question_index"] + 1 : next_context_question_index + 1
            ]
            question_numbers = [
                int(item["question_numbers"][0]) for item in group
            ]
            if not question_numbers:
                question_numbers = [gap["following_number"]]

            contexts.append({
                "id": f"auto-context-between-{gap['previous_number']}-{gap['following_number']}",
                "type": "context",
                "top": gap["top"],
                "bottom": gap["bottom"],
                "question_numbers": question_numbers,
                "label": "Automatisch contextvoorstel — inhoud vóór de bijbehorende vragen",
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
        # Gebruik exact dezelfde herkenning als de API voor de vraagstarts.
        # Zo kan stap 8 geen andere paginagrens hanteren dan stap 7 en wordt
        # een verwijzing in de inhoudsopgave niet aangezien voor de echte
        # administratieve slotsectie.
        cv_last_content_page = (
            cv_content_end_page(pdf)
            if document_type == "correctievoorschrift"
            else pdf.page_count - 1
        )
        # Verwijder alleen oude gegenereerde PNG's in deze eigen werkmap.
        # Bronbestanden staan elders en worden nooit gewijzigd of verwijderd.
        for old_file in destination.glob("question-*.png"):
            old_file.unlink()

        for index, start in enumerate(starts):
            next_start = starts[index + 1] if index + 1 < len(starts) else None
            first_page = int(start["page_index"])
            last_page = int(next_start["page_index"]) if next_start else (
                cv_last_content_page
            )
            segments = []
            extracted_text_parts: list[str] = []

            # Een CV-vraagstart mag nooit buiten het afgebakende
            # beoordelingsmodel vallen. Als een start door een verouderde
            # review of een afwijkende slotsectie toch ná de laatste
            # inhoudspagina staat, stop dan met een gerichte validatiefout.
            # Zo bereikt een lege lijst nooit de afbeeldingsstitcher.
            if first_page > last_page:
                raise ValueError(
                    f"CV-vraag {start['question_number']} begint na de laatste "
                    "pagina van het beoordelingsmodel. Controleer de vraagstart "
                    "en de grens van de administratieve slotsectie."
                )

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
