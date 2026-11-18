import json
import re
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
questions = json.loads((ROOT / "exam-open.json").read_text(encoding="utf-8"))
html = (ROOT / "examenoefenen.html").read_text(encoding="utf-8")
match = re.search(r"const binaryAnswerKeys=(\{.*?\});\nbinaryAnswerKeys\[", html, re.S)
if not match:
    raise SystemExit("Embedded binary answer-key object not found")
keys = json.loads(match.group(1))

def is_binary(question):
    prompt = question.get("q", "")
    return bool(re.search(r"juist\s+of\s+onjuist|wel\s+(?:of\s+niet|of\s+geen|een[\s\S]*?of\s+geen)", prompt, re.I))

def cv_lines(question):
    path = ROOT / question["cv"]
    with fitz.open(path) as pdf:
        for page in pdf:
            lines = [line.strip() for line in page.get_text("text").splitlines() if line.strip()]
            for i, line in enumerate(lines[:-1]):
                if line == str(question["n"]) and re.match(r"maximumscore\b", lines[i + 1], re.I):
                    return lines[i + 2:]
    raise ValueError(f"Official CV heading not found: {question['id']}")

def answer_side(answer):
    value = answer.strip().lower()
    if value.startswith(("juist", "wel")):
        return "left"
    if value.startswith(("onjuist", "niet", "geen")):
        return "right"
    raise ValueError(f"Unknown binary answer: {answer!r}")

# The same shared statement prompt can be attached to several consecutive
# open questions in a passage. Count the explicitly curated interactive
# question IDs, not every card whose copied prompt happens to contain the
# words "wel of niet" or "juist of onjuist".
questions_by_id = {q["id"]: q for q in questions}
missing_questions = sorted(set(keys) - set(questions_by_id))
if missing_questions:
    raise SystemExit(f"Binary answer-key questions missing from exam data: {missing_questions}")
binary = [questions_by_id[question_id] for question_id in keys]
not_binary = [q["id"] for q in binary if not is_binary(q)]
if not_binary:
    raise SystemExit(f"Curated binary questions lack a binary prompt: {not_binary}")
if len(binary) != 72:
    raise SystemExit(f"Expected 72 curated binary questions, found {len(binary)}")

for q in binary:
    key = keys.get(q["id"])
    if not key:
        raise SystemExit(f"Missing embedded answer key: {q['id']}")
    lines = cv_lines(q)
    if q["id"] == "ha26t2-open-28":
        if not any(line.lower().startswith("wel (veganistisch) met een juiste toelichting") for line in lines):
            raise SystemExit("B12 answer criterion changed in official CV")
        expected = ["left"]
        if not key.get("requiresExplanation"):
            raise SystemExit("B12 explanation requirement missing")
    elif q["id"] == "ha26t1-open-29":
        values = [line.lower() for line in lines if line.lower() in {"wel", "geen"}]
        expected = [answer_side(x) for x in values[:4]]
        if len(expected) != 4:
            raise SystemExit("Could not extract all four answers from the 2x2 digestion table")
        if key.get("scoreGroups") != [[0, 1], [2, 3]]:
            raise SystemExit("2x2 digestion table scoring groups do not match CV")
    else:
        count_match = re.search(r"nummers?\s+1\s+tot en met\s+(\d+)", q.get("q", ""), re.I)
        count = int(count_match.group(1)) if count_match else (3 if re.search(r"nummers?\s+1\s*,\s*2\s+en\s+3", q.get("q", ""), re.I) or re.search(r"namen\s+Isa,\s*Kate\s+en\s+Mounir", q.get("q", ""), re.I) else 0)
        if not count:
            raise SystemExit(f"Cannot determine binary row count: {q['id']}")
        if re.search(r"namen\s+Isa,\s*Kate\s+en\s+Mounir", q.get("q", ""), re.I):
            by_name = {}
            for line in lines:
                m = re.match(r"(Isa|Kate|Mounir):\s*(juist|onjuist)", line, re.I)
                if m:
                    by_name[m.group(1)] = m.group(2)
            answers = [by_name.get(name) for name in ("Isa", "Kate", "Mounir")]
        else:
            answers = []
            for number in range(1, count + 1):
                found = None
                for i, line in enumerate(lines[:-1]):
                    if line == str(number) and re.match(r"^(juist|onjuist|wel|niet|geen)\b", lines[i + 1], re.I):
                        found = lines[i + 1]
                        break
                answers.append(found)
        if len(answers) != count or any(answer is None for answer in answers):
            raise SystemExit(f"Could not extract all official answers: {q['id']} ({answers})")
        expected = [answer_side(answer) for answer in answers]
    if key.get("correct") != expected:
        raise SystemExit(f"Answer-key mismatch for {q['id']}: embedded={key.get('correct')}, CV={expected}")
    if key.get("scoreMap", [])[-1:] != [int(q.get("points", 0))]:
        raise SystemExit(f"Maximum-score mismatch for {q['id']}")

aliases = {
    "vw25-14": "vw25t1-open-14",
    "vw25t2-8": "vw25t2-open-8",
    "ha24-8": "ha24t1-open-8",
    "vw24-1": "vw24t1-open-1",
    "vw24t2-2": "vw24t2-open-2",
}
for alias, source in aliases.items():
    declaration = rf'binaryAnswerKeys\["{re.escape(alias)}"\]\s*=\s*binaryAnswerKeys\["{re.escape(source)}"\]'
    if not re.search(declaration, html):
        raise SystemExit(f"Legacy key alias missing: {alias} -> {source}")

print(f"Verified {len(binary)} binary-question answer keys against the official CvTE correction-scheme PDFs; all answer rows and maximum scores match.")
