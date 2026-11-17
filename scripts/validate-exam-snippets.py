import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATASETS = [
    ("exam-mcq.json", "meerkeuzevragen"),
    ("exam-open.json", "open vragen"),
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
        for attachment in record.get("attachmentPdfs", []):
            if not (ROOT / attachment).is_file():
                errors.append(f"{label} {qid}: ontbrekende volledige uitwerkbijlage {attachment}")
        if not primary:
            errors.append(f"{label} {qid}: geen primaire samengestelde afbeelding")
        complete_single_page = (
            len(paths) == 1
            and paths[0] == primary
            and "question-complete-" in paths[0].lower()
        )
        if len(paths) < 2 and not complete_single_page:
            errors.append(f"{label} {qid}: verwacht aparte context- en vraagafbeelding of één volledige bronpagina, kreeg {len(paths)}")
        if len(paths) != len(set(paths)):
            errors.append(f"{label} {qid}: dubbele afbeelding in images-array")
        if not paths:
            errors.append(f"{label} {qid}: geen losse context-/vraagafbeeldingen gekoppeld")
        else:
            # The frontend labels every image before the final one as context;
            # the final image must therefore be the question crop itself.
            if not all("context" in p.lower() for p in paths[:-1]):
                errors.append(f"{label} {qid}: een tussenafbeelding is geen contextafbeelding: {paths[:-1]}")
            if not any(("question" in paths[-1].lower() or "mcq-" in paths[-1].lower()) for _ in [0]):
                errors.append(f"{label} {qid}: laatste afbeelding is geen vraagafbeelding: {paths[-1]}")
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
    print("\n".join(errors))
    raise SystemExit(f"Controle mislukt: {len(errors)} fouten in {total} vragen.")
print(f"Controle geslaagd: {total} vragen; alle primaire, context- en vraagafbeeldingen bestaan en zijn leesbare afbeeldingen.")
