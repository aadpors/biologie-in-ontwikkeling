import inspect
import unittest

from app import ExamApp


class ExamWindowSeparationTests(unittest.TestCase):
    def test_main_window_is_library_only(self):
        source = inspect.getsource(ExamApp._build)
        self.assertIn("EXAMENBIBLIOTHEEK", source)
        self.assertIn("library_table", source)
        self.assertNotIn("candidate_tree", source)
        self.assertNotIn("pdf_canvas", source)
        self.assertNotIn("VRAAGCONTROLE", source)

    def test_processing_workspace_has_its_own_builder(self):
        source = inspect.getsource(ExamApp._build_workspace)
        self.assertIn("candidate_tree", source)
        self.assertIn("pdf_canvas", source)
        self.assertIn("self.root.after", source)

    def test_opening_exam_creates_separate_workspace(self):
        source = inspect.getsource(ExamApp._launch_workspace)
        self.assertIn("tk.Toplevel(self.root)", source)
        self.assertIn("workspace._build_workspace()", source)
        self.assertIn("workspace.save_project()", source)

    def test_library_open_action_delegates_to_workspace(self):
        source = inspect.getsource(ExamApp.open_project)
        self.assertIn("self._launch_workspace(folder)", source)

    def test_import_opens_first_exam_in_workspace(self):
        source = inspect.getsource(ExamApp.import_year_set)
        self.assertIn("self._launch_workspace(created[0])", source)


if __name__ == "__main__":
    unittest.main()
