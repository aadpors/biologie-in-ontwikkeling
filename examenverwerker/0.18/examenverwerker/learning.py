"""Zelflerende detectie op basis van expliciete docentcorrecties.

Deze module gebruikt geen ondoorzichtig model en wijzigt geen brongegevens.
Iedere review levert gelabelde voorbeelden op. Op basis daarvan berekent
het systeem per detectiekenmerk hoe vaak een voorstel is geaccepteerd.
Pas na voldoende voorbeelden krijgt een kenmerk invloed op de rangschikking;
een menselijke correctie wordt dus niet op basis van één examen tot algemene
regel verheven.

De eerste leerlaag richt zich op vraagstarts. Dezelfde opslagstructuur kan
worden gebruikt voor fragmentgrenzen en contextgroepen.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


MIN_EXAMPLES_PER_FEATURE = 5
# Fragmentgrenzen leveren per examen meerdere concrete, handmatig gecorrigeerde
# voorbeelden op. Voor offsets is daarom een kleinere, aparte drempel logisch:
# drie vraagfragmenten zijn al drie observaties (geen drie examens). De offset
# wordt bovendien beperkt tot een robuuste mediaan en blijft een voorstel.
MIN_BOUNDARY_EXAMPLES = 3


def _band(value: float, width: float = 0.05) -> str:
    """Maak een stabiele band voor een genormaliseerde positie."""
    return str(round(float(value) / width) * width)


def question_start_features(candidate: dict[str, Any], page: dict[str, Any] | None = None) -> dict[str, str]:
    """Vertaal een kandidaat naar uitlegbare, layout-onafhankelijke kenmerken.

    Absolute pixelcoördinaten worden bewust niet opgeslagen: die zijn
    afhankelijk van paginaformaat en renderinstellingen. We gebruiken
    genormaliseerde posities en expliciete detectorwaarschuwingen.
    """
    bbox = candidate.get("pdf_bbox") or [0, 0, 0, 0]
    page_width = float((page or {}).get("width") or 1)
    page_height = float((page or {}).get("height") or 1)
    x = float(bbox[0]) / page_width
    y = float(bbox[1]) / page_height
    text = str(candidate.get("text", "")).strip()
    if candidate.get("source") == "manual":
        form = "manual"
    elif candidate.get("sequence_warning"):
        form = "sequence_warning"
    elif candidate.get("score_prefix"):
        form = "score_prefix"
    elif text and text.split()[0].rstrip(".)").isdigit() and len(text.split()) > 1:
        form = "number_with_text"
    else:
        form = "standalone_number"
    font_size = float(candidate.get("font_size") or 0)
    return {
        "form": form,
        "x_band": _band(x, 0.05),
        "y_zone": "top" if y < 0.12 else "bottom" if y > 0.82 else "body",
        "font_band": "small" if font_size < 9 else "normal" if font_size < 14 else "large",
        "duplicate": "yes" if candidate.get("duplicate_number") else "no",
    }


def build_learning_profile(examples: list[dict[str, Any]]) -> dict[str, Any]:
    """Bereken transparante acceptatiepercentages per kenmerk.

    Alleen gelabelde, expliciet opgeslagen reviews tellen mee. Onbeoordeelde
    kandidaten en automatisch gegenereerde voorstellen tellen niet mee.
    """
    totals: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for example in examples:
        label = example.get("accepted")
        features = example.get("features")
        if not isinstance(label, bool) or not isinstance(features, dict):
            continue
        for feature, value in features.items():
            bucket = totals[(str(feature), str(value))]
            bucket[0] += 1
            bucket[1] += int(label)

    learned = []
    for (feature, value), (count, accepted) in sorted(totals.items()):
        rate = accepted / count
        learned.append({
            "feature": feature,
            "value": value,
            "examples": count,
            "accepted": accepted,
            "rejected": count - accepted,
            "acceptance_rate": round(rate, 3),
            "eligible": count >= MIN_EXAMPLES_PER_FEATURE,
        })
    return {
        "example_count": len(examples),
        "minimum_examples": MIN_EXAMPLES_PER_FEATURE,
        "learned_features": learned,
        "active_feature_count": sum(item["eligible"] for item in learned),
    }


def learned_adjustment(features: dict[str, str], profile: dict[str, Any]) -> dict[str, Any]:
    """Geef een beperkte, uitlegbare correctie op basis van voldoende feedback.

    De correctie verandert nooit een kandidaat rechtstreeks in goedgekeurd of
    afgewezen. De detector kan de uitkomst uitsluitend gebruiken als extra
    rangschikkingssignaal; de bestaande sequentie- en visuele controles blijven
    ongewijzigd.
    """
    index = {
        (item["feature"], item["value"]): item
        for item in profile.get("learned_features", [])
        if item.get("eligible")
    }
    evidence = []
    scores = []
    for feature, value in features.items():
        item = index.get((feature, value))
        if item:
            evidence.append({
                "feature": feature,
                "value": value,
                "acceptance_rate": item["acceptance_rate"],
                "examples": item["examples"],
            })
            scores.append(float(item["acceptance_rate"]))
    if not scores:
        return {"score_adjustment": 0.0, "evidence": [], "learning_active": False}
    # Beperk de invloed tot maximaal +/- 0,15. Zo kan feedback helpen
    # rangschikken, maar nooit harde detectorregels overrulen.
    mean_rate = sum(scores) / len(scores)
    adjustment = max(-0.15, min(0.15, (mean_rate - 0.5) * 0.3))
    return {
        "score_adjustment": round(adjustment, 3),
        "evidence": evidence,
        "learning_active": True,
    }



def _median(values: list[float]) -> float | None:
    """Bereken een mediaan zonder externe numerieke afhankelijkheid."""
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 2)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)


def build_boundary_learning_profile(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Leer typische handmatige grenscorrecties per documenttype.

    De offsets zijn uitgedrukt in PDF-punten ten opzichte van het automatische
    voorstel. Een mediaan is robuuster dan een gemiddelde wanneer één
    uitzonderlijk grote correctie wordt aangebracht.
    """
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if not record.get("stage", "").startswith("fragment_boundaries:"):
            continue
        document_type = record["stage"].split(":", 1)[1]
        by_type[document_type].extend(record.get("accepted", {}).get("examples", []))
    result = {}
    for document_type, examples in by_type.items():
        starts = [float(item["start_offset"]) for item in examples if isinstance(item.get("start_offset"), (int, float))]
        ends = [float(item["end_offset"]) for item in examples if isinstance(item.get("end_offset"), (int, float))]
        result[document_type] = {
            "examples": len(examples),
            "active": len(examples) >= MIN_BOUNDARY_EXAMPLES,
            "median_start_offset": _median(starts),
            "median_end_offset": _median(ends),
        }
    return result


def build_context_learning_profile(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Leer terugkerende correcties in de vraagbereiken van contextgroepen."""
    changes = []
    for record in records:
        if record.get("stage") != "fragment_review":
            continue
        for item in record.get("summary", {}).get("context_range_changes", []):
            if all(isinstance(item.get(key), int) for key in (
                "suggested_from", "suggested_to", "accepted_from", "accepted_to"
            )):
                changes.append({
                    "start_shift": item["accepted_from"] - item["suggested_from"],
                    "end_shift": item["accepted_to"] - item["suggested_to"],
                })
    return {
        "examples": len(changes),
        "active": len(changes) >= MIN_EXAMPLES_PER_FEATURE,
        "median_start_shift": _median([item["start_shift"] for item in changes]),
        "median_end_shift": _median([item["end_shift"] for item in changes]),
    }



def apply_context_range_learning(
    contexts: list[dict[str, Any]],
    profile: dict[str, Any],
    question_numbers: set[int],
) -> list[dict[str, Any]]:
    """Pas voldoende onderbouwde contextbereikcorrecties toe op nieuwe voorstellen.

    Alleen nog niet handmatig gecontroleerde voorstellen worden aangepast.
    De aanpassing blijft zichtbaar als metadata en de docent houdt de normale
    visuele review. Een opgeslagen contextbeslissing wordt later door de
    workflowlaag over dit voorstel heen gezet.
    """
    adjusted = []
    numbers = sorted(question_numbers)
    if not profile.get("active"):
        return [dict(item) for item in contexts]
    for original in contexts:
        item = dict(original)
        if item.get("reviewed"):
            adjusted.append(item)
            continue
        start = int(item.get("from_question", 0))
        end = int(item.get("to_question", start))
        proposed_start = start + int(profile.get("median_start_shift") or 0)
        proposed_end = end + int(profile.get("median_end_shift") or 0)
        # Beperk de grenzen tot bestaande vragen en voorkom een omgekeerd
        # bereik wanneer historische correcties op een klein examen landen.
        proposed_start = min(numbers, key=lambda number: abs(number - proposed_start)) if numbers else start
        proposed_end = min(numbers, key=lambda number: abs(number - proposed_end)) if numbers else end
        if proposed_start > proposed_end:
            proposed_start, proposed_end = start, end
        item["from_question"] = proposed_start
        item["to_question"] = proposed_end
        item["learning_adjusted"] = (proposed_start != start or proposed_end != end)
        item["learning_correction"] = {
            "start_shift": int(profile.get("median_start_shift") or 0),
            "end_shift": int(profile.get("median_end_shift") or 0),
            "examples": profile.get("examples", 0),
        }
        adjusted.append(item)
    return adjusted



def learned_boundary_overrides(
    accepted_starts: list[dict[str, Any]],
    page_heights: list[float],
    profile: dict[str, Any],
    *,
    margin_points: float = 10.0,
) -> dict[int, dict[str, float]]:
    """Maak voorlopige fragmentgrenzen uit geleerde offsets.

    Deze helper levert alleen voorstellen. De caller moet reeds opgeslagen
    docentoverrides erna samenvoegen, zodat expliciete correcties altijd winnen.
    """
    if not profile.get("active") or not accepted_starts or not page_heights:
        return {}
    ordered = sorted(
        accepted_starts,
        key=lambda item: (int(item["page_index"]), float(item["pdf_bbox"][1])),
    )
    result: dict[int, dict[str, float]] = {}
    start_offset = float(profile.get("median_start_offset") or 0)
    end_offset = float(profile.get("median_end_offset") or 0)
    for index, start in enumerate(ordered):
        next_start = ordered[index + 1] if index + 1 < len(ordered) else None
        first_page = int(start["page_index"])
        last_page = int(next_start["page_index"]) if next_start else len(page_heights) - 1
        if not 0 <= first_page < len(page_heights) or not 0 <= last_page < len(page_heights):
            continue
        default_end = (
            float(next_start["pdf_bbox"][1])
            if next_start and int(next_start["page_index"]) == last_page
            else float(page_heights[last_page])
        )
        end_y = default_end + end_offset
        if next_start and int(next_start["page_index"]) == last_page:
            end_y -= margin_points
        result[int(start["question_number"])] = {
            "start_y": float(start["pdf_bbox"][1]) + start_offset,
            "end_y": end_y,
        }
    return result
