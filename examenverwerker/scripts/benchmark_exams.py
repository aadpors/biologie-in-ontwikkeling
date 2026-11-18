"""Run the new PDF engine against the real exam PDFs committed to this repository."""
from __future__ import annotations
import json, re, sys
from pathlib import Path

# Support execution both from this folder and via a repository-root invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import analyze_pdf, detect_question_candidates

ROOT=Path(__file__).resolve().parents[2]
PDF_DIR=ROOT/"examens"
OUT=Path(__file__).resolve().parents[1]/"artifacts"/"exam-analysis-report.json"
EXPECTED={
 ("ha","24","1"):45,("ha","24","2"):48,("vw","24","1"):42,("vw","24","2"):41,
 ("ha","25","1"):48,("ha","25","2"):44,("vw","25","1"):40,("vw","25","2"):42,
 ("ha","26","1"):43,("ha","26","2"):46,("vw","26","1"):41,("vw","26","2"):39,
}
PATTERN=re.compile(r"^(ha|vw)-1018-a-(\d{2})-(\d+)-o(?:-|\.pdf)",re.I)

def main():
    if not PDF_DIR.is_dir(): raise SystemExit(f"Examensmap niet gevonden: {PDF_DIR}")
    rows=[]; failures=[]
    for path in sorted(PDF_DIR.glob("*.pdf")):
        try:
            analysis=analyze_pdf(path)
            text_pages=sum(bool(p["text"].strip()) for p in analysis["pages"])
            item={"file":path.name,"pages":analysis["page_count"],"pages_with_text":text_pages,"ocr_required":text_pages==0,
                  "sha256":analysis["sha256"],"role":"other","candidate_count":None}
            match=PATTERN.match(path.name)
            if match:
                key=(match.group(1).lower(),match.group(2),match.group(3))
                candidates=detect_question_candidates(analysis)
                item.update({"role":"opgaven","level":"Havo" if key[0]=="ha" else "Vwo",
                             "year":"20"+key[1],"period":key[2],"candidate_count":len(candidates),
                             "expected_question_count":EXPECTED.get(key)})
                if not candidates: failures.append(f"{path.name}: geen vraagstartkandidaten")
            elif "-c" in path.stem.lower(): item["role"]="correctievoorschrift"
            elif "-u" in path.stem.lower(): item["role"]="uitwerkbijlage"
            if item["pages"]<1: failures.append(f"{path.name}: geen pagina's")

            rows.append(item)
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({"pdf_count":len(rows),"failures":failures,"documents":rows},ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"PDF's onderzocht: {len(rows)}")
    print(f"Problemen: {len(failures)}")
    for row in rows:
        if row["role"]=="opgaven":
            print(f"{row['file']}: {row['candidate_count']} kandidaten (verwacht {row['expected_question_count']})")
    for failure in failures: print("FOUT:",failure)
    if not rows: raise SystemExit("Geen examen-PDF's gevonden.")
    if failures: raise SystemExit(1)

if __name__=="__main__": main()
