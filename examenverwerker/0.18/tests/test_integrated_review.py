"""Integratietests voor CV-voorbewerking, antwoorden en documentrelaties."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from fastapi.testclient import TestClient

from examenverwerker import main
from examenverwerker.storage import Store


class IntegratedReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        main.DATA = self.root
        main.STORE = Store(self.root)
        self.client = TestClient(main.app)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def pdf(pages):
        doc = fitz.open()
        for lines in pages:
            page = doc.new_page()
            y = 80
            for line in lines:
                page.insert_text((60, y), line, fontsize=10)
                y += 28
        data = doc.tobytes()
        doc.close()
        return data

    def create_exam(self, opgaven_pages=None):
        uploads = [
            ("files", ("vw-1018-a-26-2-o.pdf", self.pdf(opgaven_pages or [["1p 1 Kies het juiste antwoord.", "A. optie een", "B. optie twee"]]), "application/pdf")),
            ("files", ("vw-1018-a-26-2-u.pdf", self.pdf([["4", "invulschema"], ["27", "invulschema"]]), "application/pdf")),
            ("files", ("vw-1018-a-26-2-c.pdf", self.pdf([["1 Regels voor beoordeling", "2 Algemene regels"], ["4 Beoordelingsmodel", "1 maximumscore 1", "B 1"]]), "application/pdf")),
        ]
        imported = self.client.post("/api/exams/import", files=uploads)
        self.assertEqual(imported.status_code, 200, imported.text)
        exam_id = imported.json()["exam_id"]
        confirmed = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{
                "vw-1018-a-26-2-o.pdf":"opgaven",
                "vw-1018-a-26-2-u.pdf":"uitwerkbijlage",
                "vw-1018-a-26-2-c.pdf":"correctievoorschrift",
            }
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        return exam_id

    def test_context_group_title_uses_first_nonempty_pdf_text_line(self):
        """Een contextgroeptitel is letterlijk de eerste niet-lege tekstregel."""
        self.assertEqual(
            main._first_nonempty_text_line("\n  Opwinding door kattenkruid  \n\nDe volgende regel hoort bij de context."),
            "Opwinding door kattenkruid",
        )
        self.assertEqual(main._first_nonempty_text_line("\n \n"), "")

    def test_cv_detection_ignores_numbered_preamble_before_marking_model(self):
        exam_id = self.create_exam()
        result = self.client.get(f"/api/exams/{exam_id}/document-question-starts/correctievoorschrift")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([item["question_number"] for item in result.json()["candidates"]], [1])
        self.assertEqual(result.json()["pages"][0]["candidate_count"], 0)

    def test_answer_endpoint_reads_cv_fragment_and_relations_allow_partial_workbook(self):
        exam_id = self.create_exam()
        for doc_type, step in [("opgaven", "opgaven_starts"), ("uitwerkbijlage", "uitwerk_starts"), ("correctievoorschrift", "cv_starts")]:
            starts = self.client.get(f"/api/exams/{exam_id}/document-question-starts/{doc_type}")
            self.assertEqual(starts.status_code, 200, starts.text)
            saved = self.client.post(f"/api/exams/{exam_id}/document-question-starts/{doc_type}/review", json={"candidates":starts.json()["candidates"]})
            self.assertEqual(saved.status_code, 200, saved.text)
            main.STORE.complete_step(exam_id, step, {"candidates":starts.json()["candidates"], "reviewed_all_pages":True,
                                                       "document_sha256":starts.json()["document"]["sha256"]})
        # CV-fragmentgeneratie en antwoordherkenning gebruiken de opgeslagen,
        # expliciet goedgekeurde vraagstart als bron.
        cv_fragments = self.client.get(f"/api/exams/{exam_id}/document-question-fragments/correctievoorschrift")
        self.assertEqual(cv_fragments.status_code, 200, cv_fragments.text)

        # Stap 4 gebruikt dezelfde goedgekeurde vraagstarts en moet daarom
        # ook via de volledige API-route een bruikbaar vraagfragment opleveren.
        # Deze controle voorkomt dat alleen de losse analysemodule slaagt,
        # terwijl de daadwerkelijke werkruimte bij het openen een serverfout geeft.
        question_analysis = self.client.get(f"/api/exams/{exam_id}/question-analysis")
        self.assertEqual(question_analysis.status_code, 200, question_analysis.text)
        self.assertEqual(question_analysis.json()["question_count"], 1)
        self.assertTrue(question_analysis.json()["questions"][0]["segments"])

        answers = self.client.get(f"/api/exams/{exam_id}/answers")
        self.assertEqual(answers.status_code, 200, answers.text)
        self.assertEqual(answers.json()["questions"][0]["answer_text"], "B")
        relations = self.client.get(f"/api/exams/{exam_id}/relations")
        self.assertEqual(relations.status_code, 200, relations.text)
        # De uitwerkbijlage bevat alleen 4 en 27; afwezigheid van vraag 1 is
        # een normale situatie en mag geen ontbrekende CV-koppeling opleveren.
        self.assertEqual(relations.json()["missing_cv"], [])
        self.assertFalse(relations.json()["questions"][0]["has_uitwerkbijlage"])

    def test_stitched_fragment_review_can_open_step_four_question_analysis(self):
        """Test de volledige stap-3-opslag en de daaropvolgende stap-4-API."""
        exam_id = self.create_exam(opgaven_pages=[
            ["1p 1 Kies het juiste antwoord.", "A. optie een", "B. optie twee"],
            ["Aanvullende tekst op de volgende pagina."],
        ])
        starts = self.client.get(f"/api/exams/{exam_id}/document-question-starts/opgaven")
        self.assertEqual(starts.status_code, 200, starts.text)
        saved_starts = self.client.post(
            f"/api/exams/{exam_id}/document-question-starts/opgaven/review",
            json={"candidates": starts.json()["candidates"]},
        )
        self.assertEqual(saved_starts.status_code, 200, saved_starts.text)
        main.STORE.complete_step(exam_id, "opgaven_starts", {
            "candidates": starts.json()["candidates"], "reviewed_all_pages": True,
            "document_sha256": starts.json()["document"]["sha256"],
        })

        stitched = self.client.get(f"/api/exams/{exam_id}/stitched-opgaven")
        self.assertEqual(stitched.status_code, 200, stitched.text)
        metadata = stitched.json()
        self.assertTrue(metadata["white_row_ranges"])
        valid_row = metadata["white_row_ranges"][0][0]
        next_valid_row = next(
            (start for start, end in metadata["white_row_ranges"] if start > valid_row),
            None,
        )
        self.assertIsNotNone(next_valid_row)

        selections = [
            {"id": "q1", "type": "vraag", "top": valid_row, "bottom": next_valid_row,
             "question_numbers": [1], "label": "Vraag 1"},
        ]
        saved = self.client.post(
            f"/api/exams/{exam_id}/stitched-opgaven/review",
            json={"selections": selections, "reviewed": True},
        )
        self.assertEqual(saved.status_code, 200, saved.text)

        # De compatibele fragmentreview vult het bewijs dat de workflowstap
        # nodig heeft om stap 3 af te ronden; daarna wordt de echte stap-4-route
        # aangeroepen, precies zoals de browser dit doet.
        fragment_review = self.client.post(
            f"/api/exams/{exam_id}/document-question-fragments/opgaven/review",
            json={"reviewed_question_numbers": [1], "reviewed_all_questions": True,
                  "boundary_overrides": []},
        )
        self.assertEqual(fragment_review.status_code, 200, fragment_review.text)
        completed = self.client.post(
            f"/api/exams/{exam_id}/steps/opgaven_fragments/complete",
            json={"reviewed": True, "reviewed_all_questions": True,
                  "reviewed_question_numbers": [1]},
        )
        self.assertEqual(completed.status_code, 200, completed.text)

        step_four = self.client.get(f"/api/exams/{exam_id}/question-analysis")
        self.assertEqual(step_four.status_code, 200, step_four.text)
        self.assertEqual(step_four.json()["question_count"], 1)
        self.assertTrue(step_four.json()["questions"][0]["segments"])

        # Niet-witte pixels mogen ook via de API niet als grens worden opgeslagen.
        # Kies bewust een rij direct na een volledig witte band. Die rij
        # bevat de eerste zichtbare PDF-pixels en mag dus geen grens worden.
        invalid_row = metadata["white_row_ranges"][0][1] + 1
        self.assertFalse(any(start <= invalid_row <= end for start, end in metadata["white_row_ranges"]))
        invalid = self.client.post(
            f"/api/exams/{exam_id}/stitched-opgaven/review",
            json={"selections": [{"id":"bad","type":"vraag","top":invalid_row,
                                  "bottom":next_valid_row,"question_numbers":[1]}],
                  "reviewed": False},
        )
        self.assertEqual(invalid.status_code, 422)

    def test_stitched_opgaven_preserves_saved_boundaries_when_image_fingerprint_is_stale(self):
        """Een nieuwe stitchversie mag eerder handmatig werk niet vervangen."""
        exam_id = self.create_exam(opgaven_pages=[
            ["Voorblad van het examen."],
            ["1p 1 Kies het juiste antwoord.", "A. optie een", "B. optie twee"],
        ])
        starts = self.client.get(
            f"/api/exams/{exam_id}/document-question-starts/opgaven"
        )
        self.assertEqual(starts.status_code, 200, starts.text)
        main.STORE.complete_step(exam_id, "opgaven_starts", {
            "candidates": starts.json()["candidates"],
            "reviewed_all_pages": True,
            "document_sha256": starts.json()["document"]["sha256"],
        })

        first_open = self.client.get(f"/api/exams/{exam_id}/stitched-opgaven")
        self.assertEqual(first_open.status_code, 200, first_open.text)
        rows = first_open.json()["white_row_ranges"]
        first_top = rows[0][0]
        first_bottom = next(
            start for start, end in rows if start > first_top
        )
        original_selection = {
            "id": "manual-q1",
            "type": "vraag",
            "top": first_top,
            "bottom": first_bottom,
            "question_numbers": [1],
            "label": "Handmatig gecontroleerde vraag 1",
        }
        saved = self.client.post(
            f"/api/exams/{exam_id}/stitched-opgaven/review",
            json={"selections": [original_selection], "reviewed": False},
        )
        self.assertEqual(saved.status_code, 200, saved.text)

        # Simuleer een cachevernieuwing: de PDF is hetzelfde, maar de hash van
        # de afgeleide afbeelding verschilt. De fragmentdata zelf blijft staan.
        exam = main.STORE.get_exam(exam_id)
        evidence = exam["steps"]["opgaven_fragments"]["evidence"]
        evidence["stitched_image_sha256"] = "oude-afbeelding-hash"
        main.STORE.save_step_draft(exam_id, "opgaven_fragments", evidence)

        reopened = self.client.get(f"/api/exams/{exam_id}/stitched-opgaven")
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertIn("herstelvoorstel", reopened.json()["selection_warning"].lower())
        self.assertEqual(reopened.json()["segmentation_mode"], "saved")
        self.assertEqual(reopened.json()["selections"], [original_selection])

        # Ook na het openen mag de server de oude grenzen niet stilzwijgend
        # vervangen door automatisch gegenereerde voorstellen.
        persisted = main.STORE.get_exam(exam_id)["steps"]["opgaven_fragments"]["evidence"]
        self.assertEqual(persisted["stitched_selections"], [original_selection])
        self.assertEqual(persisted["stitched_image_sha256"], "oude-afbeelding-hash")

    def test_no_supplement_requires_explicit_confirmation(self):
        exam_id = self.create_exam()
        result = self.client.get(f"/api/exams/{exam_id}/cv-supplement")
        self.assertTrue(result.json()["not_required"])
        # Simuleer de reeds afgeronde verplichte voorganger van de stap.
        main.STORE.complete_step(exam_id, "cv_fragments", {"reviewed_all_questions":True})
        blocked = self.client.post(f"/api/exams/{exam_id}/steps/cv_aanvulling/complete", json={"reviewed":True})
        self.assertEqual(blocked.status_code, 422)
        accepted = self.client.post(f"/api/exams/{exam_id}/steps/cv_aanvulling/complete", json={"reviewed":True,"not_required":True})
        self.assertEqual(accepted.status_code, 200, accepted.text)

    def complete_starts(self, exam_id):
        for doc_type, step in [("opgaven", "opgaven_starts"), ("uitwerkbijlage", "uitwerk_starts"), ("correctievoorschrift", "cv_starts")]:
            starts = self.client.get(f"/api/exams/{exam_id}/document-question-starts/{doc_type}")
            self.assertEqual(starts.status_code, 200, starts.text)
            self.client.post(f"/api/exams/{exam_id}/document-question-starts/{doc_type}/review", json={"candidates":starts.json()["candidates"]})
            main.STORE.complete_step(exam_id, step, {"candidates":starts.json()["candidates"], "reviewed_all_pages":True,
                                                       "document_sha256":starts.json()["document"]["sha256"]})

    def test_snippets_requires_explicit_confirmation_when_no_context_was_detected(self):
        exam_id = self.create_exam()
        self.complete_starts(exam_id)
        snippets = self.client.get(f"/api/exams/{exam_id}/snippets")
        self.assertEqual(snippets.status_code, 200, snippets.text)
        self.assertEqual(snippets.json()["context_count"], 0)
        numbers = [q["question_number"] for q in snippets.json()["opgaven"]["questions"]]
        payload = {"contexts":[], "reviewed_question_numbers":numbers,
                   "reviewed_uitwerk_numbers":[q["question_number"] for q in snippets.json()["uitwerkbijlage"]["questions"]],
                   "reviewed_cv_numbers":[q["question_number"] for q in snippets.json()["correctievoorschrift"]["questions"]]}
        blocked = self.client.post(f"/api/exams/{exam_id}/snippets/review", json=payload)
        self.assertEqual(blocked.status_code, 422)
        # Automatisch opslaan mag een onvolledige review bewaren; afronden
        # blijft geblokkeerd totdat de docent expliciet geen context bevestigt.
        draft = self.client.post(f"/api/exams/{exam_id}/snippets/review", json={**payload, "draft":True})
        self.assertEqual(draft.status_code, 200, draft.text)
        self.assertFalse(draft.json()["complete"])
        payload["confirmed_no_contexts"] = True
        accepted = self.client.post(f"/api/exams/{exam_id}/snippets/review", json=payload)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertTrue(accepted.json()["complete"])

    def test_final_review_requires_explanation_for_score_mismatch_and_allows_publication(self):
        exam_id = self.create_exam()
        self.complete_starts(exam_id)
        # De review-API's brongegevens komen normaal uit de eerdere werkstappen.
        main.STORE.complete_step(exam_id, "opgaven_analyse", {"questions":[
            {"question_number":1,"question_type":"meerkeuze","max_points":1}
        ]})
        main.STORE.complete_step(exam_id, "antwoorden", {"questions":[
            {"question_number":1,"answer_kind":"meerkeuze","answer_text":"B","cv_max_points":2}
        ]})
        main.STORE.complete_step(exam_id, "relaties", {"questions":[
            {"question_number":1,"reviewed":True,"note":""}
        ]})
        main.STORE.complete_step(exam_id, "snippets", {"reviewed_all_questions":True,
            "reviewed_all_contexts":True,"reviewed_all_uitwerk":True,"reviewed_all_cv":True,
            "expected_question_numbers":[1],"contexts":[],"confirmed_no_contexts":True})
        review = self.client.get(f"/api/exams/{exam_id}/final-review")
        self.assertEqual(review.status_code, 200, review.text)
        self.assertFalse(review.json()["questions"][0]["points_match"])
        blocked = self.client.post(f"/api/exams/{exam_id}/final-review/review", json={"questions":[
            {"question_number":1,"reviewed":True,"resolution_note":""}
        ]})
        self.assertEqual(blocked.status_code, 422)
        draft = self.client.post(f"/api/exams/{exam_id}/final-review/review", json={
            "draft":True,"questions":[{"question_number":1,"reviewed":True,"resolution_note":""}]
        })
        self.assertEqual(draft.status_code, 200, draft.text)
        self.assertFalse(draft.json()["complete"])
        accepted = self.client.post(f"/api/exams/{exam_id}/final-review/review", json={"questions":[
            {"question_number":1,"reviewed":True,"resolution_note":"De CV-score is leidend; verschil handmatig gecontroleerd."}
        ]})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        completed = self.client.post(f"/api/exams/{exam_id}/steps/eindcontrole/complete", json={"reviewed":True})
        self.assertEqual(completed.status_code, 200, completed.text)
        published = self.client.post(f"/api/exams/{exam_id}/publish")
        self.assertEqual(published.status_code, 200, published.text)
        listed = self.client.get("/api/exams").json()
        self.assertTrue(next(item for item in listed if item["id"] == exam_id)["published"])


    def test_final_review_autosave_does_not_rebuild_snippet_images(self):
        """POST autosaves validate from stored evidence, not expensive snippet generation."""
        exam_id = self.create_exam()
        main.STORE.complete_step(exam_id, "opgaven_analyse", {"questions":[
            {"question_number":1,"question_type":"meerkeuze","max_points":1}
        ]})
        main.STORE.complete_step(exam_id, "antwoorden", {"questions":[
            {"question_number":1,"answer_kind":"meerkeuze","answer_text":"B","cv_max_points":1}
        ]})
        main.STORE.complete_step(exam_id, "snippets", {"expected_question_numbers":[1]})

        # If the POST route still calls get_final_review(), this test fails.
        with patch.object(main, "get_final_review", side_effect=AssertionError("snippet images rebuilt")):
            saved = self.client.post(f"/api/exams/{exam_id}/final-review/review", json={
                "draft":True,
                "questions":[{"question_number":1,"reviewed":True,"resolution_note":""}]
            })
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertTrue(saved.json()["complete"])
            completed = self.client.post(f"/api/exams/{exam_id}/steps/eindcontrole/complete", json={
                "reviewed":True,"reviewed_all_questions":True
            })
        self.assertEqual(completed.status_code, 200, completed.text)

    def test_optional_workbook_can_be_skipped_only_when_absent(self):
        opgaven = self.pdf([["1p 1 Geef een verklaring."]])
        cv = self.pdf([["4 Beoordelingsmodel", "1 maximumscore 1", "Het antwoord moet blijken uit..."]])
        imported = self.client.post("/api/exams/import", files=[
            ("files", ("vw-1018-a-26-2-o.pdf", opgaven, "application/pdf")),
            ("files", ("vw-1018-a-26-2-c.pdf", cv, "application/pdf")),
        ])
        exam_id = imported.json()["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"vw-1018-a-26-2-o.pdf":"opgaven","vw-1018-a-26-2-c.pdf":"correctievoorschrift"}
        })
        skipped = self.client.post(f"/api/exams/{exam_id}/skip-optional-workbook")
        self.assertEqual(skipped.status_code, 200, skipped.text)
        exam = self.client.get(f"/api/exams/{exam_id}").json()
        self.assertEqual(exam["steps"]["uitwerk_starts"]["evidence"]["not_applicable"], True)
        self.assertEqual(exam["steps"]["uitwerk_fragments"]["evidence"]["not_applicable"], True)

    def test_reviewed_supplement_replaces_answer_proposal_and_stays_visible(self):
        opgaven = self.pdf([["1p 1 Geef het juiste antwoord."]])
        cv = self.pdf([["4 Beoordelingsmodel", "1 maximumscore 1", "A 1"]])
        workbook = self.pdf([["4", "schema"]])
        supplement = self.pdf([["Aanvulling op het correctievoorschrift", "Vraag 1: in plaats van het eerdere antwoord geldt: B. maximumscore 2."]])
        imported = self.client.post("/api/exams/import", files=[
            ("files", ("vw-1018-a-26-2-o.pdf", opgaven, "application/pdf")),
            ("files", ("vw-1018-a-26-2-u.pdf", workbook, "application/pdf")),
            ("files", ("vw-1018-a-26-2-c.pdf", cv, "application/pdf")),
            ("files", ("vw-1018-a-26-2-a.pdf", supplement, "application/pdf")),
        ])
        exam_id = imported.json()["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"vw-1018-a-26-2-o.pdf":"opgaven","vw-1018-a-26-2-u.pdf":"uitwerkbijlage",
                              "vw-1018-a-26-2-c.pdf":"correctievoorschrift","vw-1018-a-26-2-a.pdf":"aanvulling_correctievoorschrift"}
        })
        for doc_type, step in [("opgaven", "opgaven_starts"), ("correctievoorschrift", "cv_starts")]:
            starts = self.client.get(f"/api/exams/{exam_id}/document-question-starts/{doc_type}").json()
            main.STORE.complete_step(exam_id, step, {"candidates":starts["candidates"],"reviewed_all_pages":True,
                                                       "document_sha256":starts["document"]["sha256"]})
        main.STORE.complete_step(exam_id, "cv_aanvulling", {"items":[
            {"page_number":1,"action":"vervangen","question_numbers":[1],"reviewed":True}
        ],"reviewed_all_pages":True})
        answers = self.client.get(f"/api/exams/{exam_id}/answers")
        self.assertEqual(answers.status_code, 200, answers.text)
        question = answers.json()["questions"][0]
        self.assertEqual(question["answer_kind"], "handmatig")
        self.assertIn("Vraag 1", question["answer_text"])
        self.assertEqual(question["cv_max_points"], 2)
        self.assertEqual(question["supplement_pages"][0]["action"], "vervangen")

    def test_cv_fragment_review_uses_the_same_stitched_pagewide_workspace(self):
        """Stap 8 gebruikt dezelfde lange, paginabrede selectie als stap 3 en 6."""
        exam_id = self.create_exam()

        starts = self.client.get(
            f"/api/exams/{exam_id}/document-question-starts/correctievoorschrift"
        )
        self.assertEqual(starts.status_code, 200, starts.text)
        self.assertEqual([item["question_number"] for item in starts.json()["candidates"]], [1])
        saved_starts = self.client.post(
            f"/api/exams/{exam_id}/document-question-starts/correctievoorschrift/review",
            json={"candidates": starts.json()["candidates"]},
        )
        self.assertEqual(saved_starts.status_code, 200, saved_starts.text)
        main.STORE.complete_step(exam_id, "cv_starts", {
            "candidates": starts.json()["candidates"],
            "reviewed_all_pages": True,
            "document_sha256": starts.json()["document"]["sha256"],
        })

        # Een eerder concept kan nog oude PDF-puntgrenzen bevatten.
        # De nieuwe doorlopende review moet die verouderde coördinaten wissen.
        main.STORE.save_step_draft(exam_id, "cv_fragments", {
            "boundary_overrides": [{"question_number": 1, "start_y": 900.0, "end_y": 950.0}]
        })

        stitched = self.client.get(
            f"/api/exams/{exam_id}/stitched-document/correctievoorschrift"
        )
        self.assertEqual(stitched.status_code, 200, stitched.text)
        self.assertGreater(stitched.json()["width"], 0)
        self.assertGreater(stitched.json()["height"], 0)
        self.assertIn("/correctievoorschrift/exam-long.png", stitched.json()["image_url"])
        proposals = stitched.json()["proposed_selections"]
        self.assertTrue(proposals, "Voor de goedgekeurde CV-vraagstart moet een fragmentvoorstel bestaan.")

        selection = dict(proposals[0])
        selection.update({
            "type": "vraag",
            "question_numbers": [1],
            "label": "Vraag 1",
        })
        saved = self.client.post(
            f"/api/exams/{exam_id}/stitched-document/correctievoorschrift/review",
            json={"selections": [selection], "reviewed": False},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["selection_count"], 1)
        saved_evidence = self.client.get(f"/api/exams/{exam_id}").json()["steps"]["cv_fragments"]["evidence"]
        self.assertEqual(saved_evidence["boundary_overrides"], [])

        fragments = self.client.get(
            f"/api/exams/{exam_id}/document-question-fragments/correctievoorschrift"
        )
        self.assertEqual(fragments.status_code, 200, fragments.text)
        self.assertEqual(fragments.json()["question_count"], 1)
        question = fragments.json()["questions"][0]
        self.assertTrue(question["stitched"])
        # De eerste PDF-pagina bevat alleen algemene regels. Stap 8 begint
        # bewust pas op de pagina met de echte kop Beoordelingsmodel.
        self.assertEqual(question["first_page"], 2)
        self.assertEqual(question["last_page"], 2)
        self.assertIn("correctievoorschrift", question["segments"][0]["url"])

    def test_cv_detector_excludes_numbered_closed_answer_items(self):
        opgaven = self.pdf([["1p 1 Geef een verklaring."]])
        cv = self.pdf([["4 Beoordelingsmodel", "1 maximumscore 1", "2 B 2", "3 maximumscore 2", "1 onjuist", "2 juist", "3 juist"]])
        imported = self.client.post("/api/exams/import", files=[
            ("files", ("vw-1018-a-26-2-o.pdf", opgaven, "application/pdf")),
            ("files", ("vw-1018-a-26-2-c.pdf", cv, "application/pdf")),
        ])
        exam_id = imported.json()["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"vw-1018-a-26-2-o.pdf":"opgaven","vw-1018-a-26-2-c.pdf":"correctievoorschrift"}
        })
        result = self.client.get(f"/api/exams/{exam_id}/document-question-starts/correctievoorschrift")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([item["question_number"] for item in result.json()["candidates"]], [1,2,3])

