"""Unit tests for the non-destructive Claude exam dataset importer."""
import sys
import unittest
from pathlib import Path

# Load the script as a module without requiring scripts/ to be a Python package.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
from import_claude_exam_dataset import DatasetError, safe_archive_path


class ImportSafetyTests(unittest.TestCase):
    def test_rejects_parent_traversal(self):
        with self.assertRaises(DatasetError):
            safe_archive_path("../outside.txt")

    def test_rejects_absolute_paths(self):
        with self.assertRaises(DatasetError):
            safe_archive_path("/etc/passwd")

    def test_rejects_windows_drive_paths(self):
        with self.assertRaises(DatasetError):
            safe_archive_path("C:/outside.txt")

    def test_accepts_normal_posix_path(self):
        self.assertEqual(
            safe_archive_path("snippets/havo-2024-t1/q01.png").as_posix(),
            "snippets/havo-2024-t1/q01.png",
        )


if __name__ == "__main__":
    unittest.main()
