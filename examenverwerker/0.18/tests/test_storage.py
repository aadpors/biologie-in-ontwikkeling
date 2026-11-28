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

    def test_reopened_step_invalidates_dependents_only_after_a_real_change(self):
        """Ongewijzigd opnieuw afronden behoudt downstream-goedkeuringen."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            store.create_exam("012345abcdef", "Biologie vwo 2026 tv2", [])
            approved = {"candidates":[{"question_number":1,"accepted":True}]}
            downstream = {"selections":[{"question_number":1,"top":100,"bottom":300}]}
            store.complete_step("012345abcdef", "opgaven_starts", approved)
            store.complete_step("012345abcdef", "opgaven_fragments", downstream)

            store.reopen_step("012345abcdef", "opgaven_starts", approved)
            exam = store.get_exam("012345abcdef")
            self.assertEqual(exam["steps"]["opgaven_starts"]["status"], "pending")
            self.assertEqual(exam["steps"]["opgaven_fragments"]["status"], "complete")

            # Een identieke herbevestiging laat de downstream-status ongemoeid.
            changed = store.complete_step("012345abcdef", "opgaven_starts", approved)
            self.assertFalse(changed)
            self.assertEqual(
                store.get_exam("012345abcdef")["steps"]["opgaven_fragments"]["status"],
                "complete",
            )

            # Een inhoudelijke wijziging levert een expliciet signaal voor de API.
            store.reopen_step("012345abcdef", "opgaven_starts", approved)
            revised = {"candidates":[{"question_number":1,"accepted":True},
                                     {"question_number":2,"accepted":True}]}
            changed = store.complete_step("012345abcdef", "opgaven_starts", revised)
            self.assertTrue(changed)
            store.invalidate_steps("012345abcdef", ["opgaven_fragments"])
            exam = store.get_exam("012345abcdef")
            self.assertEqual(exam["steps"]["opgaven_fragments"]["status"], "pending")
            self.assertEqual(exam["steps"]["opgaven_fragments"]["evidence"], downstream)

    def test_reopened_metadata_compares_against_approved_values(self):
        """Metadata wordt alleen als gewijzigd gezien als de bevestigde waarden afwijken."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            store.create_exam("012345abcdef", "Biologie vwo 2026 tv2", [])
            original = {
                "subject":"biologie", "level":"vwo", "year":2026, "period":2,
                "document_types":{"exam.pdf":"correctievoorschrift"},
            }
            store.confirm_metadata("012345abcdef", original)
            store.reopen_metadata("012345abcdef", original)
            self.assertFalse(store.confirm_metadata("012345abcdef", original))

            store.reopen_metadata("012345abcdef", original)
            revised = {**original, "period":1}
            self.assertTrue(store.confirm_metadata("012345abcdef", revised))

    def test_invalidation_preserves_review_evidence_and_clears_publication(self):
        """Ongeldig bewijs blijft als concept beschikbaar voor gerichte hercontrole."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            store.create_exam("012345abcdef", "Biologie vwo 2026 tv2", [])
            evidence = {"selections":[{"question_number":28,"top":100,"bottom":300}]}
            store.complete_step("012345abcdef", "cv_fragments", evidence)
            store.publish_exam("012345abcdef")

            store.invalidate_steps("012345abcdef", ["cv_fragments", "antwoorden", "publicatie"])
            exam = store.get_exam("012345abcdef")

            self.assertEqual(exam["steps"]["cv_fragments"]["status"], "pending")
            self.assertEqual(exam["steps"]["cv_fragments"]["evidence"], evidence)
            self.assertEqual(exam["steps"]["publicatie"]["status"], "pending")
            self.assertEqual(exam["published"], 0)
            self.assertIsNone(exam["published_at"])
