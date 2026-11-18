"""Deterministic PDF analysis primitives. Proposals only; never silently approve."""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path
from datetime import datetime
from typing import Any

QUESTION_RE = re.compile(r"^\s*(\d{1,2})[\.\)]\s+(?=\S)")
MC_RE = re.compile(r"^\s*([A-D])[\.\)]\s+")
FIGURE_RE = re.compile(r"(?i)\b(afbeelding|figuur|tabel|schema)\s+(\d+)\b")
POINTS_RE = re.compile(r"\((\d+)\s*(?:pnt|punten?)\)", re.I)

def digest_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def analyze_pdf(path: Path) -> dict[str, Any]:
    import fitz
    doc=fitz.open(path)
    pages=[]
    for i,page in enumerate(doc):
        blocks=[]
        for b in page.get_text("blocks", sort=True):
            x0,y0,x1,y1,text,*_=b
            if text.strip():
                blocks.append({"bbox":[round(x0,2),round(y0,2),round(x1,2),round(y1,2)],"text":text.strip()})
        pages.append({"page":i+1,"width":page.rect.width,"height":page.rect.height,
                      "text":page.get_text("text",sort=True),"blocks":blocks})
    meta=doc.metadata or {}
    doc.close()
    return {"file":path.name,"sha256":digest_file(path),"page_count":len(pages),"metadata":meta,"pages":pages}

def detect_question_candidates(analysis: dict) -> list[dict]:
    """Find plausible numbered starts; repeated numbering is intentionally retained."""
    found=[]
    for page in analysis.get("pages",[]):
        for block in page.get("blocks",[]):
            lines=block["text"].splitlines()
            for line_no,line in enumerate(lines):
                m=QUESTION_RE.match(line)
                if not m: continue
                n=int(m.group(1))
                if not 1 <= n <= 60: continue
                # Exclude likely list numbering and years/decimal fragments.
                prefix=block["text"][:max(0,block["text"].find(line))]
                if re.search(r"\b(?:bijvoorbeeld|namelijk|stappenplan)\s*$",prefix,re.I): continue
                found.append({"number":n,"page":page["page"],"bbox":block["bbox"],
                              "line":line.strip(),"line_index":line_no,
                              "confidence":0.45,"status":"controle_nodig",
                              "reason":"Nummerpatroon gevonden; vraagstart moet inhoudelijk worden bevestigd."})
    # Confidence is a ranking hint, not approval.
    for item in found:
        line=item["line"]
        if len(line)>12 and re.search(r"\b(verklaar|beschrijf|noem|geef|welke|wat|waarom|bereken|noteer|leg)\b",line,re.I):
            item["confidence"]=0.72
        if re.match(r"^\d{1,2}\.\s+[A-Z]",line):
            item["confidence"]=max(item["confidence"],0.68)
    return found

def render_crop(pdf_path: Path, page_number: int, bbox: list[float], output: Path, scale: float=2.0):
    """Render a source PDF rectangle unchanged; coordinates are PDF points."""
    import fitz
    if page_number < 1: raise ValueError("Paginanummer begint bij 1.")
    doc=fitz.open(pdf_path)
    if page_number > len(doc): raise ValueError("Paginanummer valt buiten het document.")
    page=doc[page_number-1]
    rect=fitz.Rect(*bbox) & page.rect
    if rect.is_empty or rect.width < 2 or rect.height < 2: raise ValueError("Ongeldige uitsnede.")
    pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=rect,alpha=False)
    output.parent.mkdir(parents=True,exist_ok=True)
    pix.save(output)
    doc.close()
    return {"path":str(output),"page":page_number,"bbox":list(rect),"source_sha256":digest_file(pdf_path),
            "method":"directe PDF-render; geen inhoudelijke beeldbewerking"}

def learn_decision(knowledge_dir: Path, decision: dict):
    knowledge_dir.mkdir(parents=True,exist_ok=True)
    path=knowledge_dir/"decisions.jsonl"
    record={"created_at":datetime.now().astimezone().isoformat(timespec="seconds"),**decision}
    with path.open("a",encoding="utf-8") as f: f.write(json.dumps(record,ensure_ascii=False)+"\n")
    return record

def load_decisions(knowledge_dir: Path) -> list[dict]:
    path=knowledge_dir/"decisions.jsonl"
    if not path.exists(): return []
    rows=[]
    for line in path.read_text(encoding="utf-8").splitlines():
        try: rows.append(json.loads(line))
        except json.JSONDecodeError: continue
    return rows

def suggest_from_learning(knowledge_dir: Path, key: str) -> dict:
    """Only return patterns backed by repeated decisions; never auto-apply."""
    matches=[d for d in load_decisions(knowledge_dir) if d.get("pattern_key")==key and d.get("accepted") is True]
    counts={}
    for d in matches:
        value=json.dumps(d.get("chosen"),sort_keys=True,ensure_ascii=False)
        counts[value]=counts.get(value,0)+1
    if not counts: return {"suggestion":None,"support":0,"auto_apply":False}
    winner=max(counts,key=counts.get)
    return {"suggestion":json.loads(winner),"support":counts[winner],"auto_apply":False}

def validate_website_records(mcq: list, opened: list, contexts: list) -> list[dict]:
    errors=[]
    ids={}
    for kind,rows in (("mcq",mcq),("open",opened)):
        for i,row in enumerate(rows):
            rid=row.get("id")
            if not rid: errors.append({"kind":"missing_id","dataset":kind,"index":i})
            elif rid in ids: errors.append({"kind":"duplicate_id","id":rid,"datasets":[ids[rid],kind]})
            else: ids[rid]=kind
            for field in ("level","year","period","n","page","q","pdf","cv"):
                if row.get(field) in (None,""): errors.append({"kind":"missing_field","id":rid,"field":field})
            for image in [row.get("image"),*(row.get("images") or [])]:
                if image and not str(image).startswith("exam-snippets/"):
                    errors.append({"kind":"unexpected_image_path","id":rid,"path":image})
    keys=set()
    for c in contexts:
        key=(c.get("level"),str(c.get("year")),str(c.get("period")),c.get("n"))
        if key in keys: errors.append({"kind":"duplicate_context","key":key})
        keys.add(key)
    return errors

def build_question_record(meta: dict, candidate: dict, question_text: str, source_pdf: str, cv_pdf: str) -> dict:
    """Create a review record, deliberately not a website publication record."""
    return {"schema":"biologie-question-review-v1","id":None,"exam":meta,
            "number":candidate["number"],"source_page":candidate["page"],
            "source_bbox":candidate["bbox"],"question_text":question_text,
            "source_pdf":source_pdf,"cv_pdf":cv_pdf,"snippet_candidates":[],
            "status":"controle_nodig","approved_by_human":False}
