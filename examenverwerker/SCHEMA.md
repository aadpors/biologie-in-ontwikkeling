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


Concept-vraagrecords bewaren na het opslaan ook `exam_structure_status`, `exam_structure_fragment_ids`, `question_region_page_spans` en `context_region_fragments`. Dezelfde gegevens gaan mee in het lokale exportmanifest, zodat de handmatig afgebakende bronregio's en vraagkoppelingen niet verloren gaan bij het maken van een exportpakket. Ze vervangen de bestaande websitevelden niet.


## Meerdere documentstructuren en CV-regio's

- `exam_structures[document_id]`: zelfstandige vraag/contextstructuur per opgaven-PDF; de oudere enkelvoudige `exam_structure`-sleutel blijft voor compatibiliteit beschikbaar.
- `cv_regions[document_id][question_number]`: handmatig afgebakende regio van het bijbehorende correctievoorschrift of een officiële aanvulling, met document-ID, SHA-256, documentrol en genormaliseerde paginagrenzen.
- `question_region_fragment_id` en `exam_structure_question_number`: expliciete koppeling tussen het vraagrecord en precies het juiste vraagfragment.
- `cv_source_region` en `cv_source_region_file`: gecontroleerde CV-regio en de rechtstreeks gerenderde uitsnede.
- `context_asset_files`: geselecteerde figuur-/tabeluitsneden plus handmatig begrensde contextregio's, met bronhash, pagina, bijschrift en fragmentkoppeling. Deze bestanden worden niet langer als vraagafbeeldingen geëxporteerd.
- `source_context`: selecteerbare tekst die uit de handmatig begrensde contextregio's van de originele PDF is gehaald.
- `cv_amendment_regions`: per geselecteerde officiële aanvulling de vraaggebonden regio, bronhash en gerenderde uitsnede.

De exportpoort blokkeert ontbrekende vraag- of CV-regio's, gewijzigde bronnen, onvolledige addendumafbakening en ongeldige contextbestanden. De oorspronkelijke PDF blijft de primaire bron; geen enkele automatische detectie of AI-voorstel kan deze handmatige afbakening goedkeuren.


## Integriteitscontrole en herbeoordeling

- `exam_structure_invalidated`: wordt gezet zodra de vraaggrenzen of contextkoppelingen na het maken van een vraagrecord veranderen.
- `cv_region_invalidated`: wordt gezet zodra de visuele CV-/aanvullingsregio of de gerenderde uitsnede verandert.
- `question_region_snippet_sha256`, `cv_source_region_sha256` en `snippet_sha256` per context-/aanvullingsasset: verwachte hashes van de gegenereerde uitsneden. De exportpoort vergelijkt deze met de bestanden op schijf.
- Bij wijziging worden eerdere goedkeuring en checklistvinkjes ingetrokken. Het vraagrecord moet opnieuw vanuit de actuele grenzen worden samengesteld en volledig worden gecontroleerd.

De bronhashes van opgaven, CV en aanvullingen worden opnieuw gecontroleerd bij het samenstellen van een conceptrecord én bij export. Dit voorkomt dat een bestaande afbakening ongemerkt op een vervangen PDF of een handmatig gewijzigd PNG-bestand wordt toegepast.
