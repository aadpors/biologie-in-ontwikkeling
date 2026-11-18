"""Benchmark PDF question candidates against source PDFs and independent CV anchors."""
from __future__ import annotations
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import analyze_pdf, detect_question_candidates, detect_cv_question_numbers, compare_question_numbering
ROOT=Path(__file__).resolve().parents[2]
PDF_DIR=ROOT/"examens"
OUT=Path(__file__).resolve().parents[1]/"artifacts"/"exam-analysis-report.json"
PATTERN=re.compile(r"^(ha|vw)-1018-a-(\d{2})-(\d+)-o(?:-|\.pdf)",re.I)
def main():
    # Windows runners and portable consoles may use legacy code pages (e.g. cp1252).
    # Diagnostic text from source PDFs must never abort the benchmark on Unicode glyphs.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if not PDF_DIR.is_dir(): raise SystemExit(f"Examensmap niet gevonden: {PDF_DIR}")
    rows=[]; failures=[]; warnings=[]
    for path in sorted(PDF_DIR.glob("*.pdf")):
        try:
            analysis=analyze_pdf(path)
            text_pages=sum(bool(p["text"].strip()) for p in analysis["pages"])
            item={"file":path.name,"pages":analysis["page_count"],"pages_with_text":text_pages,"ocr_required":text_pages==0,"sha256":analysis["sha256"],"role":"other","candidate_count":None}
            match=PATTERN.match(path.name)
            if match:
                key=(match.group(1).lower(),match.group(2),match.group(3))
                candidates=detect_question_candidates(analysis)
                cv_name=re.sub(r"-o(?:-spr)?\.pdf$","-c.pdf",path.name,flags=re.I)
                cv_matches=[p for p in PDF_DIR.glob("*.pdf") if p.name.lower()==cv_name.lower()]
                cv_path=cv_matches[0] if cv_matches else None
                cv_result=None
                if cv_path and cv_path.is_file():
                    cv_analysis=analyze_pdf(cv_path)
                    cv_candidates=detect_cv_question_numbers(cv_analysis)
                    cv_result=compare_question_numbering(candidates,cv_candidates)
                    cv_result["cv_file"]=cv_path.name
                    cv_result["cv_candidate_details"]=cv_candidates
                    cv_all_text="\\n".join(p.get("text","") for p in cv_analysis["pages"])
                    model_pos=cv_all_text.lower().rfind("beoordelingsmodel")
                    cv_result["cv_text_sample"]=cv_all_text[max(0,model_pos-150):model_pos+2200] if model_pos>=0 else cv_all_text[:2200]
                    cv_result["cv_pages_with_text"]=sum(bool(p.get("text","").strip()) for p in cv_analysis["pages"])
                item.update({"role":"opgaven","level":"Havo" if key[0]=="ha" else "Vwo","year":"20"+key[1],"period":key[2],"candidate_count":len(candidates),"candidate_details":candidates,"cv_crosscheck":cv_result,"candidate_count_is_ground_truth":False})
                if not candidates: failures.append(f"{path.name}: geen vraagstartkandidaten")
                if cv_result and cv_result["status"]!="nummers_overeen": warnings.append(f"{path.name}: vraagnummering wijkt af tussen opgaven en CV; beide originele PDFs handmatig controleren.")
            elif "-c" in path.stem.lower(): item["role"]="correctievoorschrift"
            elif "-u" in path.stem.lower(): item["role"]="uitwerkbijlage"
            if item["pages"]<1: failures.append(f"{path.name}: geen paginas")
            rows.append(item)
        except Exception as exc: failures.append(f"{path.name}: {exc}")
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({"pdf_count":len(rows),"failures":failures,"warnings":warnings,"documents":rows,"benchmark_policy":{"primary_source":"origineel opgaven-PDF","independent_crosscheck":"officieel correctievoorschrift; herkenning blijft voorlopig","legacy_snippets_used_as_ground_truth":False,"candidate_totals_are_ground_truth":False}},ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"PDFs onderzocht: {len(rows)}")
    print(f"Technische problemen: {len(failures)}")
    print(f"Waarschuwingen over onafhankelijke CV-vergelijking: {len(warnings)}")
    print("Bestaande websitesnippets en hun aantallen zijn NIET als waarheid gebruikt.")
    for row in rows:
        if row["role"]=="opgaven":
            cv=row.get("cv_crosscheck")
            status=cv["status"] if cv else "geen gekoppeld CV"
            print("{}: {} kandidaten; {}".format(row["file"],row["candidate_count"],status))
            for candidate in row.get("candidate_details",[]):
                print("  n{} p{} x={:.1f} y={:.1f} w={:.1f} c={:.2f} {} | volgende: {}".format(candidate["number"],candidate["page"],candidate["bbox"][0],candidate["bbox"][1],candidate["bbox"][2]-candidate["bbox"][0],candidate["confidence"],candidate["line"][:80],candidate.get("next_line","")[:100]))
            if cv:
                print("  alleen opgaven: {}; alleen CV: {}".format(cv["ontbreekt_in_cv"],cv["ontbreekt_in_opgaven"]))
                print("  CV-ankers: {}; CV-tekstpagina's: {}".format(len(cv["cv_candidate_details"]),cv["cv_pages_with_text"]))
                print("  CV-tekstvoorbeeld: {}".format(cv["cv_text_sample"][:2200].replace("\\n"," / ")))
    for warning in warnings: print("WAARSCHUWING:",warning)
    for failure in failures: print("FOUT:",failure)
    if not rows: raise SystemExit("Geen examen-PDFs gevonden.")
    if failures: raise SystemExit(1)
if __name__=="__main__": main()
