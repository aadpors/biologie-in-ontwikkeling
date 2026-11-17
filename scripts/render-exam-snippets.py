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
        statement_bottom = max(statement_top + 2, marker[1] - clip.get("question_margin", 7))
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
    y_end = min((word[1] - 5 for word in following), default=page.rect.height - 25)
    y_end = max(y_end, marker_word[3] + 35)
    # A generous context window from the top of this page prevents clipping
    # introductory text and full-width diagrams. Never narrow the page width.
    rect = fitz.Rect(0, 25, page.rect.width, min(page.rect.height, y_end))
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    return pix, page_index + 1


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
