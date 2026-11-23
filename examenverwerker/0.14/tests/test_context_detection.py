"""Tests voor contextvoorstellen en contextkoppelingen."""
import tempfile
import unittest
from pathlib import Path

import fitz

from examenverwerker.context_detection import generate_context_candidates, validate_context_review


class ContextDetectionTests(unittest.TestCase):
    def test_context_before_first_question_is_rendered_and_grouped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((60, 70), "Onderwerp over een biologisch proces", fontsize=14)
            page.insert_textbox((60, 100, 520, 260), "Wetenschappers onderzochten verschillende organismen en beschreven de omstandigheden waaronder dit proces plaatsvindt. De resultaten laten zien hoe de betrokken organismen reageren op veranderingen in hun leefomgeving en welke factoren daarbij een rol spelen.", fontsize=10)
            page.insert_text((60, 360), "Vraag 1 begint hier", fontsize=10)
            path = root / "context.pdf"
            doc.save(path)
            doc.close()
            result = generate_context_candidates(path,
                [{"question_number":1,"page_index":0,"pdf_bbox":[60,350,90,365]},
                 {"question_number":2,"page_index":0,"pdf_bbox":[60,500,90,515]}],
                root / "derived")
            self.assertEqual(result["context_count"], 1)
            context = result["contexts"][0]
            self.assertEqual(context["from_question"], 1)
            self.assertEqual(context["to_question"], 2)
            self.assertTrue((root / "derived" / context["filename"]).is_file())

    def test_context_review_requires_all_contexts_and_valid_question_range(self):
        payload = {"contexts":[{"id":"context-p1","from_question":1,"to_question":3,"reviewed":True}]}
        result = validate_context_review(payload, {"context-p1"}, {1,2,3,4})
        self.assertTrue(result["reviewed_all_contexts"])
        with self.assertRaisesRegex(ValueError, "niet-bestaand vraagnummer"):
            validate_context_review({"contexts":[{"id":"context-p1","from_question":1,"to_question":5,"reviewed":True}]},
                                    {"context-p1"}, {1,2,3,4})
