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


if __name__ == "__main__":
    unittest.main()
