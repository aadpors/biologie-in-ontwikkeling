"""Static regression checks for the isolated v2 preview page."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "examenoefenen-v2-preview.html"


class PreviewPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")
        scripts = re.findall(r"<script>(.*?)</script>", cls.html, flags=re.S)
        if len(scripts) != 1:
            raise AssertionError(f"Expected one inline application script, found {len(scripts)}")
        cls.script = scripts[0]

    def test_page_is_explicitly_a_preview(self):
        self.assertIn("Afgeschermde ontwikkelversie", self.html)
        self.assertIn("exam-data/claude-2024-2026", self.html)
        self.assertNotIn('src="examenoefenen.html"', self.html)

    def test_all_twelve_exam_ids_are_configured(self):
        for level in ("havo", "vwo"):
            for year in (2024, 2025, 2026):
                for period in (1, 2):
                    self.assertIn(f"{level}-{year}-t{period}", self.script)

    def test_no_open_question_is_automatically_graded(self):
        self.assertIn('q.type==="mcq"', self.script)
        self.assertIn("ad.correct_answer", self.script)
        self.assertIn('q.type==="open"', self.script)
        self.assertIn("Mijn score", self.script)

    def test_javascript_syntax(self):
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as handle:
            handle.write(self.script)
            handle.flush()
            subprocess.run(["node", "--check", handle.name], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
