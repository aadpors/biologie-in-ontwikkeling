import json  # Generate a static, inspectable inventory of MCQ cards.
import re
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "exam-snippets"
OUT.mkdir(exist_ok=True)

EXAMS = [
    ("ha25t1", "Havo", "2025", "1", "examens/ha-1018-a-25-1-o.pdf", "examens/ha-1018-a-25-1-c.pdf"),
    ("vw25t1", "Vwo", "2025", "1", "examens/vw-1018-a-25-1-o.pdf", "examens/vw-1018-a-25-1-c.pdf"),
    ("ha25t2", "Havo", "2025", "2", "examens/ha-1018-a-25-2-o.pdf", "examens/ha-1018-a-25-2-c.pdf"),
    ("vw25t2", "Vwo", "2025", "2", "examens/vw-1018-a-25-2-o.pdf", "examens/vw-1018-a-25-2-c.pdf"),
    ("ha26t1", "Havo", "2026", "1", "examens/ha-1018-a-26-1-o.pdf", "examens/ha-1018-a-26-1-c.pdf"),
    ("vw26t1", "Vwo", "2026", "1", "examens/vw-1018-a-26-1-o.pdf", "examens/vw-1018-a-26-1-c.pdf"),
    ("ha26t2", "Havo", "2026", "2", "examens/ha-1018-a-26-2-o.pdf", "examens/ha-1018-a-26-2-c.pdf"),
    ("vw26t2", "Vwo", "2026", "2", "examens/vw-1018-a-26-2-o.pdf", "examens/vw-1018-a-26-2-c.pdf"),
]

SELECTED_CONTEXTS = {
    ("vw25t1", 14), ("vw25t1", 15), ("vw25t1", 16), ("vw25t1", 17), ("vw25t1", 18),
    ("ha25t1", 1), ("ha25t1", 3), ("ha25t1", 5),
    ("ha26t1", 4), ("ha26t1", 5), ("ha26t1", 7), ("ha26t1", 8), ("ha26t1", 15), ("ha26t1", 16),
    ("vw26t1", 1), ("vw26t1", 2), ("vw26t1", 12), ("vw26t1", 14), ("vw26t1", 16), ("vw26t1", 20),
    ("ha25t2", 3), ("ha25t2", 9),
    ("vw25t2", 6), ("vw25t2", 8),
    ("ha26t2", 3), ("ha26t2", 9),
    ("vw26t2", 14), ("vw26t2", 24),
}

HEADER_RE = re.compile(r"^(?:[HV][AW]-1018-a-\d{2}-\d-o|\d+\s*/\s*\d+|lees verder|einde|vraag\s+antwoord\s+scores|vraag|antwoord|scores)\b", re.I)
MARKER_RE = re.compile(r"^\s*(\d+)\s*p\s+(\d{1,2})(?:\s+|$)", re.I)
NUMBER_RE = re.compile(r"^\s*(\d{1,2})\s*$")
OPTION_RE = re.compile(r"^\s*([A-F])(?:\s+(.+))?\s*$")

def line_records(page):
    records = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            txt = "".join(s.get("text", "") for s in spans).strip()
            if not txt:
                continue
            size = max((s.get("size", 0) for s in spans), default=0)
            bold = any("bold" in s.get("font", "").lower() for s in spans)
            records.append({
                "text": re.sub(r"\s+", " ", txt),
                "bbox": line.get("bbox", [0, 0, 0, 0]),
                "size": size,
                "bold": bold,
            })
    # Detect a genuine two-column page before sorting. A simple top-to-bottom
    # sort interleaves the columns, which can attach an unrelated context or even
    # another question's answer options to the current question.
    if len(records) >= 8:
        xs = sorted(r["bbox"][0] for r in records)
        gaps = [(xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)]
        gap, split = max(gaps, default=(0, 0))
        left_count, right_count = split + 1, len(xs) - split - 1
        if gap >= page.rect.width * 0.12 and left_count >= 4 and right_count >= 4:
            split_x = (xs[split] + xs[split + 1]) / 2
            for record in records:
                record["column"] = 0 if record["bbox"][0] < split_x else 1
            records.sort(key=lambda x: (x["column"], round(x["bbox"][1], 1), x["bbox"][0]))
        else:
            records.sort(key=lambda x: (round(x["bbox"][1], 1), x["bbox"][0]))
    else:
        records.sort(key=lambda x: (round(x["bbox"][1], 1), x["bbox"][0]))
    return records

def find_markers(lines):
    markers = []
    prompt_starts = re.compile(
        r"^(hieronder|wat|welk|welke|waar|wanneer|waarom|hoe|leg|verklaar|beschrijf|noteer|geef|noem|is|zijn|neemt|beoordeel|schrijf|bereken|licht|beredeneer|laat|tot welke|in welk|op welk|op welke|hoeveel|waardoor)",
        re.I,
    )
    point_re = re.compile(r"^\s*(\d+)\s*p\s*$", re.I)

    def prompt_start_before(index):
        for j in range(index - 1, max(index - 16, -1), -1):
            if prompt_starts.match(lines[j]["text"]):
                return j
            if (
                (lines[j]["size"] >= 13 or (lines[j]["bold"] and lines[j]["size"] >= 10.5))
                and len(lines[j]["text"]) < 90
                and not re.match(r"^(afbeelding|tabel|grafiek|legenda)(?:\s+\d+)?$", lines[j]["text"], re.I)
            ):
                break
        return index

    for i, record in enumerate(lines):
        inline = MARKER_RE.match(record["text"])
        if inline:
            inline_prompt = record["text"][inline.end():].strip()
            start = i if inline_prompt else prompt_start_before(i)
            markers.append({
                "line": start, "number_line": i, "points_line": i,
                "number": int(inline.group(2)), "points": int(inline.group(1)),
                "inline_prompt": inline_prompt
            })
            continue

        nmatch = NUMBER_RE.fullmatch(record["text"])
        if not nmatch:
            continue
        number = int(nmatch.group(1))
        if not 1 <= number <= 50:
            continue
        previous = lines[i - 1]["text"] if i else ""
        following = lines[i + 1]["text"] if i + 1 < len(lines) else ""

        # Sometimes the question text comes first, followed by its number and point marker.
        if point_re.match(following):
            pm = point_re.match(following)
            start = i - 1 if (previous.endswith("?") or prompt_starts.match(previous)) else prompt_start_before(i)
            markers.append({"line": start, "number_line": i, "points_line": i + 1, "number": number, "points": int(pm.group(1))})
            continue

        # In other layouts the number precedes the prompt and point marker.
        for offset in range(2, 7):
            j = i + offset
            if j >= len(lines):
                break
            pm = point_re.match(lines[j]["text"])
            if pm:
                prompt = " ".join(x["text"] for x in lines[i + 1:j]).strip()
                if prompt and (prompt_starts.match(prompt) or "?" in prompt):
                    markers.append({"line": i, "number_line": i, "points_line": j, "number": number, "points": int(pm.group(1))})
                break

    unique = []
    seen = set()
    for marker in sorted(markers, key=lambda x: x["line"]):
        if marker["number"] not in seen:
            unique.append(marker)
            seen.add(marker["number"])
    return unique

def parse_options(block_lines):
    options = []
    current = None
    current_lines = 0
    stop_starts = re.compile(r"^(let op|lees verder|einde|bronvermelding|de volgende|om uit te sluiten|fokkers|afbeelding|tijdens|na afloop|hieronder staat|in het onderzoek|de onderzoekers|vervolgens)", re.I)
    for line in block_lines:
        text = line.strip()
        if not text:
            continue
        m = OPTION_RE.match(text)
        if m and m.group(1) in "ABCDEF":
            key, value = m.group(1), (m.group(2) or "").strip()
            if current:
                options.append(current)
            current = {"key": key, "text": value}
            current_lines = 1 if value else 0
        elif current:
            if re.match(r"^\d+\s*p$", text, re.I) or HEADER_RE.match(text):
                break
            if len(options) >= 3 and current["text"] and stop_starts.match(text):
                break
            if current_lines >= 3:
                break
            current["text"] = (current["text"] + " " + text).strip()
            current_lines += 1
    if current:
        options.append(current)
    keys = [o["key"] for o in options]
    if len(keys) >= 3 and keys[0] == "A" and keys == list("ABCDEF"[:len(keys)]):
        return options
    # Labels for image-based answer options may be separate from their diagrams.
    compact = " ".join(block_lines)
    labels = re.search(r"\bA\s+B\s+C\s+D(?:\s+E)?(?:\s+F)?\b", compact)
    if labels:
        return [{"key": k, "text": "Bekijk optie " + k + " in de oorspronkelijke afbeelding"} for k in labels.group(0).split()]
    return []

def clean_context(lines):
    cleaned = []
    for line in lines:
        text = line.strip()
        if not text or HEADER_RE.match(text):
            continue
        if re.fullmatch(r"\d+\s*p", text, re.I) or NUMBER_RE.fullmatch(text):
            continue
        cleaned.append(text)
    return "\n".join(cleaned).strip()

def answer_from_cv(cv_text, qnum):
    # The official CV stores MCQ answers as e.g. "11  B  2".
    line_pattern = re.compile(rf"^\s*{qnum}\s+([A-F])\s+\d+\s*$")
    for line in cv_text.splitlines():
        match = line_pattern.match(line)
        if match:
            return match.group(1).upper()
    # Some layouts put the letter on the line immediately after the number.
    lines = cv_text.splitlines()
    for i, line in enumerate(lines[:-1]):
        if line.strip() == str(qnum):
            match = re.match(r"^\s*([A-F])\s+\d+\s*$", lines[i + 1])
            if match:
                return match.group(1).upper()
    return ""

def extract_exam(prefix, level, year, period, exam_rel, cv_rel):
    exam_path, cv_path = ROOT / exam_rel, ROOT / cv_rel
    if not exam_path.exists() or not cv_path.exists():
        raise FileNotFoundError(f"Missing source file: {exam_path if not exam_path.exists() else cv_path}")
    with fitz.open(cv_path) as cv_doc:
        cv_text = "\n".join(page.get_text("text", sort=True) for page in cv_doc)
    found = []
    contexts = []
    heading_re = re.compile(r"^(?:vraag|antwoord|scores|afbeelding(?:\s+\d+)?|tabel(?:\s+\d+)?|grafiek(?:\s+\d+)?|legenda|lees verder|einde)$", re.I)
    with fitz.open(exam_path) as doc:
        for page_index, page in enumerate(doc):
            # Context is page-local. Never carry text from the preceding PDF page:
            # a new topic can begin at the top of every page, and stale context
            # was the cause of unrelated introductions appearing on later questions.
            lines = line_records(page)
            markers = find_markers(lines)
            if not markers:
                headings = [
                    j for j, line in enumerate(lines)
                    if (line["size"] >= 13 or (line["bold"] and line["size"] >= 10.5))
                    and len(line["text"]) < 90
                    and not HEADER_RE.match(line["text"])
                    and not heading_re.match(line["text"])
                    and not re.match(r"^\d+\s*p", line["text"], re.I)
                ]
                # Pages without questions can contain the start or continuation
                # of a context. It is deliberately not reused on another page:
                # the next page is segmented independently to avoid stale context.
                continue

            previous_ranges = []
            cursor = 0
            for idx, marker in enumerate(markers):
                start = marker["line"]
                end = markers[idx + 1]["line"] if idx + 1 < len(markers) else len(lines)
                headings = [
                    j for j in range(cursor, start)
                    if (lines[j]["size"] >= 13 or (lines[j]["bold"] and lines[j]["size"] >= 10.5))
                    and len(lines[j]["text"]) < 90
                    and not HEADER_RE.match(lines[j]["text"])
                    and not heading_re.match(lines[j]["text"])
                    and not re.match(r"^\d+\s*p", lines[j]["text"], re.I)
                ]
                if headings:
                    cursor = headings[-1]
                    active_context = []
                context_line_indices = [j for j in range(cursor, start) if not any(a <= j < b for a, b in previous_ranges)]
                context_lines = [lines[j]["text"] for j in context_line_indices]
                # Each question gets only the context physically preceding it on
                # this page (plus context continued between questions on this page).
                # Do not append prior-page context: that silently associates unrelated
                # topics with the current question.
                context = clean_context(context_lines)
                context_y0 = max(0, min((lines[j]["bbox"][1] for j in context_line_indices), default=35) - 5)

                # Havo 2025-I question 14 starts a new stem-cell-transplant
                # context on the same page as questions 12 and 13. The generic
                # open-question boundary can consume that paragraph as part of
                # question 13, leaving question 14 without its own context.
                # Anchor this card to the start of its actual context paragraph;
                # keep the full page width and stop at question 14 as usual.
                if (prefix, marker["number"]) == ("ha25t1", 14):
                    anchor = page.search_for("Eileen komt in aanmerking")
                    if anchor:
                        anchor_y = anchor[0].y0
                        context_line_indices = [
                            j for j, line in enumerate(lines)
                            if anchor_y - 1 <= line["bbox"][1] < lines[start]["bbox"][1]
                        ]
                        context = clean_context([lines[j]["text"] for j in context_line_indices])
                        context_y0 = max(0, anchor_y - 5)

                excluded = {marker["number_line"], marker["points_line"]}
                block_text = []
                block_indices = []
                if marker.get("inline_prompt"):
                    block_text.append(marker["inline_prompt"])
                    block_indices.append(marker["number_line"])
                for j in range(start, end):
                    if j not in excluded and not HEADER_RE.match(lines[j]["text"]):
                        block_text.append(lines[j]["text"])
                        block_indices.append(j)

                options = parse_options(block_text)
                first_option = next((i for i, x in enumerate(block_text) if OPTION_RE.match(x.strip())), len(block_text))
                selected_prompt = "\n".join(x for x in block_text[:first_option] if x.strip()).strip()
                if not selected_prompt:
                    selected_prompt = "\n".join(x for x in block_text if x.strip()).strip()

                # Determine where the question itself ends so later context can be
                # carried forward without carrying the previous question into the next card.
                if options and first_option < len(block_text):
                    option_positions = [i for i, x in enumerate(block_text) if OPTION_RE.match(x.strip())]
                    last_option = option_positions[-1]
                    end_pos = last_option
                    previous_bottom = lines[block_indices[last_option]]["bbox"][3]
                    for j in range(last_option + 1, min(len(block_text), last_option + 4)):
                        current_line = lines[block_indices[j]]
                        paragraph_gap = current_line["bbox"][1] - previous_bottom
                        if paragraph_gap > 18:
                            break
                        if re.match(r"^\d+\s*p$", block_text[j].strip(), re.I) or HEADER_RE.match(block_text[j].strip()):
                            break
                        end_pos = j
                        previous_bottom = max(previous_bottom, current_line["bbox"][3])
                    question_end_line = block_indices[end_pos]
                elif start < marker["number_line"]:
                    question_end_line = marker["points_line"]
                else:
                    # Open questions do not have A-D options to delimit them.
                    # Do not consume every line up to the next question marker:
                    # a new boxed/context paragraph can begin in between (e.g.
                    # Havo 2025-I question 13 followed by the transplant context
                    # for question 14). Stop at the first clear paragraph break
                    # after the question prompt has begun.
                    question_end_line = end - 1
                    previous_bottom = lines[start]["bbox"][3]
                    prompt_seen = False
                    for j in range(start + 1, end):
                        gap = lines[j]["bbox"][1] - previous_bottom
                        if prompt_seen and gap > 18:
                            question_end_line = j - 1
                            break
                        if j not in {marker["number_line"], marker["points_line"]}:
                            prompt_seen = True
                        previous_bottom = max(previous_bottom, lines[j]["bbox"][3])
                question_end_line = max(start, min(question_end_line, end - 1))

                if (prefix, marker["number"]) in SELECTED_CONTEXTS:
                    context_image = f"question-{prefix}-{marker['number']}.jpg"
                    context_y1 = min(page.rect.height, lines[question_end_line]["bbox"][3] + 7)
                    page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), clip=fitz.Rect(0, context_y0, page.rect.width, context_y1), alpha=False).save(OUT / context_image)
                    context_record = {"level": level, "year": year, "period": period, "n": marker["number"], "page": page_index + 1, "image": f"exam-snippets/{context_image}"}
                    if (prefix, marker["number"]) in {("vw25t1", 14), ("vw25t1", 15), ("vw25t1", 16), ("vw25t1", 17), ("vw25t1", 18)}:
                        context_record["images"] = ["exam-snippets/vw25-t1-hippo-context.jpg", f"exam-snippets/{context_image}"]
                    contexts.append(context_record)

                false_positive_open_questions = {
                    ("ha25t2", 30), ("ha25t2", 40), ("vw25t2", 14),
                    ("vw26t1", 30), ("ha26t2", 40)
                }
                if (prefix, marker["number"]) in false_positive_open_questions or not options:
                    previous_ranges.append((start, question_end_line + 1))
                    cursor = question_end_line + 1
                    continue

                correct = answer_from_cv(cv_text, marker["number"])
                option_keys = [o["key"] for o in options]
                required_keys = "ABCDEF"[:max(len(option_keys), "ABCDEF".find(correct) + 1 if correct else len(option_keys))]
                if (prefix, marker["number"]) == ("vw25t2", 22):
                    required_keys = "ABCDEF"
                options_by_key = {o["key"]: o for o in options}
                options = [{"key": key, "text": options_by_key.get(key, {}).get("text", "")} for key in required_keys]

                # Full-width page strip containing context and question.
                y0 = context_y0
                y1 = min(page.rect.height, lines[question_end_line]["bbox"][3] + 7)
                crop = fitz.Rect(0, y0, page.rect.width, y1)
                qid = f"{prefix}-mcq-{marker['number']}"
                image_name = f"mcq-{qid}.jpg"
                page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), clip=crop, alpha=False).save(OUT / image_name)

                prompt = "\n".join(x for x in block_text[:first_option] if x.strip()).strip()
                if not prompt:
                    prompt = "\n".join(x for x in block_text if x.strip()).strip()
                found.append({
                    "id": qid,
                    "level": level,
                    "year": year,
                    "period": period,
                    "n": marker["number"],
                    "points": marker["points"],
                    "page": page_index + 1,
                    "theme": "Meerkeuzevragen",
                    "concept": "Meerkeuze",
                    "end": "Nog te rubriceren",
                    "focus": "Meerkeuzevraag uit het officiële centraal examen.",
                    "source": context or "Gebruik de context en gegevens in de oorspronkelijke examenopgave.",
                    "q": prompt,
                    "options": options,
                    "correct": correct,
                    "image": f"exam-snippets/{image_name}",
                    "pdf": exam_rel,
                    "cv": cv_rel,
                    "questionType": "mcq",
                })
                previous_ranges.append((start, question_end_line + 1))
                cursor = question_end_line + 1
    return found, contexts


all_questions = []
all_contexts = []
for exam in EXAMS:
    items, contexts = extract_exam(*exam)
    all_questions.extend(items)
    all_contexts.extend(contexts)
    print(f"{exam[0]}: {len(items)} meerkeuzevragen; {len(contexts)} geselecteerde contexten")
# Question 40 in VWO 2025 time slot 2 uses a table layout that PyMuPDF
# does not expose as ordinary A-D text blocks; add it from the official page.
if not any(q["id"] == "vw25t2-mcq-40" for q in all_questions):
    pdf_rel = "examens/vw-1018-a-25-2-o.pdf"
    with fitz.open(ROOT / pdf_rel) as doc:
        page = doc[18]  # printed page 19 of the exam
        start_hits = page.search_for("Op welk type eiland")
        end_hits = page.search_for("klein veraf")
        if not start_hits or not end_hits:
            raise RuntimeError("Could not locate VWO 2025 time slot 2 question 40 for its image crop")
        y0 = max(0, min(r.y0 for r in start_hits) - 5)
        y1 = min(page.rect.height, max(r.y1 for r in end_hits) + 6)
        image_name = "mcq-vw25t2-mcq-40.jpg"
        page.get_pixmap(
            matrix=fitz.Matrix(1.8, 1.8),
            clip=fitz.Rect(0, y0, page.rect.width, y1),
            alpha=False,
        ).save(OUT / image_name)
    all_questions.append({
        "id": "vw25t2-mcq-40",
        "level": "Vwo",
        "year": "2025",
        "period": "2",
        "n": 40,
        "points": 2,
        "page": 19,
        "theme": "Meerkeuzevragen",
        "concept": "Meerkeuze",
        "end": "Nog te rubriceren",
        "focus": "Meerkeuzevraag over de eilandtheorie van McArthur en Wilson.",
        "source": "De verdwerging van grote zoogdieren op een gekoloniseerd eiland is mede te verklaren met de eilandtheorie van McArthur en Wilson. Een kleiner aantal soorten op een eiland maakt de kans groter dat predatoren afwezig zijn. Grote zoogdiersoorten kunnen dan verdwergen.",
        "q": "Op welk type eiland zal het aantal soorten het kleinst zijn volgens de eilandtheorie van McArthur en Wilson?",
        "options": [
            {"key": "A", "text": "groot, dichtbij"},
            {"key": "B", "text": "groot, veraf"},
            {"key": "C", "text": "klein, dichtbij"},
            {"key": "D", "text": "klein, veraf"},
        ],
        "correct": "D",
        "image": "exam-snippets/mcq-vw25t2-mcq-40.jpg",
        "pdf": pdf_rel,
        "cv": "examens/vw-1018-a-25-2-c.pdf",
        "questionType": "mcq",
    })

missing = [q["id"] for q in all_questions if not q["correct"]]
print(f"Totaal: {len(all_questions)} meerkeuzevragen; zonder automatisch gevonden antwoord: {len(missing)}")
if missing:
    print("Controle nodig voor antwoorden:", ", ".join(missing))
(ROOT / "exam-mcq.json").write_text(json.dumps(all_questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
context_by_key = {}
for item in all_contexts:
    context_by_key.setdefault((item["level"], item["year"], item["period"], item["n"]), item)
all_contexts = list(context_by_key.values())
# Context records intentionally contain image references only. The original
# exam page snippets are the sole source of question/context wording.
(ROOT / "exam-contexts.json").write_text(json.dumps(all_contexts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Geschreven: exam-mcq.json en exam-contexts.json")
