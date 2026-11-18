"""Safe, local export to the existing website JSON layout."""
from __future__ import annotations
import hashlib, json, shutil
from pathlib import Path
from datetime import datetime

REQUIRED=("id","level","year","period","n","points","page","theme","concept","end","focus","source","q","pdf","cv","questionType")

def sha256(path: Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def _copy_source(project_dir: Path, source_name: str, dest_dir: Path, dest_name: str|None=None):
    source=project_dir/"bronnen"/source_name
    if not source.is_file(): raise FileNotFoundError(f"Bronbestand ontbreekt: {source_name}")
    dest_dir.mkdir(parents=True,exist_ok=True)
    target=dest_dir/(dest_name or source.name)
    shutil.copy2(source,target)
    return target

def validate_review_records(records: list[dict], project_dir: Path) -> list[dict]:
    errors=[]
    seen=set()
    for i,r in enumerate(records):
        rid=r.get("id") or f"record-{i+1}"
        if r.get("approved_by_human") is not True:
            errors.append({"id":rid,"error":"niet_menselijk_goedgekeurd"})
        if r.get("status") not in ("goedgekeurd","approved"):
            errors.append({"id":rid,"error":"status_niet_goedgekeurd"})
        meta=r.get("exam",{})
        for field in ("level","year","period","points","theme","concept","end","focus","questionType"):
            if meta.get(field) in (None,""):
                errors.append({"id":rid,"error":f"examenmetadata_ontbreekt:{field}"})
        if meta.get("questionType") not in ("mcq","open"):
            errors.append({"id":rid,"error":"vraagtype_onbekend"})
        if not r.get("id"):
            errors.append({"id":rid,"error":"id_ontbreekt"})
        if r.get("number") is None or r.get("source_page") is None:
            errors.append({"id":rid,"error":"vraagnummer_of_bronpagina_ontbreekt"})
        if meta.get("questionType")=="mcq" and (not r.get("options") or not r.get("correct")):
            errors.append({"id":rid,"error":"meerkeuzeopties_of_correct_antwoord_ontbreekt"})
        if not r.get("source_pdf") or not (project_dir/"bronnen"/r["source_pdf"]).is_file():
            errors.append({"id":rid,"error":"opgavenbron_ontbreekt"})
        if not r.get("cv_pdf") or not (project_dir/"bronnen"/r["cv_pdf"]).is_file():
            errors.append({"id":rid,"error":"correctievoorschrift_ontbreekt"})
        if not r.get("snippet_file") or not (project_dir/"snippets"/r["snippet_file"]).is_file():
            errors.append({"id":rid,"error":"snippet_ontbreekt"})
        if not r.get("question_text"):
            errors.append({"id":rid,"error":"vraagtekst_ontbreekt"})
        if rid in seen: errors.append({"id":rid,"error":"dubbel_id"})
        seen.add(rid)
        for ref in r.get("uitwerkbijlagen",[]):
            if not (project_dir/"bronnen"/ref).is_file():
                errors.append({"id":rid,"error":f"uitwerkbijlage_ontbreekt:{ref}"})
    return errors

def export_approved_records(records: list[dict], project_dir: Path, output_dir: Path):
    errors=validate_review_records(records,project_dir)
    if errors: return {"ok":False,"errors":errors,"export_dir":None}
    if output_dir.exists() and any(output_dir.iterdir()):
        return {"ok":False,"errors":[{"error":"exportmap_is_niet_leeg","message":"Kies een nieuwe exportmap; bestaande bestanden worden nooit overschreven."}],"export_dir":None}
    output_dir.mkdir(parents=True,exist_ok=True)
    exam_dir=output_dir/"examens"; snippet_dir=output_dir/"exam-snippets"
    exam_dir.mkdir(); snippet_dir.mkdir()
    mcq=[]; opened=[]; manifest=[]
    for r in records:
        meta=r["exam"]
        source_name=r["source_pdf"]; cv_name=r["cv_pdf"]
        source_target=_copy_source(project_dir,source_name,exam_dir)
        cv_target=_copy_source(project_dir,cv_name,exam_dir)
        snippet_name=r["snippet_file"]
        shutil.copy2(project_dir/"snippets"/snippet_name,snippet_dir/snippet_name)
        row={"id":r["id"],"level":meta["level"],"year":str(meta["year"]),"period":str(meta["period"]),
             "n":int(r["number"]),"points":int(meta["points"]),"page":int(r["source_page"]),
             "theme":meta["theme"],"concept":meta["concept"],"end":meta["end"],
             "focus":meta["focus"],"source":r.get("source_context",""),"q":r["question_text"],
             "image":f"exam-snippets/{snippet_name}","images":[f"exam-snippets/{snippet_name}"],
             "pdf":f"examens/{source_target.name}","cv":f"examens/{cv_target.name}",
             "questionType":meta["questionType"]}
        if meta["questionType"]=="mcq":
            row["options"]=r.get("options",[])
            row["correct"]=r.get("correct")
            mcq.append(row)
        else:
            opened.append(row)
        appendix=[]
        for ref in r.get("uitwerkbijlagen",[]):
            dest=_copy_source(project_dir,ref,exam_dir)
            appendix.append({"file":f"examens/{dest.name}","sha256":sha256(dest)})
        manifest.append({"id":r["id"],"source_sha256":sha256(project_dir/"bronnen"/source_name),
                         "cv_sha256":sha256(project_dir/"bronnen"/cv_name),
                         "snippet_sha256":sha256(project_dir/"snippets"/snippet_name),
                         "uitwerkbijlagen":appendix,"human_approved":True})
    (output_dir/"exam-mcq.json").write_text(json.dumps(mcq,ensure_ascii=False,indent=2),encoding="utf-8")
    (output_dir/"exam-open.json").write_text(json.dumps(opened,ensure_ascii=False,indent=2),encoding="utf-8")
    (output_dir/"manifest.json").write_text(json.dumps({"schema":"biologie-publicatiepakket-v1",
        "created_at":datetime.now().astimezone().isoformat(timespec="seconds"),
        "question_count":len(mcq)+len(opened),"mcq_count":len(mcq),"open_count":len(opened),
        "records":manifest,"website_appendix_linking":"controleerbaar_meeleveren; websiteveld nog niet automatisch uitgebreid"},ensure_ascii=False,indent=2),encoding="utf-8")
    return {"ok":True,"errors":[],"export_dir":str(output_dir),"mcq":len(mcq),"open":len(opened)}
