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
    """Herken antwoordopties in zowel compacte als regel-voor-regel-PDF-tekst.

    PDF-tekstextractie zet de letter en de antwoordtekst niet altijd op
    dezelfde regel. Soms staat er bijvoorbeeld eerst alleen "A." en pas op
    de volgende regel de antwoordtekst. Ook kan een optie met een haakje in
    plaats van een punt beginnen. Deze parser herkent die varianten, maar
    accepteert alleen een aaneengesloten reeks vanaf A om toevallige letters
    in gewone zinnen niet als antwoordopties te behandelen.
    """
    lines = _normalise_lines(text)
    found: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        # Gebruik eerst de gebruikelijke notatie: "A. antwoord" of "A) antwoord".
        match = re.match(r"^\s*([A-E])[.)]?\s+(.+?)\s*$", line, re.IGNORECASE)
        if match:
            letter, option_text = match.group(1).upper(), match.group(2).strip()
            if len(option_text) >= 2:
                found.setdefault(letter, option_text)
            index += 1
            continue

        # In sommige PDF's staat de letter als afzonderlijke tekstregel.
        # Neem dan de eerstvolgende regel als antwoordtekst, tenzij die zelf
        # al een volgende optieletter is.
        standalone = re.fullmatch(r"\s*([A-E])[.)]?\s*", line, re.IGNORECASE)
        if standalone and index + 1 < len(lines):
            next_line = lines[index + 1]
            next_is_option = bool(re.match(r"^\s*[A-E][.)]?\s+", next_line, re.IGNORECASE)
                                   or re.fullmatch(r"\s*[A-E][.)]?\s*", next_line, re.IGNORECASE))
            if not next_is_option and len(next_line.strip()) >= 2:
                found.setdefault(standalone.group(1).upper(), next_line.strip())
                index += 2
                continue
        index += 1

    ordered = [letter for letter in "ABCDE" if letter in found]
    if len(ordered) < 2 or ordered != list("ABCDE")[:len(ordered)]:
        return []
    return [{"letter": letter, "text": found[letter]} for letter in ordered]


def detect_closed_answer_form(text: str) -> str | None:
    """Benoem de concrete gesloten antwoordvorm die in de vraag wordt genoemd.

    Dit is aanvullende informatie naast het algemene vraagtype 'gesloten'.
    De functie doet geen uitspraak over welk antwoord inhoudelijk juist is;
    zij benoemt uitsluitend de antwoordcategorieën die de vraag zelf noemt.
    """
    lowered = re.sub(r"\s+", " ", text.casefold())
    forms = (
        (r"juist\s*(?:/|of)\s*onjuist|waar\s*(?:/|of)\s*niet waar", "juist / onjuist"),
        (r"wel\s*(?:/|of)\s*niet", "wel / niet"),
        (r"wel\s*(?:/|of)\s*geen", "wel / geen"),
        (r"hoger\s*(?:,|/|of en)\s*gelijk\s*(?:,|/|of en)\s*lager|hoger,? gelijk(?: aan)?,? of lager", "hoger / gelijk / lager"),
        (r"lager\s*(?:,|/|of en)\s*gelijk\s*(?:,|/|of en)\s*hoger", "lager / gelijk / hoger"),
        (r"meer\s*(?:,|/|of en)\s*evenveel\s*(?:,|/|of en)\s*minder", "meer / gelijk / minder"),
        (r"meer\s*(?:/|of)\s*minder", "meer / minder"),
        (r"ja\s*(?:/|of)\s*nee", "ja / nee"),
        (r"juist\s*(?:/|of)\s*onjuist", "juist / onjuist"),
    )
    for pattern, label in forms:
        if re.search(pattern, lowered):
            return label
    return None


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
        ("hoger, gelijk of lager", "hoger/gelijk/lager"),
        ("hoger / gelijk / lager", "hoger/gelijk/lager"),
        ("hoger of lager", "hoger/lager"),
        ("hoger/lager", "hoger/lager"),
        ("meer, evenveel of minder", "meer/gelijk/minder"),
        ("meer, gelijk of minder", "meer/gelijk/minder"),
        ("groter, gelijk of kleiner", "groter/gelijk/kleiner"),
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
    if len(options) >= 2 or any(signal in lowered for signal in multiple_choice_signals):
        reason = ("Er is een aaneengesloten reeks van minimaal twee antwoordopties gevonden."
                  if len(options) >= 2 else
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
        closed_answer_form = detect_closed_answer_form(text) if question_type == "gesloten" else None
        max_points, points_reason = detect_max_points(text)
        questions.append({
            "question_number": question["question_number"],
            "question_type": question_type,
            "closed_answer_form": closed_answer_form,
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
