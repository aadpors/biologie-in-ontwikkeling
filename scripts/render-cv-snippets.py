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

def heading_at(lines, index, number=None):
    line = lines[index]
    text = re.sub(r"\\s+", " ", line["text"]).strip()
    if number is not None:
        if re.match(rf"^{number}\\s+(?:maximumscore\\b|[A-D]\\s+\\d\\b)", text, re.I):
            return True
        if text == str(number):
            for nxt in lines[index + 1:index + 4]:
                if nxt["y0"] - line["y0"] > 38:
                    break
                next_text = re.sub(r"\\s+", " ", nxt["text"]).strip()
                if re.match(r"^(?:maximumscore\\b|[A-D]\\s+\\d\\b)", next_text, re.I):
                    return True
        return False
    if re.match(r"^\\d{1,2}\\s+(?:maximumscore\\b|[A-D]\\s+\\d\\b)", text, re.I):
        return True
    if re.fullmatch(r"\\d{1,2}", text):
        for nxt in lines[index + 1:index + 4]:
            if nxt["y0"] - line["y0"] > 38:
                break
            next_text = re.sub(r"\\s+", " ", nxt["text"]).strip()
            if re.match(r"^(?:maximumscore\\b|[A-D]\\s+\\d\\b)", next_text, re.I):
                return True
    return False

for item in items:
    source = ROOT / item["pdf"]
    if not source.exists():
        raise FileNotFoundError(f"Official marking scheme not found: {source}")
    rendered = False
    with fitz.open(source) as doc:
        for page_index, page in enumerate(doc):
            lines = page_lines(page)
            if item["question"] == 14 and "vw-1018-a-25-1-c.pdf" in item["pdf"]:
                diagnostic = [line for line in lines if "14" in line["text"] or "maximumscore" in line["text"].lower()]
                print("DIAGNOSTIC page", page_index + 1, [line["text"] for line in diagnostic[:35]])
            matches = [i for i, line in enumerate(lines) if heading_at(lines, i, item["question"])]
            if not matches:
                continue
            heading = lines[matches[0]]
            following = [line for i, line in enumerate(lines) if line["y0"] > heading["y0"] + 3 and heading_at(lines, i)]
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
