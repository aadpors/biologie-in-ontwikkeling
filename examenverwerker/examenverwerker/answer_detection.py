"""Voorstellen voor antwoorden op basis van de gekoppelde CV-fragmenten.

Deze module maakt geen definitieve antwoordbeslissingen. Een correctievoorschrift
kan antwoorden in verschillende tabelindelingen presenteren; daarom herkennen
we alleen patronen die voldoende specifiek zijn en bewaren we de volledige
brontekst. Bij twijfel blijft het antwoordtype 'handmatig' en moet de docent
het fragment zelf beoordelen.
"""
from __future__ import annotations

import re
from typing import Any

# Veel Cito-correctievoorschriften plaatsen het antwoord en de score naast
# elkaar. Deze patronen zijn bewust strikt: een losse letter midden in tekst
# is geen bewijs voor een meerkeuzeantwoord.
MC_LINE = re.compile(r"^\s*([A-E])\s+([012])\s*$", re.IGNORECASE)
MC_INLINE = re.compile(r"^\s*([A-E])\s{2,}([012])\s*$", re.IGNORECASE)
# Sommige PDF-tekstextracties voegen de vraagnummerkolom, antwoordkolom en
# scorekolom samen tot één regel, bijvoorbeeld "2 B 2". Binnen het fragment
# van vraag 2 is dat een eenduidig patroon; buiten dat fragment gebruiken we
# deze regex niet om te voorkomen dat een willekeurige tabelrij wordt gelezen.
MC_TABLE_LINE = re.compile(r"^\s*(\d{1,2})\s+([A-E])\s+([012])\s*$", re.IGNORECASE)
CLOSED_LINE = re.compile(r"^\s*(\d{1,2})\s+(juist|onjuist|wel|geen|niet|meer|minder|hoger|lager|ja|nee)\s*$", re.IGNORECASE)
MAX_SCORE = re.compile(r"maximumscore\s*(\d{1,2})", re.IGNORECASE)


def _lines(text: str) -> list[str]:
    """Behoud de volgorde van de CV-tekst, maar negeer lege regels."""
    return [line.strip() for line in text.replace("\r", "\n").splitlines() if line.strip()]


def detect_cv_max_points(text: str, question_number: int | None = None) -> int | None:
    """Lees de expliciete maximumscore uit rubric of MC-scorekolom."""
    maximum = MAX_SCORE.search(text)
    if maximum:
        return int(maximum.group(1))
    for line in _lines(text):
        match = MC_LINE.fullmatch(line) or MC_INLINE.fullmatch(line)
        if match:
            return int(match.group(2))
        table_match = MC_TABLE_LINE.fullmatch(line)
        if table_match and question_number is not None and int(table_match.group(1)) == question_number:
            return int(table_match.group(3))
    return None


def detect_cv_answer(text: str, question_number: int | None = None) -> dict[str, Any]:
    """Herken alleen expliciete antwoordnotaties uit één CV-vraagfragment."""
    lines = _lines(text)
    if not lines:
        return {"answer_kind": "handmatig", "answer_text": "", "confidence": "laag",
                "reason": "Geen selecteerbare tekstlaag in het CV-fragment."}

    # In het correctievoorschrift kunnen vóór het antwoord een maximumscore,
    # titel of korte beoordelingsinstructie staan. We scannen alle regels, maar
    # bewaren alleen een kandidaat die exact aan de notatie voldoet.
    mc_candidates: list[str] = []
    for line in lines:
        match = MC_LINE.fullmatch(line) or MC_INLINE.fullmatch(line)
        if match:
            mc_candidates.append(match.group(1).upper())
            continue
        table_match = MC_TABLE_LINE.fullmatch(line)
        if table_match and question_number is not None and int(table_match.group(1)) == question_number:
            mc_candidates.append(table_match.group(2).upper())
    if len(set(mc_candidates)) == 1:
        return {"answer_kind": "meerkeuze", "answer_text": mc_candidates[0],
                "confidence": "middel", "reason": "Een losse antwoordletter met scorekolom is gevonden."}
    if len(set(mc_candidates)) > 1:
        return {"answer_kind": "handmatig", "answer_text": "", "confidence": "laag",
                "reason": "Meerdere mogelijke antwoordletters gevonden; handmatige controle nodig."}

    closed: list[tuple[int, str]] = []
    for line in lines:
        match = CLOSED_LINE.fullmatch(line)
        if match:
            closed.append((int(match.group(1)), match.group(2).casefold()))
    if closed:
        # Gesloten antwoorden bestaan vaak uit genummerde uitspraken. Houd
        # alleen de volgorde en de labels vast; interpreteer geen scoretabellen.
        unique = {}
        for number, value in closed:
            unique.setdefault(number, value)
        answer = "\n".join(f"{number}. {value}" for number, value in sorted(unique.items()))
        return {"answer_kind": "gesloten", "answer_text": answer,
                "confidence": "middel", "reason": "Genummerde gesloten antwoorden (zoals juist/onjuist) herkend."}

    # Open antwoorden zijn meestal beoordelingscriteria, geen enkelvoudig
    # antwoord. De volledige CV-tekst wordt daarom aangeboden als rubrictekst.
    # De gebruiker moet bevestigen dat de volledige criteria zichtbaar zijn.
    content_lines = [line for line in lines if not MAX_SCORE.search(line)]
    return {"answer_kind": "open", "answer_text": "\n".join(content_lines),
            "confidence": "laag", "reason": "Geen eenduidig gesloten antwoordpatroon; CV-tekst als beoordelingsvoorstel."}


def analyse_answers(cv_fragments: dict[str, Any], question_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    """Koppel per vraag een voorzichtig antwoordvoorstel aan het CV-fragment."""
    expected_types = {item["question_number"]: item.get("question_type")
                      for item in (question_analysis or {}).get("questions", [])}
    results = []
    for fragment in cv_fragments.get("questions", []):
        number = int(fragment["question_number"])
        detected = detect_cv_answer(fragment.get("extracted_text", ""), number)
        expected = expected_types.get(number)
        # Wanneer de opgave als meerkeuze is geclassificeerd, maar het CV geen
        # enkele letter oplevert, verlagen we de zekerheid niet kunstmatig:
        # we markeren expliciet dat een visuele controle nodig is.
        if expected == "meerkeuze" and detected["answer_kind"] != "meerkeuze":
            detected = {**detected, "confidence": "laag",
                        "reason": detected["reason"] + " De opgave is als meerkeuze herkend; controleer het CV."}
        cv_max_points = detect_cv_max_points(fragment.get("extracted_text", ""), number)
        opgaven_question = next((item for item in (question_analysis or {}).get("questions", [])
                                 if item.get("question_number") == number), {})
        opgaven_points = opgaven_question.get("max_points")
        results.append({
            "question_number": number,
            "cv_max_points": cv_max_points,
            "opgaven_max_points": opgaven_points,
            "points_match": (cv_max_points == opgaven_points) if cv_max_points is not None and opgaven_points is not None else None,
            "answer_kind": detected["answer_kind"],
            "answer_text": detected["answer_text"],
            "confidence": detected["confidence"],
            "reason": detected["reason"],
            "expected_question_type": expected,
            "segments": fragment.get("segments", []),
            "reviewed": False,
        })
    return {"question_count": len(results), "questions": results,
            "document": cv_fragments.get("document")}


def validate_answer_review(payload: dict[str, Any], expected_numbers: set[int]) -> dict[str, Any]:
    """Valideer dat ieder CV-antwoord afzonderlijk is beoordeeld."""
    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise ValueError("De antwoordcontrole ontbreekt.")
    cleaned = []
    seen: set[int] = set()
    allowed = {"meerkeuze", "gesloten", "open", "handmatig"}
    for item in questions:
        if not isinstance(item, dict):
            raise ValueError("Een antwoord heeft een ongeldig formaat.")
        number = item.get("question_number")
        if not isinstance(number, int) or number not in expected_numbers or number in seen:
            raise ValueError("Een vraagnummer ontbreekt, is dubbel of hoort niet bij het examen.")
        seen.add(number)
        kind = item.get("answer_kind")
        answer = item.get("answer_text")
        if kind not in allowed or not isinstance(answer, str) or len(answer) > 30000:
            raise ValueError(f"Ongeldig antwoord bij vraag {number}.")
        cv_points = item.get("cv_max_points")
        opgaven_points = item.get("opgaven_max_points")
        if cv_points is not None and (not isinstance(cv_points, int) or not 0 <= cv_points <= 20):
            raise ValueError(f"Ongeldige CV-score bij vraag {number}.")
        if opgaven_points is not None and (not isinstance(opgaven_points, int) or not 0 <= opgaven_points <= 20):
            raise ValueError(f"Ongeldige opgavenscore bij vraag {number}.")
        supplement_pages = item.get("supplement_pages", [])
        if not isinstance(supplement_pages, list) or len(supplement_pages) > 20:
            raise ValueError(f"Ongeldige CV-aanvulling bij vraag {number}.")
        cleaned.append({"question_number": number, "answer_kind": kind,
                        "answer_text": answer, "cv_max_points": cv_points,
                        "opgaven_max_points": opgaven_points,
                        "supplement_pages": supplement_pages,
                        "points_match": (cv_points == opgaven_points) if cv_points is not None and opgaven_points is not None else None,
                        "reviewed": bool(item.get("reviewed"))})
    if seen != expected_numbers:
        raise ValueError(f"Niet alle CV-vragen zijn opgenomen: {sorted(expected_numbers - seen)}.")
    reviewed_count = sum(item["reviewed"] for item in cleaned)
    return {"questions": cleaned, "reviewed_count": reviewed_count,
            "reviewed_all_questions": reviewed_count == len(cleaned)}
