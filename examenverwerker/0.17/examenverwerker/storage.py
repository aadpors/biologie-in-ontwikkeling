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
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def resolve_shared_data_root(version_root: Path) -> Path:
    """Gebruik één gegevensmap voor alle versie-mappen van de applicatie.

    Iedere versie blijft afzonderlijk uitvoerbaar, maar examens horen niet
    opnieuw geïmporteerd te hoeven worden wanneer de gebruiker een nieuwe
    versie start. Daarom staat de gedeelde opslag één niveau boven de
    versiemap. Als daar nog geen opslag bestaat, wordt de bestaande 0.13-data
    één keer volledig gekopieerd. De oude map blijft onaangeroerd als
    terugvalkopie; bron-PDF's en SQLite-bestand gaan dus niet verloren.
    """
    shared_root = version_root.parent / "data"
    legacy_root = version_root.parent / "0.13" / "data"

    if not shared_root.exists() and legacy_root.is_dir():
        shared_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(legacy_root, shared_root)

    return shared_root.resolve()


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
                CREATE TABLE IF NOT EXISTS publication_versions (
                    exam_id TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    published_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    PRIMARY KEY (exam_id, version)
                );
                CREATE TABLE IF NOT EXISTS steps (
                    exam_id TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    step_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (exam_id, step_key)
                );
                -- Bewaar de laatst goedgekeurde momentopname wanneer een stap
                -- opnieuw wordt geopend. Pas bij de nieuwe afronding vergelijken
                -- we de definitieve inhoud en bepalen we of vervolgstappen echt
                -- opnieuw gecontroleerd moeten worden.
                CREATE TABLE IF NOT EXISTS step_reopen_baselines (
                    exam_id TEXT NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    step_key TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
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

    def find_exam_by_document_hashes(self, hashes: list[str]):
        """Zoek een eerder examen met exact dezelfde verzameling bron-PDF's.

        Bestandsnamen zijn niet betrouwbaar als unieke sleutel: dezelfde
        documenten kunnen later onder andere namen worden aangeboden.
        Daarom vergelijken we de SHA-256-hashes als een verzameling, zodat
        ook een andere volgorde van uploaden als hetzelfde examen geldt.
        """
        requested = sorted(set(hashes))
        if not requested:
            return None
        with self.connection() as db:
            exams = db.execute("SELECT id,title FROM exams ORDER BY created_at DESC").fetchall()
            for exam in exams:
                rows = db.execute(
                    "SELECT sha256 FROM documents WHERE exam_id=?", (exam["id"],)
                ).fetchall()
                stored = sorted(row["sha256"] for row in rows)
                if stored and stored == requested:
                    return {"id": exam["id"], "title": exam["title"]}
        return None

    def delete_exam(self, exam_id: str):
        """Verwijder de databasegegevens van één examen in een transactie.

        De bijbehorende bron- en afgeleide bestanden worden door de API-laag
        verwijderd nadat deze databasebewerking is geslaagd.
        """
        with self.connection() as db:
            db.execute("DELETE FROM exams WHERE id=?", (exam_id,))

    def reopen_metadata(self, exam_id: str, metadata: dict[str, Any]):
        """Open metadata als concept en bewaar de goedgekeurde nulmeting.

        Afhankelijke stappen worden nog niet ongeldig verklaard. Dat gebeurt
        pas wanneer de docent de gewijzigde metadata daadwerkelijk bevestigt.
        Bij een identieke bevestiging blijft alle vervolggoedkeuring behouden.
        """
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO step_reopen_baselines(exam_id,step_key,evidence_json) "
                "VALUES (?,?,?)",
                (exam_id, "metadata", json.dumps(metadata, ensure_ascii=False)),
            )
            db.execute("UPDATE exams SET confirmed=0 WHERE id=?", (exam_id,))
            db.execute("DELETE FROM steps WHERE exam_id=? AND step_key='metadata'", (exam_id,))
            db.execute(
                "INSERT INTO steps(exam_id,step_key,status,evidence_json,updated_at) "
                "VALUES (?,?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(exam_id,step_key) DO UPDATE SET status='pending', "
                "evidence_json=excluded.evidence_json, updated_at=CURRENT_TIMESTAMP",
                (exam_id, "metadata_draft", "pending", json.dumps(metadata, ensure_ascii=False)),
            )

    def reopen_step(self, exam_id: str, step_key: str, evidence: dict[str, Any]):
        """Open een stap zonder vervolggoedkeuringen voortijdig te verliezen.

        De bestaande evidence wordt zowel als bewerkbaar concept als in een
        aparte baseline opgeslagen. Bij de nieuwe afronding kan zo exact
        worden vastgesteld of de inhoud werkelijk veranderd is.
        """
        serialised = json.dumps(evidence, ensure_ascii=False)
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO step_reopen_baselines(exam_id,step_key,evidence_json) "
                "VALUES (?,?,?)",
                (exam_id, step_key, serialised),
            )
            db.execute(
                "INSERT INTO steps(exam_id,step_key,status,evidence_json,updated_at) "
                "VALUES (?,?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(exam_id,step_key) DO UPDATE SET "
                "status='pending', evidence_json=excluded.evidence_json, updated_at=CURRENT_TIMESTAMP",
                (exam_id, step_key, "pending", serialised),
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

    def confirm_metadata(self, exam_id: str, metadata: dict) -> bool:
        """Bevestig metadata en geef terug of de goedgekeurde inhoud veranderde."""
        serialised = json.dumps(metadata, ensure_ascii=False)
        with self.connection() as db:
            baseline_row = db.execute(
                "SELECT evidence_json FROM step_reopen_baselines "
                "WHERE exam_id=? AND step_key='metadata'",
                (exam_id,),
            ).fetchone()
            changed = bool(
                baseline_row
                and json.loads(baseline_row["evidence_json"]) != metadata
            )
            db.execute("UPDATE exams SET metadata_json=?, confirmed=1 WHERE id=?",
                       (serialised, exam_id))
            db.execute("INSERT OR REPLACE INTO steps(exam_id,step_key,status,evidence_json,updated_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                       (exam_id, "metadata", "complete", json.dumps({"confirmed": True})))
            db.execute(
                "DELETE FROM step_reopen_baselines WHERE exam_id=? AND step_key='metadata'",
                (exam_id,),
            )
            return changed

    def complete_step(self, exam_id: str, step_key: str, evidence: dict) -> bool:
        """Rond een stap af en vergelijk met de laatst goedgekeurde momentopname.

        De retourwaarde is True als de inhoud sinds het heropenen veranderde.
        De API-laag gebruikt dat signaal om uitsluitend dan afhankelijke
        goedkeuringen ongeldig te verklaren.
        """
        serialised = json.dumps(evidence, ensure_ascii=False)
        with self.connection() as db:
            baseline_row = db.execute(
                "SELECT evidence_json FROM step_reopen_baselines "
                "WHERE exam_id=? AND step_key=?",
                (exam_id, step_key),
            ).fetchone()
            changed = bool(
                baseline_row
                and json.loads(baseline_row["evidence_json"]) != evidence
            )
            db.execute(
                "INSERT OR REPLACE INTO steps(exam_id,step_key,status,evidence_json,updated_at) "
                "VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                (exam_id, step_key, "complete", serialised),
            )
            db.execute(
                "DELETE FROM step_reopen_baselines WHERE exam_id=? AND step_key=?",
                (exam_id, step_key),
            )
            return changed


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

    def save_step_draft_preserving_identical_complete(
        self,
        exam_id: str,
        step_key: str,
        evidence: dict[str, Any],
        *,
        identity_fields: tuple[str, ...],
    ) -> bool:
        """Bewaar een conceptreview zonder een identieke goedkeuring terug te draaien.

        Een browser kan vlak vóór het afronden nog een autosave starten. Die
        HTTP-aanvraag kan pas ná de expliciete afrondactie in de database
        aankomen. Een controle buiten de transactie is dan onvoldoende: de
        autosave kan eerst 'pending' lezen en daarna alsnog de status
        'complete' overschrijven.

        BEGIN IMMEDIATE vergrendelt de SQLite-schrijfrij vóórdat de bestaande
        status wordt gelezen. Daardoor geldt een vaste volgorde:
        - komt de autosave eerst, dan kan de afrondactie daarna 'complete' zetten;
        - komt de afrondactie eerst, dan ziet de autosave de complete rij en
          behoudt zij die goedkeuring wanneer de inhoudelijke velden identiek zijn.

        De methode retourneert True wanneer een concept is opgeslagen en False
        wanneer een identieke, reeds goedgekeurde versie ongewijzigd bleef.
        """
        serialised = json.dumps(evidence, ensure_ascii=False)
        with self.connection() as db:
            # Neem vóór de SELECT de schrijflock; anders kunnen twee requests
            # allebei een oude status lezen en elkaar alsnog overschrijven.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status, evidence_json FROM steps WHERE exam_id=? AND step_key=?",
                (exam_id, step_key),
            ).fetchone()

            if row and row["status"] == "complete":
                approved = json.loads(row["evidence_json"])
                if all(approved.get(field) == evidence.get(field) for field in identity_fields):
                    return False

            db.execute(
                "INSERT INTO steps(exam_id,step_key,status,evidence_json,updated_at) "
                "VALUES (?,?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(exam_id,step_key) DO UPDATE SET "
                "status='pending', evidence_json=excluded.evidence_json, updated_at=CURRENT_TIMESTAMP",
                (exam_id, step_key, "pending", serialised),
            )
            return True

    def publish_exam(self, exam_id: str):
        """Maak een onveranderbare publicatieversie en markeer deze actueel.

        Elke publicatie krijgt een oplopend versienummer en een volledige
        momentopname van metadata, bronbestanden (hashes) en workflowbewijs.
        De vorige publicatie wordt nooit overschreven. Dit vormt later ook
        een betrouwbare set referentievoorbeelden voor het leermechanisme.
        """
        with self.connection() as db:
            exam = db.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
            if not exam:
                raise ValueError("Examen niet gevonden.")
            documents = [dict(row) for row in db.execute(
                "SELECT * FROM documents WHERE exam_id=? ORDER BY id", (exam_id,)
            ).fetchall()]
            steps = [dict(row) for row in db.execute(
                "SELECT * FROM steps WHERE exam_id=? ORDER BY step_key", (exam_id,)
            ).fetchall()]
            versions = db.execute(
                "SELECT COALESCE(MAX(version),0) AS latest FROM publication_versions WHERE exam_id=?",
                (exam_id,)
            ).fetchone()
            version = int(versions["latest"]) + 1
            snapshot = {
                "exam": dict(exam),
                "documents": documents,
                "steps": [{**step, "evidence": json.loads(step["evidence_json"])}
                          for step in steps],
                "version": version,
            }
            db.execute(
                "INSERT INTO publication_versions(exam_id,version,published_at,snapshot_json) "
                "VALUES (?,?,CURRENT_TIMESTAMP,?)",
                (exam_id, version, json.dumps(snapshot, ensure_ascii=False)),
            )
            db.execute("UPDATE exams SET published=1, published_at=CURRENT_TIMESTAMP WHERE id=?", (exam_id,))
            db.execute(
                "INSERT OR REPLACE INTO steps(exam_id,step_key,status,evidence_json,updated_at) "
                "VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                (exam_id, "publicatie", "complete", json.dumps({"published": True, "version": version})),
            )

    def publication_versions(self, exam_id: str):
        """Geef de metadata van eerdere publicaties terug, zonder de snapshots te wijzigen."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT version,published_at,snapshot_json FROM publication_versions "
                "WHERE exam_id=? ORDER BY version DESC", (exam_id,)
            ).fetchall()
        return [{"version": row["version"], "published_at": row["published_at"],
                 "snapshot": json.loads(row["snapshot_json"])} for row in rows]

    def invalidate_steps(self, exam_id: str, keys: list[str]):
        """Markeer afhankelijke stappen als opnieuw te controleren, maar bewaar hun werk.

        Een wijziging in een eerdere workflowstap maakt latere goedkeuringen
        ongeldig, maar maakt de opgeslagen correcties en selecties niet
        waardeloos. Bewaar daarom evidence_json als concept en wijzig alleen
        de status. De volgende stap kan de bestaande invoer opnieuw tonen,
        zodat de gebruiker alleen hoeft aan te passen wat werkelijk veranderd is.

        Publicatiestatus wordt teruggezet wanneer de publicatiestap zelf in de
        invalidatieset zit. Een eerder gepubliceerde versie mag na een wijziging
        nooit als actueel gepubliceerd blijven gelden.
        """
        unique_keys = list(dict.fromkeys(keys))
        if not unique_keys:
            return
        with self.connection() as db:
            db.executemany(
                "UPDATE steps SET status='pending', updated_at=CURRENT_TIMESTAMP "
                "WHERE exam_id=? AND step_key=?",
                [(exam_id, key) for key in unique_keys],
            )
            if "publicatie" in unique_keys:
                db.execute(
                    "UPDATE exams SET published=0, published_at=NULL WHERE id=?",
                    (exam_id,),
                )
