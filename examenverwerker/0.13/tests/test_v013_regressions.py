"""Regressietests voor automatische segmentatie in versie 0.13.

De tests gebruiken gecontroleerde geometrie. Ze controleren de
coördinaatomrekening en paginaovergangen, maar vervangen geen visuele
acceptatietest met echte examen-PDF's.
"""
import unittest

from examenverwerker.question_fragments import propose_stitched_question_selections\nfrom examenverwerker.question_detection import detect_question_starts\nimport fitz\nfrom pathlib import Path\nimport tempfile


class StitchedProposalTests(unittest.TestCase):
    def test_creates_question_segments_and_keeps_page_transition(self):
        pages = [
            {"page_number": 2, "top": 0, "bottom": 1000,
             "crop_pixels": [0, 100, 1000, 900],
             "render_width": 1000, "stitched_width": 1000},
            {"page_number": 3, "top": 1028, "bottom": 2028,
             "crop_pixels": [0, 100, 1000, 900],
             "render_width": 1000, "stitched_width": 1000},
        ]
        starts = [
            {"question_number": 1, "page_index": 1, "pdf_bbox": [40, 120, 60, 140]},
            {"question_number": 2, "page_index": 1, "pdf_bbox": [40, 420, 60, 440]},
            {"question_number": 3, "page_index": 2, "pdf_bbox": [40, 180, 60, 200]},
        ]
        selections = propose_stitched_question_selections(
            pages, starts, render_scale=1.25, image_height=2028
        )
        self.assertEqual([item["question_numbers"] for item in selections], [[1], [2], [3]])
        self.assertTrue(all(item["bottom"] > item["top"] for item in selections))
        self.assertGreater(selections[1]["bottom"], 1000)
        self.assertEqual(selections[-1]["bottom"], 2028)

    def test_empty_or_unmappable_starts_produce_no_proposals(self):
        pages = [{"page_number": 2, "top": 0, "bottom": 500,
                  "crop_pixels": [0, 0, 100, 500],
                  "render_width": 100, "stitched_width": 100}]
        self.assertEqual(propose_stitched_question_selections(pages, [], image_height=500), [])
        invalid = [{"question_number": 1, "page_index": 8, "pdf_bbox": [0, 1, 2, 3]}]
        self.assertEqual(propose_stitched_question_selections(pages, invalid, image_height=500), [])

    def test_statement_number_reset_is_not_accepted_as_main_questions(self):
        # Simuleer hoofdvragen 1-8, gevolgd door drie stellingen 1-3 en
        # vervolgens de echte hoofdvraag 9. De LIS-filter moet de stellingen
        # als verdachte kandidaten bewaren, maar niet automatisch accepteren.
        with tempfile.TemporaryDirectory() as folder:
            pdf_path = Path(folder) / "number-reset.pdf"
            pdf = fitz.open()
            page = pdf.new_page(width=595, height=842)
            for index, number in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 9]):
                page.insert_text((42, 55 + index * 28), str(number), fontsize=12)
            pdf.save(pdf_path)
            pdf.close()

            result = detect_question_starts(str(pdf_path))
            candidates = result["candidates"]
            accepted_numbers = [item["question_number"] for item in candidates if item["accepted"]]
            rejected_numbers = [item["question_number"] for item in candidates if not item["accepted"]]

        self.assertEqual(accepted_numbers, [1, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertEqual(rejected_numbers, [1, 2, 3])
        self.assertTrue(all(item["sequence_warning"] for item in candidates if not item["accepted"]))

    def test_sparse_real_main_question_numbers_remain_accepted(self):
        # Echte examens slaan soms vraagnummers over in een documentdeel.
        # Een sprong vooruit is daarom toegestaan zolang de reeks oploopt.
        with tempfile.TemporaryDirectory() as folder:
            pdf_path = Path(folder) / "sparse-numbers.pdf"
            pdf = fitz.open()
            page = pdf.new_page(width=595, height=842)
            numbers = [12, 13, 14, 17, 18, 25, 26, 31, 32]
            for index, number in enumerate(numbers):
                page.insert_text((42, 55 + index * 35), str(number), fontsize=12)
            pdf.save(pdf_path)
            pdf.close()

            result = detect_question_starts(str(pdf_path))

        self.assertEqual([item["question_number"] for item in result["candidates"]], numbers)
        self.assertTrue(all(item["accepted"] for item in result["candidates"]))


if __name__ == "__main__":
    unittest.main()
