import tempfile, unittest
from pathlib import Path
from engine import detect_question_candidates, learn_decision, suggest_from_learning, validate_website_records

class EngineTests(unittest.TestCase):
    def test_question_candidates_keep_repeated_numbers(self):
        a={"pages":[{"page":1,"blocks":[{"bbox":[1,2,3,4],"text":"1. Beschrijf de functie van dit orgaan.\nA. optie"}]},
                    {"page":2,"blocks":[{"bbox":[1,2,3,4],"text":"1. Welke stof wordt gevormd?"}]}]}
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

if __name__=="__main__": unittest.main()
