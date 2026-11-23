"""Regressietests voor automatische segmentatie in versie 0.13.

De tests gebruiken gecontroleerde geometrie. Ze controleren de
coördinaatomrekening en paginaovergangen, maar vervangen geen visuele
acceptatietest met echte examen-PDF's.
"""
import unittest

from examenverwerker.question_fragments import propose_stitched_question_selections


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


if __name__ == "__main__":
    unittest.main()
