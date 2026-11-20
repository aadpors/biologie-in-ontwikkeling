import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from structure import make_exam_structure, make_fragment, make_page_span, make_cv_fragment
from exam_workflow import (
    exam_export_fingerprint, exam_workflow_state, restore_import_batch,
)


def project():
    doc = {
        "id": "opgaven-1", "sha256": "source-hash", "type_voorstel": "opgaven",
        "documenttype_handmatig": "opgaven", "status": "handmatig_bevestigd",
    }
    candidate = {
        "id": "candidate-1", "document_id": "opgaven-1",
        "number": 1, "page": 2, "human_decision": True,
    }
    return {
        "documenten": [doc],
        "exam_metadata": {"level": "Vwo", "year": "2026", "period": "1",
                          "source": "handmatig_bevestigd"},
        "vraagkandidaten": [candidate],
        "vraagrecords": [],
    }


def with_structure(data):
    doc = data["documenten"][0]
    fragment = make_fragment("vraag", make_page_span(2, .1, .8), [1], [1], "q1")
    data["exam_structures"] = {
        doc["id"]: make_exam_structure(doc, [fragment], [1])
    }
    data["vraagkandidaten"][0]["vraagtype_controle"] = {"type": "open"}
    data["vraagkandidaten"][0]["vraagtype_status"] = "visueel_bevestigd"
    return data


def with_cv(data):
    cv = {
        "id": "cv-1", "sha256": "cv-hash", "type_voorstel": "correctievoorschrift",
        "documenttype_handmatig": "correctievoorschrift", "status": "handmatig_bevestigd",
        "vraagstarts_detectie": {"status": "visueel_bevestigd"},
    }
    data["documenten"].append(cv)
    data["cv_regions"] = {
        "cv-1": {"1": make_cv_fragment(cv, 1, [{"page": 1, "top": .1, "bottom": .8}])}
    }
    return data


def with_record(data):
    data["vraagrecords"] = [{
        "id": "record-1", "candidate_document_id": "opgaven-1",
        "number": 1, "source_page": 2,
    }]
    return data


class ExamWorkflowTests(unittest.TestCase):
    def test_empty_project_starts_at_import(self):
        self.assertEqual(exam_workflow_state({})["stage"], "import")

    def test_document_type_confirmation_precedes_metadata_and_analysis(self):
        data = project()
        data["documenten"][0]["status"] = "voorstel"
        self.assertEqual(exam_workflow_state(data)["stage"], "documenttype")

    def test_metadata_must_be_confirmed(self):
        data = project()
        data["exam_metadata"]["source"] = "bestandsnaam"
        self.assertEqual(exam_workflow_state(data)["stage"], "metadata")

    def test_question_starts_are_detected_before_fragments(self):
        data = project()
        data["vraagkandidaten"] = []
        self.assertEqual(exam_workflow_state(data)["stage"], "vraagstarts")

    def test_undecided_question_start_blocks_fragment_editor(self):
        data = project()
        data["vraagkandidaten"][0]["human_decision"] = None
        self.assertEqual(exam_workflow_state(data)["stage"], "vraagstarts")

    def test_confirmed_question_requires_question_and_context_fragments(self):
        self.assertEqual(exam_workflow_state(project())["stage"], "opgaven_fragmenten")

    def test_stale_structure_returns_to_fragment_review(self):
        data = with_structure(project())
        data["exam_structures"]["opgaven-1"]["status"] = "verouderd"
        self.assertEqual(exam_workflow_state(data)["stage"], "opgaven_fragmenten")

    def test_question_type_is_reviewed_after_fragment_boundaries(self):
        data = with_structure(project())
        data["vraagkandidaten"][0]["vraagtype_status"] = "controle_nodig"
        self.assertEqual(exam_workflow_state(data)["stage"], "vraaganalyse")

    def test_cv_is_required_after_question_analysis(self):
        data = with_structure(project())
        self.assertEqual(exam_workflow_state(data)["stage"], "vraaganalyse")
        with_record(data)
        self.assertEqual(exam_workflow_state(data)["stage"], "cv_starts")

    def test_cv_question_starts_require_visual_review(self):
        data = with_record(with_structure(project()))
        data["documenten"].append({
            "id": "cv-1", "sha256": "cv-hash", "type_voorstel": "correctievoorschrift",
            "documenttype_handmatig": "correctievoorschrift", "status": "handmatig_bevestigd",
        })
        self.assertEqual(exam_workflow_state(data)["stage"], "cv_starts")

    def test_appendix_question_starts_require_visual_review(self):
        data = with_record(with_structure(project()))
        data["documenten"].append({
            "id": "appendix-1", "sha256": "appendix-hash", "type_voorstel": "uitwerkbijlage",
            "documenttype_handmatig": "uitwerkbijlage", "status": "handmatig_bevestigd",
        })
        self.assertEqual(exam_workflow_state(data)["stage"], "uitwerkbijlage_starts")

    def test_cv_region_is_required_for_each_question(self):
        data = with_record(with_structure(project()))
        data["documenten"].append({
            "id": "cv-1", "sha256": "cv-hash", "type_voorstel": "correctievoorschrift",
            "documenttype_handmatig": "correctievoorschrift", "status": "handmatig_bevestigd",
        })
        self.assertEqual(exam_workflow_state(data)["stage"], "cv_fragmenten")

    def test_answer_review_follows_cv_fragment_review(self):
        data = with_cv(with_record(with_structure(project())))
        self.assertEqual(exam_workflow_state(data)["stage"], "antwoorden")
        data["vraagrecords"][0]["answer_review"] = {"status": "visueel_bevestigd"}
        self.assertEqual(exam_workflow_state(data)["stage"], "volledigheid")

    def test_snippet_and_final_visual_review_are_distinct_gates(self):
        data = with_cv(with_record(with_structure(project())))
        data["vraagrecords"][0]["answer_review"] = {"status": "visueel_bevestigd"}
        data["completeness_review"] = {"status": "visueel_bevestigd"}
        self.assertEqual(exam_workflow_state(data)["stage"], "snippets")
        data["vraagrecords"][0]["question_region_snippet_file"] = "q1.png"
        self.assertEqual(exam_workflow_state(data)["stage"], "eindcontrole")
        data["final_visual_review"] = {"status": "visueel_bevestigd"}
        self.assertEqual(exam_workflow_state(data)["stage"], "export")

    def test_export_fingerprint_detects_any_reviewed_data_change(self):
        data = with_cv(with_record(with_structure(project())))
        first = exam_export_fingerprint(data)
        data["vraagrecords"][0]["question_text"] = "Aangepast"
        self.assertNotEqual(first, exam_export_fingerprint(data))

    def test_matching_export_fingerprint_marks_project_complete(self):
        data = with_cv(with_record(with_structure(project())))
        data["vraagrecords"][0]["answer_review"] = {"status": "visueel_bevestigd"}
        data["vraagrecords"][0]["question_region_snippet_file"] = "q1.png"
        data["completeness_review"] = {"status": "visueel_bevestigd"}
        data["final_visual_review"] = {"status": "visueel_bevestigd"}
        data["export_status"] = {"fingerprint": exam_export_fingerprint(data)}
        self.assertEqual(exam_workflow_state(data)["stage"], "voltooid")

    def test_import_batch_is_restored_after_restart(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            first, second = root / "2025" / "havo", root / "2026" / "vwo"
            for folder in (first, second):
                folder.mkdir(parents=True)
                (folder / "project.json").write_text("{}", encoding="utf-8")
            (root / "import-batch.json").write_text(json.dumps({
                "schema": "biologie-examenimport-v1",
                "projecten": [{"pad": "2025/havo"}, {"pad": "2026/vwo"}],
            }), encoding="utf-8")
            restored = restore_import_batch(root, second, {
                "import_batch_manifest": "import-batch.json"})
            self.assertEqual(restored["paths"], [first.resolve(), second.resolve()])
            self.assertEqual(restored["index"], 1)

    def test_import_batch_manifest_cannot_escape_exam_root(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "examens"
            root.mkdir()
            outside = Path(temp) / "outside"
            outside.mkdir()
            (outside / "project.json").write_text("{}", encoding="utf-8")
            (root / "import-batch.json").write_text(json.dumps({
                "schema": "biologie-examenimport-v1", "projecten": [{"pad": "../outside"}]
            }), encoding="utf-8")
            self.assertIsNone(restore_import_batch(root, outside, {
                "import_batch_manifest": "import-batch.json"}))


if __name__ == "__main__":
    unittest.main()
