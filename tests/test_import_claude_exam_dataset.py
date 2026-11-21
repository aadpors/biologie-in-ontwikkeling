"""Unit tests for the non-destructive Claude exam dataset importer."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from import_claude_exam_dataset import DatasetError, safe_archive_path


class ImportSafetyTests(unittest.TestCase):
    def test_rejects_parent_traversal(self):
        with self.assertRaises(DatasetError):
            safe_archive_path("../outside.txt")

    def test_rejects_absolute_paths(self):
        with self.assertRaises(DatasetError):
            safe_archive_path("/etc/passwd")

    def test_accepts_normal_posix_path(self):
        self.assertEqual(safe_archive_path("snippets/havo-2024-t1/q01.png").as_posix(),
                         "snippets/havo-2024-t1/q01.png")


if __name__ == "__main__":
    unittest.main()
