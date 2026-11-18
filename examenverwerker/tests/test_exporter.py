import tempfile, unittest
from pathlib import Path
from exporter import export_approved_records

class ExportTests(unittest.TestCase):
    def make_fixture(self, root):
        project=Path(root)/"project"; (project/"bronnen").mkdir(parents=True); (project/"snippets").mkdir()
        for name in ("opgaven.pdf","cv.pdf","uitwerkbijlage.pdf"):
            (project/"bronnen"/name).write_bytes(b"%PDF-original-"+name.encode())
        (project/"snippets"/"vraag1.png").write_bytes(b"PNG-snippet")
        record={
            "id":"ha26t1-open-1","status":"goedgekeurd","approved_by_human":True,
            "exam":{"level":"Havo","year":"2026","period":"1","points":2,"theme":"Ecologie",
                    "concept":"Ecosystemen","end":"E1","focus":"Toepassing","questionType":"open"},
            "number":1,"source_page":2,"source_pdf":"opgaven.pdf","cv_pdf":"cv.pdf",
            "snippet_file":"vraag1.png","question_text":"Beschrijf de relatie.",
            "uitwerkbijlagen":["uitwerkbijlage.pdf"]
        }
        return project,record

    def test_unapproved_record_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d); record["approved_by_human"]=False
            result=export_approved_records([record],project,Path(d)/"out")
            self.assertFalse(result["ok"])
            self.assertIn("niet_menselijk_goedgekeurd",[x["error"] for x in result["errors"]])

    def test_approved_export_includes_complete_appendix_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            out=Path(d)/"out"
            result=export_approved_records([record],project,out)
            self.assertTrue(result["ok"],result)
            self.assertTrue((out/"examens"/"uitwerkbijlage.pdf").is_file())
            self.assertTrue((out/"exam-open.json").is_file())
            self.assertTrue((out/"manifest.json").is_file())

if __name__=="__main__": unittest.main()
