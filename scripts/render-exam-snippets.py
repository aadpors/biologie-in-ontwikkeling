import json
import re
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "exam-snippets.json"
OUT = ROOT / "exam-snippets"
OUT.mkdir(exist_ok=True)


def question_number_from_filename(filename):
    match = re.search(r"question-[a-z]+\d{2}t\d-(\d+)\.jpg$", filename)
    return int(match.group(1)) if match else None


def find_question_page(doc, number, preferred_page):
    # Locate the printed question number in the PDF text itself. Manifest page
    # numbers are only hints: PDFs can contain cover pages or shifted numbering.
    marker = re.compile(
        rf"^\s*(?:(?:\d+\s*p)\s*)?{number}\s+(?=[A-ZÀ-Ý(])",
        re.MULTILINE,
    )
    matches = []
    for page_index, page in enumerate(doc):
        text = page.get_text("text", sort=True)
        if marker.search(text):
            matches.append((page_index, page))
    if not matches:
        raise ValueError(
            f"Question {number} not found in PDF text for any page; "
            "refusing to publish a potentially mislabelled crop."
        )
    if len(matches) == 1:
        return matches[0]
    # Prefer the configured page only when it is one of the pages containing
    # the exact printed marker. Otherwise stop rather than guessing.
    preferred = preferred_page - 1
    for page_index, page in matches:
        if page_index == preferred:
            return page_index, page
    raise ValueError(
        f"Question {number} appears on multiple pages "
        f"{[i + 1 for i, _ in matches]}; manifest page {preferred_page} "
        "does not disambiguate them."
    )


def render_question(doc, clip, scale):
    number = question_number_from_filename(clip["output"])
    if number is None:
        # Shared context-only images retain their explicitly configured crop.
        page = doc[clip["page"] - 1]
        configured = fitz.Rect(*clip["rect"])
        rect = fitz.Rect(0, configured.y0, page.rect.width, configured.y1)
        return page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False), clip["page"]

    page_index, page = find_question_page(doc, number, clip["page"])
    words = page.get_text("words", sort=True)
    # Find the question-number token and the question's final line. The crop
    # retains full page width and all material above the question (its context,
    # tables and figures), but ends before the next numbered question marker.
    number_words = [
        word for word in words
        if word[4].strip(".,:") == str(number)
        and word[1] > 20
    ]
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
            pix.save(output)
            print(f"Rendered {clip['output']} from {item['pdf']} page {actual_page}")
