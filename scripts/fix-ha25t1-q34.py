import json
import re
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "exam-snippets"
PDF = ROOT / "examens" / "ha-1018-a-25-1-o.pdf"


def question_marker_words(page, number):
    words = page.get_text("words", sort=True)
    found = []
    for index, word in enumerate(words):
        if word[4].strip(".,:") != str(number) or word[0] > 125:
            continue
        previous = words[index - 1] if index else None
        following = words[index + 1] if index + 1 < len(words) else None
        if following and following[4].isdigit() and abs(following[1] - word[1]) < 4 and following[0] <= word[2] + 3:
            continue
        if previous and re.fullmatch(r"\d+p", previous[4].strip().lower()) and abs(previous[1] - word[1]) < 4:
            found.append(word)
    return found


def main():
    if not PDF.is_file():
        raise FileNotFoundError(PDF)
    OUT.mkdir(exist_ok=True)
    with fitz.open(PDF) as doc:
        matches = [
            (i, page, question_marker_words(page, 34))
            for i, page in enumerate(doc)
            if question_marker_words(page, 34)
        ]
        preferred = [item for item in matches if item[0] == 13]
        if preferred:
            page_index, page, markers = preferred[0]
        elif len(matches) == 1:
            page_index, page, markers = matches[0]
        else:
            raise ValueError(f"Havo 2025-I q34: scored marker ambiguous: {[i + 1 for i, _, _ in matches]}")
        marker = min(markers, key=lambda word: word[1])
        # Use the final printed word of q34 as the lower boundary. There is
        # no following question on this page, so falling back to page height
        # included the footer and a large empty area in the published image.
        final_words = [
            word for word in page.get_text("words", sort=True)
            if word[4].strip(".,:;!?").lower() == "geleid"
            and word[1] >= marker[1] - 3
        ]
        if not final_words:
            raise ValueError("Havo 2025-I q34: final prompt word 'geleid' not found")
        bottom = max(word[3] for word in final_words) + 9
        top = max(0, marker[1] - 34)
        if bottom <= top + 10 or bottom >= page.rect.height - 35:
            raise ValueError(f"Havo 2025-I q34: implausible crop bounds top={top}, bottom={bottom}")
        crop_rect = fitz.Rect(0, top, page.rect.width, bottom)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), clip=crop_rect, alpha=False)
        pix.save(OUT / "question-ha25t1-34-only.jpg")
        crop_text = page.get_text("text", clip=crop_rect)
        normalized_crop_text = " ".join(crop_text.split())
        if "De onderzoekers vermoeden dat de grotere milt" not in normalized_crop_text or "Beschrijf hoe evolutie" not in normalized_crop_text:
            raise ValueError("Havo 2025-I q34: one or more question lines are missing from crop")
        if "Hieronder staan uitspraken" in crop_text or "mutante allel" in crop_text:
            raise ValueError("Havo 2025-I q34: q33 text leaked into q34 crop")
        if "lees verder" in crop_text.lower() or "14 / 20" in crop_text:
            raise ValueError("Havo 2025-I q34: page footer leaked into q34 crop")
        print(f"Rendered and text-checked q34 crop from page {page_index + 1}")

    open_path = ROOT / "exam-open.json"
    records = json.loads(open_path.read_text(encoding="utf-8"))
    by_id = {record.get("id"): record for record in records}
    q33, q34 = by_id.get("ha25t1-open-33"), by_id.get("ha25t1-open-34")
    if not q33 or not q34:
        raise ValueError("Havo 2025-I q34: q33/q34 data record missing")
    q34["source"] = q33["source"]
    q34["q"] = (
        "De onderzoekers vermoeden dat de grotere milt van de Bajau-mannen "
        "het gevolg is van evolutie.\n"
        "Beschrijf hoe evolutie tot een grotere milt kan hebben geleid."
    )
    q34["image"] = "exam-snippets/question-ha25t1-34-only.jpg"
    q34["images"] = [
        "exam-snippets/context-ha25t1-q33-complete.jpg",
        "exam-snippets/question-ha25t1-34-only.jpg",
    ]
    open_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    contexts_path = ROOT / "exam-contexts.json"
    contexts = json.loads(contexts_path.read_text(encoding="utf-8"))
    context_q34 = next((
        record for record in contexts
        if record.get("level") == "Havo"
        and str(record.get("year")) == "2025"
        and str(record.get("period")) == "1"
        and int(record.get("n", 0)) == 34
    ), None)
    if context_q34 is None:
        raise ValueError("Havo 2025-I q34: context record missing")
    context_q34["image"] = "exam-snippets/context-ha25t1-q33-complete.jpg"
    context_q34["images"] = [
        "exam-snippets/context-ha25t1-q33-complete.jpg",
        "exam-snippets/question-ha25t1-34-only.jpg",
    ]
    contexts_path.write_text(json.dumps(contexts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
