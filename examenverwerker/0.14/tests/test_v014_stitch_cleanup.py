"""Regressietests voor opschonen en contextvoorstellen in versie 0.14."""

import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image

from examenverwerker.question_fragments import build_stitched_exam
from examenverwerker.context_detection import generate_context_candidates


class StitchedPageCleanupTests(unittest.TestCase):
    def test_footer_page_number_is_masked_before_page_crop(self):
        """Een los paginanummer mag de ondergrens van de crop niet bepalen."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "exam.pdf"
            output = root / "exam-long.png"

            pdf = fitz.open()
            pdf.new_page(width=600, height=800)  # Voorblad: wordt overgeslagen.
            page = pdf.new_page(width=600, height=800)
            page.insert_text((55, 110), "Een inhoudelijke context begint hier.", fontsize=12)
            page.insert_text((55, 150), "De tweede regel bevat voldoende zichtbare inhoud.", fontsize=12)
            page.insert_text((300, 780), "2", fontsize=10)  # Los paginanummer in footer.
            pdf.save(source)
            pdf.close()

            metadata = build_stitched_exam(source, output, render_scale=1.25)
            self.assertEqual(len(metadata["pages"]), 1)
            crop = metadata["pages"][0]["crop_pixels"]
            full_render_height = metadata["pages"][0]["source_height"] * 1.25

            # De crop eindigt bij de echte inhoud en niet bij het paginanummer
            # onderaan de oorspronkelijke pagina.
            self.assertLess(crop[3], full_render_height * 0.50)
            self.assertTrue(output.is_file())
            with Image.open(output) as stitched:
                self.assertEqual(stitched.height, metadata["height"])

    def test_page_crops_are_stitched_with_small_explicit_gap(self):
        """De totale hoogte is de som van de afzonderlijke crops plus de gap."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "two-pages.pdf"
            output = root / "stitched.png"

            pdf = fitz.open()
            pdf.new_page(width=600, height=800)
            for page_number in range(2):
                page = pdf.new_page(width=600, height=800)
                page.insert_text((60, 100), f"Inhoud pagina {page_number + 2}", fontsize=14)
                page.insert_text((60, 145), "Nog een inhoudelijke regel.", fontsize=12)
            pdf.save(source)
            pdf.close()

            metadata = build_stitched_exam(source, output, render_scale=1.25)
            expected = sum(item["stitched_height"] for item in metadata["pages"])
            expected += metadata["page_gap"] * (len(metadata["pages"]) - 1)
            self.assertEqual(metadata["height"], expected)
            self.assertEqual(metadata["page_gap"], 12)


class ContextProposalTests(unittest.TestCase):
    def test_context_above_first_question_is_proposed_for_manual_review(self):
        """Een inhoudelijk tekstblok boven vraag 1 wordt als context voorgesteld."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "context.pdf"
            output = root / "contexts"

            pdf = fitz.open()
            pdf.new_page(width=600, height=800)
            page = pdf.new_page(width=600, height=800)
            context_lines = [
                "In een ecosysteem leven organismen samen en beïnvloeden zij elkaar.",
                "Onderzoekers meten veranderingen in populaties gedurende het jaar.",
            ]
            for index, line in enumerate(context_lines):
                page.insert_text((50, 80 + index * 22), line, fontsize=11)
            page.insert_text((50, 170), "1", fontsize=12)
            pdf.save(source)
            pdf.close()

            starts = [{
                "question_number": 1,
                "page_index": 1,
                "pdf_bbox": [50, 180, 60, 195],
            }]
            result = generate_context_candidates(source, starts, output)
            self.assertEqual(result["context_count"], 1)
            self.assertEqual(result["contexts"][0]["from_question"], 1)
            self.assertEqual(result["contexts"][0]["to_question"], 1)
            self.assertTrue((output / result["contexts"][0]["filename"]).is_file())


if __name__ == "__main__":
    unittest.main()
