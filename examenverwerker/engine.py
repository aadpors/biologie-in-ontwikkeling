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

def infer_exam_metadata(filename: str, text: str = ""):
    name=Path(filename).stem.lower()
    m=re.search(r"(?:^|[-_])(ha|vw)[-_]1018[-_]a[-_](\d{2})[-_](\d+)[-_]([ocu])(?:[-_]|$)",name)
    if not m: m=re.search(r"(ha|vw)[-_]?(\d{2})t(\d+)",name)
    if m:
        return {"level":"Havo" if m.group(1)=="ha" else "Vwo","year":"20"+m.group(2),
                "period":str(int(m.group(3))),"confidence":0.96,"source":"bestandsnaam"}
    # If filenames are renamed, use only the opening pages as a secondary
    # source. All three identity fields must be present before auto-suggesting.
    opening=" ".join(str(text or "").split())[:5000]
    level_match=re.search(r"\b(HAVO|VWO)\b",opening,re.I)
    year_match=re.search(r"\b(20\d{2})\b",opening)
    period_match=re.search(r"\b(?:tijdvak|tijdvaknummer|tv)\s*([123])\b",opening,re.I)
    if level_match and year_match and period_match:
        return {"level":"Havo" if level_match.group(1).lower()=="havo" else "Vwo",
                "year":year_match.group(1),"period":period_match.group(1),
                "confidence":0.82,"source":"eerste_pdf_paginas"}
    return {}

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
        visual_assets = []
        image_index = 0
        vector_index = 0
        for raw_block in raw.get("blocks", []):
            if raw_block.get("type") == 1 and raw_block.get("bbox"):
                image_index += 1
                visual_assets.append({
                    "id": f"p{i+1}-image-{image_index}", "kind": "image",
                    "bbox": [round(float(v), 2) for v in raw_block["bbox"]],
                    "width": int(raw_block.get("width", 0) or 0),
                    "height": int(raw_block.get("height", 0) or 0),
                    "extension": str(raw_block.get("ext", "")),
                    "xref": int(raw_block.get("xref", 0) or 0)
                })
        # Vector-based figures and tables do not appear as image blocks.
        # Keep only substantial drawing bounds; tiny paths are usually glyphs
        # or decorative lines and would create thousands of noisy candidates.
        page_area = float(page.rect.width * page.rect.height) or 1.0
        try:
            for drawing in page.get_drawings():
                rect = drawing.get("rect")
                if not rect:
                    continue
                area = max(0.0, float(rect.width) * float(rect.height))
                if area / page_area < 0.012 or area / page_area > 0.92:
                    continue
                vector_index += 1
                visual_assets.append({
                    "id": f"p{i+1}-vector-{vector_index}", "kind": "vector_region",
                    "bbox": [round(float(v), 2) for v in rect],
                    "drawing_type": str(drawing.get("type", "s"))
                })
        except Exception:
            # Some malformed PDFs expose unsupported drawing commands.
            # Text and raster inventory should still remain usable.
            pass
        pages.append({"page":i+1,"width":page.rect.width,"height":page.rect.height,
                      "text":page.get_text("text",sort=True),"blocks":blocks,
                      "visual_assets": visual_assets})
    meta=doc.metadata or {}
    doc.close()
    return {"file":path.name,"sha256":digest_file(path),"page_count":len(pages),"metadata":meta,"pages":pages}

def match_exam_documents(exam_doc: dict, related_docs: list[dict]) -> list[dict]:
    """Match related PDFs only when level, year and period all agree."""
    meta = exam_doc.get("exam_metadata") or infer_exam_metadata(exam_doc.get("bestand", ""))
    def reliable(identity):
        if not all(identity.get(k) for k in ("level", "year", "period")):
            return False
        if identity.get("source") == "eerste_pdf_paginas" and float(identity.get("confidence", 0)) < 0.9:
            return False
        return True
    if not reliable(meta):
        return []
    key = (str(meta["level"]).lower(), str(meta["year"]), str(meta["period"]))
    matches = []
    for doc in related_docs:
        other = doc.get("exam_metadata") or infer_exam_metadata(doc.get("bestand", ""))
        other_key = (str(other.get("level", "")).lower(), str(other.get("year", "")), str(other.get("period", "")))
        if reliable(other) and other_key == key:
            matches.append(doc)
    return matches


def match_correction_documents(opgaven_doc: dict, cv_docs: list[dict]) -> list[dict]:
    """Match only the correction scheme belonging to this exact exam identity."""
    return match_exam_documents(opgaven_doc, cv_docs)


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
            if standalone and (not next_text or re.match(r"^[A-H][.)]?$",next_text)):
                continue
            if re.match(r"^\d{1,2}[.)]\s+(?:januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)\b",value,re.I):
                continue
            probe=value+" "+next_text
            point_marker=bool(re.fullmatch(r"\d{1,2}\s*p",next_text,re.I))
            question_cue=bool(re.search(r"\b(verklaar|beschrijf|noem|geef|welk|welke|wat|wie|waar|waarom|waardoor|waarin|waarmee|wanneer|hoe|bereken|noteer|leg|toon|gebruik|kies|bepaal|licht toe|beargumenteer|leid af|selecteer)\b",probe,re.I))
            # A bare number is not enough: text line numbers and table cells are common
            # in biology exams. Keep a standalone number only with a scoring marker
            # or a recognisable instruction/question cue in the adjacent text.
            if standalone and not point_marker and not question_cue:
                continue
            # Numbered prose lines (e.g. line-numbered source texts) are not questions
            # unless the line itself contains a question/instruction or a score marker.
            if m and not point_marker and not question_cue:
                continue
            confidence=0.95 if point_marker else (0.78 if question_cue else 0.40)
            if standalone and idx==len(page_lines)-1 and next_text:
                confidence=min(confidence,0.55)
            found.append({"number":n,"page":page["page"],"bbox":line["bbox"],
                          "line":value,"next_line":next_text,"confidence":confidence,
                          "status":"controle_nodig",
                          "reason":"Nummerpatroon gevonden; vraagstart en vraaggrens moeten worden bevestigd."})
    # One exam question number should normally have one start. If a strong
    # points-marker candidate exists, a weaker same-number prompt elsewhere is
    # usually a numbered source-text line. Suppress it but retain the evidence
    # so a reviewer can restore it if this exam uses an unusual layout.
    grouped={}
    for candidate in found:
        grouped.setdefault(candidate["number"],[]).append(candidate)
    kept=[]
    suppressed=[]
    for number,items in grouped.items():
        strong=[x for x in items if x["confidence"]>=0.9]
        weak=[x for x in items if x["confidence"]<0.9]
        if len(strong)==1 and weak:
            winner=strong[0]
            kept.extend(strong)
            for candidate in weak:
                suppressed.append({**candidate,"status":"onderdrukt_dubbel_vraagnummer",
                    "suppressed_by":{"page":winner["page"],"bbox":winner["bbox"],
                                     "line":winner["line"],"confidence":winner["confidence"]},
                    "reason":"Zelfde vraagnummer als een sterkere kandidaat met expliciete puntenaanduiding."})
        else:
            kept.extend(items)
    analysis["suppressed_question_candidates"]=suppressed
    return sorted(kept,key=lambda x:(int(x["page"]),float(x["bbox"][1]),float(x["bbox"][0])))

def render_page(pdf_path: Path, page_number: int, output: Path, scale: float=1.25):
    """Render a full original page for human visual review."""
    import pymupdf as fitz
    doc=fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError("Paginanummer valt buiten het document.")
        pix=doc[page_number-1].get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
        output.parent.mkdir(parents=True,exist_ok=True)
        pix.save(output)
    finally:
        doc.close()
    return output

def render_crop(pdf_path: Path, page_number: int, bbox: list[float], output: Path, scale: float=2.0):
    """Render a source PDF rectangle unchanged; coordinates are PDF points."""
    import pymupdf as fitz
    if page_number < 1: raise ValueError("Paginanummer begint bij 1.")
    doc=fitz.open(pdf_path)
    try:
        if page_number > len(doc): raise ValueError("Paginanummer valt buiten het document.")
        page=doc[page_number-1]
        rect=fitz.Rect(*bbox) & page.rect
        if rect.is_empty or rect.width < 2 or rect.height < 2: raise ValueError("Ongeldige uitsnede.")
        pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=rect,alpha=False)
        output.parent.mkdir(parents=True,exist_ok=True)
        pix.save(output)
        return {"path":str(output),"page":page_number,"bbox":list(rect),"source_sha256":digest_file(pdf_path),
                "method":"directe PDF-render; geen inhoudelijke beeldbewerking"}
    finally:
        doc.close()


def pixel_rect_to_pdf_bbox(pixel_bbox: list[float], image_size: tuple[int, int],
                           page_size: tuple[float, float]) -> list[float]:
    """Convert a rectangle drawn on a rendered full-page image to PDF points."""
    if len(pixel_bbox) != 4 or len(image_size) != 2 or len(page_size) != 2:
        raise ValueError("De uitsnedegegevens zijn onvolledig.")
    image_width, image_height = (float(x) for x in image_size)
    page_width, page_height = (float(x) for x in page_size)
    if min(image_width, image_height, page_width, page_height) <= 0:
        raise ValueError("De pagina-afmetingen zijn ongeldig.")
    x0, y0, x1, y1 = (float(x) for x in pixel_bbox)
    left, right = sorted((max(0.0, min(image_width, x0)), max(0.0, min(image_width, x1))))
    top, bottom = sorted((max(0.0, min(image_height, y0)), max(0.0, min(image_height, y1))))
    if right - left < 3 or bottom - top < 3:
        raise ValueError("Selecteer een duidelijk zichtbare figuur- of tabelregio.")
    sx, sy = page_width / image_width, page_height / image_height
    bbox = [round(left * sx, 2), round(top * sy, 2),
            round(right * sx, 2), round(bottom * sy, 2)]
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise ValueError("De geselecteerde uitsnede is te klein.")
    return bbox


def render_composite_crops(pdf_path: Path, segments: list[dict], output: Path, scale: float = 1.5):
    """Render multiple page regions into one tall PNG, preserving CV answers across pages."""
    import pymupdf as fitz
    if not segments:
        raise ValueError("Geen fragmentregio's opgegeven.")
    source = fitz.open(pdf_path)
    try:
        normalized=[]
        width=0.0
        total_height=0.0
        for segment in segments:
            page_no=int(segment["page"])
            if not 1 <= page_no <= len(source):
                raise ValueError(f"Ongeldig PDF-paginanummer: {page_no}")
            rect=fitz.Rect(segment["bbox"])
            rect &= source[page_no-1].rect
            if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                continue
            normalized.append((page_no-1,rect))
            width=max(width,rect.width)
            total_height += rect.height + 12.0
        if not normalized:
            raise ValueError("De opgegeven fragmenten bevatten geen zichtbaar paginagebied.")
        output_doc=fitz.open()
        try:
            target_page=output_doc.new_page(width=width,height=max(100.0,total_height))
            y=0.0
            for page_index,clip in normalized:
                target=fitz.Rect(0,y,clip.width,y+clip.height)
                target_page.show_pdf_page(target,source,page_index,clip=clip,keep_proportion=False)
                y += clip.height + 12.0
            pix=target_page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
            output.parent.mkdir(parents=True,exist_ok=True)
            pix.save(output)
        finally:
            output_doc.close()
    finally:
        source.close()
    return output


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
    if support < 2 or competing > 0:
        return {"suggestion":None,"support":support,"conflicting":competing>0,"auto_apply":False}
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

def review_checklist_errors(record: dict, checklist: dict) -> list[str]:
    """Return blockers before a human can explicitly approve a draft question."""
    required=["question_text","question_type","points","cv_alignment","images_and_context","appendices","cv_addenda"]
    if (record.get("exam") or {}).get("questionType")=="mcq":
        required.append("answer_options")
    missing=[key for key in required if checklist.get(key) is not True]
    errors=[f"controle_niet_afgevinkt:{key}" for key in missing]
    if record.get("source_analysis_invalidated") is True:
        errors.append("bron_opnieuw_geanalyseerd_record_opnieuw_samenstellen")
    if record.get("exam_structure_invalidated") is True:
        errors.append("vraag_contextstructuur_gewijzigd_record_opnieuw_samenstellen")
    if record.get("cv_region_invalidated") is True:
        errors.append("cv_regio_gewijzigd_record_opnieuw_samenstellen")
    if not str(record.get("question_text","")).strip():
        errors.append("vraagtekst_ontbreekt")
    if not record.get("source_pdf") or not record.get("cv_pdf"):
        errors.append("opgaven_of_cv_niet_gekoppeld")
    if not record.get("snippet_files") and not record.get("snippet_file"):
        errors.append("vraagfragment_ontbreekt")
    if (record.get("exam") or {}).get("questionType")=="open" and not (
        record.get("cv_snippet_file") or record.get("cv_snippet_files")
    ):
        errors.append("cv_fragment_ontbreekt")
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


def detect_cv_question_numbers(analysis: dict) -> list[dict]:
    """Detect question anchors in a correction scheme; candidates require review."""
    found = []
    seen = set()
    for page in analysis.get("pages", []):
        text = str(page.get("text", "")).replace("\\n", "\n")
        lines = [line.strip() for line in text.splitlines()]
        for index, value in enumerate(lines):
            # CVs commonly use 'Vraag 3', or a compact table row.
            patterns = (
                re.match(r"(?i)^vraag\s+(\d{1,2})(?:\b|[.:)])", value),
                # Official Dutch CV tables often use "1 maximumscore 2".
                # Subcriteria such as "1 (allel) g" are deliberately excluded.
                re.match(r"(?i)^(\d{1,2})\s+maximumscore\b", value),
                # MCQ rows use e.g. "2 B 1" (question, answer letter, score).
                re.match(r"(?i)^(\d{1,2})\s+[A-H]\s+\d\b", value),
            )
            match = next((m for m in patterns if m), None)
            # Some layouts split "Vraag" and its number, or put the number
            # immediately above "maximumscore". Never accept a bare number
            # without one of those structural cues: page/line numbers abound.
            if not match and re.fullmatch(r"\d{1,2}[.)]?", value):
                previous = lines[index - 1] if index else ""
                following = lines[index + 1] if index + 1 < len(lines) else ""
                if (re.fullmatch(r"(?i)vraag", previous)
                    or re.match(r"(?i)^maximumscore\b", following)
                    or re.match(r"(?i)^[A-H]\s+\d\b", following)):
                    match = re.match(r"^(\d{1,2})", value)
            if not match:
                continue
            number = int(match.group(1))
            if not 1 <= number <= 60:
                continue
            key = (number, page.get("page"))
            if key in seen:
                continue
            seen.add(key)
            bbox=None
            for block in page.get("blocks",[]):
                for text_line in block.get("lines",[]):
                    if str(text_line.get("text","")).strip()==value:
                        bbox=text_line.get("bbox")
                        break
                if bbox:
                    break
            if bbox is None:
                bbox=[0.0,0.0,float(page.get("width",0)),0.0]
            found.append({"number": number, "page": page.get("page"), "bbox": bbox,
                          "line": value, "confidence": 0.75,
                          "status": "controle_nodig",
                          "reason": "Vraaganker in correctievoorschrift; inhoudelijke controle vereist."})
    return found


def compare_question_numbering(opgaven: list[dict], cv: list[dict]) -> dict:
    """Compare unique question numbers without assuming either source is complete."""
    op_numbers = sorted({int(x["number"]) for x in opgaven if x.get("number") is not None})
    cv_numbers = sorted({int(x["number"]) for x in cv if x.get("number") is not None})
    return {
        "opgaven_nummers": op_numbers,
        "cv_nummers": cv_numbers,
        "ontbreekt_in_cv": sorted(set(op_numbers) - set(cv_numbers)),
        "ontbreekt_in_opgaven": sorted(set(cv_numbers) - set(op_numbers)),
        "status": "controle_nodig" if set(op_numbers) != set(cv_numbers) else "nummers_overeen"
    }


def propose_question_regions(analysis: dict, candidates: list[dict]) -> list[dict]:
    """Propose per-question page regions, split by page; proposals are never approved."""
    pages = {int(p["page"]): p for p in analysis.get("pages", [])}
    ordered = sorted(candidates, key=lambda c: (int(c["page"]), float(c.get("bbox", [0, 0])[1])))
    proposals = []
    for index, candidate in enumerate(ordered):
        start_page = int(candidate["page"])
        if start_page not in pages:
            continue
        start_bbox = candidate.get("bbox", [0, 0, 0, 0])
        start_y = max(0.0, float(start_bbox[1]) - 8.0)
        next_candidate = ordered[index + 1] if index + 1 < len(ordered) else None
        end_page = int(next_candidate["page"]) if next_candidate else max(pages)
        end_y = max(0.0, float(next_candidate.get("bbox", [0, 0])[1]) - 8.0) if next_candidate else None
        segments = []
        for page_no in range(start_page, end_page + 1):
            page = pages.get(page_no)
            if not page:
                continue
            width, height = float(page.get("width", 0)), float(page.get("height", 0))
            if width <= 0 or height <= 0:
                continue
            y0 = start_y if page_no == start_page else 0.0
            y1 = end_y if page_no == end_page and end_y is not None else height
            if y1 > y0:
                segments.append({"page": page_no, "bbox": [0.0, y0, width, y1]})
        if not segments:
            continue
        question_text = extract_candidate_text(analysis, candidate, next_candidate)
        context_refs = detect_context_references(question_text)
        linked_context = link_context_assets(analysis, context_refs, start_page, end_page)
        proposals.append({
            "number": int(candidate["number"]), "start_page": start_page,
            "end_page": end_page, "source_segments": segments,
            "text_proposal": question_text, "context_candidates": linked_context,
            "context_assets_require_manual_review": True,
            "status": "voorstel_niet_goedgekeurd",
            "warning": "Automatische paginagrenzen en contextverwijzingen zijn indicatief. Controleer vraagtekst, figuren, tabellen, bijschriften en eventuele doorloop handmatig."
        })
    return proposals



def extract_candidate_text(analysis: dict, candidate: dict, next_candidate: dict | None = None) -> str:
    """Extract a bounded text proposal between consecutive question anchors."""
    start_page = int(candidate["page"])
    start_y = float(candidate.get("bbox", [0, 0, 0, 0])[1])
    stop_page = int(next_candidate["page"]) if next_candidate else None
    stop_y = float(next_candidate.get("bbox", [0, 0, 0, 0])[1]) if next_candidate else None
    collected = []
    for page in analysis.get("pages", []):
        page_no = int(page["page"])
        if page_no < start_page or (stop_page is not None and page_no > stop_page):
            continue
        for block in page.get("blocks", []):
            lines = block.get("lines") or [{"bbox": block.get("bbox", [0, 0, 0, 0]), "text": x}
                                           for x in str(block.get("text", "")).splitlines()]
            for line in lines:
                text = str(line.get("text", "")).strip()
                if not text:
                    continue
                y = float(line.get("bbox", [0, 0, 0, 0])[1])
                if page_no == start_page and y + 1 < start_y:
                    continue
                if stop_page is not None and page_no == stop_page and y >= stop_y:
                    continue
                collected.append((page_no, y, text))
    collected.sort(key=lambda item: (item[0], item[1]))
    return "\n".join(item[2] for item in collected)



def link_context_assets(analysis: dict, references: list[dict],
                       start_page: int | None = None,
                       end_page: int | None = None) -> list[dict]:
    """Find reviewable image/vector candidates for explicit figure/table references.

    This is deliberately a candidate linker, not an automatic semantic match.
    It uses caption text and PDF geometry, and preserves ambiguity for review.
    """
    pages = analysis.get("pages", [])
    page_map = {int(p.get("page", 0)): p for p in pages}
    caption_re = re.compile(
        r"^\s*(figuur|afbeelding|foto|illustratie|tabel|grafiek|diagram|schema|bron|tekst|bijlage)\s*([0-9]{1,2}[A-Z]?|[A-Z])\b",
        re.I
    )
    kind_map = {
        "figuur": "figuur", "afbeelding": "afbeelding", "foto": "afbeelding",
        "illustratie": "afbeelding", "tabel": "tabel", "grafiek": "grafiek",
        "diagram": "grafiek", "schema": "grafiek",
        "bron": "bron", "tekst": "bron", "bijlage": "bron"
    }
    results = []
    for ref in references:
        kind = ref.get("kind")
        number = str(ref.get("number") or "").upper()
        if not number or kind == "ongenummerde_verwijzing":
            results.append({**ref, "caption_matches": [], "asset_candidates": [],
                            "link_status": "geen_nummer_handmatige_koppeling"})
            continue
        captions = []
        for page in pages:
            page_no = int(page.get("page", 0))
            for block in page.get("blocks", []):
                lines = block.get("lines") or [{"bbox": block.get("bbox", [0,0,0,0]), "text": x}
                                               for x in str(block.get("text", "")).splitlines()]
                for line in lines:
                    text = str(line.get("text", "")).strip()
                    match = caption_re.match(text)
                    if not match:
                        continue
                    caption_kind = kind_map.get(match.group(1).lower())
                    if caption_kind == kind and match.group(2).upper() == number:
                        captions.append({"page": page_no, "text": text,
                                         "bbox": line.get("bbox", block.get("bbox", [0,0,0,0]))})
        asset_candidates = []
        text_region_candidates = []
        for caption in captions:
            page = page_map.get(caption["page"], {})
            cb = caption["bbox"]
            cy = (float(cb[1]) + float(cb[3])) / 2
            if kind == "bron":
                # Source texts are often plain text rather than raster/vector
                # figures. Keep the following text blocks as explicit candidates.
                following=[]
                for block in page.get("blocks",[]):
                    bb=block.get("bbox",[0,0,0,0])
                    by=(float(bb[1])+float(bb[3]))/2
                    block_text=str(block.get("text","")).strip()
                    begins_after_caption=float(bb[1]) >= float(cb[1])
                    contains_caption=float(bb[1]) <= float(cb[1]) < float(bb[3])
                    is_caption_only=block_text.casefold()==str(caption["text"]).casefold()
                    if by > cy and (begins_after_caption or (contains_caption and not is_caption_only)):
                        following.append((max(0.0,float(bb[1])-cy),block))
                for distance,block in sorted(following,key=lambda x:x[0])[:8]:
                    text_region_candidates.append({
                        "page":caption["page"],"bbox":block.get("bbox"),
                        "text":str(block.get("text",""))[:1200],
                        "caption":caption["text"],"distance_to_caption":round(distance,1),
                        "status":"broncontext_visueel_controleren"
                    })
                continue
            ranked = []
            for asset in page.get("visual_assets", []):
                ab = asset.get("bbox", [0,0,0,0])
                ay = (float(ab[1]) + float(ab[3])) / 2
                # Captions can be either above or below the associated figure.
                distance = abs(ay - cy)
                if distance <= 220:
                    ranked.append((distance, asset))
            for distance, asset in sorted(ranked, key=lambda x: x[0])[:8]:
                asset_candidates.append({
                    "page": caption["page"], "asset_id": asset["id"],
                    "asset_kind": asset["kind"], "bbox": asset["bbox"],
                    "caption": caption["text"], "distance_to_caption": round(distance, 1),
                    "status": "visueel_controleren"
                })
        if not captions and start_page is not None:
            lo = max(1, int(start_page) - 1)
            hi = int(end_page or start_page) + 1
            for page_no in range(lo, hi + 1):
                page = page_map.get(page_no, {})
                for asset in page.get("visual_assets", []):
                    asset_candidates.append({
                        "page": page_no, "asset_id": asset["id"],
                        "asset_kind": asset["kind"], "bbox": asset["bbox"],
                        "caption": None, "distance_to_caption": None,
                        "status": "nabijgelegen_mogelijkheid_handmatig_controleren"
                    })
        results.append({
            **ref, "caption_matches": captions,
            "asset_candidates": asset_candidates,
            "text_region_candidates": text_region_candidates,
            "link_status": "caption_en_tekstregio_gevonden" if captions and text_region_candidates
                           else "caption_en_geometrie_gevonden" if captions and asset_candidates
                           else "caption_gevonden_geen_asset" if captions
                           else "geen_caption_gevonden_handmatige_koppeling"
        })
    return results


def detect_context_references(text: str) -> list[dict]:
    """Find explicit figure/table/source references for human context linking."""
    value = str(text or "")
    patterns = [
        ("figuur", r"\b(figuur)\s*([0-9]{1,2}[A-Z]?|[A-Z])\b"),
        ("afbeelding", r"\b(afbeelding|foto|illustratie)\s*([0-9]{1,2}[A-Z]?|[A-Z])\b"),
        ("tabel", r"\b(tabel)\s*([0-9]{1,2}[A-Z]?|[A-Z])\b"),
        ("grafiek", r"\b(grafiek|diagram|schema)\s*([0-9]{1,2}[A-Z]?|[A-Z])\b"),
        ("bron", r"\b(bron|tekst|bijlage)\s*([0-9]{1,2}[A-Z]?|[A-Z])\b"),
    ]
    found = []
    seen = set()
    for kind, pattern in patterns:
        for match in re.finditer(pattern, value, flags=re.I):
            number = match.group(2).upper()
            key = (kind, number)
            if key in seen:
                continue
            seen.add(key)
            found.append({"kind": kind, "number": number,
                          "matched_text": match.group(0),
                          "status": "context_koppeling_controleren"})
    if re.search(r"\b(bovenstaande|onderstaande|afgebeelde|hierboven|hieronder)\s+(afbeelding|figuur|tabel|grafiek|tekst)\b", value, re.I):
        found.append({"kind": "ongenummerde_verwijzing", "number": None,
                      "matched_text": "Verwijzing naar bovenstaand/onderstaand materiaal",
                      "status": "context_koppeling_controleren"})
    return found


def detect_question_type(text: str) -> dict:
    """Heuristic question-format detection; returns reviewable signals, not truth."""
    value = str(text or "")
    options = []
    for line in value.splitlines():
        match = re.match(r"^\s*(?:\(([A-H])\)|([A-H])[.):])\s+(.+)$", line)
        if match:
            label = match.group(1) or match.group(2)
            option_text = match.group(3).strip()
            if option_text:
                options.append({"label": label, "text": option_text})
    lowered = value.lower()
    if options:
        labels = [x["label"] for x in options]
        last_index = max("ABCDEFGH".index(x) for x in labels)
        expected = list("ABCDEFGH"[:last_index + 1])
        gaps = [label for label in expected if label not in labels]
        duplicates = sorted({label for label in labels if labels.count(label) > 1})
        complete = not gaps and not duplicates and len(options) >= 2
        return {"type": "meerkeuze", "subtype": "enkelvoudige_keuze",
                "options": options, "option_labels": labels,
                "options_complete": complete, "option_gaps": gaps,
                "duplicate_option_labels": duplicates,
                "confidence": 0.85 if complete else 0.55,
                "status": "controle_nodig"}
    if re.search(r"\b(juist|onjuist|waar|niet waar)\b", lowered) and re.search(r"\b(stelling|uitspraken|bewering)\b", lowered):
        qtype, subtype, confidence = "juist_onjuist", "stellingbeoordeling", 0.65
    elif re.search(r"\b(wel of niet|wel/niet|ja of nee|ja/nee)\b", lowered):
        qtype, subtype, confidence = "wel_niet", "binaire_beoordeling", 0.7
    else:
        qtype, subtype, confidence = "open", "open_vraag", 0.55
    return {"type": qtype, "subtype": subtype, "options": [], "option_labels": [],
            "options_complete": None, "option_gaps": [], "duplicate_option_labels": [],
            "confidence": confidence, "status": "controle_nodig"}


def extract_region_text(pdf_path: Path, segments: list[dict]) -> str:
    """Extract selectable source text inside manually bounded PDF regions, page by page."""
    import pymupdf as fitz
    if not segments:
        return ""
    source = fitz.open(pdf_path)
    try:
        parts = []
        for segment in sorted(segments, key=lambda x: int(x["page"])):
            page_no = int(segment["page"])
            if not 1 <= page_no <= len(source):
                raise ValueError(f"Ongeldig paginanummer voor tekstextractie: {page_no}")
            rect = fitz.Rect(segment["bbox"]) & source[page_no - 1].rect
            text = source[page_no - 1].get_text("text", clip=rect, sort=True).strip()
            if text:
                parts.append(f"[Pagina {page_no}]\n{text}")
        return "\n\n".join(parts)
    finally:
        source.close()


def pdf_page_count(pdf_path: Path) -> int:
    """Read only the page count for efficient final-review navigation."""
    import pymupdf as fitz
    with fitz.open(pdf_path) as document:
        return len(document)


def pixel_rect_to_pdf_bbox(pixel_bbox, image_size, page_size):
    """Convert a pixel rectangle to PDF points, clamped to the full page."""
    try:
        x0, y0, x1, y1 = (float(value) for value in pixel_bbox)
        image_width, image_height = (float(value) for value in image_size)
        page_width, page_height = (float(value) for value in page_size)
    except (TypeError, ValueError):
        raise ValueError("Ongeldige uitsnede- of paginagegevens.") from None
    if image_width <= 0 or image_height <= 0 or page_width <= 0 or page_height <= 0:
        raise ValueError("Afbeeldings- en pagina-afmetingen moeten groter dan nul zijn.")
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    left = min(max(left, 0.0), image_width)
    right = min(max(right, 0.0), image_width)
    top = min(max(top, 0.0), image_height)
    bottom = min(max(bottom, 0.0), image_height)
    bbox = [left * page_width / image_width,
            top * page_height / image_height,
            right * page_width / image_width,
            bottom * page_height / image_height]
    if bbox[2] - bbox[0] < 2.0 or bbox[3] - bbox[1] < 2.0:
        raise ValueError("De geselecteerde uitsnede is te klein.")
    return [round(value, 2) for value in bbox]
