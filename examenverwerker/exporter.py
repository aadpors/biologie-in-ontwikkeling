"""Safe, local export to the existing examenoefenen.html data contract."""
from __future__ import annotations
import hashlib, json, shutil
from pathlib import Path
from datetime import datetime
from engine import infer_exam_metadata, review_checklist_errors

def sha256(path: Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def _copy_source(project_dir: Path, source_name: str, dest_dir: Path):
    if Path(source_name).name!=source_name: raise ValueError("Ongeldig bronbestandspad.")
    source=project_dir/"bronnen"/source_name
    if not source.is_file(): raise FileNotFoundError(f"Bronbestand ontbreekt: {source_name}")
    dest_dir.mkdir(parents=True,exist_ok=True)
    target=dest_dir/source.name
    if target.exists() and sha256(target)!=sha256(source):
        raise FileExistsError(f"Bestandsnaamconflict in exportmap: {target.name}")
    if not target.exists(): shutil.copy2(source,target)
    return target

def validate_review_records(records: list[dict], project_dir: Path) -> list[dict]:
    errors=[]; seen=set()
    for i,r in enumerate(records):
        rid=r.get("id") or f"record-{i+1}"
        if r.get("approved_by_human") is not True: errors.append({"id":rid,"error":"niet_menselijk_goedgekeurd"})
        if r.get("status") not in ("goedgekeurd","approved"): errors.append({"id":rid,"error":"status_niet_goedgekeurd"})
        for review_error in review_checklist_errors(r,r.get("record_review_checklist",{})):
            errors.append({"id":rid,"error":review_error})
        if r.get("source_analysis_invalidated") is True:
            errors.append({"id":rid,"error":"bron_analyse_verouderd"})
        meta=r.get("exam",{})
        for field in ("level","year","period","points","theme","concept","end","focus","questionType"):
            if meta.get(field) in (None,""): errors.append({"id":rid,"error":f"examenmetadata_ontbreekt:{field}"})
        if meta.get("questionType") not in ("mcq","open"): errors.append({"id":rid,"error":"vraagtype_onbekend"})
        if meta.get("level") not in ("Havo","Vwo"): errors.append({"id":rid,"error":"niveau_onbekend"})
        if not str(meta.get("year","")).isdigit() or len(str(meta.get("year","")))!=4: errors.append({"id":rid,"error":"jaartal_ongeldig"})
        if str(meta.get("period")) not in ("1","2","3"): errors.append({"id":rid,"error":"tijdvak_ongeldig"})
        try:
            if int(meta.get("points",-1)) < 0: raise ValueError()
        except (TypeError,ValueError): errors.append({"id":rid,"error":"puntenaantal_ongeldig"})
        if not r.get("id"): errors.append({"id":rid,"error":"id_ontbreekt"})
        if not isinstance(r.get("number"),int) or r["number"]<1 or not isinstance(r.get("source_page"),int) or r["source_page"]<1:
            errors.append({"id":rid,"error":"vraagnummer_of_bronpagina_ongeldig"})
        if meta.get("questionType")=="mcq":
            options=r.get("options") or []
            keys=[str(o.get("key","")).upper() for o in options if isinstance(o,dict)]
            if (not isinstance(options,list) or len(options)<2 or len(keys)!=len(options)
                or len(set(keys))!=len(keys) or any(k not in "ABCDEFGH" or len(k)!=1 for k in keys)
                or any(not str(o.get("text","")).strip() for o in options if isinstance(o,dict))
                or str(r.get("correct","")).upper() not in keys):
                errors.append({"id":rid,"error":"meerkeuzeopties_of_correct_antwoord_ongeldig"})
        expected={"level":meta.get("level"),"year":str(meta.get("year")),"period":str(meta.get("period"))}
        source_identity=infer_exam_metadata(str(r.get("source_pdf","")))
        cv_identity=infer_exam_metadata(str(r.get("cv_pdf","")))
        for label,identity,confirmation_flag in (
            ("opgavenbron",source_identity,"source_match_human_confirmed"),
            ("correctievoorschrift",cv_identity,"cv_match_human_confirmed")
        ):
            if identity:
                actual={"level":identity.get("level"),"year":str(identity.get("year")),"period":str(identity.get("period"))}
                if actual!=expected and r.get(confirmation_flag) is not True:
                    errors.append({"id":rid,"error":f"{label}_past_niet_bij_examen"})
            elif r.get(confirmation_flag) is not True:
                errors.append({"id":rid,"error":f"{label}_niet_handmatig_gecontroleerd"})
        for field,label in (("source_pdf","opgavenbron_ontbreekt"),("cv_pdf","correctievoorschrift_ontbreekt")):
            if not r.get(field) or Path(str(r.get(field,""))).name!=r.get(field) or not (project_dir/"bronnen"/r[field]).is_file(): errors.append({"id":rid,"error":label})
        snippets=r.get("snippet_files") or ([r["snippet_file"]] if r.get("snippet_file") else [])
        if not snippets: errors.append({"id":rid,"error":"snippet_ontbreekt"})
        for name in snippets:
            if Path(name).name!=name:
                errors.append({"id":rid,"error":"ongeldig_snippetpad"})
            elif not (project_dir/"snippets"/name).is_file(): errors.append({"id":rid,"error":f"snippet_ontbreekt:{name}"})
        if meta.get("questionType")=="open":
            cv_snippets=r.get("cv_snippet_files") or ([r["cv_snippet_file"]] if r.get("cv_snippet_file") else [])
            if len(cv_snippets)!=1:
                errors.append({"id":rid,"error":"exact_een_cv_snippet_verplicht_voor_huidige_website"})
            for name in cv_snippets:
                if Path(name).name!=name: errors.append({"id":rid,"error":"ongeldig_cv_snippetpad"})
                elif not (project_dir/"snippets"/name).is_file(): errors.append({"id":rid,"error":f"cv_snippet_ontbreekt:{name}"})
        amendment=r.get("cv_amendment_snippet_file")
        if amendment and (Path(amendment).name!=amendment or not (project_dir/"snippets"/amendment).is_file()): errors.append({"id":rid,"error":"cv_aanvulling_snippet_ontbreekt"})
        if not r.get("question_text"): errors.append({"id":rid,"error":"vraagtekst_ontbreekt"})
        if rid in seen: errors.append({"id":rid,"error":"dubbel_id"})
        seen.add(rid)
        for ref in r.get("uitwerkbijlagen",[]):
            if Path(ref).name!=ref:
                errors.append({"id":rid,"error":"ongeldig_bijlagepad"})
            elif not (project_dir/"bronnen"/ref).is_file():
                errors.append({"id":rid,"error":f"uitwerkbijlage_ontbreekt:{ref}"})
            else:
                identity=infer_exam_metadata(ref)
                if identity and (identity.get("level")!=meta.get("level") or str(identity.get("year"))!=str(meta.get("year")) or str(identity.get("period"))!=str(meta.get("period"))) and r.get("appendix_match_human_confirmed") is not True:
                    errors.append({"id":rid,"error":f"uitwerkbijlage_past_niet_bij_examen:{ref}"})
                elif not identity and r.get("appendix_match_human_confirmed") is not True:
                    errors.append({"id":rid,"error":f"uitwerkbijlage_niet_handmatig_gecontroleerd:{ref}"})
        for ref in r.get("cv_amendment_pdfs",[]):
            if Path(ref).name!=ref:
                errors.append({"id":rid,"error":"ongeldig_aanvullingpad"})
            elif not (project_dir/"bronnen"/ref).is_file():
                errors.append({"id":rid,"error":f"cv_aanvulling_pdf_ontbreekt:{ref}"})
            else:
                identity=infer_exam_metadata(ref)
                if identity and (identity.get("level")!=meta.get("level") or str(identity.get("year"))!=str(meta.get("year")) or str(identity.get("period"))!=str(meta.get("period"))) and r.get("cv_amendment_match_human_confirmed") is not True:
                    errors.append({"id":rid,"error":f"cv_aanvulling_past_niet_bij_examen:{ref}"})
                elif not identity and r.get("cv_amendment_match_human_confirmed") is not True:
                    errors.append({"id":rid,"error":f"cv_aanvulling_niet_handmatig_gecontroleerd:{ref}"})
    return errors

def export_approved_records(records: list[dict], project_dir: Path, output_dir: Path):
    errors=validate_review_records(records,project_dir)
    if errors: return {"ok":False,"errors":errors,"export_dir":None}
    if output_dir.exists() and any(output_dir.iterdir()):
        return {"ok":False,"errors":[{"error":"exportmap_is_niet_leeg","message":"Kies een nieuwe exportmap; bestaande bestanden worden nooit overschreven."}],"export_dir":None}
    output_dir.mkdir(parents=True,exist_ok=True)
    exam_dir=output_dir/"examens"; snippet_dir=output_dir/"exam-snippets"
    exam_dir.mkdir(); snippet_dir.mkdir()
    mcq=[]; opened=[]; contexts=[]; cv_manifest=[]; manifest=[]
    for r in records:
        meta=r["exam"]; source_name=r["source_pdf"]; cv_name=r["cv_pdf"]
        source_target=_copy_source(project_dir,source_name,exam_dir)
        cv_target=_copy_source(project_dir,cv_name,exam_dir)
        snippet_names=r.get("snippet_files") or [r["snippet_file"]]
        for name in snippet_names:
            shutil.copy2(project_dir/"snippets"/name,snippet_dir/name)
        row={"id":r["id"],"level":meta["level"],"year":str(meta["year"]),"period":str(meta["period"]),
             "n":int(r["number"]),"points":int(meta["points"]),"page":int(r["source_page"]),
             "theme":meta["theme"],"concept":meta["concept"],"end":meta["end"],"focus":meta["focus"],
             "source":r.get("source_context",""),"q":r["question_text"],
             "image":f"exam-snippets/{snippet_names[0]}","images":[f"exam-snippets/{name}" for name in snippet_names],
             "pdf":f"examens/{source_target.name}","cv":f"examens/{cv_target.name}","questionType":meta["questionType"]}
        appendix=[]
        for ref in r.get("uitwerkbijlagen",[]):
            dest=_copy_source(project_dir,ref,exam_dir)
            appendix.append(f"examens/{dest.name}")
        cv_amendments=[]
        for ref in r.get("cv_amendment_pdfs",[]):
            dest=_copy_source(project_dir,ref,exam_dir)
            cv_amendments.append(f"examens/{dest.name}")
        if appendix: row["attachmentPdfs"]=appendix
        contexts.append({"level":meta["level"],"year":str(meta["year"]),"period":str(meta["period"]),
                         "n":int(r["number"]),"page":int(r["source_page"]),
                         "image":row["image"],"images":row["images"]})
        if meta["questionType"]=="mcq":
            row["options"]=r["options"]; row["correct"]=r["correct"]; mcq.append(row)
        else:
            opened.append(row)
            cv_name_snippet=(r.get("cv_snippet_files") or [r["cv_snippet_file"]])[0]
            shutil.copy2(project_dir/"snippets"/cv_name_snippet,snippet_dir/cv_name_snippet)
            cv_item={"id":r["id"],"question":int(r["number"]),"pdf":f"examens/{cv_target.name}","output":cv_name_snippet}
            amendment=r.get("cv_amendment_snippet_file")
            if amendment:
                shutil.copy2(project_dir/"snippets"/amendment,snippet_dir/amendment)
                cv_item["amendment_output"]=amendment
            cv_manifest.append(cv_item)
        manifest.append({"id":r["id"],"source_sha256":sha256(project_dir/"bronnen"/source_name),
                         "cv_sha256":sha256(project_dir/"bronnen"/cv_name),
                         "snippet_sha256":[sha256(project_dir/"snippets"/name) for name in snippet_names],
                         "cv_snippet_sha256":sha256(project_dir/"snippets"/(r.get("cv_snippet_files") or [r.get("cv_snippet_file")])[0]) if meta["questionType"]=="open" else None,
                         "cv_amendment_snippet_sha256":sha256(project_dir/"snippets"/r["cv_amendment_snippet_file"]) if r.get("cv_amendment_snippet_file") else None,
                         "uitwerkbijlagen":[{"file":name,"sha256":sha256(output_dir/name)} for name in appendix],
                         "cv_amendment_pdfs":[{"file":name,"sha256":sha256(output_dir/name)} for name in cv_amendments],
                         "human_approved":True})
    (output_dir/"exam-mcq.json").write_text(json.dumps(mcq,ensure_ascii=False,indent=2),encoding="utf-8")
    (output_dir/"exam-open.json").write_text(json.dumps(opened,ensure_ascii=False,indent=2),encoding="utf-8")
    (output_dir/"exam-contexts.json").write_text(json.dumps(contexts,ensure_ascii=False,indent=2),encoding="utf-8")
    (output_dir/"scripts").mkdir(exist_ok=True)
    (output_dir/"scripts"/"cv-snippets.json").write_text(json.dumps(cv_manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    (output_dir/"manifest.json").write_text(json.dumps({"schema":"biologie-publicatiepakket-v1",
        "created_at":datetime.now().astimezone().isoformat(timespec="seconds"),
        "question_count":len(mcq)+len(opened),"mcq_count":len(mcq),"open_count":len(opened),
        "records":manifest},ensure_ascii=False,indent=2),encoding="utf-8")
    return {"ok":True,"errors":[],"export_dir":str(output_dir),"mcq":len(mcq),"open":len(opened)}
