"""Tests voor hoofdvraagherkenning en het opslaan van visuele correcties."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import Image
from fastapi.testclient import TestClient

from examenverwerker import main
from examenverwerker.storage import Store
from examenverwerker.question_detection import detect_question_starts, validate_review
from examenverwerker.question_fragments import generate_question_fragments, build_stitched_exam, normalise_stitched_selections
from examenverwerker.question_analysis import analyse_questions, detect_options, detect_question_type, detect_max_points, detect_closed_answer_form, validate_question_analysis


class QuestionDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        main.DATA = self.root
        main.STORE = Store(self.root)
        self.client = TestClient(main.app)

    def tearDown(self):
        self.temp.cleanup()

    def make_pdf(self):
        doc = fitz.open()
        page = doc.new_page()
        # Een vraagnummer op een eigen regel is een kandidaat. Een subnummer,
        # een getal midden in een zin en een paginavoet zijn dat nadrukkelijk niet.
        page.insert_text((60, 70), "1\nWat is de functie van dit orgaan?\n1a\nNoem twee kenmerken.\nDe temperatuur is 37 graden.", fontsize=11)
        page.insert_text((60, 130), "2. Beschrijf de bouw van het orgaan.", fontsize=11)
        page.insert_text((60, 800), "3", fontsize=8)
        data = doc.tobytes()
        doc.close()
        return data

    def test_multiple_choice_options_support_separate_letter_lines_and_two_options(self):
        # PDF-tekstextractie kan de antwoordletter en antwoordtekst splitsen.
        extracted = "Kies het juiste antwoord.\nA.\nDe celkern bevat DNA.\nB.\nHet celmembraan bevat cellulose."
        options = detect_options(extracted)
        self.assertEqual([item["letter"] for item in options], ["A", "B"])
        self.assertEqual(options[0]["text"], "De celkern bevat DNA.")
        self.assertEqual(detect_question_type(extracted, options)[0], "meerkeuze")

    def test_multiple_choice_options_support_inline_and_parenthesised_markers(self):
        # Sommige PDF-tekstlagen zetten meerdere antwoordopties achter elkaar
        # op één regel; andere gebruiken haakjes of een dubbele punt.
        inline = "Kies het juiste antwoord. A. De celkern bevat DNA. B) Het membraan bevat cellulose. C: Ribosomen maken eiwitten."
        options = detect_options(inline)
        self.assertEqual([item["letter"] for item in options], ["A", "B", "C"])
        self.assertIn("De celkern bevat DNA", options[0]["text"])
        self.assertIn("Het membraan bevat cellulose", options[1]["text"])
        self.assertIn("Ribosomen maken eiwitten", options[2]["text"])

    def test_multiple_choice_numeric_single_character_options_are_kept(self):
        # In VWO 2026-II vragen 2 en 25 zijn antwoordopties getallen.
        # Een antwoord als "A 9" of "A 0" mag niet verdwijnen omdat de
        # antwoordtekst maar één teken bevat.
        question_two = "A 9\nB 19\nC 24\nD 26"
        question_twenty_five = "A 0\nB 504\nC 1008\nD 95.247\nE 190.494"
        self.assertEqual(
            [(item["letter"], item["text"]) for item in detect_options(question_two)],
            [("A", "9"), ("B", "19"), ("C", "24"), ("D", "26")],
        )
        self.assertEqual(
            [(item["letter"], item["text"]) for item in detect_options(question_twenty_five)],
            [("A", "0"), ("B", "504"), ("C", "1008"), ("D", "95.247"), ("E", "190.494")],
        )

    def test_multiple_choice_supports_six_options_through_f(self):
        # VWO 2026-II vraag 28 bevat zes antwoordopties, A tot en met F.
        options_text = "\n".join(
            f"{letter} 5’- SEQUENTIE {letter} - 3’"
            for letter in "ABCDEF"
        )
        self.assertEqual(
            [item["letter"] for item in detect_options(options_text)],
            list("ABCDEF"),
        )
        payload = {
            "questions": [{
                "question_number": 28,
                "question_type": "meerkeuze",
                "max_points": 2,
                "options": detect_options(options_text),
                "reviewed": True,
            }]
        }
        validated = validate_question_analysis(payload, {28})
        self.assertEqual(len(validated["questions"][0]["options"]), 6)

    def test_option_ocr_is_skipped_for_recognised_sets_and_open_questions(self):
        # Vermijd OCR als de PDF-tekst al opties bevat of als een vraag
        # duidelijk open is en geen aanwijzingen voor meerkeuze bevat.
        from examenverwerker.question_analysis import _should_run_option_ocr
        self.assertFalse(_should_run_option_ocr("A 9\nB 19\nC 24", [
            {"letter": "A", "text": "9"}, {"letter": "B", "text": "19"}
        ]))
        self.assertFalse(_should_run_option_ocr("Leg uit waarom dit gebeurt.", []))
        self.assertTrue(_should_run_option_ocr("A 9\nB 19", []))
        self.assertTrue(_should_run_option_ocr("", []))

    def test_multiple_choice_options_reject_nonconsecutive_letter_noise(self):
        # Een losse letter in lopende tekst mag niet als complete antwoordset
        # worden geïnterpreteerd.
        self.assertEqual(detect_options("A. Dit is een gewone zin. Daarna volgt optie C in de uitleg."), [])

    def test_visual_ocr_rebuilds_lines_from_separate_option_labels_and_text(self):
        # RapidOCR levert tekstregels met bounding boxes. Deze test bootst
        # antwoordletters en antwoordteksten na die visueel op dezelfde regel
        # staan, maar als losse OCR-detecties worden teruggegeven.
        image_path = self.root / "visual-options.png"
        Image.new("RGB", (120, 50), "white").save(image_path)

        class FakeOCRResult:
            boxes = [
                [[0, 0], [12, 0], [12, 10], [0, 10]],
                [[18, 0], [110, 0], [110, 10], [18, 10]],
                [[0, 20], [12, 20], [12, 30], [0, 30]],
                [[18, 20], [110, 20], [110, 30], [18, 30]],
            ]
            txts = ["A.", "De celkern bevat DNA.", "B.", "Het celmembraan bevat cellulose."]

        class FakeEngine:
            def __call__(self, _path):
                return FakeOCRResult()

        # Gebruik de modulefunctie rechtstreeks; de expliciete import houdt
        # de test onafhankelijk van interne attributen van main.py.
        from examenverwerker.question_analysis import _ocr_image_text
        with patch("examenverwerker.question_analysis._get_ocr_engine", return_value=FakeEngine()):
            recognised = _ocr_image_text([image_path])

        self.assertEqual(
            recognised.splitlines(),
            ["A. De celkern bevat DNA.", "B. Het celmembraan bevat cellulose."],
        )

    def test_new_ocr_proposals_update_old_unreviewed_analysis_drafts(self):
        # Oude concepten konden een eerder onjuist voorstel 'open' met lege
        # opties blijven terugzetten. Een nieuwe OCR-herkenning moet die lege
        # velden aanvullen, zonder bestaande handmatige antwoordteksten kwijt
        # te raken.
        question = {
            "question_number": 4,
            "question_type": "meerkeuze",
            "max_points": 2,
            "options": [
                {"letter": "A", "text": "Nieuwe optie A"},
                {"letter": "B", "text": "Nieuwe optie B"},
            ],
            "reviewed": False,
        }
        old_draft = {
            "question_type": "open",
            "max_points": None,
            "options": [],
            "reviewed": False,
        }
        main._merge_saved_question_analysis(question, old_draft)
        self.assertEqual(question["question_type"], "meerkeuze")
        self.assertEqual([item["letter"] for item in question["options"]], ["A", "B"])

        # Een bestaande handmatige tekst blijft behouden, terwijl een optie
        # die pas door de nieuwe OCR is gevonden alsnog wordt toegevoegd.
        question["options"] = [
            {"letter": "A", "text": "Nieuwe optie A"},
            {"letter": "B", "text": "Nieuwe optie B"},
        ]
        manual_draft = {
            "question_type": "open",
            "max_points": None,
            "options": [{"letter": "A", "text": "Handmatig gecorrigeerde optie A"}],
            "reviewed": False,
        }
        main._merge_saved_question_analysis(question, manual_draft)
        self.assertEqual(question["question_type"], "meerkeuze")
        self.assertEqual(
            question["options"],
            [
                {"letter": "A", "text": "Handmatig gecorrigeerde optie A"},
                {"letter": "B", "text": "Nieuwe optie B"},
            ],
        )

    def test_reviewed_question_analysis_is_never_overwritten_by_new_detection(self):
        # Een expliciet door de docent gecontroleerde keuze blijft leidend,
        # ook wanneer de automatische analyse later andere signalen vindt.
        question = {
            "question_number": 5,
            "question_type": "meerkeuze",
            "max_points": 2,
            "options": [{"letter": "A", "text": "OCR-voorstel"}],
            "reviewed": False,
        }
        reviewed = {
            "question_type": "open",
            "max_points": 4,
            "options": [],
            "reviewed": True,
        }
        main._merge_saved_question_analysis(question, reviewed)
        self.assertEqual(question["question_type"], "open")
        self.assertEqual(question["max_points"], 4)
        self.assertEqual(question["options"], [])
        self.assertTrue(question["reviewed"])

    def test_question_analysis_uses_visual_ocr_when_pdf_text_has_no_options(self):
        # De PDF-tekstlaag kan een meerkeuzevraag wel herkennen als tekst,
        # maar de antwoordopties missen doordat ze als afbeelding of in aparte
        # kolommen zijn opgeslagen. De zichtbare vraagafbeelding is dan de
        # aanvullende bron voor de opties.
        question = {
            "question_number": 7,
            "extracted_text": "Welke uitspraak over fotosynthese is juist?",
            "segments": [],
            "image_paths": ["vraag-7.png"],
        }
        visual_text = (
            "A De lichtreactie vindt plaats in de mitochondriën.\n"
            "B De donkerreactie vindt plaats in de stroma.\n"
            "C Bij fotosynthese ontstaat zuurstof uit koolstofdioxide."
        )
        with patch("examenverwerker.question_analysis._ocr_image_text", return_value=visual_text) as ocr:
            result = analyse_questions({"questions": [question]})

        ocr.assert_called_once_with(["vraag-7.png"])
        detected = result["questions"][0]
        self.assertEqual(detected["question_type"], "meerkeuze")
        self.assertEqual([option["letter"] for option in detected["options"]], ["A", "B", "C"])
        self.assertIn("vraagafbeelding", detected["type_reason"])

    def test_question_type_recognises_common_dutch_multiple_choice_formulations(self):
        # Niet ieder examen gebruikt letterlijk de instructie 'kies het juiste
        # antwoord'. Deze formuleringen zijn ook sterke aanwijzingen voor een
        # meerkeuzevraag wanneer de antwoordopties visueel nog gecontroleerd
        # moeten worden.
        examples = (
            "Welke uitspraak is onjuist?",
            "Welke combinatie is correct?",
            "Wat is de juiste volgorde van deze processen?",
            "Welke letter hoort bij de juiste afbeelding?",
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertEqual(detect_question_type(text, [])[0], "meerkeuze")

    def test_closed_answer_form_is_reported_explicitly(self):
        self.assertEqual(
            detect_closed_answer_form("Is de concentratie hoger, gelijk of lager?"),
            "hoger / gelijk / lager",
        )
        self.assertEqual(
            detect_closed_answer_form("Is de stof wel of niet aanwezig?"),
            "wel / niet",
        )
        self.assertEqual(
            detect_closed_answer_form("Is de uitspraak juist of onjuist?"),
            "juist / onjuist",
        )

    def test_cv_detector_recognises_multiple_choice_answer_split_over_three_lines(self):
        # In een CV kan de MC-regel door de tabelopmaak in drie regels worden
        # geëxtraheerd: eerst het vraagnnummer, dan de antwoordletter en dan
        # de score. De CV-vraagstart moet ondanks die splitsing behouden blijven.
        document = fitz.open()
        page = document.new_page()
        page.insert_text((60, 80), "Beoordelingsmodel", fontsize=12)
        page.insert_text((60, 130), "1", fontsize=11)
        page.insert_text((100, 130), "B", fontsize=11)
        page.insert_text((160, 130), "1", fontsize=11)
        page.insert_text((60, 190), "2", fontsize=11)
        page.insert_text((60, 215), "maximumscore 2", fontsize=10)
        path = self.root / "cv-split-mc.pdf"
        document.save(path)
        document.close()

        imported = self.client.post("/api/exams/import", files=[
            ("files", ("biologie-vwo-2026-tv2-c.pdf", path.read_bytes(), "application/pdf")),
        ])
        self.assertEqual(imported.status_code, 200, imported.text)
        exam_id = imported.json()["exam_id"]
        confirmed = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-c.pdf":"correctievoorschrift"},
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        result = self.client.get(
            f"/api/exams/{exam_id}/document-question-starts/correctievoorschrift"
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn(1, [item["question_number"] for item in result.json()["candidates"]])
        self.assertIn(2, [item["question_number"] for item in result.json()["candidates"]])

    def test_cv_detector_recognises_open_questions_with_score_in_separate_column(self):
        # Het CV kan de vraagkolom en de scorekolom als afzonderlijke
        # tekstblokken opslaan. De PDF-tekstvolgorde is dan niet betrouwbaar:
        # "maximumscore" kan vóór het vraagnummer worden uitgelezen.
        document = fitz.open()
        page = document.new_page()
        page.insert_text((60, 80), "Beoordelingsmodel", fontsize=12)

        # Open vraag 1: scorekolom bewust vóór de vraagnummerkolom invoegen.
        page.insert_text((350, 130), "maximumscore 3", fontsize=10)
        page.insert_text((60, 130), "1", fontsize=11)
        page.insert_text((90, 155), "Uit het antwoord moet blijken dat ...", fontsize=10)

        # Open vraag 2: zelfde tabelvorm, maar met een andere regelafstand.
        page.insert_text((350, 220), "maximumscore 2", fontsize=10)
        page.insert_text((60, 220), "2", fontsize=11)
        page.insert_text((90, 245), "De kandidaat noemt twee kenmerken.", fontsize=10)

        # Meerkeuzevraag 3 blijft eveneens herkenbaar wanneer letter en score
        # in losse tekstkolommen naast het vraagnummer staan.
        page.insert_text((60, 310), "3", fontsize=11)
        page.insert_text((350, 310), "B", fontsize=10)
        page.insert_text((405, 310), "1", fontsize=10)

        path = self.root / "cv-open-en-mc.pdf"
        document.save(path)
        document.close()

        imported = self.client.post("/api/exams/import", files=[
            ("files", ("biologie-vwo-2026-tv2-c.pdf", path.read_bytes(), "application/pdf")),
        ])
        self.assertEqual(imported.status_code, 200, imported.text)
        exam_id = imported.json()["exam_id"]
        confirmed = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-c.pdf":"correctievoorschrift"},
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        result = self.client.get(
            f"/api/exams/{exam_id}/document-question-starts/correctievoorschrift"
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(
            [item["question_number"] for item in result.json()["candidates"]],
            [1, 2, 3],
        )

    def test_cv_open_question_can_have_a_long_scoring_block(self):
        # Een open vraag kan veel beoordelingsregels bevatten voordat
        # maximumscore wordt vermeld. De vraagstart moet daarom niet worden
        # afgewezen omdat de score meer dan 48 PDF-punten lager staat.
        document = fitz.open()
        page = document.new_page()
        page.insert_text((60, 80), "Beoordelingsmodel", fontsize=12)

        # Vraag 1 begint in de vaste vraagnummerkolom. Een ingesprongen
        # los nummer in de antwoordcriteria is een subonderdeel en mag de
        # zoekruimte naar de maximumscore niet voortijdig afkappen.
        page.insert_text((60, 130), "1.", fontsize=11)
        page.insert_text((95, 160), "1", fontsize=10)
        page.insert_text((95, 185), "De kandidaat noemt het eerste criterium.", fontsize=10)
        page.insert_text((95, 210), "De kandidaat licht dit verder toe.", fontsize=10)
        page.insert_text((350, 255), "maximumscore 3", fontsize=10)

        # Een volgende hoofdvraag op dezelfde vraagnummerkolom vormt wel
        # de bovengrens van het beoordelingsblok van vraag 1.
        page.insert_text((60, 320), "2.", fontsize=11)
        page.insert_text((350, 345), "maximumscore 2", fontsize=10)

        path = self.root / "cv-long-open-question.pdf"
        document.save(path)
        document.close()

        imported = self.client.post("/api/exams/import", files=[
            ("files", ("biologie-vwo-2026-tv2-c.pdf", path.read_bytes(), "application/pdf")),
        ])
        self.assertEqual(imported.status_code, 200, imported.text)
        exam_id = imported.json()["exam_id"]
        confirmed = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-c.pdf":"correctievoorschrift"},
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        result = self.client.get(
            f"/api/exams/{exam_id}/document-question-starts/correctievoorschrift"
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(
            [item["question_number"] for item in result.json()["candidates"]],
            [1, 2],
        )

    def test_cv_end_section_ignores_table_of_contents_entry(self):
        # De inhoudsopgave kan de kop "5 Aanleveren scores" noemen. Die
        # vermelding mag het beoordelingsmodel niet afkappen: alleen de echte
        # zelfstandige kop bovenaan de administratieve slotpagina telt.
        document = fitz.open()
        contents_page = document.new_page()
        contents_page.insert_text((60, 80), "Inhoud", fontsize=12)
        contents_page.insert_text((60, 400), "5 Aanleveren scores", fontsize=10)

        model_page = document.new_page()
        model_page.insert_text((60, 80), "4 Beoordelingsmodel", fontsize=12)
        model_page.insert_text((60, 130), "1", fontsize=11)
        model_page.insert_text((60, 155), "maximumscore 2", fontsize=10)
        model_page.insert_text((90, 180), "De kandidaat noemt twee juiste kenmerken.", fontsize=10)

        final_page = document.new_page()
        final_page.insert_text((60, 80), "5 Aanleveren scores", fontsize=12)
        final_page.insert_text((60, 120), "Verwerk de scores in de applicatie Wolf.", fontsize=10)

        path = self.root / "cv-end-section-contents.pdf"
        document.save(path)
        document.close()

        imported = self.client.post("/api/exams/import", files=[
            ("files", ("biologie-vwo-2026-tv2-c.pdf", path.read_bytes(), "application/pdf")),
        ])
        self.assertEqual(imported.status_code, 200, imported.text)
        exam_id = imported.json()["exam_id"]
        confirmed = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-c.pdf":"correctievoorschrift"},
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        result = self.client.get(
            f"/api/exams/{exam_id}/document-question-starts/correctievoorschrift"
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(
            [(item["question_number"], item["page_index"])
             for item in result.json()["candidates"]],
            [(1, 1)],
        )

    def test_cv_heading_ignores_mentions_in_introductory_text(self):
        # Een juridische toelichting kan het woord "beoordelingsmodel"
        # noemen vóór de zelfstandige hoofdstukkop. Alleen die echte kop
        # mag bepalen waar de vraagstartdetectie begint.
        document = fitz.open()
        intro_page = document.new_page()
        intro_page.insert_text((60, 80), "Het beoordelingsmodel wordt hieronder toegelicht.")
        intro_page.insert_text((60, 120), "1")
        intro_page.insert_text((60, 145), "Regels voor de beoordeling")
        # Een inhoudsopgave kan de zelfstandige kop letterlijk herhalen,
        # maar staat niet bovenaan de pagina en mag de modelgrens niet bepalen.
        intro_page.insert_text((60, 400), "Beoordelingsmodel")

        model_page = document.new_page()
        model_page.insert_text((60, 80), "4 Beoordelingsmodel")
        model_page.insert_text((60, 130), "1")
        model_page.insert_text((60, 155), "maximumscore 2")
        path = self.root / "cv-heading.pdf"
        document.save(path)
        document.close()

        imported = self.client.post("/api/exams/import", files=[
            ("files", ("biologie-vwo-2026-tv2-c.pdf", path.read_bytes(), "application/pdf")),
        ])
        self.assertEqual(imported.status_code, 200, imported.text)
        exam_id = imported.json()["exam_id"]
        confirmed = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-c.pdf":"correctievoorschrift"},
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        result = self.client.get(
            f"/api/exams/{exam_id}/document-question-starts/correctievoorschrift"
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(
            [(item["question_number"], item["page_index"])
             for item in result.json()["candidates"]],
            [(1, 1)],
        )

    def test_detector_uses_only_standalone_main_question_lines(self):
        path = self.root / "sample.pdf"
        path.write_bytes(self.make_pdf())
        result = detect_question_starts(str(path))
        self.assertEqual(result["page_count"], 1)
        self.assertEqual([item["question_number"] for item in result["candidates"]], [1, 2])
        self.assertEqual(result["candidates"][0]["page_index"], 0)
        self.assertEqual(len(result["candidates"][0]["preview_bbox"]), 4)

    def test_detector_keeps_sequence_outliers_visible_instead_of_silently_dropping_them(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((60, 80), "11. Eerste vraag", fontsize=11)
        page.insert_text((60, 112), "6 kPa is de gemeten druk", fontsize=11)
        page.insert_text((60, 144), "1, 2 of 3 uitspraken zijn juist", fontsize=11)
        page.insert_text((60, 176), "12. Twaalfde vraag", fontsize=11)
        page.insert_text((60, 208), "1. Dit is geen nieuwe vraagreeks", fontsize=11)
        path = self.root / "false-numbers.pdf"
        path.write_bytes(doc.tobytes())
        doc.close()
        result = detect_question_starts(str(path))
        self.assertEqual([item["question_number"] for item in result["candidates"]], [11, 12, 1])
        self.assertTrue(result["candidates"][-1]["sequence_warning"])

    def test_page_alignment_is_calculated_independently_for_each_page(self):
        # Even en oneven pagina's kunnen door hun spiegelmarges een andere
        # linkerpositie voor de vraagnummerkolom hebben. Beide pagina's moeten
        # hun eigen uitlijning mogen gebruiken.
        doc = fitz.open()
        doc.new_page()
        doc.new_page()
        doc[0].insert_text((58, 80), "1. Eerste vraag", fontsize=11)
        doc[1].insert_text((104, 80), "2. Tweede vraag", fontsize=11)
        path = self.root / "alternating-margins.pdf"
        path.write_bytes(doc.tobytes())
        doc.close()

        result = detect_question_starts(str(path))
        self.assertEqual([(item["question_number"], item["page_index"])
                          for item in result["candidates"]], [(1, 0), (2, 1)])

    def test_page_result_exposes_pdf_words_for_reading_manual_number_box(self):
        path = self.root / "manual-number.pdf"
        path.write_bytes(self.make_pdf())
        result = detect_question_starts(str(path))
        words = result["pages"][0]["words"]
        self.assertTrue(any(word["text"] == "2." and len(word["bbox"]) == 4
                            for word in words))

    def test_review_validation_rejects_invalid_page_and_bbox(self):
        with self.assertRaises(ValueError):
            validate_review({"candidates":[{"id":"x","question_number":1,"page_index":2,"pdf_bbox":[1,1,2,2],"accepted":True}]}, 1)
        with self.assertRaises(ValueError):
            validate_review({"candidates":[{"id":"x","question_number":1,"page_index":0,"pdf_bbox":[2,2,1,1],"accepted":True}]}, 1)

    def test_api_returns_candidates_and_persists_review_as_pending(self):
        response = self.client.post("/api/exams/import", files=[("files", ("biologie-vwo-2026-tv2-o.pdf", self.make_pdf(), "application/pdf"))])
        self.assertEqual(response.status_code, 200, response.text)
        exam_id = response.json()["exam_id"]
        confirmed = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven"}
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        detected = self.client.get(f"/api/exams/{exam_id}/question-starts")
        self.assertEqual(detected.status_code, 200, detected.text)
        candidate = detected.json()["candidates"][0]
        saved = self.client.post(f"/api/exams/{exam_id}/question-starts/review", json={"candidates":[candidate]})
        self.assertEqual(saved.status_code, 200, saved.text)
        exam = self.client.get(f"/api/exams/{exam_id}").json()
        self.assertEqual(exam["steps"]["opgaven_starts"]["status"], "pending")
        self.assertEqual(exam["steps"]["opgaven_starts"]["evidence"]["accepted_count"], 1)

    def test_late_identical_question_start_autosave_preserves_completed_step(self):
        """Een late autosave mag een al goedgekeurde vraagstartreview niet heropenen."""
        response = self.client.post(
            "/api/exams/import",
            files=[("files", ("biologie-vwo-2026-tv2-o.pdf", self.make_pdf(), "application/pdf"))],
        )
        exam_id = response.json()["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven"}
        })
        detected = self.client.get(f"/api/exams/{exam_id}/document-question-starts/opgaven").json()
        candidates = detected["candidates"]
        saved = self.client.post(
            f"/api/exams/{exam_id}/document-question-starts/opgaven/review",
            json={"candidates":candidates},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        completed = self.client.post(
            f"/api/exams/{exam_id}/steps/opgaven_starts/complete",
            json={"reviewed":True, "reviewed_all_pages":True},
        )
        self.assertEqual(completed.status_code, 200, completed.text)

        # Simuleer de vertraagde identieke autosave die bij het verlaten van
        # het vraagstartscherm nog onderweg kan zijn.
        late_save = self.client.post(
            f"/api/exams/{exam_id}/document-question-starts/opgaven/review",
            json={"candidates":candidates},
        )
        self.assertEqual(late_save.status_code, 200, late_save.text)
        self.assertTrue(late_save.json()["complete"])
        exam = self.client.get(f"/api/exams/{exam_id}").json()
        self.assertEqual(exam["steps"]["opgaven_starts"]["status"], "complete")

    def test_review_validation_rejects_coordinates_outside_page(self):
        review = {"candidates":[{"id":"manual-1","question_number":1,"page_index":0,
                                  "pdf_bbox":[10,10,2000,20],"accepted":True,"source":"manual"}]}
        with self.assertRaisesRegex(ValueError, "buiten de paginagrenzen"):
            validate_review(review, 1, [(595.0, 842.0)])

    def test_manual_candidate_is_restored_after_reload(self):
        response = self.client.post("/api/exams/import", files=[("files", ("biologie-vwo-2026-tv2-o.pdf", self.make_pdf(), "application/pdf"))])
        exam_id = response.json()["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven"}
        })
        detected = self.client.get(f"/api/exams/{exam_id}/question-starts").json()
        manual = {"id":"manual-test-1", "question_number":3, "page_index":0,
                  "text":"Handmatig toegevoegde vraagstart", "pdf_bbox":[60,200,90,218],
                  "preview_bbox":[81,270,121.5,294.3], "accepted":True, "source":"manual"}
        candidates = detected["candidates"] + [manual]
        saved = self.client.post(f"/api/exams/{exam_id}/question-starts/review", json={"candidates":candidates})
        self.assertEqual(saved.status_code, 200, saved.text)
        reloaded = self.client.get(f"/api/exams/{exam_id}/question-starts")
        self.assertEqual(reloaded.status_code, 200, reloaded.text)
        self.assertIn("manual-test-1", [item["id"] for item in reloaded.json()["candidates"]])

    def test_manually_corrected_question_number_survives_reload(self):
        response = self.client.post("/api/exams/import", files=[("files", ("biologie-vwo-2026-tv2-o.pdf", self.make_pdf(), "application/pdf"))])
        exam_id = response.json()["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven"}
        })
        detected = self.client.get(f"/api/exams/{exam_id}/question-starts").json()
        # Simuleer een docent die een automatisch fout herkend nummer corrigeert.
        corrected = [dict(item) for item in detected["candidates"]]
        corrected[1]["question_number"] = 7
        saved = self.client.post(f"/api/exams/{exam_id}/question-starts/review", json={"candidates":corrected})
        self.assertEqual(saved.status_code, 200, saved.text)

        reloaded = self.client.get(f"/api/exams/{exam_id}/question-starts").json()
        restored = next(item for item in reloaded["candidates"] if item["id"] == corrected[1]["id"])
        self.assertEqual(restored["question_number"], 7)

    def test_removed_automatic_candidate_stays_removed_after_reload(self):
        response = self.client.post("/api/exams/import", files=[("files", ("biologie-vwo-2026-tv2-o.pdf", self.make_pdf(), "application/pdf"))])
        exam_id = response.json()["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven"}
        })
        detected = self.client.get(f"/api/exams/{exam_id}/question-starts").json()
        removed = dict(detected["candidates"][0], accepted=False, removed=True)
        candidates = [removed, *detected["candidates"][1:]]
        self.client.post(f"/api/exams/{exam_id}/question-starts/review", json={"candidates":candidates})
        reloaded = self.client.get(f"/api/exams/{exam_id}/question-starts").json()
        self.assertNotIn(removed["id"], [item["id"] for page in reloaded["pages"] for item in page["candidates"]])

    def test_fragment_generator_splits_question_across_pages(self):
        document = fitz.open()
        first = document.new_page()
        first.insert_text((60, 80), "Vraag 1 begint hier")
        second = document.new_page()
        second.insert_text((60, 130), "Vraag 1 loopt hier verder")
        second.insert_text((60, 300), "Vraag 2 begint hier")
        pdf_path = self.root / "two-pages.pdf"
        document.save(pdf_path)
        document.close()
        starts = [
            {"id":"q1", "question_number":1, "page_index":0, "pdf_bbox":[60,70,90,85]},
            {"id":"q2", "question_number":2, "page_index":1, "pdf_bbox":[60,290,90,305]},
        ]
        result = generate_question_fragments(pdf_path, starts, self.root / "derived")
        self.assertEqual(result["question_count"], 2)
        self.assertEqual([segment["page_number"] for segment in result["questions"][0]["segments"]], [1,2])
        self.assertTrue((self.root / "derived" / result["questions"][0]["segments"][0]["filename"]).is_file())
        self.assertLess(result["questions"][0]["segments"][1]["pdf_clip"][3], 842)

    def test_stitched_fragment_review_can_continue_into_question_analysis(self):
        # Dit is de volledige API-route die de browser in stap 3 en stap 4
        # doorloopt. De vraagafbeeldingen, tekstextractie en stapvalidatie
        # moeten dezelfde goedgekeurde fragmentgrenzen blijven gebruiken.
        document = fitz.open()
        cover = document.new_page()
        cover.insert_text((70, 100), "Biologie examen vwo 2026")
        questions = document.new_page()
        questions.insert_text((70, 100), "1. Beschrijf de functie van het celmembraan.", fontsize=11)
        questions.insert_text((70, 250), "2. Leg uit waarom transport energie kost.", fontsize=11)
        pdf_bytes = document.tobytes()
        document.close()

        imported = self.client.post(
            "/api/exams/import",
            files=[("files", ("biologie-vwo-2026-tv2-o.pdf", pdf_bytes, "application/pdf"))],
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        exam_id = imported.json()["exam_id"]
        confirmed = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven"},
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        starts = self.client.get(f"/api/exams/{exam_id}/question-starts")
        self.assertEqual(starts.status_code, 200, starts.text)
        candidates = starts.json()["candidates"]
        self.assertEqual([item["question_number"] for item in candidates], [1, 2])
        saved_starts = self.client.post(
            f"/api/exams/{exam_id}/question-starts/review",
            json={"candidates":candidates},
        )
        self.assertEqual(saved_starts.status_code, 200, saved_starts.text)
        completed_starts = self.client.post(
            f"/api/exams/{exam_id}/steps/opgaven_starts/complete",
            json={"reviewed":True, "reviewed_all_pages":True},
        )
        self.assertEqual(completed_starts.status_code, 200, completed_starts.text)

        stitched = self.client.get(f"/api/exams/{exam_id}/stitched-opgaven")
        self.assertEqual(stitched.status_code, 200, stitched.text)
        proposed = stitched.json()["proposed_selections"]
        question_selections = [item for item in proposed if item["type"] == "vraag"]
        self.assertEqual(len(question_selections), 2)
        self.assertTrue(stitched.json()["white_row_ranges"])

        reviewed_selections = [
            {**item, "question_numbers":list(item["question_numbers"])}
            for item in proposed
        ]
        saved_stitched = self.client.post(
            f"/api/exams/{exam_id}/stitched-opgaven/review",
            json={"selections":reviewed_selections, "reviewed":True},
        )
        self.assertEqual(saved_stitched.status_code, 200, saved_stitched.text)

        saved_fragment_review = self.client.post(
            f"/api/exams/{exam_id}/document-question-fragments/opgaven/review",
            json={"reviewed_question_numbers":[1, 2],
                  "reviewed_all_questions":True, "boundary_overrides":[]},
        )
        self.assertEqual(saved_fragment_review.status_code, 200, saved_fragment_review.text)
        completed_fragments = self.client.post(
            f"/api/exams/{exam_id}/steps/opgaven_fragments/complete",
            json={"reviewed":True, "reviewed_all_questions":True,
                  "reviewed_question_numbers":[1, 2]},
        )
        self.assertEqual(completed_fragments.status_code, 200, completed_fragments.text)

        # Een vertraagde pagehide/visibilitychange-autosave met exact dezelfde
        # selectie mag de zojuist afgeronde fragmentcontrole niet terugzetten.
        late_autosave = self.client.post(
            f"/api/exams/{exam_id}/stitched-opgaven/review",
            json={"selections":reviewed_selections, "reviewed":False},
        )
        self.assertEqual(late_autosave.status_code, 200, late_autosave.text)
        self.assertTrue(late_autosave.json()["complete"])
        current_exam = self.client.get(f"/api/exams/{exam_id}").json()
        self.assertEqual(current_exam["steps"]["opgaven_fragments"]["status"], "complete")

        analysis = self.client.get(f"/api/exams/{exam_id}/question-analysis")
        self.assertEqual(analysis.status_code, 200, analysis.text)
        questions_result = analysis.json()["questions"]
        self.assertEqual([item["question_number"] for item in questions_result], [1, 2])
        self.assertIn("celmembraan", questions_result[0]["extracted_text"].casefold())
        self.assertIn("energie kost", questions_result[1]["extracted_text"].casefold())
        self.assertTrue(all(item["segments"] for item in questions_result))

    def test_fragment_step_cannot_complete_without_full_review(self):
        response = self.client.post("/api/exams/import", files=[("files", ("biologie-vwo-2026-tv2-o.pdf", self.make_pdf(), "application/pdf"))])
        exam_id = response.json()["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven"}
        })
        detected = self.client.get(f"/api/exams/{exam_id}/question-starts").json()
        saved = self.client.post(f"/api/exams/{exam_id}/question-starts/review", json={"candidates":detected["candidates"]})
        self.client.post(f"/api/exams/{exam_id}/steps/opgaven_starts/complete", json={"reviewed":True, "reviewed_all_pages":True})
        fragments = self.client.get(f"/api/exams/{exam_id}/question-fragments")
        self.assertEqual(fragments.status_code, 200, fragments.text)
        first_image_url = fragments.json()["questions"][0]["segments"][0]["url"]
        image_response = self.client.get(first_image_url)
        self.assertEqual(image_response.status_code, 200, image_response.text)
        self.assertEqual(image_response.headers.get("content-type"), "image/png")
        bypass = self.client.post(f"/api/exams/{exam_id}/steps/opgaven_fragments/complete", json={"reviewed":True})
        self.assertEqual(bypass.status_code, 422)
        numbers = [question["question_number"] for question in fragments.json()["questions"]]
        review = self.client.post(f"/api/exams/{exam_id}/question-fragments/review", json={
            "reviewed_question_numbers":numbers, "reviewed_all_questions":True
        })
        self.assertEqual(review.status_code, 200, review.text)
        self.assertTrue(review.json()["complete"])
        complete = self.client.post(f"/api/exams/{exam_id}/steps/opgaven_fragments/complete", json={"reviewed":True})
        self.assertEqual(complete.status_code, 200, complete.text)
        analysis = self.client.get(f"/api/exams/{exam_id}/question-analysis")
        self.assertEqual(analysis.status_code, 200, analysis.text)
        questions = analysis.json()["questions"]
        self.assertTrue(questions)
        bypass_analysis = self.client.post(f"/api/exams/{exam_id}/steps/opgaven_analyse/complete", json={"reviewed":True})
        self.assertEqual(bypass_analysis.status_code, 422)
        for question in questions:
            question["reviewed"] = True
        saved_analysis = self.client.post(f"/api/exams/{exam_id}/question-analysis/review", json={"questions":questions})
        self.assertEqual(saved_analysis.status_code, 200, saved_analysis.text)
        self.assertTrue(saved_analysis.json()["complete"])
        completed_analysis = self.client.post(f"/api/exams/{exam_id}/steps/opgaven_analyse/complete", json={"reviewed":True})
        self.assertEqual(completed_analysis.status_code, 200, completed_analysis.text)

    def test_reopen_question_starts_preserves_draft_and_invalidates_fragments(self):
        response = self.client.post("/api/exams/import", files=[("files", ("biologie-vwo-2026-tv2-o.pdf", self.make_pdf(), "application/pdf"))])
        exam_id = response.json()["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven"}
        })
        detected = self.client.get(f"/api/exams/{exam_id}/question-starts").json()
        self.client.post(f"/api/exams/{exam_id}/question-starts/review", json={"candidates":detected["candidates"]})
        self.client.post(f"/api/exams/{exam_id}/steps/opgaven_starts/complete", json={"reviewed":True, "reviewed_all_pages":True})
        reopened = self.client.post(f"/api/exams/{exam_id}/steps/opgaven_starts/reopen")
        self.assertEqual(reopened.status_code, 200, reopened.text)
        exam = self.client.get(f"/api/exams/{exam_id}").json()
        self.assertEqual(exam["steps"]["opgaven_starts"]["status"], "pending")
        self.assertTrue(exam["steps"]["opgaven_starts"]["evidence"]["candidates"])

    def test_question_analysis_detects_options_closed_forms_and_explicit_points(self):
        text = "Kies het juiste antwoord.\nA. eerste antwoord\nB. tweede antwoord\nC. derde antwoord\nMaximumscore 2 punten"
        options = detect_options(text)
        self.assertEqual([item["letter"] for item in options], ["A", "B", "C"])
        self.assertEqual(detect_question_type(text, options)[0], "meerkeuze")
        self.assertEqual(detect_max_points(text)[0], 2)
        closed_type, _ = detect_question_type("Is de uitspraak juist/onjuist?", [])
        self.assertEqual(closed_type, "gesloten")
        mc_without_options, _ = detect_question_type("Kies het juiste antwoord bij de afbeelding.", [])
        self.assertEqual(mc_without_options, "meerkeuze")

    def test_question_analysis_validation_requires_every_question_reviewed(self):
        payload = {"questions":[
            {"question_number":1,"question_type":"meerkeuze","max_points":2,
             "options":[{"letter":"A","text":"optie"}],"reviewed":True},
            {"question_number":2,"question_type":"open","max_points":None,"options":[],"reviewed":False},
        ]}
        result = validate_question_analysis(payload, {1,2})
        self.assertFalse(result["reviewed_all_questions"])
        payload["questions"][1]["reviewed"] = True
        self.assertTrue(validate_question_analysis(payload, {1,2})["reviewed_all_questions"])
        with self.assertRaisesRegex(ValueError, "dubbel genummerde"):
            validate_question_analysis({"questions":[{"question_number":1,"question_type":"meerkeuze",                "max_points":2,"options":[{"letter":"A","text":"x"},{"letter":"A","text":"y"}],"reviewed":True}]}, {1})

    def test_question_start_review_is_reused_for_answer_sheet_and_marking_scheme(self):
        sample = self.make_pdf()
        response = self.client.post("/api/exams/import", files=[
            ("files", ("biologie-vwo-2026-tv2-o.pdf", sample, "application/pdf")),
            ("files", ("biologie-vwo-2026-tv2-u.pdf", sample, "application/pdf")),
            ("files", ("biologie-vwo-2026-tv2-c.pdf", sample, "application/pdf")),
        ])
        self.assertEqual(response.status_code, 200, response.text)
        exam_id = response.json()["exam_id"]
        confirmed = self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{
                "biologie-vwo-2026-tv2-o.pdf":"opgaven",
                "biologie-vwo-2026-tv2-u.pdf":"uitwerkbijlage",
                "biologie-vwo-2026-tv2-c.pdf":"correctievoorschrift",
            }
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        for document_type, step_key in [("uitwerkbijlage", "uitwerk_starts"), ("correctievoorschrift", "cv_starts")]:
            detected = self.client.get(f"/api/exams/{exam_id}/document-question-starts/{document_type}")
            self.assertEqual(detected.status_code, 200, detected.text)
            candidates = detected.json()["candidates"]
            saved = self.client.post(f"/api/exams/{exam_id}/document-question-starts/{document_type}/review", json={"candidates":candidates})
            self.assertEqual(saved.status_code, 200, saved.text)
            completed = self.client.post(f"/api/exams/{exam_id}/steps/{step_key}/complete", json={"reviewed":True, "reviewed_all_pages":True})
            self.assertEqual(completed.status_code, 200, completed.text)
            fragments = self.client.get(f"/api/exams/{exam_id}/document-question-fragments/{document_type}")
            self.assertEqual(fragments.status_code, 200, fragments.text)
            self.assertEqual(fragments.json()["document_type"], document_type)
            first_fragment_url = fragments.json()["questions"][0]["segments"][0]["url"]
            fragment_image = self.client.get(first_fragment_url)
            self.assertEqual(fragment_image.status_code, 200, fragment_image.text)
            self.assertEqual(fragment_image.headers.get("content-type"), "image/png")
            reviewed_numbers = [question["question_number"] for question in fragments.json()["questions"]]
            saved_fragments = self.client.post(f"/api/exams/{exam_id}/document-question-fragments/{document_type}/review", json={
                "reviewed_question_numbers":reviewed_numbers, "reviewed_all_questions":True
            })
            self.assertEqual(saved_fragments.status_code, 200, saved_fragments.text)
            fragment_step = "uitwerk_fragments" if document_type == "uitwerkbijlage" else "cv_fragments"
            completed_fragments = self.client.post(f"/api/exams/{exam_id}/steps/{fragment_step}/complete", json={"reviewed":True})
            self.assertEqual(completed_fragments.status_code, 200, completed_fragments.text)

    def test_stitched_exam_skips_cover_and_returns_page_coordinate_map(self):
        # De lange werkafbeelding begint op pagina 2; pagina 1 is de omslag.
        # Beide inhoudspagina's moeten in documentvolgorde terug te vinden zijn.
        doc = fitz.open()
        for label in ("OMSLAG", "INHOUD PAGINA TWEE", "INHOUD PAGINA DRIE"):
            page = doc.new_page()
            page.insert_text((70, 100), label, fontsize=14)
        source = self.root / "stitched-source.pdf"
        target = self.root / "exam-long.png"
        source.write_bytes(doc.tobytes())
        doc.close()
        metadata = build_stitched_exam(source, target, render_scale=0.8)
        self.assertTrue(target.is_file())
        self.assertEqual([page["page_number"] for page in metadata["pages"]], [2, 3])
        self.assertEqual(metadata["height"], metadata["pages"][0]["stitched_height"] +
                         metadata["pages"][1]["stitched_height"] + metadata["page_gap"])
        self.assertLess(metadata["pages"][0]["top"], metadata["pages"][1]["top"])

    def test_cv_fragments_remove_repeated_marginal_lines_and_stitch_pages(self):
        document = fitz.open()
        first = document.new_page()
        first.insert_text((60, 30), "Correctievoorschrift biologie", fontsize=8)
        first.insert_text((60, 90), "1")
        first.insert_text((60, 130), "Een antwoord wordt goed gerekend wanneer...")
        first.insert_text((60, 810), "1", fontsize=8)
        second = document.new_page()
        second.insert_text((60, 30), "Correctievoorschrift biologie", fontsize=8)
        second.insert_text((60, 100), "Vervolg van vraag 1")
        second.insert_text((60, 300), "2")
        second.insert_text((60, 810), "2", fontsize=8)
        pdf_path = self.root / "cv.pdf"
        document.save(pdf_path)
        document.close()
        starts = [
            {"id":"cv-q1", "question_number":1, "page_index":0, "pdf_bbox":[60,80,80,95]},
            {"id":"cv-q2", "question_number":2, "page_index":1, "pdf_bbox":[60,290,80,305]},
        ]
        result = generate_question_fragments(pdf_path, starts, self.root / "cv-derived", document_type="correctievoorschrift")
        question_one = result["questions"][0]
        self.assertTrue(question_one["stitched"])
        self.assertEqual(len(question_one["source_segments"]), 2)
        self.assertEqual(len(question_one["segments"]), 1)
        stitched_path = self.root / "cv-derived" / question_one["segments"][0]["filename"]
        self.assertTrue(stitched_path.is_file())
        from PIL import Image
        source_sizes = []
        for segment in question_one["source_segments"]:
            with Image.open(self.root / "cv-derived" / segment["filename"]) as source_image:
                source_sizes.append(source_image.size)
        with Image.open(stitched_path) as stitched:
            self.assertEqual(stitched.width, max(size[0] for size in source_sizes))
            self.assertEqual(stitched.height, sum(size[1] for size in source_sizes) + 24)



    def test_detector_recognises_score_prefix_before_question_number(self):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((60, 100), "1p 1 Geef een combinatie van ouders en nakomeling.", fontsize=11)
        page.insert_text((60, 180), "2p 2 Uit het fenotype blijkt dat het gen.", fontsize=11)
        path = self.root / "score-prefix.pdf"
        document.save(path)
        document.close()
        result = detect_question_starts(str(path))
        self.assertEqual([item["question_number"] for item in result["candidates"]], [1, 2])

    def test_fragment_generator_applies_manual_boundary_overrides(self):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((60, 120), "Question content starts here")
        page.insert_text((60, 220), "Question content ends here")
        pdf_path = self.root / "boundaries.pdf"
        document.save(pdf_path)
        document.close()
        starts = [{"id":"q1", "question_number":1, "page_index":0, "pdf_bbox":[60,110,90,125]}]
        result = generate_question_fragments(pdf_path, starts, self.root / "boundary-derived",
                                             boundary_overrides={1:{"start_y":150,"end_y":260}})
        clip = result["questions"][0]["segments"][0]["pdf_clip"]
        self.assertEqual(clip[1], 150)
        self.assertEqual(clip[3], 260)

    def test_cv_fragment_generator_uses_real_slot_section_not_contents_reference(self):
        # Stap 7 en stap 8 moeten dezelfde grens hanteren. Een vermelding van
        # "5 Aanleveren scores" in de inhoudsopgave mag een laatste examenvraag
        # op een latere pagina van het beoordelingsmodel niet uitsluiten.
        document = fitz.open()
        contents_page = document.new_page()
        contents_page.insert_text((60, 80), "Inhoud", fontsize=12)
        contents_page.insert_text((60, 400), "5 Aanleveren scores", fontsize=10)

        model_page = document.new_page()
        model_page.insert_text((60, 80), "4 Beoordelingsmodel", fontsize=12)
        model_page.insert_text((60, 130), "39", fontsize=11)
        model_page.insert_text((60, 155), "maximumscore 2", fontsize=10)
        model_page.insert_text((90, 180), "De kandidaat noemt twee juiste kenmerken.", fontsize=10)

        final_page = document.new_page()
        final_page.insert_text((60, 80), "5 Aanleveren scores", fontsize=12)
        final_page.insert_text((60, 120), "Verwerk de scores in de applicatie Wolf.", fontsize=10)

        pdf_path = self.root / "cv-fragment-end-section-contents.pdf"
        document.save(pdf_path)
        document.close()

        result = generate_question_fragments(
            pdf_path,
            [{"id":"cv-q39", "question_number":39, "page_index":1,
              "pdf_bbox":[60,120,80,135]}],
            self.root / "cv-fragment-end-section",
            document_type="correctievoorschrift",
        )

        self.assertEqual(result["question_count"], 1)
        self.assertEqual(result["questions"][0]["first_page"], 2)
        self.assertEqual(result["questions"][0]["last_page"], 2)
        self.assertIn("maximumscore 2", result["questions"][0]["extracted_text"])

    def test_last_cv_question_stops_before_administrative_pages(self):
        document = fitz.open()
        first = document.new_page()
        first.insert_text((60, 100), "1")
        first.insert_text((60, 140), "Answer criteria for the final question")
        second = document.new_page()
        second.insert_text((60, 100), "Continuation of the answer criteria")
        third = document.new_page()
        third.insert_text((60, 100), "5 Aanleveren scores")
        pdf_path = self.root / "cv-ending.pdf"
        document.save(pdf_path)
        document.close()
        result = generate_question_fragments(pdf_path,
            [{"id":"q1", "question_number":1, "page_index":0, "pdf_bbox":[60,90,80,105]}],
            self.root / "cv-derived", document_type="correctievoorschrift")
        self.assertEqual(result["questions"][0]["last_page"], 2)

    def test_duplicate_accepted_question_numbers_block_start_completion(self):
        response = self.client.post("/api/exams/import", files=[("files", ("biologie-vwo-2026-tv2-o.pdf", self.make_pdf(), "application/pdf"))])
        exam_id = response.json()["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven"}
        })
        result = self.client.get(f"/api/exams/{exam_id}/question-starts").json()
        first = result["candidates"][0]
        duplicate = dict(first, id="duplicate-question-one")
        self.client.post(f"/api/exams/{exam_id}/question-starts/review", json={"candidates":[first, duplicate]})
        completed = self.client.post(f"/api/exams/{exam_id}/steps/opgaven_starts/complete", json={"reviewed":True,"reviewed_all_pages":True})
        self.assertEqual(completed.status_code, 422)
        self.assertIn("dubbele hoofdvraagstarts", completed.text)

    def test_fragment_boundary_override_is_saved_and_used_by_api(self):
        response = self.client.post("/api/exams/import", files=[("files", ("biologie-vwo-2026-tv2-o.pdf", self.make_pdf(), "application/pdf"))])
        exam_id = response.json()["exam_id"]
        self.client.post(f"/api/exams/{exam_id}/metadata/confirm", json={
            "subject":"biologie", "level":"vwo", "year":2026, "period":2,
            "document_types":{"biologie-vwo-2026-tv2-o.pdf":"opgaven"}
        })
        starts = self.client.get(f"/api/exams/{exam_id}/question-starts").json()
        self.client.post(f"/api/exams/{exam_id}/question-starts/review", json={"candidates":starts["candidates"]})
        self.client.post(f"/api/exams/{exam_id}/steps/opgaven_starts/complete", json={"reviewed":True,"reviewed_all_pages":True})
        fragments = self.client.get(f"/api/exams/{exam_id}/document-question-fragments/opgaven").json()
        question = fragments["questions"][0]
        saved = self.client.post(f"/api/exams/{exam_id}/document-question-fragments/opgaven/review", json={
            "reviewed_question_numbers":[question["question_number"]],"reviewed_all_questions":True,
            "boundary_overrides":[{"question_number":question["question_number"],"start_y":150,"end_y":300}]
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        regenerated = self.client.get(f"/api/exams/{exam_id}/document-question-fragments/opgaven").json()
        self.assertEqual(regenerated["questions"][0]["segments"][0]["pdf_clip"][1], 150)
        self.assertEqual(regenerated["questions"][0]["segments"][0]["pdf_clip"][3], 300)


    def test_fragment_boundaries_require_pure_white_rgb_rows(self):
        # Een bijna-witte pixel is nog steeds inhoud. Alleen de rijen die
        # volledig uit RGB(255, 255, 255) bestaan, mogen als grens dienen.
        image_path = self.root / "white-rows.png"
        image = Image.new("RGB", (4, 4), (255, 255, 255))
        image.putpixel((2, 1), (254, 255, 255))
        image.save(image_path)
        image.close()

        ranges = main._white_row_ranges(image_path)
        self.assertEqual(ranges, [[0, 0], [2, 3]])
        self.assertTrue(main._is_white_boundary(0, ranges))
        # Een decimale coördinaat mag niet door afronden alsnog op rij 0
        # worden goedgekeurd; de opgeslagen grens moet exact een pixelrij zijn.
        self.assertFalse(main._is_white_boundary(0.4, ranges))

    def test_stitched_normalisation_does_not_cut_a_question_at_an_early_blank_row(self):
        # De detector kan een interne witregel in een vraag ten onrechte als
        # ondergrens voorstellen. De normalisatie moet de vraag dan laten
        # doorlopen tot de witte rij vóór de volgende goedgekeurde vraagstart.
        image_path = self.root / "question-boundaries.png"
        image = Image.new("RGB", (20, 200), (255, 255, 255))
        for y in range(30, 66):
            for x in range(3, 17):
                image.putpixel((x, y), (0, 0, 0))
        # Dit zichtbare tekstblok ligt ná vraag 1 en vóór vraag 2.
        # Het is context bij de voorafgaande vraag en mag niet in vraag 2
        # worden opgenomen.
        for y in range(76, 94):
            for x in range(3, 17):
                image.putpixel((x, y), (30, 30, 30))
        for y in range(112, 141):
            for x in range(3, 17):
                image.putpixel((x, y), (0, 0, 0))
        # Vraag 3 volgt op vraag 2 zonder een nieuw contextblok. Het context-
        # fragment tussen vraag 1 en 2 moet daarom bij beide vervolgvragen horen.
        for y in range(160, 181):
            for x in range(3, 17):
                image.putpixel((x, y), (0, 0, 0))
        image.save(image_path)
        image.close()

        white_rows = main._white_row_ranges(image_path)
        selections = [
            {"id":"q1", "type":"vraag", "top":28, "bottom":70,
             "question_numbers":[1], "label":"Vraag 1"},
            {"id":"q2", "type":"vraag", "top":112, "bottom":150,
             "question_numbers":[2], "label":"Vraag 2"},
            {"id":"q3", "type":"vraag", "top":160, "bottom":190,
             "question_numbers":[3], "label":"Vraag 3"},
        ]
        normalised = normalise_stitched_selections(
            selections, white_rows, image_path, image_height=200
        )
        questions = [item for item in normalised if item["type"] == "vraag"]

        self.assertEqual(len(questions), 3)
        # De ondergrens van vraag 1 ligt op de bovenste witte rij direct
        # onder de laatste inhoudsregel; de bovengrens van vraag 2 ligt op
        # de onderste witte rij direct boven de eerste inhoudsregel.
        self.assertEqual(questions[0]["bottom"], 66)
        self.assertEqual(questions[1]["top"], 111)
        self.assertEqual(questions[1]["bottom"], 141)
        self.assertEqual(questions[2]["top"], 159)
        self.assertEqual(questions[2]["bottom"], 181)
        self.assertLess(questions[0]["bottom"], questions[1]["top"])
        contexts = [item for item in normalised if item["type"] == "context"]
        self.assertEqual(len(contexts), 1)
        # De context staat vóór vraag 2 en 3 en wordt aan beide gekoppeld,
        # maar blijft een afzonderlijk fragment buiten de vraagafbeeldingen.
        self.assertEqual(contexts[0]["question_numbers"], [2, 3])
        self.assertEqual(contexts[0]["top"], questions[0]["bottom"])
        self.assertEqual(contexts[0]["bottom"], questions[1]["top"])

    def test_stitched_normalisation_keeps_non_context_gap_inside_previous_question(self):
        # Niet iedere zichtbare ruimte tussen vragen is een context. Zonder
        # inhoudelijke contextkandidaat moet de tekst behouden blijven bij de
        # voorafgaande vraag en mag geen contextfragment ontstaan.
        image_path = self.root / "question-gap.png"
        image = Image.new("RGB", (20, 120), (255, 255, 255))
        for y in range(10, 25):
            for x in range(2, 18):
                image.putpixel((x, y), (0, 0, 0))
        for y in range(45, 62):
            for x in range(2, 18):
                image.putpixel((x, y), (20, 20, 20))
        for y in range(82, 100):
            for x in range(2, 18):
                image.putpixel((x, y), (0, 0, 0))
        image.save(image_path)
        image.close()
        white_rows = main._white_row_ranges(image_path)
        selections = [
            {"id":"q1", "type":"vraag", "top":8, "bottom":28,
             "question_numbers":[1], "label":"Vraag 1"},
            {"id":"q2", "type":"vraag", "top":80, "bottom":102,
             "question_numbers":[2], "label":"Vraag 2"},
        ]
        normalised = normalise_stitched_selections(
            selections, white_rows, image_path, image_height=120,
            context_candidates_only=True,
        )
        self.assertFalse(any(item["type"] == "context" for item in normalised))
        questions = [item for item in normalised if item["type"] == "vraag"]
        self.assertEqual(questions[0]["bottom"], questions[1]["top"])

    def test_selected_stitched_text_is_read_from_the_matching_source_page(self):
        # Pagina 1 is de omslag en wordt niet in het stitchwerkvlak opgenomen.
        # De tekstextractie moet de geselecteerde pixelstrook terugrekenen naar
        # de juiste bronpagina, zonder tekst van een andere pagina toe te voegen.
        document = fitz.open()
        cover = document.new_page()
        cover.insert_text((60, 100), "OMSLAGTEKST")
        content = document.new_page()
        content.insert_text((60, 100), "Vraag 1 unieke geselecteerde tekst")
        content.insert_text((60, 300), "Vraag 2 staat lager op dezelfde pagina")
        later = document.new_page()
        later.insert_text((60, 100), "Tekst van een latere pagina")
        pdf_path = self.root / "selected-text.pdf"
        document.save(pdf_path)
        document.close()

        metadata = build_stitched_exam(pdf_path, self.root / "selected-text.png")
        first_content_page = metadata["pages"][0]
        extracted = main._extract_stitched_selection_text(
            pdf_path,
            metadata["pages"],
            first_content_page["top"],
            first_content_page["bottom"],
        )

        self.assertIn("Vraag 1 unieke geselecteerde tekst", extracted)
        self.assertIn("Vraag 2 staat lager op dezelfde pagina", extracted)
        self.assertNotIn("OMSLAGTEKST", extracted)
        self.assertNotIn("Tekst van een latere pagina", extracted)


if __name__ == "__main__":
    unittest.main()


class ImageBasedAnswerOptionTests(unittest.TestCase):
    """Regressietests voor antwoordopties die volledig uit beeld bestaan."""

    IMAGE = "data:image/jpeg;base64,/9j/2Q=="

    def _payload(self, options, *, reviewed=True, question_type="meerkeuze"):
        return {"questions": [{
            "question_number": 12,
            "question_type": question_type,
            "max_points": 1,
            "options": options,
            "reviewed": reviewed,
        }]}

    def test_image_only_and_mixed_options_are_accepted_and_normalised(self):
        # Een respirogram of grafiek kan de volledige inhoud van een optie
        # vormen. Een combinatie van tekst en beeld moet eveneens bewaard
        # blijven, zonder dat er kunstmatig OCR-tekst wordt geëist.
        payload = self._payload([
            {"letter": "A", "text": "", "image_data": self.IMAGE},
            {"letter": "B", "text": "De grafiek toont een stijging.", "image_data": self.IMAGE},
        ])
        result = validate_question_analysis(payload, {12})
        options = result["questions"][0]["options"]
        self.assertEqual(options[0]["option_type"], "afbeelding")
        self.assertEqual(options[0]["text"], "")
        self.assertEqual(options[0]["image_data"], self.IMAGE)
        self.assertEqual(options[1]["option_type"], "combinatie")

    def test_reviewed_multiple_choice_requires_at_least_two_complete_options(self):
        # Een vraag mag pas worden goedgekeurd als alle antwoordmogelijkheden
        # daadwerkelijk zijn vastgelegd; lege regels zijn geen antwoordopties.
        with self.assertRaisesRegex(ValueError, "minder dan twee"):
            validate_question_analysis(self._payload([
                {"letter": "A", "text": "", "image_data": self.IMAGE},
            ]), {12})
        with self.assertRaisesRegex(ValueError, "bevat geen tekst of afbeelding"):
            validate_question_analysis(self._payload([
                {"letter": "A", "text": ""},
                {"letter": "B", "text": "Antwoord B"},
            ]), {12})

    def test_image_option_data_is_strictly_validated(self):
        # Alleen een lokale JPEG-data-URL is toegestaan. Onverwachte URL's,
        # bestandspaden en extreem grote payloads worden geweigerd.
        with self.assertRaisesRegex(ValueError, "ongeldig of te groot"):
            validate_question_analysis(self._payload([
                {"letter": "A", "text": "", "image_data": "https://example.com/image.png"},
                {"letter": "B", "text": "Antwoord B"},
            ]), {12})
        with self.assertRaisesRegex(ValueError, "ongeldig of te groot"):
            validate_question_analysis(self._payload([
                {"letter": "A", "text": "", "image_data": "data:image/jpeg;base64," + ("A" * 2_000_001)},
                {"letter": "B", "text": "Antwoord B"},
            ]), {12})

    def test_image_only_options_survive_reopening_analysis(self):
        # Het opnieuw openen van stap 4 mag een afbeelding zonder begeleidende
        # tekst niet wegfilteren uit de eerder opgeslagen docentcorrectie.
        question = {"question_number": 12, "question_type": "meerkeuze",
                    "max_points": 1, "options": [], "reviewed": False}
        saved = {"question_type": "meerkeuze", "max_points": 1,
                 "options": [
                     {"letter": "A", "text": "", "image_data": self.IMAGE},
                     {"letter": "B", "text": "Tekstoptie"},
                 ], "reviewed": False}
        main._merge_saved_question_analysis(question, saved)
        self.assertEqual([item["letter"] for item in question["options"]], ["A", "B"])
        self.assertEqual(question["options"][0]["image_data"], self.IMAGE)

    def test_step_four_contains_real_image_crop_and_explicit_review_controls(self):
        # Controleer dat de UI daadwerkelijk een selectiekader over de
        # PDF-afbeelding gebruikt en de crop als antwoordoptie kan opslaan.
        static_dir = Path(main.__file__).resolve().parents[1] / "static"
        app_js = (static_dir / "app.js").read_text(encoding="utf-8")
        app_css = (static_dir / "app.css").read_text(encoding="utf-8")
        self.assertIn("Afbeeldingsoptie uit deze pagina selecteren", app_js)
        self.assertIn("drawImage(img", app_js)
        self.assertIn("data-option-revision", app_js)
        self.assertIn("analysis-crop-selection", app_css)
        self.assertIn("analysis-option-preview", app_css)
        # Contextgroepkaarten in de rechter inspector moeten compact blijven.
        self.assertIn(".stitched-inspector .context-group-card", app_css)
        self.assertIn("padding: 7px 9px !important;", app_css)
