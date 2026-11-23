"""Opslagmigraties en publicatiestatus."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from examenverwerker.storage import Store, resolve_shared_data_root


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

    def test_new_version_migrates_existing_013_data_once(self):
        """Een nieuwe versie neemt de bestaande examens en bronnen mee."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "examenverwerker"
            legacy = base / "0.13" / "data"
            current_version = base / "0.14"
            legacy.mkdir(parents=True)
            (legacy / "examenverwerker.sqlite3").write_bytes(b"sqlite-database")
            (legacy / "exams").mkdir()
            (legacy / "exams" / "source.pdf").write_bytes(b"original-pdf")

            shared = resolve_shared_data_root(current_version)

            self.assertEqual(shared, base / "data")
            self.assertEqual((shared / "examenverwerker.sqlite3").read_bytes(), b"sqlite-database")
            self.assertEqual((shared / "exams" / "source.pdf").read_bytes(), b"original-pdf")
            # De oude versie blijft intact als terugvalkopie.
            self.assertTrue((legacy / "examenverwerker.sqlite3").is_file())

    def test_existing_shared_data_is_never_overwritten_by_legacy_copy(self):
        """Latere starts mogen nieuwere gedeelde data niet terugzetten."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "examenverwerker"
            legacy = base / "0.13" / "data"
            shared = base / "data"
            legacy.mkdir(parents=True)
            shared.mkdir(parents=True)
            (legacy / "marker.txt").write_text("oud", encoding="utf-8")
            (shared / "marker.txt").write_text("nieuw", encoding="utf-8")

            resolved = resolve_shared_data_root(base / "0.14")

            self.assertEqual((resolved / "marker.txt").read_text(encoding="utf-8"), "nieuw")

    def test_publish_exam_persists_status_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            store.create_exam("012345abcdef", "Biologie vwo 2026 tv2", [])
            store.publish_exam("012345abcdef")
            exam = store.get_exam("012345abcdef")
            self.assertEqual(exam["published"], 1)
            self.assertIsNotNone(exam["published_at"])
            self.assertEqual(exam["steps"]["publicatie"]["status"], "complete")
