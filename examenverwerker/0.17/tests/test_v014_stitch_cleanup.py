"""Regressietests voor opschonen en contextvoorstellen in versie 0.14."""

import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from examenverwerker.question_fragments import build_stitched_exam, propose_stitched_question_selections, cv_model_start, normalise_stitched_selections
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
            page.insert_text((45, 780), "VW-1018-a-26-2-o     2 / 19     lees verder ►►►", fontsize=9)  # Samengestelde examenfooter.
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

    def test_cv_stitch_starts_at_real_assessment_model_heading(self):
        """Pagina's vóór hoofdstuk 4 en de ruimte boven de kop vallen buiten stap 8."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "cv.pdf"
            output = root / "cv-long.png"

            pdf = fitz.open()
            toc = pdf.new_page(width=600, height=800)
            toc.insert_text((50, 90), "4 Beoordelingsmodel", fontsize=9)
            preamble = pdf.new_page(width=600, height=800)
            preamble.insert_text((50, 110), "Algemene toelichting op het correctievoorschrift.", fontsize=12)
            model = pdf.new_page(width=600, height=800)
            model.insert_text((50, 90), "4 Beoordelingsmodel", fontsize=18)
            model.insert_text((50, 150), "1 maximumscore 2", fontsize=12)
            model.insert_text((50, 180), "Het antwoord moet blijken uit de gegevens.", fontsize=12)
            pdf.save(source)
            pdf.close()

            with fitz.open(source) as source_pdf:
                start_page, start_y = cv_model_start(source_pdf)
            self.assertEqual(start_page, 2)
            self.assertGreater(start_y, 0)

            metadata = build_stitched_exam(
                source, output, start_page=start_page, start_y=start_y,
                end_page=2, render_scale=1.0,
            )
            self.assertEqual([item["page_number"] for item in metadata["pages"]], [3])
            self.assertGreaterEqual(metadata["pages"][0]["crop_pixels"][1], round(start_y))

    def test_last_question_fragment_stops_after_last_visible_content_row(self):
        """Een leeg stuk onder het antwoord wordt niet in het vraagfragment opgenomen."""
        with tempfile.TemporaryDirectory() as folder:
            image_path = Path(folder) / "stitched.png"
            image = Image.new("RGB", (100, 180), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((10, 55, 90, 82), fill="black")
            image.save(image_path)
            image.close()

            result = normalise_stitched_selections(
                [{"id":"q1","type":"vraag","top":50,"bottom":160,
                  "question_numbers":[1],"label":"Vraag 1"}],
                [[0, 4], [45, 49], [83, 87], [120, 124], [150, 154]],
                image_path,
                image_height=180,
                leading_top=0,
            )
            question = next(item for item in result if item["type"] == "vraag")
            self.assertEqual(question["bottom"], 83)

    def test_question_number_survives_when_footer_marker_shares_its_text_line(self):
        """Een vraagnummer op dezelfde regel als een paginateller mag niet verdwijnen."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "mixed-footer-line.pdf"
            output = root / "mixed-footer-line-long.png"

            pdf = fitz.open()
            page = pdf.new_page(width=600, height=800)
            page.insert_text((55, 150), "Inhoudelijke tekst boven de vraag.", fontsize=12)
            # Sommige PDF's leveren de vraag en footer als één tekstspan/regel.
            # De volledige regel mag dan niet als voettekst worden gemaskeerd.
            page.insert_text((55, 780), "Vraag 28   2 / 19   lees verder", fontsize=9)
            pdf.save(source)
            pdf.close()

            metadata = build_stitched_exam(source, output, start_page=0, render_scale=1.0)
            crop_top = metadata["pages"][0]["crop_pixels"][1]
            with Image.open(output) as stitched:
                # Zoek in het gebied waar 'Vraag 28' is afgedrukt naar niet-witte
                # pixels. Daarmee testen we de uiteindelijke afbeelding, niet
                # alleen de PDF-tekstlaag of de metadata.
                question_y = 780 - crop_top
                question_area = stitched.crop((45, max(0, question_y - 18), 180, question_y + 5))
                self.assertLess(sum(1 for pixel in question_area.convert("L").getdata() if pixel < 180), 5000)
                self.assertGreater(
                    sum(1 for pixel in question_area.convert("L").getdata() if pixel < 180),
                    0,
                )

    def test_question_number_in_separate_span_survives_footer_cleanup(self):
        """Een apart PDF-span met vraagnummer blijft staan naast losse footer-spans."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "separate-footer-spans.pdf"
            output = root / "separate-footer-spans-long.png"

            pdf = fitz.open()
            page = pdf.new_page(width=600, height=800)
            page.insert_text((55, 150), "Inhoudelijke tekst blijft behouden.", fontsize=12)
            # De PDF bewaart de vraag en de footer als afzonderlijke spans op
            # dezelfde regel. Het vraagnummer mag niet als paginanummer gelden.
            page.insert_text((45, 780), "Vraag 30", fontsize=9)
            page.insert_text((115, 780), "2 / 19", fontsize=9)
            page.insert_text((165, 780), "lees verder", fontsize=9)
            pdf.save(source)
            pdf.close()

            metadata = build_stitched_exam(source, output, start_page=0, render_scale=1.0)
            with Image.open(output) as stitched:
                crop_top = metadata["pages"][0]["crop_pixels"][1]
                question_y = 780 - crop_top
                question_area = stitched.crop((35, max(0, question_y - 18), 110, question_y + 5))
                dark_pixels = sum(
                    1 for pixel in question_area.convert("L").getdata() if pixel < 180
                )
                self.assertGreater(dark_pixels, 0, "Vraag 30 is ten onrechte uit de examenstrook verwijderd.")

    def test_standalone_question_numbers_28_and_30_survive_at_bottom_margin(self):
        """Een los vraagnummer onderaan de pagina mag nooit als paginanummer verdwijnen."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "standalone-question-numbers.pdf"
            output = root / "standalone-question-numbers-long.png"

            pdf = fitz.open()
            for question_number in (28, 30):
                page = pdf.new_page(width=600, height=800)
                page.insert_text((55, 150), "De inhoudelijke vraagtekst staat hierboven.", fontsize=12)
                # Dit bootst een vraagkop na die door de PDF-export als een
                # zelfstandige numerieke regel in de onderste marge is opgeslagen.
                page.insert_text((55, 780), str(question_number), fontsize=12)
            pdf.save(source)
            pdf.close()

            metadata = build_stitched_exam(source, output, start_page=0, render_scale=1.0)
            self.assertEqual(len(metadata["pages"]), 2)
            with Image.open(output) as stitched:
                for page_meta in metadata["pages"]:
                    # De vraagnummerregel hoort binnen de gerenderde paginacrop
                    # te blijven. Controleer de daadwerkelijke pixelinhoud.
                    crop_top = page_meta["crop_pixels"][1]
                    number_y = 780 - crop_top
                    number_area = stitched.crop(
                        (45, max(0, number_y - 18), 90, number_y + 5)
                    )
                    dark_pixels = sum(
                        1 for pixel in number_area.convert("L").getdata() if pixel < 180
                    )
                    self.assertGreater(
                        dark_pixels, 0,
                        "Een zelfstandig vraagnummer in de onderste marge is verwijderd.",
                    )

    def test_repeated_standalone_page_numbers_are_still_removed(self):
        """Echte losse paginanummers worden herkend aan hun herhaalde positie."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "repeated-page-numbers.pdf"
            output = root / "repeated-page-numbers-long.png"

            pdf = fitz.open()
            pdf.new_page(width=600, height=800)  # Omslag.
            for page_number in (2, 3):
                page = pdf.new_page(width=600, height=800)
                page.insert_text((55, 150), "Inhoudelijke tekst blijft behouden.", fontsize=12)
                page.insert_text((300, 780), str(page_number), fontsize=9)
            pdf.save(source)
            pdf.close()

            metadata = build_stitched_exam(source, output, render_scale=1.0)
            self.assertEqual(len(metadata["pages"]), 2)
            for page_meta in metadata["pages"]:
                self.assertLess(
                    page_meta["crop_pixels"][3], 400,
                    "Een herhaald paginanummer is ten onrechte als inhoud behouden.",
                )

    def test_standalone_exam_code_in_footer_is_removed(self):
        """Ook een losse Cito-documentcode in de onderste marge wordt gemaskeerd."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "footer-code.pdf"
            output = root / "footer-code-long.png"

            pdf = fitz.open()
            page = pdf.new_page(width=600, height=800)
            page.insert_text((55, 110), "Inhoudelijke beoordelingsregel staat hier.", fontsize=12)
            page.insert_text((55, 720), "VW-1018-a-26-2-c", fontsize=9)
            pdf.save(source)
            pdf.close()

            metadata = build_stitched_exam(source, output, start_page=0, render_scale=1.0)
            crop = metadata["pages"][0]["crop_pixels"]
            self.assertLess(crop[3], 300)

    def test_page_crops_are_stitched_with_clear_white_separator(self):
        """De totale hoogte is de som van de crops plus een duidelijk zichtbare witte scheidingsstrook."""
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
            self.assertEqual(metadata["page_gap"], 32)


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



class StitchedSelectionNormalisationTests(unittest.TestCase):
    def test_overlapping_questions_are_clamped_and_blank_context_is_removed(self):
        """Vragen op dezelfde pagina mogen niet overlappen; witruimte is geen context."""
        from PIL import Image, ImageDraw
        from examenverwerker.question_fragments import normalise_stitched_selections

        with tempfile.TemporaryDirectory() as folder:
            image_path = Path(folder) / "stitched.png"
            image = Image.new("RGB", (100, 180), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((10, 10, 90, 35), fill="black")   # zichtbare context
            draw.rectangle((10, 60, 90, 82), fill="black")   # vraag 1
            draw.rectangle((10, 100, 90, 125), fill="black") # vraag 2
            image.save(image_path)
            image.close()

            result = normalise_stitched_selections(
                [
                    {"id":"q1","type":"vraag","top":55,"bottom":110,
                     "question_numbers":[1],"label":"Vraag 1"},
                    {"id":"q2","type":"vraag","top":95,"bottom":140,
                     "question_numbers":[2],"label":"Vraag 2"},
                    {"id":"empty-context","type":"context","top":83,"bottom":95,
                     "question_numbers":[2]},
                ],
                [[0, 4], [40, 44], [55, 59], [83, 87], [95, 99], [126, 130], [150, 154]],
                image_path,
                image_height=180,
                leading_top=0,
            )

            questions = [item for item in result if item["type"] == "vraag"]
            contexts = [item for item in result if item["type"] == "context"]
            self.assertEqual(len(questions), 2)
            self.assertLessEqual(questions[0]["bottom"], questions[1]["top"])
            # De strook tussen de vragen is volledig wit en mag geen context worden.
            self.assertFalse(any(item["top"] == 83 and item["bottom"] == 95 for item in contexts))
            # Een inleidende context wordt gekoppeld aan de daaropvolgende
            # vragen tot aan het volgende contextblok. In dit voorbeeld is er
            # geen tweede contextblok, dus vallen vraag 1 en 2 in dezelfde groep.
            self.assertEqual(contexts[0]["question_numbers"], [1, 2])


class QuestionAndContextSegmentationTests(unittest.TestCase):
    def test_questions_are_bounded_by_visual_gaps_and_context_is_the_space_between(self):
        """Vraagfragmenten worden door witregels begrensd; tussenruimtes worden context."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "segmentation.pdf"
            output = root / "stitched.png"

            pdf = fitz.open()
            pdf.new_page(width=600, height=800)  # Voorblad.
            page = pdf.new_page(width=600, height=800)
            page.insert_text((50, 90), "Een context beschrijft een ecosysteem.", fontsize=12)
            page.insert_text((50, 125), "Onderzoekers volgen de populatie.", fontsize=12)
            page.insert_text((50, 190), "1 Welke organismen komen voor?", fontsize=12)
            page.insert_text((50, 215), "Noem twee voorbeelden.", fontsize=12)
            page.insert_text((50, 285), "In het gebied verandert de temperatuur.", fontsize=12)
            page.insert_text((50, 310), "Ook de voedselbeschikbaarheid neemt af.", fontsize=12)
            page.insert_text((50, 390), "2 Leg uit wat er met de populatie gebeurt.", fontsize=12)
            page.insert_text((50, 415), "Gebruik de gegevens uit de context.", fontsize=12)
            pdf.save(source)
            pdf.close()

            metadata = build_stitched_exam(source, output, render_scale=1.25)
            starts = [
                {"question_number":1,"page_index":1,"pdf_bbox":[50,188,60,202]},
                {"question_number":2,"page_index":1,"pdf_bbox":[50,388,60,402]},
            ]
            selections = propose_stitched_question_selections(
                metadata["pages"], starts, image_height=metadata["height"], pdf_path=source
            )
            questions = [item for item in selections if item["type"] == "vraag"]
            contexts = [item for item in selections if item["type"] == "context"]
            self.assertEqual(len(questions), 2)
            self.assertEqual(len(contexts), 2)
            # De eerste context staat vóór vraag 1 en hoort bij vraag 1.
            # De tweede staat vóór vraag 2 en hoort bij die daaropvolgende
            # vraag, niet bij de voorafgaande vraag 1.
            self.assertEqual(contexts[0]["question_numbers"], [1])
            self.assertEqual(contexts[1]["question_numbers"], [2])
            self.assertGreater(contexts[0]["bottom"], contexts[0]["top"])
            self.assertLessEqual(contexts[0]["bottom"], questions[0]["top"])
            self.assertLessEqual(questions[0]["bottom"], contexts[1]["top"])
            self.assertLessEqual(contexts[1]["bottom"], questions[1]["top"])


if __name__ == "__main__":
    unittest.main()
