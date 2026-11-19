"""Pure workflow-state helpers for the exam processing application.

This module intentionally contains no Tkinter code so progression rules can be
unit-tested independently from the desktop UI.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from structure import validate_exam_structure


def restore_import_batch(examens_root, current_folder, data: dict,
                        project_file: str = "project.json"):
    """Safely restore a batch queue from the manifest linked to an exam project."""
    manifest_name = data.get("import_batch_manifest")
    if not manifest_name:
        return None
    root = Path(examens_root).resolve()
    manifest_path = root / Path(str(manifest_name)).name
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema") != "biologie-examenimport-v1":
            return None
        entries = manifest.get("projecten", [])
        if not isinstance(entries, list):
            return None
        paths = []
        for entry in entries:
            if not isinstance(entry, dict):
                return None
            relative_path = entry.get("pad")
            if not isinstance(relative_path, str) or not relative_path:
                return None
            candidate = (root / relative_path).resolve()
            if not candidate.is_relative_to(root):
                return None
            if (candidate / project_file).is_file():
                paths.append(candidate)
        current = Path(current_folder).resolve()
        if current not in paths:
            return None
        return {"paths": paths, "index": paths.index(current),
                "manifest_path": manifest_path}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def exam_export_fingerprint(data: dict) -> str:
    """Hash all source and reviewed data that an export package depends on."""
    payload = {
        "documenten": data.get("documenten", []),
        "vraagkandidaten": data.get("vraagkandidaten", []),
        "exam_structures": data.get("exam_structures", {}),
        "exam_structure": data.get("exam_structure", {}),
        "vraagrecords": data.get("vraagrecords", []),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
        for record in records:
            if record.get("candidate_document_id") != candidate.get("document_id"):
                continue
            try:
                same_number = int(record.get("number")) == int(candidate.get("number"))
                same_page = int(record.get("source_page")) == int(candidate.get("page"))
            except (TypeError, ValueError):
                continue
            if same_number and same_page:
                return True
        return False

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

    fingerprint = exam_export_fingerprint(data)
    export_status = data.get("export_status") or {}
    if export_status.get("fingerprint") == fingerprint:
        return {"stage": "voltooid", "label": "Exportpakket gemaakt",
                "action": "Het gecontroleerde exportpakket is aangemaakt; er is niets gepubliceerd."}
    return {"stage": "export", "label": "Exportpakket maken",
            "action": "Maak het gecontroleerde exportpakket."}
