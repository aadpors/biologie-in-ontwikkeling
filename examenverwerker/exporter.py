"""Safe, local export to the existing examenoefenen.html data contract."""
from __future__ import annotations
import hashlib, json, shutil
from pathlib import Path
from datetime import datetime
from engine import infer_exam_metadata, review_checklist_errors
from structure import make_page_span, validate_cv_fragment

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
        if r.get("exam_structure_invalidated") is True:
            errors.append({"id":rid,"error":"vraag_contextstructuur_gewijzigd_record_opnieuw_samenstellen"})
        if r.get("cv_region_invalidated") is True:
            errors.append({"id":rid,"error":"cv_regio_gewijzigd_record_opnieuw_samenstellen"})
        # Publication requires source-faithful manual regions, not only the old
        # automatically proposed question/CV snippets.
        source_name = r.get("source_pdf", "")
        try:
            structure_question_number = int(r.get("exam_structure_question_number", -1))
        except (TypeError, ValueError):
            structure_question_number = -1
        if (r.get("exam_structure_status") != "gekoppeld" or not r.get("exam_structure_document_id")
                or not r.get("exam_structure_source_sha256") or not r.get("question_region_fragment_id")
                or structure_question_number != int(r.get("number", 0))
                or r.get("question_region_fragment_id") not in r.get("exam_structure_fragment_ids", [])):
            errors.append({"id":rid,"error":"handmatige_vraagafbakening_ontbreekt"})
        elif Path(str(source_name)).name != source_name:
            errors.append({"id":rid,"error":"ongeldig_opgavenbronpad"})
        elif source_name and (project_dir/"bronnen"/source_name).is_file():
            if sha256(project_dir/"bronnen"/source_name) != r.get("exam_structure_source_sha256"):
                errors.append({"id":rid,"error":"vraagafbakening_bronbestand_gewijzigd"})
        spans = r.get("question_region_page_spans", [])
        if not spans:
            errors.append({"id":rid,"error":"vraagfragment_paginagrenzen_ontbreken"})
        previous_page = 0
        for span in spans:
            try:
                clean = make_page_span(span["page"], span["top"], span["bottom"])
                if clean["page"] <= previous_page:
                    errors.append({"id":rid,"error":"vraagfragment_paginagrenzen_niet_oplopend"})
                previous_page = clean["page"]
            except (KeyError, TypeError, ValueError):
                errors.append({"id":rid,"error":"vraagfragment_paginagrens_ongeldig"})
        cv_region = r.get("cv_source_region")
        if not isinstance(cv_region, dict):
            errors.append({"id":rid,"error":"cv_handmatige_afbakening_ontbreekt"})
        else:
            cv_identity = {"id":r.get("cv_source_document_id"),"sha256":r.get("cv_source_sha256")}
            for region_error in validate_cv_fragment(cv_region, cv_identity, r.get("number", 0), "correctievoorschrift"):
                errors.append({"id":rid,"error":region_error})
            cv_file = r.get("cv_pdf", "")
            if cv_file and Path(str(cv_file)).name == cv_file and (project_dir/"bronnen"/cv_file).is_file() and sha256(project_dir/"bronnen"/cv_file) != r.get("cv_source_sha256"):
                errors.append({"id":rid,"error":"cv_afbakening_bronbestand_gewijzigd"})
        cv_region_file = r.get("cv_source_region_file")
        if not cv_region_file or Path(str(cv_region_file)).name != cv_region_file or not (project_dir/"snippets"/str(cv_region_file)).is_file():
            errors.append({"id":rid,"error":"cv_handmatige_uitsnede_ontbreekt"})
        elif not r.get("cv_source_region_sha256") or sha256(project_dir/"snippets"/cv_region_file) != r.get("cv_source_region_sha256"):
            errors.append({"id":rid,"error":"cv_handmatige_uitsnede_hash_afwijkend"})
        selected_addenda = set(r.get("cv_amendment_pdfs", []))
        addendum_regions = r.get("cv_amendment_regions", [])
        covered_addenda = set()
        for item in addendum_regions:
            region = item.get("fragment", {})
            identity = {"id":item.get("document_id"),"sha256":item.get("source_sha256")}
            for region_error in validate_cv_fragment(region, identity, r.get("number", 0), "aanvulling"):
                errors.append({"id":rid,"error":region_error})
            covered_addenda.add(item.get("source_pdf"))
            snippet = item.get("snippet_file", "")
            if not snippet or Path(str(snippet)).name != snippet or not (project_dir/"snippets"/str(snippet)).is_file():
                errors.append({"id":rid,"error":"cv_aanvulling_handmatige_uitsnede_ontbreekt"})
            elif not item.get("snippet_sha256") or sha256(project_dir/"snippets"/snippet) != item.get("snippet_sha256"):
                errors.append({"id":rid,"error":"cv_aanvulling_uitsnede_hash_afwijkend"})
            source_name = str(item.get("source_pdf", ""))
            source = project_dir/"bronnen"/source_name if Path(source_name).name == source_name else None
            if source is None or not source.is_file() or sha256(source) != item.get("source_sha256"):
                errors.append({"id":rid,"error":"cv_aanvulling_afbakening_bronbestand_gewijzigd"})
        if selected_addenda - covered_addenda:
            errors.append({"id":rid,"error":"niet_alle_geselecteerde_cv_aanvullingen_visueel_afgebakend"})
        declared_amendment_snippets = sorted(r.get("cv_amendment_snippet_files", []))
        region_amendment_snippets = sorted(x.get("snippet_file", "") for x in addendum_regions)
        if declared_amendment_snippets != region_amendment_snippets:
            errors.append({"id":rid,"error":"cv_aanvulling_snippets_komen_niet_overeen_met_afgebakende_regios"})
        for asset in r.get("context_asset_files", []):
            name = asset.get("file", "")
            if not name or Path(str(name)).name != name or not (project_dir/"snippets"/str(name)).is_file():
                errors.append({"id":rid,"error":"contextuitsnede_ontbreekt"})
            if asset.get("source_document_id") and asset.get("source_document_id") != r.get("exam_structure_document_id"):
                errors.append({"id":rid,"error":"contextuitsnede_verkeerde_bron"})
            if asset.get("source_sha256") and asset.get("source_sha256") != r.get("exam_structure_source_sha256"):
                errors.append({"id":rid,"error":"contextuitsnede_bronhash_afwijkend"})
            if asset.get("asset_id") and asset.get("caption_human_confirmed") is not True:
                errors.append({"id":rid,"error":"contextbijschrift_niet_handmatig_bevestigd"})
            if asset.get("crop_method") in ("handmatige_rechthoek_op_originele_pdf", "handmatige_paginabrede_strook_op_originele_pdf"):
                bbox = asset.get("bbox")
                try:
                    coords = [float(x) for x in bbox]
                    page_no = int(asset.get("page", 0))
                    valid_bbox = (len(coords) == 4 and page_no >= 1 and
                                  coords[0] >= 0 and coords[1] >= 0 and
                                  coords[2] > coords[0] and coords[3] > coords[1])
                except (TypeError, ValueError):
                    valid_bbox = False
                if asset.get("crop_method") == "handmatige_paginabrede_strook_op_originele_pdf":
                    try:
                        page_width = float(asset.get("page_size", [])[0])
                        valid_bbox = valid_bbox and abs(coords[0]) <= 0.01 and abs(coords[2] - page_width) <= 0.01
                    except (TypeError, ValueError, IndexError):
                        valid_bbox = False
                if not valid_bbox:
                    errors.append({"id":rid,"error":"handmatige_contextuitsnede_geometrie_ongeldig"})
                if (asset.get("source_document_id") != r.get("exam_structure_document_id")
                        or asset.get("source_sha256") != r.get("exam_structure_source_sha256")
                        or not asset.get("source_pdf") or Path(str(asset.get("source_pdf"))).name != asset.get("source_pdf")
                        or asset.get("source_pdf") != r.get("source_pdf")):
                    errors.append({"id":rid,"error":"handmatige_contextuitsnede_herkomst_ontbreekt"})
                try:
                    asset_question_number = int(asset.get("question_number", -1))
                except (TypeError, ValueError):
                    asset_question_number = -1
                if asset_question_number != int(r.get("number", 0)):
                    errors.append({"id":rid,"error":"handmatige_contextuitsnede_verkeerd_vraagnummer"})
                if (asset.get("fragment_id") is not None
                        and asset.get("fragment_id") not in r.get("exam_structure_fragment_ids", [])):
                    errors.append({"id":rid,"error":"handmatige_contextuitsnede_verkeerd_contextfragment"})
            if name and (project_dir/"snippets"/str(name)).is_file():
                if not asset.get("snippet_sha256") or sha256(project_dir/"snippets"/str(name)) != asset.get("snippet_sha256"):
                    errors.append({"id":rid,"error":"contextuitsnede_hash_afwijkend"})
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
        if len(snippets) != 1 or snippets[0] != r.get("snippet_file"):
            errors.append({"id":rid,"error":"vraagfragment_bestanden_niet_eenduidig"})
        if snippets and Path(str(snippets[0])).name == snippets[0] and (project_dir/"snippets"/snippets[0]).is_file():
            expected_question_hash = r.get("question_region_snippet_sha256")
            if not expected_question_hash or sha256(project_dir/"snippets"/snippets[0]) != expected_question_hash:
                errors.append({"id":rid,"error":"vraagfragment_render_hash_afwijkend"})
        for name in snippets:
            if Path(name).name!=name:
                errors.append({"id":rid,"error":"ongeldig_snippetpad"})
            elif not (project_dir/"snippets"/name).is_file(): errors.append({"id":rid,"error":f"snippet_ontbreekt:{name}"})
        if meta.get("questionType")=="open":
            cv_snippets=r.get("cv_snippet_files") or ([r["cv_snippet_file"]] if r.get("cv_snippet_file") else [])
            if len(cv_snippets)!=1:
                errors.append({"id":rid,"error":"exact_een_cv_snippet_verplicht_voor_huidige_website"})
            if len(cv_snippets)==1 and cv_snippets[0] != cv_region_file:
                errors.append({"id":rid,"error":"website_cv_snippet_is_niet_de_handmatig_afgebakende_regio"})
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
        context_assets = r.get("context_asset_files", [])
        context_image_paths = []
        for asset in context_assets:
            name = asset["file"]
            if name not in [Path(x).name for x in context_image_paths]:
                shutil.copy2(project_dir/"snippets"/name, snippet_dir/name)
                context_image_paths.append(f"exam-snippets/{name}")
        cv_region_file = r.get("cv_source_region_file")
        if cv_region_file and cv_region_file not in snippet_names:
            shutil.copy2(project_dir/"snippets"/cv_region_file, snippet_dir/cv_region_file)
        amendment_files = list(r.get("cv_amendment_snippet_files") or
                               ([r["cv_amendment_snippet_file"]] if r.get("cv_amendment_snippet_file") else []))
        for amendment_file in amendment_files:
            if amendment_file not in snippet_names and amendment_file != cv_region_file:
                shutil.copy2(project_dir/"snippets"/amendment_file, snippet_dir/amendment_file)
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
        # The current website consumes only "image" and "images" from
        # exam-contexts.json. Preserve its established order: context assets
        # first, the question crop last (the last image is labelled as the
        # original question in examenoefenen.html).
        question_image_paths = [f"exam-snippets/{name}" for name in snippet_names]
        website_image_paths = context_image_paths + question_image_paths
        contexts.append({"level":meta["level"],"year":str(meta["year"]),"period":str(meta["period"]),
                         "n":int(r["number"]),"page":int(r["source_page"]),
                         "image":website_image_paths[0] if website_image_paths else "",
                         "images":website_image_paths,
                         "contextImages":context_image_paths,
                         "contextAssets":[{"image":f"exam-snippets/{x['file']}","caption":x.get("caption"),
                             "page":x.get("page"),"asset_id":x.get("asset_id"),"asset_kind":x.get("asset_kind"),"type":x.get("type"),
                             "fragment_id":x.get("fragment_id"),"question_number":x.get("question_number"),"crop_method":x.get("crop_method")} for x in context_assets],
                         "contextRegions":r.get("context_region_fragments", []),
                         "contextText":r.get("source_context", ""),
                         "questionImage":row["image"],"questionImages":row["images"]})
        if meta["questionType"]=="mcq":
            row["options"]=r["options"]; row["correct"]=r["correct"]; mcq.append(row)
        else:
            opened.append(row)
            cv_name_snippet=(r.get("cv_snippet_files") or [r["cv_snippet_file"]])[0]
            if cv_name_snippet != cv_region_file:
                shutil.copy2(project_dir/"snippets"/cv_name_snippet,snippet_dir/cv_name_snippet)
            cv_item={"id":r["id"],"question":int(r["number"]),"pdf":f"examens/{cv_target.name}","output":cv_name_snippet}
            if amendment_files:
                cv_item["amendment_output"]=amendment_files[0]
                cv_item["amendment_outputs"]=amendment_files
            cv_manifest.append(cv_item)
        manifest.append({"id":r["id"],"source_sha256":sha256(project_dir/"bronnen"/source_name),
                         "cv_sha256":sha256(project_dir/"bronnen"/cv_name),
                         "snippet_sha256":[sha256(project_dir/"snippets"/name) for name in snippet_names],
                         "cv_snippet_sha256":sha256(project_dir/"snippets"/(r.get("cv_snippet_files") or [r.get("cv_snippet_file")])[0]) if meta["questionType"]=="open" else None,
                         "cv_amendment_snippet_sha256":sha256(project_dir/"snippets"/r["cv_amendment_snippet_file"]) if r.get("cv_amendment_snippet_file") else None,
                         "cv_amendment_snippet_sha256s":[sha256(project_dir/"snippets"/name) for name in amendment_files],
                         "uitwerkbijlagen":[{"file":name,"sha256":sha256(output_dir/name)} for name in appendix],
                         "cv_amendment_pdfs":[{"file":name,"sha256":sha256(output_dir/name)} for name in cv_amendments],
                         "human_approved":True,
                         "exam_structure_status":r.get("exam_structure_status", "structuur_niet_ingesteld"),
                         "exam_structure_document_id":r.get("exam_structure_document_id"),
                         "question_region_fragment_id":r.get("question_region_fragment_id"),
                         "exam_structure_question_number":r.get("exam_structure_question_number"),
                         "exam_structure_fragment_ids":r.get("exam_structure_fragment_ids", []),
                         "question_region_page_spans":r.get("question_region_page_spans", []),
                         "context_region_fragments":r.get("context_region_fragments", []),
                         "context_asset_files":[{"file":x["file"],"sha256":sha256(project_dir/"snippets"/x["file"]),
                             "asset_id":x.get("asset_id"),"asset_kind":x.get("asset_kind"),"caption":x.get("caption"),"page":x.get("page"),
                             "fragment_id":x.get("fragment_id"),"type":x.get("type"),"source_document_id":x.get("source_document_id"),
                             "source_sha256":x.get("source_sha256"),"source_pdf":x.get("source_pdf"),"bbox":x.get("bbox"),
                             "snippet_sha256":x.get("snippet_sha256"),"caption_human_confirmed":x.get("caption_human_confirmed", False),"question_number":x.get("question_number"),"crop_method":x.get("crop_method")} for x in context_assets],
                         "cv_source_region":r.get("cv_source_region"),
                         "cv_source_region_sha256":sha256(project_dir/"snippets"/cv_region_file) if cv_region_file else None,
                         "cv_amendment_regions":r.get("cv_amendment_regions", [])})
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
