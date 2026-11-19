# Intern gegevensmodel

De verwerker houdt bron, voorstel, menselijke beslissing en website-export uit elkaar.

## Document
`id`, `bestand`, `opslagbestand`, `sha256`, `type_voorstel`, `type_zekerheid`, `status`, `pagina_aantal`, `metadata`.

## Vraagkandidaat
`number`, `page`, `bbox` (PDF-punten), `line`, `confidence`, `status`, `reason`. Kandidaten blijven per vindplaats bestaan; dubbele nummers worden dus niet weggepoetst.

## Vraagreview
`schema`, `exam`, `number`, `source_page`, `source_bbox`, `question_text`, `source_pdf`, `cv_pdf`, `snippet_candidates`, `status`, `approved_by_human`.

## Herkomst
Iedere afbeelding en extractie verwijst naar het bronbestand via SHA-256, paginanummer en uitsnede-coördinaten. Renders worden opnieuw gemaakt vanuit de originele PDF; er wordt geen afbeelding gegenereerd of inhoud gereconstrueerd.

## Websitecontract
De bestaande velden in `exam-mcq.json`, `exam-open.json` en `exam-contexts.json` blijven het doelcontract. Export maakt eerst een apart pakket en valideert verplichte velden, unieke ID's, paden en contextdubbelen. Er is geen rechtstreekse schrijfroute naar de live site.


## Examenstructuur (visuele afbakening)

`exam_structure` bevat de handmatig gecontroleerde structuur van één opgaven-PDF:
- `schema`: `biologie-examenstructuur-v1`
- `document_id` en `source_sha256`: exacte bronidentiteit; bij heranalyse wordt de structuur verouderd verklaard
- `nummering_bevestigd`: alleen waar nadat iedere vraagstartkandidaat handmatig als vraag of geen vraag is beoordeeld
- `vraag_nummers`: unieke, bevestigde vraag nummers
- `fragments[]`: type (`context_intro`, `vraagcontext`, `vraag`, `tussenliggende_context`), vraagkoppelingen, status en `page_spans[]`
- `page_spans[]`: paginanummer plus genormaliseerde verticale grenzen `top` en `bottom` tussen 0 en 1. Iedere pagina van een doorlopend fragment heeft eigen grenzen.

Een contextinleiding wordt standaard aan alle bevestigde vragen gekoppeld. Een vraagfragment moet precies één vraagnummer hebben. De editor gebruikt uitsluitend een visuele grijsmarkering buiten twee dunne zwarte horizontale lijnen; de originele PDF wordt nooit gewijzigd. De structuur blijft concept totdat de verdere inhoudelijke en visuele controles zijn uitgevoerd.
