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
    """Find plausible numbered starts across text blocks; retain duplicates."""
    found=[]
    for page in analysis.get("pages",[]):
        page_lines=[]
        for block in page.get("blocks",[]):
            for line in (block.get("lines") or [{"bbox":block["bbox"],"text":x} for x in block["text"].splitlines()]):
                if line.get("text","").strip():
                    page_lines.append(line)
        page_lines.sort(key=lambda x:(round(x["bbox"][1],1),x["bbox"][0]))
        for idx,line in enumerate(page_lines):
            value=line["text"].strip()
            m=QUESTION_RE.match(value)
            standalone=re.match(r"^(\d{1,2})[.)]?$",value)
            if not m and not standalone: continue
            n=int((m or standalone).group(1))
            if not 1 <= n <= 60: continue
            next_text=page_lines[idx+1]["text"].strip() if idx+1<len(page_lines) else ""
            if standalone and (not next_text or re.match(r"^[A-D][.)]",next_text)):
                continue
            if re.match(r"^\d{1,2}[.)]\s+(?:januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)\b",value,re.I):
                continue
            probe=value+" "+next_text
            confidence=0.40
            if re.search(r"\b(verklaar|beschrijf|noem|geef|welke|wat|waarom|bereken|noteer|leg|toon)\b",probe,re.I):
                confidence=0.68
            if m and len(value)>16: confidence=max(confidence,0.66)
            found.append({"number":n,"page":page["page"],"bbox":line["bbox"],
                          "line":value,"next_line":next_text,"confidence":confidence,
                          "status":"controle_nodig",
                          "reason":"Nummerpatroon gevonden; vraagstart en vraaggrens moeten worden bevestigd."})
    return found



def detect_cv_question_numbers(analysis: dict) -> list[dict]:
    """Find explicit 'Vraag N'/'Opgave N' anchors in a marking scheme."""
    found=[]
    pattern=re.compile(r"(?i)\b(vraag|opgave)\s+(\d{1,2})\b")
    for page in analysis.get("pages",[]):
        for match in pattern.finditer(page.get("text","")):
            found.append({"number":int(match.group(2)),"page":page["page"],
                          "label":match.group(1).lower(),"status":"controle_nodig"})
    return found

def compare_question_numbering(opgaven: list[dict], cv: list[dict]) -> dict:
    op_numbers={x["number"] for x in opgaven}
    cv_numbers={x["number"] for x in cv}
    return {"opgaven_nummers":sorted(op_numbers),"cv_nummers":sorted(cv_numbers),
            "ontbreekt_in_cv":sorted(op_numbers-cv_numbers),
            "ontbreekt_in_opgaven":sorted(cv_numbers-op_numbers),
            "opgaven_dubbelen":sorted(n for n in op_numbers if sum(x["number"]==n for x in opgaven)>1),
            "cv_dubbelen":sorted(n for n in cv_numbers if sum(x["number"]==n for x in cv)>1),
            "status":"vergelijking_is_signaal_geen_goedkeuring"}

def propose_question_regions(analysis: dict, candidates: list[dict], horizontal_margin: float=28.0) -> list[dict]:
    """Propose source-page regions between consecutive starts; never call them complete."""
    pages={p["page"]:p for p in analysis.get("pages",[])}
    ordered=sorted(candidates,key=lambda x:(x["page"],x["bbox"][1],x["bbox"][0]))
    proposals=[]
    for i,item in enumerate(ordered):
        page_no=item["page"]
        page=pages.get(page_no)
        if not page: continue
        x0=horizontal_margin
        x1=max(x0+10,page["width"]-horizontal_margin)
        y0=max(0.0,item["bbox"][1]-8.0)
        next_item=ordered[i+1] if i+1<len(ordered) else None
        if next_item and next_item["page"]==page_no:
            y1=min(page["height"],max(y0+10,next_item["bbox"][1]-5.0))
            segments=[{"page":page_no,"bbox":[x0,y0,x1,y1]}]
        else:
            segments=[{"page":page_no,"bbox":[x0,y0,x1,page["height"]]}]
            if next_item and next_item["page"]>page_no+1:
                for pno in range(page_no+1,next_item["page"]):
                    p=pages.get(pno)
                    if p: segments.append({"page":pno,"bbox":[x0,0.0,x1,p["height"]]})
            if next_item and next_item["page"]>page_no:
                p=pages.get(next_item["page"])
                if p:
                    y1=min(p["height"],max(10.0,next_item["bbox"][1]-5.0))
                    segments.append({"page":next_item["page"],"bbox":[x0,0.0,x1,y1]})
        proposals.append({"number":item["number"],"start_page":page_no,
                          "source_segments":segments,"status":"voorstel_niet_goedgekeurd",
                          "completeness":"onbekend",
                          "warning":"Dit fragment loopt tot de volgende gevonden nummerkandidaat. Gedeelde context, bijschriften en verwijzingen kunnen erbuiten staan."})
    return proposals

def find_context_references(analysis: dict, question_text: str, before_pages: int=3) -> list[dict]:
    """Find earlier page mentions of referenced figures/tables as review leads."""
    refs=[]
    for kind,number in FIGURE_RE.findall(question_text or ""):
        refs.append((kind.lower(),int(number)))
    if not refs: return []
    pages=analysis.get("pages",[])
    results=[]
    for kind,number in refs:
        pattern=re.compile(rf"(?i)\b{re.escape(kind)}\s+{number}\b")
        for page in pages:
            if pattern.search(page.get("text","")):
                results.append({"kind":kind,"number":number,"page":page["page"],
                                "match":"verwijzing of bijschrift gevonden",
                                "status":"contextkandidaat_niet_bevestigd"})
    return results


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
