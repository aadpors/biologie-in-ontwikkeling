import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from batch_import import (
    batch_document_warnings,
    exam_identity_key,
    group_exam_documents,
    validate_batch_documents,
    resolve_examens_root,
)


def document(name, level="Vwo", year="2026", period="1", role="opgaven",
             confidence=0.96, metadata_confidence=0.96, metadata_source="bestandsnaam"):
    return {
        "bestand": name,
        "type_voorstel": role,
        "type_zekerheid": confidence,
        "exam_metadata": {
            "level": level, "year": year, "period": period,
            "confidence": metadata_confidence, "source": metadata_source,
        },
    }


class BatchImportTests(unittest.TestCase):
    def test_projects_root_is_always_inside_program_root(self):
        with TemporaryDirectory() as temp:
            base = Path(temp) / "portable-app"
            base.mkdir()
            expected = base / "projecten"
            self.assertEqual(resolve_examens_root(base), expected)

    def test_existing_legacy_folders_do_not_change_projects_root(self):
        with TemporaryDirectory() as temp:
            base = Path(temp) / "portable-app"
            base.mkdir()
            (base / "examens").mkdir()
            self.assertEqual(resolve_examens_root(base), base / "projecten")

    def test_projects_root_does_not_require_precreation(self):
        with TemporaryDirectory() as temp:
            base = Path(temp) / "portable-app"
            base.mkdir()
            self.assertEqual(resolve_examens_root(base), base / "projecten")

    def test_groups_only_exact_level_year_period(self):
        docs = [
            document("vwo-o.pdf"),
            document("havo-o.pdf", level="Havo"),
            document("vwo-t2-o.pdf", period="2"),
            document("vwo-2025-o.pdf", year="2025"),
        ]
        groups, unassigned = group_exam_documents(docs)
        self.assertEqual(len(groups), 4)
        self.assertEqual(unassigned, [])

    def test_incomplete_identity_is_not_guessed_or_grouped(self):
        doc = document("mystery.pdf")
        doc["exam_metadata"] = {"level": "Vwo", "year": "2026"}
        self.assertIsNone(exam_identity_key(doc))
        groups, unassigned = group_exam_documents([doc])
        self.assertEqual(groups, {})
        self.assertEqual(unassigned, [doc])

    def test_unknown_type_and_uncertain_metadata_block_import(self):
        doc = document("unknown.pdf", role="onbekend", confidence=0.35)
        self.assertGreaterEqual(len(validate_batch_documents([doc])), 2)

    def test_low_metadata_confidence_blocks_import_for_any_inference_source(self):
        for source in ("bestandsnaam", "eerste_pdf_paginas", "pdf_metadata"):
            with self.subTest(source=source):
                doc = document("uncertain.pdf", metadata_confidence=0.72,
                               metadata_source=source)
                errors = validate_batch_documents([doc])
                self.assertTrue(any("examenidentiteit is onzeker" in error for error in errors))

    def test_manual_metadata_confirmation_passes_confidence_check(self):
        doc = document("confirmed.pdf", metadata_confidence=1.0,
                       metadata_source="handmatig_bevestigd")
        self.assertEqual(validate_batch_documents([doc]), [])

    def test_warnings_do_not_silently_claim_cv_exists(self):
        warnings = batch_document_warnings([document("opgaven.pdf")])
        self.assertIn("Geen correctievoorschrift gevonden.", warnings)

    def test_exact_role_and_identity_pass_validation(self):
        self.assertEqual(validate_batch_documents([document("opgaven.pdf")]), [])


