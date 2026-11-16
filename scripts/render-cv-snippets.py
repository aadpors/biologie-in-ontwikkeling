import json
import re
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "cv-snippets.json"
OUT = ROOT / "exam-snippets"
OUT.mkdir(exist_ok=True)

items = json.loads(MANIFEST.read_text(encoding="utf-8"))

def page_lines(page):
    lines = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = " ".join(s.get("text", "") for s in spans).strip()
            if text:
                x0 = min(s["bbox"][0] for s in spans)
                y0 = min(s["bbox"][1] for s in spans)
                y1 = max(s["bbox"][3] for s in spans)
                lines.append({"text": text, "x0": x0, "y0": y0, "y1": y1})
    return sorted(lines, key=lambda line: (round(line["y0"], 1), line["x0"]))

def is_question_heading(line, number):
    text = re.sub(r"\s+", " ", line["text"]).strip()
    if line["x0"] > 125:
        return False
    return bool(re.match(rf"^{number}\s+(?:maximumscore\b|[A-D]\s+\d\b)", text, re.I))

def is_any_question_heading(line):
    text = re.sub(r"\s+", " ", line["text"]).strip()
    if line["x0"] > 125:
        return False
    return bool(re.match(r"^\d{1,2}\s+(?:maximumscore\b|[A-D]\s+\d\b)", text, re.I))

for item in items:
    source = ROOT / item["pdf"]
    if not source.exists():
        raise FileNotFoundError(f"Official marking scheme not found: {source}")
    rendered = False
    with fitz.open(source) as doc:
        for page_index, page in enumerate(doc):
            lines = page_lines(page)
            matches = [i for i, line in enumerate(lines) if is_question_heading(line, item["question"])]
            if not matches:
                continue
            heading = lines[matches[0]]
            following = [line for line in lines if line["y0"] > heading["y0"] + 3 and is_any_question_heading(line)]
            bottom = min((line["y0"] for line in following), default=page.rect.height - 38)
            top = max(0, heading["y0"] - 9)
            bottom = min(page.rect.height, max(top + 35, bottom - 5))
            rect = fitz.Rect(42, top, page.rect.width - 42, bottom)
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), clip=rect, alpha=False)
            output = OUT / item["output"]
            pix.save(output)
            print(f"Rendered {item['output']} from {item['pdf']} page {page_index + 1}, question {item['question']}")
            rendered = True
            break
    if not rendered:
        raise RuntimeError(f"Could not locate question {item['question']} in {item['pdf']}; refusing to create an incorrect snippet.")
