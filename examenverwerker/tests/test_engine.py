import tempfile, unittest
from pathlib import Path
from engine import detect_question_candidates, detect_cv_question_numbers, compare_question_numbering, propose_question_regions, classify_document_role, infer_exam_metadata, build_question_record, learn_decision, suggest_from_learning, validate_website_records, analyze_pdf, render_crop

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
    def test_learning_requires_repeated_support_and_never_autoplays(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            learn_decision(p,{"pattern_key":"layout-a","chosen":"question","accepted":True})
            self.assertIsNone(suggest_from_learning(p,"layout-a")["suggestion"])
            learn_decision(p,{"pattern_key":"layout-a","chosen":"question","accepted":True})
            s=suggest_from_learning(p,"layout-a")
            self.assertEqual(s["suggestion"],"question")
            self.assertFalse(s["auto_apply"])
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
