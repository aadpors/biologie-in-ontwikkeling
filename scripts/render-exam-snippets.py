import json
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "exam-snippets.json"
OUT = ROOT / "exam-snippets"
OUT.mkdir(exist_ok=True)  # Generated source crops are committed for static-site delivery.

items = json.loads(MANIFEST.read_text(encoding="utf-8"))
for item in items:
    source = ROOT / item["pdf"]
    if not source.exists():
        raise FileNotFoundError(source)
    with fitz.open(source) as doc:
        scale = item.get("scale", 1.8)
        for clip in item["clips"]:
            page = doc[clip["page"] - 1]
            configured = fitz.Rect(*clip["rect"])
            # Always preserve the full horizontal page width; only the vertical
            # bounds are question-specific.
            rect = fitz.Rect(0, configured.y0, page.rect.width, configured.y1)
            pix = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                clip=rect,
                alpha=False,
            )
            output = OUT / clip["output"]
            pix.save(output)
            print(f"Rendered {clip['output']} from {item['pdf']} page {clip['page']}")
