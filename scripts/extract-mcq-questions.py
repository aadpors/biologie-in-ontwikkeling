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

HEADER_RE = re.compile(r"^(?:[HV][AW]-1018-a-\d{2}-\d-o|\d+\s*/\s*\d+|lees verder|einde)\b", re.I)
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
    records.sort(key=lambda x: (round(x["bbox"][1], 1), x["bbox"][0]))
    return records

def find_markers(lines):
    markers = []
    i = 0
    while i < len(lines):
        text = lines[i]["text"]
        m = MARKER_RE.match(text)
        if m:
            markers.append({"line": i, "number": int(m.group(2)), "points": int(m.group(1))})
            i += 1
            continue
        if re.fullmatch(r"\d+\s*p", text, re.I) and i + 1 < len(lines):
            n = NUMBER_RE.match(lines[i + 1]["text"])
            if n:
                markers.append({"line": i, "number": int(n.group(1)), "points": int(re.match(r"\d+", text).group())})
                i += 2
                continue
        i += 1
    # Keep only one marker per question number on a page.
    unique = []
    seen = set()
    for marker in markers:
        if marker["number"] not in seen:
            unique.append(marker)
            seen.add(marker["number"])
    return unique

def parse_options(block_lines):
    options = []
    current = None
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
        elif current:
            current["text"] = (current["text"] + " " + text).strip()
    if current:
        options.append(current)
    # Require a complete consecutive set beginning with A.
    keys = [o["key"] for o in options]
    if len(keys) >= 3 and keys[0] == "A" and keys == list("ABCDEF"[:len(keys)]):
        return options
    # A/B/C/D labels can be placed on one line above image-based answer options.
    compact = " ".join(block_lines)
    labels = re.search(r"\bA\s+B\s+C\s+D(?:\s+E)?(?:\s+F)?\b", compact)
    if labels:
        return [{"key": k, "text": "Afbeelding/keuze " + k} for k in labels.group(0).split()]
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
    # In the official marking schemes, a multiple-choice answer is normally
    # a single letter immediately after the maximum-score line.
    matches = list(re.finditer(rf"(?m)^\s*{qnum}\s*$", cv_text))
    for match in matches:
        chunk = cv_text[match.end():match.end() + 450]
        m = re.search(r"maximumscore\s+\d+\s+([A-F])(?:\s|$)", chunk, re.I)
        if m:
            return m.group(1).upper()
        m = re.search(r"maximumscore\s+\d+\s*\n\s*([A-F])\s*(?:\n|$)", chunk, re.I)
        if m:
            return m.group(1).upper()
    return ""

def extract_exam(prefix, level, year, period, exam_rel, cv_rel):
    exam_path, cv_path = ROOT / exam_rel, ROOT / cv_rel
    if not exam_path.exists() or not cv_path.exists():
        raise FileNotFoundError(f"Missing source file: {exam_path if not exam_path.exists() else cv_path}")
    with fitz.open(cv_path) as cv_doc:
        cv_text = "\n".join(page.get_text("text", sort=True) for page in cv_doc)
    found = []
    with fitz.open(exam_path) as doc:
        for page_index, page in enumerate(doc):
            lines = line_records(page)
            markers = find_markers(lines)
            if not markers:
                continue
            previous_ranges = []
            for idx, marker in enumerate(markers):
                start = marker["line"]
                end = markers[idx + 1]["line"] if idx + 1 < len(markers) else len(lines)
                block = lines[start:end]
                block_text = [x["text"] for x in block]
                # The question block begins at the point marker. Remove that marker.
                if block_text:
                    block_text = block_text[1:] if re.match(r"^\d+\s*p\s+\d+", block_text[0], re.I) else block_text[2:]
                options = parse_options(block_text)
                if not options:
                    previous_ranges.append((start, end))
                    continue
                # Context starts at the last prominent case heading on this page.
                heading_candidates = [
                    j for j in range(start)
                    if (lines[j]["size"] >= 13 or (lines[j]["bold"] and lines[j]["size"] >= 11))
                    and len(lines[j]["text"]) < 90
                    and not HEADER_RE.match(lines[j]["text"])
                    and not re.match(r"^\d+\s*p", lines[j]["text"], re.I)
                ]
                context_start = heading_candidates[-1] if heading_candidates else 0
                context_lines = []
                for j in range(context_start, start):
                    if any(a <= j < b for a, b in previous_ranges):
                        continue
                    context_lines.append(lines[j]["text"])
                context = clean_context(context_lines)
                # The original question crop preserves diagrams and any graphical answer options.
                y0 = max(0, block[0]["bbox"][1] - 4) if block else 0
                y1 = min(page.rect.height, block[-1]["bbox"][3] + 5) if block else page.rect.height
                # Include a little more vertical context when options are graphical.
                crop = fitz.Rect(35, y0, page.rect.width - 35, y1)
                qid = f"{prefix}-mcq-{marker['number']}"
                image_name = f"mcq-{qid}.jpg"
                pix = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), clip=crop, alpha=False)
                pix.save(OUT / image_name)
                prompt_lines = []
                first_option = next((i for i, x in enumerate(block_text) if OPTION_RE.match(x.strip())), len(block_text))
                prompt_lines = block_text[:first_option]
                prompt = "\n".join(x for x in prompt_lines if x.strip()).strip()
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
                    "correct": answer_from_cv(cv_text, marker["number"]),
                    "image": f"exam-snippets/{image_name}",
                    "pdf": exam_rel,
                    "cv": cv_rel,
                    "questionType": "mcq",
                })
                previous_ranges.append((start, end))
    return found

all_questions = []
for exam in EXAMS:
    items = extract_exam(*exam)
    all_questions.extend(items)
    print(f"{exam[0]}: {len(items)} meerkeuzevragen")
missing = [q["id"] for q in all_questions if not q["correct"]]
print(f"Totaal: {len(all_questions)} meerkeuzevragen; zonder automatisch gevonden antwoord: {len(missing)}")
if missing:
    print("Controle nodig voor antwoorden:", ", ".join(missing))
(ROOT / "exam-mcq.json").write_text(json.dumps(all_questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Geschreven: exam-mcq.json")
