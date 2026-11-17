# Examenbeheer

De beheeromgeving staat voorlopig op een niet-gelinkte URL:

`/beheer-7f4d9b2c/`

## Eerste versie

- Upload van meerdere PDF- en ZIP-bestanden tegelijk.
- Bestanden worden opgeslagen in de private Supabase Storage-bucket `exam-inbox`.
- Uploadmetadata, status en gebeurtenissen worden bijgehouden in `public.exam_ingest_jobs` en `public.exam_ingest_events`.
- Uploadgeschiedenis, details, verwijderen en opnieuw aanbieden zijn beschikbaar.
- Er wordt niets gepubliceerd naar de openbare website.

## Belangrijk: huidige grens

Dit is de eerste werkende beheerbasis. De AI-analyse, PDF-inventarisatie, vraag-/contextsegmentatie, beeldsamenstelling en visuele beoordelingsworkflow zijn nog niet gekoppeld. Een upload wordt dus opgeslagen en geregistreerd, maar niet ten onrechte als verwerkt gemarkeerd. De volgende fase bouwt een verwerkingsworker die de bestaande PDF-renderers vervangt/uitbreidt en elke vraag inhoudelijk én visueel controleert.

## Tijdelijke toegang

De route is niet gelinkt en heeft `noindex,nofollow`, maar is niet beveiligd met authenticatie. De tijdelijke Supabase RLS- en Storage-policies laten anonieme toegang toe tot de beheerwachtrij. Iedereen die de URL of publieke API-configuratie kent, kan deze data benaderen. Gebruik dit alleen als tijdelijke tussenstap; voeg vóór productiegebruik een echte toegangscontrole toe.

## Datamodel

- `exam_ingest_jobs`: één record per geüpload bestand, met status, voortgang, metadata en foutdetails.
- `exam_ingest_events`: tijdlijn van upload- en verwerkingsgebeurtenissen.
- `exam-inbox`: private opslagbucket voor originele PDF-/ZIP-bestanden.
