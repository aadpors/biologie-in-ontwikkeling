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
        if (
            record.get("level") == "Havo"
            and str(record.get("year")) == "2024"
            and str(record.get("period")) == "1"
            and int(record.get("n", 0)) == 3
            and filename in {"exam-contexts.json", "exam-open.json"}
            and (not paths or paths[0] != "exam-snippets/context-ha24t1-q1-complete.jpg")
        ):
            errors.append(
                f"{label} {qid}: gedeelde algemene hartklepcontext ontbreekt "
                "of staat niet vóór de vraagafbeelding"
            )
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
        # Targeted visual regressions for known source-page boundary failures.
        if (
            filename in {"exam-open.json", "exam-contexts.json"}
            and record.get("level") == "Havo"
            and str(record.get("year")) == "2024"
            and str(record.get("period")) == "1"
            and int(record.get("n", 0)) == 3
            and len(paths) >= 2
        ):
            question_image = ROOT / paths[-1]
            with Image.open(question_image) as image:
                gray = image.convert("L")
                pixels = gray.load()
                width, height = gray.size
                for y in range(max(0, height - 12), height):
                    if sum(1 for x in range(width) if pixels[x, y] < 235) >= width * 0.70:
                        errors.append(f"{label} {qid}: horizontale paginascheidingslijn blijft aan de onderrand van de vraagafbeelding staan")
                        break
                gray.close()
        visual_minimums = {
            ("Havo", "2024", "1", 27): 500,
            ("Vwo", "2025", "1", 11): 600,
        }
        visual_key = (record.get("level"), str(record.get("year")), str(record.get("period")), int(record.get("n", 0)))
        if filename in {"exam-open.json", "exam-contexts.json"} and visual_key in visual_minimums and paths:
            with Image.open(ROOT / paths[0]) as image:
                if image.height < visual_minimums[visual_key]:
                    errors.append(
                        f"{label} {qid}: contextafbeelding lijkt een doorlopende figuur af te snijden "
                        f"({image.height}px; verwacht minstens {visual_minimums[visual_key]}px)"
                    )

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

# Every official correction-scheme manifest entry must resolve to a readable generated image.
cv_manifest = json.loads((ROOT / "scripts" / "cv-snippets.json").read_text(encoding="utf-8"))
for item in cv_manifest:
    for key in ("output", "amendment_output"):
        rel = item.get(key)
        if not rel:
            continue
        path = ROOT / "exam-snippets" / rel if not str(rel).startswith("exam-snippets/") else ROOT / rel
        if not path.is_file():
            errors.append(f"correctievoorschrift {item.get('id')}: ontbrekende snippet {path.relative_to(ROOT)}")
            continue
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                if image.width < 100 or image.height < 30:
                    errors.append(f"correctievoorschrift {item.get('id')}: onwaarschijnlijk kleine afbeelding {rel} ({image.size})")
        except Exception as exc:
            errors.append(f"correctievoorschrift {item.get('id')}: ongeldige afbeelding {rel}: {exc}")

if errors:
    print("\n".join(errors))
    raise SystemExit(f"Controle mislukt: {len(errors)} fouten in {total} vragen.")
print(f"Controle geslaagd: {total} vragen; alle primaire, context- en vraagafbeeldingen bestaan en zijn leesbare afbeeldingen.")
