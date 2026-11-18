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


DOC_ROLE_TERMS={
    "opgaven":["opgaven","opgave","vragenboekje","examenopgaven"],
    "correctievoorschrift":["correctievoorschrift","correctievoorschr","antwoordmodel","beoordelingsmodel"],
    "uitwerkbijlage":["uitwerkbijlage","uitwerkblad"],
    "aanvulling":["aanvulling","aanvullingen","erratum","errata"],
}

def classify_document_role(filename: str, text: str):
    lower=filename.lower()
    hay=(lower+" "+text[:12000].lower())
    scores={kind:sum(2 if term in lower else 1 for term in terms if term in hay)
            for kind,terms in DOC_ROLE_TERMS.items()}
    if re.search(r"-(?:o)(?:-|\.pdf$)",lower): scores["opgaven"]+=3
    if re.search(r"-(?:c)(?:-|\.pdf$)",lower): scores["correctievoorschrift"]+=3
    if re.search(r"-(?:c)-a\d",lower): scores["aanvulling"]+=5
    if re.search(r"-(?:u)(?:-|\.pdf$)",lower): scores["uitwerkbijlage"]+=3
    if "uitwerkbijlage" in lower or "uitwerkbijlage" in hay: scores["uitwerkbijlage"]+=5
    best=max(scores,key=scores.get); ordered=sorted(scores.values(),reverse=True)
    if ordered[0]==0: return "onbekend",0.0,scores
    confidence=0.96 if ordered[0]>=4 and ordered[0]>ordered[1] else (0.78 if ordered[0]>ordered[1] else 0.35)
    return best,confidence,scores

def infer_exam_metadata(filename: str):
    name=Path(filename).stem.lower()
    m=re.search(r"(?:^|[-_])(ha|vw)[-_]1018[-_]a[-_](\d{2})[-_](\d+)[-_]([oc])(?:[-_]|$)",name)
    if not m: m=re.search(r"(ha|vw)[-_]?(\d{2})t(\d+)",name)
    if not m: return {}
    return {"level":"Havo" if m.group(1)=="ha" else "Vwo","year":"20"+m.group(2),
            "period":str(int(m.group(3))),"confidence":0.96,"source":"bestandsnaam"}

def digest_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def analyze_pdf(path: Path) -> dict[str, Any]:
    import pymupdf as fitz
    doc=fitz.open(path)
    pages=[]
    for i,page in enumerate(doc):
        raw=page.get_text("dict", sort=True)
        blocks=[]
        for block in raw.get("blocks",[]):
            if block.get("type") != 0: continue
            lines=[]
            for line in block.get("lines",[]):
                spans=line.get("spans",[])
                text="".join(s.get("text","") for s in spans).strip()
                if not text: continue
                boxes=[s["bbox"] for s in spans if s.get("text","").strip()]
                if boxes:
                    bbox=[min(b[0] for b in boxes),min(b[1] for b in boxes),
                          max(b[2] for b in boxes),max(b[3] for b in boxes)]
                else: bbox=line.get("bbox",block.get("bbox",[0,0,0,0]))
                lines.append({"bbox":[round(x,2) for x in bbox],"text":text})
            if lines:
                blocks.append({"bbox":block.get("bbox",[0,0,0,0]),
                               "text":"\n".join(x["text"] for x in lines),"lines":lines})
        pages.append({"page":i+1,"width":page.rect.width,"height":page.rect.height,
                      "text":page.get_text("text",sort=True),"blocks":blocks})
    meta=doc.metadata or {}
    doc.close()
    return {"file":path.name,"sha256":digest_file(path),"page_count":len(pages),"metadata":meta,"pages":pages}

def detect_question_candidates(analysis: dict) -> list[dict]:
    """Find plausible numbered starts across text blocks and page breaks."""
    pages=analysis.get("pages",[])
    lines_by_page={}
    for page in pages:
        page_lines=[]
        for block in page.get("blocks",[]):
            for line in (block.get("lines") or [{"bbox":block["bbox"],"text":x} for x in block["text"].splitlines()]):
                if line.get("text","").strip(): page_lines.append(line)
        page_lines.sort(key=lambda x:(round(x["bbox"][1],1),x["bbox"][0]))
        lines_by_page[page["page"]]=page_lines
    found=[]
    for page_index,page in enumerate(pages):
        page_lines=lines_by_page.get(page["page"],[])
        next_page_lines=lines_by_page.get(page["page"]+1,[])
        for idx,line in enumerate(page_lines):
            value=line["text"].strip()
            m=QUESTION_RE.match(value)
            standalone=re.match(r"^(\d{1,2})[.)]?$",value)
            if not m and not standalone: continue
            n=int((m or standalone).group(1))
            if not 1 <= n <= 60: continue
            next_text=page_lines[idx+1]["text"].strip() if idx+1<len(page_lines) else ""
            if standalone and not next_text and page.get("height") and line["bbox"][1] >= page["height"]*0.78 and next_page_lines:
                next_text=next_page_lines[0]["text"].strip()
            if standalone and (not next_text or re.match(r"^[A-D][.)]",next_text)):
                continue
            if re.match(r"^\d{1,2}[.)]\s+(?:januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)\b",value,re.I):
                continue
            probe=value+" "+next_text
            confidence=0.40
            if re.search(r"\b(verklaar|beschrijf|noem|geef|welke|wat|waarom|bereken|noteer|leg|toon)\b",probe,re.I):
                confidence=0.68
            if m and len(value)>16: confidence=max(confidence,0.66)
            if standalone and idx==len(page_lines)-1 and next_text:
                confidence=min(confidence,0.55)
            found.append({"number":n,"page":page["page"],"bbox":line["bbox"],
                          "line":value,"next_line":next_text,"confidence":confidence,
                          "status":"controle_nodig",
                          "reason":"Nummerpatroon gevonden; vraagstart en vraaggrens moeten worden bevestigd."})
    return found

def render_page(pdf_path: Path, page_number: int, output: Path, scale: float=1.25):
    """Render a full original page for human visual review."""
    import fitz
    doc=fitz.open(pdf_path)
    if page_number < 1 or page_number > len(doc):
        doc.close()
        raise ValueError("Paginanummer valt buiten het document.")
    pix=doc[page_number-1].get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
    output.parent.mkdir(parents=True,exist_ok=True)
    pix.save(output)
    doc.close()
    return output

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


def question_pattern_key(candidate: dict) -> str:
    line=str(candidate.get("line","")).strip()
    if re.match(r"^\d{1,2}[.)]\s+\S",line):
        return "question_start:numbered_line_with_text"
    if re.fullmatch(r"\d{1,2}[.)]?",line) and candidate.get("next_line"):
        return "question_start:standalone_number_then_text"
    return "question_start:other_number_pattern"

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
    support=counts[winner]
    competing=max((n for value,n in counts.items() if value!=winner),default=0)
    # One decision is not a reusable pattern; ties are conflicting evidence.
    if support < 2 or support==competing:
        return {"suggestion":None,"support":support,"conflicting":support==competing and competing>0,"auto_apply":False}
    return {"suggestion":json.loads(winner),"support":support,"conflicting":False,"auto_apply":False}

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
    """Create a review record; never an approved website record."""
    level_prefix="ha" if meta.get("level")=="Havo" else "vw"
    year=str(meta.get("year",""))[-2:]
    period=str(meta.get("period",""))
    question_type=meta.get("questionType","open")
    rid=f"{level_prefix}{year}t{period}-{question_type}-{candidate['number']}"
    return {"schema":"biologie-question-review-v1","id":rid,"exam":meta,
            "number":candidate["number"],"source_page":candidate["page"],
            "source_bbox":candidate["bbox"],"question_text":question_text,
            "source_pdf":source_pdf,"cv_pdf":cv_pdf,"snippet_files":[],
            "cv_snippet_file":None,"uitwerkbijlagen":[],"source_context":"",
            "status":"controle_nodig","approved_by_human":False,
            "candidate_confidence":candidate.get("confidence",0.0),
            "candidate_status":candidate.get("status","controle_nodig")}
