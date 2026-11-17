#!/usr/bin/env python3
"""Rebuild MCQ answer labels/text from original PDF word coordinates.

The source PDF is authoritative. This post-processor replaces malformed text-layer
parsing, while preserving image-only alternatives as explicitly labelled visual choices.
"""
import json
import re
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
MCQ_PATH = ROOT / "exam-mcq.json"
EXAM_DIR = ROOT / "examens"


def page_columns(page, words):
    """Return detected column boundaries, or the full page when it is not two-column."""
    xs = sorted(w[0] for w in words if w[0] < page.rect.width * 0.96)
    if len(xs) < 8:
        return [(0.0, page.rect.width)]
    gaps = [(xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)]
    gap, split = max(gaps, default=(0.0, 0))
    left_count, right_count = split + 1, len(xs) - split - 1
    if gap >= page.rect.width * 0.12 and left_count >= 4 and right_count >= 4:
        split_x = (xs[split] + xs[split + 1]) / 2
        return [(0.0, split_x), (split_x, page.rect.width)]
    return [(0.0, page.rect.width)]


def locate_question_marker(words, number):
    """Find the printed number preceded by a score marker such as '2p'."""
    candidates = []
    for word in words:
        if word[4] != str(number) or word[1] > 770:
            continue
        if any(
            prior[4].lower().endswith("p")
            and prior[0] < word[0]
            and word[0] - prior[2] < 28
            and abs(prior[1] - word[1]) < 5
            for prior in words
        ):
            candidates.append(word)
    return min(candidates, key=lambda w: w[1]) if candidates else None


def line_clusters(words):
    """Group words into visual lines, then into cells separated by a wide gap."""
    lines = []
    for word in sorted(words, key=lambda w: (w[1], w[0])):
        line = next((line for line in lines if abs(line[0][1] - word[1]) < 3), None)
        if line is None:
            lines.append([word])
        else:
            line.append(word)
    cells = []
    for line in lines:
        line.sort(key=lambda w: w[0])
        current = []
        previous = None
        for word in line:
            if current and word[0] - previous[2] > 15:
                cells.append(current)
                current = []
            current.append(word)
            previous = word
        if current:
            cells.append(current)
    return cells


def extract_options(page, number):
    words = page.get_text("words", sort=True)
    marker = locate_question_marker(words, number)
    if marker is None:
        raise ValueError(f"Question {number}: printed question marker not found")
    columns = page_columns(page, words)
    col = next((c for c in columns if c[0] <= marker[0] < c[1]), (0.0, page.rect.width))
    col_left, col_right = col

    # Find the next printed question marker in this same column. This keeps
    # options from a later question/context out of the current answer block.
    next_markers = []
    for word in words:
        if not word[4].isdigit() or not (1 <= int(word[4]) <= 50):
            continue
        if not (col_left <= word[0] < col_right) or word[1] <= marker[1] + 4:
            continue
        if any(
            prior[4].lower().endswith("p")
            and col_left <= prior[0] < col_right
            and prior[0] < word[0]
            and word[0] - prior[2] < 28
            and abs(prior[1] - word[1]) < 5
            for prior in words
        ):
            next_markers.append(word[1])
    block_bottom = min(next_markers) - 3 if next_markers else 770

    labels = [
        w for w in words
        if w[4] in "ABCDEF"
        and col_left <= w[0] < col_right
        and w[1] > marker[1] + 12
        and w[1] < block_bottom
    ]
    labels.sort(key=lambda w: (round(w[1], 1), w[0]))
    runs = []
    for index, word in enumerate(labels):
        if word[4] != "A":
            continue
        run = [word]
        expected = "B"
        for candidate in labels[index + 1:]:
            previous = run[-1]
            follows = (candidate[1] > previous[1] + 4) or (
                abs(candidate[1] - previous[1]) <= 4 and candidate[0] > previous[0]
            )
            if candidate[4] == expected and follows:
                run.append(candidate)
                expected = chr(ord(expected) + 1)
                if expected > "F":
                    break
        if len(run) >= 3:
            runs.append(run)
    if not runs:
        raise ValueError(f"Question {number}: no sequential A-C or longer options found")
    run = min(runs, key=lambda r: (r[0][1], -len(r)))

    result = []
    for index, label in enumerate(run):
        next_label = run[index + 1] if index + 1 < len(run) else None
        same_row_next = next_label is not None and abs(next_label[1] - label[1]) <= 4
        y0 = label[1] - 3
        if same_row_next:
            y1 = label[1] + 24
            x0, x1 = label[2] + 2, next_label[0] - 2
        else:
            y1 = next_label[1] - 3 if next_label is not None else min(block_bottom, label[1] + 27)
            x0, x1 = label[2] + 2, col_right
        option_words = [
            w for w in words
            if x0 <= w[0] < x1 and y0 <= w[1] < y1 and w[1] < block_bottom + 1
        ]
        cells = line_clusters(option_words)
        values = []
        for cell in cells:
            cell.sort(key=lambda w: (w[1], w[0]))
            text = " ".join(w[4] for w in cell).strip()
            if text:
                values.append(text)
        if len(values) == 2 and all(re.fullmatch(r"\d+", value) for value in values):
            text = values[0] + "/" + values[1]
        elif values:
            text = " | ".join(values)
        else:
            text = f"Afbeelding bij optie {label[4]} (zie vraagafbeelding)"
        result.append({"key": label[4], "text": re.sub(r"\s+", " ", text).strip()})
    return result


def main():
    records = json.loads(MCQ_PATH.read_text(encoding="utf-8"))
    docs = {}
    changed = []
    manual_options = {
        "vw24t1-mcq-34": [
            {"key": "A", "text": "0"}, {"key": "B", "text": "1/16"},
            {"key": "C", "text": "1/8"}, {"key": "D", "text": "1/4"},
            {"key": "E", "text": "1/2"},
        ],
        "ha25t2-mcq-7": [
            {"key": "A", "text": "1/4"}, {"key": "B", "text": "1/3"},
            {"key": "C", "text": "1/2"}, {"key": "D", "text": "2/3"},
            {"key": "E", "text": "3/4"},
        ],
        "ha26t1-mcq-18": [
            {"key": "A", "text": "0"}, {"key": "B", "text": "1/4"},
            {"key": "C", "text": "1/2"}, {"key": "D", "text": "3/4"},
            {"key": "E", "text": "1"},
        ],
        "vw25t1-mcq-30": [
            {"key": "A", "text": "C → A"}, {"key": "B", "text": "C → T"},
            {"key": "C", "text": "G → A"}, {"key": "D", "text": "G → T"},
        ],
        "ha26t2-mcq-4": [
            {"key": "A", "text": "A | groter"}, {"key": "B", "text": "A | kleiner"},
            {"key": "C", "text": "(c2 - c1) | groter"}, {"key": "D", "text": "(c2 - c1) | kleiner"},
            {"key": "E", "text": "x | groter"}, {"key": "F", "text": "x | kleiner"},
        ],
        "vw24t2-mcq-39": [
            {"key": "A", "text": "Er worden minder elektronen aangeslagen bij licht met een golflengte van 450 nm."},
            {"key": "B", "text": "Er worden minder elektronen aangeslagen bij licht met een golflengte van 700 nm."},
            {"key": "C", "text": "Fotosysteem II draagt meer bij aan de NADPH-productie dan fotosysteem I."},
            {"key": "D", "text": "Fotosysteem II draagt meer bij aan de ATP-productie dan fotosysteem I."},
        ],
        "vw24t1-mcq-41": [
            {"key": "A", "text": "MHC-I | fagocytose"}, {"key": "B", "text": "MHC-I | lysis"},
            {"key": "C", "text": "MHC-II | fagocytose"}, {"key": "D", "text": "MHC-II | lysis"},
        ],
        "ha24t2-mcq-46": [
            {"key": "A", "text": "de kniepeesreflex"},
            {"key": "B", "text": "de regulatie van de ademhaling"},
            {"key": "C", "text": "de regulatie van de testosteronproductie"},
        ],
        "ha25t1-mcq-46": [
            {"key": "A", "text": "in de regels 1, 2 en 3"},
            {"key": "B", "text": "in de regels 4 en 5"},
            {"key": "C", "text": "in de regels 6, 7 en 8"},
            {"key": "D", "text": "in de regels 9 en 10"},
            {"key": "E", "text": "in de regels 11, 12 en 13"},
        ],
        "ha25t2-mcq-43": [
            {"key": "A", "text": "letter P | plaats 1"}, {"key": "B", "text": "letter P | plaats 2"},
            {"key": "C", "text": "letter Q | plaats 1"}, {"key": "D", "text": "letter Q | plaats 2"},
        ],
    }
    full_page_anchors = {
        "ha25t1-mcq-31": "De milt is onderdeel van het lymfevatenstelsel",
        "ha26t1-mcq-35": "In de evolutionaire stamboom zie je",
        "vw24t2-mcq-36": "Om te bepalen hoe slaap en chromosoomdynamiek samenhangen",
    }

    for record in records:
        pdf_name = Path(record["pdf"]).name
        pdf_path = EXAM_DIR / pdf_name
        if not pdf_path.is_file():
            raise FileNotFoundError(pdf_path)
        if pdf_path not in docs:
            docs[pdf_path] = fitz.open(pdf_path)
        page = docs[pdf_path][int(record["page"]) - 1]
        old = record.get("options", [])
        try:
            new = extract_options(page, int(record["n"]))
        except Exception as exc:
            raise ValueError(f"{record['id']}: {exc}") from exc
        if record["id"] in manual_options:
            new = manual_options[record["id"]]
        if not new:
            raise ValueError(f"{record['id']}: no options extracted")
        if old != new:
            changed.append((record["id"], old, new))
        record["options"] = new

        anchor = full_page_anchors.get(record["id"])
        if anchor:
            hits = page.search_for(anchor)
            if not hits:
                raise ValueError(f"{record['id']}: source crop anchor not found: {anchor}")
            top = max(0, min(hit.y0 for hit in hits) - 5)
            footer = max(1, page.rect.height - 20)
            pix = page.get_pixmap(
                matrix=fitz.Matrix(1.8, 1.8),
                clip=fitz.Rect(0, top, page.rect.width, footer),
                alpha=False,
            )
            crop_name = f"source-complete-{record['id']}.jpg"
            pix.save(ROOT / "exam-snippets" / crop_name)
            image_path = f"exam-snippets/{crop_name}"
            record["image"] = image_path
            record["images"] = [image_path]
            print(f"VOLLEDIGE BRONAFBEELDING {record['id']}: {image_path}")

    for record in records:
        keys = [option["key"] for option in record.get("options", [])]
        if keys != list("ABCDEF"[:len(keys)]) or len(keys) < 3:
            raise ValueError(f"{record['id']}: invalid option sequence {keys}")
        if any("Bekijk optie" in option.get("text", "") for option in record["options"]):
            raise ValueError(f"{record['id']}: temporary option placeholder remains")
        if record.get("correct") and record["correct"] not in keys:
            raise ValueError(f"{record['id']}: correct key {record['correct']} is not an available option")
        for image_path in [record.get("image"), *record.get("images", [])]:
            if image_path and not (ROOT / image_path).is_file():
                raise FileNotFoundError(f"{record['id']}: missing image {image_path}")

    MCQ_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Controle afgerond: {len(records)} meerkeuzevragen gecontroleerd; {len(changed)} optieblokken opnieuw opgebouwd; geen placeholders of ontbrekende afbeeldingen.")
    for qid, old, new in changed:
        print(f"AANGEPAST {qid}: {len(old)} -> {len(new)} opties")
    for doc in docs.values():
        doc.close()


if __name__ == "__main__":
    main()
