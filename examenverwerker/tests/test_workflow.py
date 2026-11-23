"""Integratietests voor de eerste samenhangende applicatieversie.

De tests gebruiken kleine PDF's die ter plekke worden gemaakt. Daarmee
controleren we echte PDF-import, metadataherkenning, blijvende opslag,
server-side stapbeveiliging en het ongeldig maken van afhankelijke stappen.
"""
import io
import tempfile
import unittest
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from examenverwerker import main
from examenverwerker.storage import Store
from examenverwerker.domain import invalidate_dependents


class WorkflowApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        main.DATA = root
        main.STORE = Store(root)
        self.client = TestClient(main.app)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def pdf_bytes(text="Biologie vwo 2026 tijdvak 2"):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), text)
        result = document.tobytes()
        document.close()
        return result

    def import_sample(self):
        response = self.client.post("/api/exams/import", files=[
            ("files", ("biologie-vwo-2026-tv2-o.pdf", self.pdf_bytes(), "application/pdf")),
            ("files", ("biologie-vwo-2026-tv2-c.pdf", self.pdf_bytes("Correctievoorschrift biologie vwo 2026"), "application/pdf")),
        ])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_import_detects_document_suffix_and_persists_originals(self):
        result = self.import_sample()
        self.assertEqual(len(result["documents"]), 2)
        self.assertEqual(result["documents"][0]["metadata"]["document_type"], "opgaven")
        self.assertEqual(result["documents"][0]["metadata"]["level"], "vwo")
        self.assertEqual(result["documents"][0]["metadata"]["year"], 2026)
        self.assertEqual(result["documents"][0]["metadata"]["period"], 2)
        self.assertEqual(result["documents"][1]["metadata"]["document_type"], "correctievoorschrift")
        exam = self.client.get(f"/api/exams/{result['exam_id']}").json()
        self.assertEqual(exam["documents"][0]["page_count"], 1)
        self.assertEqual(len(exam["documents"][0]["sha256"]), 64)

    def test_metadata_requires_all_fields_and_document_types(self):
        result = self.import_sample()
        exam_id = result["exam_id"]
        bad = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={"subject":"biologie"})
        self.assertEqual(bad.status_code, 422)
        good = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven", "biologie-vwo-2026-tv2-c.pdf":"correctievoorschrift"}
        })
        self.assertEqual(good.status_code, 200, good.text)
        exam = self.client.get(f"/api/exams/{exam_id}").json()
        self.assertTrue(exam["confirmed"])
        self.assertEqual(exam["steps"]["metadata"]["status"], "complete")

    def test_step_cannot_skip_prerequisites_or_omit_evidence(self):
        result = self.import_sample()
        exam_id = result["exam_id"]
        blocked = self.client.post(f"/api/exams/{exam_id}/steps/opgaven_fragments/complete", json={"reviewed":True})
        self.assertEqual(blocked.status_code, 409)
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven", "biologie-vwo-2026-tv2-c.pdf":"correctievoorschrift"}
        })
        missing_evidence = self.client.post(f"/api/exams/{exam_id}/steps/opgaven_starts/complete", json={})
        self.assertEqual(missing_evidence.status_code, 422)

    def test_reopening_metadata_removes_dependent_approvals_from_database(self):
        result = self.import_sample()
        exam_id = result["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven", "biologie-vwo-2026-tv2-c.pdf":"correctievoorschrift"}
        })
        self.client.post(f"/api/exams/{exam_id}/steps/opgaven_starts/complete", json={"reviewed":True,"candidate_count":39})
        response = self.client.post(f"/api/exams/{exam_id}/steps/metadata/invalidate")
        self.assertEqual(response.status_code, 200)
        exam = self.client.get(f"/api/exams/{exam_id}").json()
        self.assertNotIn("metadata", exam["steps"])
        self.assertNotIn("opgaven_starts", exam["steps"])

    def test_reopening_metadata_invalidates_all_later_steps(self):
        self.assertIn("publicatie", invalidate_dependents("metadata"))
        self.assertIn("eindcontrole", invalidate_dependents("metadata"))

    def test_preview_returns_png_for_original_page(self):
        result = self.import_sample()
        doc = self.client.get(f"/api/exams/{result['exam_id']}").json()["documents"][0]
        response = self.client.get(f"/api/exams/{result['exam_id']}/documents/{doc['id']}/preview/0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_non_pdf_upload_is_rejected(self):
        response = self.client.post("/api/exams/import", files=[("files", ("not-a-pdf.txt", b"hello", "text/plain"))])
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
