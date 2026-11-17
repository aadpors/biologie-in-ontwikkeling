# Examenbeheer

De beheeromgeving staat voorlopig op een niet-gelinkte URL:

`/beheer-7f4d9b2c/`

## Huidige werking

- Upload van meerdere PDF- en ZIP-bestanden tegelijk.
- Bestanden worden opgeslagen in de private Supabase Storage-bucket `exam-inbox`.
- Uploadmetadata, status en gebeurtenissen worden bijgehouden in `public.exam_ingest_jobs` en `public.exam_ingest_events`.
- Uploadgeschiedenis, details, verwijderen en opnieuw aanbieden zijn beschikbaar.
- De knop **Inventariseer wachtende uploads** start de Supabase Edge Function per bestand.
- De worker controleert PDF's, haalt per pagina tekst en paginagrootte op, herkent waar mogelijk niveau/jaar/tijdvak/documenttype uit de bestandsnaam en bewaart een `inventory.json` in de private bucket.
- ZIP-bestanden worden geïnventariseerd en de gevonden PDF's worden afzonderlijk in de private bucket opgeslagen.
- Inventarisatie-uitkomsten worden als `review_required` gemarkeerd; dit betekent nadrukkelijk nog niet dat vragen/contexten zijn gekoppeld of dat afbeeldingen zijn goedgekeurd.
- **Download ChatGPT-verwerkingspakket** maakt in de browser een ZIP met de originele opgaven-PDF's, bijbehorende uitwerkbijlagen en hun pagina-inventarisaties. Correctievoorschriften worden bewust uitgesloten.
- Het pakket bevat ook verwerkingsinstructies en een manifest met documentmetadata. Er wordt geen externe AI-API aangeroepen.

## Gratis verwerkingsroute

De inhoudelijke AI-analyse wordt vanuit de ChatGPT-conversatie uitgevoerd, niet vanuit Supabase. De gebruiker downloadt het verwerkingspakket uit de beheeromgeving en voegt het hier toe. Analyse, selectie van contexten en vraagfragmenten en inhoudelijke controle gebeuren in ChatGPT. Resultaten blijven concept totdat de volledige set vragen inhoudelijk en visueel is gecontroleerd.

De Edge Function `analyze-exam-questions` is bewust gedeactiveerd op functieniveau: hij retourneert HTTP 410 en voert geen externe verzoeken uit. Een eventuele oude `OPENAI_API_KEY`-secret wordt niet gelezen of gebruikt. Er kunnen dus via deze functie geen OpenAI API-kosten ontstaan.

## Kwaliteitsregels

- Verwerk alle vragen, open én meerkeuze, zonder uitzonderingen.
- De originele PDF is leidend voor vraagtekst, figuren, tabellen, onderschriften en beeldmateriaal.
- Koppel gedeelde contexten ook als die op eerdere pagina's of tussen vragen van dezelfde groep staan.
- Behoud leesvolgorde, kolommen, labels, legenda's en volledige figuren; kies bij twijfel een ruimere uitsnede.
- Reconstructeer, herschrijf of genereer geen exameninhoud of beeldmateriaal.
- Leg onzekerheden vast met vraagnummer, bronpagina, reden en voorgestelde uitsnede.
- Controleer aantallen en nummering tegen de volledige PDF.
- Correctievoorschriften en addenda mogen voor latere antwoord-/scoreverwerking worden gebruikt, maar niet als bron voor vraagbeelden.
- Publiceer niets voordat de volledige vraagset inhoudelijk en visueel is gecontroleerd en expliciet is goedgekeurd.

## Tijdelijke toegang

De route is niet gelinkt en heeft `noindex,nofollow`, maar is niet beveiligd met volwaardige toegangscontrole. De tijdelijke Supabase RLS- en Storage-policies laten anonieme toegang toe tot de beheerwachtrij. Iedereen die de URL of publieke API-configuratie kent, kan deze data mogelijk benaderen. Gebruik dit alleen als tijdelijke tussenstap; voeg vóór productiegebruik echte toegangscontrole toe.

## Datamodel

- `exam_ingest_jobs`: één record per geüpload bestand, met status, voortgang, metadata en foutdetails.
- `exam_ingest_events`: tijdlijn van upload- en verwerkingsgebeurtenissen.
- `exam-inbox`: private opslagbucket voor originele PDF-/ZIP-bestanden.
