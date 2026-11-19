import unittest

from structure import make_exam_structure, make_fragment, make_page_span
from workflow import exam_export_fingerprint, exam_workflow_state


def base_exam():
    document = {"id": "opgaven-1", "sha256": "source-hash", "type_voorstel": "opgaven"}
    candidate = {
        "id": "candidate-1", "document_id": "opgaven-1",
        "number": 1, "page": 2, "human_decision": True,
    }
    return {
        "documenten": [document],
        "vraagkandidaten": [candidate],
        "vraagrecords": [],
    }


def with_valid_structure(data):
    document = data["documenten"][0]
    fragment = make_fragment(
        "vraag", make_page_span(2, 0.1, 0.8), [1], [1], "question-1"
    )
    data["exam_structures"] = {
        document["id"]: make_exam_structure(document, [fragment], [1])
    }
    return data


class ExamWorkflowTests(unittest.TestCase):
    def test_empty_exam_starts_at_import(self):
        self.assertEqual(exam_workflow_state({})["stage"], "import")

    def test_exam_without_opgaven_role_requires_document_review(self):
        data = {"documenten": [{"type_voorstel": "correctievoorschrift"}]}
        self.assertEqual(exam_workflow_state(data)["stage"], "documenttype")

    def test_opgaven_without_candidates_requires_analysis(self):
        data = {"documenten": [{"id": "o", "type_voorstel": "opgaven"}],
                "vraagkandidaten": []}
        self.assertEqual(exam_workflow_state(data)["stage"], "analyse")

    def test_undecided_candidate_blocks_structure_and_records(self):
        data = base_exam()
        data["vraagkandidaten"][0]["human_decision"] = None
        self.assertEqual(exam_workflow_state(data)["stage"], "vraagstarts")

    def test_all_rejected_candidates_require_missing_question_check(self):
        data = base_exam()
        data["vraagkandidaten"][0]["human_decision"] = False
        self.assertEqual(exam_workflow_state(data)["stage"], "ontbrekende_vragen")

    def test_confirmed_candidates_require_current_structure(self):
        self.assertEqual(exam_workflow_state(base_exam())["stage"], "structuur")

    def test_stale_structure_returns_exam_to_structure_stage(self):
        data = with_valid_structure(base_exam())
        data["exam_structures"]["opgaven-1"]["status"] = "verouderd"
        self.assertEqual(exam_workflow_state(data)["stage"], "structuur")

    def test_valid_structure_requires_question_record(self):
        data = with_valid_structure(base_exam())
        self.assertEqual(exam_workflow_state(data)["stage"], "vraagrecords")

    def test_record_requires_human_approval(self):
        data = with_valid_structure(base_exam())
        data["vraagrecords"] = [{
            "candidate_document_id": "opgaven-1",
            "number": 1, "source_page": 2, "approved_by_human": False,
        }]
        self.assertEqual(exam_workflow_state(data)["stage"], "eindcontrole")

    def test_fully_approved_exam_is_ready_for_export(self):
        data = with_valid_structure(base_exam())
        data["vraagrecords"] = [{
            "candidate_document_id": "opgaven-1",
            "number": 1, "source_page": 2, "approved_by_human": True,
        }]
        self.assertEqual(exam_workflow_state(data)["stage"], "export")

    def test_each_opgaven_pdf_needs_its_own_valid_structure(self):
        data = with_valid_structure(base_exam())
        data["documenten"].append({
            "id": "opgaven-2", "sha256": "second-hash", "type_voorstel": "opgaven"
        })
        self.assertEqual(exam_workflow_state(data)["stage"], "structuur")

    def test_matching_export_fingerprint_marks_exam_complete(self):
        data = with_valid_structure(base_exam())
        data["vraagrecords"] = [{
            "candidate_document_id": "opgaven-1",
            "number": 1, "source_page": 2, "approved_by_human": True,
        }]
        data["export_status"] = {
            "fingerprint": exam_export_fingerprint(data),
            "export_dir": "export/test",
        }
        self.assertEqual(exam_workflow_state(data)["stage"], "voltooid")

    def test_changed_record_invalidates_previous_export_completion(self):
        data = with_valid_structure(base_exam())
        data["vraagrecords"] = [{
            "candidate_document_id": "opgaven-1",
            "number": 1, "source_page": 2, "approved_by_human": True,
            "question_text": "Oorspronkelijke vraag",
        }]
        data["export_status"] = {
            "fingerprint": exam_export_fingerprint(data),
            "export_dir": "export/test",
        }
        data["vraagrecords"][0]["question_text"] = "Gewijzigde vraag"
        self.assertEqual(exam_workflow_state(data)["stage"], "export")


if __name__ == "__main__":
    unittest.main()
