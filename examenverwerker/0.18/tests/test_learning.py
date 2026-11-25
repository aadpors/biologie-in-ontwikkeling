"""Regressietests voor de uitlegbare zelflerende detectielaag."""
import tempfile
import unittest
from pathlib import Path

from examenverwerker.learning import (
    MIN_EXAMPLES_PER_FEATURE,
    build_learning_profile,
    learned_adjustment,
    question_start_features,
    build_boundary_learning_profile,
    build_context_learning_profile,
    apply_context_range_learning,
    learned_boundary_overrides,
)
from examenverwerker.storage import Store


class LearningTests(unittest.TestCase):
    def test_question_start_features_are_independent_of_render_resolution(self):
        candidate = {
            "text": "2p 17 Via welk bloedvat wordt zuurstof vervoerd?",
            "pdf_bbox": [60, 120, 72, 134],
            "font_size": 11,
            "source": "automatic",
        }
        features = question_start_features(candidate, {"width": 600, "height": 800})
        self.assertEqual(features["x_band"], "0.1")
        self.assertEqual(features["y_zone"], "body")
        self.assertEqual(features["font_band"], "normal")

    def test_profile_does_not_activate_from_too_few_examples(self):
        examples = [
            {"accepted": True, "features": {"form": "standalone_number"}}
            for _ in range(MIN_EXAMPLES_PER_FEATURE - 1)
        ]
        profile = build_learning_profile(examples)
        self.assertEqual(profile["active_feature_count"], 0)
        adjustment = learned_adjustment({"form": "standalone_number"}, profile)
        self.assertFalse(adjustment["learning_active"])
        self.assertEqual(adjustment["score_adjustment"], 0.0)

    def test_profile_activates_only_after_minimum_reviewed_examples(self):
        examples = [
            {"accepted": index < 4, "features": {"form": "standalone_number"}}
            for index in range(MIN_EXAMPLES_PER_FEATURE)
        ]
        profile = build_learning_profile(examples)
        self.assertEqual(profile["active_feature_count"], 1)
        adjustment = learned_adjustment({"form": "standalone_number"}, profile)
        self.assertTrue(adjustment["learning_active"])
        self.assertGreater(adjustment["score_adjustment"], 0)
        self.assertEqual(adjustment["evidence"][0]["examples"], MIN_EXAMPLES_PER_FEATURE)

    def test_score_adjustment_is_bounded_and_never_sets_acceptance(self):
        examples = [
            {"accepted": False, "features": {"form": "sequence_warning"}}
            for _ in range(20)
        ]
        profile = build_learning_profile(examples)
        adjustment = learned_adjustment({"form": "sequence_warning"}, profile)
        self.assertGreaterEqual(adjustment["score_adjustment"], -0.15)
        self.assertLessEqual(adjustment["score_adjustment"], 0.15)
        self.assertNotIn("accepted", adjustment)

    def test_boundary_profile_learns_median_manual_offsets_per_document_type(self):
        records = [{
            "stage": "fragment_boundaries:opgaven",
            "accepted": {"examples": [
                {"start_offset": -2, "end_offset": 4},
                {"start_offset": -4, "end_offset": 6},
                {"start_offset": -3, "end_offset": 5},
                {"start_offset": -3, "end_offset": 5},
                {"start_offset": -5, "end_offset": 7},
            ]},
        }]
        profile = build_boundary_learning_profile(records)
        self.assertTrue(profile["opgaven"]["active"])
        self.assertEqual(profile["opgaven"]["median_start_offset"], -3)
        self.assertEqual(profile["opgaven"]["median_end_offset"], 5)

    def test_context_profile_learns_corrected_question_ranges(self):
        records = [{
            "stage": "fragment_review",
            "summary": {"context_range_changes": [
                {"suggested_from": 2, "suggested_to": 4, "accepted_from": 1, "accepted_to": 5}
                for _ in range(5)
            ]},
        }]
        profile = build_context_learning_profile(records)
        self.assertTrue(profile["active"])
        self.assertEqual(profile["median_start_shift"], -1)
        self.assertEqual(profile["median_end_shift"], 1)

    def test_learned_context_range_adjustment_is_clamped_and_visible(self):
        contexts = [{
            "id": "context-1", "from_question": 2, "to_question": 4,
            "reviewed": False,
        }]
        profile = {
            "active": True, "examples": 6,
            "median_start_shift": -1, "median_end_shift": 2,
        }
        adjusted = apply_context_range_learning(contexts, profile, {1, 2, 3, 4, 5})
        self.assertEqual(adjusted[0]["from_question"], 1)
        self.assertEqual(adjusted[0]["to_question"], 5)
        self.assertTrue(adjusted[0]["learning_adjusted"])
        self.assertEqual(adjusted[0]["learning_correction"]["examples"], 6)

    def test_learned_context_ranges_never_change_reviewed_contexts(self):
        contexts = [{
            "id": "context-1", "from_question": 2, "to_question": 4,
            "reviewed": True,
        }]
        profile = {
            "active": True, "examples": 8,
            "median_start_shift": -2, "median_end_shift": 3,
        }
        adjusted = apply_context_range_learning(contexts, profile, {1, 2, 3, 4, 5})
        self.assertEqual(adjusted[0]["from_question"], 2)
        self.assertEqual(adjusted[0]["to_question"], 4)

    def test_learned_boundary_offsets_create_proposals_for_each_question(self):
        starts = [
            {"question_number": 1, "page_index": 0, "pdf_bbox": [50, 100, 60, 112]},
            {"question_number": 2, "page_index": 0, "pdf_bbox": [50, 300, 60, 312]},
            {"question_number": 3, "page_index": 1, "pdf_bbox": [50, 80, 60, 92]},
        ]
        profile = {
            "active": True, "examples": 7,
            "median_start_offset": -4, "median_end_offset": 6,
        }
        overrides = learned_boundary_overrides(starts, [800, 800], profile)
        self.assertEqual(overrides[1]["start_y"], 96)
        self.assertEqual(overrides[1]["end_y"], 296)
        self.assertEqual(overrides[2]["start_y"], 296)
        self.assertEqual(overrides[2]["end_y"], 76)
        self.assertEqual(overrides[3]["start_y"], 76)
        self.assertEqual(overrides[3]["end_y"], 806)

    def test_boundary_learning_is_inactive_below_five_examples(self):
        starts = [{"question_number": 1, "page_index": 0, "pdf_bbox": [50, 100, 60, 112]}]
        profile = {"active": False, "examples": 4, "median_start_offset": -4, "median_end_offset": 6}
        self.assertEqual(learned_boundary_overrides(starts, [800], profile), {})

    def test_feedback_is_append_only_and_can_be_reloaded(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            store.create_exam("exam-1", "Testexamen", [])
            examples = [{"accepted": True, "features": {"form": "manual"}}]
            store.record_detection_examples("exam-1", "question_starts:opgaven", "hash", examples)
            store.record_detection_examples("exam-1", "question_starts:opgaven", "hash", examples)
            records = store.list_fragment_feedback("question_starts:opgaven")
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["accepted"]["examples"], examples)
            self.assertEqual(store.fragment_feedback_count("question_starts:opgaven"), 2)


if __name__ == "__main__":
    unittest.main()
