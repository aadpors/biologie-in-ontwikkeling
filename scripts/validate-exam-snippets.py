import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATASETS = [
    ("exam-mcq.json", "meerkeuzevragen"),
    ("exam-contexts.json", "open vragen"),
]

errors = []
total = 0
for filename, label in DATASETS:
    records = json.loads((ROOT / filename).read_text(encoding="utf-8"))
    for record in records:
        total += 1
        qid = record.get("id") or f'{record.get("level")} {record.get("year")}-{record.get("period")} vraag {record.get("n")}'
        paths = record.get("images") or []
        primary = record.get("image")
        if not primary:
            errors.append(f"{label} {qid}: geen primaire samengestelde afbeelding")
        if len(paths) < 2:
            errors.append(f"{label} {qid}: verwacht aparte context- en vraagafbeelding, kreeg {len(paths)}")
        if len(paths) != len(set(paths)):
            errors.append(f"{label} {qid}: dubbele afbeelding in images-array")
        if not any("context" in p.lower() for p in paths):
            errors.append(f"{label} {qid}: geen contextafbeelding gekoppeld")
        if not any(("question" in p.lower() or "mcq-" in p.lower()) for p in paths):
            errors.append(f"{label} {qid}: geen vraagafbeelding gekoppeld")
        for rel in ([primary] if primary else []) + paths:
            path = ROOT / rel
            if not path.is_file():
                errors.append(f"{label} {qid}: ontbrekend bestand {rel}")
                continue
            try:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    if image.width < 100 or image.height < 30:
                        errors.append(f"{label} {qid}: onwaarschijnlijk kleine afbeelding {rel} ({image.size})")
            except Exception as exc:
                errors.append(f"{label} {qid}: ongeldige afbeelding {rel}: {exc}")

if errors:
    print("\\n".join(errors))
    raise SystemExit(f"Controle mislukt: {len(errors)} fouten in {total} vragen.")
print(f"Controle geslaagd: {total} vragen; alle primaire, context- en vraagafbeeldingen bestaan en zijn leesbare afbeeldingen.")
