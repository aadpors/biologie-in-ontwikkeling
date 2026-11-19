import tempfile, unittest
from pathlib import Path
from engine import detect_question_candidates, detect_cv_question_numbers, compare_question_numbering, propose_question_regions, classify_document_role, infer_exam_metadata, build_question_record, question_pattern_key, learn_decision, suggest_from_learning, validate_website_records, analyze_pdf, render_crop, match_correction_documents, match_exam_documents, link_context_assets, render_composite_crops, review_checklist_errors, detect_context_references, extract_region_text, pixel_rect_to_pdf_bbox, pdf_page_count, propose_context_fragments, classify_question_with_visuals

class EngineTests(unittest.TestCase):
    def test_official_exam_filename_roles_and_metadata(self):
        self.assertEqual(classify_document_role("ha-1018-a-24-1-o-spr.pdf","")[0],"opgaven")
        self.assertEqual(classify_document_role("ha-1018-a-26-1-c.pdf","")[0],"correctievoorschrift")
        self.assertEqual(classify_document_role("ha-1018-a-26-1-c-a1_0.pdf","")[0],"aanvulling")
        self.assertEqual(classify_document_role("ha-1018-a-25-1-u.pdf","")[0],"uitwerkbijlage")
        self.assertEqual(infer_exam_metadata("ha-1018-a-24-1-o-spr.pdf")["level"],"Havo")
        self.assertEqual(infer_exam_metadata("vw-1018-a-26-2-o.pdf")["year"],"2026")
        self.assertEqual(infer_exam_metadata("ha-1018-a-25-1-u.pdf")["period"],"1")
        self.assertEqual(infer_exam_metadata("ha-1018-a-26-1-c-a1_0.pdf")["year"],"2026")
    def test_exam_metadata_can_be_inferred_from_opening_pdf_text(self):
        got=infer_exam_metadata("hernoemde-opgaven.pdf","CENTRAAL EXAMEN HAVO 2025 tijdvak 2")
        self.assertEqual(got["level"],"Havo")
        self.assertEqual(got["year"],"2025")
        self.assertEqual(got["period"],"2")
        self.assertEqual(got["source"],"eerste_pdf_paginas")

    def test_correction_scheme_matching_never_pools_other_exams(self):
        op={"bestand":"ha-1018-a-26-1-o.pdf"}
        cvs=[
            {"bestand":"ha-1018-a-26-1-c.pdf"},
            {"bestand":"ha-1018-a-26-2-c.pdf"},
            {"bestand":"vw-1018-a-26-1-c.pdf"}
        ]
        got=match_correction_documents(op,cvs)
        self.assertEqual([x["bestand"] for x in got],["ha-1018-a-26-1-c.pdf"])

    def test_low_confidence_cover_metadata_requires_manual_confirmation_before_pairing(self):
        low={"level":"Havo","year":"2025","period":"1","confidence":0.82,"source":"eerste_pdf_paginas"}
        op={"bestand":"renamed-o.pdf","exam_metadata":low}
        cv={"bestand":"renamed-c.pdf","exam_metadata":low}
        self.assertEqual(match_correction_documents(op,[cv]),[])
        confirmed={**low,"confidence":1.0,"source":"handmatig_bevestigd"}
        op["exam_metadata"]=confirmed
        cv["exam_metadata"]=confirmed
        self.assertEqual(match_correction_documents(op,[cv]),[cv])

    def test_appendix_matching_excludes_other_exam_periods(self):
        op={"bestand":"ha-1018-a-26-1-o.pdf"}
        related=[
            {"bestand":"ha-1018-a-26-2-u.pdf"},
            {"bestand":"ha-1018-a-26-1-u.pdf"}
        ]
        self.assertEqual([x["bestand"] for x in match_exam_documents(op,related)],["ha-1018-a-26-1-u.pdf"])

    def test_correction_scheme_matching_uses_confirmed_per_document_identity(self):
        identity={"level":"Vwo","year":"2025","period":"2","source":"handmatig_bevestigd"}
        op={"bestand":"opgaven-hernoemd.pdf","exam_metadata":identity}
        cvs=[
            {"bestand":"cv-ander-examen.pdf","exam_metadata":{"level":"Vwo","year":"2025","period":"1"}},
            {"bestand":"cv-hernoemd.pdf","exam_metadata":identity}
        ]
        self.assertEqual([x["bestand"] for x in match_correction_documents(op,cvs)],["cv-hernoemd.pdf"])

    def test_weaker_same_number_prompt_is_suppressed_when_points_marker_exists(self):
        analysis={"pages":[
            {"page":1,"height":800,"blocks":[{"bbox":[50,100,100,130],"lines":[
                {"bbox":[50,100,60,110],"text":"11"},
                {"bbox":[70,112,90,122],"text":"2p"}]}]},
            {"page":2,"height":800,"blocks":[{"bbox":[40,140,500,180],"lines":[
                {"bbox":[40,140,50,150],"text":"11"},
                {"bbox":[60,140,500,160],"text":"Welk effect heeft dit op de populatie?"}]}]}
        ]}
        got=detect_question_candidates(analysis)
        self.assertEqual([(x["number"],x["page"],x["confidence"]) for x in got],[(11,1,0.95)])
        suppressed=analysis["suppressed_question_candidates"]
        self.assertEqual(len(suppressed),1)
        self.assertEqual(suppressed[0]["page"],2)
        self.assertEqual(suppressed[0]["suppressed_by"]["page"],1)

    def test_question_candidates_keep_repeated_numbers(self):
        a={"pages":[{"page":1,"blocks":[{"bbox":[1,2,3,4],"lines":[{"bbox":[1,2,20,14],"text":"1."},{"bbox":[1,15,100,27],"text":"Beschrijf de functie van dit orgaan."}],"text":"1.\nBeschrijf de functie van dit orgaan."}]},
                    {"page":2,"blocks":[{"bbox":[1,2,3,4],"lines":[{"bbox":[1,2,140,14],"text":"1. Welke stof wordt gevormd?"}],"text":"1. Welke stof wordt gevormd?"}]}]}
        got=detect_question_candidates(a)
        self.assertEqual([x["number"] for x in got],[1,1])
        self.assertTrue(all(x["status"]=="controle_nodig" for x in got))
    def test_cv_question_anchors_recognise_official_maximumscore_rows(self):
        a={"pages":[{"page":1,"text":"Vraag Antwoord Scores\n1 maximumscore 2\n1 (allel) g\n2 B 1\n3 maximumscore 1\n3 juiste uitleg","blocks":[]} ]}
        got=detect_cv_question_numbers(a)
        self.assertEqual([x["number"] for x in got],[1,2,3])

    def test_question_candidates_recognise_welk_prompt(self):
        a={"pages":[{"page":1,"blocks":[{"bbox":[0,0,300,100],"lines":[
            {"bbox":[10,10,20,20],"text":"8."},
            {"bbox":[30,10,250,20],"text":"Welk orgaan produceert dit hormoon?"}
        ],"text":"8.\nWelk orgaan produceert dit hormoon?"}]}]}
        got=detect_question_candidates(a)
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]["number"],8)

    def test_question_candidates_reject_numbered_source_lines_and_keep_score_markers(self):
        a={"pages":[{"page":1,"blocks":[{"bbox":[0,0,300,300],"lines":[
            {"bbox":[10,10,20,20],"text":"1"},
            {"bbox":[10,25,20,35],"text":"2"},
            {"bbox":[10,40,20,50],"text":"3"},
            {"bbox":[10,55,200,65],"text":"Een doorlopende tekstregel."},
            {"bbox":[10,100,20,110],"text":"4"},
            {"bbox":[30,100,50,110],"text":"1p"},
            {"bbox":[30,120,200,130],"text":"De vraagtekst volgt hier."}
        ],"text":"1\n2\n3\nEen doorlopende tekstregel.\n4\n1p\nDe vraagtekst volgt hier."}]}]}
        got=detect_question_candidates(a)
        self.assertEqual([x["number"] for x in got],[4])
        self.assertEqual(got[0]["confidence"],0.95)

    def test_question_number_at_bottom_can_continue_on_next_page(self):
        a={"pages":[
            {"page":1,"height":800,"blocks":[{"bbox":[20,760,40,780],"lines":[{"bbox":[20,760,40,780],"text":"7."}],"text":"7."}]},
            {"page":2,"height":800,"blocks":[{"bbox":[20,40,240,60],"lines":[{"bbox":[20,40,240,60],"text":"Beschrijf de oorzaak."}],"text":"Beschrijf de oorzaak."}]}
        ]}
        got=detect_question_candidates(a)
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]["number"],7)
        self.assertEqual(got[0]["page"],1)
        self.assertEqual(got[0]["next_line"],"Beschrijf de oorzaak.")
    def test_question_pattern_key_uses_generalizable_features_not_exam_specific_text(self):
        inline = question_pattern_key({"line":"4. Beschrijf de functie van dit orgaan.","next_line":"2p"})
        other_text = question_pattern_key({"line":"19. Beschrijf het proces in deze situatie.","next_line":"3 punten"})
        standalone = question_pattern_key({"line":"4.","next_line":"Beschrijf de oorzaak."})
        self.assertEqual(inline, other_text)
        self.assertIn("shape=inline", inline)
        self.assertIn("points=1", inline)
        self.assertIn("shape=standalone", standalone)
        self.assertNotEqual(inline, standalone)

    def test_learning_requires_three_independent_exams_and_never_auto_applies(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            # Repeated corrections in one PDF must not masquerade as independent evidence.
            for _ in range(5):
                learn_decision(p,{"pattern_key":"layout-a","chosen":"question","accepted":True,
                                  "document_id":"exam-a","candidate_line":"4. Beschrijf dit","page":1})
            same_exam=suggest_from_learning(p,"layout-a")
            self.assertIsNone(same_exam["suggestion"])
            self.assertEqual(same_exam["document_support"],1)
            for exam in ("exam-b","exam-c"):
                learn_decision(p,{"pattern_key":"layout-a","chosen":"question","accepted":True,
                                  "document_id":exam,"candidate_line":"8. Beschrijf dit","page":2})
            learned=suggest_from_learning(p,"layout-a")
            self.assertEqual(learned["suggestion"],"question")
            self.assertEqual(learned["document_support"],3)
            self.assertEqual(learned["confidence"],1.0)
            self.assertFalse(learned["auto_apply"])
            learn_decision(p,{"pattern_key":"layout-a","chosen":"not_question","accepted":True,
                              "document_id":"exam-d","candidate_line":"9. Bronregel","page":3})
            conflict=suggest_from_learning(p,"layout-a")
            self.assertIsNone(conflict["suggestion"])
            self.assertTrue(conflict["conflicting"])
            self.assertFalse(conflict["auto_apply"])

    def test_context_proposals_use_visual_assets_and_link_to_confirmed_question(self):
        analysis = {"pages": [{
            "page": 1, "width": 600, "height": 800,
            "visual_assets": [{"id": "p1-image-1", "kind": "image", "bbox": [100, 180, 450, 300]}],
            "blocks": [{"lines": [{"bbox": [110, 302, 250, 318], "text": "Figuur 2. De bouw van een blad"}]}],
        }]}
        candidates = [{"number": 2, "page": 1, "bbox": [40, 100, 90, 120], "human_decision": True}]
        proposals = propose_context_fragments(analysis, candidates)
        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal["type"], "vraagcontext")
        self.assertEqual(proposal["question_numbers"], [2])
        self.assertEqual(proposal["status"], "automatisch_voorstel_nog_te_controleren")
        self.assertEqual(proposal["confidence"], 0.82)
        self.assertIn("Figuur 2", proposal["evidence"]["captions"][0])

    def test_context_proposals_do_not_invent_regions_without_visual_assets(self):
        analysis = {"pages": [{"page": 1, "width": 600, "height": 800,
                               "visual_assets": [], "blocks": []}]}
        candidates = [{"number": 1, "page": 1, "bbox": [40, 100, 90, 120],
                       "human_decision": True}]
        self.assertEqual(propose_context_fragments(analysis, candidates), [])

    def test_duplicate_ids_reported(self):
        row={"id":"same","level":"Havo","year":"2025","period":"1","n":1,"page":1,"q":"x","pdf":"a.pdf","cv":"b.pdf"}
        errors=validate_website_records([row],[row],[])
        self.assertTrue(any(e["kind"]=="duplicate_id" for e in errors))
    def test_cv_numbering_crosscheck_reports_differences(self):
        op=[{"number":1},{"number":2},{"number":3}]
        cv=[{"number":1},{"number":3},{"number":4}]
        result=compare_question_numbering(op,cv)
        self.assertEqual(result["ontbreekt_in_cv"],[2])
        self.assertEqual(result["ontbreekt_in_opgaven"],[4])
    def test_question_regions_can_span_pages(self):
        analysis={"pages":[{"page":1,"width":600,"height":800},{"page":2,"width":600,"height":800}]}
        candidates=[{"number":1,"page":1,"bbox":[50,700,80,720]},{"number":2,"page":2,"bbox":[50,100,80,120]}]
        regions=propose_question_regions(analysis,candidates)
        self.assertEqual(len(regions[0]["source_segments"]),2)
        self.assertEqual(regions[0]["status"],"voorstel_niet_goedgekeurd")
    def test_human_approval_requires_all_review_categories(self):
        record={"exam":{"questionType":"open"},"question_text":"Leg uit.","source_pdf":"o.pdf","cv_pdf":"c.pdf",
                "snippet_files":["q.png"],"cv_snippet_file":"cv-q1.png"}
        checklist={"question_text":True,"question_type":True,"points":True,"cv_alignment":True,
                   "images_and_context":True,"appendices":False,"cv_addenda":True}
        self.assertIn("controle_niet_afgevinkt:appendices",review_checklist_errors(record,checklist))
        checklist["appendices"]=True
        self.assertEqual(review_checklist_errors(record,checklist),[])

    def test_source_reanalysis_invalidates_old_record_approval(self):
        record={"exam":{"questionType":"open"},"question_text":"Leg uit.","source_pdf":"o.pdf","cv_pdf":"c.pdf",
                "snippet_files":["q.png"],"cv_snippet_file":"cv-q1.png","source_analysis_invalidated":True}
        checklist={"question_text":True,"question_type":True,"points":True,"cv_alignment":True,
                   "images_and_context":True,"appendices":True,"cv_addenda":True}
        self.assertIn("bron_opnieuw_geanalyseerd_record_opnieuw_samenstellen",review_checklist_errors(record,checklist))

    def test_open_question_cannot_be_approved_without_cv_snippet(self):
        record={"exam":{"questionType":"open"},"question_text":"Leg uit.","source_pdf":"o.pdf","cv_pdf":"c.pdf",
                "snippet_files":["q.png"]}
        checklist={"question_text":True,"question_type":True,"points":True,"cv_alignment":True,
                   "images_and_context":True,"appendices":True,"cv_addenda":True}
        self.assertIn("cv_fragment_ontbreekt",review_checklist_errors(record,checklist))

    def test_mcq_approval_requires_answer_option_review(self):
        record={"exam":{"questionType":"mcq"},"question_text":"Kies.","source_pdf":"o.pdf","cv_pdf":"c.pdf",
                "snippet_files":["q.png"],"options":[{"key":"A","text":"A"},{"key":"B","text":"B"}],"correct":"A"}
        checklist={"question_text":True,"question_type":True,"points":True,"cv_alignment":True,
                   "images_and_context":True,"appendices":True,"cv_addenda":True}
        self.assertIn("controle_niet_afgevinkt:answer_options",review_checklist_errors(record,checklist))

    def test_review_record_is_never_preapproved_and_uses_site_id(self):
        meta={"level":"Havo","year":"2026","period":"1","questionType":"open"}
        candidate={"number":7,"page":3,"bbox":[30,100,60,120],"confidence":0.7}
        record=build_question_record(meta,candidate,"Beschrijf dit.","opgaven.pdf","cv.pdf")
        self.assertEqual(record["id"],"ha26t1-open-7")
        self.assertFalse(record["approved_by_human"])
        self.assertEqual(record["status"],"controle_nodig")
    def test_cv_parser_rejects_bare_page_numbers(self):
        a={"pages":[{"page":1,"text":"56\n57\n60\nVraag\n4\nmaximumscore 2\n"}]}
        got=detect_cv_question_numbers(a)
        self.assertEqual([x["number"] for x in got],[4])

    def test_cv_anchor_detection(self):
        a={"pages":[{"page":1,"text":"Vraag 1\nBeoordelingsmodel\nVraag 3"}]}
        got=detect_cv_question_numbers(a)
        self.assertEqual([x["number"] for x in got],[1,3])

    def test_question_type_detection_and_option_integrity(self):
        from engine import detect_question_type
        result=detect_question_type("Kies het juiste antwoord.\nA. mitochondriën\nB. ribosomen\nC. celkern\nD. celmembraan")
        self.assertEqual(result["type"],"meerkeuze")
        self.assertEqual(result["option_labels"],["A","B","C","D"])
        self.assertTrue(result["options_complete"])
        self.assertEqual(result["status"],"controle_nodig")
        missing=detect_question_type("Kies het juiste antwoord.\nA. eerste optie\nC. derde optie")
        self.assertFalse(missing["options_complete"])
        self.assertEqual(missing["option_gaps"],["B"])
        # PDF text extraction can place all options on one line.
        inline=detect_question_type("Kies het juiste antwoord. A. mitochondriën B. ribosomen C. celkern D. celmembraan")
        self.assertEqual(inline["type"],"meerkeuze")
        self.assertEqual(inline["option_labels"],["A","B","C","D"])
        self.assertTrue(inline["options_complete"])
        self.assertIn("ribosomen",inline["options"][1]["text"])

        # Parenthesized and lower-case labels are common in exam layouts/OCR.
        lower=detect_question_type("(a) mitochondriën\n(b) ribosomen\n(c) celkern")
        self.assertEqual(lower["type"],"meerkeuze")
        self.assertEqual(lower["option_labels"],["A","B","C"])
        self.assertTrue(lower["options_complete"])

        # A label on its own line followed by option text must also be retained.
        split=detect_question_type("Kies één antwoord.\nA\nmitochondriën\nB\nribosomen")
        self.assertEqual(split["type"],"meerkeuze")
        self.assertEqual(split["option_labels"],["A","B"])

        # An incidental single letter/label in prose is not sufficient evidence.
        prose=detect_question_type("A. Beschrijf de functie van mitochondriën.")
        self.assertEqual(prose["type"],"open")


    def test_context_assets_link_caption_to_nearby_pdf_image_and_vector(self):
        analysis={"pages":[
            {"page":1,"blocks":[
                {"bbox":[40,300,300,320],"text":"Figuur 2","lines":[{"bbox":[40,300,100,320],"text":"Figuur 2"}]}
            ],"visual_assets":[
                {"id":"p1-image-1","kind":"image","bbox":[40,80,300,290]},
                {"id":"p1-vector-1","kind":"vector_region","bbox":[320,90,500,280]}
            ]},
            {"page":2,"blocks":[],"visual_assets":[{"id":"p2-image-1","kind":"image","bbox":[40,40,300,250]}]}
        ]}
        refs=[{"kind":"figuur","number":"2","matched_text":"figuur 2"}]
        linked=link_context_assets(analysis,refs,start_page=1,end_page=1)
        self.assertEqual(linked[0]["link_status"],"caption_en_geometrie_gevonden")
        self.assertEqual(linked[0]["caption_matches"][0]["page"],1)
        self.assertEqual({x["asset_id"] for x in linked[0]["asset_candidates"]},{"p1-image-1","p1-vector-1"})
        self.assertTrue(all(x["status"]=="visueel_controleren" for x in linked[0]["asset_candidates"]))

    def test_numbered_source_text_links_to_text_blocks_not_only_images(self):
        analysis={"pages":[{"page":3,"blocks":[
            {"bbox":[40,80,200,100],"text":"Bron 1","lines":[{"bbox":[40,80,100,100],"text":"Bron 1"}]},
            {"bbox":[40,110,500,220],"text":"De bron beschrijft een ecosysteem en bevat relevante gegevens."},
            {"bbox":[40,230,500,320],"text":"Een tweede alinea met aanvullende context."}
        ],"visual_assets":[]}]}
        linked=link_context_assets(analysis,[{"kind":"bron","number":"1","matched_text":"Bron 1"}],3,3)
        self.assertEqual(linked[0]["link_status"],"caption_en_tekstregio_gevonden")
        self.assertGreaterEqual(len(linked[0]["text_region_candidates"]),1)
        self.assertIn("ecosysteem",linked[0]["text_region_candidates"][0]["text"])

    def test_unnumbered_context_reference_keeps_manual_review_without_guessing(self):
        linked=link_context_assets({"pages":[]},[{"kind":"ongenummerde_verwijzing","number":None}],1,1)
        self.assertEqual(linked[0]["link_status"],"geen_nummer_handmatige_koppeling")
        self.assertEqual(linked[0]["asset_candidates"],[])

    def test_context_references_recognise_lettered_subfigures(self):
        refs=detect_context_references("Vergelijk figuur 2A met figuur 2B en tabel 3.")
        self.assertEqual([(x["kind"],x["number"]) for x in refs],
                         [("figuur","2A"),("figuur","2B"),("tabel","3")])

    def test_context_reference_detection(self):
        from engine import detect_context_references
        refs=detect_context_references("Gebruik figuur 2 en tabel 1. Vergelijk dit met bron A.")
        self.assertEqual([(x["kind"],x["number"]) for x in refs],
                         [("figuur","2"),("tabel","1"),("bron","A")])
        unnumbered=detect_context_references("Gebruik de bovenstaande afbeelding.")
        self.assertEqual(unnumbered[0]["kind"],"ongenummerde_verwijzing")

    def test_candidate_text_is_bounded_by_next_question(self):
        from engine import extract_candidate_text
        analysis={"pages":[
            {"page":1,"blocks":[{"bbox":[0,10,100,20],"lines":[
                {"bbox":[0,10,10,20],"text":"1."},
                {"bbox":[0,25,100,35],"text":"Gebruik figuur 2."},
                {"bbox":[0,50,100,60],"text":"2. Volgende vraag."}]}]},
            {"page":2,"blocks":[{"bbox":[0,5,100,15],"lines":[
                {"bbox":[0,5,100,15],"text":"Vervolg van vraag 2."}]}]}
        ]}
        first={"number":1,"page":1,"bbox":[0,10,10,20]}
        second={"number":2,"page":1,"bbox":[0,50,100,60]}
        self.assertEqual(extract_candidate_text(analysis,first,second),"1.\nGebruik figuur 2.")


    def test_visual_answer_options_are_flagged_as_possible_multiple_choice(self):
        import pymupdf as fitz
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"visual-options.pdf"
            doc=fitz.open()
            page=doc.new_page(width=600,height=800)
            page.insert_text((50,60),"Kies het juiste antwoord.",fontsize=11)
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,40,40),0)
            pix.clear_with(180)
            for x in (60,180,300,420):
                page.insert_image(fitz.Rect(x,120,x+70,190),pixmap=pix)
            page.insert_text((60,210),"A",fontsize=10)
            page.insert_text((180,210),"B",fontsize=10)
            page.insert_text((300,210),"C",fontsize=10)
            page.insert_text((420,210),"D",fontsize=10)
            doc.save(path); doc.close()
            analysis=analyze_pdf(path)
            candidate={"page":1,"bbox":[40,45,80,65]}
            check=classify_question_with_visuals(analysis,candidate,None,
                                                 "Kies het juiste antwoord.")
            self.assertEqual(check["type"],"mogelijk_visuele_meerkeuze")
            self.assertEqual(check["visual_detection"]["status"],
                             "waarschijnlijke_visuele_meerkeuze")
            self.assertGreaterEqual(check["visual_detection"]["raster_image_count"],4)
            self.assertTrue(check["visual_detection"]["requires_visual_review"])

    def test_single_illustration_is_not_misclassified_as_visual_multiple_choice(self):
        import pymupdf as fitz
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"illustration.pdf"
            doc=fitz.open()
            page=doc.new_page(width=600,height=800)
            page.insert_text((50,60),"Beschrijf wat je ziet.",fontsize=11)
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,40,40),0)
            pix.clear_with(180)
            page.insert_image(fitz.Rect(60,120,260,300),pixmap=pix)
            doc.save(path); doc.close()
            analysis=analyze_pdf(path)
            candidate={"page":1,"bbox":[40,45,80,65]}
            check=classify_question_with_visuals(analysis,candidate,None,
                                                 "Beschrijf wat je ziet.")
            self.assertEqual(check["type"],"open")
            self.assertEqual(check["visual_detection"]["status"],
                             "visueel_materiaal_bij_vraag")
            self.assertTrue(check.get("visual_material_present"))

    def test_pdf_analysis_inventories_raster_and_vector_visual_assets(self):
        try:
            import pymupdf as fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"visuals.pdf"
            doc=fitz.open()
            page=doc.new_page()
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,40,40),0)
            pix.clear_with(180)
            page.insert_image(fitz.Rect(50,100,250,250),pixmap=pix)
            page.draw_rect(fitz.Rect(300,100,500,250),color=(0,0,0),width=1)
            page.insert_text((50,280),"Figuur 2",fontsize=11)
            doc.save(p); doc.close()
            result=analyze_pdf(p)
            assets=result["pages"][0]["visual_assets"]
            self.assertTrue(any(x["kind"]=="image" for x in assets))
            self.assertTrue(any(x["kind"]=="vector_region" for x in assets))
            linked=link_context_assets(result,[{"kind":"figuur","number":"2"}],1,1)
            self.assertEqual(linked[0]["link_status"],"caption_en_geometrie_gevonden")
            self.assertGreaterEqual(len(linked[0]["asset_candidates"]),2)

    def test_cv_answer_regions_from_multiple_pages_render_as_one_snippet(self):
        try:
            import pymupdf as fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"cv.pdf"
            doc=fitz.open()
            page1=doc.new_page(); page1.insert_text((60,80),"1 maximumscore 2")
            page1.insert_text((60,120),"Eerste beoordelingsregel")
            page2=doc.new_page(); page2.insert_text((60,80),"Vervolg van het antwoord")
            page2.insert_text((60,120),"2 maximumscore 1")
            doc.save(p); doc.close()
            analysis=analyze_pdf(p)
            anchors=detect_cv_question_numbers(analysis)
            q1=next(x for x in anchors if x["number"]==1)
            self.assertIsNotNone(q1.get("bbox"))
            regions=propose_question_regions(analysis,anchors)
            proposal=next(x for x in regions if x["number"]==1)
            self.assertEqual([x["page"] for x in proposal["source_segments"]],[1,2])
            out=Path(d)/"snippets"/"cv-q1.png"
            render_composite_crops(p,proposal["source_segments"],out)
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size,500)

    def test_pdf_page_count_helper(self):
        import pymupdf as fitz
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"count.pdf"
            doc=fitz.open()
            doc.new_page()
            doc.new_page()
            doc.save(path)
            doc.close()
            self.assertEqual(pdf_page_count(path), 2)

    def test_pdf_text_and_exact_crop(self):
        try:
            import pymupdf as fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"source.pdf"
            doc=fitz.open(); page=doc.new_page(); page.insert_text((72,72),"1. Beschrijf de afbeelding.")
            doc.save(p); doc.close()
            result=analyze_pdf(p)
            self.assertEqual(result["page_count"],1)
            self.assertIn("Beschrijf",result["pages"][0]["text"])
            out=Path(d)/"crop.png"
            render_crop(p,1,[60,55,250,90],out)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size,100)


    def test_manual_region_text_extraction_uses_original_pdf_coordinates(self):
        import pymupdf as fitz
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"region.pdf"
            doc=fitz.open()
            page=doc.new_page(width=600,height=800)
            page.insert_text((50,100),"TEXT INSIDE SELECTION")
            page.insert_text((50,700),"TEXT OUTSIDE SELECTION")
            doc.save(path)
            doc.close()
            text=extract_region_text(path,[{"page":1,"bbox":[0,50,600,200]}])
            self.assertIn("TEXT INSIDE SELECTION",text)
            self.assertNotIn("TEXT OUTSIDE SELECTION",text)


    def test_manual_context_crop_coordinates_map_to_original_pdf(self):
        bbox = pixel_rect_to_pdf_bbox([100, 200, 500, 700], (1200, 1600), (600, 800))
        self.assertEqual(bbox, [50.0, 100.0, 250.0, 350.0])

    def test_manual_context_crop_coordinates_are_clamped_and_reject_tiny_regions(self):
        bbox = pixel_rect_to_pdf_bbox([-20, 100, 1300, 1700], (1200, 1600), (600, 800))
        self.assertEqual(bbox, [0.0, 50.0, 600.0, 800.0])
        with self.assertRaises(ValueError):
            pixel_rect_to_pdf_bbox([10, 10, 12, 40], (1200, 1600), (600, 800))
        with self.assertRaises(ValueError):
            pixel_rect_to_pdf_bbox([0, 0, 100, 100], (0, 1600), (600, 800))


if __name__=="__main__": unittest.main()
