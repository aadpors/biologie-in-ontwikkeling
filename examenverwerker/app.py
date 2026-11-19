from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import traceback
import tempfile
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from exporter import export_approved_records
from engine import analyze_pdf, detect_question_candidates, detect_cv_question_numbers, compare_question_numbering, learn_decision, render_page, render_crop, propose_question_regions, classify_document_role, infer_exam_metadata, question_pattern_key, suggest_from_learning, extract_candidate_text, detect_question_type, detect_context_references, match_correction_documents, match_exam_documents, build_question_record, render_composite_crops, review_checklist_errors, extract_region_text, pdf_page_count, pixel_rect_to_pdf_bbox
from structure import FRAGMENT_TYPES, make_page_span, make_fragment, append_page_span, make_exam_structure, validate_exam_structure, mark_structure_stale, fragments_for_question, make_cv_fragment, validate_cv_fragment, page_spans_to_segments, missing_question_regions
from batch_import import group_exam_documents, batch_document_warnings, validate_batch_documents, resolve_examens_root

APP_VERSION = "0.13.1"
PROJECT_FILE = "project.json"

def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def fit_window(window, desired_width, desired_height, min_width=820, min_height=560):
    """Size and center a window so it stays within the current display."""
    window.update_idletasks()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    width = min(desired_width, max(720, screen_width - 40))
    height = min(desired_height, max(520, screen_height - 90))
    window.minsize(min(min_width, width), min(min_height, height))
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


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
        fit_window(self.root, 1380, 900, 900, 620)
        self.project_dir = None
        self.data = None
        app_base=Path(sys.executable).parent if getattr(sys,"frozen",False) else Path(__file__).parent
        self.app_base = app_base
        self.examens_root = resolve_examens_root(app_base)
        self.knowledge_dir=app_base/"kennisbank"
        self._style()
        self._build()
        self._welcome()

    def _style(self):
        """Warm, card-based interface inspired by the original biology website."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.colors = {
            "canvas": "#F5F7F7", "surface": "#FFFFFF", "wine": "#741D3B",
            "wine_dark": "#552039", "wine_soft": "#F7EDF1", "teal": "#168B8B",
            "teal_dark": "#0F7275", "teal_soft": "#E8F3F2", "orange": "#E89A38",
            "ink": "#24313B", "muted": "#63717B", "line": "#DCE3E6",
            "green": "#2D7955", "green_soft": "#EAF2EB", "table_alt": "#F7F9F9"
        }
        self.root.configure(background=self.colors["canvas"])
        style.configure("App.TFrame", background=self.colors["canvas"])
        style.configure("Card.TFrame", background=self.colors["surface"])
        style.configure("Title.TLabel", background=self.colors["canvas"],
                        font=("Segoe UI", 23, "bold"), foreground=self.colors["wine"])
        style.configure("Section.TLabel", background=self.colors["surface"],
                        font=("Segoe UI", 12, "bold"), foreground=self.colors["wine"])
        style.configure("Muted.TLabel", background=self.colors["surface"],
                        font=("Segoe UI", 9), foreground=self.colors["muted"])
        style.configure("Body.TLabel", background=self.colors["surface"],
                        font=("Segoe UI", 10), foreground=self.colors["ink"])
        style.configure("Metric.TLabel", background=self.colors["surface"],
                        font=("Segoe UI", 22, "bold"), foreground=self.colors["wine"])
        style.configure("MetricCaption.TLabel", background=self.colors["surface"],
                        font=("Segoe UI", 9), foreground=self.colors["muted"])
        style.configure("Project.TLabel", background=self.colors["surface"],
                        font=("Segoe UI", 12, "bold"), foreground=self.colors["wine"])
        style.configure("Status.TLabel", background=self.colors["teal_soft"],
                        font=("Segoe UI", 9), foreground=self.colors["teal_dark"],
                        padding=(10, 7))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                        padding=(15, 10), background=self.colors["teal"],
                        foreground="#FFFFFF", borderwidth=0, focusthickness=0)
        style.map("Accent.TButton", background=[("active", self.colors["teal_dark"]),
                  ("pressed", self.colors["teal_dark"])], foreground=[("disabled", "#D9E5E5")])
        style.configure("Wine.TButton", font=("Segoe UI", 10, "bold"),
                        padding=(15, 10), background=self.colors["wine"],
                        foreground="#FFFFFF", borderwidth=0, focusthickness=0)
        style.map("Wine.TButton", background=[("active", self.colors["wine_dark"]),
                  ("pressed", self.colors["wine_dark"])])
        style.configure("Secondary.TButton", font=("Segoe UI", 9, "bold"),
                        padding=(11, 8), background="#EEF2F3",
                        foreground=self.colors["ink"], borderwidth=1,
                        relief="flat", bordercolor=self.colors["line"])
        style.map("Secondary.TButton", background=[("active", "#E2EAEC")])
        style.configure("Notebook", background=self.colors["canvas"], borderwidth=0, tabmargins=(0, 8, 0, 0))
        style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"),
                        padding=(18, 11), background="#E9EFF0", foreground=self.colors["muted"])
        style.map("TNotebook.Tab", background=[("selected", self.colors["wine"])],
                  foreground=[("selected", "#FFFFFF")])
        style.configure("Treeview", rowheight=36, font=("Segoe UI", 9),
                        background=self.colors["surface"], fieldbackground=self.colors["surface"],
                        foreground=self.colors["ink"], borderwidth=0, relief="flat")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                        background="#EDF2F3", foreground=self.colors["muted"],
                        padding=(10, 11), relief="flat")
        style.map("Treeview", background=[("selected", "#F1DDE5")],
                  foreground=[("selected", self.colors["ink"])])
        style.configure("Vertical.TScrollbar", background="#DCE3E6",
                        troughcolor="#F5F7F7", bordercolor="#F5F7F7", arrowsize=12)

    def _build(self):
        """Integrated examination workbench: source PDF, documents, candidates and review."""
        self.root.title("Biologie Examenverwerker")
        fit_window(self.root, 1440, 920, 980, 640)
        shell = ttk.Frame(self.root, style="App.TFrame", padding=10)
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="App.TFrame")
        header.pack(fill="x", pady=(0, 8))
        brand = ttk.Frame(header, style="App.TFrame")
        brand.pack(side="left", fill="x", expand=True)
        ttk.Label(brand, text="BIOLOGIE EXAMENVERWERKER", style="Title.TLabel").pack(anchor="w")
        ttk.Label(brand, text="Werkruimte voor volledige, visueel gecontroleerde examenverwerking",
                  style="Muted.TLabel").pack(anchor="w", pady=(1, 0))
        self.project_label = ttk.Label(header, text="Nog geen examen geopend", style="Project.TLabel")
        self.project_label.pack(side="right", padx=10)

        toolbar = ttk.Frame(shell, style="App.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        actions = [
            ("Nieuw project", self.new_project, "Secondary.TButton"),
            ("Project openen", self.open_project, "Secondary.TButton"),
            ("＋ Examens importeren", self.import_year_set, "Accent.TButton"),
            ("Vraagstarts analyseren", self.analyze_questions, "Secondary.TButton"),
            ("Structuur bewerken", self.edit_exam_structure, "Secondary.TButton"),
            ("Vraagrecord maken", self._workspace_create_record, "Secondary.TButton"),
            ("Eindcontrole", self.show_records, "Secondary.TButton"),
            ("Exportpakket", self.export_project, "Wine.TButton"),
        ]
        for label, callback, style in actions[:4]:
            ttk.Button(toolbar, text=label, command=callback, style=style).pack(side="left", padx=(0, 5))
        toolbar_secondary = ttk.Frame(shell, style="App.TFrame")
        toolbar_secondary.pack(fill="x", pady=(0, 6))
        for label, callback, style in actions[4:]:
            ttk.Button(toolbar_secondary, text=label, command=callback, style=style).pack(side="left", padx=(0, 5))

        correction_bar = ttk.Frame(shell, style="App.TFrame")
        correction_bar.pack(fill="x", pady=(0, 7))
        ttk.Button(correction_bar, text="Correcties uit Biologie-controle importeren",
                   command=self._workspace_import_corrections).pack(side="left", padx=(0, 5))
        ttk.Button(correction_bar, text="Beoordelingen exporteren",
                   command=self._workspace_export_corrections).pack(side="left")
        ttk.Label(correction_bar,
                  text="Bewaart besluiten, notities, vraagnummercorrecties en exacte PDF-posities.",
                  style="Muted.TLabel").pack(side="left", padx=10)

        workspace = ttk.Panedwindow(shell, orient="horizontal")
        workspace.pack(fill="both", expand=True)
        left = ttk.Frame(workspace, style="App.TFrame", padding=(0, 0, 6, 0))
        right = ttk.Frame(workspace, style="App.TFrame", padding=(6, 0, 0, 0))
        workspace.add(left, weight=3)
        workspace.add(right, weight=8)

        # Left column: source documents and question candidates.
        docs_card = ttk.LabelFrame(left, text="DOCUMENTEN", padding=7)
        docs_card.pack(fill="both", expand=True, pady=(0, 7))
        doc_actions = ttk.Frame(docs_card)
        doc_actions.pack(fill="x", pady=(0, 5))
        ttk.Button(doc_actions, text="PDF's toevoegen", command=self.add_pdfs).pack(side="left")
        ttk.Button(doc_actions, text="Type corrigeren", command=self.correct_type).pack(side="left", padx=4)
        ttk.Button(doc_actions, text="Metadata", command=self.edit_exam_metadata).pack(side="left")
        doc_cols = ("name", "type", "pages", "state")
        self.table = ttk.Treeview(docs_card, columns=doc_cols, show="headings", height=7, selectmode="browse")
        for col, label, width in [
            ("name", "Bestand", 210), ("type", "Type", 105),
            ("pages", "Pag.", 42), ("state", "Status", 105)
        ]:
            self.table.heading(col, text=label)
            self.table.column(col, width=width, minwidth=35, anchor="w" if col in ("name", "type", "state") else "center")
        doc_scroll = ttk.Scrollbar(docs_card, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=doc_scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        doc_scroll.pack(side="right", fill="y")
        self.table.bind("<<TreeviewSelect>>", self._workspace_document_selected)
        self.table.bind("<Double-1>", self.show_document)

        candidates_card = ttk.LabelFrame(left, text="VRAAGSTARTS EN CONTROLE", padding=7)
        candidates_card.pack(fill="both", expand=True)
        filter_row = ttk.Frame(candidates_card)
        filter_row.pack(fill="x", pady=(0, 5))
        self._workspace_filter = tk.StringVar(value="Alle kandidaten")
        ttk.Label(filter_row, text="Filter").pack(side="left")
        filter_box = ttk.Combobox(filter_row, textvariable=self._workspace_filter,
            values=["Alle kandidaten", "Nog te beoordelen", "Sterke signalen", "Zwakke signalen", "Dubbele nummers", "Niet in CV"],
            state="readonly", width=20)
        filter_box.pack(side="left", padx=5, fill="x", expand=True)
        filter_box.bind("<<ComboboxSelected>>", lambda _e: self._workspace_refresh_candidates())
        candidate_cols = ("number", "page", "signal", "status")
        self.candidate_tree = ttk.Treeview(candidates_card, columns=candidate_cols, show="headings",
                                            height=12, selectmode="browse")
        for col, label, width in [
            ("number", "Nr.", 42), ("page", "Pag.", 48), ("signal", "Signaal", 62), ("status", "Beoordeling", 145)
        ]:
            self.candidate_tree.heading(col, text=label)
            self.candidate_tree.column(col, width=width, minwidth=32,
                anchor="center" if col in ("number", "page", "signal") else "w")
        candidate_scroll = ttk.Scrollbar(candidates_card, orient="vertical", command=self.candidate_tree.yview)
        self.candidate_tree.configure(yscrollcommand=candidate_scroll.set)
        self.candidate_tree.pack(side="left", fill="both", expand=True)
        candidate_scroll.pack(side="right", fill="y")
        self.candidate_tree.bind("<<TreeviewSelect>>", self._workspace_candidate_selected)

        # Right column: original PDF at full working size and persistent review controls.
        right_split = ttk.Panedwindow(right, orient="horizontal")
        right_split.pack(fill="both", expand=True)
        viewer = ttk.LabelFrame(right_split, text="ORIGINELE PDF · BRON VAN WAARHEID", padding=7)
        review = ttk.LabelFrame(right_split, text="VRAAGCONTROLE", padding=9)
        right_split.add(viewer, weight=7)
        right_split.add(review, weight=3)

        page_toolbar = ttk.Frame(viewer)
        page_toolbar.pack(fill="x", pady=(0, 5))
        ttk.Button(page_toolbar, text="◀", width=3, command=lambda: self._workspace_change_page(-1)).pack(side="left")
        self._workspace_page_label = ttk.Label(page_toolbar, text="Pagina — / —")
        self._workspace_page_label.pack(side="left", padx=8)
        ttk.Button(page_toolbar, text="▶", width=3, command=lambda: self._workspace_change_page(1)).pack(side="left")
        ttk.Separator(page_toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(page_toolbar, text="−", width=3, command=lambda: self._workspace_zoom_by(0.8)).pack(side="left")
        ttk.Button(page_toolbar, text="100%", command=self._workspace_reset_zoom).pack(side="left", padx=3)
        ttk.Button(page_toolbar, text="+", width=3, command=lambda: self._workspace_zoom_by(1.25)).pack(side="left")
        ttk.Button(page_toolbar, text="Markeer ontbrekende vraag", command=self._workspace_start_manual_mark).pack(side="right")
        canvas_wrap = ttk.Frame(viewer)
        canvas_wrap.pack(fill="both", expand=True)
        self.pdf_canvas = tk.Canvas(canvas_wrap, background="#DCE2E5", highlightthickness=0,
                                    cursor="crosshair")
        pdf_y = ttk.Scrollbar(canvas_wrap, orient="vertical", command=self.pdf_canvas.yview)
        pdf_x = ttk.Scrollbar(viewer, orient="horizontal", command=self.pdf_canvas.xview)
        self.pdf_canvas.configure(yscrollcommand=pdf_y.set, xscrollcommand=pdf_x.set)
        self.pdf_canvas.pack(side="left", fill="both", expand=True)
        pdf_y.pack(side="right", fill="y")
        pdf_x.pack(fill="x")
        self.pdf_canvas.bind("<Button-1>", self._workspace_canvas_click)
        self.pdf_canvas.bind("<MouseWheel>", lambda e: self.pdf_canvas.yview_scroll(int(-e.delta / 120), "units"))

        self._workspace_summary = ttk.Label(review, text="Selecteer een document of vraagstart.",
                                            style="Body.TLabel", wraplength=330, justify="left")
        self._workspace_summary.pack(fill="x", anchor="w", pady=(0, 8))
        number_row = ttk.Frame(review)
        number_row.pack(fill="x", pady=(0, 5))
        ttk.Label(number_row, text="Vraagnummer").pack(side="left")
        self._workspace_number = tk.StringVar()
        ttk.Entry(number_row, textvariable=self._workspace_number, width=7).pack(side="left", padx=6)
        ttk.Button(number_row, text="Opslaan", command=self._workspace_save_candidate).pack(side="right")

        ttk.Label(review, text="Vraagtekst / opdrachtformulering").pack(anchor="w")
        self._workspace_text = tk.Text(review, height=12, wrap="word", font=("Segoe UI", 9),
                                       undo=True, padx=7, pady=6)
        self._workspace_text.pack(fill="both", expand=True, pady=(3, 5))
        self._workspace_detected_details = ttk.Label(review, text="", style="Muted.TLabel",
            wraplength=330, justify="left")
        self._workspace_detected_details.pack(fill="x", pady=(0, 6))
        ttk.Label(review, text="Notitie bij de beoordeling").pack(anchor="w")
        self._workspace_note = tk.Text(review, height=4, wrap="word", font=("Segoe UI", 9),
                                       undo=True, padx=7, pady=5)
        self._workspace_note.pack(fill="x", pady=(3, 8))
        ttk.Button(review, text="Tekst en notitie bewaren", command=self._workspace_save_candidate,
                   style="Secondary.TButton").pack(fill="x", pady=(0, 8))
        ttk.Separator(review).pack(fill="x", pady=5)
        ttk.Label(review, text="Beoordeel deze vraagstart").pack(anchor="w", pady=(0, 5))
        ttk.Button(review, text="✓  Dit is een vraag", command=lambda: self._workspace_decide(True),
                   style="Accent.TButton").pack(fill="x", pady=3)
        ttk.Button(review, text="✕  Geen vraag", command=lambda: self._workspace_decide(False),
                   style="Secondary.TButton").pack(fill="x", pady=3)
        ttk.Button(review, text="?  Twijfel / later beoordelen", command=lambda: self._workspace_decide(None),
                   style="Secondary.TButton").pack(fill="x", pady=3)
        ttk.Button(review, text="Concept-vraagrecord samenstellen",
                   command=self._workspace_create_record, style="Wine.TButton").pack(fill="x", pady=(10, 3))
        ttk.Button(review, text="Onderdrukte nummerkandidaten bekijken",
                   command=lambda: self.show_suppressed_candidates(self.root)).pack(fill="x", pady=3)

        footer = ttk.Frame(shell, style="App.TFrame")
        footer.pack(fill="x", pady=(7, 0))
        self.status = ttk.Label(footer, text="Importeer examens of open een bestaand project.", style="Status.TLabel")
        self.status.pack(side="left", fill="x", expand=True)
        log_frame = ttk.LabelFrame(shell, text="ACTIVITEIT EN MELDINGEN", padding=(7, 4))
        log_frame.pack(fill="x", pady=(6, 0))
        self.log = tk.Text(log_frame, height=3, wrap="word", font=("Segoe UI", 8),
                           background="#FBFCFC", foreground=self.colors["ink"],
                           insertbackground=self.colors["ink"], relief="flat", padx=7, pady=4)
        self.log.pack(fill="x")
        self.log.configure(state="disabled")

        self._workspace_temp = tempfile.TemporaryDirectory(prefix="biologie-werkruimte-")
        self._workspace_zoom = 1.0
        self._workspace_scale = 1.0
        self._workspace_photo = None
        self._workspace_doc_id = None
        self._workspace_page = 1
        self._workspace_rows = []
        self._workspace_selected = None
        self._workspace_mark_mode = False
        self.root.after(150, self._workspace_refresh)

    def _workspace_doc(self):
        if not self.data:
            return None
        return next((d for d in self.data.get("documenten", [])
                     if d.get("id") == self._workspace_doc_id), None)

    def _workspace_document_selected(self, _event=None):
        if not self.data or not self.table.selection():
            return
        index = int(self.table.selection()[0])
        docs = self.data.get("documenten", [])
        if index >= len(docs):
            return
        doc = docs[index]
        self._workspace_doc_id = doc.get("id")
        self._workspace_page = 1
        self._workspace_selected = None
        self._workspace_refresh_candidates()
        self._workspace_render_page()

    def _workspace_refresh(self):
        if not self.data:
            self._workspace_rows = []
            self._workspace_refresh_candidates()
            self._workspace_summary.configure(text="Selecteer of importeer een examen. De originele PDF verschijnt hier.")
            self.pdf_canvas.delete("all")
            self._workspace_page_label.configure(text="Pagina — / —")
            return
        docs = self.data.get("documenten", [])
        if not self._workspace_doc_id or not any(d.get("id") == self._workspace_doc_id for d in docs):
            preferred = next((d for d in docs if d.get("type_voorstel") == "opgaven"), docs[0] if docs else None)
            self._workspace_doc_id = preferred.get("id") if preferred else None
        if self._workspace_doc_id:
            for item in self.table.get_children():
                self.table.delete(item)
            for index, doc in enumerate(docs):
                self.table.insert("", "end", iid=str(index), values=(
                    doc.get("bestand", ""), doc.get("type_voorstel", "onbekend"),
                    doc.get("pagina_aantal", "—"), str(doc.get("status", "onbekend")).replace("_", " ")))
            target = next((str(i) for i,d in enumerate(docs) if d.get("id")==self._workspace_doc_id), None)
            if target and target in self.table.get_children():
                self.table.selection_set(target)
                self.table.focus(target)
            self._workspace_refresh_candidates()
            if self._workspace_selected is None:
                self._workspace_render_page()
        else:
            self._workspace_rows = []
            self._workspace_refresh_candidates()
            self.pdf_canvas.delete("all")
            self._workspace_page_label.configure(text="Pagina — / —")
            self._workspace_summary.configure(text="Dit project bevat nog geen documenten. Voeg PDF's toe of importeer een examen.")

    def _workspace_refresh_candidates(self, select_index=None):
        if not hasattr(self, "candidate_tree"):
            return
        for item in self.candidate_tree.get_children():
            self.candidate_tree.delete(item)
        all_rows = (self.data or {}).get("vraagkandidaten", [])
        rows = [r for r in all_rows if r.get("document_id") == self._workspace_doc_id]
        filter_value = self._workspace_filter.get() if hasattr(self, "_workspace_filter") else "Alle kandidaten"
        number_counts = {}
        for row in rows:
            number_counts[row.get("number")] = number_counts.get(row.get("number"), 0) + 1
        if filter_value == "Nog te beoordelen":
            rows = [r for r in rows if r.get("human_decision") is None]
        elif filter_value == "Sterke signalen":
            rows = [r for r in rows if float(r.get("confidence", 0) or 0) >= 0.9]
        elif filter_value == "Zwakke signalen":
            rows = [r for r in rows if float(r.get("confidence", 0) or 0) < 0.9]
        elif filter_value == "Dubbele nummers":
            rows = [r for r in rows if number_counts.get(r.get("number"), 0) > 1]
        elif filter_value == "Niet in CV":
            rows = [r for r in rows if r.get("cv_number_match") is False]
        self._workspace_rows = rows
        for index, row in enumerate(rows):
            status = row.get("status", "controle_nodig").replace("_", " ")
            self.candidate_tree.insert("", "end", iid=str(index), values=(
                row.get("number", "—"), row.get("page", "—"),
                f"{float(row.get('confidence', 0) or 0):.0%}", status))
        if rows:
            if select_index is None:
                select_index = next((i for i,r in enumerate(rows) if r.get("human_decision") is None), 0)
            select_index = max(0, min(int(select_index), len(rows)-1))
            self.candidate_tree.selection_set(str(select_index))
            self.candidate_tree.focus(str(select_index))
            self.candidate_tree.see(str(select_index))
            self._workspace_candidate_selected()
        else:
            self._workspace_selected = None
            self._workspace_summary.configure(text="Geen vraagkandidaten voor dit document of deze filter. Je kunt op de PDF een ontbrekende vraag handmatig aanwijzen.")
            self._workspace_text.delete("1.0", "end")
            self._workspace_note.delete("1.0", "end")
            self._workspace_number.set("")
            self._workspace_render_page()

    def _workspace_candidate_selected(self, _event=None):
        if not self.candidate_tree.selection():
            return
        index = int(self.candidate_tree.selection()[0])
        if index >= len(self._workspace_rows):
            return
        row = self._workspace_rows[index]
        self._workspace_selected = row
        self._workspace_number.set(str(row.get("number", "")))
        self._workspace_text.delete("1.0", "end")
        self._workspace_text.insert("1.0", row.get("vraagtekst_voorstel", "") or "")
        self._workspace_note.delete("1.0", "end")
        self._workspace_note.insert("1.0", row.get("review_note", "") or "")
        check = row.get("vraagtype_controle", {})
        cv = "CV-match" if row.get("cv_number_match") is True else (
            "Nummer niet in CV" if row.get("cv_number_match") is False else "CV niet beschikbaar")
        self._workspace_summary.configure(text=(
            f"Vraag {row.get('number')} · PDF-pagina {row.get('page')} · "
            f"signaal {float(row.get('confidence',0) or 0):.0%}\n"
            f"{check.get('type','type nog controleren')} · {cv}\n"
            f"{row.get('reason','')}\nStatus: {row.get('status','controle_nodig').replace('_',' ')}"))
        options = check.get("options", [])
        option_text = "Antwoordopties: " + (" · ".join(
            f"{x.get('label','?')} {x.get('text','')}" for x in options) if options else "geen opties herkend")
        references = row.get("context_verwijzingen", [])
        reference_text = "Verwijzingen: " + (" · ".join(
            f"{x.get('kind','')} {x.get('number') or ''}" for x in references) if references else "geen expliciete verwijzingen herkend")
        self._workspace_detected_details.configure(text=option_text + "\n" + reference_text)
        self._workspace_page = int(row.get("page", 1))
        self._workspace_render_page()

    def _workspace_render_page(self):
        doc = self._workspace_doc()
        if not doc:
            return
        source = self.project_dir / "bronnen" / doc["opslagbestand"]
        if not source.is_file():
            self.pdf_canvas.delete("all")
            self._workspace_summary.configure(text="Het bronbestand ontbreekt; herstel de originele PDF voordat je verdergaat.")
            return
        try:
            import pymupdf as fitz
            pdf = fitz.open(source)
            page_count = len(pdf)
            if not page_count:
                pdf.close()
                raise ValueError("PDF bevat geen pagina's.")
            self._workspace_page = max(1, min(self._workspace_page, page_count))
            page_rect = pdf[self._workspace_page-1].rect
            page_width, page_height = float(page_rect.width), float(page_rect.height)
            pdf.close()
            canvas_width = max(420, self.pdf_canvas.winfo_width()-30)
            fit_scale = min(1.35, canvas_width / page_width)
            scale = max(0.45, fit_scale * self._workspace_zoom)
            output = Path(self._workspace_temp.name) / f"{doc['id']}-pagina-{self._workspace_page}-{scale:.3f}.png"
            render_page(source, self._workspace_page, output, scale=scale)
            photo = tk.PhotoImage(file=str(output))
            self._workspace_photo = photo
            self._workspace_scale = scale
            self.pdf_canvas.delete("all")
            self.pdf_canvas.create_image(0, 0, image=photo, anchor="nw", tags=("page",))
            self.pdf_canvas.configure(scrollregion=(0, 0, photo.width(), photo.height()))
            row = self._workspace_selected
            if row and int(row.get("page", 0) or 0) == self._workspace_page and row.get("bbox"):
                x0,y0,x1,y1 = [float(x)*scale for x in row["bbox"]]
                self.pdf_canvas.create_rectangle(x0-5,y0-4,x1+5,y1+4,
                    outline="#D71920", width=3, tags=("marker",))
                self.pdf_canvas.create_text(x0+5,y0-13,text=f"Vraag {row.get('number')}",
                    anchor="sw",fill="#D71920",font=("Segoe UI",11,"bold"),tags=("marker",))
                self.pdf_canvas.yview_moveto(max(0, (y0-120) / max(1, photo.height())))
            self._workspace_page_label.configure(text=f"Pagina {self._workspace_page} / {page_count}")
            if self._workspace_mark_mode:
                self.status.configure(text="Klik op de exacte positie van de ontbrekende vraag in de PDF.")
        except Exception as exc:
            self._error("Originele PDF weergeven", exc)

    def _workspace_change_page(self, delta):
        self._workspace_page += int(delta)
        self._workspace_render_page()

    def _workspace_zoom_by(self, factor):
        self._workspace_zoom = max(0.55, min(2.5, self._workspace_zoom * factor))
        self._workspace_render_page()

    def _workspace_reset_zoom(self):
        self._workspace_zoom = 1.0
        self._workspace_render_page()

    def _workspace_start_manual_mark(self):
        if not self._workspace_doc() or self._workspace_doc().get("type_voorstel") != "opgaven":
            messagebox.showinfo("Selecteer opgaven-PDF", "Selecteer eerst het opgavenbestand waarin een vraag ontbreekt.")
            return
        self._workspace_mark_mode = True
        self.pdf_canvas.configure(cursor="crosshair")
        self.status.configure(text="Klik op de exacte positie van de ontbrekende vraag in de originele PDF.")

    def _workspace_canvas_click(self, event):
        if not self._workspace_mark_mode:
            return
        doc = self._workspace_doc()
        if not doc:
            return
        try:
            import pymupdf as fitz
            source = self.project_dir / "bronnen" / doc["opslagbestand"]
            pdf = fitz.open(source)
            page = pdf[self._workspace_page-1]
            px = self.pdf_canvas.canvasx(event.x)
            py = self.pdf_canvas.canvasy(event.y)
            x, y = px / self._workspace_scale, py / self._workspace_scale
            if x < 0 or y < 0 or x > page.rect.width or y > page.rect.height:
                pdf.close()
                return
            pdf.close()
            number = simpledialog.askinteger("Ontbrekende vraag", "Welk vraagnummer ontbreekt?", minvalue=1, maxvalue=60, parent=self.root)
            if number is None:
                self._workspace_mark_mode = False
                return
            prompt = simpledialog.askstring("Vraagtekst", "Voer de vraag of opdrachtformulering in (je kunt deze later verder aanvullen):", parent=self.root) or ""
            stable_key = f"{doc['id']}|{self._workspace_page}|{int(number)}|{x:.1f}|{y:.1f}"
            row = {
                "id": hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:16],
                "number": int(number), "original_number": int(number), "page": int(self._workspace_page),
                "bbox": [round(x,2), round(y,2), round(x+24,2), round(y+18,2)],
                "line": f"{number}.", "next_line": prompt, "confidence": 1.0,
                "status": "handmatig_toegevoegd", "human_decision": True,
                "manual_added": True, "manual_position_confirmed": True,
                "reason": "Handmatig op de originele PDF-pagina toegevoegd.",
                "vraagtekst_voorstel": prompt, "vraagtype_status": "controle_nodig",
                "review_note": "Handmatig toegevoegd; controleer de volledige vraaggrens en context."
            }
            row["document_id"] = doc["id"]
            row["bestand"] = doc["bestand"]
            row["vraagtype_controle"] = detect_question_type(prompt)
            row["context_verwijzingen"] = detect_context_references(prompt)
            self.data.setdefault("vraagkandidaten", []).append(row)
            self._workspace_store_candidate_correction(row)
            self._workspace_mark_mode = False
            self.pdf_canvas.configure(cursor="crosshair")
            self.save_project()
            self._workspace_filter.set("Alle kandidaten")
            self._workspace_refresh_candidates(len(self._workspace_rows))
            self._log(f"Vraag {number} handmatig toegevoegd op PDF-pagina {self._workspace_page}, positie x={x:.1f}, y={y:.1f} pt.")
        except Exception as exc:
            self._workspace_mark_mode = False
            self._error("Ontbrekende vraag handmatig markeren", exc)

    def _workspace_save_candidate(self):
        row = self._workspace_selected
        if not row:
            messagebox.showinfo("Geen vraag geselecteerd", "Selecteer eerst een vraagkandidaat.")
            return
        try:
            number = int(self._workspace_number.get().strip())
            if not 1 <= number <= 60:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ongeldig vraagnummer", "Gebruik een vraagnummer van 1 tot en met 60.")
            return
        row.setdefault("original_number", row.get("number"))
        row["number"] = number
        row["vraagtekst_voorstel"] = self._workspace_text.get("1.0", "end-1c").strip()
        row["review_note"] = self._workspace_note.get("1.0", "end-1c").strip()
        row["vraagtype_controle"] = detect_question_type(row["vraagtekst_voorstel"])
        row["context_verwijzingen"] = detect_context_references(row["vraagtekst_voorstel"])
        row["vraagtype_status"] = "controle_nodig"
        self._workspace_store_candidate_correction(row)
        self.save_project()
        self._workspace_summary.configure(text=f"Vraag {number} opgeslagen. Tekst en notitie zijn bewaard in het project.")
        self._workspace_refresh_candidates(self.candidate_tree.index(self.candidate_tree.selection()[0])
            if self.candidate_tree.selection() else 0)
        self._log(f"Vraag {number}: nummer, vraagtekst en notitie opgeslagen.")

    def _workspace_decide(self, decision):
        row = self._workspace_selected
        if not row:
            messagebox.showinfo("Geen vraag geselecteerd", "Selecteer eerst een vraagkandidaat.")
            return
        if decision is None:
            row["human_decision"] = None
            row["status"] = "twijfel_handmatige_nacontrole"
            row["decision_reason"] = "Handmatig als twijfel gemarkeerd."
        else:
            row["human_decision"] = bool(decision)
            row["status"] = "bevestigd_vraagstart" if decision else "afgewezen_geen_vraag"
            row["decision_reason"] = "Handmatig beoordeeld in de geïntegreerde werkruimte."
            learn_decision(self.knowledge_dir, {
                "pattern_key": question_pattern_key(row),
                "chosen": "question" if decision else "not_question",
                "accepted": True, "scope": "voorstel_voor_toekomstige_herkenning",
                "document_id": row.get("document_id"), "page": row.get("page"),
                "candidate_line": row.get("line"), "reason": row["decision_reason"],
                "human_decision": bool(decision)})
        self._workspace_store_candidate_correction(row)
        self.save_project()
        self._log(f"Vraagstart {row.get('number')} op pagina {row.get('page')}: {row['status']}.")
        next_index = next((i for i,r in enumerate(self._workspace_rows)
                           if r is not row and r.get("human_decision") is None), None)
        self._workspace_refresh_candidates(next_index if next_index is not None else 0)

    def _workspace_create_record(self):
        if not self._workspace_rows:
            messagebox.showinfo("Geen kandidaten", "Analyseer eerst de opgaven-PDF en selecteer een vraagstart.")
            return
        if not self.candidate_tree.selection():
            messagebox.showinfo("Selecteer een vraag", "Selecteer eerst een kandidaat.")
            return
        index = int(self.candidate_tree.selection()[0])
        row = self._workspace_rows[index]
        if row.get("human_decision") is not True:
            messagebox.showwarning("Vraagstart eerst bevestigen",
                "Bevestig eerst dat dit een echte vraagstart is. Handmatig toegevoegde vragen zijn al expliciet bevestigd.")
            return
        self.create_question_record(self._workspace_rows, self.candidate_tree, self.root)

    def _workspace_store_candidate_correction(self, row):
        """Persist the latest human decision in the project correction ledger."""
        if not self.data or not row:
            return
        doc = next((d for d in self.data.get("documenten", [])
                    if d.get("id") == row.get("document_id")), None)
        if not doc:
            return
        decision = row.get("human_decision")
        changed_number = row.get("number") != row.get("original_number", row.get("number"))
        has_review = (decision is not None or row.get("status") == "twijfel_handmatige_nacontrole"
            or row.get("manual_added") or row.get("review_note") or changed_number
            or row.get("manual_position_confirmed"))
        if not has_review:
            return
        position = {}
        if row.get("bbox") and len(row["bbox"]) >= 2:
            position = {"x": round(float(row["bbox"][0]), 2), "y": round(float(row["bbox"][1]), 2)}
        correction_id = str(row.get("legacy_correction_id") or row.get("id") or hashlib.sha256(
            f"{doc.get('id')}|{row.get('page')}|{row.get('original_number',row.get('number'))}|{position}".encode("utf-8")
        ).hexdigest()[:16])
        row["legacy_correction_id"] = correction_id
        correction = {
            "id": correction_id, "pagina": int(row.get("page", 0) or 0),
            "vraagnummer": int(row.get("number", 0) or 0),
            "oorspronkelijk_nummer": int(row.get("original_number", row.get("number", 0)) or 0),
            "beslissing": "vraag" if decision is True else ("geen_vraag" if decision is False else "open"),
            "notitie": row.get("review_note") or row.get("decision_reason") or "",
            "positie_pdf_pt": position,
            "handmatig_toegevoegd": bool(row.get("manual_added", False))
        }
        self.data["biologie_controle_correcties"] = self._workspace_merge_correction_entries(
            self.data.get("biologie_controle_correcties", []),
            [{"bestand": doc.get("bestand"), "correcties": [correction]}])

    def _workspace_merge_correction_entries(self, existing_entries, incoming_entries):
        """Deduplicate legacy corrections by document and stable correction ID."""
        by_name = {}
        for entry in existing_entries or []:
            if isinstance(entry, dict) and entry.get("bestand"):
                by_name[str(entry["bestand"])] = {
                    **entry, "correcties": [dict(c) for c in entry.get("correcties", []) if isinstance(c, dict)]
                }
        for entry in incoming_entries or []:
            if not isinstance(entry, dict) or not entry.get("bestand"):
                continue
            name = str(entry["bestand"])
            target = by_name.setdefault(name, {"bestand": name, "correcties": []})
            if entry.get("documenttype_handmatig"):
                target["documenttype_handmatig"] = entry["documenttype_handmatig"]
            indexed = {str(c.get("id")): c for c in target.get("correcties", []) if c.get("id")}
            for raw in entry.get("correcties", []):
                if not isinstance(raw, dict):
                    continue
                correction = dict(raw)
                if not correction.get("id"):
                    pos = correction.get("positie_pdf_pt") or {}
                    seed = "|".join(str(correction.get(k, "")) for k in
                        ("pagina", "oorspronkelijk_nummer", "vraagnummer", "beslissing"))
                    correction["id"] = hashlib.sha256(
                        f"{name}|{seed}|{pos.get('x','')}|{pos.get('y','')}".encode("utf-8")
                    ).hexdigest()[:16]
                key = str(correction["id"])
                previous = indexed.get(key, {})
                combined = {**previous, **correction}
                if not correction.get("positie_pdf_pt") and previous.get("positie_pdf_pt"):
                    combined["positie_pdf_pt"] = previous["positie_pdf_pt"]
                if not correction.get("notitie") and previous.get("notitie"):
                    combined["notitie"] = previous["notitie"]
                indexed[key] = combined
            target["correcties"] = list(indexed.values())
        return list(by_name.values())

    def _workspace_load_global_corrections(self):
        """Apply the portable Biologie-controle correction library to whichever exam is opened."""
        if not self.data:
            return
        path = self.knowledge_dir / "biologie-correcties.json"
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("formaat") != "biologie-correcties-v1":
                return
            # Project-specific decisions take precedence over the older global import.
            self.data["biologie_controle_correcties"] = self._workspace_merge_correction_entries(
                payload.get("documenten", []), self.data.get("biologie_controle_correcties", []))
            self._workspace_apply_saved_corrections()
            self.save_project()
        except Exception as exc:
            self._error("Biologie-controlecorrecties laden", exc)

    def _workspace_import_corrections(self):
        """Import the compact biologie-correcties-v1 format without replacing newer decisions."""
        if not self.data or not self.project_dir:
            messagebox.showinfo("Eerst een examen openen", "Open eerst het examenproject waarin je de correcties wilt bewaren.")
            return
        filename = filedialog.askopenfilename(
            title="Importeer correcties uit Biologie-controle",
            filetypes=[("Biologie-controle correcties", "*.json"), ("JSON-bestanden", "*.json")])
        if not filename:
            return
        try:
            payload = json.loads(Path(filename).read_text(encoding="utf-8"))
            if payload.get("formaat") != "biologie-correcties-v1":
                raise ValueError("Dit bestand heeft niet het formaat biologie-correcties-v1.")
            imported = payload.get("documenten")
            if not isinstance(imported, list):
                raise ValueError("Het correctiebestand bevat geen geldige documentenlijst.")
            global_path = self.knowledge_dir / "biologie-correcties.json"
            global_entries = []
            if global_path.is_file():
                global_payload = json.loads(global_path.read_text(encoding="utf-8"))
                if global_payload.get("formaat") == "biologie-correcties-v1":
                    global_entries = global_payload.get("documenten", [])
            # Preserve the current project's earlier imported decisions, then
            # let the newly selected correction file update the global library.
            global_entries = self._workspace_merge_correction_entries(
                global_entries, self.data.get("biologie_controle_correcties", []))
            global_entries = self._workspace_merge_correction_entries(global_entries, imported)
            global_path.parent.mkdir(parents=True, exist_ok=True)
            global_path.write_text(json.dumps({
                "formaat": "biologie-correcties-v1", "app_versie": APP_VERSION,
                "aangemaakt": now(),
                "aantal_correcties": sum(len(x.get("correcties", [])) for x in global_entries),
                "documenten": global_entries,
                "toelichting": "Draagbare correctiebibliotheek uit Biologie-controle; geen PDF-inhoud."
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            self.data["biologie_controle_correcties"] = global_entries
            current_names = {d.get("bestand") for d in self.data.get("documenten", [])}
            unmatched = [x.get("bestand") for x in global_entries if x.get("bestand") not in current_names]
            applied = sum(len(x.get("correcties", [])) for x in global_entries
                          if x.get("bestand") in current_names)
            self._workspace_apply_saved_corrections()
            self.save_project()
            self.refresh()
            self._log(f"Biologie-controlecorrecties geïmporteerd uit {Path(filename).name}; {applied} correcties beschikbaar in dit project en de centrale correctiebibliotheek.")
            if unmatched:
                self._log("Correcties voor nog niet gekoppelde documenten bewaard: " + ", ".join(unmatched))
            messagebox.showinfo("Correcties geïmporteerd",
                f"De correcties zijn samengevoegd en in de centrale correctiebibliotheek én dit project bewaard.\n"
                f"Ze worden automatisch toegepast wanneer je de bijbehorende examenprojecten opent.\n\n"
                f"Niet gekoppelde bestanden: {len(unmatched)}", parent=self.root)
        except Exception as exc:
            self._error("Correcties importeren", exc)
            messagebox.showerror("Importeren mislukt", str(exc), parent=self.root)

    def _workspace_apply_saved_corrections(self, target_rows=None):
        """Apply imported Biologie-controle corrections to the current candidate set."""
        if not self.data:
            return
        rows = target_rows if target_rows is not None else self.data.setdefault("vraagkandidaten", [])
        for document_state in self.data.get("biologie_controle_correcties", []):
            filename = document_state.get("bestand")
            doc = next((d for d in self.data.get("documenten", []) if d.get("bestand") == filename), None)
            if not doc:
                continue
            manual_role = document_state.get("documenttype_handmatig")
            if manual_role in {"opgaven", "correctievoorschrift", "aanvulling", "uitwerkbijlage"}:
                doc["type_voorstel"] = manual_role
                doc["documenttype_handmatig"] = manual_role
                doc["type_zekerheid"] = 1.0
                doc["status"] = "handmatig_bevestigd"
            current = [r for r in rows if r.get("document_id") == doc.get("id")]
            for correction in document_state.get("correcties", []):
                page_no = int(correction.get("pagina", 0) or 0)
                original_number = int(correction.get("oorspronkelijk_nummer",
                    correction.get("vraagnummer", 0)) or 0)
                position = correction.get("positie_pdf_pt") or {}
                x = position.get("x")
                y = position.get("y")
                candidate = next((r for r in current if str(r.get("id")) == str(correction.get("id"))), None)
                if candidate is None:
                    def close_match(r):
                        if int(r.get("page", 0) or 0) != page_no:
                            return False
                        number_match = int(r.get("original_number", r.get("number", 0)) or 0) == original_number
                        if x is not None and y is not None and r.get("bbox"):
                            return number_match and abs(float(r["bbox"][0])-float(x)) <= 8 and abs(float(r["bbox"][1])-float(y)) <= 8
                        return number_match
                    candidate = next((r for r in current if close_match(r)), None)
                if candidate is None and correction.get("handmatig_toegevoegd"):
                    if x is None or y is None:
                        continue
                    candidate = {
                        "id": str(correction.get("id")),
                        "document_id": doc["id"], "bestand": doc["bestand"],
                        "number": int(correction.get("vraagnummer", original_number) or original_number),
                        "original_number": original_number, "page": page_no,
                        "bbox": [float(x), float(y), float(x)+24, float(y)+18],
                        "line": "", "next_line": "", "confidence": 1.0,
                        "status": "handmatig_toegevoegd", "manual_added": True,
                        "manual_position_confirmed": True, "vraagtekst_voorstel": "",
                        "vraagtype_status": "controle_nodig", "review_note": "",
                        "vraagtype_controle": {"type": "onbekend", "options": []},
                        "context_verwijzingen": []
                    }
                    rows.append(candidate)
                    current.append(candidate)
                if candidate is None:
                    continue
                candidate["legacy_correction_id"] = str(correction.get("id"))
                candidate.setdefault("original_number", original_number)
                if correction.get("vraagnummer") is not None:
                    candidate["number"] = int(correction["vraagnummer"])
                if x is not None and y is not None:
                    bbox = candidate.get("bbox") or [float(x), float(y), float(x)+24, float(y)+18]
                    width = max(12.0, float(bbox[2])-float(bbox[0]))
                    height = max(10.0, float(bbox[3])-float(bbox[1]))
                    candidate["bbox"] = [float(x), float(y), float(x)+width, float(y)+height]
                    candidate["manual_position_confirmed"] = True
                candidate["manual_added"] = bool(correction.get("handmatig_toegevoegd", candidate.get("manual_added", False)))
                candidate["review_note"] = correction.get("notitie", candidate.get("review_note", ""))
                decision = correction.get("beslissing", "open")
                if decision == "vraag":
                    candidate["human_decision"] = True
                    candidate["status"] = "bevestigd_vraagstart"
                elif decision == "geen_vraag":
                    candidate["human_decision"] = False
                    candidate["status"] = "afgewezen_geen_vraag"
                else:
                    candidate["human_decision"] = None
                    candidate["status"] = "twijfel_handmatige_nacontrole"

    def _workspace_merge_review_state(self, doc, candidates, previous_candidates):
        """Keep human decisions and manually added positions when analysis is rerun."""
        for old in previous_candidates:
            if old.get("document_id") != doc.get("id"):
                continue
            match = next((r for r in candidates if r.get("id") == old.get("id")), None)
            if match is None:
                old_bbox = old.get("bbox") or []
                match = next((r for r in candidates
                    if int(r.get("page", 0) or 0) == int(old.get("page", 0) or 0)
                    and int(r.get("number", 0) or 0) == int(old.get("original_number", old.get("number", 0)) or 0)
                    and len(old_bbox) >= 2 and r.get("bbox")
                    and abs(float(r["bbox"][0])-float(old_bbox[0])) <= 8
                    and abs(float(r["bbox"][1])-float(old_bbox[1])) <= 8), None)
            if match is None and old.get("manual_added"):
                candidates.append(dict(old))
                continue
            if match is None:
                continue
            for key in ("human_decision", "review_note", "manual_added",
                        "manual_position_confirmed", "legacy_correction_id", "decision_reason"):
                if key in old:
                    match[key] = old[key]
            if old.get("human_decision") is not None or old.get("status") == "twijfel_handmatige_nacontrole":
                match["status"] = old.get("status", match.get("status"))
            if old.get("number") != old.get("original_number", old.get("number")):
                match["original_number"] = old.get("original_number", old.get("number"))
                match["number"] = old.get("number")
            if old.get("manual_position_confirmed") and old.get("bbox"):
                match["bbox"] = list(old["bbox"])
        self._workspace_apply_saved_corrections(candidates)
        return candidates

    def _workspace_export_corrections(self):
        if not self.data or not self.project_dir:
            messagebox.showinfo("Eerst een examen openen", "Open eerst een examenproject.")
            return
        output = filedialog.asksaveasfilename(
            title="Exporteer Biologie-controlecorrecties",
            defaultextension=".json", initialfile="biologie-correcties.json",
            filetypes=[("JSON-bestanden", "*.json")])
        if not output:
            return
        global_path = self.knowledge_dir / "biologie-correcties.json"
        global_entries = []
        if global_path.is_file():
            try:
                global_payload = json.loads(global_path.read_text(encoding="utf-8"))
                if global_payload.get("formaat") == "biologie-correcties-v1":
                    global_entries = global_payload.get("documenten", [])
            except Exception:
                global_entries = []
        by_name = self._workspace_merge_correction_entries(
            global_entries, self.data.get("biologie_controle_correcties", []))
        for doc in self.data.get("documenten", []):
            group = by_name.setdefault(doc.get("bestand"), {
                "bestand": doc.get("bestand"), "correcties": []})
            if doc.get("documenttype_handmatig"):
                group["documenttype_handmatig"] = doc["documenttype_handmatig"]
            existing = {str(c.get("id")): c for c in group.get("correcties", [])
                        if isinstance(c, dict) and c.get("id")}
            for row in self.data.get("vraagkandidaten", []):
                if row.get("document_id") != doc.get("id"):
                    continue
                decision = row.get("human_decision")
                changed_number = row.get("number") != row.get("original_number", row.get("number"))
                has_review = (decision is not None or row.get("status") == "twijfel_handmatige_nacontrole"
                    or row.get("manual_added") or row.get("review_note") or changed_number
                    or row.get("manual_position_confirmed"))
                if not has_review:
                    continue
                pos = {}
                if row.get("bbox") and len(row["bbox"]) >= 2:
                    pos = {"x": round(float(row["bbox"][0]), 2), "y": round(float(row["bbox"][1]), 2)}
                correction_id = str(row.get("legacy_correction_id") or row.get("id") or hashlib.sha256(
                    f"{doc.get('id')}|{row.get('page')}|{row.get('original_number',row.get('number'))}|{pos}".encode("utf-8")
                ).hexdigest()[:16])
                decision_text = "vraag" if decision is True else ("geen_vraag" if decision is False else "open")
                correction = {
                    "id": correction_id, "pagina": int(row.get("page", 0) or 0),
                    "vraagnummer": int(row.get("number", 0) or 0),
                    "oorspronkelijk_nummer": int(row.get("original_number", row.get("number", 0)) or 0),
                    "beslissing": decision_text,
                    "notitie": row.get("review_note") or row.get("decision_reason") or "",
                    "positie_pdf_pt": pos,
                    "handmatig_toegevoegd": bool(row.get("manual_added", False))
                }
                existing[correction_id] = {**existing.get(correction_id, {}), **correction}
            group["correcties"] = list(existing.values())
        payload = {
            "formaat": "biologie-correcties-v1", "app_versie": APP_VERSION,
            "aangemaakt": now(),
            "aantal_correcties": sum(len(x.get("correcties", [])) for x in by_name.values()),
            "documenten": list(by_name.values()),
            "toelichting": "Alleen handmatige beoordelingen en correcties; geen PDF-inhoud of afbeeldingen."
        }
        try:
            exported_text = json.dumps(payload, ensure_ascii=False, indent=2)
            Path(output).write_text(exported_text, encoding="utf-8")
            self.data["biologie_controle_correcties"] = list(by_name.values())
            self.save_project()
            global_path.parent.mkdir(parents=True, exist_ok=True)
            global_path.write_text(exported_text, encoding="utf-8")
            self._log(f"Biologie-controlecorrecties geëxporteerd: {output}; centrale correctiebibliotheek bijgewerkt.")
            messagebox.showinfo("Correcties geëxporteerd", "De correcties zijn veilig als compact JSON-bestand opgeslagen.", parent=self.root)
        except Exception as exc:
            self._error("Correcties exporteren", exc)
            messagebox.showerror("Exporteren mislukt", str(exc), parent=self.root)

    def _scrollable_tab(self, parent):
        """Return a vertically scrollable content frame for a notebook tab."""
        holder = ttk.Frame(parent, style="App.TFrame")
        holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(holder, background=self.colors["canvas"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = ttk.Frame(canvas, style="App.TFrame", padding=4)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))
        return content

    def _metric_card(self, parent, heading, value, caption, column):
        card = tk.Frame(parent, bg="#FFFFFF", highlightthickness=1,
                        highlightbackground=self.colors["line"])
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
        parent.columnconfigure(column, weight=1, uniform="metrics")
        tk.Label(card, text=heading, bg="#FFFFFF", fg=self.colors["muted"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=14, pady=(12, 1))
        number = ttk.Label(card, text=value, style="Metric.TLabel")
        number.pack(anchor="w", padx=14)
        ttk.Label(card, text=caption, style="MetricCaption.TLabel").pack(anchor="w", padx=14, pady=(0, 12))
        return number

    def _welcome(self):
        self._log("Welkom. Open een bestaand examenproject of selecteer in één keer PDF's van meerdere jaren, niveaus en tijdvakken.")
        self._log("De software leest de examens uit, groepeert ze automatisch en maakt zelf de examenmappen aan. Je controleert eerst de herkenning.")

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
        """Create a project automatically inside the portable app's own project root."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"nieuw-project-{stamp}"
        root = self.app_base / "projecten"
        self.project_dir = root / name
        try:
            self.project_dir.mkdir(parents=True, exist_ok=False)
            for folder in ("bronnen", "analyse", "snippets", "logs"):
                (self.project_dir / folder).mkdir(exist_ok=True)
            self.data = {"schema": "biologie-examenproject-v1", "app_versie": APP_VERSION, "naam": name,
                         "aangemaakt": now(), "bijgewerkt": now(), "documenten": [], "beslissingen": [],
                         "publicatiestatus": "niet_vrijgegeven", "vraagkandidaten": []}
            self._workspace_load_global_corrections()
            self.save_project()
            self.refresh()
            self._log(f"Nieuw project automatisch aangemaakt: {self.project_dir}")
        except Exception as exc:
            self.project_dir = None
            self.data = None
            self._error("Nieuw project aanmaken", exc)
            messagebox.showerror("Project aanmaken mislukt",
                f"Het project kon niet worden aangemaakt in:\n{root}\n\n"
                "Controleer of de programmamap schrijfbaar is. Details staan in de map logs.")

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
            self._workspace_load_global_corrections()
            self.refresh()
            self._log(f"Project geopend: {self.project_dir}")
        except Exception as exc:
            self._error("Project openen",exc)
            messagebox.showerror("Project openen mislukt","Dit project kon niet worden geopend. Controleer of het projectbestand geldig is. Details staan in de map logs.")

    def import_year_set(self):
        """Import arbitrary exams from multiple years without manual folder creation."""
        files = filedialog.askopenfilenames(
            title="Selecteer alle examen-PDF's (meerdere jaren, havo/vwo en tijdvakken tegelijk)",
            filetypes=[("PDF-bestanden", "*.pdf")])
        if not files:
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
        win.title("Examens controleren en automatisch groeperen")
        fit_window(win, 1180, 720, 900, 560)
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text=f"{len(documents)} unieke PDF's gevonden. Selecteer links een document; controleer het voorblad in het midden en pas de voorgestelde gegevens rechts direct aan.",
                  padding=12, wraplength=1100).pack(anchor="w")
        panes = ttk.Panedwindow(win, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=12, pady=8)
        list_panel = ttk.LabelFrame(panes, text="GESELECTEERDE PDF'S", padding=7)
        cover_panel = ttk.LabelFrame(panes, text="VOORBLAD ORIGINELE PDF", padding=7)
        fields_panel = ttk.LabelFrame(panes, text="VOORGESTELDE METADATA", padding=12)
        panes.add(list_panel, weight=4)
        panes.add(cover_panel, weight=6)
        panes.add(fields_panel, weight=4)
        columns = ("file", "role", "level", "year", "period", "state")
        tree = ttk.Treeview(list_panel, columns=columns, show="headings", selectmode="browse")
        for col, title, width in [
            ("file", "Bestand", 190), ("role", "Type", 105), ("level", "Niveau", 55),
            ("year", "Jaar", 48), ("period", "Tv", 32), ("state", "Controle", 115)]
            :
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="w" if col in ("file", "role", "state") else "center")
        tree.pack(fill="both", expand=True)
        status = ttk.Label(win, text="", padding=(12, 4), wraplength=1100)
        status.pack(anchor="w")
        preview_temp = tempfile.TemporaryDirectory(prefix="biologie-import-voorbladen-")
        win._preview_temp = preview_temp
        preview_label = ttk.Label(cover_panel, text="Selecteer links een PDF om het voorblad te bekijken.",
                                  anchor="center", justify="center")
        preview_label.pack(fill="both", expand=True)
        preview_info = ttk.Label(cover_panel, text="", wraplength=440)
        preview_info.pack(fill="x", pady=(5, 0))
        role = tk.StringVar()
        level = tk.StringVar()
        year = tk.StringVar()
        period = tk.StringVar()
        confidence_label = ttk.Label(fields_panel, text="", wraplength=360, justify="left")
        confidence_label.pack(anchor="w", pady=(0, 10))
        fields = [
            ("Documenttype", role, ttk.Combobox(fields_panel, textvariable=role,
                values=["opgaven", "correctievoorschrift", "aanvulling", "uitwerkbijlage", "onbekend"],
                state="readonly", width=25)),
            ("Niveau", level, ttk.Combobox(fields_panel, textvariable=level,
                values=["Havo", "Vwo"], state="readonly", width=25)),
            ("Jaar", year, ttk.Entry(fields_panel, textvariable=year, width=28)),
            ("Tijdvak", period, ttk.Combobox(fields_panel, textvariable=period,
                values=["1", "2", "3"], state="readonly", width=25)),
        ]
        for label, var, widget in fields:
            ttk.Label(fields_panel, text=label).pack(anchor="w", pady=(7, 2))
            widget.pack(anchor="w", fill="x")
        ttk.Label(fields_panel,
            text="Controleer de gegevens aan de hand van het voorblad. Lege of onzekere waarden moet je zelf aanvullen. Documenten worden alleen samen gegroepeerd als niveau, jaar en tijdvak exact overeenkomen.",
            wraplength=360, justify="left").pack(anchor="w", pady=(14, 8))
        selected_doc = {"index": None}
        cover_photo = {"image": None}
        
        def identity_text(doc):
            meta = doc.get("exam_metadata") or {}
            return meta.get("level", ""), meta.get("year", ""), meta.get("period", "")

        def refresh_review():
            for item in tree.get_children():
                tree.delete(item)
            groups, unassigned = group_exam_documents(documents)
            for index, doc in enumerate(documents):
                meta = doc.get("exam_metadata") or {}
                uncertain = (doc.get("type_zekerheid", 0) < 0.9
                             or float(meta.get("confidence", 0) or 0) < 0.9)
                state = "Handmatig controleren" if uncertain or not meta else "Voorstel controleren"
                if not meta:
                    state = "Metadata ontbreekt"
                tree.insert("", "end", iid=str(index), values=(
                    doc["bestand"], doc.get("type_voorstel", "onbekend"),
                    meta.get("level", "—") if meta else "—",
                    meta.get("year", "—") if meta else "—",
                    meta.get("period", "—") if meta else "—", state))
            summary = []
            for key, items in groups.items():
                summary.append(f"{key[0].upper()} {key[1]} tijdvak {key[2]}: {len(items)} PDF's")
            if unassigned:
                summary.append(f"{len(unassigned)} PDF('s) zonder complete examenidentiteit")
            status.configure(text="Automatische groepen: " + ("; ".join(summary) if summary else "nog geen complete groepen"))

        def load_selected(_event=None):
            selection = tree.selection()
            if not selection:
                selected_doc["index"] = None
                return
            index = int(selection[0])
            doc = documents[index]
            selected_doc["index"] = index
            meta = doc.get("exam_metadata") or {}
            role.set(doc.get("type_voorstel", "onbekend"))
            level.set(meta.get("level", ""))
            year.set(str(meta.get("year", "")))
            period.set(str(meta.get("period", "")))
            confidence = meta.get("confidence")
            source_label = {
                "bestandsnaam": "bestandsnaam",
                "eerste_pdf_paginas": "tekst op de eerste PDF-pagina's",
                "handmatig_bevestigd": "eerder handmatig bevestigd",
            }.get(meta.get("source"), "onbekende bron")
            confidence_label.configure(text=(
                f"Herkenningszekerheid metadata: {float(confidence or 0):.0%} · bron: {source_label}\n"
                f"Documenttypezekerheid: {float(doc.get('type_zekerheid', 0) or 0):.0%}"
            ))
            preview_info.configure(text=f"{doc['bestand']} · {doc.get('pagina_aantal', 0)} pagina's")
            preview_label.configure(image="", text="Voorblad wordt geladen…")
            cover_photo["image"] = None
            try:
                preview_path = Path(preview_temp.name) / f"voorblad-{index}.png"
                render_page(Path(doc["source_path"]), 1, preview_path, scale=0.82)
                photo = tk.PhotoImage(file=str(preview_path))
                cover_photo["image"] = photo
                preview_label.configure(image=photo, text="")
            except Exception as exc:
                preview_label.configure(image="", text=f"Het voorblad kon niet worden weergegeven.\n\n{exc}",
                                        wraplength=440)

        def save_selected():
            index = selected_doc["index"]
            if index is None:
                messagebox.showinfo("Selecteer een PDF", "Selecteer eerst links een PDF.", parent=win)
                return
            doc = documents[index]
            if role.get() not in {"opgaven", "correctievoorschrift", "aanvulling", "uitwerkbijlage"}:
                messagebox.showerror("Documenttype ontbreekt", "Kies een geldig documenttype.", parent=win)
                return
            if level.get() not in {"Havo", "Vwo"} or not re.fullmatch(r"20\d{2}", year.get().strip()) or period.get() not in {"1", "2", "3"}:
                messagebox.showerror("Examenidentiteit onvolledig",
                    "Vul niveau, een viercijferig jaar en tijdvak 1, 2 of 3 in.", parent=win)
                return
            doc["type_voorstel"] = role.get()
            doc["type_zekerheid"] = 1.0
            doc["exam_metadata"] = {"level": level.get(), "year": year.get().strip(), "period": period.get(),
                                    "confidence": 1.0, "source": "handmatig_bevestigd"}
            doc["status"] = "handmatig_bevestigd"
            refresh_review()
            tree.selection_set(str(index))
            tree.focus(str(index))
            status.configure(text="Wijzigingen opgeslagen voor de geselecteerde PDF. Controleer zo nodig de overige documenten.")

        tree.bind("<<TreeviewSelect>>", load_selected)
        ttk.Button(fields_panel, text="Wijzigingen toepassen op deze PDF",
                   command=save_selected, style="Accent.TButton").pack(fill="x", pady=(12, 4))

        def confirm_import():
            # One final approval for the batch. Do not turn uncertain automated
            # proposals into human-confirmed data: low-confidence or incomplete
            # rows must be corrected explicitly in the review table first.
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
            target_root = self.examens_root
            created = []
            created_directories = []
            manifest_path = None
            try:
                target_root.mkdir(parents=True, exist_ok=True)
                manifest = {"schema": "biologie-examenimport-v1", "aangemaakt": now(), "projecten": []}
                for key, items in sorted(groups.items()):
                    level_key, year_key, period_key = key
                    project_name = f"{level_key}-tijdvak-{period_key}"
                    year_dir = target_root / year_key
                    if not year_dir.exists():
                        year_dir.mkdir(parents=True)
                        created_directories.append(year_dir)
                    project_dir = year_dir / project_name
                    project_dir.mkdir(exist_ok=False)
                    created_directories.append(project_dir)
                    (project_dir / "bronnen").mkdir()
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
                        "naam": project_name, "pad": f"{year_key}/{project_name}", "exam_metadata": confirmed_identity,
                        "documenten": [d["bestand"] for d in project_docs],
                        "waarschuwingen": batch_document_warnings(items),
                    })
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                manifest_path = target_root / f"import-{stamp}.json"
                suffix = 2
                while manifest_path.exists():
                    manifest_path = target_root / f"import-{stamp}-{suffix}.json"
                    suffix += 1
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                if manifest_path and manifest_path.exists():
                    manifest_path.unlink()
                for created_path in reversed(created_directories):
                    shutil.rmtree(created_path, ignore_errors=True)
                messagebox.showerror("Examens importeren mislukt",
                    f"Er is een fout opgetreden. Alleen nieuwe mappen uit deze import zijn opgeruimd; bestaande examens zijn niet gewijzigd.\\n\\n{exc}", parent=win)
                return
            win.destroy()
            # Open the first exam immediately so the user can start the full
            # review workflow without having to locate project.json manually.
            # All other imported exam projects remain available under the same root.
            self.project_dir = created[0]
            self.data = json.loads((self.project_dir / PROJECT_FILE).read_text(encoding="utf-8"))
            self._workspace_load_global_corrections()
            self.refresh()
            self._log(f"Examens geïmporteerd onder: {target_root}")
            for project in created:
                self._log(f"  Project aangemaakt: {project.name}")
            self._log(f"Eerste examen automatisch geopend: {self.project_dir.name}")
            messagebox.showinfo("Examens geïmporteerd",
                f"{len(created)} examenprojecten zijn aangemaakt onder:\n{target_root}\n\n"
                f"Het eerste examen ({self.project_dir.name}) is direct geopend. Je kunt nu de vraagstarts controleren; "
                "de overige examens open je via Project openen. De oorspronkelijke PDF's zijn ongewijzigd gekopieerd.")

        ttk.Button(win, text="Voorstellen akkoord — importeren", command=confirm_import, style="Accent.TButton").pack(side="right", padx=12, pady=8)
        ttk.Button(win, text="Annuleren", command=win.destroy).pack(side="right", pady=8)
        refresh_review()
        if documents:
            tree.selection_set("0")
            tree.focus("0")
            load_selected()
        self._log(f"Bulkimport voorbereid voor controle: {len(documents)} unieke PDF's. Nog niets opgeslagen of verwerkt. Doelmap: {self.examens_root}")

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
        self._workspace_load_global_corrections()
        self.save_project()
        self.refresh()
        self.status.configure(text=f"{added} PDF('s) toegevoegd. Controleer de voorgestelde documenttypen.")

    def edit_exam_metadata(self):
        if not self.data:
            messagebox.showinfo("Eerst een project","Open eerst een examenproject.")
            return
        current=self.data.get("exam_metadata",{})
        source_doc=next((d for d in self.data.get("documenten",[])
                         if d.get("type_voorstel")=="opgaven"),None)
        source=(self.project_dir/"bronnen"/source_doc["opslagbestand"]) if source_doc else None

        win=tk.Toplevel(self.root)
        win.title("Voorblad en examengegevens controleren")
        fit_window(win, 1080, 760, 820, 560)
        win.transient(self.root)
        win.grab_set()
        body=ttk.Frame(win,padding=14); body.pack(fill="both",expand=True)
        preview_panel=ttk.LabelFrame(body,text="Voorblad van de opgaven-PDF",padding=10)
        preview_panel.pack(side="left",fill="both",expand=True,padx=(0,12))
        fields_panel=ttk.LabelFrame(body,text="Automatisch ingevulde examengegevens",padding=14)
        fields_panel.pack(side="right",fill="y")
        preview_label=ttk.Label(preview_panel,text="Voeg eerst een opgaven-PDF toe om het voorblad te bekijken.",
                                anchor="center",wraplength=460,justify="center")
        preview_label.pack(fill="both",expand=True)
        preview_temp=tempfile.TemporaryDirectory(prefix="biologie-voorblad-")
        if source and source.is_file():
            try:
                preview_path=Path(preview_temp.name)/"voorblad.png"
                render_page(source,1,preview_path,scale=0.72)
                cover_photo=tk.PhotoImage(file=str(preview_path))
                preview_label.configure(image=cover_photo,text="")
                preview_label.image=cover_photo
            except Exception as exc:
                preview_label.configure(text=f"Het voorblad kon niet worden weergegeven.\n\n{exc}")
        win._preview_temp=preview_temp

        ttk.Label(fields_panel,text="Controleer de voorgestelde gegevens aan de hand van het voorblad. Lege waarden zijn niet automatisch ingevuld.",
                  wraplength=390,justify="left").pack(anchor="w",pady=(0,12))
        if source_doc:
            ttk.Label(fields_panel,text=f"Bronbestand: {source_doc['bestand']}",wraplength=390,
                      font=("Segoe UI",9,"bold")).pack(anchor="w",pady=(0,8))
        else:
            ttk.Label(fields_panel,text="Geen opgaven-PDF gekoppeld; controleer de gegevens zodra de bron is toegevoegd.",
                      wraplength=390).pack(anchor="w",pady=(0,8))
        level=tk.StringVar(value=current.get("level",""))
        year=tk.StringVar(value=str(current.get("year","")))
        period=tk.StringVar(value=str(current.get("period","")))
        for label,var,widget in [
            ("Niveau",level,ttk.Combobox(fields_panel,textvariable=level,values=["Havo","Vwo"],state="readonly",width=30)),
            ("Jaar",year,ttk.Entry(fields_panel,width=33)),
            ("Tijdvak",period,ttk.Combobox(fields_panel,textvariable=period,values=["1","2","3"],state="readonly",width=30))
        ]:
            ttk.Label(fields_panel,text=label).pack(anchor="w",pady=(7,2))
            widget.pack(anchor="w",fill="x")

        def save():
            if level.get() not in ("Havo","Vwo") or not re.fullmatch(r"20\d{2}",year.get().strip()) or period.get() not in ("1","2","3"):
                messagebox.showerror("Examengegevens onvolledig","Controleer niveau, jaartal en tijdvak aan de hand van het voorblad.",parent=win); return
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
        buttons=ttk.Frame(fields_panel); buttons.pack(fill="x",side="bottom",pady=(16,0))
        ttk.Button(buttons,text="Gegevens opslaan",command=save,style="Accent.TButton").pack(side="right")
        ttk.Button(buttons,text="Annuleren",command=win.destroy).pack(side="right",padx=8)

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
        previous_candidates = list(self.data.get("vraagkandidaten", []))
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
                for item in ordered:
                    item.setdefault("original_number", int(item.get("number", 0) or 0))
                    bbox = item.get("bbox") or [0, 0]
                    stable_key = f"{doc['id']}|{item['page']}|{item['original_number']}|{float(bbox[0]):.1f}|{float(bbox[1]):.1f}"
                    item["id"] = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:16]
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
                candidates=self._workspace_merge_review_state(doc, ordered, previous_candidates)
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
        """Review question starts in one continuous workspace, without per-question dialogs."""
        if not self.data:
            return
        rows = self.data.get("vraagkandidaten", [])
        win = tk.Toplevel(self.root)
        win.title("Vraagstarts controleren")
        win.geometry("1280x820")
        win.minsize(1040, 680)
        win.transient(self.root)

        header = ttk.Frame(win, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text=f"{len(rows)} mogelijke vraagstarts",
                  font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(header, text="Selecteer links een vraag. Bekijk rechts de tekst, opties en context en bevestig direct. Je blijft in hetzelfde venster.",
                  wraplength=1180).pack(anchor="w", pady=(4, 0))

        split = ttk.Panedwindow(win, orient="horizontal")
        split.pack(fill="both", expand=True, padx=14, pady=8)
        left = ttk.Frame(split, padding=6)
        right = ttk.Frame(split, padding=10)
        split.add(left, weight=3)
        split.add(right, weight=5)

        cols = ("number", "page", "confidence", "type", "cv", "status")
        tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for col, label, width in [
            ("number", "Nr.", 42), ("page", "Pagina", 58), ("confidence", "Signaal", 58),
            ("type", "Type", 88), ("cv", "CV", 70), ("status", "Beoordeling", 130)
        ]:
            tree.heading(col, text=label)
            tree.column(col, width=width, anchor="center" if col in ("number", "page", "confidence") else "w")
        yscroll = ttk.Scrollbar(left, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=yscroll.set)
        tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        ttk.Label(right, text="Geselecteerde vraag", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        summary = ttk.Label(right, text="Selecteer links een vraagstart.", wraplength=720)
        summary.pack(anchor="w", pady=(4, 10))
        ttk.Label(right, text="Gevonden tekst en vraagvoorstel", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        question_box = tk.Text(right, height=15, wrap="word", font=("Segoe UI", 10))
        question_box.pack(fill="both", expand=True, pady=(4, 10))
        question_box.configure(state="disabled")

        details = ttk.Frame(right)
        details.pack(fill="x")
        options_box = tk.Text(details, height=6, wrap="word", font=("Segoe UI", 9))
        options_box.pack(side="left", fill="both", expand=True, padx=(0, 6))
        context_box = tk.Text(details, height=6, wrap="word", font=("Segoe UI", 9))
        context_box.pack(side="left", fill="both", expand=True, padx=(6, 0))
        for box in (options_box, context_box):
            box.configure(state="disabled")

        footer = ttk.Frame(win, padding=(14, 8))
        footer.pack(fill="x")
        status_label = ttk.Label(footer, text="Nog geen vraag geselecteerd.")
        status_label.pack(side="left")

        selected_index = {"value": None}
        def set_box(box, text):
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", text)
            box.configure(state="disabled")

        def learning_hint(row):
            learned = suggest_from_learning(self.knowledge_dir, question_pattern_key(row))
            suggestion = learned.get("suggestion")
            hint = ("Tegenstrijdig" if learned.get("conflicting") else
                    "Vraag" if suggestion == "question" else
                    "Geen vraag" if suggestion == "not_question" else "Geen leeradvies")
            if learned.get("support", 0):
                hint += f" ({learned['support']} eerdere keuzes)"
            return hint

        def refresh_rows(select_index=None):
            for item in tree.get_children():
                tree.delete(item)
            for i, row in enumerate(rows):
                check = row.get("vraagtype_controle", {})
                cv_label = ("Match" if row.get("cv_number_match") is True else
                            "Niet in CV" if row.get("cv_number_match") is False else "—")
                tree.insert("", "end", iid=str(i), values=(
                    row.get("number"), row.get("page"), f"{row.get('confidence', 0):.0%}",
                    check.get("type", "onbekend"), cv_label,
                    row.get("status", "controle_nodig").replace("_", " ")))
            if select_index is not None and str(select_index) in tree.get_children():
                tree.selection_set(str(select_index))
                tree.focus(str(select_index))
                tree.see(str(select_index))
                show_selected()

        def show_selected(_event=None):
            selection = tree.selection()
            if not selection:
                return
            idx = int(selection[0])
            selected_index["value"] = idx
            row = rows[idx]
            check = row.get("vraagtype_controle", {})
            summary.configure(text=(
                f"Vraag {row.get('number')} · PDF-pagina {row.get('page')} · "
                f"signaal {row.get('confidence', 0):.0%} · "
                f"status: {row.get('status', 'controle_nodig').replace('_', ' ')}\n"
                f"Leerbank: {learning_hint(row)}"))
            set_box(question_box, row.get("vraagtekst_voorstel", "") or
                    (row.get("line", "") + "\n" + row.get("next_line", "")))
            options = check.get("options", [])
            option_lines = [f"{o.get('label')}. {o.get('text')}" for o in options]
            if check.get("type") == "meerkeuze":
                option_lines.append(
                    "Ontbrekende labels: " + (", ".join(check.get("option_gaps", [])) or "geen") +
                    "\nDubbele labels: " + (", ".join(check.get("duplicate_option_labels", [])) or "geen"))
            set_box(options_box, "ANTWOORDOPTIES\n" + ("\n".join(option_lines) if option_lines else
                    "Geen antwoordopties herkend; controleer of dit een open vraag is."))
            refs = row.get("context_verwijzingen", [])
            ref_lines = [f"{x.get('kind')} {x.get('number') or ''}: {x.get('matched_text')}" for x in refs]
            set_box(context_box, "CONTEXTVERWIJZINGEN\n" + ("\n".join(ref_lines) if ref_lines else
                    "Geen expliciete figuur-, tabel-, bron- of tekstverwijzing herkend."))
            status_label.configure(text=f"Vraag {row.get('number')} geselecteerd · {idx + 1} van {len(rows)}")

        def decide(is_question):
            idx = selected_index["value"]
            if idx is None:
                messagebox.showinfo("Selecteer kandidaat", "Selecteer eerst een vraagstart.", parent=win)
                return
            row = rows[idx]
            old_status = row.get("status")
            row["status"] = "bevestigd_vraagstart" if is_question else "afgewezen_geen_vraag"
            row["human_decision"] = bool(is_question)
            row["decision_reason"] = "Handmatig bevestigd in de doorlopende vraagcontrole."
            suppression_key = f"{row.get('document_id')}|{row.get('number')}|{row.get('page')}|{float(row.get('bbox',[0,0])[1]):.1f}"
            if not is_question:
                self.data["restored_suppressed_candidate_keys"] = [
                    x for x in self.data.get("restored_suppressed_candidate_keys", []) if x != suppression_key]
                for record in self.data.get("vraagrecords", []):
                    if (record.get("candidate_document_id") == row.get("document_id")
                        and record.get("number") == row.get("number")
                        and record.get("source_page") == row.get("page")):
                        record["approved_by_human"] = False
                        record["status"] = "vraagstart_afgewezen_record_ongeldig"
                        record["source_analysis_invalidated"] = True
                        record["approval_revoked_reason"] = "De bijbehorende vraagstart is handmatig afgewezen."
            learn_decision(self.knowledge_dir, {
                "pattern_key": question_pattern_key(row),
                "chosen": "question" if is_question else "not_question",
                "accepted": True, "scope": "voorstel_voor_toekomstige_herkenning",
                "document_id": row.get("document_id"), "page": row.get("page"),
                "candidate_line": row.get("line"), "reason": row["decision_reason"],
                "human_decision": bool(is_question)})
            self.save_project()
            tree.set(str(idx), "status", row["status"].replace("_", " "))
            self._log(f"Kandidaat vraag {row['number']} op pagina {row['page']}: {row['status']}.")
            # Move to the next undecided item so a whole exam can be reviewed continuously.
            next_idx = next((n for n in range(idx + 1, len(rows))
                             if rows[n].get("human_decision") is None), None)
            if next_idx is None:
                next_idx = next((n for n, item in enumerate(rows)
                                 if item.get("human_decision") is None), None)
            if next_idx is not None:
                refresh_rows(next_idx)
            else:
                refresh_rows(idx)
                status_label.configure(text="Alle zichtbare kandidaten zijn beoordeeld. Controleer eventueel onderdrukte dubbelingen.")
            if old_status == "afgewezen_geen_vraag" and is_question:
                self._log("Eerder afgewezen vraagstart opnieuw bevestigd.")

        def inspect_original():
            idx = selected_index["value"]
            if idx is not None:
                self.preview_candidate(rows, tree, win)

        def make_record():
            idx = selected_index["value"]
            if idx is None:
                messagebox.showinfo("Selecteer kandidaat", "Selecteer eerst een vraagstart.", parent=win)
                return
            if rows[idx].get("human_decision") is not True:
                messagebox.showwarning("Vraagstart eerst bevestigen",
                    "Bevestig eerst dat dit een echte vraagstart is.", parent=win)
                return
            # Existing full record editor remains available after question-start review.
            self.create_question_record(rows, tree, win)

        tree.bind("<<TreeviewSelect>>", show_selected)
        ttk.Button(footer, text="Originele pagina", command=inspect_original).pack(side="right", padx=4)
        ttk.Button(footer, text="Concept-vraagrecord maken", command=make_record).pack(side="right", padx=4)
        ttk.Button(footer, text="Geen vraag", command=lambda: decide(False)).pack(side="right", padx=4)
        ttk.Button(footer, text="Bevestig vraag", command=lambda: decide(True), style="Accent.TButton").pack(side="right", padx=4)
        ttk.Button(footer, text="Onderdrukte dubbelingen",
                   command=lambda: self.show_suppressed_candidates(win)).pack(side="left", padx=4)
        if rows:
            refresh_rows(next((i for i, row in enumerate(rows) if row.get("human_decision") is None), 0))
        else:
            set_box(question_box, "Er zijn nog geen vraagstartkandidaten. Voer eerst de vraaganalyse uit.")
            set_box(options_box, "ANTWOORDOPTIES")
            set_box(context_box, "CONTEXTVERWIJZINGEN")

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
            item["human_decision"]=None
            item["reason"]="Handmatig hersteld uit onderdrukte dubbelingen; controleer de originele pagina."
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
                crop_status.configure(text=f"Originele pagina {number}. Sleep verticaal over de figuur of tabel; de strook loopt over de volledige paginabreedte.")
            def change_crop_page(delta):
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
                missing_regions = missing_question_regions(structure, [int(row["number"])])
                if structure_errors or missing_regions:
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

    def _open_structure_editor(self, doc):
        candidates = [x for x in self.data.get("vraagkandidaten", []) if x.get("document_id") == doc["id"]]
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
            index = int(sel[0])
            if not messagebox.askyesno("Fragment verwijderen", "Weet je zeker dat je dit fragment wilt verwijderen?", parent=win): return
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
        preview = tk.Toplevel(self.root)
        preview.title(doc["bestand"])
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
        source = self.project_dir / "bronnen" / doc["opslagbestand"]
        if not source.is_file():
            messagebox.showerror("Bronbestand ontbreekt", "De oorspronkelijke PDF kan niet worden gevonden. Voeg het bestand opnieuw toe.")
            return

        win = tk.Toplevel(self.root)
        win.title("Voorblad en documentmetadata controleren")
        fit_window(win, 1080, 760, 820, 560)
        win.transient(self.root)
        win.grab_set()
        body = ttk.Frame(win, padding=14)
        body.pack(fill="both", expand=True)
        preview_panel = ttk.LabelFrame(body, text="Voorblad van de originele PDF", padding=10)
        preview_panel.pack(side="left", fill="both", expand=True, padx=(0, 12))
        fields_panel = ttk.LabelFrame(body, text="Automatisch ingevulde gegevens", padding=14)
        fields_panel.pack(side="right", fill="y")
        ttk.Label(fields_panel, text=f"Document: {doc['bestand']}", wraplength=390,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 10))

        preview_temp = tempfile.TemporaryDirectory(prefix="biologie-voorblad-")
        preview_path = Path(preview_temp.name) / "voorblad.png"
        preview_label = ttk.Label(preview_panel, text="Voorblad wordt geladen…", anchor="center")
        preview_label.pack(fill="both", expand=True)
        try:
            render_page(source, 1, preview_path, scale=0.72)
            cover_photo = tk.PhotoImage(file=str(preview_path))
            preview_label.configure(image=cover_photo, text="")
            preview_label.image = cover_photo
        except Exception as exc:
            preview_label.configure(text=f"Het voorblad kon niet worden weergegeven.\n\n{exc}",
                                     wraplength=470, justify="center")
        win._preview_temp = preview_temp

        ttk.Label(fields_panel, text="Controleer de waarden aan de hand van het voorblad. Lege waarden zijn niet automatisch afgeleid.",
                  wraplength=390, justify="left").pack(anchor="w", pady=(0, 12))
        ttk.Label(fields_panel, text="Documenttype").pack(anchor="w", pady=(5, 2))
        choice = tk.StringVar(value=doc["type_voorstel"])
        ttk.Combobox(fields_panel, textvariable=choice, values=choices,
                     state="readonly", width=32).pack(anchor="w", fill="x")
        ttk.Label(fields_panel,text="Examenidentiteit (nodig om opgaven, CV en bijlagen veilig te koppelen)").pack(anchor="w",pady=(14,4))
        level=tk.StringVar(value=initial.get("level",""))
        year=tk.StringVar(value=str(initial.get("year","")))
        period=tk.StringVar(value=str(initial.get("period","")))
        for label,var,widget in [
            ("Niveau",level,ttk.Combobox(fields_panel,textvariable=level,values=["Havo","Vwo"],state="readonly",width=30)),
            ("Jaar",year,ttk.Entry(fields_panel,width=33)),
            ("Tijdvak",period,ttk.Combobox(fields_panel,textvariable=period,values=["1","2","3"],state="readonly",width=30))
        ]:
            ttk.Label(fields_panel,text=label).pack(anchor="w",pady=(7,2))
            widget.pack(anchor="w",fill="x")

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
            doc["documenttype_handmatig"] = new
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

        buttons=ttk.Frame(fields_panel); buttons.pack(fill="x",side="bottom",pady=(16,0))
        ttk.Button(buttons,text="Bevestigen",command=apply,style="Accent.TButton").pack(side="right")
        ttk.Button(buttons,text="Annuleren",command=win.destroy).pack(side="right",padx=8)

    def save_project(self):
        if not self.data or not self.project_dir:
            return
        self.data["bijgewerkt"] = now()
        temp = self.project_dir / (PROJECT_FILE + ".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.project_dir / PROJECT_FILE)
        self.project_label.configure(text=f"Project: {self.data['naam']}  ·  {self.project_dir}")

    def refresh(self):
        """Refresh document inventory, review queue and project progress."""
        documents = self.data.get("documenten", []) if self.data else []
        candidates = self.data.get("vraagkandidaten", []) if self.data else []
        records = self.data.get("vraagrecords", []) if self.data else []
        if hasattr(self, "project_label"):
            self.project_label.configure(text=(
                self.data.get("naam") or (self.project_dir.name if self.project_dir else "Actief project")
                if self.data else "Nog geen examen geopend"))
        if hasattr(self, "table"):
            for item in self.table.get_children():
                self.table.delete(item)
            for index, doc in enumerate(documents):
                self.table.insert("", "end", iid=str(index), values=(
                    doc.get("bestand", ""), doc.get("type_voorstel", "onbekend"),
                    doc.get("pagina_aantal", "—"), str(doc.get("status", "onbekend")).replace("_", " ")))
        if hasattr(self, "status"):
            undecided = sum(row.get("human_decision") is None for row in candidates)
            confirmed = sum(row.get("human_decision") is True for row in candidates)
            rejected = sum(row.get("human_decision") is False for row in candidates)
            unapproved_records = sum(not row.get("approved_by_human", False) for row in records)
            self.status.configure(text=(
                f"{len(documents)} documenten · {len(candidates)} vraagstarts "
                f"({confirmed} bevestigd, {rejected} afgewezen, {undecided} open) · "
                f"{len(records)} vraagrecords ({unapproved_records} nog niet goedgekeurd) · "
                "originele PDF's blijven leidend; niets wordt automatisch gepubliceerd."
                if self.data else "Importeer examens of open een bestaand project om te beginnen."))
        if hasattr(self, "candidate_tree") and hasattr(self, "_workspace_temp"):
            self._workspace_refresh()

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