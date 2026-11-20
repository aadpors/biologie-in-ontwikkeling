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
    if re.search(r"-(?:a)(?:-|\.pdf$)",lower): scores["aanvulling"]+=5
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
        text=page.get_text("text",sort=True)
        page_area=float(page.rect.width*page.rect.height) or 1.0
        large_image=any(
            block.get("type")==1 and block.get("bbox") and
            (max(0.0,float(block["bbox"][2])-float(block["bbox"][0]))*
             max(0.0,float(block["bbox"][3])-float(block["bbox"][1])))/page_area>0.18
            for block in raw.get("blocks",[])
        )
        # OCR is attempted only for pages whose embedded text is absent or
        # clearly insufficient relative to a large scanned image.
        ocr_used=False
        if len(text.strip())<40 or (large_image and len(text.strip())<180):
            raw_for_text=raw
            for language in ("nld+eng","eng"):
                try:
                    ocr_page=page.get_textpage_ocr(language=language,dpi=200,full=True)
                    ocr_text=page.get_text("text",textpage=ocr_page,sort=True)
                    if len(ocr_text.strip())>len(text.strip()):
                        raw_for_text=page.get_text("dict",textpage=ocr_page,sort=True)
                        text=ocr_text
                        ocr_used=True
                        break
                except Exception:
                    continue
        else:
            raw_for_text=raw
        blocks=[]
        for block in raw_for_text.get("blocks",[]):
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
                      "text":text,"ocr_used":ocr_used,"blocks":blocks,
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


def propose_context_fragments(analysis: dict, candidates: list[dict]) -> list[dict]:
    """Suggest full-width context bands around figures/tables and their captions.

    The proposal is deliberately conservative: it only uses visual objects
    inventoried from the source PDF, joins nearby captions, and links each band
    to the closest confirmed question anchor. Every result remains unapproved.
    """
    anchors = sorted(
        [row for row in candidates if row.get("human_decision") is True],
        key=lambda row: (int(row.get("page", 1)), float((row.get("bbox") or [0, 0])[1]))
    )
    if not anchors:
        return []
    proposals = []
    for page in analysis.get("pages", []):
        page_no = int(page.get("page", 0) or 0)
        page_height = float(page.get("height", 0) or 0)
        page_width = float(page.get("width", 0) or 0)
        # Page 1 of the question booklet is never exam context by design.
        if page_no < 2 or page_height <= 0 or page_width <= 0:
            continue
        assets = []
        for asset in page.get("visual_assets", []):
            bbox = asset.get("bbox") or []
            if len(bbox) != 4:
                continue
            x0, y0, x1, y1 = (float(value) for value in bbox)
            if x1 - x0 < 18 or y1 - y0 < 12:
                continue
            assets.append({"top": max(0.0, y0 - 7.0), "bottom": min(page_height, y1 + 7.0),
                           "asset_ids": [asset.get("id")], "caption": False})
        if not assets:
            continue
        captions = []
        for block in page.get("blocks", []):
            for line in block.get("lines", []):
                text = str(line.get("text", "")).strip()
                bbox = line.get("bbox") or []
                if len(bbox) != 4 or not FIGURE_RE.search(text):
                    continue
                captions.append({"top": float(bbox[1]), "bottom": float(bbox[3]),
                                 "text": text, "caption": True})
        for caption in captions:
            nearest = min(assets, key=lambda asset: min(
                abs(caption["top"] - asset["bottom"]),
                abs(asset["top"] - caption["bottom"])
            ))
            gap = max(0.0, max(caption["top"] - nearest["bottom"],
                               nearest["top"] - caption["bottom"]))
            if gap <= 70:
                nearest["top"] = max(0.0, min(nearest["top"], caption["top"] - 3.0))
                nearest["bottom"] = min(page_height, max(nearest["bottom"], caption["bottom"] + 3.0))
                nearest["caption"] = True
                nearest.setdefault("caption_text", []).append(caption["text"])

        assets.sort(key=lambda item: item["top"])
        clusters = []
        for asset in assets:
            if clusters and asset["top"] <= clusters[-1]["bottom"] + 18:
                cluster = clusters[-1]
                cluster["bottom"] = max(cluster["bottom"], asset["bottom"])
                cluster["asset_ids"].extend(asset["asset_ids"])
                cluster["caption"] = cluster["caption"] or asset["caption"]
                cluster.setdefault("caption_text", []).extend(asset.get("caption_text", []))
            else:
                clusters.append(dict(asset))
        for index, cluster in enumerate(clusters, 1):
            if cluster["bottom"] - cluster["top"] < 12:
                continue
            # A captioned visual block between two question starts is a
            # stronger signal for context introducing the next question.
            # An uncaptioned block after a question is more likely part of that
            # question's own material, so keep it linked to the preceding anchor.
            cluster_start = (page_no, float(cluster["top"]))
            following = [
                row for row in anchors
                if (int(row.get("page", 0)),
                    float((row.get("bbox") or [0, 0])[1])) >= cluster_start
            ]
            preceding = [
                row for row in anchors
                if (int(row.get("page", 0)),
                    float((row.get("bbox") or [0, 0])[1])) < cluster_start
            ]
            if following and (cluster.get("caption") or not preceding):
                linked = min(following, key=lambda row: (
                    int(row.get("page", 0)), float((row.get("bbox") or [0, 0])[1])
                ))
            elif preceding:
                linked = max(preceding, key=lambda row: (
                    int(row.get("page", 0)), float((row.get("bbox") or [0, 0])[1])
                ))
            else:
                linked = anchors[0]
            top = max(0.0, min(1.0, cluster["top"] / page_height))
            bottom = max(0.0, min(1.0, cluster["bottom"] / page_height))
            if bottom - top < 0.005:
                continue
            proposals.append({
                "id": f"voorstel-context-{page_no}-{index}-{linked.get('number')}",
                "type": "context",
                "context_role": "vraaggebonden",
                "page_spans": [{"page": page_no, "top": round(top, 6), "bottom": round(bottom, 6)}],
                "question_numbers": [int(linked["number"])],
                "status": "automatisch_voorstel_nog_te_controleren",
                "confidence": 0.82 if cluster["caption"] else 0.68,
                "evidence": {
                    "visual_assets": [value for value in cluster["asset_ids"] if value],
                    "captions": cluster.get("caption_text", []),
                    "reason": "Afbeelding, schema of tabel met nabijgelegen bijschrift"
                    if cluster["caption"] else "Visueel object in de buurt van een bevestigde vraagstart",
                },
            })
    return proposals

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


def prepare_exam_preview_pdf(source_path: Path, output_path: Path, padding: float = 3.0) -> dict:
    """Create a safe, derived preview: omit the cover and trim only proven footers.

    Footer-like text is not automatically safe to remove. Before trimming,
    every proposed footer
    line is checked for meaningful text or visual material below it. If such
    content exists, that footer hypothesis is rejected and the page is kept
    down to its last meaningful element. Source coordinates and page numbers
    remain unchanged in the returned map.
    """
    import fitz
    source = fitz.open(source_path)
    try:
        if len(source) < 2:
            raise ValueError("De opgaven-PDF bevat geen pagina's na het voorblad.")

        page_rows = []
        for page_index in range(1, len(source)):
            page = source[page_index]
            height = float(page.rect.height)
            raw = page.get_text("dict", sort=True)
            lines = []
            assets = []
            for block in raw.get("blocks", []):
                if block.get("type") == 0:
                    for line in block.get("lines", []):
                        text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                        if not text:
                            continue
                        bbox = line.get("bbox") or block.get("bbox") or [0, 0, 0, 0]
                        normalized = re.sub(r"\s+", " ", text.lower()).strip()
                        item = {
                            "text": text,
                            "normalized": normalized,
                            "top": float(bbox[1]),
                            "bottom": float(bbox[3]),
                        }
                        lines.append(item)
                elif block.get("type") == 1 and block.get("bbox"):
                    assets.append([float(x) for x in block["bbox"]])
            try:
                for drawing in page.get_drawings():
                    rect = drawing.get("rect")
                    if rect and rect.width > 18 and rect.height > 12:
                        assets.append([
                            float(rect.x0), float(rect.y0),
                            float(rect.x1), float(rect.y1),
                        ])
            except Exception:
                # Malformed vector data must not prevent text-based review.
                pass
            page_rows.append({
                "original_page": page_index + 1,
                "width": float(page.rect.width),
                "height": height,
                "lines": lines,
                "assets": assets,
            })

        explicit_footer = re.compile(
            r"^(?:examenblad\b|college voor toetsen\b|cito\b|www\.|©|"
            r"lees\s+verder(?:\s*[►▶>]{1,3})?|"
            r"(?:biologie\s*[|·-]\s*)?examen\s+20\d{2}|"
            r"(?:vw|ha)-\d{4}-[a-z]-\d{2}-\d-[\w-]+(?:\s+.*)?)$",
            re.I,
        )
        mapping = []
        preview = fitz.open()
        try:
            for row in page_rows:
                height, width = row["height"], row["width"]
                candidates = []
                for line in row["lines"]:
                    relative_top = line["top"] / max(1.0, height)
                    if relative_top < 0.76:
                        continue
                    standalone_page_number = bool(
                        re.fullmatch(r"\d{1,3}", line["normalized"])
                        and relative_top >= 0.90
                    )
                    page_counter = bool(
                        re.fullmatch(
                            r"(?:pagina\s*)?\d{1,3}\s*(?:/|van)\s*\d{1,3}",
                            line["text"], re.I,
                        )
                        or re.fullmatch(r"pagina\s*\d{1,3}", line["text"], re.I)
                        or re.fullmatch(r"tijdvak\s*\d{1,2}", line["text"], re.I)
                    )
                    footer_marker = (
                        len(line["text"]) <= 120
                        and bool(explicit_footer.search(line["text"]))
                    )
                    if footer_marker or standalone_page_number or page_counter:
                        candidates.append(line)

                # A footer candidate is safe only if no non-footer text or
                # visual object follows it. This protects the final content
                # line of a question (including the Vwo 2026-II 'overerft'
                # regression) even when a repeated body line looks footer-like.
                candidate_ids = {id(line) for line in candidates}
                footer_lines = []
                rejected_footer_lines = []
                for candidate in candidates:
                    content_after = any(
                        id(line) not in candidate_ids
                        and line["top"] > candidate["bottom"] + 1.0
                        for line in row["lines"]
                    )
                    visual_after = any(
                        asset[1] > candidate["bottom"] + 1.0
                        for asset in row["assets"]
                    )
                    if content_after or visual_after:
                        rejected_footer_lines.append(candidate)
                    else:
                        footer_lines.append(candidate)

                footer_top = min(
                    (line["top"] for line in footer_lines), default=None
                )
                footer_ids = {id(line) for line in footer_lines}
                body_lines = [
                    line for line in row["lines"] if id(line) not in footer_ids
                ]
                body_assets = [
                    asset for asset in row["assets"]
                    if footer_top is None or asset[1] < footer_top
                ]
                body_bottom = max(
                    (line["bottom"] for line in body_lines), default=0.0
                )
                body_bottom = max(
                    body_bottom,
                    max((asset[3] for asset in body_assets), default=0.0),
                )

                footer_conflict = (
                    footer_top is not None
                    and body_bottom + float(padding) >= footer_top
                )
                if footer_conflict:
                    # There is not enough whitespace between the final body
                    # element and the footer. Keep the complete page instead
                    # of shaving off the descenders or final line of a question.
                    rejected_footer_lines.extend(footer_lines)
                    footer_lines = []
                    footer_top = None
                    body_lines = list(row["lines"])
                    body_assets = list(row["assets"])
                    body_bottom = max(
                        max((line["bottom"] for line in body_lines), default=0.0),
                        max((asset[3] for asset in body_assets), default=0.0),
                    )
                    cutoff = height
                elif body_bottom <= 0:
                    # A blank or unextractable page is kept intact for review.
                    cutoff = height
                else:
                    cutoff = min(height, body_bottom + float(padding))

                target = preview.new_page(width=width, height=cutoff)
                clip = fitz.Rect(0, 0, width, cutoff)
                target.show_pdf_page(
                    target.rect, source, row["original_page"] - 1,
                    clip=clip, keep_proportion=False,
                )
                mapping.append({
                    "original_page": row["original_page"],
                    "preview_page": len(mapping) + 1,
                    "width": width,
                    "original_height": height,
                    "preview_height": cutoff,
                    "footer_detected": bool(footer_lines),
                    "footer_text": [line["text"] for line in footer_lines],
                    "footer_cutoff": footer_top,
                    "footer_candidates_rejected": [
                        line["text"] for line in rejected_footer_lines
                    ],
                    "footer_review_required": bool(rejected_footer_lines) or footer_conflict,
                    "last_content_bottom": body_bottom,
                })

            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.exists():
                output_path.unlink()
            preview.save(output_path, garbage=4, deflate=True)
        finally:
            preview.close()

        return {
            "path": str(output_path),
            "source_sha256": digest_file(source_path),
            "page_map": mapping,
            "removed_first_page": True,
            "method": "afgeleide preview; originele PDF ongewijzigd",
        }
    finally:
        source.close()

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


def render_composite_crops(
    pdf_path: Path,
    segments: list[dict],
    output: Path,
    scale: float = 1.5,
    gap: float = 12.0,
):
    """Render ordered PDF regions into one tall image without changing content."""
    import pymupdf as fitz
    if not segments:
        raise ValueError("Geen fragmentregio's opgegeven.")
    source = fitz.open(pdf_path)
    try:
        normalized = []
        width = 0.0
        total_height = 0.0
        for segment in segments:
            page_no = int(segment["page"])
            if not 1 <= page_no <= len(source):
                raise ValueError(f"Ongeldig PDF-paginanummer: {page_no}")
            rect = fitz.Rect(segment["bbox"])
            rect &= source[page_no - 1].rect
            if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                continue
            normalized.append((page_no - 1, rect))
            width = max(width, rect.width)
            total_height += rect.height
        total_height += float(gap) * max(0, len(normalized) - 1)
        if not normalized:
            raise ValueError("De opgegeven fragmenten bevatten geen zichtbaar paginagebied.")
        output_doc = fitz.open()
        try:
            target_page = output_doc.new_page(
                width=width, height=max(10.0, total_height)
            )
            y = 0.0
            for index, (page_index, clip) in enumerate(normalized):
                target = fitz.Rect(0, y, clip.width, y + clip.height)
                target_page.show_pdf_page(
                    target, source, page_index, clip=clip, keep_proportion=False
                )
                if index < len(normalized) - 1:
                    y += clip.height + float(gap)
            pix = target_page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), alpha=False
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            pix.save(output)
        finally:
            output_doc.close()
    finally:
        source.close()
    return output


def render_stitched_preview(
    preview_pdf_path: Path,
    output_path: Path,
    page_map: list[dict],
    scale: float = 1.05,
    gap: float = 12.0,
    max_height_px: int = 26000,
) -> dict:
    """Render all cleaned preview pages as one vertically stitched image.

    The layout maps every pixel band back to its original PDF page. If a very
    long exam would exceed a safe Tk image height, the scale is reduced while
    retaining the same page-relative coordinate mapping.
    """
    import pymupdf as fitz

    source = fitz.open(preview_pdf_path)
    try:
        segments = []
        layout = []
        total_points = 0.0
        for item in page_map:
            preview_page = int(item["preview_page"])
            if not 1 <= preview_page <= len(source):
                raise ValueError("De preview bevat een ongeldige paginakoppeling.")
            page = source[preview_page - 1]
            rect = page.rect
            segments.append({
                "page": preview_page,
                "bbox": [0.0, 0.0, float(rect.width), float(rect.height)],
            })
            total_points += float(rect.height)
        total_points += float(gap) * max(0, len(segments) - 1)
        if not segments:
            raise ValueError("Er zijn geen opgeschoonde examenpagina's om samen te voegen.")
        actual_scale = min(float(scale), float(max_height_px) / max(1.0, total_points))
        if actual_scale < 0.55:
            raise ValueError(
                "Dit examen bevat te veel pagina's voor één doorlopende afbeelding. "
                "Gebruik de paginaweergave of splits het document."
            )
        cursor = 0.0
        for item, segment in zip(page_map, segments):
            page = source[int(item["preview_page"]) - 1]
            page_height = float(page.rect.height)
            layout.append({
                "original_page": int(item["original_page"]),
                "preview_page": int(item["preview_page"]),
                "width": float(page.rect.width),
                "height": page_height,
                "y0": cursor * actual_scale,
                "y1": (cursor + page_height) * actual_scale,
                "scale": actual_scale,
            })
            cursor += page_height + float(gap)
    finally:
        source.close()

    render_composite_crops(
        preview_pdf_path, segments, output_path,
        scale=actual_scale, gap=gap,
    )
    return {
        "path": str(output_path),
        "layout": layout,
        "scale": actual_scale,
        "width_points": max(item["width"] for item in layout),
        "height_points": total_points,
    }

def question_pattern_key(candidate: dict) -> str:
    """Build a privacy-safe, normalized feature signature for reusable learning.

    Exact question text, question number, page and coordinates are deliberately
    excluded: they are exam-specific and would cause memorisation rather than learning.
    """
    line = re.sub(r"\s+", " ", str(candidate.get("line", "")).strip().lower())
    following = re.sub(r"\s+", " ", str(candidate.get("next_line", "")).strip().lower())
    standalone = bool(re.fullmatch(r"\d{1,2}[.)]?", line))
    inline = bool(re.match(r"^\d{1,2}[.)]\s+\S", line))
    points = bool(re.search(r"\b\d{1,2}\s*(?:p|pt|punt|punten)\b", following))
    cue_words = r"\b(verklaar|beschrijf|noem|geef|welk|welke|wat|wie|waar|waarom|waardoor|waarin|waarmee|wanneer|hoe|bereken|noteer|leg|toon|gebruik|kies|bepaal|licht toe|beargumenteer|leid af|selecteer)\b"
    cue = "instruction" if re.search(cue_words, line + " " + following, re.I) else "none"
    if re.match(r"^[a-h][.)]\s+", following):
        following_kind = "option"
    elif following and re.fullmatch(r"\d{1,2}\s*(?:p|pt|punt|punten)", following, re.I):
        following_kind = "points"
    elif following:
        following_kind = "text"
    else:
        following_kind = "empty"
    shape = "inline" if inline else "standalone" if standalone else "other"
    return f"qstart:v2:shape={shape}|cue={cue}|points={int(points)}|next={following_kind}"


def learn_decision(knowledge_dir: Path, decision: dict):
    """Append an auditable human decision; machine suggestions never become labels."""
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    path = knowledge_dir / "decisions.jsonl"
    record = {"created_at": datetime.now().astimezone().isoformat(timespec="seconds"), **decision}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_decisions(knowledge_dir: Path) -> list[dict]:
    path = knowledge_dir / "decisions.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except json.JSONDecodeError:
            # A truncated final line must not make the complete knowledge base unusable.
            continue
    return rows


def suggest_from_learning(knowledge_dir: Path, key: str) -> dict:
    """Suggest a label only after consistent evidence from independent exam PDFs.

    Decisions from one document count once. A minimum of three independent
    documents and 80% agreement are required; conflicting or weak evidence is
    exposed as such. The result is advice only and is never auto-applied.
    """
    latest_by_document = {}
    legacy_support = 0
    for decision in load_decisions(knowledge_dir):
        if decision.get("pattern_key") != key or decision.get("accepted") is not True:
            continue
        chosen = decision.get("chosen")
        if chosen not in {"question", "not_question"}:
            continue
        document_id = str(decision.get("document_id") or "")
        if not document_id:
            legacy_support += 1
            continue
        candidate_key = (
            document_id,
            str(decision.get("candidate_id") or decision.get("candidate_line") or ""),
            str(decision.get("page") or ""),
        )
        latest_by_document[candidate_key] = decision

    # Legacy records without a document identity are intentionally not allowed
    # to establish a reusable rule: they cannot prove independent exam support.
    per_document = {}
    for decision in latest_by_document.values():
        doc_id = str(decision.get("document_id"))
        per_document.setdefault(doc_id, []).append(decision.get("chosen"))
    votes = {"question": 0, "not_question": 0}
    for labels in per_document.values():
        # Multiple reviewed candidates in one exam contribute one exam-level vote.
        for label in set(labels):
            votes[label] += 1
    total = sum(votes.values())
    if total == 0:
        return {"suggestion": None, "support": 0, "document_support": 0,
                "confidence": 0.0, "conflicting": False, "auto_apply": False}
    winner = max(votes, key=votes.get)
    support = votes[winner]
    confidence = support / total
    enough_independent_evidence = support >= 3 and len(per_document) >= 3
    consistent = confidence >= 0.8
    suggestion = winner if enough_independent_evidence and consistent else None
    return {
        "suggestion": suggestion,
        "support": support,
        "document_support": len(per_document),
        "confidence": round(confidence, 3),
        "conflicting": not consistent,
        "legacy_records_ignored": legacy_support,
        "auto_apply": False,
    }

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

def build_consolidated_cv_pdf(entries: list[dict], snippets_dir: Path,
                               output_path: Path, metadata: dict | None = None) -> dict:
    """Create a derived, question-ordered CV PDF without changing source PDFs."""
    import io
    import pymupdf as fitz
    from PIL import Image

    if not entries:
        raise ValueError("Er zijn geen vraagfragmenten voor het geconsolideerde CV.")
    output_path=Path(output_path)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    result=fitz.open()
    labels={
        "ongewijzigd":"Ongewijzigd · oorspronkelijke beoordelingsinformatie",
        "toevoeging":"Toevoeging uit de officiële CV-aanvulling",
        "wijziging":"Gewijzigde beoordelingsinformatie uit de officiële aanvulling",
        "vervanging":"Geldende vervanging uit de officiële CV-aanvulling",
        "intrekking":"INGETROKKEN · oorspronkelijke beoordelingsinformatie niet meer toepassen",
    }
    try:
        for entry in sorted(entries,key=lambda item:int(item.get("question_number",0) or 0)):
            number=int(entry.get("question_number",0) or 0)
            change=entry.get("change_type") or "ongewijzigd"
            original=Path(snippets_dir)/str(entry.get("original_region_file") or "")
            if not original.is_file():
                raise ValueError(f"Vraag {number}: oorspronkelijk CV-fragment ontbreekt.")
            if change=="vervanging":
                components=[("Oorspronkelijke tekst · vervangen",original)]
            elif change=="intrekking":
                components=[(labels[change],original)]
            else:
                components=[(labels.get(change,"Oorspronkelijke beoordelingsinformatie"),original)]
            amendment_items=entry.get("amendment_regions") or []
            for amendment in amendment_items:
                amendment_path=Path(snippets_dir)/str(amendment.get("snippet_file") or "")
                if not amendment_path.is_file():
                    raise ValueError(f"Vraag {number}: CV-aanvullingsfragment ontbreekt.")
                if change=="vervanging":
                    amendment_label="GELDENDE VERVANGING"
                elif change=="intrekking":
                    amendment_label="Officiële intrekking / toelichting"
                elif change=="toevoeging":
                    amendment_label="Toegevoegde beoordelingsinformatie"
                else:
                    amendment_label="Aanvullende wijzigingsinformatie"
                components.append((amendment_label,amendment_path))
            if change=="vervanging" and len(components)==1:
                raise ValueError(f"Vraag {number}: vervanging is geclassificeerd, maar het vervangende fragment ontbreekt.")
            if change in ("toevoeging","wijziging") and len(components)==1:
                raise ValueError(f"Vraag {number}: wijziging is geclassificeerd, maar het aanvullingsfragment ontbreekt.")
            for component_label,image_path in components:
                with Image.open(image_path) as opened:
                    image=opened.convert("RGB")
                    width,height=image.size
                    max_slice_height=max(1,int(width*1.38))
                    slices=max(1,(height+max_slice_height-1)//max_slice_height)
                    for slice_index in range(slices):
                        top=slice_index*max_slice_height
                        bottom=min(height,top+max_slice_height)
                        crop=image.crop((0,top,width,bottom))
                        buffer=io.BytesIO()
                        crop.save(buffer,format="PNG")
                        image_bytes=buffer.getvalue()
                        page=result.new_page(width=595,height=842)
                        page.insert_text((34,30),f"Correctievoorschrift · vraag {number}",
                                         fontsize=14,fontname="helv")
                        page.insert_text((34,49),component_label,fontsize=9,fontname="helv")
                        available=fitz.Rect(34,62,561,805)
                        scale=min(available.width/crop.width,available.height/crop.height)
                        image_width=crop.width*scale
                        image_height=crop.height*scale
                        rect=fitz.Rect((595-image_width)/2,72,
                                       (595+image_width)/2,72+image_height)
                        page.insert_image(rect,stream=image_bytes,keep_proportion=True)
                        page.insert_text((34,826),
                            f"Bronfragment: {image_path.name} · deel {slice_index+1}/{slices}",
                            fontsize=7,fontname="helv")
                        crop.close()
                    image.close()
        meta=metadata or {}
        result.set_metadata({
            "title":f"Geconsolideerd correctievoorschrift {meta.get('level','')} {meta.get('year','')}",
            "author":"Examenverwerker",
            "subject":f"Tijdvak {meta.get('period','')} · afgeleid document",
            "keywords":"geconsolideerd correctievoorschrift; bronfragmenten; traceerbaarheid",
        })
        result.save(output_path,garbage=4,deflate=True)
    finally:
        result.close()
    return {"path":str(output_path),"sha256":digest_file(output_path),
            "page_count":len(fitz.open(output_path))}


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


def question_fragment_boundary(analysis: dict[str, Any], candidate: dict,
                                next_candidate: dict | None = None) -> tuple[int, float, str]:
    """Find the first blank-line or horizontal frame boundary after a question start.

    The next confirmed question start is a safety cap, not the primary boundary.
    Coordinates are returned in PDF points.
    """
    pages = {int(page["page"]): page for page in analysis.get("pages", [])}
    start_page = int(candidate.get("page", 1))
    start_bbox = candidate.get("bbox") or [0, 0, 0, 0]
    start_y = max(0.0, float(start_bbox[1]) - 2.0)
    cap_page = int(next_candidate["page"]) if next_candidate else max(pages, default=start_page)
    cap_y = float((next_candidate.get("bbox") or [0, 0, 0, 0])[1]) if next_candidate else None

    for page_no in range(start_page, cap_page + 1):
        page = pages.get(page_no)
        if not page:
            continue
        height = float(page.get("height", 0) or 0)
        width = float(page.get("width", 0) or 0)
        lines = []
        for block in page.get("blocks", []):
            for line in block.get("lines", []):
                bbox = line.get("bbox") or block.get("bbox") or [0, 0, 0, 0]
                if len(bbox) != 4 or not str(line.get("text", "")).strip():
                    continue
                y0, y1 = float(bbox[1]), float(bbox[3])
                if page_no == start_page and y1 <= start_y:
                    continue
                if page_no == cap_page and cap_y is not None and y0 >= cap_y:
                    continue
                lines.append((y0, y1))
        lines.sort()
        heights = sorted(max(1.0, bottom - top) for top, bottom in lines)
        median_height = heights[len(heights) // 2] if heights else 10.0
        blank_gap = max(9.0, median_height * 1.65)

        # A thin, page-wide vector line is treated as a printed frame divider.
        frame_ys = []
        for asset in page.get("visual_assets", []):
            if asset.get("kind") != "vector_region":
                continue
            x0, y0, x1, y1 = map(float, asset.get("bbox", [0, 0, 0, 0]))
            if width and (x1 - x0) >= width * 0.72 and 0.5 <= (y1 - y0) <= 6.0:
                if (page_no > start_page or y0 > start_y) and (
                    page_no < cap_page or cap_y is None or y0 < cap_y
                ):
                    frame_ys.append(y0)
        first_frame = min(frame_ys) if frame_ys else None

        previous_bottom = start_y if page_no == start_page else (
            lines[0][1] if lines else 0.0
        )
        for line_index, (line_top, line_bottom) in enumerate(lines):
            # Ignore the page's top margin: a new page is not itself a blank line.
            if page_no > start_page and line_index == 0:
                previous_bottom = line_bottom
                continue
            if line_top - previous_bottom >= blank_gap:
                boundary = (line_top + previous_bottom) / 2.0
                if first_frame is not None and first_frame < boundary:
                    return page_no, first_frame, "kader"
                return page_no, boundary, "witregel"
            previous_bottom = max(previous_bottom, line_bottom)
        if first_frame is not None:
            return page_no, first_frame, "kader"

    if next_candidate:
        return cap_page, max(0.0, cap_y or 0.0), "volgende_vraagstart"
    return max(pages, default=start_page), float(pages.get(max(pages, default=start_page), {}).get("height", 0.0)), "pagina-einde"


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
    """Detect question formats from selectable PDF text, including common layout/OCR variants.

    Option labels may be on separate lines, inline with other options, wrapped
    onto a following line, or extracted as lower-case labels. Two distinct
    option labels are required; a single incidental 'A.' is not enough.
    """
    value = str(text or "").replace("\u00a0", " ")
    normalized_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    options_by_label = {}
    inline_pattern = re.compile(
        r"(?<![A-Za-z0-9])(?:\(([A-Ha-h])\)|([A-Ha-h])[.):])\s*"
        r"(.+?)(?=(?<![A-Za-z0-9])(?:\([A-Ha-h]\)|[A-Ha-h][.):])\s*|$)"
    )

    def add_option(label: str, option_text: str):
        label = label.upper()
        option_text = re.sub(r"\s+", " ", option_text).strip(" \t:;")
        if label in "ABCDEFGH" and option_text and len(option_text) > 0:
            # Prefer the longest capture if the same label occurs in duplicate OCR lines.
            if label not in options_by_label or len(option_text) > len(options_by_label[label]):
                options_by_label[label] = option_text

    # 1) Conventional line-start forms: A. text, (A) text, A) text, A: text.
    line_option = re.compile(r"^\s*(?:\(([A-Ha-h])\)|([A-Ha-h])[.):])\s*(.*?)\s*$")
    standalone_label = re.compile(r"^\s*(?:\(([A-Ha-h])\)|([A-Ha-h])[.):]?)\s*$")
    for index, line in enumerate(normalized_lines):
        inline_matches = list(inline_pattern.finditer(line)) if "inline_pattern" in locals() else []
        if len(inline_matches) >= 2:
            for inline_match in inline_matches:
                add_option(inline_match.group(1) or inline_match.group(2), inline_match.group(3))
            continue
        match = line_option.match(line)
        if match and match.group(3):
            add_option(match.group(1) or match.group(2), match.group(3))
            continue
        label_match = standalone_label.match(line)
        if label_match:
            following = normalized_lines[index + 1] if index + 1 < len(normalized_lines) else ""
            if following and not standalone_label.match(following):
                add_option(label_match.group(1) or label_match.group(2), following)

    # 2) Inline extraction: some PDF text layers place A/B/C/D options on one line.
    # Require explicit punctuation and a plausible option body to avoid matching
    # ordinary capital letters in prose.
    for line in normalized_lines:
        matches = list(inline_pattern.finditer(line))
        if len(matches) >= 2:
            for match in matches:
                add_option(match.group(1) or match.group(2), match.group(3))

    # 3) OCR sometimes drops punctuation but keeps one option per line ("A mitochondria").
    # Only use this fallback when at least two consecutive labels are present.
    bare_options = []
    for line in normalized_lines:
        match = re.match(r"^\s*([A-Ha-h])\s{1,}(.{2,})$", line)
        if match:
            bare_options.append((match.group(1).upper(), match.group(2).strip()))
    if len(bare_options) >= 2:
        for label, option_text in bare_options:
            add_option(label, option_text)

    labels = sorted(options_by_label, key="ABCDEFGH".index)
    if len(labels) >= 2:
        options = [{"label": label, "text": options_by_label[label]} for label in labels]
        last_index = max("ABCDEFGH".index(label) for label in labels)
        expected = list("ABCDEFGH"[:last_index + 1])
        gaps = [label for label in expected if label not in labels]
        # Distinct labels are stored once; repeated source labels are still reported.
        source_labels = re.findall(
            r"(?im)^\s*(?:\(([A-Ha-h])\)|([A-Ha-h])[.):])\s+",
            value
        )
        seen_source = [a or b for a, b in source_labels]
        duplicates = sorted({label.upper() for label in seen_source
                             if seen_source.count(label) > 1})
        sequential = labels[0] == "A" and labels == expected
        confidence = 0.92 if sequential and len(labels) >= 3 else 0.78 if len(labels) >= 2 else 0.55
        return {
            "type": "meerkeuze",
            "subtype": "enkelvoudige_keuze",
            "options": options,
            "option_labels": labels,
            "options_complete": sequential and not duplicates,
            "option_gaps": gaps,
            "duplicate_option_labels": duplicates,
            "confidence": confidence,
            "status": "controle_nodig",
        }

    lowered = value.lower()
    if re.search(r"\b(juist|onjuist|waar|niet waar)\b", lowered) and re.search(r"\b(stelling|uitspraken|bewering)\b", lowered):
        qtype, subtype, confidence = "juist_onjuist", "stellingbeoordeling", 0.65
    elif re.search(r"\b(wel of niet|wel/niet|ja of nee|ja/nee)\b", lowered):
        qtype, subtype, confidence = "wel_niet", "binaire_beoordeling", 0.7
    else:
        qtype, subtype, confidence = "open", "open_vraag", 0.55
    return {
        "type": qtype, "subtype": subtype, "options": [], "option_labels": [],
        "options_complete": None, "option_gaps": [], "duplicate_option_labels": [],
        "confidence": confidence, "status": "controle_nodig",
    }



def detect_visual_answer_options(analysis: dict, candidate: dict, following: dict | None = None,
                                 question_text: str = "") -> dict:
    """Flag likely image-based answer alternatives without pretending to OCR them.

    Uses PDF image/vector geometry and nearby selectable A-H labels. It deliberately
    distinguishes strong visual-choice evidence from a generic question illustration.
    """
    pages = analysis.get("pages", [])
    first_page = int(candidate.get("page", 1) or 1)
    last_page = int(following.get("page", len(pages)) if following else len(pages))
    start_y = float((candidate.get("bbox") or [0, 0, 0, 0])[1])
    end_y = float((following.get("bbox") or [0, 0, 0, 0])[1]) if following else None
    prompt = str(question_text or "").lower()
    selection_language = bool(re.search(
        r"\b(kies|selecteer|welke|welk|juist antwoord|beste antwoord|"
        r"combinatie|antwoordalternatief|antwoordoptie)\b", prompt
    ))
    visual = []
    nearby_labels = set()
    for page_data in pages:
        page_no = int(page_data.get("page", 0) or 0)
        if page_no < first_page or page_no > last_page:
            continue
        page_height = float(page_data.get("height", 0) or 0)
        page_width = float(page_data.get("width", 0) or 0)
        if page_height <= 0 or page_width <= 0:
            continue
        low = start_y if page_no == first_page else 0.0
        high = end_y if following and page_no == last_page else page_height
        if high is None:
            high = page_height
        if high <= low:
            continue
        page_assets = []
        for asset in page_data.get("visual_assets", []):
            bbox = asset.get("bbox") or []
            if len(bbox) != 4:
                continue
            x0, y0, x1, y1 = map(float, bbox)
            overlap = max(0.0, min(y1, high) - max(y0, low))
            if overlap <= 0 or (x1 - x0) * (y1 - y0) < page_width * page_height * 0.003:
                continue
            item = {"page": page_no, "kind": asset.get("kind", "visual"),
                    "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                    "id": asset.get("id")}
            page_assets.append(item)
        if not page_assets:
            continue
        for block in page_data.get("blocks", []):
            for line in block.get("lines", []):
                text = str(line.get("text", "")).strip()
                label = re.match(r"^\(?([A-Ha-h])\)?[.):]?\s*$", text)
                if not label:
                    continue
                lb = line.get("bbox") or block.get("bbox") or []
                if len(lb) != 4:
                    continue
                lx, ly = float(lb[0]), float(lb[1])
                for asset in page_assets:
                    ax0, ay0, ax1, ay1 = asset["bbox"]
                    # Option labels are commonly immediately left of, or above,
                    # a diagram/photo; use a generous but page-relative tolerance.
                    near = (abs(ly - ay0) <= page_height * 0.07 and
                            (abs(lx - ax0) <= page_width * 0.16 or
                             abs(lx - ax1) <= page_width * 0.16))
                    if near:
                        nearby_labels.add(label.group(1).upper())
        visual.extend(page_assets)

    raster_count = sum(1 for item in visual if item["kind"] == "image")
    vector_count = sum(1 for item in visual if item["kind"] == "vector_region")
    labels = sorted(nearby_labels, key="ABCDEFGH".index)
    # Repeated raster choices are strong even if the labels are embedded as pixels.
    aligned_raster_choices = False
    raster = [x for x in visual if x["kind"] == "image"]
    for i, left in enumerate(raster):
        lx = (left["bbox"][0] + left["bbox"][2]) / 2
        ly = (left["bbox"][1] + left["bbox"][3]) / 2
        for right in raster[i + 1:]:
            rx = (right["bbox"][0] + right["bbox"][2]) / 2
            ry = (right["bbox"][1] + right["bbox"][3]) / 2
            if left["page"] == right["page"] and (
                abs(ly - ry) <= 0.08 * max(1.0, pages[left["page"] - 1]["height"]) or
                abs(lx - rx) <= 0.08 * max(1.0, pages[left["page"] - 1]["width"])
            ):
                aligned_raster_choices = True
                break
        if aligned_raster_choices:
            break

    strong = len(labels) >= 2 or aligned_raster_choices or (
        selection_language and (raster_count >= 1 or vector_count >= 3)
    )
    possible = not strong and bool(visual) and selection_language
    if strong:
        status = "waarschijnlijke_visuele_meerkeuze"
        qtype = "mogelijk_visuele_meerkeuze"
        confidence = 0.84 if len(labels) >= 2 or aligned_raster_choices else 0.72
    elif possible:
        status = "mogelijk_visuele_antwoordopties"
        qtype = "mogelijk_visuele_meerkeuze"
        confidence = 0.58
    elif visual:
        status = "visueel_materiaal_bij_vraag"
        qtype = "open_met_visueel_materiaal"
        confidence = 0.5
    else:
        status = "geen_visueel_antwoordmateriaal_gevonden"
        qtype = None
        confidence = 0.0
    return {
        "type": qtype, "status": status, "confidence": confidence,
        "visual_asset_count": len(visual), "raster_image_count": raster_count,
        "vector_region_count": vector_count, "nearby_option_labels": labels,
        "selection_language": selection_language,
        "evidence": visual[:20],
        "requires_visual_review": bool(visual),
    }


def classify_question_with_visuals(analysis: dict, candidate: dict,
                                   following: dict | None = None,
                                   question_text: str = "") -> dict:
    """Combine text-based classification with visual answer-option evidence."""
    result = detect_question_type(question_text)
    visual = detect_visual_answer_options(analysis, candidate, following, question_text)
    result["visual_detection"] = visual
    if visual["type"] == "mogelijk_visuele_meerkeuze":
        result["type"] = "mogelijk_visuele_meerkeuze"
        result["subtype"] = "afbeeldingsopties_controleren"
        result["confidence"] = max(float(result.get("confidence", 0)), visual["confidence"])
        result["status"] = "visuele_opties_handmatig_controleren"
    elif visual["type"] == "open_met_visueel_materiaal":
        result["visual_material_present"] = True
        result["visual_review_note"] = "Er staat beeldmateriaal bij deze vraag; controleer of dit context of antwoordopties zijn."
    return result

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
            page=source[page_no - 1]
            rect = fitz.Rect(segment["bbox"]) & page.rect
            text = page.get_text("text", clip=rect, sort=True).strip()
            if not text:
                # OCR is deliberately selective: only a manually selected region
                # with no usable embedded text triggers a page OCR attempt.
                for language in ("nld+eng","eng"):
                    try:
                        textpage=page.get_textpage_ocr(language=language,dpi=200,full=True)
                        text=page.get_text("text",clip=rect,textpage=textpage,sort=True).strip()
                        if text:
                            break
                    except Exception:
                        continue
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
