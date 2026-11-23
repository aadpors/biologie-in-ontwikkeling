"""Voorstellen voor vraagtype, maximumscore en meerkeuzeopties.

Deze module haalt signalen uit de tekstlaag van de PDF-fragmenten, maar doet
geen definitieve inhoudelijke classificatie. De vraagafbeelding blijft in de
reviewinterface zichtbaar en de gebruiker moet iedere vraag expliciet
controleren. Bij onvoldoende aanwijzingen blijft een veld leeg/onbekend.
"""
from __future__ import annotations

import re
from typing import Any

# Alleen opties aan het begin van een tekstregel tellen mee. Een letter A-E
# midden in lopende tekst mag niet als antwoordoptie worden geïnterpreteerd.
OPTION_LINE = re.compile(r"^\s*([A-E])\s*[.)]\s+(.+?)\s*$", re.IGNORECASE)
# Puntennotaties verschillen tussen examens. De regex vangt expliciete
# vermeldingen, maar gokt niet wanneer het examen geen puntenaantal toont.
POINT_PATTERNS = (
    re.compile(r"\b(?:maximaal|max\.?|maximumscore)\s*(\d{1,2})\s*(?:punt(?:en)?|p)?\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\s*(?:punt(?:en)?|p)\b", re.IGNORECASE),
)


def _normalise_lines(text: str) -> list[str]:
    """Normaliseer PDF-tekstregels zonder de zichtbare volgorde te wijzigen."""
    return [line.strip() for line in text.replace("\r", "\n").split("\n") if line.strip()]


def detect_options(text: str) -> list[dict[str, str]]:
    """Herken mogelijke A-E-opties en vereis een aaneengesloten reeks."""
    found: dict[str, str] = {}
    for line in _normalise_lines(text):
        match = OPTION_LINE.match(line)
        if match:
            letter = match.group(1).upper()
            # Dubbele letters kunnen voorkomen door herhaalde koppen of een
            # tweekolomsopmaak; de eerste tekstregel blijft het voorstel.
            found.setdefault(letter, match.group(2).strip())
    ordered = [letter for letter in "ABCDE" if letter in found]
    if len(ordered) < 2:
        return []
    # Een losse A en C is geen betrouwbare set. Accepteer alleen prefixen
    # van A, B, C, D, E; ontbrekende latere opties zijn wel toegestaan.
    if ordered != list("ABCDE")[:len(ordered)]:
        return []
    return [{"letter": letter, "text": found[letter]} for letter in ordered]


def detect_question_type(text: str, options: list[dict[str, str]]) -> tuple[str, str]:
    """Bepaal een voorzichtig typevoorstel plus een leesbare reden."""
    lowered = text.casefold()
    closed_signals = (
        ("juist of onjuist", "juist/onjuist"),
        ("juist/onjuist", "juist/onjuist"),
        ("wel of niet", "wel/niet"),
        ("wel/niet", "wel/niet"),
        ("meer of minder", "meer/minder"),
        ("meer/minder", "meer/minder"),
        ("hoger of lager", "hoger/lager"),
        ("hoger/lager", "hoger/lager"),
        ("waar of niet waar", "waar/niet waar"),
        ("ja of nee", "ja/nee"),
        ("ja/nee", "ja/nee"),
    )
    for phrase, label in closed_signals:
        if phrase in lowered:
            return "gesloten", f"De tekst bevat de gesloten antwoordvorm {label}."
    # Een vraag kan expliciet meerkeuze zijn zonder dat de antwoordopties als
    # losse tekstregels zijn geëxtraheerd. De vraagformulering is dan genoeg
    # voor een voorstel; het ontbreken van opties verhindert de classificatie niet.
    multiple_choice_signals = (
        "kies het juiste antwoord", "welke van de volgende",
        "welke uitspraak is juist", "welke bewering is juist",
        "wat is het juiste antwoord", "welk antwoord is juist",
    )
    if len(options) >= 3 or any(signal in lowered for signal in multiple_choice_signals):
        reason = ("Er is een aaneengesloten reeks van minimaal drie antwoordopties gevonden."
                  if len(options) >= 3 else
                  "De vraagformulering wijst op een meerkeuzevraag; opties hoeven niet herkend te zijn.")
        return "meerkeuze", reason
    if options:
        return "onbekend", "Er zijn enkele optieachtige regels gevonden, maar geen volledige herkenbare set."
    return "open", "Geen herkenbare meerkeuzeopties of gesloten antwoordvorm gevonden; controleer de afbeelding."


def detect_max_points(text: str) -> tuple[int | None, str]:
    """Lees een expliciet puntenaantal als voorstel; leid het niet af uit tekst."""
    for pattern in POINT_PATTERNS:
        matches = [int(match.group(1)) for match in pattern.finditer(text)]
        # Alleen één eenduidige scorewaarde wordt voorgesteld. Meerdere
        # verschillende getallen kunnen bij subvragen horen en blijven leeg.
        unique = sorted(set(matches))
        if len(unique) == 1 and 0 <= unique[0] <= 20:
            return unique[0], "Expliciete puntenvermelding in het vraagfragment."
        if len(unique) > 1:
            return None, "Meerdere mogelijke puntenaantallen gevonden; handmatige controle nodig."
    return None, "Geen eenduidige puntenvermelding in het vraagfragment gevonden."


def analyse_questions(fragment_result: dict[str, Any]) -> dict[str, Any]:
    """Maak per vraag een bewerkbaar voorstel, gekoppeld aan de afbeelding."""
    questions = []
    for question in fragment_result.get("questions", []):
        text = question.get("extracted_text", "")
        options = detect_options(text)
        question_type, type_reason = detect_question_type(text, options)
        max_points, points_reason = detect_max_points(text)
        questions.append({
            "question_number": question["question_number"],
            "question_type": question_type,
            "max_points": max_points,
            "options": options,
            "type_reason": type_reason,
            "points_reason": points_reason,
            "extracted_text": text,
            "segments": question["segments"],
            "reviewed": False,
        })
    return {"question_count": len(questions), "questions": questions}


def validate_question_analysis(payload: dict[str, Any], expected_numbers: set[int]) -> dict[str, Any]:
    """Valideer de handmatig gecontroleerde type-/puntengegevens."""
    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise ValueError("De gecontroleerde vragen ontbreken.")
    cleaned: list[dict[str, Any]] = []
    seen: set[int] = set()
    allowed_types = {"meerkeuze", "gesloten", "open", "onbekend"}
    for item in questions:
        if not isinstance(item, dict):
            raise ValueError("Een vraaganalyse heeft een ongeldig formaat.")
        number = item.get("question_number")
        if not isinstance(number, int) or number not in expected_numbers or number in seen:
            raise ValueError("Een vraagnummer ontbreekt, is dubbel of hoort niet bij dit examen.")
        seen.add(number)
        question_type = item.get("question_type")
        if question_type not in allowed_types:
            raise ValueError(f"Ongeldig vraagtype bij vraag {number}.")
        points = item.get("max_points")
        if points is not None and (not isinstance(points, int) or not 0 <= points <= 20):
            raise ValueError(f"Ongeldig maximumaantal punten bij vraag {number}.")
        options = item.get("options", [])
        if (not isinstance(options, list) or len(options) > 5 or
                any(not isinstance(option, dict) or option.get("letter") not in list("ABCDE")
                    or not isinstance(option.get("text"), str) or not option.get("text", "").strip()
                    for option in options) or
                len({option["letter"] for option in options if isinstance(option, dict) and "letter" in option}) != len(options)):
            raise ValueError(f"Ongeldige of dubbel genummerde antwoordopties bij vraag {number}.")
        cleaned.append({"question_number": number, "question_type": question_type,
                        "max_points": points, "options": options, "reviewed": bool(item.get("reviewed"))})
    if seen != expected_numbers:
        missing = sorted(expected_numbers - seen)
        raise ValueError(f"Niet alle vragen zijn opgenomen in de controle: {missing}.")
    reviewed_count = sum(item["reviewed"] for item in cleaned)
    return {"questions": cleaned, "reviewed_count": reviewed_count,
            "reviewed_all_questions": reviewed_count == len(cleaned)}
