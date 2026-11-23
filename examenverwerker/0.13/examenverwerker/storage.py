"""Persistente opslag voor examens, documenten en workflowstatus.

SQLite is hier bewust gekozen: de app kan lokaal draaien zonder aparte
serverdatabase. De opslaglaag is klein gehouden, maar gebruikt transacties
voor wijzigingen die meerdere tabellen raken. PDF-bestanden zelf staan als
ongewijzigde bronbestanden in een map per examen; de database bewaart alleen
hun relatieve pad en controlehash.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "examenverwerker.sqlite3"
        self._initialise()

    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def connection(self):
        """Beheer commit en sluiten expliciet; sqlite-contexten sluiten niet zelf."""
        db = self.connect()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialise(self):
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS exams (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    published INTEGER NOT NULL DEFAULT 0,
                    published_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exam_id TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    page_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS steps (
                    exam_id TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    step_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (exam_id, step_key)
                );
            """)
            # SQLite CREATE TABLE IF NOT EXISTS past een bestaande database
            # niet aan. Deze migratie voegt publicatiestatus daarom alleen toe
            # wanneer de kolommen nog ontbreken; eerdere examens blijven intact.
            columns = {row[1] for row in db.execute("PRAGMA table_info(exams)").fetchall()}
            if "published" not in columns:
                db.execute("ALTER TABLE exams ADD COLUMN published INTEGER NOT NULL DEFAULT 0")
            if "published_at" not in columns:
                db.execute("ALTER TABLE exams ADD COLUMN published_at TEXT")

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def create_exam(self, exam_id: str, title: str, documents: list[dict[str, Any]]):
        with self.connection() as db:
            db.execute("INSERT INTO exams(id,title) VALUES (?,?)", (exam_id, title))
            for document in documents:
                db.execute(
                    "INSERT INTO documents(exam_id,filename,relative_path,sha256,metadata_json,page_count) VALUES (?,?,?,?,?,?)",
                    (exam_id, document["filename"], document["relative_path"], document["sha256"],
                     json.dumps(document["metadata"], ensure_ascii=False), document["page_count"]),
                )

    def get_exam(self, exam_id: str):
        with self.connection() as db:
            exam = db.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
            if not exam:
                return None
            docs = db.execute("SELECT * FROM documents WHERE exam_id=? ORDER BY id", (exam_id,)).fetchall()
            steps = db.execute("SELECT * FROM steps WHERE exam_id=?", (exam_id,)).fetchall()
        return {
            **dict(exam),
            "metadata": json.loads(exam["metadata_json"]),
            "documents": [{**dict(row), "metadata": json.loads(row["metadata_json"])} for row in docs],
            "steps": {row["step_key"]: {"status": row["status"], "evidence": json.loads(row["evidence_json"])} for row in steps},
        }

    def list_exams(self):
        with self.connection() as db:
            rows = db.execute("SELECT id,title,confirmed,published,published_at,created_at FROM exams ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def confirm_metadata(self, exam_id: str, metadata: dict):
        with self.connection() as db:
            db.execute("UPDATE exams SET metadata_json=?, confirmed=1 WHERE id=?",
                       (json.dumps(metadata, ensure_ascii=False), exam_id))
            db.execute("INSERT OR REPLACE INTO steps(exam_id,step_key,status,evidence_json,updated_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                       (exam_id, "metadata", "complete", json.dumps({"confirmed": True})))

    def complete_step(self, exam_id: str, step_key: str, evidence: dict):
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO steps(exam_id,step_key,status,evidence_json,updated_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                       (exam_id, step_key, "complete", json.dumps(evidence, ensure_ascii=False)))


    def save_step_draft(self, exam_id: str, step_key: str, evidence: dict[str, Any]):
        """Bewaar tussentijdse reviewgegevens zonder de stap goed te keuren.

        Een docent kan een grote PDF-review in meerdere sessies uitvoeren.
        Daarom bewaren we de kandidaatbeslissingen direct, maar blijft de
        workflowstatus ``pending`` totdat de expliciete afrondactie plaatsvindt.
        Bestaande volledige goedkeuring wordt bij een nieuwe conceptreview
        verwijderd: gewijzigde inhoud mag nooit op oude goedkeuring steunen.
        """
        with self.connection() as db:
            db.execute(
                "INSERT INTO steps(exam_id,step_key,status,evidence_json,updated_at) "
                "VALUES (?,?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(exam_id,step_key) DO UPDATE SET "
                "status='pending', evidence_json=excluded.evidence_json, updated_at=CURRENT_TIMESTAMP",
                (exam_id, step_key, "pending", json.dumps(evidence, ensure_ascii=False)),
            )

    def publish_exam(self, exam_id: str):
        """Publicatiestatus en workflowbewijs in één transactie vastleggen.

        De API controleert vóór deze methode of de integrale eindcontrole is
        afgerond. Door beide wijzigingen in dezelfde SQLite-transactie uit te
        voeren kan een examen niet wel gepubliceerd zijn maar nog als
        ongepubliceerd in de workflow staan (of andersom).
        """
        with self.connection() as db:
            db.execute("UPDATE exams SET published=1, published_at=CURRENT_TIMESTAMP WHERE id=?", (exam_id,))
            db.execute(
                "INSERT OR REPLACE INTO steps(exam_id,step_key,status,evidence_json,updated_at) "
                "VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                (exam_id, "publicatie", "complete", json.dumps({"published": True})),
            )

    def invalidate_steps(self, exam_id: str, keys: list[str]):
        with self.connection() as db:
            db.executemany("DELETE FROM steps WHERE exam_id=? AND step_key=?", [(exam_id, key) for key in keys])
