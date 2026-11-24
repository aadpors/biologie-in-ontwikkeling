"""Integratietests voor de eerste samenhangende applicatieversie.

De tests gebruiken kleine PDF's die ter plekke worden gemaakt. Daarmee
controleren we echte PDF-import, metadataherkenning, blijvende opslag,
server-side stapbeveiliging en het ongeldig maken van afhankelijke stappen.
"""
import io
import tempfile
import unittest
from unittest.mock import patch
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

    def test_late_identical_question_start_autosave_cannot_reopen_approved_step(self):
        """Een vertraagde identieke autosave mag een afgeronde stap niet terugzetten."""
        result = self.import_sample()
        exam_id = result["exam_id"]
        approved = {
            "candidates": [{"id":"candidate-1", "question_number":1, "accepted":True}],
            "document_sha256": "a" * 64,
            "reviewed_all_pages": True,
        }
        main.STORE.complete_step(exam_id, "opgaven_starts", approved)

        # Simuleer een autosave die vóór de afrondklik is gestart, maar pas
        # daarna bij de opslaglaag aankomt. De inhoudelijke review is identiek.
        saved_as_draft = main.STORE.save_step_draft_preserving_identical_complete(
            exam_id,
            "opgaven_starts",
            approved,
            identity_fields=("candidates", "document_sha256"),
        )
        self.assertFalse(saved_as_draft)
        self.assertEqual(
            main.STORE.get_exam(exam_id)["steps"]["opgaven_starts"]["status"],
            "complete",
        )

        # Een echte wijziging moet de goedkeuring juist wel intrekken.
        changed = {
            **approved,
            "candidates": [{"id":"candidate-1", "question_number":2, "accepted":True}],
        }
        saved_as_draft = main.STORE.save_step_draft_preserving_identical_complete(
            exam_id,
            "opgaven_starts",
            changed,
            identity_fields=("candidates", "document_sha256"),
        )
        self.assertTrue(saved_as_draft)
        self.assertEqual(
            main.STORE.get_exam(exam_id)["steps"]["opgaven_starts"]["status"],
            "pending",
        )

    def test_stitched_exam_cache_avoids_rebuilding_unchanged_source(self):
        """Terugnavigeren naar stap 3 mag geen nieuwe render-/stitchronde starten."""
        document = fitz.open()
        document.new_page()  # Voorblad wordt standaard overgeslagen.
        page = document.new_page()
        page.insert_text((70, 100), "Vraag 1: beschrijf de cel.")
        root = Path(self.temp.name)
        pdf_path = root / "cache-source.pdf"
        document.save(pdf_path)
        document.close()

        output_path = root / "derived" / "exam-long.png"
        source_hash = main.STORE.sha256(pdf_path)
        first = main._load_or_build_stitched_exam(pdf_path, output_path, source_hash)
        self.assertTrue(output_path.is_file())
        self.assertTrue(output_path.with_suffix(".metadata.json").is_file())

        # De tweede aanroep moet de PNG en metadata uit de cache lezen. Als
        # de renderer toch wordt aangeroepen, faalt deze test direct.
        with patch.object(main, "build_stitched_exam", side_effect=AssertionError("onverwachte herbouw")):
            second = main._load_or_build_stitched_exam(pdf_path, output_path, source_hash)
        self.assertEqual(first["pages"], second["pages"])
        self.assertEqual(first["height"], second["height"])
        self.assertTrue(second["white_row_ranges"])

    def test_stitched_fragments_preserve_the_full_page_width(self):
        """Een lange fragmentafbeelding mag geen linker- of rechterkolom afsnijden."""
        document = fitz.open()
        page = document.new_page(width=600, height=800)
        page.insert_text((90, 110), "Vraag 1: beschrijf de functie van het celmembraan.")
        root = Path(self.temp.name)
        pdf_path = root / "full-width-source.pdf"
        document.save(pdf_path)
        document.close()

        output_path = root / "derived" / "full-width.png"
        main.build_stitched_exam(pdf_path, output_path, start_page=0)

        from PIL import Image
        with Image.open(output_path) as rendered:
            # 600 PDF-punten × 1,25 renderfactor = 750 pixels.
            # De volledige paginabreedte blijft behouden, ook als de inhoud
            # zelf slechts een smalle strook in het midden van de pagina beslaat.
            self.assertEqual(rendered.width, 750)

    def test_single_page_workbook_is_not_mistaken_for_a_cover_only_opgavenboekje(self):
        """Een uitwerkbijlage van één pagina bevat vaak direct de antwoorden."""
        opgaven = fitz.open()
        opgaven.new_page().insert_text((70, 100), "Omslag opgaven")
        opgaven.new_page().insert_text((70, 100), "1. Beschrijf de functie van het celmembraan.")
        opgaven_bytes = opgaven.tobytes()
        opgaven.close()

        # Deze uitwerkbijlage heeft bewust maar één pagina. Anders dan bij het
        # opgavenboekje mag de renderer de eerste pagina hier niet overslaan:
        # er is geen afzonderlijke omslagpagina verondersteld.
        workbook = fitz.open()
        workbook.new_page().insert_text((70, 100), "Vraag 1 — Noteer uw antwoord.")
        workbook_bytes = workbook.tobytes()
        workbook.close()

        imported = self.client.post("/api/exams/import", files=[
            ("files", ("biologie-vwo-2026-tv2-o.pdf", opgaven_bytes, "application/pdf")),
            ("files", ("biologie-vwo-2026-tv2-u.pdf", workbook_bytes, "application/pdf")),
        ])
        self.assertEqual(imported.status_code, 200, imported.text)
        exam_id = imported.json()["exam_id"]
        confirmed = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{
                "biologie-vwo-2026-tv2-o.pdf":"opgaven",
                "biologie-vwo-2026-tv2-u.pdf":"uitwerkbijlage",
            },
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        stitched = self.client.get(
            f"/api/exams/{exam_id}/stitched-document/uitwerkbijlage"
        )
        self.assertEqual(stitched.status_code, 200, stitched.text)
        self.assertEqual(len(stitched.json()["pages"]), 1)
        self.assertEqual(stitched.json()["pages"][0]["page_number"], 1)

    def test_step_six_uses_stitched_workbook_selections_for_final_fragments(self):
        """Stap 6 gebruikt dezelfde doorlopende selectiewerkruimte als stap 3."""
        opgaven = fitz.open()
        cover = opgaven.new_page()
        cover.insert_text((70, 100), "Biologie vwo 2026")
        question_page = opgaven.new_page()
        question_page.insert_text((70, 100), "1. Beschrijf de functie van het celmembraan.")
        opgaven_bytes = opgaven.tobytes()
        opgaven.close()

        workbook = fitz.open()
        workbook.new_page().insert_text((70, 100), "Uitwerkbijlage biologie")
        workbook_page = workbook.new_page()
        workbook_page.insert_text((70, 100), "1. Noteer uw antwoord.")
        workbook_bytes = workbook.tobytes()
        workbook.close()

        imported = self.client.post("/api/exams/import", files=[
            ("files", ("biologie-vwo-2026-tv2-o.pdf", opgaven_bytes, "application/pdf")),
            ("files", ("biologie-vwo-2026-tv2-u.pdf", workbook_bytes, "application/pdf")),
        ])
        self.assertEqual(imported.status_code, 200, imported.text)
        exam_id = imported.json()["exam_id"]
        confirmed = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{
                "biologie-vwo-2026-tv2-o.pdf":"opgaven",
                "biologie-vwo-2026-tv2-u.pdf":"uitwerkbijlage",
            },
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        starts = self.client.get(
            f"/api/exams/{exam_id}/document-question-starts/uitwerkbijlage"
        )
        self.assertEqual(starts.status_code, 200, starts.text)
        candidates = starts.json()["candidates"]
        self.assertEqual([item["question_number"] for item in candidates], [1])
        saved_starts = self.client.post(
            f"/api/exams/{exam_id}/document-question-starts/uitwerkbijlage/review",
            json={"candidates":candidates},
        )
        self.assertEqual(saved_starts.status_code, 200, saved_starts.text)
        completed_starts = self.client.post(
            f"/api/exams/{exam_id}/steps/uitwerk_starts/complete",
            json={"reviewed":True, "reviewed_all_pages":True},
        )
        self.assertEqual(completed_starts.status_code, 200, completed_starts.text)

        stitched = self.client.get(
            f"/api/exams/{exam_id}/stitched-document/uitwerkbijlage"
        )
        self.assertEqual(stitched.status_code, 200, stitched.text)
        white_ranges = stitched.json()["white_row_ranges"]
        self.assertTrue(white_ranges)
        # Kies twee geldige witte rijen rond de tekststrook. De test gebruikt
        # uitsluitend servergerapporteerde grenzen, net als de browser.
        first = white_ranges[0]
        last = white_ranges[-1]
        top = first[0]
        bottom = last[1]
        self.assertGreater(bottom, top)

        saved_selection = self.client.post(
            f"/api/exams/{exam_id}/stitched-document/uitwerkbijlage/review",
            json={"selections":[{
                "id":"workbook-q1", "type":"vraag", "top":top, "bottom":bottom,
                "question_numbers":[1], "label":"Vraag 1",
            }], "reviewed":True},
        )
        self.assertEqual(saved_selection.status_code, 200, saved_selection.text)

        fragments = self.client.get(
            f"/api/exams/{exam_id}/document-question-fragments/uitwerkbijlage"
        )
        self.assertEqual(fragments.status_code, 200, fragments.text)
        self.assertEqual(fragments.json()["question_count"], 1)
        self.assertTrue(fragments.json()["questions"][0]["stitched"])
        self.assertEqual(fragments.json()["questions"][0]["question_number"], 1)

    def test_legacy_automatic_context_link_is_repaired_without_changing_manual_links(self):
        """Heropenen van oude examens herstelt alleen de oude automatische koppeling."""
        selections = [
            {
                "id":"q38", "type":"vraag", "top":150, "bottom":190,
                "question_numbers":[38], "label":"Vraag 38",
            },
            {
                "id":"q39", "type":"vraag", "top":200, "bottom":240,
                "question_numbers":[39], "label":"Vraag 39",
            },
            {
                "id":"auto-context-between-37-38",
                "type":"context",
                "top":100,
                "bottom":150,
                "question_numbers":[37],
                "label":"Automatisch contextvoorstel — inhoud na de voorafgaande vraag",
            },
            {
                "id":"manual-context-1",
                "type":"context",
                "top":250,
                "bottom":300,
                "question_numbers":[38, 39],
                "label":"Door docent gekoppelde context",
            },
        ]

        repaired = main._repair_automatic_context_links(selections)
        repaired_auto = next(item for item in repaired if item["id"] == "auto-context-between-37-38")
        repaired_manual = next(item for item in repaired if item["id"] == "manual-context-1")

        self.assertEqual(repaired_auto["question_numbers"], [38, 39])
        self.assertIn("bijbehorende vragen", repaired_auto["label"])
        # Handmatig gekozen koppelingen met meerdere vraagnummers blijven
        # ongewijzigd; de migratie mag geen inhoudelijke docentkeuze overschrijven.
        self.assertEqual(repaired_manual["question_numbers"], [38, 39])
        self.assertEqual(repaired_manual["label"], "Door docent gekoppelde context")

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

    def test_metadata_draft_is_persisted_without_confirming_exam(self):
        result = self.import_sample()
        exam_id = result["exam_id"]
        response = self.client.post(f"/api/exams/{exam_id}/metadata/draft", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":None,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven"}
        })
        self.assertEqual(response.status_code, 200, response.text)
        exam = self.client.get(f"/api/exams/{exam_id}").json()
        self.assertFalse(exam["confirmed"])
        self.assertEqual(exam["steps"]["metadata_draft"]["evidence"]["level"], "vwo")
        self.assertIsNone(exam["steps"]["metadata_draft"]["evidence"]["period"])

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

        # Na bevestiging moet de workflow de metadatafase overslaan en
        # direct de eerste inhoudelijke stap aanbieden. Dit controleert de
        # serverstatus waarop de browser zijn volgende scherm baseert.
        workflow = self.client.get("/api/workflow").json()
        completed = {
            key for key, step in exam["steps"].items()
            if step["status"] == "complete"
        }
        next_step = next(step for step in workflow if step["key"] not in completed)
        self.assertEqual(next_step["key"], "opgaven_starts")

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

    def test_duplicate_exam_requires_confirmation_and_replaces_old_processing(self):
        """Een identieke PDF-verzameling mag alleen na bevestiging worden vervangen."""
        opgaven_pdf = self.pdf_bytes()
        cv_pdf = self.pdf_bytes("Correctievoorschrift biologie vwo 2026")
        original_files = [
            ("files", ("biologie-vwo-2026-tv2-o.pdf", opgaven_pdf, "application/pdf")),
            ("files", ("biologie-vwo-2026-tv2-c.pdf", cv_pdf, "application/pdf")),
        ]
        original_response = self.client.post("/api/exams/import", files=original_files)
        self.assertEqual(original_response.status_code, 200, original_response.text)
        original = original_response.json()

        # Zelfde bronbestanden, maar in omgekeerde uploadvolgorde.
        duplicate_files = [
            ("files", ("biologie-vwo-2026-tv2-c.pdf", cv_pdf, "application/pdf")),
            ("files", ("biologie-vwo-2026-tv2-o.pdf", opgaven_pdf, "application/pdf")),
        ]
        duplicate = self.client.post("/api/exams/import", files=duplicate_files)
        self.assertEqual(duplicate.status_code, 409)
        detail = duplicate.json()["detail"]
        self.assertEqual(detail["code"], "duplicate_exam")
        self.assertEqual(detail["exam_id"], original["exam_id"])

        # De bevestigde vervanging maakt een nieuw examen en verwijdert de
        # oude databasegegevens inclusief alle bijbehorende workflowstappen.
        replacement_files = [
            ("files", ("biologie-vwo-2026-tv2-c.pdf", cv_pdf, "application/pdf")),
            ("files", ("biologie-vwo-2026-tv2-o.pdf", opgaven_pdf, "application/pdf")),
        ]
        replacement = self.client.post(
            "/api/exams/import",
            data={"replace_exam_id": original["exam_id"]},
            files=replacement_files,
        )
        self.assertEqual(replacement.status_code, 200, replacement.text)
        self.assertNotEqual(replacement.json()["exam_id"], original["exam_id"])
        self.assertEqual(self.client.get(f"/api/exams/{original['exam_id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/exams/{replacement.json()['exam_id']}").status_code, 200)

    def test_reopening_metadata_preserves_values_and_clears_confirmation(self):
        """Metadata opnieuw openen bewaart de oude invoer als bewerkbaar concept."""
        result = self.import_sample()
        exam_id = result["exam_id"]
        metadata = {
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{
                "biologie-vwo-2026-tv2-o.pdf":"opgaven",
                "biologie-vwo-2026-tv2-c.pdf":"correctievoorschrift"
            }
        }
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json=metadata)
        response = self.client.post(f"/api/exams/{exam_id}/steps/metadata/reopen")
        self.assertEqual(response.status_code, 200, response.text)
        exam = self.client.get(f"/api/exams/{exam_id}").json()
        self.assertFalse(exam["confirmed"])
        self.assertEqual(exam["steps"]["metadata_draft"]["evidence"], metadata)
        self.assertNotIn("metadata", exam["steps"])

    def test_non_pdf_upload_is_rejected(self):
        response = self.client.post("/api/exams/import", files=[("files", ("not-a-pdf.txt", b"hello", "text/plain"))])
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
