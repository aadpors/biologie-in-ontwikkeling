import tempfile, unittest
from pathlib import Path
from exporter import export_approved_records, validate_review_records

class ExportTests(unittest.TestCase):
    def make_fixture(self, root):
        project=Path(root)/"project"; (project/"bronnen").mkdir(parents=True); (project/"snippets").mkdir()
        for name in ("opgaven.pdf","cv.pdf","uitwerkbijlage.pdf","aanvulling.pdf"):
            (project/"bronnen"/name).write_bytes(b"%PDF-original-"+name.encode())
        (project/"snippets"/"vraag1.png").write_bytes(b"PNG-snippet")
        (project/"snippets"/"cv1.jpg").write_bytes(b"CV-snippet")
        record={
            "id":"ha26t1-open-1","status":"goedgekeurd","approved_by_human":True,
            "exam":{"level":"Havo","year":"2026","period":"1","points":2,"theme":"Ecologie",
                    "concept":"Ecosystemen","end":"E1","focus":"Toepassing","questionType":"open"},
            "number":1,"source_page":2,"source_pdf":"opgaven.pdf","cv_pdf":"cv.pdf",
            "snippet_file":"vraag1.png","cv_snippet_file":"cv1.jpg","question_text":"Beschrijf de relatie.",
            "source_match_human_confirmed":True,"cv_match_human_confirmed":True,
            "appendix_match_human_confirmed":True,"cv_amendment_match_human_confirmed":True,
            "record_review_checklist":{"question_text":True,"question_type":True,"points":True,
                "cv_alignment":True,"images_and_context":True,"appendices":True,"cv_addenda":True},
            "uitwerkbijlagen":["uitwerkbijlage.pdf"]
        }
        return project,record

    def test_unapproved_record_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d); record["approved_by_human"]=False
            result=export_approved_records([record],project,Path(d)/"out")
            self.assertFalse(result["ok"])
            self.assertIn("niet_menselijk_goedgekeurd",[x["error"] for x in result["errors"]])

    def test_complete_cv_addendum_pdf_is_preserved_in_export(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            record["cv_amendment_pdfs"]=["aanvulling.pdf"]
            out=Path(d)/"out"
            result=export_approved_records([record],project,out)
            self.assertTrue(result["ok"],result)
            self.assertTrue((out/"examens"/"aanvulling.pdf").is_file())
            import json
            cv_data=json.loads((out/"scripts"/"cv-snippets.json").read_text(encoding="utf-8"))
            manifest=json.loads((out/"manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["records"][0]["cv_amendment_pdfs"][0]["file"],"examens/aanvulling.pdf")

    def test_approved_flag_without_complete_checklist_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            record["record_review_checklist"]["images_and_context"]=False
            errors=validate_review_records([record],project)
            self.assertIn("controle_niet_afgevinkt:images_and_context",[x["error"] for x in errors])

    def test_mismatched_official_correction_scheme_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            (project/"bronnen"/"ha-1018-a-26-1-o.pdf").write_bytes(b"opgaven")
            (project/"bronnen"/"ha-1018-a-26-2-c.pdf").write_bytes(b"wrong cv")
            record["source_pdf"]="ha-1018-a-26-1-o.pdf"
            record["cv_pdf"]="ha-1018-a-26-2-c.pdf"
            record["source_match_human_confirmed"]=True
            record["cv_match_human_confirmed"]=True
            errors=validate_review_records([record],project)
            self.assertIn("correctievoorschrift_past_niet_bij_examen",[x["error"] for x in errors])

    def test_appendix_from_another_exam_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            wrong="ha-1018-a-26-2-u.pdf"
            (project/"bronnen"/wrong).write_bytes(b"wrong period appendix")
            record["uitwerkbijlagen"]=[wrong]
            errors=validate_review_records([record],project)
            self.assertIn("uitwerkbijlage_past_niet_bij_examen:"+wrong,[x["error"] for x in errors])

    def test_mcq_duplicate_or_empty_options_are_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            record["exam"]["questionType"]="mcq"
            record["options"]=[{"key":"A","text":"Optie A"},{"key":"A","text":""}]
            record["correct"]="A"
            errors=validate_review_records([record],project)
            self.assertIn("meerkeuzeopties_of_correct_antwoord_ongeldig",[x["error"] for x in errors])

    def test_approved_export_includes_complete_appendix_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            out=Path(d)/"out"
            result=export_approved_records([record],project,out)
            self.assertTrue(result["ok"],result)
            self.assertTrue((out/"examens"/"uitwerkbijlage.pdf").is_file())
            self.assertTrue((out/"exam-open.json").is_file())
            self.assertTrue((out/"manifest.json").is_file())
            self.assertTrue((out/"scripts"/"cv-snippets.json").is_file())
            import json
            opened=json.loads((out/"exam-open.json").read_text(encoding="utf-8"))
            self.assertEqual(opened[0]["attachmentPdfs"],["examens/uitwerkbijlage.pdf"])

if __name__=="__main__": unittest.main()
