import tempfile, unittest
from pathlib import Path
from engine import detect_question_candidates, learn_decision, suggest_from_learning, validate_website_records, analyze_pdf, render_crop

class EngineTests(unittest.TestCase):
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
    def test_pdf_text_and_exact_crop(self):
        try:
            import fitz
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
