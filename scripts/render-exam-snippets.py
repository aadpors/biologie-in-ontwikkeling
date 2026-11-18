import json
import re
from pathlib import Path

import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "exam-snippets.json"
OUT = ROOT / "exam-snippets"
OUT.mkdir(exist_ok=True)


def question_number_from_filename(filename):
    match = re.search(r"question-[a-z]+\d{2}t\d-(\d+)\.jpg$", filename)
    return int(match.group(1)) if match else None


def question_marker_words(page, number):
    words = page.get_text("words", sort=True)
    found = []
    for index, word in enumerate(words):
        if word[4].strip(".,:") != str(number) or word[0] > 125:
            continue
        # In these exam PDFs the printed question number is preceded on the
        # same baseline by a score marker such as "1p" or "2p". This avoids
        # confusing numbered lists/figure labels with question numbers.
        previous = words[index - 1] if index else None
        following = words[index + 1] if index + 1 < len(words) else None
        # PyMuPDF can split a printed number such as "36" into adjacent
        # character tokens "3" and "6". Reject a partial numeric token.
        if following and following[4].isdigit() and abs(following[1] - word[1]) < 4 and following[0] <= word[2] + 3:
            continue
        if previous and re.fullmatch(r"\d+p", previous[4].strip().lower()) and abs(previous[1] - word[1]) < 4:
            found.append(word)
    return found


def find_question_page(doc, number, preferred_page):
    matches = []
    for page_index, page in enumerate(doc):
        if question_marker_words(page, number):
            matches.append((page_index, page))
    if not matches:
        raise ValueError(
            f"Scored question marker {number} not found in PDF; "
            "refusing to publish a potentially mislabelled crop."
        )
    preferred = preferred_page - 1
    for page_index, page in matches:
        if page_index == preferred:
            return page_index, page
    if len(matches) == 1:
        return matches[0]
    raise ValueError(
        f"Question {number} appears on multiple pages "
        f"{[i + 1 for i, _ in matches]}; refusing ambiguous crop."
    )

def render_shared_context(doc, clip, scale):
    # Join the full-width end of page 8 and the continuation on page 9.
    question_number = clip["through_question"]
    question_page_index, question_page = find_question_page(doc, question_number, clip["through_page"])
    marker = min(question_marker_words(question_page, question_number), key=lambda word: word[1])
    first_page = doc[clip["page"] - 1]
    matrix = fitz.Matrix(scale, scale)
    first_rect = fitz.Rect(0, clip.get("top", 25), first_page.rect.width, first_page.rect.height - clip.get("bottom_margin", 25))
    first_pix = first_page.get_pixmap(matrix=matrix, clip=first_rect, alpha=False)
    first = Image.frombytes("RGB", (first_pix.width, first_pix.height), first_pix.samples)

    # The shared hippopotamus introduction belongs to questions 14–18, but
    # the statements immediately before question 14 belong to question 14
    # only. Keep the shared image clean and save those statements separately.
    continuation_top = clip.get("continuation_top", 25)
    statement_hits = question_page.search_for(clip.get("question_context_anchor", "Hieronder staan uitspraken over de populatiegroei"))
    if statement_hits:
        statement_top = max(0, min(rect.y0 for rect in statement_hits) - 5)
        statement_bottom = max(statement_top + 2, marker[1] - 2)  # Preserve descenders in the final statement line.
        statement_rect = fitz.Rect(0, statement_top, question_page.rect.width, statement_bottom)
        statement_pix = question_page.get_pixmap(matrix=matrix, clip=statement_rect, alpha=False)
        statement_image = Image.frombytes("RGB", (statement_pix.width, statement_pix.height), statement_pix.samples)
        statement_image.save(OUT / clip.get("question_context_output", "vw25-t1-hippo-q14-context.jpg"), quality=94)

    # Do not append the question-14 statements to the shared context image.
    return first, question_page_index + 1


def render_question(doc, clip, scale):
    number = question_number_from_filename(clip["output"])
    if number is None:
        if clip.get("through_question"):
            return render_shared_context(doc, clip, scale)
        page = doc[clip["page"] - 1]
        if clip.get("from_anchor") and clip.get("before_question"):
            anchor_hits = page.search_for(clip["from_anchor"])
            markers = question_marker_words(page, clip["before_question"])
            if not anchor_hits or not markers:
                raise ValueError(
                    f"Could not isolate question-specific context for question "
                    f"{clip['before_question']}: {clip['from_anchor']!r}"
                )
            top = max(0, min(rect.y0 for rect in anchor_hits) - 5)
            marker = min(markers, key=lambda word: word[1])
            bottom = marker[1] - 2
            if bottom <= top + 2:
                raise ValueError(f"Empty context crop before question {clip['before_question']}")
            rect = fitz.Rect(0, top, page.rect.width, bottom)
            return page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False), clip["page"]
        configured = fitz.Rect(*clip["rect"])
        rect = fitz.Rect(0, configured.y0, page.rect.width, configured.y1)
        return page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False), clip["page"]

    page_index, page = find_question_page(doc, number, clip["page"])
    words = page.get_text("words", sort=True)
    # Find the question-number token and the question's final line. The crop
    # retains full page width and all material above the question (its context,
    # tables and figures), but ends before the next numbered question marker.
    number_words = question_marker_words(page, number)
    if not number_words:
        raise ValueError(f"Question {number}: text marker found but no word bbox")
    # Use the first occurrence after the configured page preference when unique.
    marker_word = min(number_words, key=lambda word: word[1])
    y_question = marker_word[1]
    following = [
        word for word in words
        if word[1] > y_question + 12
        and re.fullmatch(r"\d{1,2}", word[4].strip(".,:"))
        and word[0] < page.rect.width * 0.35
    ]
    y_end = min((word[1] - 2 for word in following), default=page.rect.height - 25)
    y_end = max(y_end, marker_word[3] + 9)
    # A generous context window from the top of this page prevents clipping
    # introductory text and full-width diagrams. Never narrow the page width.
    rect = fitz.Rect(0, 25, page.rect.width, min(page.rect.height, y_end))
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    return pix, page_index + 1


# Havo 2025-I q26: the sentence "Hieronder staan drie uitspraken" is
# the question introduction, not part of the shared Bajau context. Split the
# source page at that exact printed boundary so the two images reflect the
# original exam structure.
def render_havo_2025_i_q26():
    pdf = ROOT / "examens" / "ha-1018-a-25-1-o.pdf"
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    with fitz.open(pdf) as doc:
        page = doc[11]  # printed page 12
        context_top = page.search_for("De Bajau")
        context_end = page.search_for("ontstaat, en kan zo verdrinken.")
        question_top = page.search_for("Hieronder staan drie uitspraken.")
        question_end = page.search_for("bijbehorende uitspraak juist of onjuist is.")
        if not all((context_top, context_end, question_top, question_end)):
            raise ValueError(
                "Havo 2025-I q26: missing exact source boundary anchor; "
                "refusing to publish incorrectly divided context/question images."
            )
        scale = fitz.Matrix(1.8, 1.8)
        def save_crop(top, bottom, filename):
            rect = fitz.Rect(0, max(0, top), page.rect.width, min(page.rect.height, bottom))
            if rect.height <= 2:
                raise ValueError(f"Havo 2025-I q26: invalid crop bounds for {filename}")
            pix = page.get_pixmap(matrix=scale, clip=rect, alpha=False)
            pix.save(OUT / filename)
        # The two source lines are adjacent in the printed exam. Use the
        # whitespace midpoint between their text boxes as one shared boundary;
        # independent padding on both crops caused a false overlap and stopped
        # the entire 2024–2026 regeneration.
        context_text_bottom = max(r.y1 for r in context_end)
        question_text_top = min(r.y0 for r in question_top)
        if question_text_top <= context_text_bottom:
            raise ValueError(
                "Havo 2025-I q26: source text boxes themselves overlap; "
                "refusing to publish ambiguous context/question crops."
            )
        boundary = (context_text_bottom + question_text_top) / 2
        context_bottom = boundary
        question_start = boundary
        question_bottom = max(r.y1 for r in question_end) + 9
        save_crop(min(r.y0 for r in context_top) - 5, context_bottom,
                  "context-ha25t1-q26-complete.jpg")
        save_crop(question_start, question_bottom,
                  "question-ha25t1-26-only.jpg")
    # Keep the manifest paths stable; the open-question record already points
    # to these two images. The primary fallback should point to the question
    # crop rather than an obsolete combined crop.
    open_path = ROOT / "exam-open.json"
    records = json.loads(open_path.read_text(encoding="utf-8"))
    target = next((r for r in records if r.get("id") == "ha25t1-open-26"), None)
    if target is None:
        raise ValueError("Havo 2025-I q26: open-question record missing")
    target["image"] = "exam-snippets/question-ha25t1-26-only.jpg"
    target["images"] = [
        "exam-snippets/context-ha25t1-q26-complete.jpg",
        "exam-snippets/question-ha25t1-26-only.jpg",
    ]
    open_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Havo 2025-I q26: context/question boundary corrected")


render_havo_2025_i_q26()

items = json.loads(MANIFEST.read_text(encoding="utf-8"))
for item in items:
    source = ROOT / item["pdf"]
    if not source.exists():
        raise FileNotFoundError(source)
    with fitz.open(source) as doc:
        scale = item.get("scale", 1.8)
        for clip in item["clips"]:
            pix, actual_page = render_question(doc, clip, scale)
            output = OUT / clip["output"]
            if isinstance(pix, Image.Image):
                pix.save(output, quality=94)
            else:
                pix.save(output)
            print(f"Rendered {clip['output']} from {item['pdf']} page {actual_page}")


# Havo 2025-I q34 shares the genetic/Bajau information framework with q33.
# The generic page crop incorrectly included q33 above q34. Reuse the exact
# q33 context crop and render q34 from its own scored question marker only.
def render_havo_2025_i_q34():
    pdf = ROOT / "examens" / "ha-1018-a-25-1-o.pdf"
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    output = "question-ha25t1-34-only.jpg"
    with fitz.open(pdf) as doc:
        page_index, page = find_question_page(doc, 34, 14)
        markers = question_marker_words(page, 34)
        if not markers:
            raise ValueError("Havo 2025-I q34: scored question marker missing")
        marker = min(markers, key=lambda word: word[1])
        words = page.get_text("words", sort=True)
        following = [
            word for word in words
            if word[1] > marker[1] + 12
            and re.fullmatch(r"\d{1,2}", word[4].strip(".,:"))
            and word[0] < page.rect.width * 0.35
        ]
        bottom = min((word[1] - 2 for word in following), default=page.rect.height - 25)
        bottom = max(bottom, marker[3] + 9)
        rect = fitz.Rect(0, max(0, marker[1] - 4), page.rect.width, min(page.rect.height, bottom))
        if rect.height <= 2:
            raise ValueError("Havo 2025-I q34: invalid question-only crop")
        pix = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), clip=rect, alpha=False)
        pix.save(OUT / output)
        print(f"Rendered {output} from {pdf.name} page {page_index + 1}")

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
    q34["image"] = "exam-snippets/" + output
    q34["images"] = [
        "exam-snippets/context-ha25t1-q33-complete.jpg",
        "exam-snippets/" + output,
    ]
    open_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    context_path = ROOT / "exam-contexts.json"
    context_records = json.loads(context_path.read_text(encoding="utf-8"))
    context_q34 = next((
        record for record in context_records
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
        "exam-snippets/" + output,
    ]
    context_path.write_text(json.dumps(context_records, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")


render_havo_2025_i_q34()
