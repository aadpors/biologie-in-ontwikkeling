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
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = " ".join(s.get("text", "") for s in spans).strip()
            if text:
                lines.append({"text": text, "x0": min(s["bbox"][0] for s in spans), "y0": min(s["bbox"][1] for s in spans)})
    return sorted(lines, key=lambda line: (round(line["y0"], 1), line["x0"]))

def heading_at(lines, index, number=None):
    line = lines[index]
    text = re.sub(r"\s+", " ", line["text"]).strip()
    combined = r"(?:maximumscore\b|[A-F](?:\s+\d\b)?\b)"
    if number is not None:
        if re.match(rf"^{number}\s+{combined}", text, re.I):
            return True
        if text == str(number):
            return any(abs(other["y0"] - line["y0"]) < 14 and re.match(rf"^{combined}", re.sub(r"\s+", " ", other["text"]).strip(), re.I) for other in lines if other is not line)
        return False
    if re.match(rf"^\d{{1,2}}\s+{combined}", text, re.I):
        return True
    if re.fullmatch(r"\d{1,2}", text):
        return any(abs(other["y0"] - line["y0"]) < 14 and re.match(rf"^{combined}", re.sub(r"\s+", " ", other["text"]).strip(), re.I) for other in lines if other is not line)
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
            top = max(0, heading["y0"] - 8)
            bottom = min(page.rect.height - 38, min((line["y0"] for line in following), default=page.rect.height - 38) - 5)
            bottom = max(top + 35, bottom)
            rect = fitz.Rect(42, top, page.rect.width - 42, bottom)
            page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), clip=rect, alpha=False).save(OUT / output)
            print(f"Rendered {output} from {pdf_path.name}, page {page_index + 1}, question {question}")
            return
    raise RuntimeError(f"Could not locate question {question} in {pdf_path}; refusing to create an incorrect snippet.")

def render_amendment(pdf_path, output):
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        lines = page_lines(page)
        start = next((line["y0"] for line in lines if re.search(r"Op pagina\s+\d+", line["text"], re.I)), None)
        if start is None:
            raise RuntimeError(f"Could not locate amendment text in {pdf_path}")
        end = next((line["y0"] for line in lines if re.search(r"Ik verzoek u dit bericht", line["text"], re.I)), page.rect.height - 70)
        rect = fitz.Rect(42, max(0, start - 18), page.rect.width - 42, min(page.rect.height - 55, end - 8))
        page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), clip=rect, alpha=False).save(OUT / output)
        print(f"Rendered amendment {output} from {pdf_path.name}, page 1")

for item in items:
    source = ROOT / item["pdf"]
    if not source.exists():
        raise FileNotFoundError(f"Official marking scheme not found: {source}")
    render_question(source, item["question"], item["output"])
    if item.get("amendment_pdf"):
        amendment = ROOT / item["amendment_pdf"]
        if not amendment.exists():
            raise FileNotFoundError(f"Official marking-scheme amendment not found: {amendment}")
        render_amendment(amendment, item["amendment_output"])
