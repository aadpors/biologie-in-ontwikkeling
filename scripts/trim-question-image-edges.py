"""Final pass: remove horizontal source-page separators below question crops."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "exam-snippets"
trimmed = []

for path in sorted(OUT.glob("question-*.jpg")):
    with Image.open(path) as source:
        image = source.convert("RGB")
    gray = image.convert("L")
    pixels = gray.load()
    width, height = gray.size
    rule_y = None
    for y in range(max(0, height - 20), height - 1):
        dark_fraction = sum(1 for x in range(width) if pixels[x, y] < 235) / width
        if dark_fraction < 0.70:
            continue
        above = [
            sum(1 for x in range(width) if pixels[x, py] < 235) / width
            for py in range(max(0, y - 3), y)
        ]
        if above and max(above) < 0.15:
            rule_y = y
            break
    gray.close()
    if rule_y is not None:
        bottom = max(1, rule_y - 1)
        content = image.crop((0, 0, width, bottom))
        result = Image.new("RGB", (width, bottom + 4), "white")
        result.paste(content, (0, 0))
        result.save(path, quality=94)
        content.close()
        result.close()
        trimmed.append(path.name)
    image.close()

print(f"Vraagafbeeldingen gecontroleerd: {len(list(OUT.glob('question-*.jpg')))}; scheidingslijnen verwijderd: {len(trimmed)}")
if trimmed:
    print("\n".join(trimmed))
