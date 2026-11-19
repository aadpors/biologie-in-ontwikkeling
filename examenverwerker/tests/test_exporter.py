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
        (project/"snippets"/"cv-amend1.png").write_bytes(b"CV-amendment-snippet")
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
        import hashlib
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        record.update({
            "exam_structure_status":"gekoppeld",
            "exam_structure_document_id":"opgaven-doc-1",\n            "question_region_fragment_id":"q1","exam_structure_fragment_ids":["q1"],"exam_structure_question_number":1,
            "exam_structure_source_sha256":digest(project/"bronnen"/"opgaven.pdf"),
            "question_region_page_spans":[{"page":2,"top":0.1,"bottom":0.9}],
            "cv_source_document_id":"cv-doc-1",
            "cv_source_sha256":digest(project/"bronnen"/"cv.pdf"),
            "cv_source_region":{"id":"cv-cv-doc-1-q1","document_id":"cv-doc-1",
                "source_sha256":digest(project/"bronnen"/"cv.pdf"),"document_role":"correctievoorschrift",
                "question_number":1,"page_spans":[{"page":1,"top":0.1,"bottom":0.9}]},
            "cv_source_region_file":"cv1.jpg",
            "cv_snippet_file":"cv1.jpg",
            "cv_snippet_files":["cv1.jpg"],
            "context_asset_files":[],
            "cv_amendment_regions":[],
        })
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
            import hashlib
            amendment_hash=hashlib.sha256((project/"bronnen"/"aanvulling.pdf").read_bytes()).hexdigest()
            record["cv_amendment_pdfs"]=["aanvulling.pdf"]
            record["cv_amendment_snippet_file"]="cv-amend1.png"
            record["cv_amendment_snippet_files"]=["cv-amend1.png"]
            record["cv_amendment_regions"]=[{"document_id":"amend-doc","source_pdf":"aanvulling.pdf",
                "source_sha256":amendment_hash,"snippet_file":"cv-amend1.png",
                "fragment":{"id":"cv-amend-doc-q1","document_id":"amend-doc","source_sha256":amendment_hash,
                    "document_role":"aanvulling","question_number":1,"page_spans":[{"page":1,"top":0.1,"bottom":0.9}]}}]
            out=Path(d)/"out"
            result=export_approved_records([record],project,out)
            self.assertTrue(result["ok"],result)
            self.assertTrue((out/"examens"/"aanvulling.pdf").is_file())
            self.assertTrue((out/"exam-snippets"/"cv-amend1.png").is_file())
            import json
            cv_data=json.loads((out/"scripts"/"cv-snippets.json").read_text(encoding="utf-8"))
            manifest=json.loads((out/"manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["records"][0]["cv_amendment_pdfs"][0]["file"],"examens/aanvulling.pdf")
            self.assertTrue(manifest["records"][0]["cv_snippet_sha256"])
            self.assertTrue(manifest["records"][0]["cv_amendment_snippet_sha256"])
            self.assertEqual(cv_data[0]["amendment_output"],"cv-amend1.png")

    def test_invalidated_source_analysis_is_blocked_even_if_record_was_approved(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            record["source_analysis_invalidated"]=True
            errors=validate_review_records([record],project)
            self.assertIn("bron_analyse_verouderd",[x["error"] for x in errors])

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
            record["cv_match_human_confirmed"]=False
            errors=validate_review_records([record],project)
            self.assertIn("correctievoorschrift_past_niet_bij_examen",[x["error"] for x in errors])

    def test_manual_cv_identity_override_is_allowed_after_review(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            (project/"bronnen"/"ha-1018-a-26-1-o.pdf").write_bytes(b"opgaven")
            (project/"bronnen"/"ha-1018-a-26-2-c.pdf").write_bytes(b"manually confirmed cv")
            record["source_pdf"]="ha-1018-a-26-1-o.pdf"
            record["cv_pdf"]="ha-1018-a-26-2-c.pdf"
            record["source_match_human_confirmed"]=False
            record["cv_match_human_confirmed"]=True
            errors=validate_review_records([record],project)
            self.assertNotIn("correctievoorschrift_past_niet_bij_examen",[x["error"] for x in errors])

    def test_appendix_from_another_exam_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            wrong="ha-1018-a-26-2-u.pdf"
            (project/"bronnen"/wrong).write_bytes(b"wrong period appendix")
            record["uitwerkbijlagen"]=[wrong]
            record["appendix_match_human_confirmed"]=False
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


    def test_export_manifest_preserves_manual_exam_structure_regions(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            record["exam_structure_status"]="gekoppeld"
            record["exam_structure_fragment_ids"]=["intro-1","question-1"]
            record["question_region_page_spans"]=[{"page":2,"top":0.2,"bottom":0.8}]
            record["context_region_fragments"]=[{"id":"intro-1","type":"context_intro",
                "page_spans":[{"page":1,"top":0.1,"bottom":0.3}]}]
            result=export_approved_records([record],project,Path(d)/"out")
            self.assertTrue(result["ok"],result)
            import json
            manifest=json.loads((Path(d)/"out"/"manifest.json").read_text(encoding="utf-8"))
            exported=manifest["records"][0]
            self.assertEqual(exported["exam_structure_status"],"gekoppeld")
            self.assertEqual(exported["exam_structure_fragment_ids"],["intro-1","question-1"])
            self.assertEqual(exported["question_region_page_spans"],record["question_region_page_spans"])
            self.assertEqual(exported["context_region_fragments"],record["context_region_fragments"])


    def test_context_images_are_exported_separately_from_question_images(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            (project/"snippets"/"context-figuur.png").write_bytes(b"context image")
            record["context_asset_files"]=[{"file":"context-figuur.png","asset_id":"p2-image-1",
                "page":2,"caption":"Microscopische afbeelding","source_document_id":"opgaven-doc-1"}]
            record["context_region_fragments"]=[{"id":"context-1","type":"context_intro",
                "page_spans":[{"page":1,"top":0.1,"bottom":0.3}],"text":"De contexttekst."}]
            out=Path(d)/"out"
            result=export_approved_records([record],project,out)
            self.assertTrue(result["ok"],result)
            import json
            question=json.loads((out/"exam-open.json").read_text(encoding="utf-8"))[0]
            context=json.loads((out/"exam-contexts.json").read_text(encoding="utf-8"))[0]
            self.assertEqual(question["images"],["exam-snippets/vraag1.png"])
            self.assertEqual(context["contextImages"],["exam-snippets/context-figuur.png"])
            self.assertEqual(context["image"],"exam-snippets/context-figuur.png")
            self.assertEqual(context["contextRegions"][0]["text"],"De contexttekst.")
            self.assertTrue((out/"exam-snippets"/"context-figuur.png").is_file())

    def test_export_blocks_missing_manual_question_or_cv_region(self):
        with tempfile.TemporaryDirectory() as d:
            project,record=self.make_fixture(d)
            record["question_region_page_spans"]=[]
            record["cv_source_region"]=None
            errors=validate_review_records([record],project)
            codes=[x["error"] for x in errors]
            self.assertIn("vraagfragment_paginagrenzen_ontbreken",codes)
            self.assertIn("cv_handmatige_afbakening_ontbreekt",codes)


if __name__=="__main__": unittest.main()
