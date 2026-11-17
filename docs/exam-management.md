# Examenbeheer

De beheeromgeving staat voorlopig op een niet-gelinkte URL:

`/beheer-7f4d9b2c/`

## Huidige werking

- Upload van meerdere PDF- en ZIP-bestanden tegelijk.
- Bestanden worden opgeslagen in de private Supabase Storage-bucket `exam-inbox`.
- Uploadmetadata, status en gebeurtenissen worden bijgehouden in `public.exam_ingest_jobs` en `public.exam_ingest_events`.
- Uploadgeschiedenis, details, verwijderen en opnieuw aanbieden zijn beschikbaar.
- De knop **Inventariseer wachtende uploads** start een Supabase Edge Function per bestand.
- De worker controleert PDF's, haalt per pagina tekst en paginagrootte op, herkent waar mogelijk niveau/jaar/tijdvak/documenttype uit de bestandsnaam en bewaart een `inventory.json` in de private bucket.
- ZIP-bestanden worden geïnventariseerd en de gevonden PDF's worden afzonderlijk in de private bucket opgeslagen.
- Inventarisatie-uitkomsten worden als `review_required` gemarkeerd; dit betekent nadrukkelijk nog niet dat vragen/contexten zijn gekoppeld of dat afbeeldingen zijn goedgekeurd.
- De knop AI-analyse starten verschijnt bij geïnventariseerde opgaven-PDF's; de eerste analyse is handmatig per bestand te starten.\n- Voor AI is de Supabase Edge Function secret OPENAI_API_KEY nodig. Optioneel kan OPENAI_EXAM_MODEL worden ingesteld; standaard is gpt-4.1.\n- Er wordt niets gepubliceerd naar de openbare website.

## Belangrijk: volgende verwerkingsfasen

De eerste technische worker voert alleen bestands- en pagina-inventarisatie uit. De Edge Function analyze-exam-questions is aangesloten als eerste AI-stap. Per opgaven-PDF kan deze met een ingestelde OPENAI_API_KEY een conceptinventaris maken van alle open en meerkeuzevragen, gedeelde contexten en paginabrede fragmenten. Het resultaat wordt als JSON in de private bucket opgeslagen. Deze stap vereist handmatige start per opgaven-PDF en is begrensd tot 24 MB per PDF. Correctievoorschriften en uitwerkbijlagen worden niet als vraagbron gebruikt. De segmenten en vraagherkenning zijn AI-voorstellen en moeten inhoudelijk worden gevalideerd. De originele beeldfragmenten worden nog niet gerenderd en visuele menselijke beoordeling is nog niet aangesloten. De bestaande regex-/anker-gebaseerde renderers worden niet als inhoudelijke waarheid gebruikt. Publicatie blijft uitgeschakeld totdat de volledige vraagset (open én meerkeuze) inhoudelijk en visueel is gecontroleerd.

## Tijdelijke toegang

De route is niet gelinkt en heeft `noindex,nofollow`, maar is niet beveiligd met authenticatie. De tijdelijke Supabase RLS- en Storage-policies laten anonieme toegang toe tot de beheerwachtrij. Iedereen die de URL of publieke API-configuratie kent, kan deze data benaderen. Gebruik dit alleen als tijdelijke tussenstap; voeg vóór productiegebruik een echte toegangscontrole toe.

## Datamodel

- `exam_ingest_jobs`: één record per geüpload bestand, met status, voortgang, metadata en foutdetails.
- `exam_ingest_events`: tijdlijn van upload- en verwerkingsgebeurtenissen.
- `exam-inbox`: private opslagbucket voor originele PDF-/ZIP-bestanden.
