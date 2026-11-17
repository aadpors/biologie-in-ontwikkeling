#!/usr/bin/env python3
"""Restore complete source context for open questions with clipped/cross-page figures."""
import json
from pathlib import Path

import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
EXAM_DIR = ROOT / "examens"
SNIPPET_DIR = ROOT / "exam-snippets"
OPEN_PATH = ROOT / "exam-open.json"
CONTEXT_PATH = ROOT / "exam-contexts.json"


def render_region(page, top, bottom):
    pix = page.get_pixmap(
        matrix=fitz.Matrix(1.8, 1.8),
        clip=fitz.Rect(0, max(0, top), page.rect.width, min(page.rect.height, bottom)),
        alpha=False,
    )
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def main():
    open_records = json.loads(OPEN_PATH.read_text(encoding="utf-8"))
    context_records = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    question_text_overrides = {
        "ha24t1-open-40": "In welke volgorde vinden deze processen plaats op de akker zodat uiteindelijk NO3− beschikbaar is voor quinoa? Noteer de vier nummers in de juiste volgorde."
    }
    for record in open_records:
        if record.get("id") in question_text_overrides:
            record["q"] = question_text_overrides[record["id"]]
    docs = {}

    def get_page(filename, page_index):
        path = EXAM_DIR / filename
        if path not in docs:
            docs[path] = fitz.open(path)
        return docs[path][page_index]

    def set_crop(question_id, image):
        name = f"question-complete-{question_id}.jpg"
        image_path = f"exam-snippets/{name}"
        image.save(ROOT / image_path, quality=94)
        for record in open_records:
            if record.get("id") == question_id:
                record["image"] = image_path
                # The complete source crop already contains the context and
                # question. Use it as the sole image so an earlier fallback
                # context crop (which can be blank or incomplete) is not shown.
                record["images"] = [image_path]
        for record in context_records:
            if (
                (question_id == "ha26t2-open-12" and record.get("level") == "Havo"
                 and record.get("year") == "2026" and record.get("period") == "2" and record.get("n") == 12)
                or (question_id == "ha26t1-open-41" and record.get("level") == "Havo"
                    and record.get("year") == "2026" and record.get("period") == "1" and record.get("n") == 41)
                or (question_id == "vw24t2-open-11" and record.get("level") == "Vwo"
                    and record.get("year") == "2024" and record.get("period") == "2" and record.get("n") == 11)
                or (question_id == "vw26t1-open-36" and record.get("level") == "Vwo"
                    and record.get("year") == "2026" and record.get("period") == "1" and record.get("n") == 36)
                or (question_id == "vw26t2-open-38" and record.get("level") == "Vwo"
                    and record.get("year") == "2026" and record.get("period") == "2" and record.get("n") == 38)
                or (question_id == "vw26t1-open-32" and record.get("level") == "Vwo"
                    and record.get("year") == "2026" and record.get("period") == "1" and record.get("n") == 32)
                or (question_id == "ha26t2-open-9" and record.get("level") == "Havo"
                    and record.get("year") == "2026" and record.get("period") == "2" and record.get("n") == 9)
                or (question_id == "vw25t2-open-14" and record.get("level") == "Vwo"
                    and record.get("year") == "2025" and record.get("period") == "2" and record.get("n") == 14)
            ):
                record["image"] = image_path
                # Context cards are merged into the question in the frontend;
                # replace their image list as well, otherwise stale fallback
                # crops can still appear before the complete source image.
                record["images"] = [image_path]
        print(f"Volledige bronuitsnede hersteld: {question_id}")

    # Havo 2026-II q12: include the complete sea-grass photograph, caption and prompt.
    page = get_page("ha-1018-a-26-2-o.pdf", 5)
    top = page.search_for("afbeelding 3")
    end = page.search_for("verspreidingsgebied.")
    if not top or not end:
        raise ValueError("ha26t2-open-12: source anchors missing")
    set_crop(
        "ha26t2-open-12",
        render_region(page, min(x.y0 for x in top) - 5, max(x.y1 for x in end) + 10),
    )

    # Havo 2026-I q41: include all four antibody/macrophage diagrams, not only their labels.
    page = get_page("ha-1018-a-26-1-o.pdf", 19)
    top = page.search_for("De toegediende antistoffen maken")
    end = page.search_for("Welk organel bevat de werkzame enzymen")
    if not top or not end:
        raise ValueError("ha26t1-open-41: source anchors missing")
    set_crop(
        "ha26t1-open-41",
        render_region(page, min(x.y0 for x in top) - 5, min(x.y0 for x in end) - 5),
    )

    # VWO 2024-II q11: its controls are described on the preceding PDF page.
    previous = get_page("vw-1018-a-24-2-o-spr.pdf", 5)
    current = get_page("vw-1018-a-24-2-o-spr.pdf", 6)
    context = previous.search_for("Nicks allergie werd vastgesteld")
    question = current.search_for("Beschrijf met welk doel")
    next_context = current.search_for("Blootstelling aan ambrosiapollen")
    if not context or not question or not next_context:
        raise ValueError("vw24t2-open-11: cross-page source anchors missing")
    first = render_region(previous, min(x.y0 for x in context) - 5, previous.rect.height - 20)
    second = render_region(current, min(x.y0 for x in question) - 3, min(x.y0 for x in next_context) - 4)
    width = max(first.width, second.width)
    combined = Image.new("RGB", (width, first.height + second.height + 16), "white")
    combined.paste(first, (0, 0))
    combined.paste(second, (0, first.height + 16))
    first.close()
    second.close()
    set_crop("vw24t2-open-11", combined)
    combined.close()

    # VWO 2026-I q36: the graph in figure 4 is a drawn graphic and was cut off
    # by the text-only context boundary.
    page = get_page("vw-1018-a-26-1-o.pdf", 14)
    top = page.search_for("Obesitas kan leiden tot ongevoeligheid")
    if not top:
        raise ValueError("vw26t1-open-36: source context anchor missing")
    set_crop(
        "vw26t1-open-36",
        render_region(page, min(x.y0 for x in top) - 5, page.rect.height - 20),
    )

    # VWO 2026-II q38: include the complete population-growth graph and prompt.
    page = get_page("vw-1018-a-26-2-o.pdf", 18)
    top = page.search_for("De onderzoekers concludeerden")
    end = page.search_for("exponentieel verloopt.")
    if not top or not end:
        raise ValueError("vw26t2-open-38: source graph/question anchors missing")
    set_crop(
        "vw26t2-open-38",
        render_region(page, min(x.y0 for x in top) - 5, max(x.y1 for x in end) + 10),
    )

    # VWO 2026-I q32: the CRISPR mechanism diagram (figure 2) was cut at the
    # question boundary even though it is needed to answer the prompt.
    page = get_page("vw-1018-a-26-1-o.pdf", 13)
    top = page.search_for("De onderzoekers brachten met een virus")
    end = page.search_for("Het effect van de beige vetcellen")
    if not top or not end:
        raise ValueError("vw26t1-open-32: source diagram anchors missing")
    set_crop(
        "vw26t1-open-32",
        render_region(page, min(x.y0 for x in top) - 5, min(x.y0 for x in end) - 5),
    )

    # Havo 2026-II q9: include both complete mangrove figures and the prompt.
    page = get_page("ha-1018-a-26-2-o.pdf", 4)
    top = page.search_for("Bon biní na Boneiru")
    end = page.search_for("zuurstofarme omstandigheden.")
    if not top or not end:
        raise ValueError("ha26t2-open-9: source figure/context anchors missing")
    set_crop(
        "ha26t2-open-9",
        render_region(page, min(x.y0 for x in top) - 5, max(x.y1 for x in end) + 10),
    )

    # VWO 2025-II q14: restore the complete oogenesis diagram.
    page = get_page("vw-1018-a-25-2-o.pdf", 6)
    top = page.search_for("Verouderende eicellen")
    end = page.search_for("haploïd zijn.")
    if not top or not end:
        raise ValueError("vw25t2-open-14: source figure/question anchors missing")
    set_crop(
        "vw25t2-open-14",
        render_region(page, min(x.y0 for x in top) - 5, max(x.y1 for x in end) + 10),
    )

    for record in open_records + context_records:
        image_paths = [record.get("image"), *record.get("images", [])]
        for path in image_paths:
            if path and not (ROOT / path).is_file():
                raise FileNotFoundError(f"{record.get('id', record.get('n'))}: missing image {path}")

    OPEN_PATH.write_text(json.dumps(open_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CONTEXT_PATH.write_text(json.dumps(context_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for doc in docs.values():
        doc.close()


if __name__ == "__main__":
    main()
