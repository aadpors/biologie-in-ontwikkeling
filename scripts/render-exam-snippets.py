import json
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "exam-snippets.json"
OUT = ROOT / "exam-snippets"
OUT.mkdir(exist_ok=True)

items = json.loads(MANIFEST.read_text(encoding="utf-8"))
for item in items:
    source = ROOT / item["pdf"]
    if not source.exists():
        raise FileNotFoundError(source)
    doc = fitz.open(source)
    scale = item.get("scale", 1.8)
    page = doc[item["page"] - 1]
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    pix.save(OUT / item["output"])
    if "clip" in item:
        page = doc[item["clip"]["page"] - 1]
        rect = fitz.Rect(*item["clip"]["rect"])
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
        pix.save(OUT / item["clip"]["output"])
    doc.close()
    print(f"Rendered {item['output']} from {item['pdf']}")
    if "clip" in item:
        print(f"Rendered {item['clip']['output']} from {item['pdf']}")
