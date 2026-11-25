"""Regressietests voor de uitlegbare zelflerende detectielaag."""
import tempfile
import unittest
from pathlib import Path

from examenverwerker.learning import (
    MIN_EXAMPLES_PER_FEATURE,
    build_learning_profile,
    learned_adjustment,
    question_start_features,
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
