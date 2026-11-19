"""Pure workflow-state helpers for the exam processing application.

This module intentionally contains no Tkinter code so progression rules can be
unit-tested independently from the desktop UI.
"""
from __future__ import annotations

from structure import validate_exam_structure


def exam_workflow_state(data: dict) -> dict:
    """Return the next safe action and a concise progress label for one exam."""
    documents = data.get("documenten", []) or []
    if not documents:
        return {"stage": "import", "label": "Documenten toevoegen",
                "action": "Importeer de examen-PDF's."}

    source_docs = [doc for doc in documents if doc.get("type_voorstel") == "opgaven"]
    if not source_docs:
        return {"stage": "documenttype", "label": "Documenttype controleren",
                "action": "Wijs de juiste PDF aan als opgavenbestand."}

    candidates = data.get("vraagkandidaten", []) or []
    if not candidates:
        return {"stage": "analyse", "label": "Vraagstarts analyseren",
                "action": "Analyseer de opgaven-PDF's."}

    undecided = [row for row in candidates if row.get("human_decision") is None]
    confirmed = [row for row in candidates if row.get("human_decision") is True]
    rejected = [row for row in candidates if row.get("human_decision") is False]
    if undecided:
        return {"stage": "vraagstarts", "label": f"Vraagstarts beoordelen ({len(undecided)} open)",
                "action": "Beoordeel de volgende vraagstart.", "open_candidates": len(undecided)}

    if not confirmed:
        return {"stage": "ontbrekende_vragen", "label": "Controleer ontbrekende vraagstarts",
                "action": "Controleer of alle echte vragen handmatig zijn toegevoegd.",
                "rejected_candidates": len(rejected)}

    structures = data.get("exam_structures", {}) or {}
    missing_structures = []
    for document in source_docs:
        structure = structures.get(document.get("id"))
        legacy = data.get("exam_structure") or {}
        if structure is None and legacy.get("document_id") == document.get("id"):
            structure = legacy
        confirmed_numbers = sorted({
            int(row["number"]) for row in confirmed
            if row.get("document_id") == document.get("id") and row.get("number") is not None
        })
        if structure is None or validate_exam_structure(
            structure, document.get("id"), document.get("sha256"), confirmed_numbers
        ):
            missing_structures.append(document)

    if missing_structures:
        return {"stage": "structuur", "label": f"Structuur afbakenen ({len(missing_structures)} PDF's)",
                "action": "Leg vraag- en contextgrenzen vast.",
                "missing_structures": len(missing_structures)}

    records = data.get("vraagrecords", []) or []

    def has_record(candidate):
        return any(
            record.get("candidate_document_id") == candidate.get("document_id")
            and record.get("number") == candidate.get("number")
            and record.get("source_page") == candidate.get("page")
            for record in records
        )

    missing_records = [row for row in confirmed if not has_record(row)]
    if missing_records:
        return {"stage": "vraagrecords", "label": f"Vraagrecords maken ({len(missing_records)} open)",
                "action": "Maak het volgende concept-vraagrecord.",
                "missing_records": len(missing_records)}

    unapproved = [record for record in records if not record.get("approved_by_human", False)]
    if unapproved:
        return {"stage": "eindcontrole", "label": f"Eindcontrole ({len(unapproved)} open)",
                "action": "Controleer en keur ieder vraagrecord expliciet goed.",
                "unapproved_records": len(unapproved)}

    if not records:
        return {"stage": "ontbrekende_vragen", "label": "Controleer ontbrekende vraagstarts",
                "action": "Er zijn geen vraagrecords; controleer of er vragen ontbreken."}

    return {"stage": "export", "label": "Klaar voor export",
            "action": "Maak het gecontroleerde exportpakket."}
