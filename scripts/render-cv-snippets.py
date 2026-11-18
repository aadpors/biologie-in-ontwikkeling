import json
import re
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "cv-snippets.json"
OUT = ROOT / "exam-snippets"
OUT.mkdir(exist_ok=True)

def page_lines(page):
    lines = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = " ".join(s.get("text", "") for s in spans).strip()
            if text:
                lines.append({
                    "text": text,
                    "x0": min(s["bbox"][0] for s in spans),
                    "y0": min(s["bbox"][1] for s in spans),
                    "size": max(s.get("size", 0) for s in spans),
                    "bold": any("bold" in s.get("font", "").lower() for s in spans),
                })
    return sorted(lines, key=lambda line: (round(line["y0"], 1), line["x0"]))

def heading_at(lines, index, number=None):
    line = lines[index]
    text = re.sub(r"\\s+", " ", line["text"]).strip()
    combined = r"(?:maximumscore\\b|[A-F](?:\\s+\\d\\b)?\\b)"
    if number is not None:
        if re.match(rf"^{number}\\s+{combined}", text, re.I):
            return True
        if text == str(number):
            return any(abs(other["y0"] - line["y0"]) < 14 and re.match(rf"^{combined}", re.sub(r"\\s+", " ", other["text"]).strip(), re.I) for other in lines if other is not line)
        return False
    if re.match(rf"^\\d{{1,2}}\\s+{combined}", text, re.I):
        return True
    if re.fullmatch(r"\\d{1,2}", text):
        return any(abs(other["y0"] - line["y0"]) < 14 and re.match(rf"^{combined}", re.sub(r"\\s+", " ", other["text"]).strip(), re.I) for other in lines if other is not line)
    return False

def render_question(pdf_path, question, output):
    with fitz.open(pdf_path) as doc:
        for page_index, page in enumerate(doc):
            lines = page_lines(page)
            matches = [i for i in range(len(lines)) if heading_at(lines, i, question)]
            if not matches:
                continue
            heading = lines[matches[0]]
            following = [line for i, line in enumerate(lines) if line["y0"] > heading["y0"] + 3 and heading_at(lines, i)]
            next_topic = [
                line for line in lines
                if line["y0"] > heading["y0"] + 3
                and (line["bold"] or line["size"] >= 16)
                and line["size"] >= 11 and len(line["text"]) < 100
                and not re.match(r"^\\d{1,2}\\s+", line["text"])
                and not re.match(r"^(?:maximumscore|antwoord|scores)\\b", line["text"], re.I)
            ]
            top = max(0, heading["y0"] - 8)
            boundaries = [line["y0"] for line in following + next_topic]
            bottom = min(page.rect.height - 80, min(boundaries, default=page.rect.height - 80) - 5)
            bottom = max(top + 35, bottom)
            page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), clip=fitz.Rect(0, top, page.rect.width, bottom), alpha=False).save(OUT / output)
            print(f"Rendered {output} from {pdf_path.name}, page {page_index + 1}, question {question}")
            return
    raise RuntimeError(f"Could not locate question {question} in {pdf_path}; refusing to create an incorrect snippet.")

def render_amendment(pdf_path, output):
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        rect = fitz.Rect(0, 75, page.rect.width, page.rect.height - 72)
        page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), clip=rect, alpha=False).save(OUT / output)
        print(f"Rendered amendment {output} from {pdf_path.name}, page 1")

# Build the CV inventory from the same machine-readable question sources as the
# website. This removes the old manually curated subset: every open and MCQ
# question gets an official, local answer-key fragment.
old_items = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
old_by_id = {item["id"]: item for item in old_items}
records = json.loads((ROOT / "exam-open.json").read_text(encoding="utf-8"))
# Retain previously selected open-question snippets and add every open question
# from the generated inventory. MCQs are auto-graded and have no CV reveal UI.
items_by_id = {item["id"]: dict(item) for item in old_items}
for record in records:
    qid = record.get("id")
    if not qid:
        raise RuntimeError(f"Question without id in inventory: {record}")
    level_code = "ha" if record["level"].lower() == "havo" else "vw"
    short_year = str(record["year"])[-2:]
    period = str(record["period"])
    pdf = f"examens/{level_code}-1018-a-{short_year}-{period}-c.pdf"
    source = ROOT / pdf
    if not source.is_file():
        raise FileNotFoundError(f"Official marking scheme missing for {qid}: {pdf}")
    previous = old_by_id.get(qid, {})
    output = previous.get("output") or f"cv-{qid}.jpg"
    item = {"id": qid, "question": int(record["n"]), "pdf": pdf, "output": output}
    if previous.get("amendment_pdf"):
        item["amendment_pdf"] = previous["amendment_pdf"]
        item["amendment_output"] = previous["amendment_output"]
    items_by_id[qid] = item

items = sorted(items_by_id.values(), key=lambda item: item["id"])
MANIFEST.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
for item in items:
    source = ROOT / item["pdf"]
    render_question(source, item["question"], item["output"])
    if item.get("amendment_pdf"):
        amendment = ROOT / item["amendment_pdf"]
        if not amendment.exists():
            raise FileNotFoundError(f"Official marking-scheme amendment not found: {amendment}")
        render_amendment(amendment, item["amendment_output"])

expected = {record["id"] for record in records} | {item["id"] for item in old_items}
actual = {item["id"] for item in items}
if expected != actual:
    raise RuntimeError(f"CV coverage mismatch; missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
print(f"CV coverage complete: {len(items)} open/self-check questions.")
