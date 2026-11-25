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
