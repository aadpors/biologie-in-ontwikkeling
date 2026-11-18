import tempfile, unittest
from pathlib import Path
from engine import detect_question_candidates, detect_cv_question_numbers, compare_question_numbering, propose_question_regions, classify_document_role, infer_exam_metadata, build_question_record, question_pattern_key, learn_decision, suggest_from_learning, validate_website_records, analyze_pdf, render_crop

class EngineTests(unittest.TestCase):
    def test_official_exam_filename_roles_and_metadata(self):
        self.assertEqual(classify_document_role("ha-1018-a-24-1-o-spr.pdf","")[0],"opgaven")
        self.assertEqual(classify_document_role("ha-1018-a-26-1-c.pdf","")[0],"correctievoorschrift")
        self.assertEqual(classify_document_role("ha-1018-a-26-1-c-a1_0.pdf","")[0],"aanvulling")
        self.assertEqual(classify_document_role("ha-1018-a-25-1-u.pdf","")[0],"uitwerkbijlage")
        self.assertEqual(infer_exam_metadata("ha-1018-a-24-1-o-spr.pdf")["level"],"Havo")
        self.assertEqual(infer_exam_metadata("vw-1018-a-26-2-o.pdf")["year"],"2026")
    def test_question_candidates_keep_repeated_numbers(self):
        a={"pages":[{"page":1,"blocks":[{"bbox":[1,2,3,4],"lines":[{"bbox":[1,2,20,14],"text":"1."},{"bbox":[1,15,100,27],"text":"Beschrijf de functie van dit orgaan."}],"text":"1.\\nBeschrijf de functie van dit orgaan."}]},
                    {"page":2,"blocks":[{"bbox":[1,2,3,4],"lines":[{"bbox":[1,2,140,14],"text":"1. Welke stof wordt gevormd?"}],"text":"1. Welke stof wordt gevormd?"}]}]}
        got=detect_question_candidates(a)
        self.assertEqual([x["number"] for x in got],[1,1])
        self.assertTrue(all(x["status"]=="controle_nodig" for x in got))
    def test_question_candidates_recognise_welk_prompt(self):
        a={"pages":[{"page":1,"blocks":[{"bbox":[0,0,300,100],"lines":[
            {"bbox":[10,10,20,20],"text":"8."},
            {"bbox":[30,10,250,20],"text":"Welk orgaan produceert dit hormoon?"}
        ],"text":"8.\\nWelk orgaan produceert dit hormoon?"}]}]}
        got=detect_question_candidates(a)
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]["number"],8)

    def test_question_candidates_reject_numbered_source_lines_and_keep_score_markers(self):
        a={"pages":[{"page":1,"blocks":[{"bbox":[0,0,300,300],"lines":[
            {"bbox":[10,10,20,20],"text":"1"},
            {"bbox":[10,25,20,35],"text":"2"},
            {"bbox":[10,40,20,50],"text":"3"},
            {"bbox":[10,55,200,65],"text":"Een doorlopende tekstregel."},
            {"bbox":[10,100,20,110],"text":"4"},
            {"bbox":[30,100,50,110],"text":"1p"},
            {"bbox":[30,120,200,130],"text":"De vraagtekst volgt hier."}
        ],"text":"1\\n2\\n3\\nEen doorlopende tekstregel.\\n4\\n1p\\nDe vraagtekst volgt hier."}]}]}
        got=detect_question_candidates(a)
        self.assertEqual([x["number"] for x in got],[4])
        self.assertEqual(got[0]["confidence"],0.95)

    def test_question_number_at_bottom_can_continue_on_next_page(self):
        a={"pages":[
            {"page":1,"height":800,"blocks":[{"bbox":[20,760,40,780],"lines":[{"bbox":[20,760,40,780],"text":"7."}],"text":"7."}]},
            {"page":2,"height":800,"blocks":[{"bbox":[20,40,240,60],"lines":[{"bbox":[20,40,240,60],"text":"Beschrijf de oorzaak."}],"text":"Beschrijf de oorzaak."}]}
        ]}
        got=detect_question_candidates(a)
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]["number"],7)
        self.assertEqual(got[0]["page"],1)
        self.assertEqual(got[0]["next_line"],"Beschrijf de oorzaak.")
    def test_question_pattern_key_distinguishes_layouts(self):
        self.assertEqual(question_pattern_key({"line":"4. Beschrijf dit.","next_line":""}),"question_start:numbered_line_with_text")
        self.assertEqual(question_pattern_key({"line":"4.","next_line":"Beschrijf dit."}),"question_start:standalone_number_then_text")
    def test_learning_requires_repeated_support_and_never_autoplays(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            learn_decision(p,{"pattern_key":"layout-a","chosen":"question","accepted":True})
            self.assertIsNone(suggest_from_learning(p,"layout-a")["suggestion"])
            learn_decision(p,{"pattern_key":"layout-a","chosen":"question","accepted":True})
            s=suggest_from_learning(p,"layout-a")
            self.assertEqual(s["suggestion"],"question")
            self.assertFalse(s["auto_apply"])
            learn_decision(p,{"pattern_key":"layout-a","chosen":"not_question","accepted":True})
            tie=suggest_from_learning(p,"layout-a")
            self.assertIsNone(tie["suggestion"])
            self.assertTrue(tie["conflicting"])
    def test_duplicate_ids_reported(self):
        row={"id":"same","level":"Havo","year":"2025","period":"1","n":1,"page":1,"q":"x","pdf":"a.pdf","cv":"b.pdf"}
        errors=validate_website_records([row],[row],[])
        self.assertTrue(any(e["kind"]=="duplicate_id" for e in errors))
    def test_cv_numbering_crosscheck_reports_differences(self):
        op=[{"number":1},{"number":2},{"number":3}]
        cv=[{"number":1},{"number":3},{"number":4}]
        result=compare_question_numbering(op,cv)
        self.assertEqual(result["ontbreekt_in_cv"],[2])
        self.assertEqual(result["ontbreekt_in_opgaven"],[4])
    def test_question_regions_can_span_pages(self):
        analysis={"pages":[{"page":1,"width":600,"height":800},{"page":2,"width":600,"height":800}]}
        candidates=[{"number":1,"page":1,"bbox":[50,700,80,720]},{"number":2,"page":2,"bbox":[50,100,80,120]}]
        regions=propose_question_regions(analysis,candidates)
        self.assertEqual(len(regions[0]["source_segments"]),2)
        self.assertEqual(regions[0]["status"],"voorstel_niet_goedgekeurd")
    def test_review_record_is_never_preapproved_and_uses_site_id(self):
        meta={"level":"Havo","year":"2026","period":"1","questionType":"open"}
        candidate={"number":7,"page":3,"bbox":[30,100,60,120],"confidence":0.7}
        record=build_question_record(meta,candidate,"Beschrijf dit.","opgaven.pdf","cv.pdf")
        self.assertEqual(record["id"],"ha26t1-open-7")
        self.assertFalse(record["approved_by_human"])
        self.assertEqual(record["status"],"controle_nodig")
    def test_cv_anchor_detection(self):
        a={"pages":[{"page":1,"text":"Vraag 1\\nBeoordelingsmodel\\nVraag 3"}]}
        got=detect_cv_question_numbers(a)
        self.assertEqual([x["number"] for x in got],[1,3])

    def test_question_type_detection_and_option_integrity(self):
        from engine import detect_question_type
        result=detect_question_type("Kies het juiste antwoord.\nA. mitochondriën\nB. ribosomen\nC. celkern\nD. celmembraan")
        self.assertEqual(result["type"],"meerkeuze")
        self.assertEqual(result["option_labels"],["A","B","C","D"])
        self.assertTrue(result["options_complete"])
        self.assertEqual(result["status"],"controle_nodig")
        missing=detect_question_type("Kies het juiste antwoord.\nA. eerste optie\nC. derde optie")
        self.assertFalse(missing["options_complete"])
        self.assertEqual(missing["option_gaps"],["B"])

    def test_context_reference_detection(self):
        from engine import detect_context_references
        refs=detect_context_references("Gebruik figuur 2 en tabel 1. Vergelijk dit met bron A.")
        self.assertEqual([(x["kind"],x["number"]) for x in refs],
                         [("figuur","2"),("tabel","1"),("bron","A")])
        unnumbered=detect_context_references("Gebruik de bovenstaande afbeelding.")
        self.assertEqual(unnumbered[0]["kind"],"ongenummerde_verwijzing")

    def test_candidate_text_is_bounded_by_next_question(self):
        from engine import extract_candidate_text
        analysis={"pages":[
            {"page":1,"blocks":[{"bbox":[0,10,100,20],"lines":[
                {"bbox":[0,10,10,20],"text":"1."},
                {"bbox":[0,25,100,35],"text":"Gebruik figuur 2."},
                {"bbox":[0,50,100,60],"text":"2. Volgende vraag."}]}]},
            {"page":2,"blocks":[{"bbox":[0,5,100,15],"lines":[
                {"bbox":[0,5,100,15],"text":"Vervolg van vraag 2."}]}]}
        ]}
        first={"number":1,"page":1,"bbox":[0,10,10,20]}
        second={"number":2,"page":1,"bbox":[0,50,100,60]}
        self.assertEqual(extract_candidate_text(analysis,first,second),"1.\nGebruik figuur 2.")

    def test_pdf_text_and_exact_crop(self):
        try:
            import pymupdf as fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"source.pdf"
            doc=fitz.open(); page=doc.new_page(); page.insert_text((72,72),"1. Beschrijf de afbeelding.")
            doc.save(p); doc.close()
            result=analyze_pdf(p)
            self.assertEqual(result["page_count"],1)
            self.assertIn("Beschrijf",result["pages"][0]["text"])
            out=Path(d)/"crop.png"
            render_crop(p,1,[60,55,250,90],out)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size,100)

if __name__=="__main__": unittest.main()
