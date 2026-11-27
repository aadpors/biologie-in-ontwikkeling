"""Static contract tests for high-risk browser workflow regressions.

These checks supplement the API tests: they protect the exact browser-side
wiring for autosave flush, step-specific recovery and context-card layout.
A real browser smoke test is still needed for pixel-level interaction.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
APP_JS = ROOT / "static" / "app.js"
APP_CSS = ROOT / "static" / "app.css"


class FrontendBugfixContractTests(unittest.TestCase):
    def test_autosave_flush_listens_to_input_and_change_and_exposes_flush(self):
        js = APP_JS.read_text(encoding="utf-8")
        self.assertIn("panel.addEventListener('input', schedule);", js)
        self.assertIn("panel.addEventListener('change', schedule);", js)
        self.assertIn("panel._stageAutoSaveFlush = saveNow;", js)
        self.assertIn("panel.removeEventListener('input', schedule);", js)
        self.assertIn("panel.removeEventListener('change', schedule);", js)

    def test_step3_continue_flushes_pending_selection_before_completion(self):
        js = APP_JS.read_text(encoding="utf-8")
        start = js.index("$('#completeStitched').addEventListener('click'")
        end = js.index("    render();", start)
        completion = js[start:end]
        self.assertIn("clearTimeout(saveTimer);", completion)
        self.assertIn("await saveChain;", completion)
        self.assertIn("await persistSelections(true);", completion)
        self.assertLess(completion.index("await persistSelections(true);"),
                        completion.index("await api(`/api/exams/"))

    def test_stale_fragment_recovery_parses_step_number_and_maps_step6(self):
        js = APP_JS.read_text(encoding="utf-8")
        self.assertIn(r"error.message.match(/heropen stap\s*(\d+)/i)", js)
        self.assertIn("6: {key: 'uitwerk_fragments', label: 'stap 6 · fragmenten uitwerkbijlage'}", js)

    def test_cv_supplement_stitched_page_has_a_tall_scrollable_viewport(self):
        js = APP_JS.read_text(encoding="utf-8")
        css = APP_CSS.read_text(encoding="utf-8")
        # De CV-aanvulling gebruikt de lange samengevoegde pagina in de
        # fragmentselectiestap. De klasse moet daar worden gezet en bij het
        # openen van een volgende stap weer worden verwijderd.
        self.assertIn("panel.classList.toggle('supplement-fragments-stage', documentType === 'aanvulling_correctievoorschrift');", js)
        self.assertIn("stagePanel?.classList.remove('supplement-fragments-stage', 'supplement-merge-stage');", js)
        self.assertIn(".stage-panel.supplement-fragments-stage .stitched-image-scroll", css)
        self.assertIn("height: clamp(360px, 70vh, 900px) !important;", css)
        self.assertIn("overflow-y: scroll !important;", css)
        self.assertIn(".stage-panel.supplement-fragments-stage .stitched-image-wrap img", css)
        self.assertIn("height: auto !important;", css)

    def test_answer_review_restore_tolerates_older_saved_records_without_supplement_field(self):
        backend = (ROOT / "examenverwerker" / "main.py").read_text(encoding="utf-8")
        # Oude reviews kunnen het supplementveld missen; herstel moet .get() gebruiken.
        self.assertIn('saved[question["question_number"]].get(k, question.get(k))', backend)
        self.assertIn('Oudere opgeslagen antwoordreviews bevatten nog niet altijd', backend)

    def test_context_group_cards_wrap_inside_inspector(self):
        css = APP_CSS.read_text(encoding="utf-8")
        for rule in [
            "#contextGroupSummary .context-group-card",
            "#contextGroupSummary .context-group-title",
            "overflow-wrap: anywhere;",
            "#contextGroupSummary .context-group-questions",
            "flex-wrap: wrap;",
            "#contextGroupSummary .context-group-question-card",
            "min-width: 0;",
        ]:
            self.assertIn(rule, css)

    def test_supplement_stitched_image_route_allows_fetching_png(self):
        # De review-API kan een afbeelding genereren, maar een aparte route-
        # whitelist moet diezelfde afbeelding ook aan de browser kunnen leveren.
        # Dit beschermt tegen het geval waarin een URL 404 geeft terwijl de
        # fragmentreview verder wel metadata voor die afbeelding ontvangt.
        backend = (ROOT / "examenverwerker" / "main.py").read_text(encoding="utf-8")
        self.assertIn('"aanvulling_correctievoorschrift"} or filename != "exam-long.png"', backend)
        self.assertIn('/api/stitched-document-images/{exam_id}/{document_type}/{filename}', backend)


if __name__ == "__main__":
    unittest.main()
