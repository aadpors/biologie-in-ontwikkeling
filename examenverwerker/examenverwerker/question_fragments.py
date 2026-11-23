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
                        render_scale: float = 1.25, page_gap: int = 28,
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
                with Image.open(page_path) as source:
                    image = source.convert("RGB")
                    # Snij grote lege boven-, onder- en zijmarges weg. De
                    # drempel behoudt ook lichte lijnen, kleine labels en
                    # dunne illustraties die inhoudelijk bij de pagina horen.
                    mask = Image.eval(image.convert("L"), lambda value: 255 if value < 250 else 0)
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
            if gap >= max(8.0, typical_height * 0.85):
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
                # Als de volgende vraag op dezelfde pagina staat, zoeken we
                # binnen de ruimte tussen beide vraagstarts naar de eerste
                # duidelijke witregel of de onderrand van een kader. Dat is
                # een betere beginuitsnede dan standaard alles tot de volgende
                # vraag meenemen. Bij een vraag die doorloopt naar een volgende
                # pagina blijft de hele pagina behouden.
                if page_index == first_page and next_start and first_page == last_page:
                    visual_break = _first_visual_break(page, float(start["pdf_bbox"][1]), y1)
                    if visual_break is not None:
                        y1 = min(y1, visual_break)
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
