import unittest
from structure import (
    append_page_span, default_question_links, fragments_for_question, make_cv_fragment, make_exam_structure, make_fragment, missing_question_regions, page_spans_to_segments, validate_cv_fragment,
    make_page_span, mark_structure_stale, validate_exam_structure, normalize_fragments, FRAGMENT_TYPES,
)


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.doc = {"id": "doc-123", "sha256": "abc123"}
        self.questions = [1, 2, 4]

    def test_page_boundaries_are_normalized_and_validated(self):
        span = make_page_span(2, 0.125, 0.875)
        self.assertEqual(span, {"page": 2, "top": 0.125, "bottom": 0.875})
        with self.assertRaises(ValueError):
            make_page_span(2, 0.9, 0.2)
        with self.assertRaises(ValueError):
            make_page_span(0, 0.1, 0.9)

    def test_context_introduction_defaults_to_every_confirmed_question(self):
        self.assertEqual(default_question_links("context_intro", self.questions), [1, 2, 4])
        fragment = make_fragment("context_intro", make_page_span(1, 0.1, 0.8), [],
                                 self.questions, "intro")
        self.assertEqual(fragment["question_numbers"], self.questions)
        self.assertEqual(fragment["type"], "intro")


    def test_only_three_fragment_types_are_exposed_and_legacy_projects_migrate(self):
        self.assertEqual(FRAGMENT_TYPES, {"intro", "tussen_context", "vraag"})
        legacy = [
            {"id": "a", "type": "context_intro", "question_numbers": [1]},
            {"id": "b", "type": "vraagcontext", "question_numbers": [1]},
            {"id": "c", "type": "tussenliggende_context", "question_numbers": [2]},
        ]
        migrated = normalize_fragments(legacy)
        self.assertEqual([x["type"] for x in migrated],
                         ["intro", "tussen_context", "tussen_context"])
        self.assertEqual([x["type"] for x in legacy],
                         ["context_intro", "vraagcontext", "tussenliggende_context"])

    def test_question_fragment_requires_exactly_one_confirmed_question(self):
        with self.assertRaises(ValueError):
            make_fragment("vraag", make_page_span(1, 0.1, 0.8), [1, 2],
                          self.questions, "question")
        with self.assertRaises(ValueError):
            make_fragment("vraag", make_page_span(1, 0.1, 0.8), [9],
                          self.questions, "question")
        fragment = make_fragment("vraag", make_page_span(1, 0.1, 0.8), [2],
                                 self.questions, "question")
        self.assertEqual(fragment["question_numbers"], [2])

    def test_multi_page_fragment_keeps_independent_page_boundaries(self):
        fragment = make_fragment("vraagcontext", make_page_span(2, 0.2, 1.0),
                                 [1, 2], self.questions, "context")
        extended = append_page_span(fragment, make_page_span(3, 0.0, 0.72))
        self.assertEqual([(x["page"], x["top"], x["bottom"]) for x in extended["page_spans"]],
                         [(2, 0.2, 1.0), (3, 0.0, 0.72)])
        with self.assertRaises(ValueError):
            append_page_span(extended, make_page_span(3, 0.1, 0.8))
        with self.assertRaises(ValueError):
            append_page_span(extended, make_page_span(1, 0.1, 0.8))

    def test_structure_requires_confirmed_numbering_and_current_source(self):
        fragment = make_fragment("context_intro", make_page_span(1, 0.1, 0.8),
                                 [], self.questions, "intro")
        structure = make_exam_structure(self.doc, [fragment], self.questions)
        self.assertEqual(validate_exam_structure(structure, "doc-123", "abc123", self.questions), [])
        structure["nummering_bevestigd"] = False
        self.assertIn("vraagnummering_niet_bevestigd",
                      validate_exam_structure(structure, "doc-123", "abc123", self.questions))
        structure["nummering_bevestigd"] = True
        self.assertIn("bronbestand_gewijzigd",
                      validate_exam_structure(structure, "doc-123", "different", self.questions))

    def test_stale_structure_is_blocked_after_reanalysis(self):
        structure = make_exam_structure(self.doc, [], self.questions)
        stale = mark_structure_stale(structure, "bron opnieuw geanalyseerd")
        errors = validate_exam_structure(stale, "doc-123", "abc123", self.questions)
        self.assertIn("structuur_verouderd", errors)
        self.assertEqual(structure["status"], "concept_handmatige_controle")

    def test_invalid_question_links_and_missing_spans_are_blocked(self):
        fragment = make_fragment("vraagcontext", make_page_span(1, 0.1, 0.8),
                                 [1], self.questions, "context")
        fragment["question_numbers"] = [99]
        fragment["page_spans"] = []
        structure = make_exam_structure(self.doc, [fragment], self.questions)
        errors = validate_exam_structure(structure, "doc-123", "abc123", self.questions)
        self.assertIn("ongeldige_vraagkoppeling", errors)
        self.assertIn("fragment_zonder_paginagrenzen", errors)


    def test_question_retrieves_its_question_region_and_shared_context(self):
        intro = make_fragment("context_intro", make_page_span(1, 0.05, 0.2),
                              [], self.questions, "intro")
        question = make_fragment("vraag", make_page_span(2, 0.2, 0.8),
                                 [2], self.questions, "question-2")
        specific = make_fragment("vraagcontext", make_page_span(2, 0.05, 0.18),
                                 [2], self.questions, "context-2")
        structure = make_exam_structure(self.doc, [intro, question, specific], self.questions)
        result = fragments_for_question(structure, 2)
        self.assertEqual(result["question_fragment"]["id"], "question-2")
        self.assertEqual({x["id"] for x in result["context_fragments"]}, {"intro", "context-2"})
        self.assertEqual(fragments_for_question(structure, 4)["status"], "gekoppeld")
        self.assertEqual([x["id"] for x in fragments_for_question(structure, 4)["context_fragments"]], ["intro"])
        self.assertEqual(fragments_for_question(mark_structure_stale(structure, "reanalyse"), 2)["status"],
                         "structuur_niet_beschikbaar")


    def test_cv_regions_are_bound_to_exact_source_and_question(self):
        cv = {"id": "cv-1", "sha256": "cvhash"}
        fragment = make_cv_fragment(cv, 2, [
            make_page_span(3, 0.2, 0.8), make_page_span(4, 0.0, 0.4)
        ])
        self.assertEqual(validate_cv_fragment(fragment, cv, 2), [])
        self.assertIn("cv_fragment_bronbestand_gewijzigd",
                      validate_cv_fragment(fragment, {**cv, "sha256": "new"}, 2))
        self.assertIn("cv_fragment_verkeerd_vraagnummer",
                      validate_cv_fragment(fragment, cv, 3))
        self.assertIn("cv_fragment_verkeerd_documenttype",
                      validate_cv_fragment(fragment, cv, 2, "aanvulling"))

    def test_normalized_spans_convert_to_full_width_pdf_crops(self):
        segments = page_spans_to_segments(
            [{"page": 2, "top": 0.25, "bottom": 0.75}],
            {2: (600.0, 800.0)}
        )
        self.assertEqual(segments, [{"page": 2, "bbox": [0.0, 200.0, 600.0, 600.0]}])

    def test_missing_question_regions_are_detected(self):
        structure = make_exam_structure(self.doc, [
            make_fragment("vraag", make_page_span(2, 0.2, 0.8), [1], self.questions, "q1")
        ], self.questions)
        self.assertEqual(missing_question_regions(structure, self.questions), [2, 4])
        self.assertEqual(missing_question_regions(mark_structure_stale(structure, "changed"), self.questions),
                         self.questions)


    def test_changed_numbering_and_duplicate_question_regions_are_rejected(self):
        first = make_fragment("vraag", make_page_span(1, 0.1, 0.4), [1], self.questions, "q1a")
        second = make_fragment("vraag", make_page_span(2, 0.1, 0.4), [1], self.questions, "q1b")
        structure = make_exam_structure(self.doc, [first, second], self.questions)
        errors = validate_exam_structure(structure, "doc-123", "abc123", self.questions)
        self.assertIn("meerdere_vraagfragmenten_voor_een_vraag", errors)
        self.assertIn("bevestigde_vraagnummering_gewijzigd",
                      validate_exam_structure(structure, "doc-123", "abc123", [1, 2]))


    def test_context_fragments_must_link_to_at_least_one_question(self):
        with self.assertRaises(ValueError):
            make_fragment("vraagcontext", make_page_span(1, 0.1, 0.8), [],
                          self.questions, "unlinked-context")
        fragment = make_fragment("vraagcontext", make_page_span(1, 0.1, 0.8),
                                 [1], self.questions, "context")
        fragment["question_numbers"] = []
        structure = make_exam_structure(self.doc, [fragment], self.questions)
        self.assertIn("contextfragment_zonder_vraagkoppeling",
                      validate_exam_structure(structure, "doc-123", "abc123", self.questions))



if __name__ == "__main__":
    unittest.main()
