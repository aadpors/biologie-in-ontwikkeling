"""Safe batch-import grouping for complete biology exam year sets."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path


def resolve_examens_root(app_base: Path) -> Path:
    """Use the existing examens folder next to the app, or create that default later."""
    app_base = Path(app_base)
    preferred = app_base.parent / "examens"
    local = app_base / "examens"
    if preferred.is_dir():
        return preferred
    if local.is_dir():
        return local
    return preferred


DOCUMENT_ROLES = {"opgaven", "correctievoorschrift", "uitwerkbijlage", "aanvulling"}
IDENTITY_FIELDS = ("level", "year", "period")


def exam_identity_key(document: dict) -> tuple[str, str, str] | None:
    identity = document.get("exam_metadata") or {}
    if not all(str(identity.get(field, "")).strip() for field in IDENTITY_FIELDS):
        return None
    level = str(identity["level"]).strip().lower()
    if level not in {"havo", "vwo"}:
        return None
    year = str(identity["year"]).strip()
    period = str(identity["period"]).strip()
    if not year.isdigit() or len(year) != 4 or period not in {"1", "2", "3"}:
        return None
    return level, year, period


def group_exam_documents(documents: list[dict]) -> tuple[dict, list[dict]]:
    """Group only on an exact, complete level/year/period identity."""
    groups = defaultdict(list)
    unassigned = []
    for document in documents:
        key = exam_identity_key(document)
        if key is None:
            unassigned.append(document)
        else:
            groups[key].append(document)
    return dict(sorted(groups.items())), unassigned


def batch_document_warnings(documents: list[dict]) -> list[str]:
    roles = [str(item.get("type_voorstel", "onbekend")) for item in documents]
    warnings = []
    if "opgaven" not in roles:
        warnings.append("Geen opgaven-PDF gevonden.")
    if "correctievoorschrift" not in roles:
        warnings.append("Geen correctievoorschrift gevonden.")
    if roles.count("opgaven") > 1:
        warnings.append("Meerdere opgaven-PDF's met dezelfde examenidentiteit.")
    if roles.count("correctievoorschrift") > 1:
        warnings.append("Meerdere correctievoorschriften met dezelfde examenidentiteit.")
    return warnings


def validate_batch_documents(documents: list[dict]) -> list[str]:
    """Return blocking errors; warnings are reported separately.

    Both role and identity confidence must be high enough, regardless of the
    inference source. Manual review is represented explicitly with confidence 1.
    """
    errors = []
    for document in documents:
        filename = document.get("bestand", "Onbekend bestand")
        identity = exam_identity_key(document)
        if identity is None:
            errors.append(f"{filename}: niveau, jaar of tijdvak ontbreekt of is ongeldig.")
        role = document.get("type_voorstel")
        if role not in DOCUMENT_ROLES:
            errors.append(f"{filename}: documenttype moet eerst worden vastgesteld.")
        if float(document.get("type_zekerheid", 0) or 0) < 0.9:
            errors.append(f"{filename}: documenttype is onzeker; bevestig of corrigeer dit eerst.")
        meta = document.get("exam_metadata") or {}
        if float(meta.get("confidence", 0) or 0) < 0.9:
            errors.append(f"{filename}: examenidentiteit is onzeker; bevestig deze handmatig.")
        if meta.get("source") == "handmatig_bevestigd" and identity is None:
            errors.append(f"{filename}: handmatig bevestigde examenidentiteit is ongeldig.")
    return errors
