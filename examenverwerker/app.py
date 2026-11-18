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
from tkinter import filedialog, messagebox, ttk
from engine import analyze_pdf, detect_question_candidates, detect_cv_question_numbers, compare_question_numbering, learn_decision, render_page, render_crop, propose_question_regions, classify_document_role, infer_exam_metadata

APP_VERSION = "0.2.0"
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
        ttk.Button(foot, text="Kandidaten bekijken", command=self.show_candidates).pack(side="left")
        ttk.Button(foot, text="Examengegevens controleren", command=self.edit_exam_metadata).pack(side="left", padx=6)
        ttk.Button(foot, text="Voortgang opslaan", command=self.save_project).pack(side="right")
        self.log = tk.Text(body, height=6, wrap="word", font=("Consolas", 9), background="#f5f7f7", relief="flat")
        self.log.pack(fill="x", pady=(12, 0))
        self.log.configure(state="disabled")

    def _welcome(self):
        self._log("Welkom. Maak een project per examen. Voeg daarna alle beschikbare PDF's toe.")
        self._log("Tip: selecteer opgaven, correctievoorschrift, uitwerkbijlage en eventuele aanvullingen tegelijk.")

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
        name = tk.simpledialog.askstring("Nieuw examen", "Geef het examen een herkenbare naam:", initialvalue=base.name)
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
                exam_meta = infer_exam_metadata(source.name) if kind=="opgaven" else {}
                doc = {"id": digest[:16], "bestand": source.name, "opslagbestand": target.name,
                       "exam_metadata": exam_meta,
                       "sha256": digest, "type_voorstel": kind, "type_zekerheid": confidence,
                       "herkenningssignalen": scores, "status": "controle_nodig" if confidence < 0.9 else "herkend_nog_niet_goedgekeurd",
                       "toegevoegd": now(), "pagina_aantal": extracted["pagina_aantal"],
                       "metadata": extracted["metadata"],
                       "pagina_zonder_tekst": [p["pagina"] for p in extracted["pagina_tekst"] if p.get("ocr_nodig")],
                       "ocr_status": "handmatige_ocr_controle_nodig" if any(p.get("ocr_nodig") for p in extracted["pagina_tekst"]) else "tekstlaag_aanwezig"}
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
            self.data["exam_metadata"]={"level":level.get(),"year":year.get().strip(),"period":period.get(),"confidence":1.0,"source":"handmatig_bevestigd"}
            self.save_project(); self._log(f"Examenmetadata bevestigd: {level.get()} {year.get()} tijdvak {period.get()}.")
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
        total = 0
        cv_docs = [d for d in self.data["documenten"] if d.get("type_voorstel") == "correctievoorschrift"]
        cv_candidates = []
        for cv_doc in cv_docs:
            try:
                cv_analysis = analyze_pdf(self.project_dir / "bronnen" / cv_doc["opslagbestand"])
                cv_candidates.extend(detect_cv_question_numbers(cv_analysis))
            except Exception as exc:
                self._error(f"CV-analyse ({cv_doc['bestand']})",exc)
        all_op_candidates = []
        for doc in docs:
            source = self.project_dir / "bronnen" / doc["opslagbestand"]
            try:
                analysis = analyze_pdf(source)
                candidates = detect_question_candidates(analysis)
                for item in candidates:
                    item.update({"document_id": doc["id"], "bestand": doc["bestand"]})
                all_op_candidates.extend(candidates)
                self.data.setdefault("vraagkandidaten", [])
                self.data["vraagkandidaten"] = [x for x in self.data["vraagkandidaten"] if x.get("document_id") != doc["id"]] + candidates
                (self.project_dir / "analyse" / f"{doc['id']}-vraagkandidaten.json").write_text(
                    json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
                self._log(f"{doc['bestand']}: {len(candidates)} mogelijke vraagstarts gevonden; alles staat nog op controle nodig.")
                total += len(candidates)
            except Exception as exc:
                self._error(f"Vraaganalyse ({doc['bestand']})",exc)
        if cv_candidates:
            comparison = compare_question_numbering(all_op_candidates, cv_candidates)
            self.data["nummeringsvergelijking_cv"] = comparison
            self._log(f"Vergelijking met CV: ontbreekt in CV {comparison['ontbreekt_in_cv']}; ontbreekt in opgaven {comparison['ontbreekt_in_opgaven']}. Dit is een controlesignaal.")
        else:
            self.data["nummeringsvergelijking_cv"] = {"status":"geen_CV_kandidaat_gevonden"}
            self._log("Geen CV-nummering gevonden om mee te vergelijken.")
        self.save_project()
        self.refresh()
        messagebox.showinfo("Analyse voltooid", f"{total} mogelijke vraagstarts gevonden. CV-nummering is waar mogelijk vergeleken. Dit zijn signalen, geen automatisch goedgekeurde vragen.")

    def show_candidates(self):
        if not self.data:
            return
        rows = self.data.get("vraagkandidaten", [])
        win = tk.Toplevel(self.root)
        win.title("Mogelijke vraagstarts – altijd controleren")
        win.geometry("900x580")
        ttk.Label(win, text=f"{len(rows)} kandidaten gevonden. Herhaalde nummers blijven bewust zichtbaar.", padding=10).pack(anchor="w")
        cols=("number","page","confidence","line","status")
        tree=ttk.Treeview(win,columns=cols,show="headings")
        for col,label,width in [("number","Nr.",55),("page","PDF-pagina",90),("confidence","Signaal",90),("line","Gevonden tekst",520),("status","Status",140)]:
            tree.heading(col,text=label); tree.column(col,width=width)
        tree.pack(fill="both",expand=True,padx=10,pady=10)
        for i,row in enumerate(rows):
            tree.insert("", "end", iid=str(i), values=(row.get("number"),row.get("page"),f"{row.get('confidence',0):.0%}",row.get("line"),row.get("status")))
        ttk.Label(win,text="Een nummerpatroon is geen bewijs dat het een examenvraag is. Jouw beoordeling wordt lokaal als leerdata opgeslagen.",wraplength=850).pack(anchor="w",padx=12,pady=(0,8))
        actions=ttk.Frame(win); actions.pack(fill="x",padx=12,pady=(0,12))
        def decide(is_question):
            selected=tree.selection()
            if not selected:
                messagebox.showinfo("Selecteer kandidaat","Selecteer eerst een gevonden vraagstart.")
                return
            row=rows[int(selected[0])]
            reason=tk.simpledialog.askstring("Waarom deze keuze?","Korte reden (optioneel):",parent=win) or ""
            row["status"]="bevestigd_vraagstart" if is_question else "afgewezen_geen_vraag"
            row["human_decision"]=bool(is_question)
            row["decision_reason"]=reason
            learn_decision(self.project_dir/"kennisbank",{
                "pattern_key":"question_start:numbered-line",
                "chosen":"question" if is_question else "not_question",
                "accepted":True,"scope":"voorstel_voor_toekomstige_herkenning",
                "document_id":row.get("document_id"),"page":row.get("page"),
                "candidate_line":row.get("line"),"reason":reason,
                "human_decision":bool(is_question)})
            self.save_project()
            tree.set(selected[0],"status",row["status"])
            self._log(f"Kandidaat vraag {row['number']} op pagina {row['page']}: {row['status']}. Beslissing opgeslagen in de lokale leerbank.")
        ttk.Button(actions,text="Bevestig vraagstart",command=lambda:decide(True)).pack(side="left")
        ttk.Button(actions,text="Geen vraag",command=lambda:decide(False)).pack(side="left",padx=8)
        ttk.Button(actions,text="Originele pagina bekijken",command=lambda:self.preview_candidate(rows,tree,win)).pack(side="left",padx=8)
        ttk.Button(actions,text="Voorlopige snippet maken",command=lambda:self.create_snippet_proposal(rows,tree,win)).pack(side="left",padx=8)

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
            self.save_project()
            win=tk.Toplevel(parent); win.title(f"Voorlopig fragment vraag {row['number']}"); win.geometry("900x800")
            ttk.Label(win,text="VOORSTEL – NIET GECONTROLEERD OF PUBLICATIEKLAAR",foreground="#9b4d00",padding=8).pack(fill="x")
            ttk.Label(win,text=proposal["warning"],wraplength=860,padding=8).pack(fill="x")
            refs=proposal.get("context_candidates",[])
            ref_text="Mogelijke contextverwijzingen: "+(", ".join(f"{x['kind']} {x['number']} (p. {x['page']})" for x in refs) if refs else "geen automatische verwijzing gevonden")
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
        win = tk.Toplevel(self.root)
        win.title("Documenttype bevestigen")
        win.transient(self.root)
        ttk.Label(win, text=f"Welk type is '{doc['bestand']}'?").pack(padx=18, pady=(18, 8))
        choice = tk.StringVar(value=doc["type_voorstel"])
        combo = ttk.Combobox(win, textvariable=choice, values=choices, state="readonly", width=28)
        combo.pack(padx=18, pady=8)
        def apply():
            old = doc["type_voorstel"]
            new = choice.get()
            doc["type_voorstel"] = new
            doc["type_zekerheid"] = 1.0
            doc["status"] = "handmatig_bevestigd"
            self.data["beslissingen"].append({"document_id": doc["id"], "van": old, "naar": new, "tijd": now(), "reden": "handmatige bevestiging"})
            learn_decision(self.project_dir/"kennisbank",{
                "pattern_key":"document_role:pdf-name-pattern",
                "chosen":new,"accepted":True,"scope":"voorstel_voor_toekomstige_documentherkenning",
                "filename":doc["bestand"],"previous":old,"human_decision":True})
            self.save_project()
            self.refresh()
            self._log(f"Herkenning bevestigd: {doc['bestand']} → {new}. Deze correctie wordt bewaard.")
            win.destroy()
        ttk.Button(win, text="Bevestigen", command=apply).pack(pady=(8, 18))

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
