"""Regressietests voor antwoordherkenning en veilige CV-aanvullingen."""
import tempfile
import unittest
from pathlib import Path

import fitz

from examenverwerker.answer_detection import detect_cv_answer, detect_cv_max_points, validate_answer_review
from examenverwerker.cv_supplement import analyse_supplement, validate_supplement_review


class AnswerAndSupplementTests(unittest.TestCase):
    def test_multiple_choice_answer_requires_explicit_letter_and_score(self):
        result = detect_cv_answer("2\nB 2\n", 2)
        self.assertEqual(result["answer_kind"], "meerkeuze")
        self.assertEqual(result["answer_text"], "B")
        # De PDF-tekstextractie kan alle drie kolommen op één regel zetten.
        table_result = detect_cv_answer("2 B 2\n", 2)
        self.assertEqual(table_result["answer_kind"], "meerkeuze")
        self.assertEqual(table_result["answer_text"], "B")

    def test_cv_maximum_score_is_recognised_when_label_and_value_are_split(self):
        self.assertEqual(detect_cv_max_points("Maximumscore 2", 1), 2)
        self.assertEqual(detect_cv_max_points("Maximumscore\n2", 1), 2)
        self.assertEqual(detect_cv_max_points("Maximum\nscore\n3", 1), 3)
        self.assertEqual(detect_cv_max_points("maximum score: 4", 1), 4)

    def test_closed_answer_list_is_recognised_in_order(self):
        result = detect_cv_answer("9 maximumscore 2\n1 onjuist\n2 juist\n3 juist\n")
        self.assertEqual(result["answer_kind"], "gesloten")
        self.assertEqual(result["answer_text"], "1. onjuist\n2. juist\n3. juist")

    def test_open_rubric_is_preserved_instead_of_reduced_to_a_guess(self):
        text = "1 maximumscore 2\nUit het antwoord moet blijken dat\n• de diffusieafstand toeneemt."
        result = detect_cv_answer(text)
        self.assertEqual(result["answer_kind"], "open")
        self.assertIn("diffusieafstand", result["answer_text"])

    def test_answer_review_requires_every_question(self):
        result = validate_answer_review({"questions":[
            {"question_number":1,"answer_kind":"meerkeuze","answer_text":"B","reviewed":True},
            {"question_number":2,"answer_kind":"gesloten","answer_text":"1. juist","reviewed":False},
        ]}, {1,2})
        self.assertFalse(result["reviewed_all_questions"])
        with self.assertRaisesRegex(ValueError, "Niet alle CV-vragen"):
            validate_answer_review({"questions":[
                {"question_number":1,"answer_kind":"meerkeuze","answer_text":"B","reviewed":True}
            ]}, {1,2})

    def test_supplement_page_is_never_automatically_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "supplement.pdf"
            pdf = fitz.open()
            page = pdf.new_page()
            page.insert_text((60, 80), "Aanvulling op het correctievoorschrift")
            page.insert_text((60, 110), "Vraag 22: in plaats van het eerdere antwoord geldt...")
            pdf.save(path)
            pdf.close()
            result = analyse_supplement(str(path))
        self.assertEqual(result["items"][0]["action"], "vervangen")
        self.assertEqual(result["items"][0]["question_numbers"], [22])
        # Een voorstel is pas een bewaarde docentbeslissing na expliciete review.
        review = validate_supplement_review({"items":[
            {"page_number":1,"action":"vervangen","question_numbers":[22],"reviewed":True}
        ]}, {1})
        self.assertTrue(review["reviewed_all_pages"])
        self.assertEqual(review["merge_policy"], "reviewed_decisions_only")

    def test_supplement_question_mapping_is_validated(self):
        with self.assertRaisesRegex(ValueError, "Ongeldige vraagkoppeling"):
            validate_supplement_review({"items":[
                {"page_number":1,"action":"vervangen","question_numbers":[0,61],"reviewed":True}
            ]}, {1})

    def test_supplement_page_text_is_split_per_question_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multi-question-supplement.pdf"
            pdf = fitz.open()
            page = pdf.new_page()
            page.insert_textbox((60, 60, 520, 760),
                "Aanvulling op het correctievoorschrift\nVraag 12: het antwoord wordt uitgebreid met een biologisch juiste toelichting.\nVraag 13: voor deze vraag geldt een andere beoordelingsregel.",
                fontsize=10)
            pdf.save(path)
            pdf.close()
            result = analyse_supplement(str(path))
        question_texts = result["items"][0]["question_texts"]
        self.assertIn("Vraag 12", question_texts["12"])
        self.assertNotIn("Vraag 13", question_texts["12"])
        self.assertIn("Vraag 13", question_texts["13"])

