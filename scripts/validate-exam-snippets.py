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
        # A numbered statement list is part of the question whenever the
        # response asks students to judge/identify those statements. It must
        # not remain in the general context text; the renderer starts the
        # question crop at the detected lead-in.
        question_prompt = record.get("q", "")
        numbered_answer = bool(
            __import__("re").search(
                r"(?i)(schrijf|noteer)\s+de\s+nummers|welke\s+uitspraak|"
                r"welk\s+van\s+deze\s+uitspraken|welke\s+van\s+deze\s+uitspraken",
                question_prompt,
            )
        )
        source_text = record.get("source", "")
        has_statement_block = bool(
            __import__("re").search(
                r"(?is)(?:uitspraken?|situaties?|onderdelen|processen|stoffen|"
                r"kenmerken|gevolgen|conclusies|gegevens)[^\n]*:?\s*"
                r"(?:\n[^\n]*){0,2}\n\s*1(?:[.)]\s+|\s+\S).*?"
                r"\n\s*2(?:[.)]\s+|\s+\S)",
                source_text,
            )
        )
        if numbered_answer and has_statement_block:
            errors.append(
                f"{label} {qid}: genummerde vraagonderdelen staan nog in de algemene contexttekst"
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

# Regression: a lead-in introducing numbered statements belongs to the
# question, never to its general context. This scans every generated exam card,
# not only individually named exceptions.
list_heading_re = __import__("re").compile(
    r"^\\s*(?:hieronder|hierna)\\s+(?:staan|staat|is|zijn|volgt|volgen|wordt|worden)\\b",
    __import__("re").I,
)
numbered_item_re = __import__("re").compile(r"^\\s*([1-4])(?:[.)]\\s+|\\s+\\S)")
for filename in ("exam-mcq.json", "exam-open.json"):
    records = json.loads((ROOT / filename).read_text(encoding="utf-8"))
    for record in records:
        source_lines = [line.strip() for line in str(record.get("source", "")).splitlines() if line.strip()]
        question_text = str(record.get("q", ""))
        for index, line in enumerate(source_lines):
            if not list_heading_re.match(line):
                continue
            following = source_lines[index + 1:index + 18]
            numbers = {
                int(match.group(1))
                for item in following
                if (match := numbered_item_re.match(item))
            }
            if len(numbers) >= 2:
                errors.append(
                    f"{filename} {record.get('id')}: vraaginleiding met genummerde uitspraken staat nog in de algemene context: {line}"
                )
                if line not in question_text:
                    errors.append(
                        f"{filename} {record.get('id')}: verplaatste vraaginleiding ontbreekt in het vraagveld: {line}"
                    )

# Havo 2025-I question 26 is the original reported regression and must remain
# correct after the generalized extraction pass.
q26_regression = next(
    (q for q in json.loads((ROOT / "exam-open.json").read_text(encoding="utf-8"))
     if q.get("id") == "ha25t1-open-26"),
    None,
)
if q26_regression:
    if "Hieronder staan drie uitspraken." in str(q26_regression.get("source", "")):
        errors.append("Havo 2025-I vraag 26: de vraaginleiding staat nog in source/context")
    if "Hieronder staan drie uitspraken." not in str(q26_regression.get("q", "")):
        errors.append("Havo 2025-I vraag 26: de vraaginleiding ontbreekt in de vraag")
    if q26_regression.get("images", [])[-1:] != ["exam-snippets/question-ha25t1-26-only.jpg"]:
        errors.append("Havo 2025-I vraag 26: de vraagafbeelding is niet als laatste afbeelding gekoppeld")

# Audit the lower edge of every generated question crop.
for image_path in sorted((ROOT / "exam-snippets").glob("question-*.jpg")):
    try:
        with Image.open(image_path) as source:
            gray = source.convert("L")
            pixels = gray.load()
            width, height = gray.size
            for y in range(max(0, height - 12), height):
                if sum(1 for x in range(width) if pixels[x, y] < 235) >= width * 0.70:
                    errors.append(
                        f"{image_path.name}: horizontale paginascheidingslijn of rand "
                        "blijft aan de onderrand van de vraagafbeelding staan"
                    )
                    break
            gray.close()
    except Exception as exc:
        errors.append(f"{image_path.name}: kan vraagafbeelding niet visueel controleren: {exc}")

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

# Explicit visual regressions reported during the Havo 2025-I audit.
def audit_crop_height(rel, minimum, label, maximum=None):
    path = ROOT / rel
    if not path.is_file():
        errors.append(f"{label}: ontbrekende uitsnede {rel}")
        return
    try:
        with Image.open(path) as image:
            height = image.height
        if height < minimum or (maximum is not None and height > maximum):
            bound = f"minimaal {minimum}px" if maximum is None else f"tussen {minimum} en {maximum}px"
            errors.append(f"{label}: uitsnede heeft {height}px hoogte; verwacht {bound}")
    except Exception as exc:
        errors.append(f"{label}: uitsnede kan niet worden gelezen: {exc}")

open_by_id = {
    record.get("id"): record
    for record in json.loads((ROOT / "exam-open.json").read_text(encoding="utf-8"))
}
mcq_by_id = {
    record.get("id"): record
    for record in json.loads((ROOT / "exam-mcq.json").read_text(encoding="utf-8"))
}
q26 = open_by_id.get("ha25t1-open-26")
if not q26 or len(q26.get("images", [])) < 2:
    errors.append("Havo 2025-I vraag 26: context- en vraaguitsnede ontbreken")
else:
    if q26["images"][0] != "exam-snippets/context-ha25t1-q26-complete.jpg":
        errors.append("Havo 2025-I vraag 26: algemene Bajau-context is niet apart gekoppeld")
    if q26["images"][-1] != "exam-snippets/question-ha25t1-26-only.jpg":
        errors.append("Havo 2025-I vraag 26: vraaguitsnede met drie uitspraken ontbreekt")
    audit_crop_height(q26["images"][-1], 200, "Havo 2025-I vraag 26: drie uitspraken en instructie")

q27 = mcq_by_id.get("ha25t1-mcq-27")
if not q27 or not q27.get("images") or q27["images"][0] != "exam-snippets/context-ha25t1-q27-complete.jpg":
    errors.append("Havo 2025-I vraag 27: eigen zeehondencontext ontbreekt of is vervangen door de Bajau-context")

q29 = open_by_id.get("ha25t1-open-29")
if not q29 or len(q29.get("images", [])) < 2:
    errors.append("Havo 2025-I vraag 29: aparte vraaguitsnede ontbreekt")
else:
    audit_crop_height(
        q29["images"][-1], 30,
        "Havo 2025-I vraag 29: onderrand van de vraaguitsnede",
        maximum=120,
    )

q18_cv = next((item for item in cv_manifest if item.get("id") == "vw26t1-open-18"), None)
if not q18_cv:
    errors.append("Vwo 2026-I vraag 18: CV-koppeling ontbreekt")
else:
    audit_crop_height(
        f"exam-snippets/{q18_cv['output']}", 100,
        "Vwo 2026-I vraag 18: beide beoordelingscriteria",
    )

if errors:
    print("\n".join(errors))
    raise SystemExit(f"Controle mislukt: {len(errors)} fouten in {total} vragen.")
print(f"Controle geslaagd: {total} vragen; alle primaire, context- en vraagafbeeldingen bestaan en zijn leesbare afbeeldingen.")
