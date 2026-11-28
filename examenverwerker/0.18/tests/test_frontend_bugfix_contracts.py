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
        # De backend voegt opgeslagen reviews per veld samen. Een ontbrekend
        # veld in een oud record mag de actuele herkenning niet overschrijven.
        self.assertIn('saved_question = saved[question["question_number"]]', backend)
        self.assertIn('saved_value = saved_question.get(key)', backend)
        self.assertIn('if saved_value is not None or current_value is None:', backend)

    def test_answer_review_sends_server_detected_scores_to_persistent_evidence(self):
        # Stap 12 toont de herkende scores, maar de antwoordvelden zelf zijn
        # niet bewerkbaar. De browser moet ze meesturen; de backend vult ze
        # bovendien server-side aan zodat een oudere client ze niet verliest.
        js = APP_JS.read_text(encoding="utf-8")
        backend = (ROOT / "examenverwerker" / "main.py").read_text(encoding="utf-8")
        self.assertIn("cv_max_points:detected.cv_max_points", js)
        self.assertIn("opgaven_max_points:detected.opgaven_max_points", js)
        self.assertIn('detected_by_number = {', backend)
        self.assertIn('"cv_max_points": (', backend)
        self.assertIn('"opgaven_max_points": (', backend)
        self.assertIn('else detected_by_number.get(item.get("question_number"), {}).get("cv_max_points")', backend)

    def test_multi_exam_import_keeps_only_unprocessed_bundles_after_failure(self):
        # Elke afgeronde of bewust overgeslagen bundel verdwijnt meteen uit
        # de selectie. Een fout bij een volgende bundel mag geen reeds
        # geïmporteerde bundel opnieuw aanbieden bij een retry.
        js = APP_JS.read_text(encoding="utf-8")
        start = js.index("for (const [key, files] of groups)")
        end = js.index("if (completed.length === 1", start)
        loop = js[start:end]
        self.assertIn("const processedFiles = new Set(files);", loop)
        self.assertIn("selectedImportFiles = selectedImportFiles.filter(file => !processedFiles.has(file));", loop)
        self.assertIn("renderImportSelection();", loop)
        self.assertNotIn("selectedImportFiles = [];", loop)

    def test_launcher_avoids_an_already_running_old_server_and_marks_version(self):
        root = Path(__file__).parents[1]
        batch = (root / "start.bat").read_text(encoding="utf-8")
        powershell = (root / "start.ps1").read_text(encoding="utf-8")
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        backend = (root / "examenverwerker" / "main.py").read_text(encoding="utf-8")
        self.assertIn("APP_PORT", batch)
        self.assertIn("TcpListener", batch)
        self.assertIn("CandidatePort", powershell)
        self.assertIn("versie 0.18.6", html)
        self.assertIn("app.js?v=0.18.6", html)
        self.assertIn("Cache-Control", backend)


    def test_metadata_stage_offers_document_removal_and_refreshes_workspace(self):
        js = APP_JS.read_text(encoding="utf-8")
        self.assertIn('data-remove-document', js)
        self.assertIn("method:'DELETE'", js)
        self.assertIn("await openWorkspace(state.examId);", js)
        self.assertIn("exam.documents.length <= 1", js)

    def test_backend_document_removal_endpoint_has_safety_guards(self):
        backend = (ROOT / "examenverwerker" / "main.py").read_text(encoding="utf-8")
        storage = (ROOT / "examenverwerker" / "storage.py").read_text(encoding="utf-8")
        self.assertIn('@app.delete("/api/exams/{exam_id}/documents/{document_id}")', backend)
        self.assertIn('if exam.get("confirmed")', backend)
        self.assertIn('len(exam.get("documents", [])) <= 1', backend)
        self.assertIn('def remove_document(self, exam_id: str, document_id: int)', storage)

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

    def test_fragment_review_hides_question_cards_and_preserves_scroll(self):
        js = APP_JS.read_text(encoding="utf-8")
        self.assertNotIn('class="context-group-questions"', js)
        self.assertIn("preservedImageScrollTop = imageScroll.scrollTop", js)
        self.assertIn("imageScroll.scrollTop = preservedImageScrollTop", js)
        self.assertIn("saveTimer = setTimeout(() => persistSelections().catch(() => {}), 90);")

    def test_fragment_review_displays_learning_counts(self):
        js = APP_JS.read_text(encoding="utf-8")
        self.assertIn("/fragment-learning-status", js)
        self.assertIn("fragmentLearningStatus", js)
        self.assertIn("minimaal 5 voorbeelden per kenmerk", js)
