from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from exporter import export_approved_records
from engine import analyze_pdf, detect_question_candidates, detect_cv_question_numbers, compare_question_numbering, learn_decision, render_page, render_crop, propose_question_regions, classify_document_role, infer_exam_metadata, question_pattern_key, suggest_from_learning, extract_candidate_text, detect_question_type, detect_context_references, match_correction_documents, match_exam_documents, build_question_record, render_composite_crops, review_checklist_errors, extract_region_text, pdf_page_count, pixel_rect_to_pdf_bbox
from structure import FRAGMENT_TYPES, make_page_span, make_fragment, append_page_span, make_exam_structure, validate_exam_structure, mark_structure_stale, fragments_for_question, make_cv_fragment, validate_cv_fragment, page_spans_to_segments, missing_question_regions
from batch_import import group_exam_documents, batch_document_warnings, validate_batch_documents

APP_VERSION = "0.8.0"
PROJECT_FILE = "project.json"

def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pdf(path: Path):
    try:
        import pymupdf as fitz
    except ImportError as exc:
        raise RuntimeError("PDF-lezer ontbreekt. Start BUILD_PORTABLE.bat of installeer requirements.txt.") from exc
    doc = fitz.open(path)
    pages = []
    for index, page in enumerate(doc):
        text = page.get_text("text", sort=True)
        pages.append({"pagina": index + 1, "tekst": text, "tekens": len(text.strip()), "ocr_nodig": len(text.strip()) < 20})
    meta = doc.metadata or {}
    result = {"pagina_aantal": len(doc), "metadata": meta, "pagina_tekst": pages}
    doc.close()
    return result


class ExamApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Biologie Examenverwerker")
        self.root.geometry("1040x700")
        self.root.minsize(820, 560)
        self.project_dir = None
        self.data = None
        app_base=Path(sys.executable).parent if getattr(sys,"frozen",False) else Path(__file__).parent
        self.knowledge_dir=app_base/"kennisbank"
        self._style()
        self._build()
        self._welcome()

    def _style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground="#741d3b")
        style.configure("Sub.TLabel", font=("Segoe UI", 10), foreground="#52616b")
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=8)
        style.configure("Treeview", rowheight=30, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build(self):
        top = ttk.Frame(self.root, padding=(20, 16))
        top.pack(fill="x")
        ttk.Label(top, text="Biologie Examenverwerker", style="Title.TLabel").pack(anchor="w")
        ttk.Label(top, text="Van originele examen-PDF's naar gecontroleerde, publicatieklare vragen.", style="Sub.TLabel").pack(anchor="w", pady=(3, 0))
        bar = ttk.Frame(self.root, padding=(20, 4))
        bar.pack(fill="x")
        self.project_label = ttk.Label(bar, text="Geen project geopend", style="Sub.TLabel")
        self.project_label.pack(side="left", fill="x", expand=True)
        ttk.Button(bar, text="Nieuw examenproject", command=self.new_project, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(bar, text="Project openen", command=self.open_project).pack(side="left", padx=4)
        ttk.Button(bar, text="PDF's toevoegen", command=self.add_pdfs, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(bar, text="Jaarset importeren", command=self.import_year_set, style="Accent.TButton").pack(side="left", padx=4)

        body = ttk.Frame(self.root, padding=(20, 12))
        body.pack(fill="both", expand=True)
        self.status = ttk.Label(body, text="Begin met een nieuw examenproject of open een bestaand project.", style="Sub.TLabel")
        self.status.pack(anchor="w", pady=(0, 10))
        columns = ("name", "type", "pages", "confidence", "state")
        self.table = ttk.Treeview(body, columns=columns, show="headings")
        for col, title, width in [
            ("name", "Bestand", 360), ("type", "Herkend als", 170),
            ("pages", "Pagina's", 80), ("confidence", "Zekerheid", 100), ("state", "Status", 170)
        ]:
            self.table.heading(col, text=title)
            self.table.column(col, width=width, anchor="w" if col in ("name", "type", "state") else "center")
        self.table.pack(fill="both", expand=True)
        self.table.bind("<Double-1>", self.show_document)
        foot = ttk.Frame(body)
        foot.pack(fill="x", pady=(10, 0))
        ttk.Button(foot, text="Document bekijken", command=self.show_document).pack(side="left")
        ttk.Button(foot, text="Herkenning aanpassen", command=self.correct_type).pack(side="left", padx=6)
        ttk.Button(foot, text="Vraagstarts analyseren", command=self.analyze_questions, style="Accent.TButton").pack(side="left", padx=6)
        ttk.Button(foot, text="Examenstructuur bewerken", command=self.edit_exam_structure, style="Accent.TButton").pack(side="left", padx=6)
        ttk.Button(foot, text="Kandidaten bekijken", command=self.show_candidates).pack(side="left")
        ttk.Button(foot, text="Examengegevens controleren", command=self.edit_exam_metadata).pack(side="left", padx=6)
        ttk.Button(foot, text="Voortgang opslaan", command=self.save_project).pack(side="right")
        workflow=ttk.Frame(body); workflow.pack(fill="x",pady=(8,0))
        ttk.Button(workflow,text="Vraagrecords beoordelen en goedkeuren",command=self.show_records,style="Accent.TButton").pack(side="left")
        ttk.Button(workflow,text="Veilig exportpakket maken",command=self.export_project).pack(side="left",padx=8)
        self.log = tk.Text(body, height=6, wrap="word", font=("Consolas", 9), background="#f5f7f7", relief="flat")
        self.log.pack(fill="x", pady=(12, 0))
        self.log.configure(state="disabled")

    def _welcome(self):
        self._log("Welkom. Open een bestaand examenproject, of importeer in één keer een complete jaarset.")
        self._log("Bij jaarset-import groepeert de software PDF's automatisch op havo/vwo, jaar en tijdvak; je controleert eerst alle voorstellen.")

    def _error(self, context, exc):
        details=traceback.format_exc()
        if self.project_dir:
            log_dir=self.project_dir/"logs"
        else:
            base=Path(sys.executable).parent if getattr(sys,"frozen",False) else Path(__file__).parent
            log_dir=base/"logs"
        try:
            log_dir.mkdir(parents=True,exist_ok=True)
            stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
            (log_dir/f"fout-{stamp}.txt").write_text(context+"\n\n"+details,encoding="utf-8")
            self._log(f"{context}: niet gelukt. De details zijn veilig opgeslagen in de map logs.")
        except Exception:
            self._log(f"{context}: niet gelukt. Start het programma opnieuw en probeer het nogmaals.")

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def new_project(self):
        folder = filedialog.askdirectory(title="Kies of maak een map voor dit examenproject")
        if not folder:
            return
        base = Path(folder)
        name = simpledialog.askstring("Nieuw examen", "Geef het examen een herkenbare naam:", initialvalue=base.name)
        if not name:
            return
        self.project_dir = base / re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
        (self.project_dir / "bronnen").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "analyse").mkdir(exist_ok=True)
        (self.project_dir / "snippets").mkdir(exist_ok=True)
        self.data = {"schema": "biologie-examenproject-v1", "app_versie": APP_VERSION, "naam": name,
                     "aangemaakt": now(), "bijgewerkt": now(), "documenten": [], "beslissingen": [],
                     "publicatiestatus": "niet_vrijgegeven", "vraagkandidaten": []}
        self.save_project()
        self.refresh()
        self._log(f"Nieuw project aangemaakt: {self.project_dir}")

    def open_project(self):
        filename = filedialog.askopenfilename(title="Open projectbestand", filetypes=[("Examenproject", PROJECT_FILE), ("JSON", "*.json")])
        if not filename:
            return
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            if data.get("schema") != "biologie-examenproject-v1":
                raise ValueError("Dit is geen herkenbaar examenprojectbestand.")
            self.project_dir = Path(filename).parent
            self.data = data
            self.refresh()
            self._log(f"Project geopend: {self.project_dir}")
        except Exception as exc:
            self._error("Project openen",exc)
            messagebox.showerror("Project openen mislukt","Dit project kon niet worden geopend. Controleer of het projectbestand geldig is. Details staan in de map logs.")

    def import_year_set(self):
        """Import a complete year set without requiring pre-created exam projects."""
        files = filedialog.askopenfilenames(
            title="Selecteer alle examen-PDF's van het jaar (havo en vwo, alle tijdvakken)",
            filetypes=[("PDF-bestanden", "*.pdf")])
        if not files:
            return
        destination = filedialog.askdirectory(title="Kies de map waarin de gecontroleerde jaarset moet worden opgeslagen")
        if not destination:
            return

        documents = []
        seen_hashes = set()
        failures = []
        for source_name in files:
            source = Path(source_name)
            try:
                digest = sha256(source)
                if digest in seen_hashes:
                    self._log(f"Dubbel bestand overgeslagen: {source.name}")
                    continue
                seen_hashes.add(digest)
                extracted = extract_pdf(source)
                all_text = "\n".join(page["tekst"] for page in extracted["pagina_tekst"])
                role, role_confidence, role_signals = classify_document_role(source.name, all_text)
                identity = infer_exam_metadata(source.name, all_text)
                documents.append({
                    "id": digest[:16], "bestand": source.name, "source_path": str(source),
                    "opslagbestand": f"{digest[:12]}-{source.name}", "sha256": digest,
                    "type_voorstel": role, "type_zekerheid": role_confidence,
                    "herkenningssignalen": role_signals, "exam_metadata": identity,
                    "pagina_aantal": extracted["pagina_aantal"], "metadata": extracted["metadata"],
                    "pagina_zonder_tekst": [p["pagina"] for p in extracted["pagina_tekst"] if p.get("ocr_nodig")],
                    "ocr_status": "handmatige_ocr_controle_nodig" if any(p.get("ocr_nodig") for p in extracted["pagina_tekst"]) else "tekstlaag_aanwezig",
                    "_extracted": extracted,
                })
            except Exception as exc:
                failures.append(f"{source.name}: {exc}")

        if failures:
            messagebox.showerror("Jaarset niet volledig ingelezen",
                "Er ging iets mis bij het lezen van één of meer PDF's. Er is nog niets geïmporteerd:\n\n" + "\n".join(failures))
            return
        if not documents:
            messagebox.showinfo("Geen nieuwe PDF's", "Er zijn geen unieke PDF-bestanden geselecteerd.")
            return

        win = tk.Toplevel(self.root)
        win.title("Jaarset controleren en automatisch groeperen")
        win.geometry("1120x650")
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text=f"{len(documents)} unieke PDF's gevonden. Controleer niveau, jaar, tijdvak en documenttype. Er wordt nog niets verwerkt of verplaatst.",
                  padding=12, wraplength=1060).pack(anchor="w")
        columns = ("file", "role", "certainty", "meta_confidence", "level", "year", "period", "pages", "state")
        tree = ttk.Treeview(win, columns=columns, show="headings", selectmode="browse")
        headings = [
            ("file", "Bestand", 280), ("role", "Documenttype", 145), ("certainty", "Typezekerheid", 85),
            ("meta_confidence", "Metazekerheid", 85), ("level", "Niveau", 70), ("year", "Jaar", 60), ("period", "Tijdvak", 65),
            ("pages", "Pagina's", 65), ("state", "Controle", 170)]
        for col, title, width in headings:
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="w" if col in ("file", "role", "state") else "center")
        tree.pack(fill="both", expand=True, padx=12, pady=8)
        status = ttk.Label(win, text="", padding=(12, 4), wraplength=1060)
        status.pack(anchor="w")

        def identity_text(doc):
            meta = doc.get("exam_metadata") or {}
            return meta.get("level", ""), meta.get("year", ""), meta.get("period", "")

        def refresh_review():
            for item in tree.get_children():
                tree.delete(item)
            groups, unassigned = group_exam_documents(documents)
            for index, doc in enumerate(documents):
                meta = doc.get("exam_metadata") or {}
                uncertain = doc.get("type_zekerheid", 0) < 0.9 or (
                    meta.get("source") == "eerste_pdf_paginas" and meta.get("confidence", 0) < 0.9)
                state = "Handmatig controleren" if uncertain or not meta else "Voorstel controleren"
                if not meta:
                    state = "Metadata ontbreekt"
                tree.insert("", "end", iid=str(index), values=(
                    doc["bestand"], doc.get("type_voorstel", "onbekend"),
                    f"{doc.get('type_zekerheid', 0):.0%}",
                    f"{meta.get('confidence', 0):.0%}" if meta else "—", *identity_text(doc),
                    doc.get("pagina_aantal", 0), state))
            summary = []
            for key, items in groups.items():
                summary.append(f"{key[0].upper()} {key[1]} tijdvak {key[2]}: {len(items)} PDF's")
            if unassigned:
                summary.append(f"{len(unassigned)} PDF('s) zonder complete examenidentiteit")
            status.configure(text="Automatische groepen: " + ("; ".join(summary) if summary else "nog geen complete groepen"))

        def edit_selected():
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("Selecteer een PDF", "Selecteer eerst een PDF om de herkenning te controleren.", parent=win)
                return
            doc = documents[int(selection[0])]
            meta = doc.get("exam_metadata") or {}
            edit = tk.Toplevel(win)
            edit.title("Documentherkenning controleren")
            edit.transient(win)
            edit.grab_set()
            frame = ttk.Frame(edit, padding=16)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text=doc["bestand"], wraplength=430).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
            role = tk.StringVar(value=doc.get("type_voorstel", "onbekend"))
            level = tk.StringVar(value=meta.get("level", "Vwo"))
            year = tk.StringVar(value=str(meta.get("year", "")))
            period = tk.StringVar(value=str(meta.get("period", "1")))
            fields = [
                (1, "Documenttype", role, ttk.Combobox(frame, textvariable=role, values=["opgaven", "correctievoorschrift", "aanvulling", "uitwerkbijlage", "onbekend"], state="readonly", width=27)),
                (2, "Niveau", level, ttk.Combobox(frame, textvariable=level, values=["Havo", "Vwo"], state="readonly", width=27)),
                (3, "Jaar", year, ttk.Entry(frame, textvariable=year, width=30)),
                (4, "Tijdvak", period, ttk.Combobox(frame, textvariable=period, values=["1", "2", "3"], state="readonly", width=27)),
            ]
            for row, label, var, widget in fields:
                ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
                widget.grid(row=row, column=1, sticky="ew", pady=5)
            ttk.Label(frame, text="Controleer dit aan de hand van de PDF. De software koppelt uitsluitend documenten met exact hetzelfde niveau, jaar en tijdvak.",
                      wraplength=440).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 4))

            def save_edit():
                if role.get() not in {"opgaven", "correctievoorschrift", "aanvulling", "uitwerkbijlage"}:
                    messagebox.showerror("Documenttype ontbreekt", "Kies een geldig documenttype.", parent=edit)
                    return
                if level.get() not in {"Havo", "Vwo"} or not re.fullmatch(r"20\d{2}", year.get().strip()) or period.get() not in {"1", "2", "3"}:
                    messagebox.showerror("Examenidentiteit onvolledig", "Vul niveau, een viercijferig jaar en tijdvak 1, 2 of 3 in.", parent=edit)
                    return
                doc["type_voorstel"] = role.get()
                doc["type_zekerheid"] = 1.0
                doc["exam_metadata"] = {"level": level.get(), "year": year.get().strip(), "period": period.get(),
                                        "confidence": 1.0, "source": "handmatig_bevestigd"}
                doc["status"] = "handmatig_bevestigd"
                refresh_review()
                edit.destroy()

            buttons = ttk.Frame(frame)
            buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
            ttk.Button(buttons, text="Opslaan", command=save_edit).pack(side="right")
            ttk.Button(buttons, text="Annuleren", command=edit.destroy).pack(side="right", padx=8)
            frame.columnconfigure(1, weight=1)

        def confirm_import():
            errors = validate_batch_documents(documents)
            if errors:
                messagebox.showerror("Eerst herkenning corrigeren",
                    "De jaarset kan nog niet veilig worden geïmporteerd:\n\n" + "\n".join(errors[:20]), parent=win)
                return
            groups, unassigned = group_exam_documents(documents)
            if unassigned:
                messagebox.showerror("Onvolledige groepering", "Niet alle PDF's hebben een volledige examenidentiteit. Er wordt niets geïmporteerd.", parent=win)
                return
            warnings = []
            for key, items in groups.items():
                for warning in batch_document_warnings(items):
                    warnings.append(f"{key[0].upper()} {key[1]} tijdvak {key[2]}: {warning}")
            warning_text = "\n".join(warnings) if warnings else "Geen ontbrekende opgaven of CV's en geen dubbele hoofd-documenttypen gesignaleerd."
            summary_text = "\n".join(f"{key[0].upper()} {key[1]} tijdvak {key[2]}: {len(items)} PDF's" for key, items in groups.items())
            if not messagebox.askyesno("Jaarset definitief controleren",
                f"Er worden {len(groups)} examenprojecten aangemaakt in een nieuwe jaarsetmap.\n\n"
                + summary_text + "\n\nWaarschuwingen:\n" + warning_text
                + "\n\nAlle getoonde metadata en documenttypen zijn door jou gecontroleerd. Doorgaan?", parent=win):
                return
            years = sorted({key[1] for key in groups})
            batch_name = f"jaarset-{years[0]}" if len(years) == 1 else "jaarset-meerdere-jaren"
            target_root = Path(destination) / batch_name
            if target_root.exists():
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                target_root = Path(destination) / f"{batch_name}-{stamp}"
                suffix = 2
                while target_root.exists():
                    target_root = Path(destination) / f"{batch_name}-{stamp}-{suffix}"
                    suffix += 1
            created = []
            created_root = False
            try:
                target_root.mkdir(parents=True, exist_ok=False)
                created_root = True
                manifest = {"schema": "biologie-examenjaarset-v1", "aangemaakt": now(), "projecten": []}
                for key, items in sorted(groups.items()):
                    level_key, year_key, period_key = key
                    project_name = f"{level_key}-{year_key}-tijdvak-{period_key}"
                    project_dir = target_root / project_name
                    (project_dir / "bronnen").mkdir(parents=True)
                    (project_dir / "analyse").mkdir()
                    (project_dir / "snippets").mkdir()
                    confirmed_identity = {"level": "Havo" if level_key == "havo" else "Vwo",
                                          "year": year_key, "period": period_key,
                                          "confidence": 1.0, "source": "handmatig_bevestigd"}
                    project_docs = []
                    for doc in items:
                        source = Path(doc["source_path"])
                        target = project_dir / "bronnen" / doc["opslagbestand"]
                        shutil.copy2(source, target)
                        extracted = doc["_extracted"]
                        (project_dir / "analyse" / f"{doc['id']}.json").write_text(
                            json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")
                        clean_doc = {k: v for k, v in doc.items() if k not in {"source_path", "_extracted"}}
                        clean_doc["exam_metadata"] = dict(confirmed_identity)
                        clean_doc["status"] = "handmatig_bevestigd"
                        project_docs.append(clean_doc)
                    project_data = {
                        "schema": "biologie-examenproject-v1", "app_versie": APP_VERSION,
                        "naam": project_name, "aangemaakt": now(), "bijgewerkt": now(),
                        "exam_metadata": confirmed_identity, "documenten": project_docs,
                        "beslissingen": [], "publicatiestatus": "niet_vrijgegeven",
                        "vraagkandidaten": [], "vraagrecords": [],
                    }
                    (project_dir / PROJECT_FILE).write_text(json.dumps(project_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    created.append(project_dir)
                    manifest["projecten"].append({
                        "naam": project_name, "pad": project_name, "exam_metadata": confirmed_identity,
                        "documenten": [d["bestand"] for d in project_docs],
                        "waarschuwingen": batch_document_warnings(items),
                    })
                (target_root / "jaarset.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                if created_root:
                    shutil.rmtree(target_root, ignore_errors=True)
                messagebox.showerror("Jaarset importeren mislukt",
                    f"Er is een fout opgetreden. De onvolledige jaarsetmap is verwijderd; bestaande projecten zijn niet gewijzigd.\n\n{exc}", parent=win)
                return
            win.destroy()
            self.project_dir = None
            self.data = None
            self.project_label.configure(text=f"Jaarset geïmporteerd: {target_root}")
            for item in self.table.get_children():
                self.table.delete(item)
            self.status.configure(text=f"{len(created)} examenprojecten aangemaakt. Open een project om de inhoudelijke verwerking te starten.")
            self._log(f"Jaarset geïmporteerd: {target_root}")
            for project in created:
                self._log(f"  Project aangemaakt: {project.name}")
            messagebox.showinfo("Jaarset geïmporteerd",
                f"{len(created)} examenprojecten zijn aangemaakt in:\n{target_root}\n\nOpen daarna per examen het projectbestand project.json. De oorspronkelijke PDF's zijn ongewijzigd gekopieerd.")

        ttk.Button(win, text="Herkenning geselecteerde PDF aanpassen", command=edit_selected).pack(side="left", padx=12, pady=8)
        ttk.Button(win, text="Alle voorstellen controleren en jaarset importeren", command=confirm_import, style="Accent.TButton").pack(side="right", padx=12, pady=8)
        ttk.Button(win, text="Annuleren", command=win.destroy).pack(side="right", pady=8)
        refresh_review()
        self._log(f"Jaarset voorbereid voor controle: {len(documents)} unieke PDF's. Nog niets opgeslagen of verwerkt.")

    def add_pdfs(self):
        if not self.data:
            messagebox.showinfo("Eerst een project", "Maak eerst een nieuw examenproject of open een bestaand project.")
            return
        files = filedialog.askopenfilenames(title="Selecteer de examen-PDF's", filetypes=[("PDF-bestanden", "*.pdf")])
        if not files:
            return
        added = 0
        for source_name in files:
            source = Path(source_name)
            try:
                digest = sha256(source)
                if any(d.get("sha256") == digest for d in self.data["documenten"]):
                    self._log(f"Overgeslagen (exact duplicaat): {source.name}")
                    continue
                target = self.project_dir / "bronnen" / f"{digest[:12]}-{source.name}"
                shutil.copy2(source, target)
                extracted = extract_pdf(target)
                all_text = "\n".join(p["tekst"] for p in extracted["pagina_tekst"])
                kind, confidence, scores = classify_document_role(source.name, all_text)
                exam_meta = infer_exam_metadata(source.name, all_text) if kind in ("opgaven", "correctievoorschrift", "uitwerkbijlage", "aanvulling") else {}
                doc = {"id": digest[:16], "bestand": source.name, "opslagbestand": target.name,
                       "exam_metadata": exam_meta,
                       "sha256": digest, "type_voorstel": kind, "type_zekerheid": confidence,
                       "herkenningssignalen": scores, "status": "controle_nodig" if confidence < 0.9 else "herkend_nog_niet_goedgekeurd",
                       "toegevoegd": now(), "pagina_aantal": extracted["pagina_aantal"],
                       "metadata": extracted["metadata"],
                       "pagina_zonder_tekst": [p["pagina"] for p in extracted["pagina_tekst"] if p.get("ocr_nodig")],
                       "ocr_status": "handmatige_ocr_controle_nodig" if any(p.get("ocr_nodig") for p in extracted["pagina_tekst"]) else "tekstlaag_aanwezig"}
                confirmed_identity=self.data.get("exam_metadata", {})
                if confirmed_identity.get("source") == "handmatig_bevestigd" and kind in ("opgaven", "correctievoorschrift", "aanvulling", "uitwerkbijlage"):
                    doc["exam_metadata"]=dict(confirmed_identity)
                (self.project_dir / "analyse" / f"{digest[:16]}.json").write_text(
                    json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")
                self.data["documenten"].append(doc)
                if exam_meta and not self.data.get("exam_metadata"):
                    self.data["exam_metadata"]=exam_meta
                    self._log(f"Examenmetadata voorgesteld vanuit bestandsnaam: {exam_meta['level']} {exam_meta['year']} tijdvak {exam_meta['period']}.")
                self._log(f"{source.name}: {kind} voorgesteld ({confidence:.0%}), {extracted['pagina_aantal']} pagina's. OCR-controle op pagina's: {doc['pagina_zonder_tekst'] or 'niet nodig'}.")
                added += 1
            except Exception as exc:
                self._error(f"PDF toevoegen ({source.name})",exc)
        self.save_project()
        self.refresh()
        self.status.configure(text=f"{added} PDF('s) toegevoegd. Controleer de voorgestelde documenttypen.")

    def edit_exam_metadata(self):
        if not self.data:
            messagebox.showinfo("Eerst een project","Open eerst een examenproject.")
            return
        current=self.data.get("exam_metadata",{})
        win=tk.Toplevel(self.root); win.title("Examengegevens controleren"); win.transient(self.root); win.grab_set()
        frame=ttk.Frame(win,padding=18); frame.pack(fill="both",expand=True)
        ttk.Label(frame,text="Controleer de gegevens die uit de bestandsnaam zijn afgeleid.",wraplength=420).grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,12))
        ttk.Label(frame,text="Niveau").grid(row=1,column=0,sticky="w",pady=5)
        level=tk.StringVar(value=current.get("level","Havo"))
        ttk.Combobox(frame,textvariable=level,values=["Havo","Vwo"],state="readonly",width=18).grid(row=1,column=1,sticky="ew",pady=5)
        ttk.Label(frame,text="Jaar").grid(row=2,column=0,sticky="w",pady=5)
        year=tk.StringVar(value=str(current.get("year","2026")))
        ttk.Entry(frame,textvariable=year,width=20).grid(row=2,column=1,sticky="ew",pady=5)
        ttk.Label(frame,text="Tijdvak").grid(row=3,column=0,sticky="w",pady=5)
        period=tk.StringVar(value=str(current.get("period","1")))
        ttk.Combobox(frame,textvariable=period,values=["1","2","3"],state="readonly",width=18).grid(row=3,column=1,sticky="ew",pady=5)
        def save():
            if not re.fullmatch(r"20\d{2}",year.get().strip()):
                messagebox.showerror("Ongeldig jaar","Vul een jaartal van vier cijfers in.",parent=win); return
            identity={"level":level.get(),"year":year.get().strip(),"period":period.get(),"confidence":1.0,"source":"handmatig_bevestigd"}
            self.data["exam_metadata"]=identity
            # A project represents one exam: apply the explicit identity to all
            # attached source documents so exact opgaven/CV/addendum matching works.
            for document in self.data.get("documenten", []):
                if document.get("type_voorstel") in ("opgaven", "correctievoorschrift", "aanvulling", "uitwerkbijlage"):
                    document["exam_metadata"]=dict(identity)
            for record in self.data.get("vraagrecords", []):
                exam=record.setdefault("exam", {})
                exam.update({"level":identity["level"],"year":identity["year"],"period":identity["period"]})
                record["source_match_human_confirmed"]=True
                record["cv_match_human_confirmed"]=True
                record["appendix_match_human_confirmed"]=True
                record["cv_amendment_match_human_confirmed"]=True
                record["approved_by_human"]=False
                record["status"]="controle_nodig"
                record["approved_at"]=None
                record["approval_revoked_reason"]="Examenidentiteit handmatig bevestigd of gewijzigd; volledige eindcontrole opnieuw uitvoeren."
                record["record_review_checklist"]={key:False for key in record.get("record_review_checklist", {})}
            self.save_project(); self._log(f"Examenmetadata bevestigd voor alle documenten: {level.get()} {year.get()} tijdvak {period.get()}.")
            win.destroy()
        ttk.Button(frame,text="Gegevens opslaan",command=save).grid(row=4,column=0,columnspan=2,sticky="ew",pady=(14,0))
        frame.columnconfigure(1,weight=1)

    def analyze_questions(self):
        if not self.data:
            messagebox.showinfo("Eerst een project", "Open eerst een examenproject.")
            return
        docs = [d for d in self.data["documenten"] if d.get("type_voorstel") == "opgaven"]
        if not docs:
            messagebox.showinfo("Geen opgaven-PDF", "Voeg eerst de opgaven-PDF toe en bevestig zo nodig het documenttype.")
            return
        cv_docs = [d for d in self.data["documenten"] if d.get("type_voorstel") == "correctievoorschrift"]
        total = 0
        comparisons = {}
        for doc in docs:
            source = self.project_dir / "bronnen" / doc["opslagbestand"]
            structures = self.data.setdefault("exam_structures", {})
            current_structure = structures.get(doc["id"])
            if current_structure is None and self.data.get("exam_structure", {}).get("document_id") == doc["id"]:
                current_structure = self.data.get("exam_structure")
            if current_structure:
                structures[doc["id"]] = mark_structure_stale(current_structure, "De vraaganalyse is opnieuw uitgevoerd; controleer de structuur opnieuw.")
                if self.data.get("exam_structure", {}).get("document_id") == doc["id"]:
                    self.data["exam_structure"] = structures[doc["id"]]
            try:
                # Re-analysis changes question boundaries and therefore invalidates
                # every previously approved record derived from this source PDF.
                for record in self.data.get("vraagrecords",[]):
                    if record.get("candidate_document_id")==doc["id"]:
                        record["approved_by_human"]=False
                        record["status"]="bron_opnieuw_te_controleren"
                        record["source_analysis_invalidated"]=True
                        record["approval_revoked_reason"]="Bron-PDF opnieuw geanalyseerd; vraaggrenzen en uitsneden opnieuw controleren."
                analysis = analyze_pdf(source)
                candidates = detect_question_candidates(analysis)
                suppressed = analysis.get("suppressed_question_candidates", [])
                # Preserve a user's explicit decision to restore a suppressed
                # candidate across later re-analyses of the same source.
                restored_keys=set(self.data.get("restored_suppressed_candidate_keys",[]))
                def candidate_key(item):
                    return f"{doc['id']}|{item['number']}|{item['page']}|{float(item.get('bbox',[0,0])[1]):.1f}"
                still_suppressed=[]
                for item in suppressed:
                    if candidate_key(item) in restored_keys:
                        item["status"]="controle_nodig"
                        item["reason"]="Handmatig hersteld uit de lijst met onderdrukte dubbelingen; opnieuw controleren."
                        item.pop("suppressed_by",None)
                        candidates.append(item)
                    else:
                        still_suppressed.append(item)
                suppressed=still_suppressed
                ordered=sorted(candidates,key=lambda x:(int(x["page"]),float(x.get("bbox",[0,0])[1])))
                for index,item in enumerate(ordered):
                    following=ordered[index+1] if index+1<len(ordered) else None
                    proposal_text=extract_candidate_text(analysis,item,following)
                    type_check=detect_question_type(proposal_text)
                    context_refs=detect_context_references(proposal_text)
                    item.update({"document_id":doc["id"],"bestand":doc["bestand"],
                        "vraagtekst_voorstel":proposal_text,"vraagtype_controle":type_check,
                        "vraagtype_status":"controle_nodig","context_verwijzingen":context_refs})
                suppressed=sorted(suppressed,key=lambda x:(int(x["page"]),float(x.get("bbox",[0,0])[1])))
                for item in suppressed:
                    item_order=(int(item["page"]),float(item.get("bbox",[0,0])[1]))
                    following=next((x for x in ordered if (int(x["page"]),float(x.get("bbox",[0,0])[1]))>item_order),None)
                    proposal_text=extract_candidate_text(analysis,item,following)
                    item.update({"document_id":doc["id"],"bestand":doc["bestand"],
                        "vraagtekst_voorstel":proposal_text,"vraagtype_controle":detect_question_type(proposal_text),
                        "vraagtype_status":"controle_nodig","context_verwijzingen":detect_context_references(proposal_text)})
                candidates=ordered
                self.data.setdefault("vraagkandidaten",[])
                self.data.setdefault("onderdrukte_vraagkandidaten",[])
                self.data["vraagkandidaten"]=[x for x in self.data["vraagkandidaten"] if x.get("document_id")!=doc["id"]]+candidates
                self.data["onderdrukte_vraagkandidaten"]=[x for x in self.data["onderdrukte_vraagkandidaten"] if x.get("document_id")!=doc["id"]]+suppressed
                (self.project_dir/"analyse"/f"{doc['id']}-vraagkandidaten.json").write_text(json.dumps(candidates,ensure_ascii=False,indent=2),encoding="utf-8")
                (self.project_dir/"analyse"/f"{doc['id']}-onderdrukte-kandidaten.json").write_text(json.dumps(suppressed,ensure_ascii=False,indent=2),encoding="utf-8")
                self._log(f"{doc['bestand']}: {len(candidates)} vraagstartkandidaten; {len(suppressed)} zwakkere nummerdubbelingen apart bewaard voor controle.")
                total += len(candidates)

                # Compare only with the CV belonging to this exact exam identity.
                # Combining all CVs in a project can create plausible but false matches.
                matching_cvs = match_correction_documents(doc, cv_docs)
                if len(matching_cvs) == 1:
                    cv_doc = matching_cvs[0]
                    cv_source = self.project_dir / "bronnen" / cv_doc["opslagbestand"]
                    cv_analysis = analyze_pdf(cv_source)
                    cv_candidates = detect_cv_question_numbers(cv_analysis)
                    # A well-populated CV gives a useful independent signal for
                    # suspicious source-line numbers; it never auto-rejects a start.
                    cv_numbers = {int(x["number"]) for x in cv_candidates}
                    opgaven_numbers = {int(x["number"]) for x in candidates}
                    cv_crosscheck_available = len(cv_numbers) >= max(5, int(len(opgaven_numbers) * 0.6))
                    for candidate in candidates+suppressed:
                        candidate["cv_number_match"] = (int(candidate["number"]) in cv_numbers) if cv_crosscheck_available else None
                        candidate["cv_crosscheck_status"] = ("nummer_in_CV" if candidate["cv_number_match"] else "nummer_niet_in_CV_controleren") if cv_crosscheck_available else "CV-onvoldoende-herkend"
                    comparison = compare_question_numbering(candidates, cv_candidates)
                    comparison.update({"cv_file": cv_doc["bestand"], "cv_document_id": cv_doc["id"],
                                       "status": "controle_nodig" if comparison["status"] != "nummers_overeen" else "nummers_overeen"})
                    doc["cv_vergelijking"] = comparison
                    comparisons[doc["id"]] = comparison
                    self._log(f"CV-controle voor {doc['bestand']} met {cv_doc['bestand']}: ontbreekt in CV {comparison['ontbreekt_in_cv']}; ontbreekt in opgaven {comparison['ontbreekt_in_opgaven']}. Dit blijft een controlesignaal.")
                elif len(matching_cvs) > 1:
                    doc["cv_vergelijking"] = {"status": "meerdere_CVs_voor_hetzelfde_examen", "cv_bestanden": [x["bestand"] for x in matching_cvs]}
                    self._log(f"CV-controle overgeslagen voor {doc['bestand']}: meerdere correctievoorschriften met dezelfde examenmetadata.")
                else:
                    doc["cv_vergelijking"] = {"status": "geen_passend_CV", "reden": "Geen correctievoorschrift met hetzelfde niveau, jaar en tijdvak gevonden."}
                    self._log(f"Geen bijbehorend CV met dezelfde examenmetadata gevonden voor {doc['bestand']}.")
            except Exception as exc:
                self._error(f"Vraaganalyse ({doc['bestand']})", exc)
        self.data["nummeringsvergelijkingen_cv"] = comparisons
        self.save_project()
        self.refresh()
        messagebox.showinfo("Analyse voltooid", f"{total} mogelijke vraagstarts gevonden. Per examen is alleen het bijbehorende correctievoorschrift vergeleken. Dit zijn signalen, geen automatisch goedgekeurde vragen.")

    def show_candidates(self):
        if not self.data:
            return
        rows = self.data.get("vraagkandidaten", [])
        win = tk.Toplevel(self.root)
        win.title("Mogelijke vraagstarts – altijd controleren")
        win.geometry("900x580")
        ttk.Label(win, text=f"{len(rows)} actieve kandidaten. Zwakkere dubbelingen worden apart bewaard en kunnen handmatig worden hersteld.", padding=10).pack(anchor="w")
        cols=("number","page","confidence","type","options","cv","line","learning","status")
        tree=ttk.Treeview(win,columns=cols,show="headings")
        for col,label,width in [("number","Nr.",48),("page","PDF-pagina",78),("confidence","Signaal",68),("type","Vraagtype",105),("options","Opties",65),("cv","CV",88),("line","Gevonden tekst",290),("learning","Leerbank",105),("status","Status",125)]:
            tree.heading(col,text=label); tree.column(col,width=width)
        tree.pack(fill="both",expand=True,padx=10,pady=10)
        for i,row in enumerate(rows):
            learned=suggest_from_learning(self.knowledge_dir,question_pattern_key(row))
            suggestion=learned.get("suggestion")
            hint=("Tegenstrijdig" if learned.get("conflicting") else "Vraag" if suggestion=="question" else "Geen vraag" if suggestion=="not_question" else "—")
            if learned.get("support",0): hint+=f" ({learned['support']}×)"
            check=row.get("vraagtype_controle",{})
            type_label=check.get("type","nog niet bepaald")
            option_count=len(check.get("options",[]))
            option_label=f"{option_count} gevonden"
            if check.get("type")=="meerkeuze" and not check.get("options_complete"):
                option_label += " – controle"
            cv_label=("Match" if row.get("cv_number_match") is True else "Niet in CV" if row.get("cv_number_match") is False else "—")
            tree.insert("", "end", iid=str(i), values=(row.get("number"),row.get("page"),f"{row.get('confidence',0):.0%}",type_label,option_label,cv_label,row.get("line"),hint,row.get("status")))
        ttk.Label(win,text="Een nummerpatroon is geen bewijs dat het een examenvraag is. Jouw beoordeling wordt lokaal als leerdata opgeslagen.",wraplength=850).pack(anchor="w",padx=12,pady=(0,8))
        actions=ttk.Frame(win); actions.pack(fill="x",padx=12,pady=(0,12))
        def decide(is_question):
            selected=tree.selection()
            if not selected:
                messagebox.showinfo("Selecteer kandidaat","Selecteer eerst een gevonden vraagstart.")
                return
            row=rows[int(selected[0])]
            reason=simpledialog.askstring("Waarom deze keuze?","Korte reden (optioneel):",parent=win) or ""
            row["status"]="bevestigd_vraagstart" if is_question else "afgewezen_geen_vraag"
            row["human_decision"]=bool(is_question)
            row["decision_reason"]=reason
            suppression_key=f"{row.get('document_id')}|{row.get('number')}|{row.get('page')}|{float(row.get('bbox',[0,0])[1]):.1f}"
            if not is_question:
                self.data["restored_suppressed_candidate_keys"]=[x for x in self.data.get("restored_suppressed_candidate_keys",[]) if x!=suppression_key]
                for record in self.data.get("vraagrecords",[]):
                    if record.get("candidate_document_id")==row.get("document_id") and record.get("number")==row.get("number") and record.get("source_page")==row.get("page"):
                        record["approved_by_human"]=False
                        record["status"]="vraagstart_afgewezen_record_ongeldig"
                        record["source_analysis_invalidated"]=True
                        record["approval_revoked_reason"]="De bijbehorende vraagstart is handmatig afgewezen."
            learn_decision(self.project_dir/"kennisbank",{
                "pattern_key":question_pattern_key(row),
                "chosen":"question" if is_question else "not_question",
                "accepted":True,"scope":"voorstel_voor_toekomstige_herkenning",
                "document_id":row.get("document_id"),"page":row.get("page"),
                "candidate_line":row.get("line"),"reason":reason,
                "human_decision":bool(is_question)})
            self.save_project()
            tree.set(selected[0],"status",row["status"])
            learned=suggest_from_learning(self.project_dir/"kennisbank",question_pattern_key(row))
            suggestion=learned.get("suggestion")
            hint=("Tegenstrijdig" if learned.get("conflicting") else "Vraag" if suggestion=="question" else "Geen vraag" if suggestion=="not_question" else "—")
            if learned.get("support",0): hint+=f" ({learned['support']}×)"
            tree.set(selected[0],"learning",hint)
            self._log(f"Kandidaat vraag {row['number']} op pagina {row['page']}: {row['status']}. Beslissing opgeslagen in de lokale leerbank.")
        def inspect_question():
            selected=tree.selection()
            if not selected:
                messagebox.showinfo("Selecteer kandidaat","Selecteer eerst een kandidaat.")
                return
            row=rows[int(selected[0])]
            check=row.get("vraagtype_controle",{})
            detail=tk.Toplevel(win)
            detail.title(f"Vraag {row.get('number')} – tekst- en optiecontrole")
            detail.geometry("760x680")
            ttk.Label(detail,text=f"Voorgesteld vraagtype: {check.get('type','onbekend')}  |  zekerheid: {check.get('confidence',0):.0%}  |  status: altijd handmatig controleren",padding=10).pack(anchor="w")
            ttk.Label(detail,text="Vraagtekstvoorstel (afbakening kan nog onjuist zijn):",padding=(10,2)).pack(anchor="w")
            question_box=tk.Text(detail,height=19,wrap="word")
            question_box.pack(fill="both",expand=True,padx=10,pady=4)
            question_box.insert("1.0",row.get("vraagtekst_voorstel",""))
            question_box.configure(state="disabled")
            ttk.Label(detail,text="Gevonden antwoordopties:",padding=(10,6)).pack(anchor="w")
            options=check.get("options",[])
            option_lines=[f"{o.get('label')}. {o.get('text')}" for o in options]
            if not option_lines:
                option_lines=["Geen A-H-antwoordopties herkend. Controleer of het een open vraag, juist/onjuist-vraag of wel/niet-vraag is."]
            ttk.Label(detail,text="\n".join(option_lines),wraplength=720,justify="left",padding=(12,2)).pack(anchor="w")
            if check.get("type")=="meerkeuze":
                gaps=check.get("option_gaps",[])
                duplicates=check.get("duplicate_option_labels",[])
                warning=("Ontbrekende labels: "+(", ".join(gaps) if gaps else "geen")+
                         " | Dubbele labels: "+(", ".join(duplicates) if duplicates else "geen"))
                ttk.Label(detail,text=warning,foreground="#9b4d00",wraplength=720,padding=10).pack(anchor="w")
            refs=row.get("context_verwijzingen",[])
            ref_lines=[f"{x.get('kind')} {x.get('number') or ''}: {x.get('matched_text')}" for x in refs]
            ttk.Label(detail,text="Mogelijke verwijzingen naar contextmateriaal:",padding=(10,4)).pack(anchor="w")
            ttk.Label(detail,text="\n".join(ref_lines) if ref_lines else "Geen expliciete figuur-, tabel-, bron- of tekstverwijzing herkend.",wraplength=720,justify="left",padding=(12,2)).pack(anchor="w")
            ttk.Label(detail,text="Dit is een automatische aanwijzing, geen inhoudelijke beoordeling. Controleer de originele PDF, alle opties en de aansluiting op het correctievoorschrift.",wraplength=720,padding=10).pack(anchor="w")
        suppressed_count=len([x for x in self.data.get("onderdrukte_vraagkandidaten",[])])
        ttk.Button(actions,text=f"Onderdrukte dubbelingen ({suppressed_count})",command=lambda:self.show_suppressed_candidates(win)).pack(side="left",padx=8)
        ttk.Button(actions,text="Maak concept-vraagrecord",command=lambda:self.create_question_record(rows,tree,win)).pack(side="left",padx=8)
        ttk.Button(actions,text="Bekijk vraag en opties",command=inspect_question).pack(side="left",padx=8)
        ttk.Button(actions,text="Bevestig vraagstart",command=lambda:decide(True)).pack(side="left")
        ttk.Button(actions,text="Geen vraag",command=lambda:decide(False)).pack(side="left",padx=8)
        ttk.Button(actions,text="Originele pagina bekijken",command=lambda:self.preview_candidate(rows,tree,win)).pack(side="left",padx=8)
        ttk.Button(actions,text="Voorlopige snippet maken",command=lambda:self.create_snippet_proposal(rows,tree,win)).pack(side="left",padx=8)

    def show_suppressed_candidates(self,parent):
        rows=self.data.get("onderdrukte_vraagkandidaten",[])
        win=tk.Toplevel(parent); win.title("Onderdrukte nummerdubbelingen · handmatige controle"); win.geometry("900x520")
        ttk.Label(win,text=f"{len(rows)} zwakkere kandidaten zijn apart gezet omdat hetzelfde nummer elders met een expliciete puntenaanduiding voorkwam. Dit is geen definitieve afwijzing.",wraplength=860,padding=10).pack(anchor="w")
        cols=("number","page","confidence","strong_page","line","reason")
        tree=ttk.Treeview(win,columns=cols,show="headings")
        for col,label,width in [("number","Nr.",55),("page","Pagina",75),("confidence","Signaal",70),("strong_page","Sterkere kandidaat p.",105),("line","Regeltekst",300),("reason","Waarom apart gezet",260)]:
            tree.heading(col,text=label); tree.column(col,width=width,anchor="w")
        tree.pack(fill="both",expand=True,padx=10,pady=8)
        for idx,item in enumerate(rows):
            strong=item.get("suppressed_by",{})
            tree.insert("","end",iid=str(idx),values=(item.get("number"),item.get("page"),f"{item.get('confidence',0):.0%}",
                strong.get("page"),item.get("next_line",""),item.get("reason","")))
        def restore():
            selected=tree.selection()
            if not selected:
                messagebox.showinfo("Selecteer kandidaat","Selecteer eerst een onderdrukte kandidaat.",parent=win); return
            item=rows[int(selected[0])]
            key=f"{item.get('document_id')}|{item.get('number')}|{item.get('page')}|{float(item.get('bbox',[0,0])[1]):.1f}"
            item["status"]="controle_nodig"
            item["human_decision"]=None            item["reason"]="Handmatig hersteld uit onderdrukte dubbelingen; controleer de originele pagina."
            item.pop("suppressed_by",None)
            self.data["onderdrukte_vraagkandidaten"]=[x for x in self.data.get("onderdrukte_vraagkandidaten",[]) if x is not item]
            self.data.setdefault("vraagkandidaten",[]).append(item)
            keys=self.data.setdefault("restored_suppressed_candidate_keys",[])
            if key not in keys: keys.append(key)
            learn_decision(self.project_dir/"kennisbank",{
                "pattern_key":question_pattern_key(item),"chosen":"question","accepted":True,
                "scope":"voorstel_voor_toekomstige_herkenning","document_id":item.get("document_id"),
                "page":item.get("page"),"candidate_line":item.get("line"),
                "reason":"Handmatig hersteld uit onderdrukte nummerdubbelingen.","human_decision":True})
            self.save_project()
            self._log(f"Onderdrukte kandidaat vraag {item.get('number')} op pagina {item.get('page')} handmatig hersteld.")
            win.destroy()
            parent.destroy()
            self.show_candidates()
        buttons=ttk.Frame(win); buttons.pack(fill="x",padx=10,pady=(0,10))
        ttk.Button(buttons,text="Originele pagina bekijken",command=lambda:self.preview_candidate(rows,tree,win)).pack(side="left")
        ttk.Button(buttons,text="Herstel geselecteerde kandidaat",command=restore).pack(side="right")

    def _scrollable_form(self, window, padding=12):
        """Create a vertically scrollable form so long exam records remain usable on laptop screens."""
        shell = ttk.Frame(window)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = ttk.Frame(canvas, padding=padding)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        def update_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def resize_content(event):
            canvas.itemconfigure(window_id, width=event.width)
        content.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", resize_content)
        canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))
        return content

    def create_question_record(self, rows, tree, parent):
        selected=tree.selection()
        if not selected:
            messagebox.showinfo("Selecteer kandidaat","Selecteer eerst een vraagstart.")
            return
        row=rows[int(selected[0])]
        if row.get("human_decision") is not True:
            messagebox.showwarning("Vraagstart eerst bevestigen","Bevestig eerst handmatig dat dit een echte vraagstart is. Een conceptrecord wordt niet gemaakt op basis van alleen een automatisch signaal.",parent=parent)
            return
        source_doc=next((d for d in self.data.get("documenten",[]) if d.get("id")==row.get("document_id")),None)
        if not source_doc:
            messagebox.showerror("Bron ontbreekt","De oorspronkelijke opgaven-PDF is niet gekoppeld.",parent=parent)
            return
        docs=self.data.get("documenten",[])
        cv_docs=[d for d in docs if d.get("type_voorstel")=="correctievoorschrift"]
        matching=match_correction_documents(source_doc,cv_docs)
        if not matching:
            messagebox.showwarning("Correctievoorschrift ontbreekt","Er is geen correctievoorschrift met hetzelfde niveau, jaar en tijdvak gevonden. Controleer eerst de documenttypen en examenmetadata.",parent=parent)
            return
        current=next((r for r in self.data.get("vraagrecords",[]) if r.get("candidate_document_id")==row.get("document_id") and r.get("number")==row.get("number") and r.get("source_page")==row.get("page")),None)
        initial_meta=source_doc.get("exam_metadata") or self.data.get("exam_metadata") or infer_exam_metadata(source_doc.get("bestand",""))
        win=tk.Toplevel(parent); win.title(f"Concept-vraagrecord · vraag {row.get('number')}"); win.geometry("900x820")
        win.transient(parent); win.grab_set()
        outer=self._scrollable_form(win,padding=14)
        ttk.Label(outer,text="CONCEPT — NIET GOEDGEKEURD VOOR PUBLICATIE",foreground="#9b4d00").pack(anchor="w")
        ttk.Label(outer,text="Controleer de tekst, het vraagtype, de punten, de context en de bijlagen aan de hand van de originele PDF en het officiële correctievoorschrift.",wraplength=850).pack(anchor="w",pady=(4,10))
        meta_frame=ttk.LabelFrame(outer,text="Examen- en vraaggegevens",padding=8); meta_frame.pack(fill="x")
        values={}
        defaults={"level":initial_meta.get("level","Havo"),"year":str(initial_meta.get("year","")),
                  "period":str(initial_meta.get("period","1")),"points":"","theme":"","concept":"","end":"","focus":""}
        labels=[("level","Niveau"),("year","Jaar"),("period","Tijdvak"),("points","Punten"),("theme","Thema"),("concept","Concept"),("end","Eindterm"),("focus","Focus")]
        for index,(key,label) in enumerate(labels):
            rr=index//4; cc=(index%4)*2
            ttk.Label(meta_frame,text=label).grid(row=rr,column=cc,sticky="w",padx=(2,4),pady=4)
            var=tk.StringVar(value=str((current or {}).get("exam",{}).get(key,defaults[key])))
            values[key]=var
            if key=="level":
                widget=ttk.Combobox(meta_frame,textvariable=var,values=["Havo","Vwo"],state="readonly",width=12)
            elif key=="period":
                widget=ttk.Combobox(meta_frame,textvariable=var,values=["1","2","3"],state="readonly",width=8)
            else:
                widget=ttk.Entry(meta_frame,textvariable=var,width=18)
            widget.grid(row=rr,column=cc+1,sticky="ew",padx=(0,8),pady=4)
        ttk.Label(outer,text="Vraagtype").pack(anchor="w",pady=(8,2))
        detected=row.get("vraagtype_controle",{}).get("type")
        default_type="mcq" if detected=="meerkeuze" else "open"
        question_type=tk.StringVar(value=(current or {}).get("exam",{}).get("questionType",default_type))
        ttk.Combobox(outer,textvariable=question_type,values=["open","mcq"],state="readonly",width=12).pack(anchor="w")
        ttk.Label(outer,text="Vraagtekst (volledig nalopen en zo nodig corrigeren)").pack(anchor="w",pady=(8,2))
        qbox=tk.Text(outer,height=12,wrap="word")
        qbox.pack(fill="both",expand=True)
        qbox.insert("1.0",(current or {}).get("question_text",row.get("vraagtekst_voorstel","")))
        initial_context_text=(current or {}).get("source_context","")
        if not initial_context_text:
            try:
                candidate_structure=self.data.get("exam_structures",{}).get(source_doc["id"]) or self.data.get("exam_structure")
                candidate_numbers=sorted({int(x["number"]) for x in self.data.get("vraagkandidaten",[])
                                          if x.get("document_id")==source_doc["id"] and x.get("human_decision") is True})
                if candidate_structure and not validate_exam_structure(candidate_structure,source_doc["id"],source_doc["sha256"],candidate_numbers):
                    linked_context=fragments_for_question(candidate_structure,row["number"]).get("context_fragments",[])
                    if linked_context:
                        context_analysis=analyze_pdf(self.project_dir/"bronnen"/source_doc["opslagbestand"])
                        context_sizes={int(p["page"]):(float(p["width"]),float(p["height"])) for p in context_analysis["pages"]}
                        context_texts=[]
                        for fragment in linked_context:
                            context_segments=page_spans_to_segments(fragment["page_spans"],context_sizes)
                            found_text=extract_region_text(self.project_dir/"bronnen"/source_doc["opslagbestand"],context_segments)
                            if found_text: context_texts.append(found_text)
                        initial_context_text="\n\n".join(context_texts)
            except Exception as exc:
                self._log(f"Contexttekst kon niet vooraf worden geladen: {exc}")
        ttk.Label(outer,text="Contexttekst (controleer en corrigeer; leeg laten als de context uitsluitend beeldmateriaal bevat)").pack(anchor="w",pady=(8,2))
        context_text_box=tk.Text(outer,height=6,wrap="word")
        context_text_box.pack(fill="x")
        context_text_box.insert("1.0",initial_context_text)
        ttk.Label(outer,text="Meerkeuzeopties als JSON-lijst (voor open vragen leeg laten). Voorbeeld: [{\"key\":\"A\",\"text\":\"...\"},{\"key\":\"B\",\"text\":\"...\"}]").pack(anchor="w",pady=(8,2))
        detected_options=[{"key":x.get("label"),"text":x.get("text","")} for x in row.get("vraagtype_controle",{}).get("options",[])]
        obox=tk.Text(outer,height=4,wrap="word")
        obox.pack(fill="x")
        obox.insert("1.0",json.dumps((current or {}).get("options",detected_options),ensure_ascii=False,indent=2))
        correct_var=tk.StringVar(value=(current or {}).get("correct",""))
        correct_frame=ttk.Frame(outer); correct_frame.pack(fill="x",pady=4)
        ttk.Label(correct_frame,text="Juiste optie (A-H)").pack(side="left")
        ttk.Entry(correct_frame,textvariable=correct_var,width=8).pack(side="left",padx=8)
        ttk.Label(outer,text="Bijbehorend correctievoorschrift").pack(anchor="w",pady=(6,2))
        cv_names=[d["bestand"] for d in matching]
        cv_choice=tk.StringVar(value=(current or {}).get("cv_display_name",cv_names[0] if len(cv_names)==1 else ""))
        ttk.Combobox(outer,textvariable=cv_choice,values=cv_names,state="readonly").pack(fill="x")
        ttk.Label(outer,text="Uitwerkbijlagen (selecteer alle bijlagen waarnaar deze vraag verwijst)").pack(anchor="w",pady=(8,2))
        appendix_docs=match_exam_documents(source_doc,[d for d in docs if d.get("type_voorstel")=="uitwerkbijlage"])
        ttk.Label(outer,text="Uitwerkbijlagen van ditzelfde examen (selecteer alle bijlagen waarnaar deze vraag verwijst)").pack(anchor="w",pady=(8,2))
        appendix_list=tk.Listbox(outer,selectmode="multiple",height=min(4,max(2,len(appendix_docs))))
        appendix_list.pack(fill="x")
        existing_appendices=set((current or {}).get("uitwerkbijlagen",[]))
        for idx,doc in enumerate(appendix_docs):
            appendix_list.insert("end",doc["bestand"])
            if doc.get("opslagbestand") in existing_appendices: appendix_list.selection_set(idx)
        amendment_docs=match_exam_documents(source_doc,[d for d in docs if d.get("type_voorstel")=="aanvulling"])
        ttk.Label(outer,text="Officiële aanvullingen op het correctievoorschrift van ditzelfde examen (selecteer alle)").pack(anchor="w",pady=(8,2))
        amendment_list=tk.Listbox(outer,selectmode="multiple",height=min(4,max(2,len(amendment_docs))))
        amendment_list.pack(fill="x")
        existing_amendments=set((current or {}).get("cv_amendment_pdfs",[]))
        for idx,doc in enumerate(amendment_docs):
            amendment_list.insert("end",doc["bestand"])
            if doc.get("opslagbestand") in existing_amendments: amendment_list.selection_set(idx)
        context_files=[dict(x) for x in row.get("context_asset_proposal_files",[])]
        # Keep manually selected/cropped context assets available when an existing
        # draft is reopened; derived full context-region renders are rebuilt below.
        known_context_files={x.get("file") for x in context_files}
        for saved_asset in (current or {}).get("context_asset_files", []):
            if saved_asset.get("asset_id") and saved_asset.get("file") not in known_context_files:
                context_files.append(dict(saved_asset))
                known_context_files.add(saved_asset.get("file"))
        context_structure = (self.data.get("exam_structures", {}).get(source_doc["id"])
                             or self.data.get("exam_structure"))
        context_fragments_for_editor = fragments_for_question(context_structure, row["number"]).get("context_fragments", [])

        ttk.Label(outer,text="Extra figuur-/tabeluitsneden die bij deze vraag horen (selecteer alleen de juiste; controleer bijschriften en context)").pack(anchor="w",pady=(8,2))
        context_list=tk.Listbox(outer,selectmode="multiple",height=min(5,max(2,len(context_files))))
        context_list.pack(fill="x")
        for idx,item in enumerate(context_files):
            context_list.insert("end",f"Pagina {item.get('page')} · {item.get('caption') or item.get('asset_id')} · {item.get('file')}")
        ttk.Label(outer,text="Bijschrift van de geselecteerde figuur/tabel (leeg laten als er geen bijschrift is)").pack(anchor="w",pady=(6,2))
        context_caption_var=tk.StringVar(value="")
        ttk.Entry(outer,textvariable=context_caption_var).pack(fill="x")
        def load_context_caption(_event=None):
            selected=context_list.curselection()
            if len(selected)==1:
                context_caption_var.set(context_files[selected[0]].get("caption") or "")
            else:
                context_caption_var.set("")
        def confirm_context_caption():
            selected=context_list.curselection()
            if len(selected)!=1:
                messagebox.showinfo("Selecteer één contextuitsnede","Selecteer één figuur of tabel om het bijschrift te bevestigen.",parent=win)
                return
            index=selected[0]
            context_files[index]["caption"]=context_caption_var.get().strip() or None
            context_files[index]["caption_human_confirmed"]=True
            context_list.delete(index)
            item=context_files[index]
            context_list.insert(index,f"Pagina {item.get('page')} · {item.get('caption') or 'geen bijschrift'} · {item.get('file')}")
            context_list.selection_set(index)
            messagebox.showinfo("Bijschrift bevestigd","Het bijschrift (of het ontbreken ervan) is voor deze uitsnede bevestigd.",parent=win)
        context_list.bind("<<ListboxSelect>>",load_context_caption)

        ttk.Button(outer,text="Bijschrift bevestigen voor geselecteerde uitsnede",command=confirm_context_caption).pack(anchor="w",pady=(2,6))
        def add_manual_context_crop():
            source_path=self.project_dir/"bronnen"/source_doc["opslagbestand"]
            if not source_path.is_file() or sha256(source_path)!=source_doc.get("sha256"):
                messagebox.showerror("Opgavenbron gewijzigd","De originele opgaven-PDF ontbreekt of is gewijzigd. Voeg de juiste PDF opnieuw toe.",parent=win)
                return
            try:
                source_analysis=analyze_pdf(source_path)
                page_count=int(source_analysis["page_count"])
                page_sizes={int(p["page"]):(float(p["width"]),float(p["height"])) for p in source_analysis["pages"]}
            except Exception as exc:
                messagebox.showerror("PDF niet beschikbaar",str(exc),parent=win)
                return
            crop_win=tk.Toplevel(win)
            crop_win.title(f"Figuur of tabel handmatig uitsnijden · vraag {row['number']}")
            crop_win.geometry("1120x850")
            crop_win.transient(win)
            ttk.Label(crop_win,text="Sleep verticaal om een horizontale strook over de volledige paginabreedte te selecteren. Er worden geen linker- of rechtergrenzen gebruikt; de PDF blijft ongewijzigd.",
                      wraplength=1080,padding=10).pack(anchor="w")
            controls=ttk.Frame(crop_win,padding=(10,4)); controls.pack(fill="x")
            page_var=tk.IntVar(value=int(row.get("page",1)))
            ttk.Button(controls,text="◀",command=lambda:change_crop_page(-1)).pack(side="left")
            ttk.Label(controls,text="Pagina").pack(side="left",padx=(8,3))
            page_spin=tk.Spinbox(controls,from_=1,to=page_count,textvariable=page_var,width=5)
            page_spin.pack(side="left")
            ttk.Label(controls,text=f"van {page_count}").pack(side="left",padx=(4,12))
            ttk.Button(controls,text="▶",command=lambda:change_crop_page(1)).pack(side="left")
            kind_var=tk.StringVar(value="figuur")
            ttk.Label(controls,text="Soort").pack(side="left",padx=(18,4))
            ttk.Combobox(controls,textvariable=kind_var,values=["figuur","tabel","grafiek","afbeelding","bron","overig"],state="readonly",width=14).pack(side="left")
            fragment_labels=["Vraag zelf / niet aan context gekoppeld"]
            fragment_map={fragment_labels[0]:None}
            for fragment in context_fragments_for_editor:
                label=f"{fragment.get('type')} · {', '.join(str(x['page']) for x in fragment.get('page_spans',[])) or 'geen pagina'} · {fragment.get('id')}"
                fragment_labels.append(label)
                fragment_map[label]=fragment.get("id")
            fragment_var=tk.StringVar(value=fragment_labels[1] if len(fragment_labels)>1 else fragment_labels[0])
            ttk.Label(controls,text="Contextkoppeling").pack(side="left",padx=(14,4))
            ttk.Combobox(controls,textvariable=fragment_var,values=fragment_labels,state="readonly",width=35).pack(side="left",fill="x",expand=True)
            frame=ttk.Frame(crop_win); frame.pack(fill="both",expand=True,padx=10,pady=4)
            canvas=tk.Canvas(frame,background="white",highlightthickness=1,highlightbackground="#b8b8b8")
            sy=ttk.Scrollbar(frame,orient="vertical",command=canvas.yview)
            sx=ttk.Scrollbar(frame,orient="horizontal",command=canvas.xview)
            canvas.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
            sy.pack(side="right",fill="y"); sx.pack(side="bottom",fill="x"); canvas.pack(side="left",fill="both",expand=True)
            photo=None
            image_width=image_height=1
            selection_start=None
            selection_lines=None
            def show_crop_page():
                nonlocal photo,image_width,image_height,selection_start,selection_lines
                number=max(1,min(page_count,int(page_var.get())))
                page_var.set(number)
                target=self.project_dir/"analyse"/f"manual-context-{source_doc['id']}-p{number}.png"
                render_page(source_path,number,target,scale=1.15)
                photo=tk.PhotoImage(file=str(target))
                image_width,image_height=photo.width(),photo.height()
                canvas.delete("all")
                canvas.create_image(0,0,image=photo,anchor="nw")
                canvas.image=photo
                canvas.configure(scrollregion=(0,0,image_width,image_height))
                selection_start=None
                selection_lines=None
                crop_status.configure(text=f"Originele pagina {number}. Sleep verticaal over de figuur of tabel; de strook loopt over de volledige paginabreedte.")            def change_crop_page(delta):
                page_var.set(max(1,min(page_count,int(page_var.get())+delta)))
                show_crop_page()
            def start_crop(event):
                nonlocal selection_start,selection_lines
                y=max(0,min(image_height,canvas.canvasy(event.y)))
                selection_start=y
                if selection_lines:
                    for line_id in selection_lines: canvas.delete(line_id)
                selection_lines=[
                    canvas.create_line(0,y,image_width,y,fill="black",width=2),
                    canvas.create_line(0,y,image_width,y,fill="black",width=2)
                ]
            def drag_crop(event):
                if selection_start is None or selection_lines is None: return
                y=max(0,min(image_height,canvas.canvasy(event.y)))
                canvas.coords(selection_lines[1],0,y,image_width,y)
            def save_manual_crop():
                if selection_start is None or selection_lines is None:
                    messagebox.showinfo("Geen uitsnede","Sleep eerst verticaal om de boven- en ondergrens van de paginabrede strook te bepalen.",parent=crop_win)
                    return
                try:
                    end_y=canvas.coords(selection_lines[1])[1]
                    top_y,bottom_y=sorted((float(selection_start),float(end_y)))
                    page_no=int(page_var.get())
                    bbox=pixel_rect_to_pdf_bbox([0,top_y,image_width,bottom_y],(image_width,image_height),page_sizes[page_no])
                    stamp=datetime.now().strftime("%Y%m%d%H%M%S%f")
                    asset_id=f"manual-p{page_no}-{stamp}"
                    name=f"context-manual-{source_doc['id']}-q{row['number']}-{asset_id}.png"
                    target=self.project_dir/"snippets"/name
                    crop_info=render_crop(source_path,page_no,bbox,target,scale=1.8)
                    preview=tk.Toplevel(crop_win)
                    preview.title(f"Contextuitsnede · pagina {page_no} · vraag {row['number']}")
                    preview.geometry("760x650")
                    ttk.Label(preview,text="Voorbeeld van de uitsnede uit de originele PDF. Het bijschrift moet nog in het hoofdvenster worden bevestigd.",
                              wraplength=720,padding=8).pack(anchor="w")
                    preview_frame=ttk.Frame(preview); preview_frame.pack(fill="both",expand=True,padx=8,pady=4)
                    preview_canvas=tk.Canvas(preview_frame,background="white")
                    preview_sy=ttk.Scrollbar(preview_frame,orient="vertical",command=preview_canvas.yview)
                    preview_sx=ttk.Scrollbar(preview_frame,orient="horizontal",command=preview_canvas.xview)
                    preview_canvas.configure(yscrollcommand=preview_sy.set,xscrollcommand=preview_sx.set)
                    preview_sy.pack(side="right",fill="y"); preview_sx.pack(side="bottom",fill="x")
                    preview_canvas.pack(side="left",fill="both",expand=True)
                    preview_photo=tk.PhotoImage(file=str(target))
                    preview_canvas.create_image(0,0,image=preview_photo,anchor="nw")
                    preview_canvas.image=preview_photo
                    preview_canvas.configure(scrollregion=preview_canvas.bbox("all"))
                    asset={"file":name,"page":page_no,"page_size":[page_sizes[page_no][0],page_sizes[page_no][1]],"caption":None,"asset_id":asset_id,
                           "asset_kind":kind_var.get(),"type":kind_var.get(),"bbox":list(crop_info["bbox"]),
                           "source_document_id":source_doc["id"],"source_sha256":source_doc["sha256"],
                           "source_pdf":source_doc["opslagbestand"],"question_number":int(row["number"]),
                           "fragment_id":fragment_map.get(fragment_var.get()),
                           "crop_method":"handmatige_paginabrede_strook_op_originele_pdf",
                           "caption_human_confirmed":False,"status":"handmatig_uitgesneden_bijschrift_te_bevestigen"}
                    context_files.append(asset)
                    row["context_asset_proposal_files"]=[dict(x) for x in context_files]
                    context_list.insert("end",f"Pagina {page_no} · {kind_var.get()} · bijschrift nog bevestigen · {name}")
                    new_index=context_list.size()-1
                    context_list.selection_set(new_index)
                    context_caption_var.set("")
                    self.save_project()
                    crop_status.configure(text=f"Uitsnede toegevoegd: pagina {page_no}. Bevestig het bijschrift in het hoofdvenster.")
                    if selection_lines:
                        for line_id in selection_lines: canvas.delete(line_id)
                    selection_start=None
                    selection_lines=None
                except Exception as exc:
                    messagebox.showerror("Uitsnede niet opgeslagen",str(exc),parent=crop_win)
            canvas.bind("<Button-1>",start_crop)
            canvas.bind("<B1-Motion>",drag_crop)
            actions=ttk.Frame(crop_win,padding=10); actions.pack(fill="x")
            crop_status=ttk.Label(actions,text="Selecteer een horizontale strook over de volledige paginabreedte.")
            crop_status.pack(side="left",fill="x",expand=True)
            ttk.Button(actions,text="Uitsnede toevoegen",command=save_manual_crop).pack(side="left",padx=8)
            ttk.Button(actions,text="Sluiten",command=crop_win.destroy).pack(side="right")
            page_spin.configure(command=show_crop_page)
            page_spin.bind("<Return>",lambda _e:show_crop_page())
            show_crop_page()
        def remove_context_assets():
            selected=list(context_list.curselection())
            if not selected:
                messagebox.showinfo("Geen uitsnede geselecteerd","Selecteer eerst één of meer uitsneden die je uit dit vraagrecord wilt verwijderen.",parent=win)
                return
            if not messagebox.askyesno("Uitsneden verwijderen",f"Verwijder {len(selected)} geselecteerde contextuitsnede(n) uit dit vraagrecord? De originele PDF blijft behouden.",parent=win):
                return
            for index in reversed(selected):
                context_files.pop(index)
                context_list.delete(index)
            row["context_asset_proposal_files"]=[dict(x) for x in context_files]
            context_caption_var.set("")
            self.save_project()
        ttk.Button(outer,text="Geselecteerde contextuitsnede(n) verwijderen",command=remove_context_assets).pack(anchor="w",pady=(2,4))
        ttk.Button(outer,text="Figuur/tabel handmatig uitsnijden uit originele PDF",command=add_manual_context_crop).pack(anchor="w",pady=(2,6))

        ttk.Label(outer,text="CV-snippetbestand (volledige beoordeling van deze vraag; voor open vragen verplicht voor export)").pack(anchor="w",pady=(8,2))
        snippet_names=sorted(p.name for p in (self.project_dir/"snippets").glob("cv-*.png"))
        cv_snippet_var=tk.StringVar(value=(current or {}).get("cv_snippet_file",""))
        cv_snippet_combo=ttk.Combobox(outer,textvariable=cv_snippet_var,values=[""]+snippet_names,state="readonly")
        cv_snippet_combo.pack(fill="x")
        def make_cv_snippet():
            cv_doc=next((d for d in matching if d["bestand"]==cv_choice.get()),None)
            if not cv_doc:
                messagebox.showerror("CV ontbreekt","Selecteer eerst het bijbehorende correctievoorschrift.",parent=win)
                return
            try:
                cv_path=self.project_dir/"bronnen"/cv_doc["opslagbestand"]
                analysis=analyze_pdf(cv_path)
                anchors=detect_cv_question_numbers(analysis)
                matches=[x for x in anchors if int(x["number"])==int(row["number"])]
                if not matches:
                    messagebox.showwarning("Vraaganker niet gevonden",f"Vraag {row['number']} is niet betrouwbaar als anker herkend in dit CV. Controleer de originele PDF; er wordt geen fragment verzonnen.",parent=win)
                    return
                def render_anchor(anchor):
                    proposals=propose_question_regions(analysis,anchors)
                    proposal=next((p for p in proposals if p["number"]==int(row["number"]) and p["start_page"]==int(anchor["page"]) and p["source_segments"]),None)
                    if not proposal:
                        messagebox.showerror("CV-fragment mislukt","Er kon geen afgebakend fragmentvoorstel worden gemaakt.",parent=win)
                        return
                    name=f"cv-{cv_doc['id']}-q{row['number']}-p{anchor['page']}.png"
                    target=self.project_dir/"snippets"/name
                    render_composite_crops(cv_path,proposal["source_segments"],target,scale=1.35)
                    cv_snippet_combo.configure(values=[""]+sorted(set(snippet_names+[name])))
                    cv_snippet_var.set(name)
                    self._log(f"CV-fragmentvoorstel gemaakt voor vraag {row['number']} uit {cv_doc['bestand']}; controleer alle beoordelingsregels en paginagrenzen.")
                    preview=tk.Toplevel(win); preview.title(f"CV-fragment vraag {row['number']} · niet goedgekeurd"); preview.geometry("900x760")
                    ttk.Label(preview,text="VOORSTEL — controleer of alle beoordelingsregels, punten en aanvullingen compleet zijn.",wraplength=850,padding=8).pack(fill="x")
                    frame=ttk.Frame(preview); frame.pack(fill="both",expand=True)
                    canvas=tk.Canvas(frame,background="#dce3e6")
                    sy=ttk.Scrollbar(frame,orient="vertical",command=canvas.yview)
                    sx=ttk.Scrollbar(frame,orient="horizontal",command=canvas.xview)
                    canvas.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
                    sy.pack(side="right",fill="y"); sx.pack(side="bottom",fill="x"); canvas.pack(side="left",fill="both",expand=True)
                    photo=tk.PhotoImage(file=str(target)); canvas.create_image(0,0,image=photo,anchor="nw")
                    canvas.image=photo; canvas.configure(scrollregion=canvas.bbox("all"))
                if len(matches)==1:
                    render_anchor(matches[0])
                else:
                    picker=tk.Toplevel(win); picker.title("Kies CV-anker"); picker.transient(win)
                    ttk.Label(picker,text=f"Vraag {row['number']} komt op meerdere pagina's voor. Kies het juiste beoordelingsmodelanker.",padding=8).pack(anchor="w")
                    choices=tk.Listbox(picker,width=90,height=min(8,len(matches)))
                    choices.pack(fill="both",expand=True,padx=8,pady=8)
                    for item in matches: choices.insert("end",f"Pagina {item['page']} · {item['line']}")
                    def choose():
                        selection=choices.curselection()
                        if not selection: return
                        anchor=matches[selection[0]]
                        picker.destroy()
                        render_anchor(anchor)
                    ttk.Button(picker,text="Gebruik geselecteerd anker",command=choose).pack(pady=(0,8))
            except Exception as exc:
                self._error("CV-fragment maken",exc)
                messagebox.showerror("CV-fragment mislukt",str(exc),parent=win)
        ttk.Button(outer,text="CV-fragment uit origineel correctievoorschrift maken (automatisch voorstel)",command=make_cv_snippet).pack(anchor="w",pady=(4,2))
        def edit_primary_cv_region():
            cv_doc = next((d for d in matching if d["bestand"] == cv_choice.get()), None)
            if not cv_doc:
                messagebox.showerror("CV ontbreekt", "Selecteer eerst het bijbehorende correctievoorschrift.", parent=win)
                return
            def saved(name, fragment):
                cv_snippet_var.set(name)
                cv_snippet_combo.configure(values=[""] + sorted(set(list(cv_snippet_combo.cget("values")) + [name])))
            self.open_cv_region_editor(row, cv_doc, saved)
        ttk.Button(outer,text="CV handmatig afbakenen op de originele PDF",command=edit_primary_cv_region).pack(anchor="w",pady=(2,4))
        ttk.Label(outer,text="Eventueel fragment uit officiële CV-aanvulling (alleen als die voor deze vraag een wijziging bevat)").pack(anchor="w",pady=(8,2))
        amendment_snippet_names=sorted(p.name for p in (self.project_dir/"snippets").glob("cv-amend-*.png"))
        amendment_snippet_var=tk.StringVar(value=(current or {}).get("cv_amendment_snippet_file",""))
        amendment_snippet_combo=ttk.Combobox(outer,textvariable=amendment_snippet_var,values=[""]+amendment_snippet_names,state="readonly")
        amendment_snippet_combo.pack(fill="x")
        def make_amendment_snippet():
            selected_amendments=amendment_list.curselection()
            if not selected_amendments:
                messagebox.showinfo("Kies aanvulling","Selecteer eerst de officiële CV-aanvulling die je wilt uitsnijden.",parent=win)
                return
            amendment_doc=amendment_docs[selected_amendments[0]]
            amendment_path=self.project_dir/"bronnen"/amendment_doc["opslagbestand"]
            try:
                amendment_analysis=analyze_pdf(amendment_path)
                anchors=detect_cv_question_numbers(amendment_analysis)
                matches=[x for x in anchors if int(x["number"])==int(row["number"])]
                if not matches:
                    messagebox.showwarning("Geen vraaganker",f"Vraag {row['number']} is niet als afzonderlijk anker herkend in {amendment_doc['bestand']}. Het volledige origineel blijft gekoppeld; controleer de aanvulling handmatig.",parent=win)
                    return
                proposals=propose_question_regions(amendment_analysis,anchors)
                proposal=next((p for p in proposals if p["number"]==int(row["number"]) and p["start_page"]==int(matches[0]["page"])),None)
                if not proposal:
                    messagebox.showwarning("Geen fragment","Er kon geen fragmentvoorstel uit de aanvulling worden gemaakt.",parent=win)
                    return
                name=f"cv-amend-{amendment_doc['id']}-q{row['number']}-p{matches[0]['page']}.png"
                target=self.project_dir/"snippets"/name
                render_composite_crops(amendment_path,proposal["source_segments"],target,scale=1.35)
                amendment_snippet_combo.configure(values=[""]+sorted(set(amendment_snippet_names+[name])))
                amendment_snippet_var.set(name)
                preview=tk.Toplevel(win); preview.title(f"CV-aanvulling vraag {row['number']} · controle"); preview.geometry("900x760")
                ttk.Label(preview,text="Voorstel uit officiële aanvulling — controleer of dit daadwerkelijk een wijziging voor deze vraag is.",wraplength=850,padding=8).pack(fill="x")
                photo=tk.PhotoImage(file=str(target)); canvas=tk.Canvas(preview); canvas.pack(fill="both",expand=True)
                canvas.create_image(0,0,image=photo,anchor="nw"); canvas.image=photo
                canvas.configure(scrollregion=canvas.bbox("all"))
                self._log(f"CV-aanvullingsfragment gemaakt voor vraag {row['number']}; inhoudelijke koppeling blijft handmatig.")
            except Exception as exc:
                self._error("CV-aanvullingsfragment maken",exc)
                messagebox.showerror("Fragment mislukt",str(exc),parent=win)
        ttk.Button(outer,text="Fragment uit geselecteerde CV-aanvulling maken (automatisch voorstel)",command=make_amendment_snippet).pack(anchor="w",pady=(4,2))
        def edit_amendment_region():
            selected = amendment_list.curselection()
            if len(selected) != 1:
                messagebox.showinfo("Selecteer één aanvulling", "Selecteer precies één officiële CV-aanvulling om visueel af te bakenen.", parent=win)
                return
            amendment_doc = amendment_docs[selected[0]]
            def saved(name, fragment):
                amendment_snippet_var.set(name)
                amendment_snippet_combo.configure(values=[""] + sorted(set(list(amendment_snippet_combo.cget("values")) + [name])))
            self.open_cv_region_editor(row, amendment_doc, saved)
        ttk.Button(outer,text="Geselecteerde CV-aanvulling handmatig afbakenen",command=edit_amendment_region).pack(anchor="w",pady=(2,4))
        def save_draft():
            try:
                meta={key:var.get().strip() for key,var in values.items()}
                if meta["level"] not in ("Havo","Vwo") or not re.fullmatch(r"20\d{2}",meta["year"]) or meta["period"] not in ("1","2","3"):
                    raise ValueError("Niveau, jaartal of tijdvak is ongeldig.")
                if not re.fullmatch(r"\d+",meta["points"]):
                    raise ValueError("Vul het aantal punten van deze vraag in.")
                if any(not meta[x] for x in ("theme","concept","end","focus")):
                    raise ValueError("Vul thema, concept, eindterm en focus in; deze velden zijn nodig voor de website.")
                qtext=qbox.get("1.0","end").strip()
                if not qtext: raise ValueError("De vraagtekst mag niet leeg zijn.")
                cv_doc=next((d for d in matching if d["bestand"]==cv_choice.get()),None)
                if not cv_doc: raise ValueError("Selecteer het juiste correctievoorschrift.")
                qtype=question_type.get()
                try: options=json.loads(obox.get("1.0","end").strip() or "[]")
                except json.JSONDecodeError as exc: raise ValueError(f"De opties zijn geen geldige JSON: {exc}")
                correct=correct_var.get().strip().upper()
                if qtype=="mcq":
                    if not isinstance(options,list) or len(options)<2: raise ValueError("Een meerkeuzevraag heeft minimaal twee opties nodig.")
                    keys=[str(x.get("key","")).upper() for x in options if isinstance(x,dict)]
                    if len(keys)!=len(options) or len(set(keys))!=len(keys) or any(k not in "ABCDEFGH" or len(k)!=1 for k in keys):
                        raise ValueError("Optielabels moeten uniek zijn en van A t/m H lopen.")
                    if correct not in keys: raise ValueError("Selecteer een juist antwoord dat tussen de opties staat.")
                    options=[{"key":str(x["key"]).upper(),"text":str(x.get("text","")).strip()} for x in options]
                    if any(not x["text"] for x in options): raise ValueError("Elke antwoordoptie moet tekst bevatten.")
                else:
                    options=[]; correct=""
                meta["points"]=int(meta["points"]); meta["questionType"]=qtype
                candidate=dict(row)
                record=build_question_record(meta,candidate,qtext,source_doc["opslagbestand"],cv_doc["opslagbestand"])
                confirmed_numbers = sorted({int(x["number"]) for x in self.data.get("vraagkandidaten", [])
                                            if x.get("document_id") == source_doc["id"] and x.get("human_decision") is True})
                structure = self.data.setdefault("exam_structures", {}).get(source_doc["id"])
                if structure is None and self.data.get("exam_structure", {}).get("document_id") == source_doc["id"]:
                    structure = self.data.get("exam_structure")
                structure_errors = validate_exam_structure(structure, source_doc["id"], source_doc["sha256"], confirmed_numbers) if structure else ["structuur_niet_ingesteld"]
                missing_regions = missing_question_regions(structure, [int(row["number"])])                if structure_errors or missing_regions:
                    raise ValueError("Baken eerst het vraagfragment voor deze vraag af in 'Examenstructuur bewerken'. " +
                                     ("Structuurcontrole: " + ", ".join(structure_errors) if structure_errors else "Vraagfragment ontbreekt."))
                linkage = fragments_for_question(structure, row["number"])
                question_fragment = linkage.get("question_fragment")
                if not question_fragment:
                    raise ValueError("Er is nog geen handmatig afgebakend vraagfragment voor deze vraag.")
                cv_region = self.data.get("cv_regions", {}).get(cv_doc["id"], {}).get(str(row["number"]))
                cv_errors = validate_cv_fragment(cv_region or {}, cv_doc, row["number"], "correctievoorschrift")
                if cv_errors:
                    raise ValueError("Baken eerst het volledige correctievoorschrift voor deze vraag handmatig af. " + ", ".join(cv_errors))
                source_path = self.project_dir / "bronnen" / source_doc["opslagbestand"]
                if not source_path.is_file() or sha256(source_path) != source_doc["sha256"]:
                    raise ValueError("De opgaven-PDF is gewijzigd sinds de vraagstructuur is opgeslagen. Voeg de juiste bron opnieuw toe en analyseer opnieuw.")
                cv_path = self.project_dir / "bronnen" / cv_doc["opslagbestand"]
                if not cv_path.is_file() or sha256(cv_path) != cv_doc["sha256"]:
                    raise ValueError("Het geselecteerde correctievoorschrift is gewijzigd sinds de CV-afbakening. Voeg de juiste PDF opnieuw toe.")
                source_analysis = analyze_pdf(source_path)
                source_sizes = {int(p["page"]): (float(p["width"]), float(p["height"])) for p in source_analysis["pages"]}
                question_segments = page_spans_to_segments(question_fragment["page_spans"], source_sizes)
                question_file = f"question-{source_doc['id']}-q{row['number']}-manual.png"
                render_composite_crops(self.project_dir / "bronnen" / source_doc["opslagbestand"],
                                       question_segments, self.project_dir / "snippets" / question_file, scale=1.45)
                question_file_hash = sha256(self.project_dir / "snippets" / question_file)
                cv_analysis = analyze_pdf(self.project_dir / "bronnen" / cv_doc["opslagbestand"])
                cv_sizes = {int(p["page"]): (float(p["width"]), float(p["height"])) for p in cv_analysis["pages"]}
                cv_segments = page_spans_to_segments(cv_region["page_spans"], cv_sizes)
                cv_file = f"cv-{cv_doc['id']}-q{row['number']}-handmatig.png"
                render_composite_crops(self.project_dir / "bronnen" / cv_doc["opslagbestand"],
                                       cv_segments, self.project_dir / "snippets" / cv_file, scale=1.35)
                selected_amendment_docs = [amendment_docs[i] for i in amendment_list.curselection()]
                amendment_regions = []
                for amendment_doc in selected_amendment_docs:
                    region = self.data.get("cv_regions", {}).get(amendment_doc["id"], {}).get(str(row["number"]))
                    errors = validate_cv_fragment(region or {}, amendment_doc, row["number"], "aanvulling")
                    if errors:
                        raise ValueError(f"Baken ook de geselecteerde CV-aanvulling {amendment_doc['bestand']} handmatig af voor vraag {row['number']}. " + ", ".join(errors))
                    amendment_path = self.project_dir / "bronnen" / amendment_doc["opslagbestand"]
                    if not amendment_path.is_file() or sha256(amendment_path) != amendment_doc["sha256"]:
                        raise ValueError(f"De geselecteerde CV-aanvulling {amendment_doc['bestand']} is gewijzigd sinds de afbakening.")
                    amend_analysis = analyze_pdf(amendment_path)
                    amend_sizes = {int(p["page"]): (float(p["width"]), float(p["height"])) for p in amend_analysis["pages"]}
                    amend_segments = page_spans_to_segments(region["page_spans"], amend_sizes)
                    amend_file = f"cv-amend-{amendment_doc['id']}-q{row['number']}-handmatig.png"
                    render_composite_crops(self.project_dir / "bronnen" / amendment_doc["opslagbestand"],
                                           amend_segments, self.project_dir / "snippets" / amend_file, scale=1.35)
                    amendment_regions.append({"document_id": amendment_doc["id"], "source_pdf": amendment_doc["opslagbestand"],
                                              "source_sha256": amendment_doc["sha256"], "fragment": region, "snippet_file": amend_file,
                                              "snippet_sha256": sha256(self.project_dir / "snippets" / amend_file)})
                context_fragments = linkage.get("context_fragments", [])
                context_assets = [dict(context_files[i]) for i in context_list.curselection()]
                for asset in context_assets:
                    asset["snippet_sha256"] = sha256(self.project_dir / "snippets" / asset["file"])
                unconfirmed_captions=[x for x in context_assets if x.get("asset_id") and x.get("caption_human_confirmed") is not True]
                if unconfirmed_captions:
                    raise ValueError("Bevestig of corrigeer eerst het bijschrift van iedere geselecteerde figuur-/tabeluitsnede.")
                context_region_files = []
                context_text_parts = []
                for context_fragment in context_fragments:
                    region_file = f"context-region-{source_doc['id']}-{context_fragment['id']}.png"
                    segments = page_spans_to_segments(context_fragment["page_spans"], source_sizes)
                    render_composite_crops(self.project_dir / "bronnen" / source_doc["opslagbestand"],
                                           segments, self.project_dir / "snippets" / region_file, scale=1.25)
                    region_text = extract_region_text(self.project_dir / "bronnen" / source_doc["opslagbestand"], segments)
                    if region_text:
                        context_text_parts.append(region_text)
                    context_region_files.append({"file": region_file, "fragment_id": context_fragment["id"],
                        "type": context_fragment["type"], "page_spans": list(context_fragment["page_spans"]),
                        "question_numbers": list(context_fragment.get("question_numbers", [])),
                        "text": region_text, "source_document_id": source_doc["id"],
                        "source_pdf": source_doc["opslagbestand"], "source_sha256": source_doc["sha256"],
                        "caption": "Handmatig afgebakende context",
                        "snippet_sha256": sha256(self.project_dir / "snippets" / region_file)})
                context_assets.extend(context_region_files)
                row["context_asset_proposal_files"]=[dict(x) for x in context_files]
                record.update({"exam":meta,"options":options,"correct":correct,
                               "snippet_file":question_file,"snippet_files":[question_file],"question_region_snippet_sha256":question_file_hash,
                               "context_asset_candidates":context_files,"context_asset_files":context_assets,"source_context":context_text_box.get("1.0","end").strip(),"context_text_human_confirmed":True,
                               "context_region_fragments":[{"id":x["id"],"type":x["type"],"page_spans":list(x.get("page_spans", [])),
                                   "question_numbers":list(x.get("question_numbers", [])),"text":next((y["text"] for y in context_region_files if y["fragment_id"]==x["id"]), "")} for x in context_fragments],
                               "cv_snippet_file":cv_file,"cv_snippet_files":[cv_file],
                               "cv_source_region":cv_region,"cv_source_region_file":cv_file,"cv_source_region_sha256":sha256(self.project_dir/"snippets"/cv_file),"cv_source_document_id":cv_doc["id"],"cv_source_sha256":cv_doc["sha256"],
                               "cv_amendment_snippet_files":[x["snippet_file"] for x in amendment_regions],
                               "cv_amendment_snippet_file":amendment_regions[0]["snippet_file"] if amendment_regions else None,
                               "cv_amendment_regions":amendment_regions,
                               "exam_structure_status":"gekoppeld",
                               "exam_structure_document_id":source_doc["id"],
                               "exam_structure_source_sha256":source_doc["sha256"],
                               "exam_structure_fragment_ids":[question_fragment["id"]]+[x["id"] for x in context_fragments],
                               "question_region_fragment_id":question_fragment["id"],"exam_structure_question_number":int(row["number"]),
                               "question_region_page_spans":list(question_fragment.get("page_spans", [])),
                               "source_analysis_invalidated":False,"exam_structure_invalidated":False,"cv_region_invalidated":False,"approval_revoked_reason":None,
                               "uitwerkbijlagen":[appendix_docs[i]["opslagbestand"] for i in appendix_list.curselection()],
                               "cv_amendment_pdfs":[d["opslagbestand"] for d in selected_amendment_docs],
                               "available_appendix_candidates":[d["opslagbestand"] for d in appendix_docs],
                               "available_cv_amendment_candidates":[d["opslagbestand"] for d in amendment_docs],
                               "appendix_match_human_confirmed":True,"cv_amendment_match_human_confirmed":True,
                               "candidate_document_id":row.get("document_id"),
                               "source_match_human_confirmed":(source_doc.get("exam_metadata") or {}).get("source")=="handmatig_bevestigd",
                               "cv_match_human_confirmed":(cv_doc.get("exam_metadata") or {}).get("source")=="handmatig_bevestigd",
                               "cv_display_name":cv_doc["bestand"],
                               "status":"controle_nodig","approved_by_human":False,
                               "record_review_checklist":{"question_text":False,"question_type":False,"points":False,
                                   "answer_options":False,"cv_alignment":False,"images_and_context":False,
                                   "appendices":False,"cv_addenda":False}})
                record["source_page"]=int(row["page"])
                records=self.data.setdefault("vraagrecords",[])
                old_index=next((i for i,x in enumerate(records) if x.get("candidate_document_id")==row.get("document_id") and x.get("number")==row.get("number") and x.get("source_page")==row.get("page")),None)
                if old_index is None: records.append(record)
                else: records[old_index]=record
                row["record_id"]=record["id"]
                self.save_project()
                self._log(f"Conceptrecord {record['id']} opgeslagen. Het record is nadrukkelijk nog niet goedgekeurd.")
                win.destroy()
                messagebox.showinfo("Concept opgeslagen","Het vraagrecord is opgeslagen als concept. Publicatie blijft geblokkeerd totdat alle inhoud, context, CV en bijlagen gecontroleerd en expliciet goedgekeurd zijn.",parent=parent)
            except Exception as exc:
                messagebox.showerror("Concept niet opgeslagen",str(exc),parent=win)
        buttons=ttk.Frame(outer); buttons.pack(fill="x",pady=(10,0))
        ttk.Button(buttons,text="Concept opslaan",command=save_draft).pack(side="right")
        ttk.Button(buttons,text="Annuleren",command=win.destroy).pack(side="right",padx=8)

    def show_records(self):
        if not self.data:
            messagebox.showinfo("Geen project","Open eerst een examenproject.")
            return
        records=self.data.get("vraagrecords",[])
        win=tk.Toplevel(self.root); win.title("Vraagrecords · inhoudelijke eindcontrole"); win.geometry("980x600")
        ttk.Label(win,text=f"{len(records)} concept-vraagrecords. Geen enkel record wordt automatisch goedgekeurd.",padding=10).pack(anchor="w")
        cols=("id","number","page","type","status","approved")
        tree=ttk.Treeview(win,columns=cols,show="headings")
        for col,label,width in [("id","Record-ID",260),("number","Vraag",70),("page","Pagina",80),("type","Type",100),("status","Status",180),("approved","Menselijk akkoord",140)]:
            tree.heading(col,text=label); tree.column(col,width=width,anchor="w")
        tree.pack(fill="both",expand=True,padx=10,pady=8)
        for i,record in enumerate(records):
            tree.insert("","end",iid=str(i),values=(record.get("id"),record.get("number"),record.get("source_page"),
                record.get("exam",{}).get("questionType"),record.get("status"),"Ja" if record.get("approved_by_human") is True else "Nee"))
        def review_selected():
            selection=tree.selection()
            if not selection:
                messagebox.showinfo("Selecteer record","Selecteer eerst een vraagrecord.",parent=win); return
            self.review_question_record(records[int(selection[0])],win)
            tree.set(selection[0],"status",records[int(selection[0])].get("status"))
            tree.set(selection[0],"approved","Ja" if records[int(selection[0])].get("approved_by_human") is True else "Nee")
        buttons=ttk.Frame(win); buttons.pack(fill="x",padx=10,pady=(0,10))
        ttk.Button(buttons,text="Open eindcontrole",command=review_selected).pack(side="left")
        ttk.Button(buttons,text="Vernieuw",command=lambda:(win.destroy(),self.show_records())).pack(side="left",padx=8)

    def review_question_record(self,record,parent):
        win=tk.Toplevel(parent); win.title(f"Eindcontrole · {record.get('id')}"); win.geometry("1040x850")
        win.transient(parent)
        outer=self._scrollable_form(win,padding=12)
        ttk.Label(outer,text="Controleer de volledige originele bron en het correctievoorschrift. Vink pas daarna de onderdelen af.",wraplength=980).pack(anchor="w")
        if record.get("source_analysis_invalidated") is True:
            ttk.Label(outer,text="LET OP: de opgaven-PDF is opnieuw geanalyseerd of de vraagstart is afgewezen. Stel het conceptrecord opnieuw samen vanuit de actuele kandidaat voordat je verdergaat.",foreground="#9b4d00",wraplength=980).pack(anchor="w",pady=4)
        if record.get("exam_structure_invalidated") is True:
            ttk.Label(outer,text="LET OP: de handmatige vraag- of contextgrenzen zijn gewijzigd. Sla dit vraagrecord opnieuw op vanuit de actuele structuur en voer de eindcontrole opnieuw uit.",foreground="#9b4d00",wraplength=980).pack(anchor="w",pady=4)
        if record.get("cv_region_invalidated") is True:
            ttk.Label(outer,text="LET OP: de handmatige CV-/aanvullingsafbakening is gewijzigd. Sla dit vraagrecord opnieuw op en voer de eindcontrole opnieuw uit.",foreground="#9b4d00",wraplength=980).pack(anchor="w",pady=4)
        meta=record.get("exam",{})
        ttk.Label(outer,text=f"{meta.get('level')} {meta.get('year')} tijdvak {meta.get('period')} · vraag {record.get('number')} · {meta.get('points')} punten · {meta.get('questionType')}",padding=(0,6)).pack(anchor="w")
        structure_note = record.get("exam_structure_status", "structuur_niet_ingesteld")
        question_pages = ",".join(str(x.get("page")) for x in record.get("question_region_page_spans", [])) or "geen"
        context_count = len(record.get("context_region_fragments", []))
        ttk.Label(outer, text=f"Visuele examenstructuur: {structure_note} · vraagfragmentpagina's: {question_pages} · gekoppelde contextfragmenten: {context_count}",
                  wraplength=980).pack(anchor="w", pady=(0, 5))
        appendix_candidates=record.get("available_appendix_candidates",[])
        addendum_candidates=record.get("available_cv_amendment_candidates",[])
        ttk.Label(outer,text="Uitwerkbijlagen beschikbaar: "+(", ".join(Path(x).name for x in appendix_candidates) if appendix_candidates else "geen bijbehorende PDF gevonden")+"\nGeselecteerd: "+(", ".join(Path(x).name for x in record.get("uitwerkbijlagen",[])) if record.get("uitwerkbijlagen") else "geen")).pack(anchor="w")
        ttk.Label(outer,text="CV-aanvullingen beschikbaar: "+(", ".join(Path(x).name for x in addendum_candidates) if addendum_candidates else "geen bijbehorende PDF gevonden")+"\nGeselecteerd: "+(", ".join(Path(x).name for x in record.get("cv_amendment_pdfs",[])) if record.get("cv_amendment_pdfs") else "geen")).pack(anchor="w",pady=(0,5))
        ttk.Label(outer,text="Vraagtekst").pack(anchor="w")
        qbox=tk.Text(outer,height=6,wrap="word")
        qbox.pack(fill="x")
        qbox.insert("1.0",record.get("question_text","")); qbox.configure(state="disabled")
        if record.get("source_context"):
            ttk.Label(outer,text="Gekoppelde contexttekst").pack(anchor="w",pady=(6,0))
            context_preview=tk.Text(outer,height=5,wrap="word")
            context_preview.pack(fill="x")
            context_preview.insert("1.0",record.get("source_context",""))
            context_preview.configure(state="disabled")
        if meta.get("questionType")=="mcq":
            option_text="\n".join(f"{x.get('key')}. {x.get('text')}" for x in record.get("options",[]))
            ttk.Label(outer,text=f"Antwoordopties en opgegeven sleutel ({record.get('correct','')})").pack(anchor="w",pady=(5,0))
            ttk.Label(outer,text=option_text or "Geen opties vastgelegd",wraplength=980,justify="left").pack(anchor="w")
        files_frame=ttk.LabelFrame(outer,text="Bronmateriaal en voorlopige uitsneden — visueel nalopen",padding=6,height=360)
        files_frame.pack(fill="both",expand=True,pady=(8,6))
        files_frame.pack_propagate(False)
        image_frame=ttk.Frame(files_frame); image_frame.pack(fill="both",expand=True)
        canvas=tk.Canvas(image_frame,background="#e8ecee")
        sy=ttk.Scrollbar(image_frame,orient="vertical",command=canvas.yview)
        sx=ttk.Scrollbar(image_frame,orient="horizontal",command=canvas.xview)
        canvas.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        sy.pack(side="right",fill="y"); sx.pack(side="bottom",fill="x"); canvas.pack(side="left",fill="both",expand=True)
        photos=[]; y=8
        preview_specs=[]
        source=self.project_dir/"bronnen"/str(record.get("source_pdf",""))
        if source.is_file():
            target=self.project_dir/"analyse"/f"eindcontrole-{record.get('id')}-opgaven.png"
            preview_specs.append(("Originele opgavenpagina",source,int(record.get("source_page",1)),target))
            shown_source_pages={int(record.get("source_page",1))}
            source_page_numbers={int(x["page"]) for x in record.get("question_region_page_spans", [])}
            for fragment in record.get("context_region_fragments", []):
                source_page_numbers.update(int(x["page"]) for x in fragment.get("page_spans", []))
            for asset in record.get("context_asset_files", []):
                if asset.get("source_document_id")==record.get("exam_structure_document_id") and asset.get("page"):
                    source_page_numbers.add(int(asset["page"]))
            if source_page_numbers:
                source_page_count = pdf_page_count(source)
                adjacent_pages = set(source_page_numbers)
                for page_no in source_page_numbers:
                    if page_no > 1: adjacent_pages.add(page_no - 1)
                    if page_no < source_page_count: adjacent_pages.add(page_no + 1)
                source_page_numbers = adjacent_pages
            for page_no in sorted(source_page_numbers-shown_source_pages):
                target=self.project_dir/"analyse"/f"eindcontrole-{record.get('id')}-opgaven-p{page_no}.png"
                preview_specs.append((f"Originele opgavenpagina {page_no}",source,page_no,target))
        cv_snippet=record.get("cv_snippet_file")
        if cv_snippet:
            preview_specs.append(("Handmatig afgebakend CV-fragment",self.project_dir/"snippets"/cv_snippet,None,None))
        cv_path=self.project_dir/"bronnen"/str(record.get("cv_pdf",""))
        if cv_path.is_file():
            cv_spans=record.get("cv_source_region", {}).get("page_spans", [])
            cv_page_count=pdf_page_count(cv_path)
            cv_page_numbers={int(x["page"]) for x in cv_spans}
            for page_no in list(cv_page_numbers):
                if page_no > 1: cv_page_numbers.add(page_no - 1)
                if page_no < cv_page_count: cv_page_numbers.add(page_no + 1)
            for page_no in sorted(cv_page_numbers):
                target=self.project_dir/"analyse"/f"eindcontrole-{record.get('id')}-cv-origineel-p{page_no}.png"
                selected = any(int(x["page"]) == page_no for x in cv_spans)
                label = "afgebakend" if selected else "aangrenzend"
                preview_specs.append((f"Originele CV-pagina {page_no} ({label})",cv_path,page_no,target))
        amendment_snippets=record.get("cv_amendment_snippet_files") or ([record["cv_amendment_snippet_file"]] if record.get("cv_amendment_snippet_file") else [])
        for amendment_index, amendment_snippet in enumerate(amendment_snippets, 1):
            preview_specs.append((f"Handmatig afgebakende CV-aanvulling {amendment_index}",self.project_dir/"snippets"/amendment_snippet,None,None))
        if not cv_snippet:
            # MCQ records do not require a website CV image, but the reviewer
            # must still see the official answer-key region before approval.
            cv_path=self.project_dir/"bronnen"/str(record.get("cv_pdf",""))
            if cv_path.is_file():
                try:
                    cv_analysis=analyze_pdf(cv_path)
                    cv_anchors=[x for x in detect_cv_question_numbers(cv_analysis) if int(x["number"])==int(record.get("number",0))]
                    cv_proposals=propose_question_regions(cv_analysis,detect_cv_question_numbers(cv_analysis))
                    for cv_index,anchor in enumerate(cv_anchors,1):
                        proposal=next((p for p in cv_proposals if p["number"]==int(record["number"]) and p["start_page"]==int(anchor["page"])),None)
                        if proposal:
                            target=self.project_dir/"analyse"/f"eindcontrole-{record.get('id')}-cv-{cv_index}.png"
                            render_composite_crops(cv_path,proposal["source_segments"],target,scale=1.0)
                            preview_specs.append((f"Origineel CV · vraag {record['number']} · anker pagina {anchor['page']}",target,None,None))
                except Exception as exc:
                    self._log(f"CV-voorvertoning niet beschikbaar voor {record.get('id')}: {exc}")
        for idx,name in enumerate(record.get("snippet_files") or ([record["snippet_file"]] if record.get("snippet_file") else []),1):
            preview_specs.append((f"Handmatig afgebakend vraagfragment {idx}",self.project_dir/"snippets"/name,None,None))
        for idx,asset in enumerate(record.get("context_asset_files", []),1):
            preview_specs.append((f"Contextfiguur/-tabel {idx} · pagina {asset.get('page', 'meerdere')} · {asset.get('caption') or asset.get('type') or asset.get('asset_id') or ''}",
                                  self.project_dir/"snippets"/asset["file"],None,None))
        for idx,name in enumerate(record.get("uitwerkbijlagen",[]),1):
            appendix=self.project_dir/"bronnen"/name
            if appendix.is_file():
                for page_no in range(1,analyze_pdf(appendix)["page_count"]+1):
                    target=self.project_dir/"analyse"/f"eindcontrole-{record.get('id')}-bijlage-{idx}-p{page_no}.png"
                    preview_specs.append((f"Uitwerkbijlage {idx} · originele pagina {page_no}",appendix,page_no,target))
        for idx,name in enumerate(record.get("cv_amendment_pdfs",[]),1):
            amendment=self.project_dir/"bronnen"/name
            if amendment.is_file():
                for page_no in range(1,analyze_pdf(amendment)["page_count"]+1):
                    target=self.project_dir/"analyse"/f"eindcontrole-{record.get('id')}-aanvulling-{idx}-p{page_no}.png"
                    preview_specs.append((f"CV-aanvulling {idx} · originele pagina {page_no}",amendment,page_no,target))
        for label,path,page_no,target in preview_specs:
            canvas.create_text(8,y,anchor="nw",text=label)
            y+=24
            try:
                if page_no is not None:
                    render_page(path,page_no,target,scale=0.9)
                    image_path=target
                else:
                    image_path=path
                photo=tk.PhotoImage(file=str(image_path))
                photos.append(photo); canvas.create_image(8,y,image=photo,anchor="nw")
                y+=photo.height()+18
            except Exception as exc:
                canvas.create_text(8,y,anchor="nw",text=f"Voorvertoning niet beschikbaar: {path.name} ({exc})")
                y+=36
        canvas.images=photos; canvas.configure(scrollregion=canvas.bbox("all"))
        ttk.Label(outer,text="Eindcontrole — bevestig alleen wat je daadwerkelijk in de originele PDF hebt gecontroleerd.",padding=(0,5)).pack(anchor="w")
        checklist=record.get("record_review_checklist",{})
        checks=[
            ("question_text","Vraagtekst is volledig, letterlijk correct en bevat alle relevante voorwaarden."),
            ("question_type","Vraagtype en opbouw zijn correct vastgesteld."),
            ("points","Puntenaantal en verdeling zijn gecontroleerd."),
            ("answer_options","Alle antwoordopties zijn volledig en in de juiste volgorde; sleutel is aan CV getoetst."),
            ("cv_alignment","Bijbehorend officiële correctievoorschrift en alle beoordelingsregels zijn gecontroleerd."),
            ("images_and_context","Alle figuren, tabellen, bijschriften, context en uitsneden zijn volledig en juist gekoppeld."),
            ("appendices","Uitwerkbijlagen zijn gecontroleerd; geen bijlage ontbreekt of hoort bij een ander examen."),
            ("cv_addenda","Alle officiële aanvullingen op het correctievoorschrift zijn gecontroleerd.")
        ]
        vars={}
        checkframe=ttk.Frame(outer); checkframe.pack(fill="x")
        required={"question_text","question_type","points","cv_alignment","images_and_context","appendices"}
        if meta.get("questionType")=="mcq": required.add("answer_options")
        required.add("cv_addenda")
        for key,label in checks:
            if key not in required: continue
            var=tk.BooleanVar(value=checklist.get(key,False) is True)
            vars[key]=var
            ttk.Checkbutton(checkframe,text=label,variable=var).pack(anchor="w")
        def approve():
            selected={key:var.get() for key,var in vars.items()}
            errors=review_checklist_errors(record,selected)
            if errors:
                messagebox.showwarning("Eindcontrole onvolledig","Dit record kan nog niet worden goedgekeurd:\n\n"+"\n".join(errors),parent=win)
                return
            record["record_review_checklist"]=selected
            record["approved_by_human"]=True
            record["status"]="goedgekeurd"
            record["approved_at"]=now()
            record["approval_method"]="handmatige_eindcontrole"
            self.save_project()
            self._log(f"Record {record.get('id')} expliciet handmatig goedgekeurd.")
            messagebox.showinfo("Record goedgekeurd","Dit record is nu expliciet door jou goedgekeurd. Het wordt pas meegenomen wanneer het volledige exportpakket alle controles doorstaat.",parent=win)
            win.destroy()
        def revoke():
            record["approved_by_human"]=False
            record["status"]="controle_nodig"
            record["approved_at"]=None
            record["record_review_checklist"]={key:False for key in vars}
            self.save_project()
            self._log(f"Goedkeuring van record {record.get('id')} ingetrokken.")
            win.destroy()
        actions=ttk.Frame(outer); actions.pack(fill="x",pady=(8,0))
        ttk.Button(actions,text="Goedkeuren",command=approve).pack(side="right")
        if record.get("approved_by_human") is True:
            ttk.Button(actions,text="Goedkeuring intrekken",command=revoke).pack(side="right",padx=8)

    def export_project(self):
        if not self.data:
            messagebox.showinfo("Geen project","Open eerst een examenproject."); return
        records=self.data.get("vraagrecords",[])
        if not records:
            messagebox.showinfo("Geen vraagrecords","Maak eerst concept-vraagrecords vanuit bevestigde vraagstarts."); return
        destination=filedialog.askdirectory(title="Kies een nieuwe, lege exportmap")
        if not destination: return
        try:
            result=export_approved_records(records,self.project_dir,Path(destination))
            if not result.get("ok"):
                errors=result.get("errors",[])
                detail="\n".join(f"• {x.get('id','')} · {x.get('error')}" for x in errors[:20])
                if len(errors)>20: detail+=f"\n… en {len(errors)-20} overige blokkades."
                messagebox.showwarning("Export geblokkeerd",f"Er is niets gepubliceerd. Los eerst deze controles op:\n\n{detail}",parent=self.root)
                self._log(f"Export geblokkeerd: {len(errors)} validatiefouten.")
                return
            self._log(f"Exportpakket gemaakt: {result['mcq']} meerkeuzevragen en {result['open']} open vragen.")
            messagebox.showinfo("Exportpakket klaar",f"Veilig exportpakket gemaakt in:\n{result['export_dir']}\n\nEr is niets naar de live website gepubliceerd.",parent=self.root)
        except Exception as exc:
            self._error("Exportpakket maken",exc)
            messagebox.showerror("Export mislukt",str(exc),parent=self.root)

    def create_snippet_proposal(self, rows, tree, parent):
        selected=tree.selection()
        if not selected:
            messagebox.showinfo("Selecteer kandidaat","Selecteer eerst een kandidaat.")
            return
        candidate_index=int(selected[0])
        row=rows[candidate_index]
        doc=next((d for d in self.data["documenten"] if d["id"]==row.get("document_id")),None)
        if not doc:
            messagebox.showerror("Bron ontbreekt","Het bijbehorende bronbestand is niet gevonden.")
            return
        source=self.project_dir/"bronnen"/doc["opslagbestand"]
        try:
            analysis=analyze_pdf(source)
            candidates=[x for x in self.data.get("vraagkandidaten",[]) if x.get("document_id")==doc["id"]]
            proposals=propose_question_regions(analysis,candidates)
            proposal=next((p for p in proposals if p["number"]==row["number"] and p["start_page"]==row["page"] and abs(p["source_segments"][0]["bbox"][1]-max(0.0,row["bbox"][1]-8.0))<1.0),None)
            if not proposal:
                messagebox.showinfo("Geen fragment","Er kon geen voorlopig fragment worden samengesteld.")
                return
            files=[]
            for idx,segment in enumerate(proposal["source_segments"],1):
                name=f"voorstel-k{candidate_index+1}-q{row['number']}-p{segment['page']}-deel{idx}.png"
                target=self.project_dir/"snippets"/name
                render_crop(source,segment["page"],segment["bbox"],target,scale=1.8)
                files.append(name)
            row["snippet_proposal_files"]=files
            row["snippet_proposal_warning"]=proposal["warning"]
            # Context crops are kept separate from the question snippets and
            # can never be exported as approved question images by accident.
            context_files=[]
            seen_assets=set()
            for ref_index,ref in enumerate(proposal.get("context_candidates",[]),1):
                context_candidates=list(ref.get("asset_candidates",[])[:4])+list(ref.get("text_region_candidates",[])[:6])
                for asset_index,asset in enumerate(context_candidates,1):
                    asset_id=asset.get("asset_id") or f"text-p{asset.get('page')}-{ref_index}-{asset_index}"
                    if asset_id in seen_assets or not asset.get("bbox"):
                        continue
                    seen_assets.add(asset_id)
                    name=f"contextvoorstel-k{candidate_index+1}-q{row['number']}-{asset_id}.png"
                    target=self.project_dir/"snippets"/name
                    render_crop(source,int(asset["page"]),asset["bbox"],target,scale=1.8)
                    context_files.append({"file":name,"page":asset["page"],"caption":asset.get("caption"),
                                          "asset_id":asset_id,"asset_kind":asset.get("asset_kind","source_text"),
                                          "bbox":list(asset["bbox"]),"source_document_id":doc["id"],
                                          "source_sha256":doc["sha256"],"status":"handmatige_controle_verplicht"})
            row["context_asset_proposal_files"]=context_files
            self.save_project()
            win=tk.Toplevel(parent); win.title(f"Voorlopig fragment vraag {row['number']}"); win.geometry("900x800")
            ttk.Label(win,text="VOORSTEL – NIET GECONTROLEERD OF PUBLICATIEKLAAR",foreground="#9b4d00",padding=8).pack(fill="x")
            ttk.Label(win,text=proposal["warning"],wraplength=860,padding=8).pack(fill="x")
            refs=proposal.get("context_candidates",[])
            ref_summaries=[]
            for ref in refs:
                captions=", ".join(f"p. {x['page']}: {x['text']}" for x in ref.get("caption_matches",[])) or "geen bijschrift gevonden"
                assets=len(ref.get("asset_candidates",[]))
                text_regions=len(ref.get("text_region_candidates",[]))
                ref_summaries.append(f"{ref.get('kind')} {ref.get('number') or ''}: {captions}; {assets} mogelijke beeldregio('s), {text_regions} tekstregio('s); status: {ref.get('link_status')}")
            ref_text="Mogelijke contextverwijzingen (alleen suggesties): "+("; ".join(ref_summaries) if ref_summaries else "geen automatische verwijzing gevonden")
            ttk.Label(win,text=ref_text,wraplength=860,padding=8).pack(fill="x")
            text_box=tk.Text(win,height=5,wrap="word",font=("Segoe UI",9))
            text_box.pack(fill="x",padx=8)
            text_box.insert("1.0",proposal.get("text_proposal",""))
            text_box.configure(state="disabled")
            frame=ttk.Frame(win); frame.pack(fill="both",expand=True)
            canvas=tk.Canvas(frame,background="#dce3e6")
            sy=ttk.Scrollbar(frame,orient="vertical",command=canvas.yview)
            sx=ttk.Scrollbar(frame,orient="horizontal",command=canvas.xview)
            canvas.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
            sy.pack(side="right",fill="y"); sx.pack(side="bottom",fill="x"); canvas.pack(side="left",fill="both",expand=True)
            photos=[]; y=0
            for name in files:
                photo=tk.PhotoImage(file=str(self.project_dir/"snippets"/name))
                photos.append(photo); canvas.create_image(0,y,image=photo,anchor="nw")
                y += photo.height()+12
            for item in context_files:
                canvas.create_text(8,y+8,anchor="nw",text=f"CONTEXTKANDIDAAT · pagina {item['page']} · {item.get('caption') or item['asset_id']} · handmatig controleren")
                photo=tk.PhotoImage(file=str(self.project_dir/"snippets"/item["file"]))
                photos.append(photo); canvas.create_image(0,y+30,image=photo,anchor="nw")
                y += photo.height()+44
            canvas.images=photos
            canvas.configure(scrollregion=canvas.bbox("all"))
            self._log(f"Voorlopige snippet(s) voor vraag {row['number']} gemaakt. Visuele controle blijft verplicht.")
        except Exception as exc:
            self._error("Voorlopige snippet maken",exc)
            messagebox.showerror("Snippetvoorstel mislukt","Er kon geen betrouwbaar fragment worden gemaakt. De originele PDF is niet gewijzigd. Details staan in logs.")

    def preview_candidate(self, rows, tree, parent):
        selected=tree.selection()
        if not selected:
            messagebox.showinfo("Selecteer kandidaat","Selecteer eerst een kandidaat.")
            return
        row=rows[int(selected[0])]
        doc=next((d for d in self.data["documenten"] if d["id"]==row.get("document_id")),None)
        if not doc:
            messagebox.showerror("Bron ontbreekt","Het bijbehorende bronbestand is niet gevonden.")
            return
        source=self.project_dir/"bronnen"/doc["opslagbestand"]
        target=self.project_dir/"analyse"/f"preview-{doc['id']}-p{row['page']}.png"
        try:
            render_page(source,row["page"],target)
            win=tk.Toplevel(parent); win.title(f"Originele PDF-pagina {row['page']} – {doc['bestand']}")
            win.geometry("900x800")
            frame=ttk.Frame(win); frame.pack(fill="both",expand=True)
            canvas=tk.Canvas(frame,background="#dce3e6")
            sy=ttk.Scrollbar(frame,orient="vertical",command=canvas.yview)
            sx=ttk.Scrollbar(frame,orient="horizontal",command=canvas.xview)
            canvas.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
            sy.pack(side="right",fill="y"); sx.pack(side="bottom",fill="x"); canvas.pack(side="left",fill="both",expand=True)
            photo=tk.PhotoImage(file=str(target))
            canvas.create_image(0,0,image=photo,anchor="nw")
            canvas.image=photo
            canvas.configure(scrollregion=canvas.bbox("all"))
            ttk.Label(win,text=f"Originele bronpagina · kandidaat vraag {row['number']} · markering is nog niet automatisch goedgekeurd",padding=8).pack(fill="x")
        except Exception as exc:
            self._error("Originele PDF-pagina tonen",exc)
            messagebox.showerror("Voorvertoning mislukt","Deze pagina kon niet worden getoond. Controleer of de PDF nog in de projectmap staat. Details staan in logs.")


    def edit_exam_structure(self):
        """Visually define full-width page spans after explicit question-number review."""
        if not self.data:
            messagebox.showinfo("Eerst een project", "Open eerst een examenproject.")
            return
        source_docs = [d for d in self.data.get("documenten", []) if d.get("type_voorstel") == "opgaven"]
        if not source_docs:
            messagebox.showinfo("Geen opgaven-PDF", "Voeg eerst de opgaven-PDF toe en bevestig het documenttype.")
            return
        if len(source_docs) > 1:
            chooser = tk.Toplevel(self.root); chooser.title("Kies opgaven-PDF"); chooser.transient(self.root)
            ttk.Label(chooser, text="Kies het examen waarvan je de structuur wilt afbakenen.", padding=10).pack(anchor="w")
            listing = tk.Listbox(chooser, width=72, height=min(8, len(source_docs)))
            listing.pack(fill="both", expand=True, padx=10, pady=8)
            for doc in source_docs: listing.insert("end", doc["bestand"])
            def open_chosen():
                sel = listing.curselection()
                if not sel: return
                doc = source_docs[sel[0]]; chooser.destroy(); self._open_structure_editor(doc)
            ttk.Button(chooser, text="Open editor", command=open_chosen).pack(pady=(0,10))
            return
        self._open_structure_editor(source_docs[0])

    def _open_structure_editor(self, doc):        candidates = [x for x in self.data.get("vraagkandidaten", []) if x.get("document_id") == doc["id"]]
        if not candidates:
            messagebox.showwarning("Eerst vraagstarts analyseren", "Analyseer eerst de vraagstarts van deze opgaven-PDF en controleer de kandidaten.")
            return
        unresolved = [x for x in candidates if x.get("human_decision") not in (True, False)]
        if unresolved:
            messagebox.showwarning("Vraagnummering nog niet bevestigd",
                f"Er zijn nog {len(unresolved)} vraagstartkandidaten zonder menselijke beslissing. Beoordeel eerst alle gevonden nummers (vraagstart of geen vraag). De contexteditor blijft tot die tijd geblokkeerd.")
            self.show_candidates()
            return
        question_numbers = sorted({int(x["number"]) for x in candidates if x.get("human_decision") is True})
        if not question_numbers:
            messagebox.showwarning("Geen bevestigde vragen", "Er is nog geen enkele vraagstart bevestigd.")
            return
        source = self.project_dir / "bronnen" / doc["opslagbestand"]
        if not source.is_file() or sha256(source) != doc.get("sha256"):
            structures = self.data.setdefault("exam_structures", {})
            old_structure = structures.get(doc["id"]) or self.data.get("exam_structure")
            if old_structure and old_structure.get("document_id") == doc["id"]:
                structures[doc["id"]] = mark_structure_stale(old_structure, "De bron-PDF wijkt af van de vastgelegde SHA-256.")
                self.data["exam_structure"] = structures[doc["id"]]
                self.save_project()
            messagebox.showerror("Bronbestand gewijzigd", "De oorspronkelijke opgaven-PDF is gewijzigd of ontbreekt. De bestaande afbakening is ongeldig verklaard. Voeg de juiste PDF opnieuw toe en analyseer opnieuw.")
            return
        analysis = analyze_pdf(source)
        page_count = int(analysis["page_count"])
        page_sizes = {int(p["page"]): (float(p["width"]), float(p["height"])) for p in analysis["pages"]}
        structures = self.data.setdefault("exam_structures", {})
        existing = structures.get(doc["id"])
        if existing is None and self.data.get("exam_structure", {}).get("document_id") == doc["id"]:
            existing = self.data.get("exam_structure")
        if existing and existing.get("document_id") == doc["id"] and existing.get("source_sha256") == doc["sha256"]:
            fragments = json.loads(json.dumps(existing.get("fragments", []), ensure_ascii=False))
        else:
            fragments = []
        original_structure_signature = json.dumps(fragments, ensure_ascii=False, sort_keys=True)
        win = tk.Toplevel(self.root); win.title(f"Examenstructuur · {doc['bestand']}"); win.geometry("1280x900")
        win.transient(self.root)
        header = ttk.Frame(win, padding=(12, 8)); header.pack(fill="x")
        ttk.Label(header, text="Eerst de vraagnummering bevestigd; nu context- en vraagfragmenten afbakenen.",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(header, text="Sleep de dunne zwarte lijnen. Binnen de lijnen blijft de PDF wit; erbuiten ligt een doorschijnende lichtgrijze markering. De bron-PDF wordt nooit aangepast.",
                  wraplength=1180).pack(anchor="w", pady=(3, 0))
        body = ttk.Frame(win, padding=8); body.pack(fill="both", expand=True)
        left = ttk.Frame(body, width=245); left.pack(side="left", fill="y", padx=(0, 10))
        right = ttk.Frame(body); right.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="Fragmenttype").pack(anchor="w")
        type_var = tk.StringVar(value="context_intro")
        type_box = ttk.Combobox(left, textvariable=type_var, state="readonly",
            values=["context_intro", "vraagcontext", "vraag", "tussenliggende_context"], width=25)
        type_box.pack(fill="x", pady=(2, 8))
        ttk.Label(left, text="Koppelen aan vraagnummer(s)").pack(anchor="w")
        qlist = tk.Listbox(left, selectmode="extended", exportselection=False, height=12)
        qlist.pack(fill="x", pady=(2, 8))
        for number in question_numbers: qlist.insert("end", f"Vraag {number}")
        def set_default_links(*_):
            qlist.selection_clear(0, "end")
            if type_var.get() == "context_intro":
                for i in range(qlist.size()): qlist.selection_set(i)
        type_box.bind("<<ComboboxSelected>>", set_default_links)
        set_default_links()
        ttk.Label(left, text="Bestaande fragmenten").pack(anchor="w", pady=(4, 2))
        fragment_tree = ttk.Treeview(left, columns=("type", "pages", "links"), show="tree headings", height=12)
        fragment_tree.heading("#0", text="Fragment")
        fragment_tree.heading("type", text="Type"); fragment_tree.column("type", width=85)
        fragment_tree.heading("pages", text="Pagina's"); fragment_tree.column("pages", width=55)
        fragment_tree.heading("links", text="Vragen"); fragment_tree.column("links", width=65)
        fragment_tree.pack(fill="both", expand=True)
        ttk.Label(left, text="Tip: maak een fragment op de eerste pagina en voeg daarna de volgende pagina's in oplopende volgorde toe.",
                  wraplength=230).pack(anchor="w", pady=8)
        nav = ttk.Frame(right); nav.pack(fill="x", pady=(0, 6))
        page_var = tk.IntVar(value=1)
        displayed_page = 1
        ttk.Button(nav, text="◀", width=3, command=lambda: change_page(-1)).pack(side="left")
        ttk.Label(nav, text="Pagina").pack(side="left", padx=(8, 3))
        page_spin = tk.Spinbox(nav, from_=1, to=page_count, textvariable=page_var, width=5, command=lambda: jump_question_page())
        page_spin.pack(side="left")
        ttk.Label(nav, text=f"van {page_count}").pack(side="left", padx=(4, 12))
        frame = ttk.Frame(right); frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(frame, background="white", highlightthickness=0)
        sy = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        sx = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.pack(side="right", fill="y"); sx.pack(side="bottom", fill="x"); canvas.pack(side="left", fill="both", expand=True)
        actions = ttk.Frame(right); actions.pack(fill="x", pady=(8, 0))
        top_y, bottom_y = 0.06, 0.94
        photo = None
        page_image_width = 1
        page_image_height = 1
        drag_target = None
        top_line = bottom_line = None
        overlay_items = []
        def selected_links():
            return [question_numbers[i] for i in qlist.curselection()]
        def selected_fragment():
            sel = fragment_tree.selection()
            return fragments[int(sel[0])] if sel else None
        def redraw_guides():
            nonlocal top_line, bottom_line, overlay_items
            for item in overlay_items:
                canvas.delete(item)
            overlay_items = []
            if photo is None: return
            y0, y1 = top_y * page_image_height, bottom_y * page_image_height
            overlay_items.append(canvas.create_rectangle(0, 0, page_image_width, y0,
                fill="#c8c8c8", stipple="gray50", outline=""))
            overlay_items.append(canvas.create_rectangle(0, y1, page_image_width, page_image_height,
                fill="#c8c8c8", stipple="gray50", outline=""))
            if top_line: canvas.delete(top_line)
            if bottom_line: canvas.delete(bottom_line)
            top_line = canvas.create_line(0, y0, page_image_width, y0, fill="black", width=1)
            bottom_line = canvas.create_line(0, y1, page_image_width, y1, fill="black", width=1)
            canvas.tag_raise(top_line); canvas.tag_raise(bottom_line)
            canvas.configure(scrollregion=(0, 0, page_image_width, page_image_height))
        def load_span_for_page():
            nonlocal top_y, bottom_y
            frag = selected_fragment()
            span = next((x for x in (frag or {}).get("page_spans", []) if int(x["page"]) == page_var.get()), None)
            if span:
                top_y, bottom_y = float(span["top"]), float(span["bottom"])
            else:
                top_y, bottom_y = 0.06, 0.94
        def show_page():
            nonlocal photo, page_image_width, page_image_height, displayed_page
            try:
                number = max(1, min(page_count, int(page_var.get())))
            except (ValueError, tk.TclError):
                number = 1
            page_var.set(number)
            displayed_page = number
            target = self.project_dir / "analyse" / f"structuur-{doc['id']}-p{number}.png"
            render_page(source, number, target, scale=1.05)
            photo = tk.PhotoImage(file=str(target))
            page_image_width, page_image_height = photo.width(), photo.height()
            canvas.delete("all")
            canvas.create_image(0, 0, image=photo, anchor="nw")
            canvas.image = photo
            load_span_for_page()
            redraw_guides()
        def change_page(delta):
            frag = selected_fragment()
            if frag and any(int(x["page"]) == displayed_page for x in frag.get("page_spans", [])):
                update_page_span()
            page_var.set(max(1, min(page_count, int(page_var.get()) + delta)))
            show_page()
        def on_press(event):
            nonlocal drag_target
            y = canvas.canvasy(event.y)
            top_px, bottom_px = top_y * page_image_height, bottom_y * page_image_height
            if abs(y - top_px) <= 12: drag_target = "top"
            elif abs(y - bottom_px) <= 12: drag_target = "bottom"
            else: drag_target = None
        def on_drag(event):
            nonlocal top_y, bottom_y
            if not drag_target: return
            y = max(0.0, min(float(page_image_height), canvas.canvasy(event.y))) / page_image_height
            if drag_target == "top": top_y = min(y, bottom_y - 0.01)
            else: bottom_y = max(y, top_y + 0.01)
            redraw_guides()
        canvas.bind("<Button-1>", on_press); canvas.bind("<B1-Motion>", on_drag)
        def refresh_fragment_list():
            for iid in fragment_tree.get_children(): fragment_tree.delete(iid)
            for index, frag in enumerate(fragments):
                pages = ",".join(str(x["page"]) for x in frag.get("page_spans", []))
                links = ",".join(str(x) for x in frag.get("question_numbers", []))
                fragment_tree.insert("", "end", iid=str(index), text=frag.get("id", f"Fragment {index+1}"),
                    values=(frag.get("type"), pages, links))
        def save_structure():
            nonlocal original_structure_signature
            current = selected_fragment()
            if current and any(int(x["page"]) == displayed_page for x in current.get("page_spans", [])):
                span = make_page_span(displayed_page, top_y, bottom_y)
                current["page_spans"] = [span if int(x["page"]) == span["page"] else dict(x)
                                         for x in current["page_spans"]]
            new_signature = json.dumps(fragments, ensure_ascii=False, sort_keys=True)
            structure_changed = new_signature != original_structure_signature
            structure = make_exam_structure(doc, fragments, question_numbers)
            errors = validate_exam_structure(structure, doc["id"], doc["sha256"], question_numbers)
            if errors:
                messagebox.showerror("Structuur niet opgeslagen", "Controleer eerst:\\n" + "\\n".join(errors), parent=win)
                return False
            if structure_changed:
                for record in self.data.get("vraagrecords", []):
                    if record.get("candidate_document_id") == doc["id"]:
                        record["exam_structure_invalidated"] = True
                        record["approved_by_human"] = False
                        record["status"] = "structuur_opnieuw_te_controleren"
                        record["approved_at"] = None
                        record["approval_revoked_reason"] = "Vraag-/contextgrenzen of koppelingen zijn gewijzigd; stel dit vraagrecord opnieuw samen."
                        record["record_review_checklist"] = {key: False for key in record.get("record_review_checklist", {})}
                original_structure_signature = new_signature
            self.data.setdefault("exam_structures", {})[doc["id"]] = structure
            # Keep the original single-document key for older project readers.
            self.data["exam_structure"] = structure
            self.save_project()
            self._log(f"Examenstructuur opgeslagen: {len(fragments)} fragment(en), bron {doc['bestand']}.")
            return True
        def create_fragment():
            try:
                kind = type_var.get()
                links = selected_links()
                if kind == "context_intro" and not links: links = question_numbers[:]
                span = make_page_span(displayed_page, top_y, bottom_y)
                fragment = make_fragment(kind, span, links, question_numbers,
                    f"frag-{doc['id'][:8]}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}")
                fragments.append(fragment)
                refresh_fragment_list()
                fragment_tree.selection_set(str(len(fragments)-1))
                save_structure()
            except Exception as exc:
                messagebox.showerror("Fragment niet opgeslagen", str(exc), parent=win)
        def update_page_span():
            frag = selected_fragment()
            if not frag:
                messagebox.showinfo("Selecteer fragment", "Selecteer eerst het fragment waarvan je de huidige paginagrens wilt aanpassen.", parent=win)
                return
            try:
                updated = dict(frag)
                spans = [dict(x) for x in frag.get("page_spans", [])]
                span = make_page_span(displayed_page, top_y, bottom_y)
                existing_index = next((i for i, item in enumerate(spans) if int(item["page"]) == span["page"]), None)
                if existing_index is None:
                    spans.append(span)
                else:
                    spans[existing_index] = span
                spans.sort(key=lambda x: int(x["page"]))
                updated["page_spans"] = spans
                fragments[int(fragment_tree.selection()[0])] = updated
                refresh_fragment_list()
                fragment_tree.selection_set(str(fragments.index(updated)))
                save_structure()
            except Exception as exc:
                messagebox.showerror("Paginagrens niet bijgewerkt", str(exc), parent=win)
        def append_page():
            frag = selected_fragment()
            if not frag:
                messagebox.showinfo("Selecteer fragment", "Selecteer eerst het fragment waaraan je deze pagina wilt toevoegen.", parent=win)
                return
            try:
                updated = append_page_span(frag, make_page_span(displayed_page, top_y, bottom_y))
                fragments[int(fragment_tree.selection()[0])] = updated
                refresh_fragment_list()
                fragment_tree.selection_set(str(fragments.index(updated)))
                save_structure()
            except Exception as exc:
                messagebox.showerror("Pagina niet toegevoegd", str(exc), parent=win)
        def delete_fragment():
            sel = fragment_tree.selection()
            if not sel: return
            index = int(sel[0])            if not messagebox.askyesno("Fragment verwijderen", "Weet je zeker dat je dit fragment wilt verwijderen?", parent=win): return
            fragments.pop(index); refresh_fragment_list(); save_structure()
        def load_selected_fragment(_event=None):
            load_span_for_page(); redraw_guides()
            frag = selected_fragment()
            if frag:
                type_var.set(frag.get("type", "vraagcontext"))
                qlist.selection_clear(0, "end")
                for i, number in enumerate(question_numbers):
                    if number in frag.get("question_numbers", []): qlist.selection_set(i)
        def update_links():
            frag = selected_fragment()
            if not frag: return
            new_type = type_var.get()
            links = selected_links()
            if new_type == "vraag" and len(links) != 1:
                messagebox.showwarning("Vraagfragment", "Een vraagfragment moet aan precies één vraagnummer gekoppeld zijn.", parent=win)
                return
            if new_type != "vraag" and not links:
                if new_type == "context_intro":
                    links = question_numbers[:]
                    messagebox.showinfo("Inleiding", "De contextinleiding is standaard aan alle bevestigde vragen gekoppeld.", parent=win)
                else:
                    messagebox.showwarning("Context zonder vraagkoppeling",
                        "Koppel dit contextfragment aan minimaal één vraag. Anders zou het materiaal bij geen enkele vraag worden getoond.", parent=win)
                    return
            frag["type"] = new_type
            frag["question_numbers"] = links
            save_structure(); refresh_fragment_list()
        fragment_tree.bind("<<TreeviewSelect>>", load_selected_fragment)
        ttk.Button(actions, text="Nieuw fragment opslaan", command=create_fragment).pack(side="left")
        ttk.Button(actions, text="Huidige paginagrens bijwerken", command=update_page_span).pack(side="left", padx=8)
        ttk.Button(actions, text="Pagina toevoegen aan geselecteerd fragment", command=append_page).pack(side="left", padx=8)
        ttk.Button(actions, text="Fragmenttype en koppeling opslaan", command=update_links).pack(side="left")
        ttk.Button(actions, text="Verwijderen", command=delete_fragment).pack(side="left", padx=8)
        def save_and_close():
            if save_structure():
                win.destroy()
        ttk.Button(actions, text="Structuur opslaan en sluiten", command=save_and_close).pack(side="right")
        refresh_fragment_list()
        if fragments: fragment_tree.selection_set("0")
        def jump_question_page(_event=None):
            current = selected_fragment()
            if current and any(int(x["page"]) == displayed_page for x in current.get("page_spans", [])):
                update_page_span()
            show_page()
        page_spin.bind("<Return>", jump_question_page)
        show_page()

    def open_cv_region_editor(self, record, cv_doc, on_saved=None):
        """Manually delimit a question's correction-scheme region on the untouched source PDF."""
        source = self.project_dir / "bronnen" / cv_doc["opslagbestand"]
        if not source.is_file() or sha256(source) != cv_doc.get("sha256"):
            messagebox.showerror("CV-bron gewijzigd", "De oorspronkelijke CV-PDF ontbreekt of is gewijzigd. Voeg het juiste bestand opnieuw toe voordat je grenzen vastlegt.")
            return
        role = cv_doc.get("type_voorstel", "correctievoorschrift")
        if role not in ("correctievoorschrift", "aanvulling"):
            messagebox.showerror("Verkeerd documenttype", "Kies een correctievoorschrift of officiële aanvulling.")
            return
        try:
            analysis = analyze_pdf(source)
            page_count = int(analysis["page_count"])
            page_sizes = {int(p["page"]): (float(p["width"]), float(p["height"])) for p in analysis["pages"]}
        except Exception as exc:
            self._error("CV-pagina's voorbereiden", exc)
            return
        question_number = int(record["number"])
        all_regions = self.data.setdefault("cv_regions", {})
        doc_regions = all_regions.setdefault(cv_doc["id"], {})
        existing = doc_regions.get(str(question_number), {})
        spans = [dict(x) for x in existing.get("page_spans", [])]
        win = tk.Toplevel(self.root)
        win.title(f"{'CV-aanvulling' if role == 'aanvulling' else 'Correctievoorschrift'} · vraag {question_number}")
        win.geometry("1120x850")
        win.transient(self.root)
        ttk.Label(win, text=f"Bak de volledige beoordelingsinformatie voor vraag {question_number} af in {cv_doc['bestand']}.",
                  padding=10, wraplength=1080).pack(anchor="w")
        ttk.Label(win, text="Gebruik dezelfde twee dunne zwarte lijnen. Buiten de selectie staat een lichte grijze arcering. Neem alle beoordelingsregels, punten en eventuele vervolgpagina's mee.",
                  padding=(10, 0, 10, 8), wraplength=1080).pack(anchor="w")
        nav = ttk.Frame(win, padding=(10, 4)); nav.pack(fill="x")
        page_var = tk.IntVar(value=spans[0]["page"] if spans else 1)
        displayed_page = int(page_var.get())
        ttk.Button(nav, text="◀", command=lambda: change_page(-1)).pack(side="left")
        ttk.Label(nav, text="Pagina").pack(side="left", padx=6)
        spin = tk.Spinbox(nav, from_=1, to=page_count, textvariable=page_var, width=5)
        spin.pack(side="left")
        ttk.Label(nav, text=f"van {page_count}").pack(side="left", padx=6)
        ttk.Label(nav, text=f"Afgebakende pagina's: {', '.join(str(x['page']) for x in spans) or 'nog geen'}").pack(side="left", padx=12)
        frame = ttk.Frame(win); frame.pack(fill="both", expand=True, padx=10, pady=4)
        canvas = tk.Canvas(frame, background="white", highlightthickness=1, highlightbackground="#b8b8b8")
        sy = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        sx = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.pack(side="right", fill="y"); sx.pack(side="bottom", fill="x"); canvas.pack(side="left", fill="both", expand=True)
        photo = None
        image_width = image_height = 1
        top_y, bottom_y = 0.06, 0.94
        drag_target = None
        dirty = False
        line_ids = []
        shade_ids = []
        def current_span():
            return make_page_span(displayed_page, top_y, bottom_y)
        def store_current_span(force=False):
            nonlocal dirty
            existing = any(int(x["page"]) == displayed_page for x in spans)
            if not force and not dirty and not existing:
                return
            span = current_span()
            spans[:] = [x for x in spans if int(x["page"]) != span["page"]]
            spans.append(span)
            spans.sort(key=lambda x: int(x["page"]))
            dirty = False
        def draw_guides():
            nonlocal line_ids, shade_ids
            for item in line_ids + shade_ids:
                canvas.delete(item)
            line_ids, shade_ids = [], []
            if photo is None:
                return
            y0, y1 = top_y * image_height, bottom_y * image_height
            shade_ids.append(canvas.create_rectangle(0, 0, image_width, y0, fill="#c8c8c8", stipple="gray50", outline=""))
            shade_ids.append(canvas.create_rectangle(0, y1, image_width, image_height, fill="#c8c8c8", stipple="gray50", outline=""))
            line_ids.append(canvas.create_line(0, y0, image_width, y0, fill="black", width=1))
            line_ids.append(canvas.create_line(0, y1, image_width, y1, fill="black", width=1))
            for item in line_ids:
                canvas.tag_raise(item)
            canvas.configure(scrollregion=(0, 0, image_width, image_height))
        def show_page():
            nonlocal photo, image_width, image_height, top_y, bottom_y, displayed_page
            try:
                page_no = max(1, min(page_count, int(page_var.get())))
            except (ValueError, tk.TclError):
                page_no = 1
            page_var.set(page_no)
            displayed_page = page_no
            saved = next((x for x in spans if int(x["page"]) == page_no), None)
            top_y, bottom_y = (float(saved["top"]), float(saved["bottom"])) if saved else (0.06, 0.94)
            target = self.project_dir / "analyse" / f"cv-region-{cv_doc['id']}-p{page_no}.png"
            render_page(source, page_no, target, scale=1.05)
            photo = tk.PhotoImage(file=str(target))
            image_width, image_height = photo.width(), photo.height()
            canvas.delete("all")
            canvas.create_image(0, 0, image=photo, anchor="nw")
            canvas.image = photo
            draw_guides()
            page_label.configure(text=f"Afgebakende pagina's: {', '.join(str(x['page']) for x in spans) or 'nog geen'}")
        def change_page(delta):
            try:
                store_current_span()
                page_var.set(max(1, min(page_count, displayed_page + delta)))
                show_page()
            except Exception as exc:
                messagebox.showerror("Grens niet opgeslagen", str(exc), parent=win)
        page_label = ttk.Label(nav, text="")
        page_label.pack(side="left", padx=10)
        def on_press(event):
            nonlocal drag_target
            y = canvas.canvasy(event.y)
            drag_target = "top" if abs(y - top_y * image_height) <= 12 else ("bottom" if abs(y - bottom_y * image_height) <= 12 else None)
        def on_drag(event):
            nonlocal top_y, bottom_y, dirty
            if not drag_target:
                return
            y = max(0.0, min(float(image_height), canvas.canvasy(event.y))) / image_height
            if drag_target == "top":
                top_y = min(y, bottom_y - 0.01)
            else:
                bottom_y = max(y, top_y + 0.01)
            dirty = True
            draw_guides()
        canvas.bind("<Button-1>", on_press); canvas.bind("<B1-Motion>", on_drag)
        actions = ttk.Frame(win, padding=10); actions.pack(fill="x")
        def save_region():
            try:
                store_current_span()
                fragment = make_cv_fragment(cv_doc, question_number, spans,
                    document_role=role)
                errors = validate_cv_fragment(fragment, cv_doc, question_number, role)
                if errors:
                    raise ValueError("Controleer de CV-afbakening: " + ", ".join(errors))
                segments = page_spans_to_segments(spans, page_sizes)
                prefix = "cv-amend" if role == "aanvulling" else "cv"
                name = f"{prefix}-{cv_doc['id']}-q{question_number}-handmatig.png"
                target = self.project_dir / "snippets" / name
                render_composite_crops(source, segments, target, scale=1.35)
                rendered_hash = sha256(target)
                for saved_record in self.data.get("vraagrecords", []):
                    if int(saved_record.get("number", -1)) != question_number:
                        continue
                    if role == "correctievoorschrift":
                        references_region = (saved_record.get("cv_source_document_id") == cv_doc["id"]
                            or saved_record.get("cv_pdf") == cv_doc["opslagbestand"])
                        old_region = saved_record.get("cv_source_region")
                        old_hash = saved_record.get("cv_source_region_sha256")
                    else:
                        old_items = [x for x in saved_record.get("cv_amendment_regions", [])
                                     if x.get("document_id") == cv_doc["id"]]
                        references_region = (cv_doc["opslagbestand"] in saved_record.get("cv_amendment_pdfs", [])
                            or bool(old_items))
                        old_region = old_items[0].get("fragment") if old_items else None
                        old_hash = old_items[0].get("snippet_sha256") if old_items else None
                    if references_region and (old_region != fragment or old_hash != rendered_hash):
                        saved_record["cv_region_invalidated"] = True
                        saved_record["approved_by_human"] = False
                        saved_record["status"] = "cv_fragment_opnieuw_te_controleren"
                        saved_record["approved_at"] = None
                        saved_record["approval_revoked_reason"] = "CV-regio of CV-uitsnede gewijzigd; stel het vraagrecord opnieuw samen en voer de eindcontrole opnieuw uit."
                        saved_record["record_review_checklist"] = {key: False for key in saved_record.get("record_review_checklist", {})}
                doc_regions[str(question_number)] = fragment
                self.save_project()
                if on_saved:
                    on_saved(name, fragment)
                self._log(f"CV-fragment voor vraag {question_number} handmatig afgebakend uit {cv_doc['bestand']}.")
                preview = tk.Toplevel(win); preview.title(f"Gecontroleerde CV-uitsnede · vraag {question_number}"); preview.geometry("850x700")
                p = tk.PhotoImage(file=str(target))
                c = tk.Canvas(preview, background="white"); c.pack(fill="both", expand=True)
                c.create_image(0, 0, image=p, anchor="nw"); c.image = p
                c.configure(scrollregion=c.bbox("all"))
                messagebox.showinfo("CV-fragment opgeslagen", "De handmatig afgebakende CV-regio en de uitsnede zijn opgeslagen. Controleer de volledige uitsnede in de voorvertoning.", parent=win)
                win.destroy()
            except Exception as exc:
                messagebox.showerror("CV-fragment niet opgeslagen", str(exc), parent=win)
        ttk.Button(actions, text="Deze pagina toevoegen / bijwerken", command=lambda: (store_current_span(True), page_label.configure(text=f"Afgebakende pagina's: {', '.join(str(x['page']) for x in spans)}"))).pack(side="left")
        ttk.Button(actions, text="CV-fragment opslaan en uitsnede maken", command=save_region).pack(side="left", padx=8)
        ttk.Button(actions, text="Sluiten", command=win.destroy).pack(side="right")
        def jump_to_page(_event=None):
            try:
                store_current_span()
                show_page()
            except Exception as exc:
                messagebox.showerror("Paginagrens niet opgeslagen", str(exc), parent=win)
        spin.configure(command=jump_to_page)
        spin.bind("<Return>", jump_to_page)
        show_page()

    def selected_doc(self):
        selected = self.table.selection()
        if not selected or not self.data:
            return None
        idx = int(selected[0])
        return self.data["documenten"][idx]

    def show_document(self, _event=None):
        doc = self.selected_doc()
        if not doc:
            return
        analysis = self.project_dir / "analyse" / f"{doc['id']}.json"
        extracted = json.loads(analysis.read_text(encoding="utf-8"))
        preview = tk.Toplevel(self.root)        preview.title(doc["bestand"])
        preview.geometry("850x620")
        header = ttk.Frame(preview, padding=12)
        header.pack(fill="x")
        ttk.Label(header, text=f"{doc['bestand']}  |  {doc['pagina_aantal']} pagina's", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(header, text=f"Voorstel: {doc['type_voorstel']} ({doc['type_zekerheid']:.0%}) · SHA-256: {doc['sha256']}", wraplength=800).pack(anchor="w")
        if doc.get("pagina_zonder_tekst"):
            ttk.Label(header,text="Let op: op deze pagina's ontbreekt een bruikbare tekstlaag; OCR/visuele controle nodig: "+", ".join(map(str,doc["pagina_zonder_tekst"])),foreground="#9b4d00",wraplength=800).pack(anchor="w",pady=(5,0))
        box = tk.Text(preview, wrap="word", font=("Segoe UI", 10))
        box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for page in extracted["pagina_tekst"]:
            box.insert("end", f"\n{'='*25} PAGINA {page['pagina']} {'='*25}\n")
            box.insert("end", page["tekst"] or "[Geen selecteerbare tekst gevonden; mogelijk scan of afbeelding.]")
        box.configure(state="disabled")

    def correct_type(self):
        doc = self.selected_doc()
        if not doc:
            messagebox.showinfo("Selecteer een document", "Selecteer eerst een PDF in de lijst.")
            return
        choices = ["opgaven", "correctievoorschrift", "uitwerkbijlage", "aanvulling", "onbekend"]
        initial = doc.get("exam_metadata") or infer_exam_metadata(doc.get("bestand","")) or self.data.get("exam_metadata",{})
        win = tk.Toplevel(self.root)
        win.title("Documenttype en examenidentiteit bevestigen")
        win.transient(self.root)
        win.grab_set()
        frame=ttk.Frame(win,padding=16); frame.pack(fill="both",expand=True)
        ttk.Label(frame, text=f"Document: {doc['bestand']}",wraplength=520).grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,8))
        ttk.Label(frame, text="Documenttype").grid(row=1,column=0,sticky="w",pady=5)
        choice = tk.StringVar(value=doc["type_voorstel"])
        ttk.Combobox(frame, textvariable=choice, values=choices, state="readonly", width=28).grid(row=1,column=1,sticky="ew",pady=5)
        ttk.Label(frame,text="Examenidentiteit (nodig om opgaven, CV en bijlagen veilig te koppelen)").grid(row=2,column=0,columnspan=2,sticky="w",pady=(12,4))
        level=tk.StringVar(value=initial.get("level","Havo"))
        year=tk.StringVar(value=str(initial.get("year","")))
        period=tk.StringVar(value=str(initial.get("period","1")))
        for row,label,var,widget in [
            (3,"Niveau",level,ttk.Combobox(frame,textvariable=level,values=["Havo","Vwo"],state="readonly",width=24)),
            (4,"Jaar",year,ttk.Entry(frame,textvariable=year,width=27)),
            (5,"Tijdvak",period,ttk.Combobox(frame,textvariable=period,values=["1","2","3"],state="readonly",width=24))
        ]:
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky="w",pady=4)
            widget.grid(row=row,column=1,sticky="ew",pady=4)
        ttk.Label(frame,text="Controleer dit per PDF. De bestandsnaam of projectmetadata kan onjuist zijn; alleen opslaan betekent dat jij de identiteit van dit document bevestigt.",wraplength=520).grid(row=6,column=0,columnspan=2,sticky="w",pady=(10,4))
        def apply():
            old = doc["type_voorstel"]
            new = choice.get()
            if new in ("opgaven","correctievoorschrift","uitwerkbijlage","aanvulling"):
                if level.get() not in ("Havo","Vwo") or not re.fullmatch(r"20\d{2}",year.get().strip()) or period.get() not in ("1","2","3"):
                    messagebox.showerror("Examenidentiteit onvolledig","Controleer niveau, jaartal en tijdvak.",parent=win)
                    return
                doc["exam_metadata"]={"level":level.get(),"year":year.get().strip(),"period":period.get(),
                                      "confidence":1.0,"source":"handmatig_bevestigd"}
            doc["type_voorstel"] = new
            doc["type_zekerheid"] = 1.0
            doc["status"] = "handmatig_bevestigd"
            self.data["beslissingen"].append({"document_id": doc["id"], "van": old, "naar": new, "tijd": now(), "reden": "handmatige bevestiging documenttype en examenidentiteit"})
            learn_decision(self.project_dir/"kennisbank",{
                "pattern_key":"document_role:pdf-name-pattern",
                "chosen":new,"accepted":True,"scope":"voorstel_voor_toekomstige_documentherkenning",
                "filename":doc["bestand"],"previous":old,"human_decision":True,
                "exam_identity":doc.get("exam_metadata")})
            if new=="opgaven":
                self.data["exam_metadata"]={k:doc["exam_metadata"][k] for k in ("level","year","period")}
            self.save_project()
            self.refresh()
            self._log(f"Herkenning en examenidentiteit bevestigd: {doc['bestand']} → {new} ({doc.get('exam_metadata',{}).get('level','')} {doc.get('exam_metadata',{}).get('year','')} tijdvak {doc.get('exam_metadata',{}).get('period','')}).")
            win.destroy()
        buttons=ttk.Frame(frame); buttons.grid(row=7,column=0,columnspan=2,sticky="ew",pady=(12,0))
        ttk.Button(buttons,text="Bevestigen",command=apply).pack(side="right")
        ttk.Button(buttons,text="Annuleren",command=win.destroy).pack(side="right",padx=8)
        frame.columnconfigure(1,weight=1)

    def save_project(self):
        if not self.data or not self.project_dir:
            return
        self.data["bijgewerkt"] = now()
        temp = self.project_dir / (PROJECT_FILE + ".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.project_dir / PROJECT_FILE)
        self.project_label.configure(text=f"Project: {self.data['naam']}  ·  {self.project_dir}")

    def refresh(self):
        for item in self.table.get_children():
            self.table.delete(item)
        if not self.data:
            return
        for idx, doc in enumerate(self.data["documenten"]):
            self.table.insert("", "end", iid=str(idx), values=(
                doc["bestand"], doc["type_voorstel"], doc["pagina_aantal"],
                f"{doc['type_zekerheid']:.0%}", doc["status"].replace("_", " ")
            ))
        count = len(self.data["documenten"])
        todo = sum(d["status"] == "controle_nodig" for d in self.data["documenten"])
        candidates = len(self.data.get("vraagkandidaten", []))
        self.status.configure(text=f"{count} document(en) opgenomen · {candidates} vraagstartkandidaten · {todo} documentherkenningen vragen controle · publicatie geblokkeerd.")

def main():
    root = tk.Tk()
    try:
        from tkinter import simpledialog
        tk.simpledialog = simpledialog
        ExamApp(root)
        root.mainloop()
    except Exception:
        details=traceback.format_exc()
        try:
            log_dir=(Path(sys.executable).parent if getattr(sys,"frozen",False) else Path(__file__).parent)/"logs"
            log_dir.mkdir(parents=True,exist_ok=True)
            (log_dir/f"crash-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt").write_text(details,encoding="utf-8")
        except Exception:
            pass
        messagebox.showerror("Programma tijdelijk gestopt","Het programma is onverwacht gestopt. Start het opnieuw. Als het probleem terugkomt, stuur dan het nieuwste bestand uit de map logs mee.")
        raise


if __name__ == "__main__":
    main()