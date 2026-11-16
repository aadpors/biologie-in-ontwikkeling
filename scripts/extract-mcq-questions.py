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
    prompt_starts = re.compile(r"^(wat|welk|welke|waar|wanneer|waarom|hoe|leg|verklaar|beschrijf|noteer|geef|noem|is|zijn|neemt|beoordeel|schrijf|bereken|licht|beredeneer|laat|tot welke|in welk|op welke|hoeveel|waardoor|welke|welk)", re.I)
    point_re = re.compile(r"^\s*(\d+)\s*p\s*$", re.I)
    for i, record in enumerate(lines):
        inline = MARKER_RE.match(record["text"])
        if inline:
            markers.append({
                "line": i, "number_line": i, "points_line": i,
                "number": int(inline.group(2)), "points": int(inline.group(1)),
                "inline_prompt": record["text"][inline.end():].strip()
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
        # In these PDFs the point marker can appear before or after the question number.
        if point_re.match(following):
            pm = point_re.match(following)
            start = i - 1 if (previous.endswith("?") or prompt_starts.match(previous)) else i
            markers.append({"line": start, "number_line": i, "points_line": i + 1, "number": number, "points": int(pm.group(1))})
            continue
        for offset in range(2, 6):
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
                excluded = {marker["number_line"], marker["points_line"]}
                block_text = ([marker["inline_prompt"]] if marker.get("inline_prompt") else []) + [
                    lines[j]["text"] for j in range(start, end)
                    if j not in excluded and not HEADER_RE.match(lines[j]["text"])
                ]
                options = parse_options(block_text)
                if (prefix, marker["number"]) in {("ha25t2", 30), ("ha25t2", 40), ("vw25t2", 14), ("vw26t1", 30), ("ha26t2", 40)}:
                    previous_ranges.append((start, end))
                    continue
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
            clip=fitz.Rect(42, y0, page.rect.width - 42, y1),
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
print("Geschreven: exam-mcq.json")
