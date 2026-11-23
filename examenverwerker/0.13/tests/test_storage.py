"""Opslagmigraties en publicatiestatus."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from examenverwerker.storage import Store


class StorageTests(unittest.TestCase):
    def test_existing_database_gets_publication_columns_without_data_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            connection = sqlite3.connect(root / "examenverwerker.sqlite3")
            connection.execute("CREATE TABLE exams (id TEXT PRIMARY KEY, title TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', confirmed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            connection.execute("INSERT INTO exams (id,title) VALUES ('abc123','Oud examen')")
            connection.commit()
            connection.close()
            store = Store(root)
            exam = store.get_exam("abc123")
            self.assertEqual(exam["title"], "Oud examen")
            self.assertEqual(exam["published"], 0)
            connection = store.connect()
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(exams)")}
            finally:
                connection.close()
            self.assertIn("published_at", columns)

    def test_publish_exam_persists_status_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            store.create_exam("012345abcdef", "Biologie vwo 2026 tv2", [])
            store.publish_exam("012345abcdef")
            exam = store.get_exam("012345abcdef")
            self.assertEqual(exam["published"], 1)
            self.assertIsNotNone(exam["published_at"])
            self.assertEqual(exam["steps"]["publicatie"]["status"], "complete")
