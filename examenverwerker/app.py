from __future__ import annotations

import hashlib
import json
import os
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
from engine import analyze_pdf, detect_question_candidates, detect_cv_question_numbers, compare_question_numbering, learn_decision, render_page, render_crop, propose_question_regions, classify_document_role, infer_exam_metadata, question_pattern_key, suggest_from_learning, extract_candidate_text, detect_question_type, classify_question_with_visuals, detect_context_references, match_correction_documents, match_exam_documents, build_question_record, render_composite_crops, review_checklist_errors, extract_region_text, pdf_page_count, pixel_rect_to_pdf_bbox, propose_context_fragments, prepare_exam_preview_pdf, render_stitched_preview
from structure import FRAGMENT_TYPES, canonical_fragment_type, normalize_fragments, make_page_span, make_fragment, append_page_span, make_exam_structure, validate_exam_structure, mark_structure_stale, fragments_for_question, make_cv_fragment, validate_cv_fragment, page_spans_to_segments, missing_question_regions
from batch_import import group_exam_documents, batch_document_warnings, validate_batch_documents, resolve_examens_root
from exam_workflow import exam_workflow_state, exam_export_fingerprint, restore_import_batch

APP_VERSION = "0.17.0"
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
        self.root.title("Examenverwerker")
        fit_window(self.root, 1380, 900, 900, 620)
        self.project_dir = None
        self.data = None
        self.import_batch_paths = []
        self.import_batch_index = 0
        self.import_batch_manifest_path = None
        app_base=Path(sys.executable).parent if getattr(sys,"frozen",False) else Path(__file__).parent
        self.app_base = app_base
        # Keep user-owned projects and learning corrections outside the
        # replaceable program directory. Portable upgrades can now replace
        # code/_internal without overwriting a teacher's exam work.
        if os.name == "nt":
            data_home = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        else:
            data_home = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
        self.user_data_root = data_home / "BiologieExamenverwerker"
        self.user_projects_root = self.user_data_root / "projecten"
        self.user_projects_root.mkdir(parents=True, exist_ok=True)
        self.user_knowledge_root = self.user_data_root / "kennisbank"
        self.user_knowledge_root.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_user_data(app_base)
        self.examens_root = resolve_examens_root(app_base)
        self.knowledge_dir=self.user_knowledge_root
        self._style()
        self._build()
        self._welcome()

    def _migrate_legacy_user_data(self, app_base):
        """Copy legacy projects and learning data once; never move/delete originals."""
        legacy_knowledge = Path(app_base) / "kennisbank"
        if legacy_knowledge.is_dir():
            for original in legacy_knowledge.rglob("*"):
                if not original.is_file():
                    continue
                duplicate = self.user_knowledge_root / original.relative_to(legacy_knowledge)
                if duplicate.exists():
                    continue
                try:
                    duplicate.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, duplicate)
                    if sha256(original) != sha256(duplicate):
                        duplicate.unlink(missing_ok=True)
                        raise IOError(f"Integriteitscontrole mislukt: {original.name}")
                    self._migration_log(f"Leerbankbestand veilig gekopieerd: {duplicate.name}")
                except Exception as exc:
                    self._migration_log(f"Leerbankmigratie overgeslagen voor {original}: {exc}")
        legacy_roots = [Path(app_base) / "projecten"]
        for legacy_root in legacy_roots:
            if not legacy_root.is_dir():
                continue
            try:
                manifests = list(legacy_root.rglob(PROJECT_FILE))
            except OSError:
                continue
            for manifest in manifests:
                source = manifest.parent
                relative = source.relative_to(legacy_root)
                target = self.user_projects_root / relative
                if target.exists():
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(source, target)
                    copied_manifest = target / PROJECT_FILE
                    copied = json.loads(copied_manifest.read_text(encoding="utf-8"))
                    if copied.get("schema") != "biologie-examenproject-v1":
                        raise ValueError("Onbekend projectformaat na kopiëren.")
                    # Verify every copied project file by size and SHA-256.
                    for original in source.rglob("*"):
                        if not original.is_file():
                            continue
                        duplicate = target / original.relative_to(source)
                        if not duplicate.is_file() or original.stat().st_size != duplicate.stat().st_size:
                            raise IOError(f"Bestand niet volledig gekopieerd: {original.name}")
                        if sha256(original) != sha256(duplicate):
                            raise IOError(f"Integriteitscontrole mislukt: {original.name}")
                    self._migration_log(f"Project veilig gekopieerd naar gebruikersgegevens: {target}")
                except Exception as exc:
                    self._migration_log(f"Projectmigratie overgeslagen voor {source}: {exc}")

    def _migration_log(self, message):
        try:
            log_dir = self.user_data_root / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with (log_dir / "migratie.log").open("a", encoding="utf-8") as handle:
                handle.write(f"{now()} {message}\\n")
        except Exception:
            pass

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
        style.configure("WorkflowTitle.TLabel", background=self.colors["canvas"],
                        font=("Segoe UI", 9, "bold"), foreground=self.colors["wine"])
        style.configure("WorkflowText.TLabel", background=self.colors["canvas"],
                        font=("Segoe UI", 9), foreground=self.colors["muted"])
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
        """Main window: exam library only."""
        self.root.title("Examenverwerker · Examenbibliotheek")
        fit_window(self.root, 1180, 780, 860, 560)
        shell = ttk.Frame(self.root, style="App.TFrame", padding=18)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="EXAMENBIBLIOTHEEK", style="Title.TLabel").pack(anchor="w")
        ttk.Label(shell, text="Beheer examens en open een afzonderlijke verwerkingswerkruimte.",
                  style="WorkflowText.TLabel").pack(anchor="w", pady=(3, 14))
        toolbar = ttk.Frame(shell, style="App.TFrame")
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="＋ Examens importeren", command=self.import_year_set,
                   style="Accent.TButton").pack(side="left")
        ttk.Button(toolbar, text="Examen openen", command=self.open_project,
                   style="Wine.TButton").pack(side="left", padx=7)
        ttk.Button(toolbar, text="Archiveren", command=self._archive_selected_exam,
                   style="Secondary.TButton").pack(side="left", padx=7)
        ttk.Button(toolbar, text="Verwijderen", command=self._delete_selected_exam,
                   style="Secondary.TButton").pack(side="left")
        filters = ttk.LabelFrame(shell, text="FILTERS", padding=9)
        filters.pack(fill="x", pady=(0, 9))
        self._library_filters = {}
        specs = [
            ("vak", "Vak", ["Alle vakken"]), ("level", "Niveau", ["Alle niveaus", "Havo", "Vwo"]),
            ("year", "Jaar", ["Alle jaren"]), ("period", "Tijdvak", ["Alle tijdvakken", "1", "2", "3"]),
            ("archived", "Archief", ["Actieve examens", "Gearchiveerd", "Alles"]),
        ]
        for i, (key, label, values) in enumerate(specs):
            cell = ttk.Frame(filters)
            cell.grid(row=0, column=i, sticky="ew", padx=(0, 8))
            filters.columnconfigure(i, weight=1)
            ttk.Label(cell, text=label, style="Muted.TLabel").pack(anchor="w")
            var = tk.StringVar(value=values[0])
            combo = ttk.Combobox(cell, textvariable=var, values=values, state="readonly", width=16)
            combo.pack(fill="x", pady=(3, 0))
            combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_library())
            self._library_filters[key] = var
            setattr(self, f"_library_{key}_combo", combo)
        panel = ttk.LabelFrame(shell, text="EXAMENS", padding=8)
        panel.pack(fill="both", expand=True)
        columns = ("subject", "level", "year", "period", "documents", "questions", "progress", "updated")
        self.library_table = ttk.Treeview(panel, columns=columns, show="headings", selectmode="browse")
        for col, label, width in [
            ("subject", "Vak", 130), ("level", "Niveau", 75), ("year", "Jaar", 65),
            ("period", "Tijdvak", 70), ("documents", "PDF's", 55), ("questions", "Vraagstarts", 85),
            ("progress", "Verwerkingsstatus", 230), ("updated", "Laatst opgeslagen", 145),
        ]:
            self.library_table.heading(col, text=label)
            self.library_table.column(col, width=width, minwidth=45,
                anchor="w" if col in ("subject", "progress") else "center")
        scroll = ttk.Scrollbar(panel, orient="vertical", command=self.library_table.yview)
        self.library_table.configure(yscrollcommand=scroll.set)
        self.library_table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.library_table.bind("<Double-1>", lambda _e: self.open_project())
        footer = ttk.Frame(shell, style="App.TFrame")
        footer.pack(fill="x", pady=(9, 0))
        self.library_status = ttk.Label(footer, text="", style="Status.TLabel")
        self.library_status.pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="Vernieuwen", command=self._refresh_library,
                   style="Secondary.TButton").pack(side="right")
        log_frame = ttk.LabelFrame(shell, text="ACTIVITEIT EN MELDINGEN", padding=(7, 4))
        log_frame.pack(fill="x", pady=(8, 0))
        self.log = tk.Text(log_frame, height=2, wrap="word", font=("Segoe UI", 8),
                           background="#FBFCFC", foreground=self.colors["ink"],
                           insertbackground=self.colors["ink"], relief="flat", padx=7, pady=4)
        self.log.pack(fill="x")
        self.log.configure(state="disabled")
        self._library_paths = {}
        self._open_workspaces = {}
        self._refresh_library()
        self.root.protocol("WM_DELETE_WINDOW", self._close_application)

    def _discover_library_projects(self):
        roots = [self.examens_root, self.user_projects_root, self.app_base / "projecten"]
        found, seen = [], set()
        legacy_root = self.app_base / "projecten"
        for root in roots:
            if not root.exists():
                continue
            try:
                manifests = sorted(root.rglob(PROJECT_FILE), key=lambda p: p.stat().st_mtime, reverse=True)
            except OSError:
                continue
            for manifest in manifests:
                folder = manifest.parent
                try:
                    resolved = folder.resolve()
                    if resolved in seen:
                        continue
                    if root.resolve() == legacy_root.resolve():
                        migrated = self.user_projects_root / folder.relative_to(legacy_root)
                        if migrated.exists() and (migrated / PROJECT_FILE).is_file():
                            continue
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    if data.get("schema") != "biologie-examenproject-v1":
                        continue
                    seen.add(resolved)
                    meta = data.get("exam_metadata") or {}
                    updated = data.get("bijgewerkt", "")
                    try:
                        updated_label = datetime.fromisoformat(updated).astimezone().strftime("%d-%m-%Y %H:%M") if updated else "—"
                    except Exception:
                        updated_label = str(updated)[:16].replace("T", " ") or "—"
                    found.append({
                        "folder": folder, "subject": data.get("vak", "Onbekend"),
                        "level": meta.get("level", ""), "year": str(meta.get("year", "")),
                        "period": str(meta.get("period", "")), "documents": len(data.get("documenten", [])),
                        "questions": len(data.get("vraagkandidaten", [])),
                        "progress": exam_workflow_state(data)["label"], "updated": updated_label,
                        "archived": bool(data.get("bibliotheek_archief", False)),
                    })
                except Exception as exc:
                    self._log(f"Project overgeslagen in bibliotheek ({folder.name}): {exc}")
        found.sort(key=lambda row: (not row["archived"], row["year"], row["level"],
                                    row["period"], row["subject"]), reverse=True)
        return found

    def _refresh_library(self):
        if not hasattr(self, "library_table"):
            return
        rows = self._discover_library_projects()
        for key, options, label in [
            ("vak", sorted({r["subject"] for r in rows}, key=str.casefold), "Alle vakken"),
            ("year", sorted({r["year"] for r in rows if r["year"]}, reverse=True), "Alle jaren"),
        ]:
            choices = [label] + options
            combo = getattr(self, f"_library_{key}_combo", None)
            if combo:
                combo.configure(values=choices)
            if self._library_filters[key].get() not in choices:
                self._library_filters[key].set(label)
        for item in self.library_table.get_children():
            self.library_table.delete(item)
        self._library_paths = {}
        filters = {k: v.get() for k, v in self._library_filters.items()}
        count = 0
        for row in rows:
            if filters["vak"] != "Alle vakken" and row["subject"] != filters["vak"]:
                continue
            if filters["level"] != "Alle niveaus" and row["level"] != filters["level"]:
                continue
            if filters["year"] != "Alle jaren" and row["year"] != filters["year"]:
                continue
            if filters["period"] != "Alle tijdvakken" and row["period"] != filters["period"]:
                continue
            if filters["archived"] == "Actieve examens" and row["archived"]:
                continue
            if filters["archived"] == "Gearchiveerd" and not row["archived"]:
                continue
            iid = str(count)
            self._library_paths[iid] = row["folder"]
            self.library_table.insert("", "end", iid=iid, values=(
                row["subject"], row["level"] or "—", row["year"] or "—", row["period"] or "—",
                row["documents"], row["questions"],
                ("Archief · " if row["archived"] else "") + row["progress"], row["updated"]))
            count += 1
        self.library_status.configure(text=f"{count} examens zichtbaar · {len(rows)} in totaal")

    def _selected_library_folder(self):
        selection = self.library_table.selection() if hasattr(self, "library_table") else ()
        return self._library_paths.get(selection[0]) if selection else None

    def _launch_workspace(self, folder, data=None):
        folder = Path(folder)
        key = str(folder.resolve())
        existing = self._open_workspaces.get(key)
        if existing is not None:
            try:
                if existing.root.winfo_exists():
                    existing.root.deiconify()
                    existing.root.lift()
                    existing.root.focus_force()
                    return existing
            except tk.TclError:
                pass
        try:
            loaded = data if data is not None else json.loads((folder / PROJECT_FILE).read_text(encoding="utf-8"))
            if loaded.get("schema") != "biologie-examenproject-v1":
                raise ValueError("Onbekend examenformaat.")
            win = tk.Toplevel(self.root)
            workspace = object.__new__(ExamApp)
            workspace.__dict__ = self.__dict__.copy()
            workspace.root = win
            workspace.project_dir = folder
            workspace.data = loaded
            workspace._workspace_owner = self
            workspace._workspace_key = key
            workspace._restore_import_batch(folder, loaded)
            workspace._build_workspace()
            workspace._workspace_load_global_corrections()
            workspace.refresh()
            meta = loaded.get("exam_metadata") or {}
            title = " · ".join(str(value) for value in [
                loaded.get("vak", "Examen"), meta.get("level", ""), meta.get("year", ""),
                f"tijdvak {meta.get('period', '')}".strip()
            ] if value)
            win.title(f"Examenverwerking · {title}")
            def close_workspace():
                try:
                    workspace.save_project()
                except Exception as exc:
                    workspace._error("Project opslaan bij sluiten", exc)
                    if not messagebox.askyesno("Opslaan niet gelukt",
                        "De laatste wijzigingen konden niet worden opgeslagen. Toch sluiten?", parent=win):
                        return
                self._open_workspaces.pop(workspace._workspace_key, None)
                try:
                    win.destroy()
                finally:
                    self._refresh_library()
            win.protocol("WM_DELETE_WINDOW", close_workspace)
            self._open_workspaces[key] = workspace
            workspace._log("Afzonderlijke verwerkingswerkruimte geopend. De examenbibliotheek blijft beschikbaar.")
            return workspace
        except Exception as exc:
            self._error("Examenverwerking openen", exc)
            messagebox.showerror("Examen openen mislukt",
                f"De verwerkingswerkruimte kon niet worden geopend. De projectgegevens zijn niet gewijzigd.\n\n{exc}",
                parent=self.root)
            return None

    def _close_application(self):
        """Save every open workspace before the library's Tk root is closed."""
        for key, workspace in list(self._open_workspaces.items()):
            try:
                workspace.save_project()
            except Exception as exc:
                workspace._error("Project opslaan bij afsluiten", exc)
                if not messagebox.askyesno("Opslaan niet gelukt",
                    "Een examen kon niet worden opgeslagen. Wil je de applicatie toch afsluiten?",
                    parent=self.root):
                    return
        self.root.destroy()

    def _archive_selected_exam(self):
        folder = self._selected_library_folder()
        if not folder:
            messagebox.showinfo("Selecteer een examen", "Selecteer eerst een examen.", parent=self.root)
            return
        try:
            key = str(folder.resolve())
            workspace = self._open_workspaces.get(key)
            if workspace is not None:
                workspace.data["bibliotheek_archief"] = not bool(workspace.data.get("bibliotheek_archief", False))
                workspace.save_project()
            else:
                path = folder / PROJECT_FILE
                data = json.loads(path.read_text(encoding="utf-8"))
                data["bibliotheek_archief"] = not bool(data.get("bibliotheek_archief", False))
                data["bijgewerkt"] = now()
                temp = path.with_suffix(".json.tmp")
                temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                temp.replace(path)
            self._refresh_library()
        except Exception as exc:
            self._error("Examen archiveren", exc)
            messagebox.showerror("Archiveren mislukt", str(exc), parent=self.root)

    def _delete_selected_exam(self):
        folder = self._selected_library_folder()
        if not folder:
            messagebox.showinfo("Selecteer een examen", "Selecteer eerst een examen.", parent=self.root)
            return
        if str(folder.resolve()) in self._open_workspaces:
            messagebox.showwarning("Examen is geopend",
                "Sluit eerst de bijbehorende verwerkingswerkruimte voordat je dit examen verwijdert.",
                parent=self.root)
            return
        if not messagebox.askyesno("Examen verwijderen",
            "Het volledige examenproject, inclusief gekopieerde bron-PDF's en controles, wordt naar de herstelbare map 'verwijderd' verplaatst. Doorgaan?",
            parent=self.root):
            return
        try:
            destination_root = self.user_data_root / "verwijderd"
            destination_root.mkdir(parents=True, exist_ok=True)
            destination = destination_root / f"{folder.name}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
            shutil.move(str(folder), str(destination))
            self._refresh_library()
            self._log(f"Examen verplaatst naar herstelbare map: {destination}")
        except Exception as exc:
            self._error("Examen verwijderen", exc)
            messagebox.showerror("Verwijderen mislukt", str(exc), parent=self.root)

    def open_project(self):
        """Open the selected exam in its own processing window."""
        folder = self._selected_library_folder()
        if folder is None:
            messagebox.showinfo("Selecteer een examen",
                "Selecteer eerst een examen in de bibliotheek.", parent=self.root)
            return
        self._launch_workspace(folder)

    def _show_exam_library(self):
        owner = getattr(self, "_workspace_owner", None)
        if owner is None:
            return
        try:
            owner.root.deiconify()
            owner.root.lift()
            owner.root.focus_force()
        except tk.TclError:
            pass

    def _build_workspace(self):
        """Build the complete exam-processing workspace in its own window."""
        self.root.title("Examenverwerker")
        fit_window(self.root, 1440, 920, 980, 640)
        shell = ttk.Frame(self.root, style="App.TFrame", padding=10)
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="App.TFrame")
        header.pack(fill="x", pady=(0, 8))
        brand = ttk.Frame(header, style="App.TFrame")
        brand.pack(side="left", fill="x", expand=True)
        ttk.Label(brand, text="EXAMENVERWERKER", style="Title.TLabel").pack(anchor="w")
        ttk.Label(brand, text="Werkruimte voor volledige, visueel gecontroleerde examenverwerking",
                  style="Muted.TLabel").pack(anchor="w", pady=(1, 0))
        self.project_label = ttk.Label(header, text="Kies een examen uit de bibliotheek", style="Project.TLabel")
        self.project_label.pack(side="right", padx=10)

        toolbar = ttk.Frame(shell, style="App.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        actions = [
            ("Examenbibliotheek tonen", self._show_exam_library, "Secondary.TButton"),
            ("Vraagstarts analyseren", self.analyze_questions, "Secondary.TButton"),
            ("Structuur bewerken", self.edit_exam_structure, "Secondary.TButton"),
            ("Eindcontrole", self.show_records, "Secondary.TButton"),
            ("Exportpakket", self.export_project, "Wine.TButton"),
        ]
        for label, callback, style in actions[:4]:
            ttk.Button(toolbar, text=label, command=callback, style=style).pack(side="left", padx=(0, 5))
        toolbar_secondary = ttk.Frame(shell, style="App.TFrame")
        toolbar_secondary.pack(fill="x", pady=(0, 5))
        for label, callback, style in actions[4:]:
            ttk.Button(toolbar_secondary, text=label, command=callback, style=style).pack(side="left", padx=(0, 5))

        # A compact, contextual next-step strip keeps the original workbench
        # layout intact while making the hand-off between processing stages explicit.
        workflow_bar = ttk.Frame(shell, style="App.TFrame")
        workflow_bar.pack(fill="x", pady=(0, 7))
        ttk.Label(workflow_bar, text="VERVOLG", style="WorkflowTitle.TLabel").pack(side="left", padx=(2, 10))
        self.workflow_label = ttk.Label(workflow_bar, text="Importeer een examen om te beginnen.",
                                        style="WorkflowText.TLabel")
        self.workflow_label.pack(side="left", fill="x", expand=True)
        self.workflow_button = ttk.Button(workflow_bar, text="Examens importeren",
                                          command=self.import_year_set, style="Accent.TButton")
        self.workflow_button.pack(side="right")

        correction_bar = ttk.Frame(shell, style="App.TFrame")
        self.correction_bar = correction_bar
        self.correction_import_button = ttk.Button(
            correction_bar, text="Correcties uit Biologie-controle importeren",
            command=self._workspace_import_corrections)
        self.correction_import_button.pack(side="left", padx=(0, 5))
        self.correction_export_button = ttk.Button(
            correction_bar, text="Beoordelingen exporteren",
            command=self._workspace_export_corrections)
        self.correction_export_button.pack(side="left")
        ttk.Label(correction_bar,
                  text="Bewaart besluiten, notities, vraagnummercorrecties en exacte PDF-posities.",
                  style="Muted.TLabel").pack(side="left", padx=10)

        workspace = ttk.Panedwindow(shell, orient="horizontal")
        workspace.pack(fill="both", expand=True)
        left = ttk.Frame(workspace, style="App.TFrame", padding=(0, 0, 6, 0))
        right = ttk.Frame(workspace, style="App.TFrame", padding=(6, 0, 0, 0))
        self._workspace_container = workspace
        self._workspace_left = left
        self._workspace_right = right
        workspace.add(left, weight=3)
        workspace.add(right, weight=8)

        # Left column: source documents and question candidates.
        docs_card = ttk.LabelFrame(left, text="DOCUMENTEN", padding=7)
        docs_card.pack(fill="both", expand=True, pady=(0, 7))
        doc_actions = ttk.Frame(docs_card)
        doc_actions.pack(fill="x", pady=(0, 5))
        ttk.Button(doc_actions, text="Aanvullende PDF's", command=self.add_pdfs).pack(side="left")
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
        self._workspace_y_scrollbar = pdf_y
        self.pdf_canvas.configure(yscrollcommand=self._workspace_scroll_changed, xscrollcommand=pdf_x.set)
        self.pdf_canvas.pack(side="left", fill="both", expand=True)
        pdf_y.pack(side="right", fill="y")
        pdf_x.pack(fill="x")
        self.pdf_canvas.bind("<Button-1>", self._workspace_canvas_click)
        self.pdf_canvas.bind("<MouseWheel>", lambda e: self.pdf_canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.pdf_canvas.bind("<Configure>", lambda _event: self.root.after_idle(self._workspace_render_visible_pages))

        self._workspace_summary = ttk.Label(review, text="Selecteer een document of vraagstart.",
                                            style="Body.TLabel", wraplength=330, justify="left")
        self._workspace_summary.pack(fill="x", anchor="w", pady=(0, 8))
        number_row = ttk.Frame(review)
        number_row.pack(fill="x", pady=(0, 5))
        ttk.Label(number_row, text="Vraagnummer").pack(side="left")
        self._workspace_number = tk.StringVar()
        ttk.Entry(number_row, textvariable=self._workspace_number, width=7).pack(side="left", padx=6)
        ttk.Button(number_row, text="Opslaan", command=self._workspace_save_candidate).pack(side="right")

        # Keep the decision controls above the expanding text editor.  With
        # the editor packed first using expand=True, Tk can allocate the whole
        # short review panel to it and push the approval buttons below the
        # visible area on ordinary laptop/window sizes.
        decision_box = ttk.LabelFrame(review, text="BEOORDELING VRAAGSTART", padding=(6, 5))
        decision_box.pack(side="top", fill="x", pady=(0, 6))
        decision_row = ttk.Frame(decision_box)
        decision_row.pack(fill="x")
        ttk.Button(decision_row, text="✓ Akkoord", command=lambda: self._workspace_decide(True),
                   style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(decision_row, text="✕ Geen vraag", command=lambda: self._workspace_decide(False),
                   style="Secondary.TButton").pack(side="left", fill="x", expand=True, padx=3)
        ttk.Button(decision_row, text="? Twijfel", command=lambda: self._workspace_decide(None),
                   style="Secondary.TButton").pack(side="left", fill="x", expand=True, padx=(3, 0))
        ttk.Button(review, text="Concept-vraagrecord samenstellen",
                   command=self._workspace_create_record, style="Wine.TButton").pack(side="top", fill="x", pady=(0, 5))
        ttk.Button(review, text="Onderdrukte nummerkandidaten bekijken",
                   command=lambda: self.show_suppressed_candidates(self.root)).pack(side="top", fill="x", pady=(0, 5))
        ttk.Label(review, text="Vraagtekst / opdrachtformulering").pack(anchor="w")
        self._workspace_text = tk.Text(review, height=5, wrap="word", font=("Segoe UI", 9),
                                       undo=True, padx=7, pady=6)
        self._workspace_text.pack(fill="both", expand=True, pady=(3, 5))
        self._workspace_detected_details = ttk.Label(review, text="", style="Muted.TLabel",
            wraplength=330, justify="left")
        self._workspace_detected_details.pack(fill="x", pady=(0, 4))
        ttk.Label(review, text="Notitie bij de beoordeling").pack(anchor="w")
        self._workspace_note = tk.Text(review, height=2, wrap="word", font=("Segoe UI", 9),
                                       undo=True, padx=7, pady=5)
        self._workspace_note.pack(fill="x", pady=(3, 4))
        ttk.Button(review, text="Tekst en notitie bewaren", command=self._workspace_save_candidate,
                   style="Secondary.TButton").pack(side="top", fill="x", pady=(0, 2))

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

    def _workflow_refresh(self):
        """Show the next safe action derived from the saved state of this exam."""
        if not hasattr(self, "workflow_button"):
            return
        if not self.data:
            self.workflow_label.configure(
                text="Open de examenbibliotheek om examens te importeren of een ander examen te kiezen.")
            self.workflow_button.configure(text="Examenbibliotheek tonen", command=self._show_exam_library)
            return

        state = exam_workflow_state(self.data)
        # Once the teacher-confirmed fragment geometry is complete, create
        # lightweight records automatically. This is not another fragment
        # review step; the records are then used for the separate question analysis.
        if state["stage"] == "vraaganalyse" and not getattr(self, "_auto_creating_drafts", False):
            source_docs = [d for d in self.data.get("documenten", [])
                           if d.get("type_voorstel") == "opgaven"]
            missing = False
            for doc in source_docs:
                confirmed = [r for r in self.data.get("vraagkandidaten", [])
                             if r.get("document_id") == doc.get("id")
                             and r.get("human_decision") is True]
                records = [r for r in self.data.get("vraagrecords", [])
                           if r.get("candidate_document_id") == doc.get("id")]
                if len(records) < len(confirmed):
                    missing = True
                    break
            if missing:
                self._auto_creating_drafts = True
                try:
                    self._workflow_make_next_record(refresh_after=False)
                    state = exam_workflow_state(self.data)
                finally:
                    self._auto_creating_drafts = False
        actions = {
            "import": ("Examenbibliotheek tonen", self._show_exam_library),
            "documenttype": ("Documenttype bevestigen", self.correct_type),
            "metadata": ("Examengegevens bevestigen", self.edit_exam_metadata),
            "vraagstarts": ("Vraagstarts beoordelen", self.show_candidates),
            "opgaven_fragmenten": ("Context- en vraagfragmenten", self.edit_exam_structure),
            "vraaganalyse": ("Vraagtype en punten controleren", self.show_records),
            "uitwerkbijlage_starts": ("Uitwerkbijlage controleren", self.show_records),
            "uitwerkbijlage_fragmenten": ("Uitwerkbijlagefragmenten", self.show_records),
            "cv_starts": ("Correctievoorschrift controleren", self.show_records),
            "cv_fragmenten": ("CV-fragmenten controleren", self.show_records),
            "aanvulling": ("CV-aanvulling verwerken", self.show_records),
            "antwoorden": ("Correcte antwoorden controleren", self.show_records),
            "volledigheid": ("Volledigheidscontrole", self.show_records),
            "snippets": ("Vraaguitsneden controleren", self.show_records),
            "eindcontrole": ("Visuele eindcontrole", self.show_records),
            "export": ("Exportpakket maken", self.export_project),
            "voltooid": ("Examenbibliotheek tonen", self._show_exam_library),
        }
        label = state["label"]
        if state["stage"] == "voltooid" and self.import_batch_index + 1 < len(self.import_batch_paths):
            label = (f"Dit examen is verwerkt. Ga door met examen "
                     f"{self.import_batch_index + 2} van {len(self.import_batch_paths)} uit dezelfde importbatch.")
            button, action = "Volgend examen", self._workflow_open_next_exam
        else:
            button, action = actions[state["stage"]]
        self.workflow_label.configure(text=f"Volgende stap · {label}. {state['action']}")
        self.workflow_button.configure(text=button, command=action)

    def _restore_import_batch(self, folder, data):
        """Restore the import queue, if this exam belongs to a saved batch."""
        restored = restore_import_batch(self.examens_root, folder, data, PROJECT_FILE)
        self.import_batch_paths = []
        self.import_batch_index = 0
        self.import_batch_manifest_path = None
        if restored:
            self.import_batch_paths = restored["paths"]
            self.import_batch_index = restored["index"]
            self.import_batch_manifest_path = restored["manifest_path"]
        else:
            self._log("Voor dit examen is geen geldige importbatch beschikbaar; het examen blijft afzonderlijk verwerkbaar.")

    def _workflow_open_next_exam(self):
        next_index = self.import_batch_index + 1
        if next_index >= len(self.import_batch_paths):
            return
        next_project = self.import_batch_paths[next_index]
        owner = getattr(self, "_workspace_owner", None)
        old_key = getattr(self, "_workspace_key", None)
        next_key = str(next_project.resolve())
        if owner is not None:
            already_open = owner._open_workspaces.get(next_key)
            if already_open is not None and already_open is not self:
                try:
                    already_open.root.deiconify()
                    already_open.root.lift()
                    already_open.root.focus_force()
                except tk.TclError:
                    pass
                messagebox.showinfo("Examen al geopend",
                    "Het volgende examen uit deze importbatch staat al in een eigen verwerkingsvenster. "
                    "Gebruik dat venster om verder te werken.", parent=self.root)
                return
        previous = (self.project_dir, self.data, self.import_batch_index,
                    getattr(self, "_workspace_doc_id", None),
                    getattr(self, "_workspace_selected", None), old_key)
        try:
            next_data = json.loads((next_project / PROJECT_FILE).read_text(encoding="utf-8"))
            if next_data.get("schema") != "biologie-examenproject-v1":
                raise ValueError("Onbekend examenformaat.")
            self.save_project()
            if owner is not None and old_key:
                owner._open_workspaces.pop(old_key, None)
            self.project_dir = next_project
            self.data = next_data
            self.import_batch_index = next_index
            self._workspace_key = next_key
            if owner is not None:
                owner._open_workspaces[next_key] = self
            self._workspace_doc_id = None
            self._workspace_selected = None
            self._workspace_load_global_corrections()
            self.refresh()
            if owner is not None:
                owner._refresh_library()
            meta = self.data.get("exam_metadata", {})
            self._log(f"Verder met examen {self.import_batch_index + 1}/{len(self.import_batch_paths)}: "
                      f"{meta.get('level', '')} {meta.get('year', '')} tijdvak {meta.get('period', '')}.")
        except Exception as exc:
            self.project_dir, self.data, self.import_batch_index = previous[:3]
            self._workspace_doc_id, self._workspace_selected = previous[3:5]
            self._workspace_key = previous[5]
            if owner is not None and old_key:
                owner._open_workspaces.pop(next_key, None)
                owner._open_workspaces[old_key] = self
            try:
                self._workspace_load_global_corrections()
                self.refresh()
            except Exception as restore_exc:
                self._log(f"Herstel van de vorige werkruimte gaf een fout: {restore_exc}")
            self._error("Volgend examen openen", exc)
            messagebox.showerror("Examen openen mislukt",
                "Het volgende examen kon niet worden geopend. De vorige werkruimte en batchpositie zijn hersteld.",
                parent=self.root)

    def _workflow_focus_next(self):
        if not self.data:
            return
        row = next((r for r in self.data.get("vraagkandidaten", [])
                    if r.get("human_decision") is None), None)
        if row is None:
            self._workflow_refresh()
            return
        self._workspace_filter.set("Alle kandidaten")
        if row.get("document_id") != self._workspace_doc_id:
            self._workspace_doc_id = row.get("document_id")
            self._workspace_selected = None
            self._workspace_refresh()
        else:
            index = next((i for i, item in enumerate(self._workspace_rows)
                          if item.get("id") == row.get("id")), 0)
            self._workspace_refresh_candidates(index)

    def _workflow_make_next_record(self, refresh_after=True):
        """Backfill simple drafts for older projects whose fragments were already saved."""
        if not self.data:
            return
        source_docs=[doc for doc in self.data.get("documenten",[])
                     if doc.get("type_voorstel")=="opgaven"]
        created=0
        try:
            for doc in source_docs:
                structure=(self.data.get("exam_structures",{}).get(doc.get("id"))
                           or self.data.get("exam_structure"))
                confirmed=[row for row in self.data.get("vraagkandidaten",[])
                           if row.get("document_id")==doc.get("id")
                           and row.get("human_decision") is True]
                if structure and confirmed:
                    created += self._classify_question_types_for_document(doc)
            if refresh_after:
                self.refresh()
            self._log(f"Conceptvragen bijgewerkt vanuit opgeslagen fragmenten: {created}.")
        except Exception as exc:
            self._error("Conceptvragen maken",exc)
            messagebox.showerror(
                "Conceptvragen niet aangemaakt",
                "De opgeslagen fragmenten zijn niet aangepast. Controleer de bronbestanden en probeer opnieuw.\n\n"+str(exc),
                parent=self.root,
            )

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
            f"{x.get('label','?')} {x.get('text','')}" for x in options) if options else "geen tekstopties herkend")
        visual = check.get("visual_detection", {})
        if visual.get("requires_visual_review"):
            option_text += (f"\nVisuele controle: {visual.get('status','beeldmateriaal gevonden').replace('_',' ')}"
                            f" · {visual.get('visual_asset_count',0)} beeldelement(en)"
                            f" · labels {', '.join(visual.get('nearby_option_labels',[])) or 'niet als tekst herkend'}")
        references = row.get("context_verwijzingen", [])
        reference_text = "Verwijzingen: " + (" · ".join(
            f"{x.get('kind','')} {x.get('number') or ''}" for x in references) if references else "geen expliciete verwijzingen herkend")
        self._workspace_detected_details.configure(text=option_text + "\n" + reference_text)
        self._workspace_page = int(row.get("page", 1))
        self._workspace_render_page()

    def _workspace_render_page(self):
        """Lay out the complete PDF, but keep only nearby pages as Tk images in memory."""
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
            with fitz.open(source) as pdf:
                page_count = len(pdf)
                if not page_count:
                    raise ValueError("PDF bevat geen pagina's.")
                canvas_width = max(420, self.pdf_canvas.winfo_width() - 30)
                fit_scale = min(1.35, canvas_width / float(pdf[0].rect.width))
                scale = max(0.45, fit_scale * self._workspace_zoom)
                page_dimensions = {
                    page_no: (
                        max(1, int(round(float(page.rect.width) * scale))),
                        max(1, int(round(float(page.rect.height) * scale))),
                    )
                    for page_no, page in enumerate(pdf, start=1)
                }

            self._workspace_scale = scale
            self._workspace_page_offsets = {}
            self._workspace_page_heights = {}
            self._workspace_page_specs = {}
            self._workspace_page_placeholders = {}
            self._workspace_page_image_items = {}
            self._workspace_photos = {}
            self.pdf_canvas.delete("all")
            y_offset = 0
            max_page_width = canvas_width
            for page_no in range(1, page_count + 1):
                width, height = page_dimensions[page_no]
                output = Path(self._workspace_temp.name) / f"{doc['id']}-doorlopend-p{page_no}-{scale:.3f}.png"
                self._workspace_page_offsets[page_no] = y_offset
                self._workspace_page_heights[page_no] = height
                self._workspace_page_specs[page_no] = {
                    "output": output, "width": width, "height": height,
                }
                max_page_width = max(max_page_width, width)
                placeholder = self.pdf_canvas.create_rectangle(
                    0, y_offset, width, y_offset + height,
                    fill="white", outline="#C5CDD1", tags=("page-placeholder", f"page-{page_no}")
                )
                label = self.pdf_canvas.create_text(
                    width / 2, y_offset + height / 2, text=f"Pagina {page_no} wordt geladen…",
                    fill="#718087", font=("Segoe UI", 10),
                    tags=("page-placeholder", f"page-{page_no}")
                )
                self._workspace_page_placeholders[page_no] = (placeholder, label)
                y_offset += height
                if page_no < page_count:
                    self.pdf_canvas.create_line(
                        0, y_offset + 3, max(width, canvas_width), y_offset + 3,
                        fill="#9AA7AD", dash=(3, 4), tags=("page-separator",)
                    )
                    y_offset += 8

            self.pdf_canvas.configure(scrollregion=(0, 0, max_page_width, y_offset))
            for candidate in self.data.get("vraagkandidaten", []):
                if candidate.get("document_id") != doc["id"] or not candidate.get("bbox"):
                    continue
                page_no = int(candidate.get("page", 1))
                if page_no not in self._workspace_page_offsets:
                    continue
                x0, y0, x1, y1 = [float(value) * scale for value in candidate["bbox"]]
                top = self._workspace_page_offsets[page_no] + y0
                selected = candidate is self._workspace_selected
                color = "#D71920" if selected else "#168B8B"
                self.pdf_canvas.create_rectangle(
                    x0 - 5, top - 4, x1 + 5, top + max(18, (y1 - y0)) + 4,
                    outline=color, width=3 if selected else 1, tags=("marker",)
                )
                self.pdf_canvas.create_text(
                    x0 + 5, top - 13, text=f"Vraag {candidate.get('number')}",
                    anchor="sw", fill=color, font=("Segoe UI", 10, "bold"), tags=("marker",)
                )

            row = self._workspace_selected
            if row:
                page_no = int(row.get("page", 1))
                if page_no in self._workspace_page_offsets:
                    target_y = self._workspace_page_offsets[page_no] + float((row.get("bbox") or [0, 0])[1]) * scale
                    self.pdf_canvas.yview_moveto(max(0, target_y / max(1, y_offset)))
                    self._workspace_page = page_no
            self._workspace_page_label.configure(text=f"Doorlopend · {page_count} pagina's")
            if self._workspace_mark_mode:
                self.status.configure(text="Klik op de exacte positie van de ontbrekende vraag in de doorlopende PDF.")
            self._workspace_render_visible_pages()
        except Exception as exc:
            self._error("Originele PDF weergeven", exc)

    def _workspace_render_visible_pages(self):
        """Render nearby pages on demand and cap live Tk PhotoImages to six."""
        specs = getattr(self, "_workspace_page_specs", {})
        if not specs:
            return
        try:
            if not self.pdf_canvas.winfo_exists():
                return
            viewport_top = self.pdf_canvas.canvasy(0)
            viewport_height = max(1, self.pdf_canvas.winfo_height())
            viewport_bottom = viewport_top + viewport_height
            margin = max(280, int(viewport_height * 0.75))
            wanted = {
                page_no for page_no, top in self._workspace_page_offsets.items()
                if top + self._workspace_page_heights[page_no] >= viewport_top - margin
                and top <= viewport_bottom + margin
            }
            if not wanted:
                wanted = {int(getattr(self, "_workspace_page", 1))}
            wanted = {page_no for page_no in wanted if page_no in specs}

            doc = self._workspace_doc()
            if not doc:
                return
            source = self.project_dir / "bronnen" / doc["opslagbestand"]
            for page_no in sorted(wanted):
                if page_no in self._workspace_photos:
                    continue
                spec = specs[page_no]
                try:
                    if not spec["output"].is_file():
                        render_page(source, page_no, spec["output"], scale=self._workspace_scale)
                    photo = tk.PhotoImage(file=str(spec["output"]))
                    self._workspace_photos[page_no] = photo
                    for item in self._workspace_page_placeholders.pop(page_no, ()):
                        self.pdf_canvas.delete(item)
                    image_item = self.pdf_canvas.create_image(
                        0, self._workspace_page_offsets[page_no],
                        image=photo, anchor="nw", tags=("page-image", f"page-{page_no}")
                    )
                    self.pdf_canvas.tag_lower(image_item)
                    self._workspace_page_image_items[page_no] = image_item
                except Exception as page_error:
                    for item in self._workspace_page_placeholders.get(page_no, ()):
                        if self.pdf_canvas.type(item) == "text":
                            self.pdf_canvas.itemconfigure(item, text=f"Pagina {page_no} kon niet worden geladen")
                    self._log(f"Pagina {page_no} kon niet worden weergegeven: {page_error}")

            # Keep visible pages plus a small buffer; evicted pages remain as
            # lightweight placeholders and can be restored instantly from PNG cache.
            keep = set(wanted)
            if len(keep) > 6:
                keep = set(sorted(keep, key=lambda n: abs(
                    (self._workspace_page_offsets[n] + self._workspace_page_heights[n] / 2)
                    - (viewport_top + viewport_height / 2)
                ))[:6])
            for page_no in list(self._workspace_photos):
                if page_no in keep:
                    continue
                image_item = self._workspace_page_image_items.pop(page_no, None)
                if image_item is not None:
                    self.pdf_canvas.delete(image_item)
                self._workspace_photos.pop(page_no, None)
                spec = specs[page_no]
                top = self._workspace_page_offsets[page_no]
                rect = self.pdf_canvas.create_rectangle(
                    0, top, spec["width"], top + spec["height"],
                    fill="white", outline="#C5CDD1", tags=("page-placeholder", f"page-{page_no}")
                )
                label = self.pdf_canvas.create_text(
                    spec["width"] / 2, top + spec["height"] / 2,
                    text=f"Pagina {page_no} wordt geladen…", fill="#718087",
                    font=("Segoe UI", 10), tags=("page-placeholder", f"page-{page_no}")
                )
                self._workspace_page_placeholders[page_no] = (rect, label)
        except (tk.TclError, KeyError, AttributeError):
            # A document can be switched or the window closed during an idle callback.
            return

    def _workspace_scroll_changed(self, first, last):
        """Keep the scrollbar synchronized and schedule lazy page rendering."""
        scrollbar = getattr(self, "_workspace_y_scrollbar", None)
        if scrollbar is not None:
            scrollbar.set(first, last)
        if getattr(self, "_workspace_page_specs", None) and not getattr(self, "_workspace_render_pending", False):
            self._workspace_render_pending = True
            def render_after_scroll():
                self._workspace_render_pending = False
                self._workspace_render_visible_pages()
            try:
                self.root.after_idle(render_after_scroll)
            except tk.TclError:
                self._workspace_render_pending = False

    def _workspace_change_page(self, delta):
        self._workspace_page = max(1, self._workspace_page + int(delta))
        offsets = getattr(self, "_workspace_page_offsets", {})
        heights = getattr(self, "_workspace_page_heights", {})
        if self._workspace_page in offsets:
            total = max(1, max((top + heights.get(page, 0) for page, top in offsets.items()), default=1))
            self.pdf_canvas.yview_moveto(offsets[self._workspace_page] / total)
            self._workspace_page_label.configure(text=f"Pagina {self._workspace_page} / {len(offsets)}")
        else:
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
            px = self.pdf_canvas.canvasx(event.x)
            py = self.pdf_canvas.canvasy(event.y)
            page_no = next((n for n, top in sorted(getattr(self, "_workspace_page_offsets", {}).items())
                            if top <= py < top + self._workspace_page_heights.get(n, 0)), None)
            if page_no is None:
                pdf.close()
                return
            self._workspace_page = page_no
            page = pdf[page_no-1]
            page_top = self._workspace_page_offsets[page_no]
            x, y = px / self._workspace_scale, (py - page_top) / self._workspace_scale
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
            row["vraagtype_controle"] = {"type":"nog_niet_bepaald","options":[],"reason":"Vraagsoort wordt pas bepaald nadat de snippetgrenzen zijn vastgesteld."}
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
        row["vraagtype_controle"] = {"type":"nog_niet_bepaald","options":[],"reason":"Vraagsoort wordt pas bepaald nadat de snippetgrenzen zijn vastgesteld."}
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

        # The queue covers every candidate, so do not let a local filter hide
        # the next item or cause the interface to jump to an unrelated row.
        self._workspace_filter.set("Alle kandidaten")
        # Continue across document boundaries instead of silently returning to
        # the first candidate when the current PDF has been fully reviewed.
        next_row = next((item for item in self.data.get("vraagkandidaten", [])
                         if item is not row and item.get("human_decision") is None), None)
        if next_row and next_row.get("document_id") != self._workspace_doc_id:
            self._workspace_doc_id = next_row.get("document_id")
            self._workspace_selected = None
            self._workspace_filter.set("Alle kandidaten")
            self._workspace_refresh()
        elif next_row:
            next_index = next((i for i, item in enumerate(self._workspace_rows)
                               if item.get("id") == next_row.get("id")), 0)
            self._workspace_refresh_candidates(next_index)
        elif decision is None:
            current_index = next((i for i, item in enumerate(self._workspace_rows)
                                  if item.get("id") == row.get("id")), 0)
            self._workspace_refresh_candidates(current_index)
            self.status.configure(text="Deze vraagstart blijft open voor latere nacontrole.")
            self._workflow_refresh()
        else:
            self._workspace_refresh_candidates(0)
            self.status.configure(text="Alle vraagstarts in dit examen zijn beoordeeld. De volgende stap is het afbakenen van de examenstructuur.")
            self._workflow_refresh()

    def _classify_question_types_for_document(self, doc):
        """Classify every confirmed question only after its saved question fragment exists."""
        if not self.data or not doc:
            raise ValueError("Er is geen actief examen of opgavenbestand.")
        structure = (self.data.get("exam_structures", {}).get(doc.get("id"))
                     or self.data.get("exam_structure"))
        candidates = sorted(
            [row for row in self.data.get("vraagkandidaten", [])
             if row.get("document_id") == doc.get("id") and row.get("human_decision") is True],
            key=lambda row: (int(row.get("page", 1)),
                             float((row.get("bbox") or [0, 0])[1]))
        )
        if not candidates:
            raise ValueError("Er zijn geen bevestigde vragen om te classificeren.")
        # Refuse to classify from question starts alone: every question needs
        # its manually checked, persisted question fragment first.
        # Older projects already contain teacher-reviewed fragment geometry
        # but predate the cached text field. Extract text only inside those saved
        # regions once; never rediscover question boundaries from the PDF.
        saved_fragments = structure.get("fragments", []) if structure else []
        if any("text" not in fragment for fragment in saved_fragments):
            source_path = self.project_dir / "bronnen" / doc["opslagbestand"]
            if not source_path.is_file() or sha256(source_path) != doc.get("sha256"):
                raise ValueError("De originele PDF ontbreekt of is gewijzigd; de opgeslagen fragmentgrenzen blijven behouden.")
            import pymupdf as fitz
            with fitz.open(source_path) as source_pdf:
                page_sizes = {
                    index + 1: (float(page.rect.width), float(page.rect.height))
                    for index, page in enumerate(source_pdf)
                }
            for fragment in saved_fragments:
                if "text" in fragment or not fragment.get("page_spans"):
                    continue
                segments = page_spans_to_segments(fragment["page_spans"], page_sizes)
                fragment["text"] = extract_region_text(source_path, segments)
            self.data.setdefault("exam_structures", {})[doc["id"]] = structure
            if self.data.get("exam_structure", {}).get("document_id") == doc["id"]:
                self.data["exam_structure"] = structure
            self.save_project()

        linked = {}
        for row in candidates:
            result = fragments_for_question(structure, int(row["number"]))
            fragment = result.get("question_fragment")
            if not fragment or not fragment.get("page_spans"):
                raise ValueError(
                    f"Vraag {row.get('number')}: het vraagfragment ontbreekt. "
                    "Leg eerst alle vraaggrenzen vast."
                )
            # The teacher has already visually checked and edited the saved
            # fragment set. Do not introduce a second confirmation/checkbox
            # round: the persisted geometry is the reviewed source of truth.
            linked[row.get("id")] = fragment

        for row in candidates:
            fragment = linked[row.get("id")]
            # This text was materialized from the exact selected fragment when
            # the teacher finished structure editing. Do not return to the PDF.
            snippet_text = str(fragment.get("text") or "")
            row["vraagtekst_voorstel"] = snippet_text
            if snippet_text.strip():
                row["vraagtype_controle"] = detect_question_type(snippet_text)
                row["vraagtype_status"] = "automatisch_bepaald_controle_nodig"
            else:
                row["vraagtype_controle"] = {
                    "type": "onbekend", "subtype": "geen_tekst_in_fragment",
                    "options": [], "option_labels": [], "options_complete": None,
                    "option_gaps": [], "duplicate_option_labels": [],
                    "confidence": 0.0, "status": "alleen_visueel_te_bepalen",
                }
                row["vraagtype_status"] = "visuele_controle_nodig"
            row["vraagtype_bepaald_na_fragmentcontrole"] = True
            row["vraagtype_fragment_id"] = fragment.get("id")
        records = self.data.setdefault("vraagrecords", [])
        subject = str(self.data.get("vak") or "Onbekend")
        exam_meta = doc.get("exam_metadata") or self.data.get("exam_metadata") or {}
        for row in candidates:
            fragment = linked[row.get("id")]
            question_links = fragments_for_question(structure, int(row["number"]))
            record = next((item for item in records
                if item.get("candidate_document_id") == doc.get("id")
                and int(item.get("number", -1) or -1) == int(row.get("number", -2) or -2)
                and int(item.get("source_page", -1) or -1) == int(row.get("page", -2) or -2)), None)
            if record is None:
                record = {
                    "schema": "exam-question-draft-v1",
                    "id": f"{subject.lower()}-{doc.get('id','')[:8]}-q{row.get('number')}",
                    "vak": subject, "exam": dict(exam_meta),
                    "number": int(row.get("number")), "source_page": int(row.get("page", 1)),
                    "candidate_document_id": doc.get("id"), "source_pdf": doc.get("opslagbestand"),
                    "question_fragment_id": fragment.get("id"), "context_fragment_ids": [],
                    "context_fragments": [], "question_text": "", "question_type": "onbekend",
                    "question_type_status": "controle_nodig", "status": "concept",
                    "approved_by_human": False,
                }
                records.append(record)
            record["question_fragment_id"] = fragment.get("id")
            record["question_text"] = str(fragment.get("text") or "")
            record["question_type"] = (row.get("vraagtype_controle") or {}).get("type", "onbekend")
            record["question_type_status"] = row.get("vraagtype_status", "controle_nodig")
            linked_contexts = question_links.get("context_fragments", [])
            record["context_fragment_ids"] = [item.get("id") for item in linked_contexts]
            record["context_fragments"] = [
                {"id": item.get("id"), "text": str(item.get("text") or ""),
                 "page_spans": item.get("page_spans", [])}
                for item in linked_contexts
            ]
        self.save_project()
        self._log(
            f"Vraagtypen bepaald en {len(candidates)} eenvoudige conceptrecords aangemaakt voor {doc.get('bestand')}."
        )
        return len(candidates)

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
        # The question type is intentionally determined only after the user
        # has saved the question snippet boundaries in the exam structure.
        source_doc = next((d for d in self.data.get("documenten", [])
                           if d.get("id") == row.get("document_id")), None)
        structure = (self.data.get("exam_structures", {}).get(row.get("document_id"))
                     or self.data.get("exam_structure"))
        linked = fragments_for_question(structure, int(row["number"]))
        question_fragment = linked.get("question_fragment")
        if not source_doc or not question_fragment or not question_fragment.get("page_spans"):
            messagebox.showwarning(
                "Vraaggrenzen eerst vastleggen",
                "Baken eerst in 'Structuur bewerken' het volledige vraagfragment af en sla de grenzen op. Daarna wordt de vraagsoort bepaald."
            )
            return
        try:
            # Use the cached text of the selected fragment; never rebuild a
            # question from neighboring regions of the original PDF.
            snippet_text = str(question_fragment.get("text") or "")
            row["vraagtekst_voorstel"] = snippet_text or row.get("vraagtekst_voorstel", "")
            row["vraagtype_controle"] = (
                detect_question_type(row["vraagtekst_voorstel"])
                if row["vraagtekst_voorstel"].strip() else {
                    "type": "onbekend", "subtype": "geen_tekst_in_fragment",
                    "options": [], "option_labels": [], "options_complete": None,
                    "option_gaps": [], "duplicate_option_labels": [],
                    "confidence": 0.0, "status": "alleen_visueel_te_bepalen",
                }
            )
            row["vraagtype_fragment_id"] = question_fragment.get("id")
            row["vraagtype_status"] = "controle_nodig"
            self.save_project()
        except Exception as exc:
            self._error("Vraagsoort bepalen na afbakening", exc)
            messagebox.showerror("Vraagsoort niet bepaald",
                f"De vraaggrenzen zijn opgeslagen, maar de vraagsoort kon nog niet worden bepaald.\\n\\n{exc}")
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
        self._log("Welkom. Beheer examens vanuit de examenbibliotheek; projecten en mappen worden automatisch geregeld.")
        self._log("Importeer meerdere PDF's tegelijk. Controleer de voorgestelde metadata en documentrollen één keer en start daarna direct met de inhoudelijke controle.")
        self.root.after(150, self._refresh_library)

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
        root = self.user_projects_root
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

    def import_year_set(self):
        """Import arbitrary exams from multiple years without manual folder creation."""
        files = filedialog.askopenfilenames(
            title="Selecteer alle examen-PDF's (meerdere jaren, havo/vwo en tijdvakken tegelijk)",
            filetypes=[("PDF-bestanden", "*.pdf")])
        if not files:
            return
        subject = simpledialog.askstring(
            "Vak kiezen", "Voor welk vak verwerk je deze examens?",
            initialvalue="Biologie", parent=self.root,
        )
        if subject is None:
            return
        subject = subject.strip() or "Onbekend"

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
        # Reserve the action footer before the expanding preview panes.  A
        # grid row below a Panedwindow can be pushed outside the visible window
        # when the child panes request their minimum sizes; pack the footer
        # first and use a fixed grid for its controls so the primary action
        # cannot disappear below the screen edge.
        shell = ttk.Frame(win, padding=0)
        shell.pack(fill="both", expand=True)
        footer = ttk.Frame(shell, padding=(12, 8))
        footer.pack(side="bottom", fill="x")
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=0)
        footer.columnconfigure(2, weight=0)
        status = ttk.Label(footer, text="", wraplength=760)
        status.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        intro = ttk.Label(shell, text=f"{len(documents)} unieke PDF's gevonden. Selecteer links een document; controleer het voorblad in het midden en pas de voorgestelde gegevens rechts direct aan.",
                          padding=12, wraplength=1100)
        intro.pack(side="top", fill="x")
        panes = ttk.Panedwindow(shell, orient="horizontal")
        panes.pack(side="top", fill="both", expand=True, padx=12, pady=(0, 8))
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
            ("year", "Jaar", 48), ("period", "Tv", 32), ("state", "Controle", 115)]:
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="w" if col in ("file", "role", "state") else "center")
        tree.pack(fill="both", expand=True)
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
                    subject_slug = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-") or "vak"
                    project_name = (
                        f"{level_key}-tijdvak-{period_key}"
                        if subject.lower() == "biologie"
                        else f"{subject_slug}-{level_key}-tijdvak-{period_key}"
                    )
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
                        "naam": project_name, "vak": subject,
                        "aangemaakt": now(), "bijgewerkt": now(),
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
                # Persist the batch reference in every project so the queue can
                # be restored after closing/restarting the desktop application.
                for project_dir in created:
                    project_file = project_dir / PROJECT_FILE
                    saved_data = json.loads(project_file.read_text(encoding="utf-8"))
                    saved_data["import_batch_manifest"] = manifest_path.name
                    temp_project_file = project_file.with_suffix(".json.tmp")
                    temp_project_file.write_text(
                        json.dumps(saved_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    temp_project_file.replace(project_file)
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
            self.import_batch_paths = list(created)
            self.import_batch_index = 0
            self.import_batch_manifest_path = manifest_path
            self._log(f"Examens geïmporteerd onder: {target_root}")
            for project in created:
                self._log(f"  Examen toegevoegd aan bibliotheek: {project.name}")
            self._log(f"Eerste examen wordt geopend in een afzonderlijk verwerkingsvenster: {created[0].name}")
            messagebox.showinfo("Examens geïmporteerd",
                f"{len(created)} examens zijn toegevoegd aan de examenbibliotheek.\n\n"
                f"Het eerste examen ({created[0].name}) wordt in een afzonderlijk verwerkingsvenster geopend. "
                "De overige examens blijven beschikbaar in de bibliotheek. De oorspronkelijke PDF's zijn ongewijzigd gekopieerd.",
                parent=self.root)
            self._refresh_library()
            self._launch_workspace(created[0])

        ttk.Button(footer, text="Annuleren", command=win.destroy).grid(row=0, column=2, sticky="e", padx=(8, 0))
        ttk.Button(footer, text="Opslaan en doorgaan naar examenverwerking  →",
                   command=confirm_import, style="Accent.TButton").grid(row=0, column=1, sticky="e")
        refresh_review()
        if documents:
            tree.selection_set("0")
            tree.focus("0")
            load_selected()
        self._log(f"Bulkimport voorbereid voor controle: {len(documents)} unieke PDF's. Nog niets opgeslagen of verwerkt. Doelmap: {self.examens_root}")

    def add_pdfs(self):
        if not self.data:
            messagebox.showinfo("Eerst een examen openen", "Kies eerst een examen uit de examenbibliotheek of importeer nieuwe examens.")
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
                    type_check={"type":"nog_niet_bepaald","options":[],"reason":"Vraagsoort wordt pas bepaald nadat de snippetgrenzen zijn vastgesteld."}
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
                        "vraagtekst_voorstel":proposal_text,"vraagtype_controle":{"type":"nog_niet_bepaald","options":[],"reason":"Vraagsoort wordt pas bepaald nadat de snippetgrenzen zijn vastgesteld."},
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
            if learned.get("document_support", 0):
                hint += (f" ({learned['document_support']} examens · "
                         f"{learned.get('confidence', 0):.0%} overeenstemming)")
            elif learned.get("legacy_records_ignored", 0):
                hint += " (oude keuzes tellen niet mee: examenbron onbekend)"
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
            visual = check.get("visual_detection", {})
            if visual.get("requires_visual_review"):
                option_lines.append(
                    "VISUELE CONTROLE NODIG: " + visual.get("status", "beeldmateriaal gevonden").replace("_", " ") +
                    f"\nBeeldelementen: {visual.get('visual_asset_count', 0)}" +
                    f"\nRasterafbeeldingen: {visual.get('raster_image_count', 0)}" +
                    f"\nNabije labels: {', '.join(visual.get('nearby_option_labels', [])) or 'niet herkend'}" +
                    "\nControleer in de PDF of dit contextmateriaal of antwoordalternatieven zijn.")
            fallback = ("Geen tekstopties herkend. Er is beeldmateriaal gevonden; controleer of de antwoordopties daarin staan."
                        if visual.get("requires_visual_review") else
                        "Geen antwoordopties herkend; controleer of dit een open vraag is.")
            set_box(options_box, "ANTWOORDOPTIES\n" + ("\n".join(option_lines) if option_lines else fallback))
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
        default_type="mcq" if detected in ("meerkeuze","mogelijk_visuele_meerkeuze") else "open"
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
        subject=self.data.get("vak","Biologie")
        win=tk.Toplevel(self.root)
        win.title(f"Vraagoverzicht · {subject}")
        win.geometry("980x620")
        ttk.Label(win,text=f"{len(records)} conceptvragen · vak: {subject}",padding=10).pack(anchor="w")
        cols=("number","page","type","status","context")
        tree=ttk.Treeview(win,columns=cols,show="headings")
        for col,label,width in [
            ("number","Vraag",70),("page","Pagina",80),("type","Vraagtype",130),
            ("status","Status",190),("context","Contexten",360)
        ]:
            tree.heading(col,text=label); tree.column(col,width=width,anchor="w")
        tree.pack(fill="both",expand=True,padx=10,pady=8)
        for i,record in enumerate(records):
            qtype=record.get("question_type") or record.get("exam",{}).get("questionType","onbekend")
            contexts=record.get("context_fragment_ids",[])
            tree.insert("","end",iid=str(i),values=(
                record.get("number"),record.get("source_page"),qtype,
                record.get("status","concept"),f"{len(contexts)} gekoppeld" if contexts else "geen"
            ))
        def open_selected():
            selection=tree.selection()
            if not selection:
                messagebox.showinfo("Selecteer vraag","Selecteer eerst een vraag.",parent=win)
                return
            record=records[int(selection[0])]
            if record.get("schema")=="exam-question-draft-v1":
                self._review_simple_question_draft(record,win)
            else:
                self.review_question_record(record,win)
            tree.set(selection[0],"type",record.get("question_type") or record.get("exam",{}).get("questionType","onbekend"))
            tree.set(selection[0],"status",record.get("status","concept"))
        buttons=ttk.Frame(win); buttons.pack(fill="x",padx=10,pady=(0,10))
        ttk.Button(buttons,text="Vraag bekijken / aanpassen",command=open_selected).pack(side="left")
        ttk.Button(buttons,text="Vernieuw",command=lambda:(win.destroy(),self.show_records())).pack(side="left",padx=8)

    def _review_consolidated_cv(self):
        """Show a traceable, question-ordered composite of the original CV and addenda."""
        records=sorted(self.data.get("vraagrecords",[]),key=lambda r:int(r.get("number",0) or 0))
        if not records:
            messagebox.showinfo("Geen vraagrecords","Er zijn nog geen vraagrecords om samen te voegen.",parent=self.root)
            return
        win=tk.Toplevel(self.root); win.title("Geconsolideerd correctievoorschrift · visuele controle")
        win.geometry("1120x860")
        outer=ttk.Frame(win,padding=10); outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="Samengevoegde weergave · bron-CV en officiële aanvullingen blijven afzonderlijk en ongewijzigd bewaard.",
                  wraplength=1080).pack(anchor="w",pady=(0,8))
        frame=ttk.Frame(outer); frame.pack(fill="both",expand=True)
        canvas=tk.Canvas(frame,background="#edf0f2")
        sy=ttk.Scrollbar(frame,orient="vertical",command=canvas.yview)
        canvas.configure(yscrollcommand=sy.set)
        canvas.pack(side="left",fill="both",expand=True); sy.pack(side="right",fill="y")
        inner=ttk.Frame(canvas,padding=8)
        window_id=canvas.create_window((0,0),window=inner,anchor="nw")
        inner.bind("<Configure>",lambda _e:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",lambda e:canvas.itemconfigure(window_id,width=e.width))
        photos=[]
        entries=[]
        missing=[]
        for record in records:
            number=record.get("number")
            block=ttk.LabelFrame(inner,text=f"Vraag {number} · {record.get('cv_amendment_change_type') or 'wijziging niet geclassificeerd'}",padding=8)
            block.pack(fill="x",pady=6)
            source_file=record.get("cv_source_region_file") or record.get("cv_snippet_file")
            source_doc=next((d for d in self.data.get("documenten",[])
                             if d.get("id")==record.get("cv_source_document_id")),None)
            if source_file and (self.project_dir/"snippets"/source_file).is_file():
                ttk.Label(block,text="Oorspronkelijk correctievoorschrift").pack(anchor="w")
                photo=tk.PhotoImage(file=str(self.project_dir/"snippets"/source_file))
                factor=max(1,(photo.width()+980-1)//980)
                if factor>1: photo=photo.subsample(factor,factor)
                ttk.Label(block,image=photo).pack(anchor="w"); photos.append(photo)
            else:
                ttk.Label(block,text="Oorspronkelijk CV-fragment ontbreekt.").pack(anchor="w")
                missing.append(f"vraag {number}: oorspronkelijk CV-fragment")
            amendments=record.get("cv_amendment_regions") or []
            for amendment in amendments:
                name=amendment.get("snippet_file")
                path=self.project_dir/"snippets"/str(name or "")
                ttk.Label(block,text="Officiële aanvulling").pack(anchor="w",pady=(6,0))
                if name and path.is_file():
                    photo=tk.PhotoImage(file=str(path))
                    factor=max(1,(photo.width()+980-1)//980)
                    if factor>1: photo=photo.subsample(factor,factor)
                    ttk.Label(block,image=photo).pack(anchor="w"); photos.append(photo)
                else:
                    ttk.Label(block,text="Aanvullingsfragment ontbreekt.").pack(anchor="w")
                    missing.append(f"vraag {number}: aanvullingsfragment")
            entries.append({
                "question_number":number,"change_type":record.get("cv_amendment_change_type"),
                "original_document_id":record.get("cv_source_document_id"),
                "original_region_file":source_file,
                "amendment_regions":[dict(x) for x in amendments],
            })
        win._consolidated_photos=photos
        if missing:
            ttk.Label(outer,text="Niet compleet: "+", ".join(missing),foreground="#9b4d00",
                      wraplength=1080).pack(anchor="w",pady=5)
        def confirm():
            if missing:
                messagebox.showwarning("Consolidatie onvolledig",
                    "Los eerst de ontbrekende bronfragmenten op voordat je de samengevoegde CV-weergave bevestigt.",parent=win)
                return
            self.data["consolidated_cv"]={
                "schema":"consolidated-cv-view-v1","status":"visueel_bevestigd",
                "reviewed_at":now(),"entries":entries,
                "sources_unchanged":True,
            }
            self.save_project()
            self._log("Geconsolideerde CV-weergave per vraag visueel bevestigd; bronbestanden zijn ongewijzigd.")
            win.destroy()
        ttk.Button(outer,text="Geconsolideerde CV-weergave bevestigen",
                   command=confirm,style="Accent.TButton").pack(anchor="e",pady=(8,0))

    def _review_simple_question_draft(self, record, parent):
        """Review question type, points, wording and options from the saved fragment."""
        win=tk.Toplevel(parent)
        win.title(f"Vraag {record.get('number')} · vraaganalyse")
        win.geometry("900x760")
        win.transient(parent)
        outer=ttk.Frame(win,padding=12); outer.pack(fill="both",expand=True)
        ttk.Label(outer,text=f"{record.get('vak','')} · vraag {record.get('number')} · pagina {record.get('source_page')}",
                  font=("Segoe UI",10,"bold")).pack(anchor="w")
        ttk.Label(outer,text="Controleer uitsluitend de inhoud die uit het reeds bevestigde vraagfragment volgt. De fragmentgrenzen worden hier niet opnieuw beoordeeld.",
                  wraplength=860).pack(anchor="w",pady=(4,10))
        top=ttk.Frame(outer); top.pack(fill="x")
        ttk.Label(top,text="Vraagtype").pack(side="left")
        type_var=tk.StringVar(value=record.get("question_type","onbekend"))
        ttk.Combobox(top,textvariable=type_var,
            values=["meerkeuze","juist_onjuist","wel_niet","ja_nee","hoger_lager",
                    "meer_minder","open","onbekend"],state="readonly",width=20).pack(side="left",padx=(6,18))
        ttk.Label(top,text="Maximaal aantal punten").pack(side="left")
        exam=record.setdefault("exam",{})
        points_var=tk.StringVar(value=str(exam.get("points","")))
        ttk.Entry(top,textvariable=points_var,width=8).pack(side="left",padx=6)
        ttk.Label(outer,text="Vraagtekst uit het gekozen vraagfragment").pack(anchor="w",pady=(12,3))
        text_box=tk.Text(outer,wrap="word",height=12)
        text_box.pack(fill="both",expand=True)
        text_box.insert("1.0",record.get("question_text",""))
        ttk.Label(outer,text="Antwoordopties (één per regel; bij meerkeuze bijvoorbeeld A. ...).").pack(anchor="w",pady=(8,3))
        options_box=tk.Text(outer,wrap="word",height=6)
        options_box.pack(fill="x")
        options_box.insert("1.0","\n".join(
            f"{item.get('key','')}. {item.get('text','')}".strip(". ")
            for item in (record.get("options") or [])
        ))
        correct_var=tk.StringVar(value=str(record.get("correct","")))
        keyrow=ttk.Frame(outer); keyrow.pack(fill="x",pady=(5,0))
        ttk.Label(keyrow,text="Correcte sleutel (indien van toepassing)").pack(side="left")
        ttk.Entry(keyrow,textvariable=correct_var,width=16).pack(side="left",padx=8)
        answer_reviewed_var=tk.BooleanVar(value=(record.get("answer_review") or {}).get("status")=="visueel_bevestigd")
        ttk.Checkbutton(outer,text="Correct antwoord (ook ja/nee, waar/onwaar, hoger/lager enz.) vergeleken met het officiële CV",
            variable=answer_reviewed_var).pack(anchor="w",pady=(6,0))
        amendment_row=ttk.Frame(outer); amendment_row.pack(fill="x",pady=(6,0))
        ttk.Label(amendment_row,text="Wijziging door CV-aanvulling").pack(side="left")
        amendment_change_var=tk.StringVar(value=record.get("cv_amendment_change_type",""))
        ttk.Combobox(amendment_row,textvariable=amendment_change_var,
            values=["niet van toepassing","toevoeging","wijziging","vervanging","intrekking","ongewijzigd"],
            state="readonly",width=24).pack(side="left",padx=8)
        contexts=record.get("context_fragments",[])
        context_text="\n\n".join(
            f"Context {index+1}: {item.get('text') or '[geen uitleesbare tekst; fragment blijft visueel gekoppeld]'}"
            for index,item in enumerate(contexts)
        )
        ttk.Label(outer,text=f"Gekoppelde contextfragmenten: {len(contexts)}",
                  wraplength=860).pack(anchor="w",pady=(8,2))
        if context_text:
            context_box=tk.Text(outer,wrap="word",height=5)
            context_box.pack(fill="x")
            context_box.insert("1.0",context_text)
            context_box.configure(state="disabled")
        def save():
            raw_points=points_var.get().strip().replace(",",".")
            if raw_points:
                try:
                    points=float(raw_points)
                    if points<0 or points>100:
                        raise ValueError
                except ValueError:
                    messagebox.showerror("Ongeldig puntenaantal","Vul een getal tussen 0 en 100 in.",parent=win)
                    return
            else:
                points=None
            options=[]
            for line in options_box.get("1.0","end").splitlines():
                line=line.strip()
                if not line:
                    continue
                match=re.match(r"^([A-H])\s*[.)-]\s*(.*)$",line,re.I)
                if match:
                    options.append({"key":match.group(1).upper(),"text":match.group(2).strip()})
                else:
                    options.append({"key":str(len(options)+1),"text":line})
            record["question_text"]=text_box.get("1.0","end").strip()
            record["question_type"]=type_var.get()
            record["question_type_status"]="handmatig_gecontroleerd"
            record["options"]=options
            record["correct"]=correct_var.get().strip()
            if answer_reviewed_var.get():
                if not correct_var.get().strip():
                    messagebox.showwarning("Antwoord ontbreekt","Vul eerst het gecontroleerde antwoord of de antwoordsleutel in.",parent=win)
                    return
                record["answer_review"]={"status":"visueel_bevestigd","answer":correct_var.get().strip(),
                                         "reviewed_at":now()}
            else:
                record.pop("answer_review",None)
            record["cv_amendment_change_type"]=amendment_change_var.get()
            record.setdefault("exam",{})["points"]=points
            record["status"]="concept"
            self.save_project()
            self._log(f"Vraag {record.get('number')}: vraagtype, punten en antwoordopties gecontroleerd.")
            win.destroy()
        region_bar=ttk.LabelFrame(outer,text="Gekoppelde documentfragmenten",padding=8)
        region_bar.pack(fill="x",pady=(10,0))
        def open_region(role):
            docs=[d for d in self.data.get("documenten",[]) if d.get("type_voorstel")==role]
            if not docs:
                messagebox.showinfo("Document ontbreekt",
                    f"Er is nog geen document van het type '{role}' toegevoegd. Voeg eerst de juiste PDF toe.",parent=win)
                return
            def launch(doc, chooser=None):
                if chooser is not None:
                    chooser.destroy()
                def saved(name, fragment):
                    if role=="correctievoorschrift":
                        record["cv_source_document_id"]=doc["id"]
                        record["cv_source_region"]=fragment
                        record["cv_source_region_file"]=name
                    elif role=="aanvulling":
                        record.setdefault("cv_amendment_regions",[])
                        record["cv_amendment_regions"]=[x for x in record["cv_amendment_regions"]
                            if x.get("document_id")!=doc["id"]]
                        record["cv_amendment_regions"].append({
                            "document_id":doc["id"],"fragment":fragment,"snippet_file":name,
                            "source_pdf":doc.get("opslagbestand"),"source_sha256":doc.get("sha256")})
                    else:
                        record.setdefault("uitwerkbijlagen",[])
                        if doc.get("opslagbestand") not in record["uitwerkbijlagen"]:
                            record["uitwerkbijlagen"].append(doc.get("opslagbestand"))
                        record.setdefault("uitwerkbijlage_region_refs",[])
                        record["uitwerkbijlage_region_refs"]=[x for x in record["uitwerkbijlage_region_refs"]
                            if x.get("document_id")!=doc["id"]]
                        record["uitwerkbijlage_region_refs"].append({
                            "document_id":doc["id"],"question_number":int(record["number"]),
                            "snippet_file":name,"source_sha256":doc.get("sha256")})
                    self.save_project()
                self.open_cv_region_editor(record,doc,saved)
            if len(docs)==1:
                launch(docs[0])
                return
            chooser=tk.Toplevel(win); chooser.title("Kies brondocument"); chooser.transient(win)
            ttk.Label(chooser,text="Selecteer het document waarin je dit vraagfragment wilt afbakenen.",padding=8).pack(anchor="w")
            listing=tk.Listbox(chooser,width=76,height=min(8,len(docs)))
            listing.pack(fill="both",expand=True,padx=8,pady=6)
            for doc in docs: listing.insert("end",doc.get("bestand",""))
            def selected():
                pick=listing.curselection()
                if pick: launch(docs[pick[0]],chooser)
            ttk.Button(chooser,text="Open fragmenteditor",command=selected).pack(pady=(0,8))
        ttk.Button(region_bar,text="Correctievoorschrift afbakenen",
                   command=lambda:open_region("correctievoorschrift")).pack(side="left",padx=(0,6))
        ttk.Button(region_bar,text="Uitwerkbijlage afbakenen",
                   command=lambda:open_region("uitwerkbijlage")).pack(side="left",padx=6)
        ttk.Button(region_bar,text="CV-aanvulling afbakenen",
                   command=lambda:open_region("aanvulling")).pack(side="left",padx=6)
        ttk.Button(region_bar,text="Geconsolideerde CV bekijken",
                   command=self._review_consolidated_cv).pack(side="left",padx=6)
        buttons=ttk.Frame(outer); buttons.pack(fill="x",pady=(10,0))
        ttk.Button(buttons,text="Analyse bevestigen en opslaan",command=save,style="Accent.TButton").pack(side="right")
        ttk.Button(buttons,text="Sluiten",command=win.destroy).pack(side="right",padx=8)

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
            messagebox.showinfo("Geen vraagrecords","Rond eerst de fragmentselectie af zodat conceptvragen worden aangemaakt."); return
        destination=filedialog.askdirectory(title="Kies een nieuwe, lege exportmap")
        if not destination: return
        try:
            export_dir=Path(destination)
            subject=str(self.data.get("vak","Biologie")).strip()
            draft_records=[item for item in records if item.get("schema")=="exam-question-draft-v1"]
            if subject.lower() != "biologie" or draft_records:
                if any(export_dir.iterdir()):
                    raise ValueError("Kies een lege exportmap. Bestaande bestanden worden niet overschreven.")
                source_dir=export_dir/"bronnen"
                source_dir.mkdir(parents=True,exist_ok=True)
                for document in self.data.get("documenten",[]):
                    source=self.project_dir/"bronnen"/document.get("opslagbestand","")
                    if source.is_file():
                        shutil.copy2(source,source_dir/source.name)
                payload={
                    "schema":"exam-question-drafts-v1",
                    "vak":subject,
                    "project":self.data.get("naam",self.project_dir.name),
                    "exam_metadata":self.data.get("exam_metadata",{}),
                    "documenten":[
                        {key:doc.get(key) for key in ("bestand","opslagbestand","type_voorstel","exam_metadata","sha256")}
                        for doc in self.data.get("documenten",[])
                    ],
                    "exam_structures":self.data.get("exam_structures",{}),
                    "vraagrecords":records,
                }
                target=export_dir/"examenverwerker-conceptvragen.json"
                temp=target.with_suffix(".json.tmp")
                temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
                temp.replace(target)
                self._log(f"Conceptvragen geëxporteerd voor vak {subject}: {target}")
                messagebox.showinfo("Conceptexport klaar",
                    f"Conceptvragen en bron-PDF's zijn geëxporteerd naar:\n{export_dir}\n\nDit is een overdraagbaar conceptpakket, geen publicatiepakket.",parent=self.root)
                return
            result=export_approved_records(records,self.project_dir,export_dir)
            if not result.get("ok"):
                errors=result.get("errors",[])
                detail="\n".join(f"• {x.get('id','')} · {x.get('error')}" for x in errors[:20])
                if len(errors)>20: detail+=f"\n… en {len(errors)-20} overige blokkades."
                messagebox.showwarning("Export geblokkeerd",f"Er is niets gepubliceerd. Los eerst deze controles op:\n\n{detail}",parent=self.root)
                self._log(f"Export geblokkeerd: {len(errors)} validatiefouten.")
                return
            self.data["export_status"] = {
                "fingerprint": exam_export_fingerprint(self.data),
                "export_dir": str(result["export_dir"]),
                "aangemaakt": now(),
                "mcq": result["mcq"],
                "open": result["open"],
            }
            self.save_project()
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
        if page_count < 2:
            messagebox.showwarning("Geen opgavenpagina's", "Pagina 1 is het voorblad en wordt niet in de fragmenteditor opgenomen. Er zijn geen volgende pagina's.")
            return
        preview_path = self.project_dir / "analyse" / f"opgaven-preview-{doc['id']}-{doc['sha256'][:12]}.pdf"
        preview_info = prepare_exam_preview_pdf(source, preview_path)
        preview_by_original = {int(item["original_page"]): item for item in preview_info["page_map"]}
        preview_heights = {int(item["original_page"]): float(item["preview_height"])
                           for item in preview_info["page_map"]}
        structures = self.data.setdefault("exam_structures", {})
        existing = structures.get(doc["id"])
        if existing is None and self.data.get("exam_structure", {}).get("document_id") == doc["id"]:
            existing = self.data.get("exam_structure")
        if existing and existing.get("document_id") == doc["id"] and existing.get("source_sha256") == doc["sha256"]:
            fragments = normalize_fragments(existing.get("fragments", []))
            # An existing saved structure is the user's working result, not a
            # fresh automatic proposal. Preserve it as reviewed on reopening;
            # do not send the user through a redundant checkbox/approval round.
            for fragment in fragments:
                if fragment.get("status") == "automatisch_voorstel_nog_te_controleren":
                    fragment["status"] = "handmatig_gecontroleerd"
                    fragment["reviewed_by_human"] = True
                    fragment["reviewed_at"] = fragment.get("reviewed_at") or now()
        else:
            fragments = []
        # Seed the editor with transparent, editable proposals derived from the
        # confirmed question starts. Page 1 is never treated as context; only
        # content on page 2 onward before question 1 can become the introduction.
        # Nothing is auto-approved.
        generated_proposals = not bool(fragments)
        if generated_proposals:
            ordered = sorted(
                [x for x in candidates if x.get("human_decision") is True],
                key=lambda x: (int(x.get("page", 1)), float((x.get("bbox") or [0, 0])[1]))
            )
            starts = []
            for item in ordered:
                page_no = int(item.get("page", 1))
                bbox = item.get("bbox") or [0, 0, 0, 0]
                height = page_sizes.get(page_no, (1.0, 1.0))[1]
                y = max(0.0, min(1.0, float(bbox[1]) / max(1.0, height)))
                starts.append((page_no, y, int(item["number"])))
            if starts:
                first_page, first_y, _ = starts[0]
                # Exclude page 1 unconditionally. Build an intro from meaningful
                # content on pages 2..first question, including a partial final page.
                intro_spans = []
                for intro_page in range(2, first_page + 1):
                    page_data = next((p for p in analysis.get("pages", [])
                                      if int(p.get("page", 0)) == intro_page), {})
                    page_height = page_sizes[intro_page][1]
                    limit = first_y if intro_page == first_page else 1.0
                    if limit <= 0.005:
                        continue
                    has_content = any(
                        len(block.get("bbox") or []) == 4
                        and float(block["bbox"][1]) < limit * page_height
                        for block in page_data.get("blocks", [])
                    ) or any(
                        len(asset.get("bbox") or []) == 4
                        and float(asset["bbox"][1]) < limit * page_height
                        for asset in page_data.get("visual_assets", [])
                    )
                    if has_content:
                        intro_spans.append({"page": intro_page, "top": 0.0,
                                            "bottom": round(limit, 6)})
                if intro_spans:
                    fragments.append({
                        "id": f"voorstel-intro-{doc['id'][:8]}",
                        "type": "context",
                        "context_role": "introductie",
                        "page_spans": intro_spans,
                        "question_numbers": question_numbers[:],
                        "status": "automatisch_voorstel_nog_te_controleren",
                        "confidence": 0.72,
                        "evidence": {
                            "reason": "Inleidende examencontext vóór de eerste bevestigde vraag; pagina 1 is uitgesloten.",
                            "source": "inhoud_voor_vraag_1",
                        },
                    })
                for index, (start_page, start_y, number) in enumerate(starts):
                    next_candidate = ordered[index + 1] if index + 1 < len(ordered) else None
                    end_page, end_y, boundary_reason = question_fragment_boundary(
                        analysis, ordered[index], next_candidate
                    )
                    spans = []
                    for page_no in range(start_page, min(page_count, end_page) + 1):
                        page_height = page_sizes[page_no][1]
                        page_top = start_y if page_no == start_page else 0.0
                        page_bottom = (end_y / page_height) if page_no == end_page else 1.0
                        if page_bottom - page_top >= 0.005:
                            spans.append({"page": page_no, "top": round(page_top, 6),
                                          "bottom": round(min(1.0, page_bottom), 6)})
                    if spans:
                        fragments.append({
                            "id": f"voorstel-vraag-{doc['id'][:6]}-{number}",
                            "type": "vraag",
                            "page_spans": spans,
                            "question_numbers": [number],
                            "status": "automatisch_voorstel_nog_te_controleren",
                            "confidence": float(ordered[index].get("confidence", 0.0) or 0.0),
                            "evidence": {
                                "reason": f"Vraagstart tot eerste {boundary_reason.replace('_', ' ')}",
                                "source": "vraagstart_witregel_kader",
                            },
                        })
                # Supplement broad question bands with focused, evidence-backed
                # context proposals around actual PDF figures and their captions.
                fragments.extend(propose_context_fragments(analysis, candidates))
        from structure import sort_fragments_reading_order, trim_question_bands_for_contexts
        if generated_proposals:
            fragments = trim_question_bands_for_contexts(fragments)
        fragments = sort_fragments_reading_order(fragments)
        # Compare saves against the loaded/proposed source structure before
        # applying footer cuts, so changed boundaries invalidate old approvals.
        original_structure_signature = json.dumps(fragments, ensure_ascii=False, sort_keys=True)
        # Keep fragment coordinates in the untouched source-PDF coordinate
        # system, but stop their visible range at the cleaned page boundary.
        for fragment in fragments:
            cleaned_spans = []
            for span in fragment.get("page_spans", []):
                original_page = int(span.get("page", 0))
                if original_page in preview_heights:
                    page_height = page_sizes[original_page][1]
                    span = dict(span)
                    span["bottom"] = min(float(span["bottom"]),
                                         preview_heights[original_page] / page_height)
                    if span["bottom"] - float(span["top"]) >= 0.005:
                        cleaned_spans.append(span)
                else:
                    cleaned_spans.append(dict(span))
            fragment["page_spans"] = cleaned_spans
        fragments = sort_fragments_reading_order(fragments)
        # Reuse the central workbench rather than opening a separate window.
        self._workspace_container.forget(self._workspace_left)
        self._workspace_container.forget(self._workspace_right)
        win = ttk.Frame(self._workspace_container, style="App.TFrame", padding=8)
        self._workspace_container.add(win, weight=1)
        header = ttk.Frame(win, padding=(12, 8)); header.pack(fill="x")
        ttk.Label(header, text="Eerst de vraagnummering bevestigd; nu context- en vraagfragmenten afbakenen.",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        trimmed_pages = sum(1 for item in preview_info["page_map"] if item.get("footer_detected"))
        ttk.Label(header, text=f"Voorbewerking: voorblad verwijderd; footer/onderliggende witruimte automatisch afgesneden op {trimmed_pages} van {len(preview_info['page_map'])} pagina's. De originele PDF blijft ongewijzigd.",
                  wraplength=1180).pack(anchor="w", pady=(3, 0))
        uncertain_pages = [
            item for item in preview_info["page_map"]
            if item.get("footer_review_required")
            or (
                not item.get("footer_detected")
                and float(item["preview_height"]) >= float(item["original_height"]) * 0.95
            )
        ]
        if uncertain_pages:
            ttk.Label(
                header,
                text="Enkele pagina's vragen nog een visuele controle: een footerindicatie overlapt mogelijk met inhoud of kon niet veilig worden vastgesteld. De inhoud is behouden.",
                foreground="#9b4d00", wraplength=1180,
            ).pack(anchor="w", pady=(2, 0))
        ttk.Label(
            header,
            text="De opgeschoonde opgavenpagina's staan hieronder achter elkaar als één doorlopende PDF. "
                 "Selecteer links een fragment en sleep de twee grenslijnen op de lange pagina. "
                 "Bij een selectie over meerdere pagina's kun je een grenslijn vasthouden en rustig naar de boven- of onderrand bewegen om mee te scrollen. "
                 "Met 'Fragmentvoorbeeld' controleer je de samengestelde uitsnede.",
            wraplength=1180,
        ).pack(anchor="w", pady=(3, 0))
        body = ttk.Frame(win, padding=8); body.pack(fill="both", expand=True)
        left = ttk.Frame(body, width=245); left.pack(side="left", fill="y", padx=(0, 10))
        right = ttk.Frame(body); right.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="Fragmenttype").pack(anchor="w")
        fragment_type_ids = {"Context": "context", "Vraag": "vraag"}
        fragment_type_labels = {value: key for key, value in fragment_type_ids.items()}
        type_var = tk.StringVar(value="Context")
        type_box = ttk.Combobox(left, textvariable=type_var, state="readonly",
            values=list(fragment_type_ids), width=25)
        type_box.pack(fill="x", pady=(2, 4))
        ttk.Label(left, text="Het voorblad/instructieblad wordt niet als context gebruikt. Context: koppel aan één of meer vragen. Vraag: precies één vraagblok.",
                  wraplength=230, justify="left").pack(anchor="w", pady=(0, 8))
        ttk.Label(left, text="Koppelen aan vraagnummer(s)").pack(anchor="w")
        qlist = tk.Listbox(left, selectmode="extended", exportselection=False, height=12)
        qlist.pack(fill="x", pady=(2, 8))
        for number in question_numbers: qlist.insert("end", f"Vraag {number}")
        # Keep the question links when switching the fragment type.
        # The user may edit both fields independently; changes are saved below.
        ttk.Label(left, text="Bestaande fragmenten").pack(anchor="w", pady=(4, 2))
        fragment_tree = ttk.Treeview(left, columns=("type", "links", "confidence"), show="tree headings", height=12)
        fragment_tree.heading("#0", text="Fragment")
        fragment_tree.column("#0", width=68)
        fragment_tree.heading("type", text="Type"); fragment_tree.column("type", width=82)
        fragment_tree.heading("links", text="Vragen"); fragment_tree.column("links", width=55)
        fragment_tree.heading("confidence", text="Zeker"); fragment_tree.column("confidence", width=48, anchor="center")
        fragment_tree.pack(fill="both", expand=True)
        fragment_info = ttk.Label(left, text="Selecteer een fragment voor de herkenningsreden en het bewijs.",
                                  wraplength=230, justify="left")
        fragment_info.pack(fill="x", pady=(5, 2))
        ttk.Label(left, text="Tip: selecteer een aaneengesloten gebied op de doorlopende PDF. Een fragment mag meerdere pagina's beslaan.",
                  wraplength=230).pack(anchor="w", pady=8)
        nav = ttk.Frame(right); nav.pack(fill="x", pady=(0, 6))
        ttk.Label(nav, text="Zoom").pack(side="left", padx=(0, 5))
        ttk.Button(nav, text="−", width=3, command=lambda: set_preview_zoom(0.85)).pack(side="left")
        ttk.Button(nav, text="100%", width=6, command=lambda: set_preview_zoom(1.0, absolute=True)).pack(side="left", padx=3)
        ttk.Button(nav, text="+", width=3, command=lambda: set_preview_zoom(1.18)).pack(side="left")
        ttk.Button(nav, text="Passend", command=lambda: fit_preview_width()).pack(side="left", padx=(5, 12))
        ttk.Label(nav, text="Ctrl + muiswiel: in-/uitzoomen", foreground="#63717B").pack(side="left")
        page_var = tk.IntVar(value=2)
        displayed_page = 2
        frame = ttk.Frame(right); frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(frame, background="white", highlightthickness=0)
        sy = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        sx = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.pack(side="right", fill="y"); sx.pack(side="bottom", fill="x"); canvas.pack(side="left", fill="both", expand=True)
        canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))
        canvas.bind("<Button-4>", lambda _event: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda _event: canvas.yview_scroll(1, "units"))
        canvas.bind("<Control-MouseWheel>", lambda event: (set_preview_zoom(1.12 if event.delta > 0 else 0.89), "break")[1])
        actions = ttk.Frame(right); actions.pack(fill="x", pady=(8, 0))
        stitched_path = self.project_dir / "analyse" / f"opgaven-doorlopend-{doc['id']}-{doc['sha256'][:12]}.png"
        preview_zoom = 1.0
        stitched_info = render_stitched_preview(
            preview_path, stitched_path, preview_info["page_map"], scale=1.05
        )
        stitched_scale = float(stitched_info["scale"])
        page_layout = stitched_info["layout"]
        page_layout_by_original = {
            int(item["original_page"]): item for item in page_layout
        }
        photo = None
        document_photo = None
        snippet_mode = False
        snippet_layout = []
        snippet_scale = 1.05
        drag_handle = None
        page_image_width = 1
        page_image_height = 1
        overlay_items = []
        selection_start = (2, 0.0)
        selection_end = (
            2, min(1.0, preview_heights[2] / page_sizes[2][1])
        )
        selection_dirty = False
        save_status = tk.StringVar(value="Wijzigingen worden automatisch opgeslagen.")

        def selected_links():
            return [question_numbers[i] for i in qlist.curselection()]

        def selected_fragment():
            sel = fragment_tree.selection()
            return fragments[int(sel[0])] if sel else None

        def position_for(page_no, normalized_y):
            layout = page_layout_by_original[int(page_no)]
            original_height = float(page_sizes[int(page_no)][1])
            return float(layout["y0"]) + float(normalized_y) * original_height * stitched_scale

        def point_for_y(global_y):
            y = max(0.0, min(float(page_image_height), float(global_y)))
            previous = None
            for layout in page_layout:
                page_no = int(layout["original_page"])
                y0, y1 = float(layout["y0"]), float(layout["y1"])
                if y < y0:
                    if previous is None:
                        return page_no, 0.0
                    previous_end = float(previous["y1"])
                    if y - previous_end <= y0 - y:
                        previous_page = int(previous["original_page"])
                        return previous_page, min(
                            1.0,
                            float(preview_heights[previous_page]) /
                            float(page_sizes[previous_page][1]),
                        )
                    return page_no, 0.0
                if y <= y1:
                    local_y = max(0.0, min(y1 - y0, y - y0))
                    normalized = local_y / (
                        float(page_sizes[page_no][1]) * stitched_scale
                    )
                    maximum = float(preview_heights[page_no]) / float(page_sizes[page_no][1])
                    return page_no, max(0.0, min(maximum, normalized))
                previous = layout
            last_page = int(page_layout[-1]["original_page"])
            return last_page, min(
                1.0,
                float(preview_heights[last_page]) /
                float(page_sizes[last_page][1]),
            )

        def selection_to_spans():
            start_point, end_point = selection_start, selection_end
            start_y = position_for(*start_point)
            end_y = position_for(*end_point)
            if start_y > end_y:
                start_point, end_point = end_point, start_point
                start_y, end_y = end_y, start_y
            if end_y - start_y < 4:
                raise ValueError("De selectie is te klein. Vergroot de afstand tussen de grenslijnen.")
            first_page, first_top = start_point
            last_page, last_bottom = end_point
            spans = []
            for page_no in range(int(first_page), int(last_page) + 1):
                if page_no not in page_layout_by_original:
                    continue
                top = float(first_top) if page_no == int(first_page) else 0.0
                bottom = (
                    float(last_bottom) if page_no == int(last_page)
                    else float(preview_heights[page_no]) / float(page_sizes[page_no][1])
                )
                if bottom - top >= 0.005:
                    spans.append(make_page_span(page_no, top, bottom))
            if not spans:
                raise ValueError("De selectie bevat geen zichtbaar deel van een opgavenpagina.")
            return spans

        def redraw_guides():
            nonlocal overlay_items
            for item in overlay_items:
                canvas.delete(item)
            overlay_items = []
            if photo is None:
                return
            if snippet_mode:
                for layout in snippet_layout:
                    span = layout["span"]
                    top_px = layout["y0"] + (
                        float(span["top"]) * layout["page_height"] - layout["clip_top"]
                    ) * snippet_scale
                    bottom_px = layout["y0"] + (
                        float(span["bottom"]) * layout["page_height"] - layout["clip_top"]
                    ) * snippet_scale
                    overlay_items.append(canvas.create_rectangle(
                        0, layout["y0"], page_image_width, top_px,
                        fill="#c8c8c8", stipple="gray50", outline="",
                    ))
                    overlay_items.append(canvas.create_rectangle(
                        0, bottom_px, page_image_width, layout["y1"],
                        fill="#c8c8c8", stipple="gray50", outline="",
                    ))
                    overlay_items.append(canvas.create_line(
                        0, top_px, page_image_width, top_px, fill="black", width=2,
                    ))
                    overlay_items.append(canvas.create_line(
                        0, bottom_px, page_image_width, bottom_px, fill="black", width=2,
                    ))
            else:
                start_px = position_for(*selection_start)
                end_px = position_for(*selection_end)
                if start_px > end_px:
                    start_px, end_px = end_px, start_px
                for layout in page_layout:
                    page_top, page_bottom = float(layout["y0"]), float(layout["y1"])
                    selected_top = max(page_top, start_px)
                    selected_bottom = min(page_bottom, end_px)
                    if selected_top > page_top:
                        overlay_items.append(canvas.create_rectangle(
                            0, page_top, page_image_width, min(selected_top, page_bottom),
                            fill="#c8c8c8", stipple="gray50", outline="",
                        ))
                    if selected_bottom < page_bottom:
                        overlay_items.append(canvas.create_rectangle(
                            0, max(selected_bottom, page_top), page_image_width, page_bottom,
                            fill="#c8c8c8", stipple="gray50", outline="",
                        ))
                    if page_top <= start_px <= page_bottom:
                        overlay_items.append(canvas.create_line(
                            0, start_px, page_image_width, start_px,
                            fill="black", width=2,
                        ))
                    if page_top <= end_px <= page_bottom:
                        overlay_items.append(canvas.create_line(
                            0, end_px, page_image_width, end_px,
                            fill="black", width=2,
                        ))
            canvas.configure(scrollregion=(0, 0, page_image_width, page_image_height))

        def show_document(scroll_to_page=None):
            nonlocal photo, document_photo, page_image_width, page_image_height, displayed_page, snippet_mode, overlay_items
            current_scroll_y = canvas.canvasy(0) if photo is not None else 0.0
            snippet_mode = False
            if document_photo is None:
                document_photo = tk.PhotoImage(file=str(stitched_path))
            photo = document_photo
            page_image_width, page_image_height = photo.width(), photo.height()
            canvas.delete("all")
            canvas.create_image(0, 0, image=photo, anchor="nw")
            canvas.image = photo
            overlay_items = []
            canvas.configure(scrollregion=(0, 0, page_image_width, page_image_height))
            if scroll_to_page is not None:
                displayed_page = max(2, min(page_count, int(scroll_to_page)))
                page_var.set(displayed_page)
            else:
                displayed_page = max(2, min(page_count, int(page_var.get())))
            redraw_guides()
            if scroll_to_page is not None:
                layout = page_layout_by_original.get(displayed_page)
                if layout:
                    target_y = float(layout["y0"])
                else:
                    target_y = 0.0
            else:
                target_y = current_scroll_y
            # Tk's yview_moveto fraction is measured against the full
            # scrollregion. Keep the same document coordinate after a redraw.
            canvas.yview_moveto(
                max(0.0, min(1.0, target_y / max(1.0, page_image_height)))
            )

        def show_page():
            show_document(page_var.get())

        def set_preview_zoom(value, absolute=False):
            nonlocal preview_zoom, stitched_scale, page_layout, page_layout_by_original
            nonlocal photo, document_photo, page_image_width, page_image_height
            if snippet_mode:
                show_document(displayed_page)
            target_zoom = max(0.55, min(2.25, float(value) if absolute else preview_zoom * float(value)))
            if abs(target_zoom - preview_zoom) < 0.001:
                return
            # Keep the selected boundaries in PDF coordinates; only the visual
            # coordinate system changes. Re-rendering avoids blurry enlargement.
            old_zoom = preview_zoom
            preview_zoom = target_zoom
            new_scale = 1.05 * preview_zoom
            try:
                zoom_path = self.project_dir / "analyse" / f"opgaven-doorlopend-{doc['id']}-{doc['sha256'][:12]}-z{preview_zoom:.2f}.png"
                zoom_info = render_stitched_preview(
                    preview_path, zoom_path, preview_info["page_map"], scale=new_scale
                )
                ratio = float(zoom_info["scale"]) / max(0.0001, stitched_scale)
                stitched_scale = float(zoom_info["scale"])
                page_layout = zoom_info["layout"]
                page_layout_by_original = {int(item["original_page"]): item for item in page_layout}
                stitched_path = zoom_path
                document_photo = tk.PhotoImage(file=str(zoom_path))
                photo = document_photo
                page_image_width, page_image_height = photo.width(), photo.height()
                show_document(displayed_page)
            except Exception as exc:
                preview_zoom = old_zoom
                self._log(f"Inzoomen op doorlopende PDF mislukt: {exc}")
                messagebox.showerror("Zoom niet beschikbaar", str(exc), parent=win)

        def fit_preview_width():
            try:
                if document_photo is None:
                    return
                available = max(300, canvas.winfo_width() - 24)
                factor = available / max(1, document_photo.width())
                set_preview_zoom(preview_zoom * factor, absolute=True)
            except Exception as exc:
                self._log(f"Passend zoomen mislukt: {exc}")

        def show_fragment():
            nonlocal photo, page_image_width, page_image_height, displayed_page, snippet_mode, snippet_layout
            frag = selected_fragment()
            if not frag or not frag.get("page_spans"):
                show_document(displayed_page)
                return
            snippet_mode = True
            spans = sorted(
                [item for item in frag["page_spans"]
                 if int(item.get("page", 0)) in preview_by_original],
                key=lambda item: int(item["page"]),
            )
            if not spans:
                show_document(displayed_page)
                return
            displayed_page = int(spans[0]["page"])
            page_var.set(displayed_page)
            segments = []
            snippet_layout = []
            cursor = 0.0
            for span in spans:
                original_page = int(span["page"])
                page_info = preview_by_original.get(original_page)
                if not page_info:
                    continue
                page_height = page_sizes[original_page][1]
                preview_height = preview_heights[original_page]
                # Snijd pas nadat de gebruiker de fragmentgrenzen heeft bepaald:
                # zoek binnen die grenzen de eerste en laatste rij met niet-witte pixels.
                clip_top = max(0.0, float(span["top"]) * page_height)
                clip_bottom = min(preview_height, float(span["bottom"]) * page_height)
                try:
                    from PIL import Image
                    pixel_path = self.project_dir / "analyse" / f"snippet-trim-p{original_page}.png"
                    render_page(preview_path, int(page_info["preview_page"]), pixel_path, scale=1.0)
                    with Image.open(pixel_path) as page_image:
                        gray = page_image.convert("L")
                        px_per_point = gray.height / max(1.0, float(page_height))
                        y0 = max(0, min(gray.height - 1, int(clip_top * px_per_point)))
                        y1 = max(y0 + 1, min(gray.height, int(clip_bottom * px_per_point)))
                        ink_bbox = gray.crop((0, y0, gray.width, y1)).point(
                            lambda value: 255 if value < 247 else 0
                        ).getbbox()
                        if ink_bbox:
                            clip_top = max(0.0, ((y0 + ink_bbox[1]) / px_per_point) - 1.5)
                            clip_bottom = min(preview_height, ((y0 + ink_bbox[3]) / px_per_point) + 1.5)
                except Exception as crop_error:
                    self._log(f"Witruimtedetectie voor fragment op pagina {original_page} overgeslagen: {crop_error}")
                if clip_bottom - clip_top < 4:
                    continue
                segments.append({
                    "page": int(page_info["preview_page"]),
                    "bbox": [0.0, clip_top, float(page_info["width"]), clip_bottom],
                })
                segment_height = (clip_bottom - clip_top) * snippet_scale
                snippet_layout.append({
                    "span": span, "page_height": page_height,
                    "clip_top": clip_top, "clip_bottom": clip_bottom,
                    "y0": cursor, "y1": cursor + segment_height,
                })
                cursor += segment_height + 12.0 * snippet_scale
            if not segments:
                show_document(displayed_page)
                return
            target = self.project_dir / "analyse" / f"snippet-{doc['id']}-{frag['id']}.png"
            render_composite_crops(preview_path, segments, target, scale=snippet_scale)
            photo = tk.PhotoImage(file=str(target))
            page_image_width, page_image_height = photo.width(), photo.height()
            canvas.delete("all")
            canvas.create_image(0, 0, image=photo, anchor="nw")
            canvas.image = photo
            redraw_guides()
            canvas.yview_moveto(0)

        def change_page(delta):
            page_var.set(max(2, min(page_count, int(page_var.get()) + delta)))
            show_document(page_var.get())

        def on_press(event):
            nonlocal drag_handle, drag_initial_boundary_y
            y = canvas.canvasy(event.y)
            drag_initial_boundary_y = y
            if snippet_mode:
                drag_handle = None
                for layout in snippet_layout:
                    span = layout["span"]
                    top_px = layout["y0"] + (
                        float(span["top"]) * layout["page_height"] - layout["clip_top"]
                    ) * snippet_scale
                    bottom_px = layout["y0"] + (
                        float(span["bottom"]) * layout["page_height"] - layout["clip_top"]
                    ) * snippet_scale
                    if abs(y - top_px) <= 12:
                        drag_handle = {"layout": layout, "edge": "top"}
                        break
                    if abs(y - bottom_px) <= 12:
                        drag_handle = {"layout": layout, "edge": "bottom"}
                        break
            else:
                top_px = position_for(*selection_start)
                bottom_px = position_for(*selection_end)
                if abs(y - top_px) <= 12:
                    drag_handle = {"edge": "top"}
                elif abs(y - bottom_px) <= 12:
                    drag_handle = {"edge": "bottom"}
                else:
                    drag_handle = None

        drag_pointer_y = None
        auto_scroll_job = None
        drag_initial_boundary_y = None

        def update_drag_selection(pointer_y):
            nonlocal selection_start, selection_end, selection_dirty
            y = max(0.0, min(float(page_image_height), canvas.canvasy(pointer_y)))
            if snippet_mode:
                layout = drag_handle["layout"]
                span = layout["span"]
                original_y = layout["clip_top"] + (y - layout["y0"]) / snippet_scale
                original_y = max(layout["clip_top"], min(layout["clip_bottom"], original_y))
                normalized = max(0.0, min(1.0, original_y / layout["page_height"]))
                if drag_handle["edge"] == "top":
                    span["top"] = min(normalized, float(span["bottom"]) - 0.005)
                else:
                    span["bottom"] = max(normalized, float(span["top"]) + 0.005)
            elif drag_handle["edge"] == "top":
                y = min(y, position_for(*selection_end) - 5.0)
                selection_start = point_for_y(y)
                selection_dirty = True
            else:
                y = max(y, position_for(*selection_start) + 5.0)
                selection_end = point_for_y(y)
                selection_dirty = True
            redraw_guides()

        def auto_scroll_tick():
            nonlocal auto_scroll_job
            auto_scroll_job = None
            if not drag_handle or drag_pointer_y is None:
                return
            viewport_height = max(1, canvas.winfo_height())
            # Deliberately slow, fixed-step scrolling. The former 1-2 units
            # every 100 ms accelerated too much near the edge and could race
            # the pointer across a very tall stitched page.
            edge_zone = 24
            if drag_pointer_y < edge_zone:
                canvas.yview_scroll(-1, "units")
            elif drag_pointer_y > viewport_height - edge_zone:
                canvas.yview_scroll(1, "units")
            else:
                return
            update_drag_selection(max(0, min(viewport_height, drag_pointer_y)))
            auto_scroll_job = canvas.after(180, auto_scroll_tick)

        def schedule_auto_scroll():
            nonlocal auto_scroll_job
            if not drag_handle or auto_scroll_job is not None:
                return
            viewport_height = max(1, canvas.winfo_height())
            if drag_pointer_y < 24 or drag_pointer_y > viewport_height - 24:
                auto_scroll_job = canvas.after(180, auto_scroll_tick)

        def on_drag(event):
            nonlocal drag_pointer_y
            if not drag_handle:
                return
            drag_pointer_y = event.y
            update_drag_selection(event.y)
            schedule_auto_scroll()

        def on_release(_event):
            nonlocal drag_handle, drag_pointer_y, auto_scroll_job, drag_initial_boundary_y
            if auto_scroll_job is not None:
                canvas.after_cancel(auto_scroll_job)
                auto_scroll_job = None
            if drag_handle:
                if snippet_mode:
                    save_structure()
                else:
                    current = selected_fragment()
                    if current:
                        try:
                            old_boundary_y = drag_initial_boundary_y
                            new_boundary_y = canvas.canvasy(_event.y) if _event is not None else None
                            current["page_spans"] = selection_to_spans()
                            # Keep adjacent context/question fragments joined
                            # when the shared lower/upper boundary is dragged.
                            if (canonical_fragment_type(current.get("type")) == "context"
                                    and drag_handle.get("edge") == "bottom"
                                    and old_boundary_y is not None and new_boundary_y is not None):
                                old_point = point_for_y(old_boundary_y)
                                new_point = point_for_y(new_boundary_y)
                                old_global = position_for(*old_point)
                                for neighbour in fragments:
                                    if neighbour is current or canonical_fragment_type(neighbour.get("type")) != "vraag":
                                        continue
                                    q_spans = sorted(neighbour.get("page_spans", []), key=lambda x: int(x["page"]))
                                    if not q_spans:
                                        continue
                                    q_first = q_spans[0]
                                    q_top = (int(q_first["page"]), float(q_first["top"]))
                                    if abs(position_for(*q_top) - old_global) <= 3.0:
                                        last = q_spans[-1]
                                        last_point = (int(last["page"]), float(last["bottom"]))
                                        if position_for(*new_point) < position_for(*last_point) - 4:
                                            first_page, first_top = new_point
                                            last_page, last_bottom = last_point
                                            rebuilt = []
                                            for page_no in range(first_page, last_page + 1):
                                                top = first_top if page_no == first_page else 0.0
                                                bottom = last_bottom if page_no == last_page else preview_heights[page_no] / page_sizes[page_no][1]
                                                if bottom - top >= 0.005:
                                                    rebuilt.append(make_page_span(page_no, top, bottom))
                                            if rebuilt:
                                                neighbour["page_spans"] = rebuilt
                                        break
                            # Do not rebuild/reselect the tree row here: its
                            # selection event reloads the fragment and jumps
                            # the stitched canvas back to the fragment start.
                            save_structure()
                        except Exception as exc:
                            messagebox.showerror("Selectie niet opgeslagen", str(exc), parent=win)
                redraw_guides()
            drag_handle = None
            drag_pointer_y = None
            drag_initial_boundary_y = None

        canvas.bind("<Button-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)

        def refresh_fragment_list():
            selected = selected_fragment()
            selected_id = selected.get("id") if selected else None
            fragments[:] = sort_fragments_reading_order(fragments)
            for iid in fragment_tree.get_children(): fragment_tree.delete(iid)
            for index, frag in enumerate(fragments):
                links = ",".join(str(x) for x in frag.get("question_numbers", []))
                confidence = frag.get("confidence")
                confidence_label = f"{float(confidence):.0%}" if isinstance(confidence, (int, float)) else "—"
                fragment_tree.insert("", "end", iid=str(index), text=fragment_type_labels.get(canonical_fragment_type(frag.get("type", "")), f"Fragment {index+1}"),
                    values=(fragment_type_labels.get(canonical_fragment_type(frag.get("type", "")), "Onbekend"), links, confidence_label))
            if selected_id:
                selected_index = next((i for i, item in enumerate(fragments)
                                       if item.get("id") == selected_id), None)
                if selected_index is not None:
                    fragment_tree.selection_set(str(selected_index))
        def save_structure():
            nonlocal original_structure_signature, selection_dirty
            save_status.set("Wijzigingen opslaan…")
            current = selected_fragment()
            if not snippet_mode and current and selection_dirty:
                try:
                    current["page_spans"] = selection_to_spans()
                except ValueError as exc:
                    save_status.set("Niet opgeslagen: controleer de selectie.")
                    messagebox.showerror("Selectie niet opgeslagen", str(exc), parent=win)
                    return False
            new_signature = json.dumps(fragments, ensure_ascii=False, sort_keys=True)
            structure_changed = new_signature != original_structure_signature
            # An explicit boundary edit reviews only the selected fragment.
            # Existing, previously hand-adjusted projects are recognized as
            # reviewed when loaded; untouched fresh proposals stay provisional.
            if selection_dirty and current:
                current["status"] = "handmatig_gecontroleerd"
                current["reviewed_by_human"] = True
                current["reviewed_at"] = now()
            structure = make_exam_structure(doc, fragments, question_numbers)
            errors = validate_exam_structure(structure, doc["id"], doc["sha256"], question_numbers)
            if errors:
                save_status.set("Niet opgeslagen: controleer de fragmenten.")
                messagebox.showerror("Structuur niet opgeslagen", "Controleer eerst:\\n" + "\\n".join(errors), parent=win)
                return False
            selection_dirty = False
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
            save_status.set(f"Automatisch opgeslagen · {datetime.now().astimezone().strftime('%H:%M:%S')}")
            self._log(f"Examenstructuur opgeslagen: {len(fragments)} fragment(en), bron {doc['bestand']}.")
            return True
        def create_fragment():
            try:
                kind = fragment_type_ids[type_var.get()]
                links = selected_links()
                if kind == "context" and not links:
                    raise ValueError("Koppel dit contextfragment aan minimaal één vraag.")
                spans = selection_to_spans()
                fragment = make_fragment(
                    kind, spans[0], links, question_numbers,
                    f"frag-{doc['id'][:8]}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                )
                fragment["page_spans"] = spans
                fragment["status"] = "handmatig_gecontroleerd"
                fragment["reviewed_by_human"] = True
                fragment["reviewed_at"] = now()
                fragments.append(fragment)
                refresh_fragment_list()
                new_index = next(i for i, item in enumerate(fragments)
                                 if item.get("id") == fragment.get("id"))
                fragment_tree.selection_set(str(new_index))
                save_structure()
                show_document()
            except Exception as exc:
                messagebox.showerror("Fragment niet opgeslagen", str(exc), parent=win)
        def update_page_span():
            nonlocal selection_dirty
            if snippet_mode:
                messagebox.showinfo(
                    "Fragmentvoorbeeld",
                    "Pas de grenzen rechtstreeks aan met de zwarte lijnen. "
                    "Gebruik 'Doorlopende PDF' om de selectie op het volledige document te wijzigen.",
                    parent=win,
                )
                return
            frag = selected_fragment()
            if not frag:
                messagebox.showinfo("Selecteer fragment", "Selecteer eerst het fragment waarvan je de grenzen wilt aanpassen.", parent=win)
                return
            try:
                frag["page_spans"] = selection_to_spans()
                selection_dirty = True
                # The fragment's label/type/link columns did not change, so
                # leave the Treeview untouched to avoid a selection event.
                save_structure()
                redraw_guides()
            except Exception as exc:
                messagebox.showerror("Selectie niet bijgewerkt", str(exc), parent=win)
        def append_page():
            nonlocal selection_start, selection_end, selection_dirty
            if snippet_mode:
                show_document(displayed_page)
                return
            frag = selected_fragment()
            if not frag:
                messagebox.showinfo("Selecteer fragment", "Selecteer eerst het fragment waaraan je een volledige pagina wilt toevoegen.", parent=win)
                return
            try:
                page_no = int(displayed_page)
                span = make_page_span(
                    page_no, 0.0,
                    min(1.0, preview_heights[page_no] / page_sizes[page_no][1]),
                )
                updated = append_page_span(frag, span)
                fragments[int(fragment_tree.selection()[0])] = updated
                ordered_spans = sorted(
                    updated.get("page_spans", []),
                    key=lambda item: int(item["page"]),
                )
                if ordered_spans:
                    selection_start = (
                        int(ordered_spans[0]["page"]),
                        float(ordered_spans[0]["top"]),
                    )
                    selection_end = (
                        int(ordered_spans[-1]["page"]),
                        float(ordered_spans[-1]["bottom"]),
                    )
                    selection_dirty = True
                refresh_fragment_list()
                fragment_tree.selection_set(str(fragments.index(updated)))
                save_structure()
                show_document(page_no)
            except Exception as exc:
                messagebox.showerror("Pagina niet toegevoegd", str(exc), parent=win)
        def delete_fragment():
            sel = fragment_tree.selection()
            if not sel: return
            index = int(sel[0])
            if not messagebox.askyesno("Fragment verwijderen", "Weet je zeker dat je dit fragment wilt verwijderen?", parent=win): return
            fragment_tree.selection_remove(fragment_tree.selection())
            fragments.pop(index)
            refresh_fragment_list()
            save_structure()
            if fragments:
                next_index = min(index, len(fragments) - 1)
                fragment_tree.selection_set(str(next_index))
                load_selected_fragment()
            else:
                show_document()
        def load_selected_fragment(_event=None):
            nonlocal selection_start, selection_end, displayed_page, selection_dirty
            frag = selected_fragment()
            if frag:
                valid_spans = sorted(
                    [item for item in frag.get("page_spans", [])
                     if int(item.get("page", 0)) in page_layout_by_original],
                    key=lambda item: int(item["page"]),
                )
                if valid_spans:
                    first, last = valid_spans[0], valid_spans[-1]
                    selection_dirty = False
                    selection_start = (int(first["page"]), float(first["top"]))
                    selection_end = (int(last["page"]), float(last["bottom"]))
                    displayed_page = int(first["page"])
                    page_var.set(displayed_page)
                else:
                    selection_dirty = False
                    selection_start = (2, 0.0)
                    selection_end = (
                        2, min(1.0, preview_heights[2] / page_sizes[2][1])
                    )
                    fragment_info.configure(
                        text="Dit oude fragment bevat geen geldige selectie op de opgeschoonde pagina's. "
                             "Baken het fragment opnieuw af op de doorlopende PDF."
                    )
                show_document(displayed_page)
                type_var.set(fragment_type_labels.get(canonical_fragment_type(frag.get("type", "context")), "Context"))
                qlist.selection_clear(0, "end")
                for i, number in enumerate(question_numbers):
                    if number in frag.get("question_numbers", []): qlist.selection_set(i)
                evidence = frag.get("evidence") or {}
                confidence = frag.get("confidence")
                certainty = f" · zekerheid {float(confidence):.0%}" if isinstance(confidence, (int, float)) else ""
                reason = evidence.get("reason") or "Handmatig afgebakend; controleer de inhoud en koppeling."
                captions = evidence.get("captions") or []
                detail = f"{fragment_type_labels.get(canonical_fragment_type(frag.get('type', '')), 'Fragment')}{certainty}\\n{reason}"
                if any(int(span.get("page", 0)) == 1 for span in frag.get("page_spans", [])):
                    detail += "\\nLET OP: dit bestaande fragment bevat nog een selectie op het verwijderde voorblad. Baken het fragment opnieuw af."
                if captions:
                    detail += "\\nBijschrift: " + " · ".join(captions[:2])
                fragment_info.configure(text=detail)
        def update_fragment_row(frag):
            try:
                index = fragments.index(frag)
                fragment_tree.item(
                    str(index),
                    values=(
                        fragment_type_labels.get(canonical_fragment_type(frag.get("type", "")), "Onbekend"),
                        ",".join(str(x) for x in frag.get("question_numbers", [])),
                        f"{float(frag['confidence']):.0%}" if isinstance(frag.get("confidence"), (int, float)) else "—",
                    ),
                )
            except (ValueError, tk.TclError):
                pass

        def autosave_fragment_links(_event=None):
            frag = selected_fragment()
            if not frag:
                return
            new_type = fragment_type_ids[type_var.get()]
            links = selected_links()
            if new_type == "vraag" and len(links) != 1:
                save_status.set("Kies precies één vraag voor een vraagfragment.")
                return
            if new_type == "context" and not links:
                save_status.set("Koppel een context aan minimaal één vraag.")
                return
            if any(int(span.get("page", 0)) == 1 for span in frag.get("page_spans", [])):
                save_status.set("Dit oude fragment moet eerst opnieuw worden afgebakend.")
                return
            frag["type"] = new_type
            frag["question_numbers"] = links
            if save_structure():
                update_fragment_row(frag)
                redraw_guides()

        type_box.bind("<<ComboboxSelected>>", autosave_fragment_links)
        qlist.bind("<<ListboxSelect>>", autosave_fragment_links)
        fragment_tree.bind("<<TreeviewSelect>>", load_selected_fragment)
        def start_new_fragment():
            nonlocal selection_start, selection_end, displayed_page, selection_dirty
            fragment_tree.selection_remove(fragment_tree.selection())
            qlist.selection_clear(0, "end")
            type_var.set("Context")
            displayed_page = max(2, min(page_count, int(page_var.get())))
            selection_start = (displayed_page, 0.0)
            selection_end = (
                displayed_page,
                min(1.0, preview_heights[displayed_page] / page_sizes[displayed_page][1]),
            )
            selection_dirty = True
            show_document(displayed_page)
        def edit_selected_source_page():
            frag = selected_fragment()
            if not frag:
                messagebox.showinfo("Selecteer fragment", "Selecteer eerst een fragment.", parent=win)
                return
            spans = sorted(
                [item for item in frag.get("page_spans", [])
                 if int(item.get("page", 0)) in page_layout_by_original],
                key=lambda item: int(item["page"]),
            )
            if spans:
                page_var.set(int(spans[0]["page"]))
                show_document(int(spans[0]["page"]))
        def previous_fragment():
            current = fragment_tree.selection()
            index = max(0, int(current[0]) - 1) if current else 0
            if fragment_tree.exists(str(index)):
                fragment_tree.selection_set(str(index))
                fragment_tree.focus(str(index))
                load_selected_fragment()
        def next_fragment():
            current = fragment_tree.selection()
            index = min(len(fragments) - 1, int(current[0]) + 1) if current else 0
            if fragment_tree.exists(str(index)):
                fragment_tree.selection_set(str(index))
                fragment_tree.focus(str(index))
                load_selected_fragment()
        ttk.Button(nav, text="◀ Fragment", command=previous_fragment).pack(side="left", padx=(12, 2))
        ttk.Button(nav, text="Fragment ▶", command=next_fragment).pack(side="left")
        ttk.Button(nav, text="Nieuwe selectie", command=start_new_fragment).pack(side="left", padx=(12, 2))
        ttk.Button(nav, text="Doorlopende PDF", command=lambda: show_document(page_var.get())).pack(side="left")
        ttk.Button(nav, text="Fragmentvoorbeeld", command=show_fragment).pack(side="left", padx=(4, 0))
        ttk.Button(actions, text="Nieuw fragment opslaan", command=create_fragment).pack(side="left")
        ttk.Button(actions, text="Selectie bijwerken", command=update_page_span).pack(side="left", padx=8)
        ttk.Button(actions, text="Volledige pagina toevoegen", command=append_page).pack(side="left", padx=8)

        ttk.Button(actions, text="Verwijderen", command=delete_fragment).pack(side="left", padx=8)
        def save_and_close():
            if not save_structure():
                return
            try:
                # Materialize the exact user-selected question fragments once.
                # All later analysis reads this saved fragment text, not the PDF.
                source_path = self.project_dir / "bronnen" / doc["opslagbestand"]
                import pymupdf as fitz
                with fitz.open(source_path) as source_pdf:
                    selected_page_sizes = {
                        page_no + 1: (float(page.rect.width), float(page.rect.height))
                        for page_no, page in enumerate(source_pdf)
                    }
                for fragment in fragments:
                    selected_segments = page_spans_to_segments(
                        fragment.get("page_spans", []), selected_page_sizes
                    )
                    fragment["text"] = extract_region_text(source_path, selected_segments)
                saved_structure = make_exam_structure(doc, fragments, question_numbers)
                self.data.setdefault("exam_structures", {})[doc["id"]] = saved_structure
                self.data["exam_structure"] = saved_structure
                self.save_project()
                classified = self._classify_question_types_for_document(doc)
            except Exception as exc:
                self._error("Vraagtypen bepalen na fragmentcontrole", exc)
                messagebox.showerror(
                    "Volgende stap niet uitgevoerd",
                    "De fragmenten zijn opgeslagen, maar de vraagtypen konden nog niet veilig worden bepaald. "
                    "De editor blijft open zodat je de genoemde vraaggrenzen kunt herstellen.\\n\\n"
                    + str(exc), parent=win
                )
                return
            self._workspace_container.forget(win)
            win.destroy()
            self._workspace_container.add(self._workspace_left, weight=3)
            self._workspace_container.add(self._workspace_right, weight=8)
            self._workspace_refresh()
            self._workflow_refresh()
            self.status.configure(
                text=f"Fragmentcontrole afgerond · vraagtypen voor {classified} vragen bepaald · volgende stap: vraagrecords."
            )
        ttk.Button(actions, text="Fragmenten klaar · verder", command=save_and_close,
                   style="Accent.TButton").pack(side="right", padx=(8, 0))
        ttk.Label(actions, textvariable=save_status, foreground="#47734a").pack(side="right", padx=(8, 12))
        refresh_fragment_list()
        if fragments:
            fragment_tree.selection_set("0")
            load_selected_fragment()
        else:
            show_page()
        def jump_question_page(_event=None):
            nonlocal displayed_page
            try:
                number = max(2, min(page_count, int(page_var.get())))
            except (ValueError, tk.TclError):
                number = 2
            displayed_page = number
            show_document(number)
        page_spin.bind("<Return>", jump_question_page)
        if fragments:
            fragment_tree.selection_set("0")
            load_selected_fragment()
        else:
            show_document(2)

    def open_cv_region_editor(self, record, cv_doc, on_saved=None):
        """Manually delimit a question's correction-scheme region on the untouched source PDF."""
        source = self.project_dir / "bronnen" / cv_doc["opslagbestand"]
        if not source.is_file() or sha256(source) != cv_doc.get("sha256"):
            messagebox.showerror("CV-bron gewijzigd", "De oorspronkelijke CV-PDF ontbreekt of is gewijzigd. Voeg het juiste bestand opnieuw toe voordat je grenzen vastlegt.")
            return
        role = cv_doc.get("type_voorstel", "correctievoorschrift")
        if role not in ("correctievoorschrift", "aanvulling", "uitwerkbijlage"):
            messagebox.showerror("Verkeerd documenttype", "Kies een correctievoorschrift, officiële aanvulling of uitwerkbijlage.")
            return
        try:
            analysis = analyze_pdf(source)
            page_count = int(analysis["page_count"])
            page_sizes = {int(p["page"]): (float(p["width"]), float(p["height"])) for p in analysis["pages"]}
        except Exception as exc:
            self._error("CV-pagina's voorbereiden", exc)
            return
        question_number = int(record["number"])
        region_store_key = "uitwerkbijlage_regions" if role == "uitwerkbijlage" else "cv_regions"
        all_regions = self.data.setdefault(region_store_key, {})
        doc_regions = all_regions.setdefault(cv_doc["id"], {})
        existing = doc_regions.get(str(question_number), {})
        spans = [dict(x) for x in existing.get("page_spans", [])]
        win = tk.Toplevel(self.root)
        role_title = {"aanvulling": "CV-aanvulling", "uitwerkbijlage": "Uitwerkbijlage",
                      "correctievoorschrift": "Correctievoorschrift"}[role]
        win.title(f"{role_title} · vraag {question_number}")
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
                prefix = "uitwerkbijlage" if role == "uitwerkbijlage" else ("cv-amend" if role == "aanvulling" else "cv")
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
        self.data["app_versie"] = APP_VERSION
        self.data["bijgewerkt"] = now()
        temp = self.project_dir / (PROJECT_FILE + ".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.project_dir / PROJECT_FILE)
        self.project_label.configure(text=f"{self.data.get('vak', 'Biologie')} · {self.data.get('naam', self.project_dir.name if self.project_dir else '')}")
        if str(self.data.get("vak", "Biologie")).strip().lower() == "biologie":
            self.correction_bar.pack(fill="x", pady=(0, 7), before=self._workspace_container)
        else:
            self.correction_bar.pack_forget()
        self._workflow_refresh()
        owner = getattr(self, "_workspace_owner", None)
        if owner is not None:
            owner._refresh_library()

    def refresh(self):
        """Refresh document inventory, review queue and project progress."""
        documents = self.data.get("documenten", []) if self.data else []
        candidates = self.data.get("vraagkandidaten", []) if self.data else []
        records = self.data.get("vraagrecords", []) if self.data else []
        if hasattr(self, "project_label"):
            self.project_label.configure(text=(
                f"{self.data.get('vak', 'Biologie')} · {self.data.get('naam') or (self.project_dir.name if self.project_dir else '')}"
                if self.data else "Kies een examen uit de bibliotheek"))
        if hasattr(self, "correction_bar"):
            if self.data and str(self.data.get("vak", "Biologie")).strip().lower() == "biologie":
                self.correction_bar.pack(fill="x", pady=(0, 7), before=self._workspace_container)
            else:
                self.correction_bar.pack_forget()
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
                if self.data else "Importeer examens of kies een bestaand examen uit de bibliotheek om te beginnen."))
        if hasattr(self, "candidate_tree") and hasattr(self, "_workspace_temp"):
            self._workspace_refresh()
        self._workflow_refresh()

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