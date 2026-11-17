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
- Er wordt niets gepubliceerd naar de openbare website.

## Belangrijk: volgende verwerkingsfasen

De eerste technische worker voert alleen bestands- en pagina-inventarisatie uit. AI-gestuurde vraagherkenning, semantische koppeling van algemene contexten en vraagintroducties, segmentselectie over meerdere pagina's, originele fragmentcompositie per vraag en visuele menselijke beoordeling zijn nog niet aangesloten. De bestaande regex-/anker-gebaseerde renderers worden niet als inhoudelijke waarheid gebruikt. Publicatie blijft uitgeschakeld totdat de volledige vraagset (open én meerkeuze) inhoudelijk en visueel is gecontroleerd.

## Tijdelijke toegang

De route is niet gelinkt en heeft `noindex,nofollow`, maar is niet beveiligd met authenticatie. De tijdelijke Supabase RLS- en Storage-policies laten anonieme toegang toe tot de beheerwachtrij. Iedereen die de URL of publieke API-configuratie kent, kan deze data benaderen. Gebruik dit alleen als tijdelijke tussenstap; voeg vóór productiegebruik een echte toegangscontrole toe.

## Datamodel

- `exam_ingest_jobs`: één record per geüpload bestand, met status, voortgang, metadata en foutdetails.
- `exam_ingest_events`: tijdlijn van upload- en verwerkingsgebeurtenissen.
- `exam-inbox`: private opslagbucket voor originele PDF-/ZIP-bestanden.
