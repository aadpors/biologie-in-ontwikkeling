"""Voorstellen voor vraagtype, maximumscore en meerkeuzeopties.

Deze module haalt signalen uit de tekstlaag van de PDF-fragmenten, maar doet
geen definitieve inhoudelijke classificatie. De vraagafbeelding blijft in de
reviewinterface zichtbaar en de gebruiker moet iedere vraag expliciet
controleren. Bij onvoldoende aanwijzingen blijft een veld leeg/onbekend.
"""
from __future__ import annotations

import re
from pathlib import Path
from statistics import median
from typing import Any

# Alleen opties aan het begin van een tekstregel tellen mee. Een letter A-F
# midden in lopende tekst mag niet als antwoordoptie worden geïnterpreteerd.
OPTION_LINE = re.compile(r"^\s*([A-F])\s*[.)]\s+(.+?)\s*$", re.IGNORECASE)
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
    """Herken antwoordopties in de meest voorkomende PDF-tekstindelingen.

    PDF-extractie is niet layoutvast: letters kunnen op een eigen regel
    staan, opties kunnen achter elkaar op één regel staan of letters kunnen
    tussen haakjes of met een dubbele punt zijn vormgegeven. Daarom combineren
    we expliciete A-F-markeringen met een regelgerichte terugvaloptie. Een
    voorstel wordt alleen geaccepteerd bij minimaal twee opeenvolgende opties
    vanaf A.
    """
    normalised_text = text.replace("\r", "\n")
    lines = _normalise_lines(normalised_text)
    found: dict[str, str] = {}

    # Herken expliciete markeringen zoals 'A. tekst', '(A) tekst', 'A) tekst'
    # en 'A: tekst'. Door tekst tussen opeenvolgende markeringen te nemen,
    # blijven opties herkenbaar wanneer de PDF ze op één regel of in kolommen
    # achter elkaar uitleest.
    marker_pattern = re.compile(
        r"(?<![A-Za-z0-9])(?:\(([A-F])\)|([A-F])\s*[.):])\s*",
        re.IGNORECASE,
    )
    matches = list(marker_pattern.finditer(normalised_text))
    for index, match in enumerate(matches):
        letter = (match.group(1) or match.group(2)).upper()
        if letter in found:
            continue
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalised_text)
        option_text = normalised_text[content_start:content_end].strip(" \t\r\n;|")
        if len(option_text) >= 1:
            found[letter] = option_text

    # Regelgerichte fallback voor PDF's die alleen een letter op een regel
    # zetten en de antwoordtekst op de volgende regel plaatsen. Deze route
    # vult alleen ontbrekende letters aan en overschrijft geen expliciet
    # herkende optie uit de tekststroom.
    index = 0
    while index < len(lines):
        line = lines[index]
        compact = re.match(r"^\s*([A-F])[.)]?\s+(.+?)\s*$", line, re.IGNORECASE)
        if compact:
            letter, option_text = compact.group(1).upper(), compact.group(2).strip()
            if len(option_text) >= 1:
                found.setdefault(letter, option_text)
            index += 1
            continue

        standalone = re.fullmatch(r"\s*([A-F])[.)]?\s*", line, re.IGNORECASE)
        if standalone and index + 1 < len(lines):
            next_line = lines[index + 1]
            next_is_option = bool(
                re.match(r"^\s*[A-F](?:[.)]|:)\s*", next_line, re.IGNORECASE)
                or re.fullmatch(r"\s*\(?[A-F]\)?[.)]?\s*", next_line, re.IGNORECASE)
            )
            if not next_is_option and len(next_line.strip()) >= 2:
                found.setdefault(standalone.group(1).upper(), next_line.strip())
                index += 2
                continue
        index += 1

    # Een losse C of D in lopende tekst is geen meerkeuzereeks. Alleen een
    # aaneengesloten prefix vanaf A wordt als betrouwbaar voorstel getoond.
    ordered = [letter for letter in "ABCDEF" if letter in found]
    if len(ordered) < 2 or ordered != list("ABCDEF")[:len(ordered)]:
        return []
    return [{"letter": letter, "text": found[letter]} for letter in ordered]



# De OCR-engine wordt pas geladen wanneer de PDF-tekstlaag onvoldoende
# informatie bevat. Zo blijft de normale route snel en worden onnodige
# modelinitialisaties tijdens het openen van stap 4 voorkomen.
_OCR_ENGINE = None
_OCR_INITIALISATION_ATTEMPTED = False


def _get_ocr_engine():
    """Initialiseer RapidOCR één keer en hergebruik de engine per proces."""
    global _OCR_ENGINE, _OCR_INITIALISATION_ATTEMPTED
    if _OCR_INITIALISATION_ATTEMPTED:
        return _OCR_ENGINE

    _OCR_INITIALISATION_ATTEMPTED = True
    try:
        # RapidOCR draait lokaal. Er worden geen vraagafbeeldingen naar een
        # externe dienst verstuurd; de OCR-modellen worden lokaal uitgevoerd.
        # De actuele RapidOCR-distributie bundelt de standaardmodellen. ONNX
        # Runtime voert de herkenning lokaal op de computer van de docent uit.
        from rapidocr import RapidOCR
        _OCR_ENGINE = RapidOCR()
    except Exception:
        # OCR is een aanvullende herkenningslaag. Een ontbrekende of niet
        # laadbare OCR-installatie mag de hele examenverwerking niet blokkeren.
        _OCR_ENGINE = None
    return _OCR_ENGINE


def _ocr_image_text(image_paths: list[str | Path]) -> str:
    """Lees de zichtbare tekst uit vraagfragmentafbeeldingen met lokale OCR.

    De PDF-tekstlaag kan antwoordopties missen wanneer letters en teksten in
    aparte kolommen, losse tekstblokken of als afbeelding zijn opgeslagen.
    Daarom wordt alleen wanneer de tekstlaag onvoldoende opties oplevert ook
    de daadwerkelijke vraagafbeelding gelezen. OCR blijft een voorstel: de
    docent ziet en beoordeelt altijd het oorspronkelijke fragment in stap 4.
    """
    engine = _get_ocr_engine()
    if engine is None:
        return ""

    recognised_lines: list[str] = []
    for image_path in image_paths:
        path = Path(image_path)
        if not path.is_file():
            continue
        try:
            response = engine(str(path))
        except Exception:
            # Een beschadigd of niet-ondersteund fragment mag andere vragen
            # niet verhinderen; ga door met de volgende afbeelding.
            continue

        # De actuele RapidOCR-versie retourneert een object met aparte
        # arrays voor bounding boxes en herkende tekst. Ondersteun daarnaast
        # het oudere tupleformaat, zodat de helper ook met eerdere releases
        # en eenvoudige testdubbels kan blijven werken.
        if hasattr(response, "boxes") and hasattr(response, "txts"):
            detections = list(zip(response.boxes, response.txts))
        else:
            detections = response[0] if isinstance(response, tuple) else response
        if not detections:
            continue

        entries: list[dict[str, float | str]] = []
        for detection in detections:
            if not isinstance(detection, (list, tuple)) or len(detection) < 2:
                continue
            box, detected_text = detection[0], str(detection[1]).strip()
            if not detected_text:
                continue
            try:
                points = box.tolist() if hasattr(box, "tolist") else box
                x_values = [float(point[0]) for point in points]
                y_values = [float(point[1]) for point in points]
            except (TypeError, ValueError, IndexError):
                # Bij een afwijkend OCR-resultaat behouden we de tekst, maar
                # gebruiken we de oorspronkelijke herkenningsvolgorde.
                entries.append({"x": float(len(entries)), "y": float(len(entries)),
                                "height": 1.0, "text": detected_text})
                continue
            entries.append({
                "x": min(x_values),
                "y": (min(y_values) + max(y_values)) / 2,
                "height": max(1.0, max(y_values) - min(y_values)),
                "text": detected_text,
            })

        if not entries:
            continue

        # Ordeneer OCR-fragmenten op visuele leesvolgorde. Antwoordletters en
        # antwoordteksten staan in sommige examens in aparte kolommen; door
        # eerst op regelhoogte en daarna op x-positie te sorteren, komen die
        # onderdelen weer op dezelfde tekstregel terecht.
        line_tolerance = max(5.0, median(float(item["height"]) for item in entries) * 0.65)
        entries.sort(key=lambda item: (float(item["y"]), float(item["x"])))
        lines: list[dict[str, Any]] = []
        for entry in entries:
            matching_line = next(
                (line for line in reversed(lines)
                 if abs(float(line["y"]) - float(entry["y"])) <= line_tolerance),
                None,
            )
            if matching_line is None:
                lines.append({"y": float(entry["y"]), "items": [entry]})
            else:
                matching_line["items"].append(entry)
                matching_line["y"] = sum(float(item["y"]) for item in matching_line["items"]) / len(matching_line["items"])

        for line in lines:
            line["items"].sort(key=lambda item: float(item["x"]))
            recognised_lines.append(" ".join(str(item["text"]) for item in line["items"]))

    return "\n".join(recognised_lines)

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
        (r"meer\s*(?:,|/|of en)\s*(?:evenveel|gelijk)\s*(?:,|/|of en)\s*minder", "meer / gelijk / minder"),
        (r"groter\s*(?:,|/|of en)\s*gelijk\s*(?:,|/|of en)\s*kleiner", "groter / gelijk / kleiner"),
        (r"toegenomen\s*(?:,|/|of en)\s*gelijk gebleven\s*(?:,|/|of en)\s*afgenomen", "toegenomen / gelijk gebleven / afgenomen"),
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
        "kies het juiste antwoord", "kies de juiste optie",
        "welke van de volgende", "welke van onderstaande",
        "welke uitspraak is juist", "welke uitspraak is onjuist",
        "welke bewering is juist", "welke bewering is onjuist",
        "welke combinatie is juist", "welke combinatie is correct",
        "welke volgorde is juist", "wat is de juiste volgorde",
        "wat is het juiste antwoord", "welk antwoord is juist",
        "welke optie is juist", "welke letter hoort",
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


def _should_run_option_ocr(text: str, options: list[dict[str, str]]) -> bool:
    """Bepaal of OCR waarschijnlijk extra antwoordopties kan opleveren.

    Een herkende reeks van minimaal twee opeenvolgende opties hoeft niet
    opnieuw door OCR. Bij een onvolledige PDF-tekstlaag is OCR wel zinvol
    wanneer er antwoordlabels of een expliciete meerkeuzeformulering staan.
    Een volledig lege tekstlaag kan wijzen op een gescand fragment en krijgt
    daarom eveneens een OCR-poging.
    """
    if len(options) >= 2:
        return False
    if not text.strip():
        return True

    # Labels zonder leesteken komen voor in officiële examens (bijvoorbeeld
    # "A 9" en "B 19"). Ook een los label op een eigen regel is een aanwijzing.
    has_option_label = bool(
        re.search(r"(?m)^\s*[A-F](?:[.) :]\s*|\s+\S)", text, re.IGNORECASE)
    )
    has_multiple_choice_wording = any(
        phrase in text.casefold()
        for phrase in (
            "kies het juiste antwoord", "kies de juiste optie",
            "welke van de volgende", "welke van onderstaande",
            "welke uitspraak is juist", "welke uitspraak is onjuist",
            "welke bewering is juist", "welke bewering is onjuist",
            "welke combinatie is juist", "welke combinatie is correct",
            "wat is het juiste antwoord", "welk antwoord is juist",
            "welke optie is juist",
        )
    )
    # De formulering kan een tussenzin bevatten, zoals "Welke uitspraak
    # over fotosynthese is juist?". Herken daarom ook de combinatie van
    # vraagwoord + onderwerp + beoordelingswoord; een exacte vaste frase
    # zou deze veelvoorkomende meerkeuzevraag missen.
    has_flexible_statement_wording = bool(re.search(
        r"\bwelke\s+uitspraak\b.*\b(?:is\s+)?(?:juist|onjuist|correct)\b",
        text,
        re.IGNORECASE | re.DOTALL,
    ))
    return has_option_label or has_multiple_choice_wording or has_flexible_statement_wording


def analyse_questions(fragment_result: dict[str, Any]) -> dict[str, Any]:
    """Maak per vraag een bewerkbaar voorstel, gekoppeld aan de afbeelding."""
    questions = []
    for question in fragment_result.get("questions", []):
        text = question.get("extracted_text", "")
        options = detect_options(text)
        ocr_text = ""

        # De PDF-tekstlaag is de snelste en doorgaans nauwkeurigste bron.
        # OCR op ieder vraagfragment maakte stap 4 onnodig traag: ook gewone
        # open vragen werden telkens door het OCR-model gehaald. We starten
        # OCR daarom alleen als de tekstlaag geen bruikbare optie oplevert én
        # er een concrete aanwijzing is voor meerkeuze (een antwoordlabel of
        # bekende meerkeuzeformulering), of wanneer de tekstlaag leeg is.
        # Een herkende reeks met twee of meer opties hoeft niet opnieuw door
        # OCR; het aantal opties alleen is geen reden voor een tweede bron.
        if _should_run_option_ocr(text, options) and question.get("image_paths"):
            ocr_text = _ocr_image_text(question["image_paths"])
            ocr_options = detect_options(ocr_text)
            if len(ocr_options) > len(options):
                options = ocr_options

        # Combineer beide bronnen uitsluitend voor de typeherkenning. De
        # originele PDF-tekst blijft apart bewaard en wordt niet overschreven
        # door mogelijke OCR-fouten.
        analysis_text = "\n".join(part for part in (text, ocr_text) if part)
        question_type, type_reason = detect_question_type(analysis_text, options)
        if ocr_text and len(options) >= 2:
            type_reason += " De antwoordopties zijn aanvullend herkend vanuit de vraagafbeelding."
        closed_answer_form = detect_closed_answer_form(analysis_text) if question_type == "gesloten" else None
        max_points, points_reason = detect_max_points(text)
        if max_points is None and ocr_text:
            ocr_points, ocr_reason = detect_max_points(ocr_text)
            if ocr_points is not None:
                max_points, points_reason = ocr_points, ocr_reason + " (herkend vanuit de vraagafbeelding via OCR.)"
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
        if (not isinstance(options, list) or len(options) > 6 or
                any(not isinstance(option, dict) or option.get("letter") not in list("ABCDEF")
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
