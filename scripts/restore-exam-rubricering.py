import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUBRICERING = ROOT / "scripts" / "exam-rubricering.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    rubric_records = load(RUBRICERING)
    rubric = {item["id"]: item for item in rubric_records}
    if len(rubric) != len(rubric_records):
        raise ValueError("Duplicate question IDs in exam-rubricering.json")

    all_ids = set()
    updated = 0
    for filename in ("exam-open.json", "exam-mcq.json"):
        path = ROOT / filename
        records = load(path)
        for record in records:
            question_id = record.get("id")
            if question_id in all_ids:
                raise ValueError(f"Duplicate question ID across inventories: {question_id}")
            all_ids.add(question_id)
            assignment = rubric.get(question_id)
            if assignment is None:
                raise ValueError(f"No curated syllabus assignment for {question_id}")
            for field in ("theme", "concept", "end"):
                value = assignment.get(field)
                if not value or value == "Nog te rubriceren":
                    raise ValueError(f"Invalid {field} assignment for {question_id}")
                record[field] = value
            updated += 1
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    missing = set(rubric) - all_ids
    if missing:
        raise ValueError(f"Rubricering contains IDs absent from generated inventory: {sorted(missing)}")
    if updated != 519 or len(all_ids) != 519:
        raise ValueError(f"Expected exactly 519 classified questions, found {updated}")

    print(f"Restored curated theme, concept and syllabus end-term for all {updated} questions.")


if __name__ == "__main__":
    main()
