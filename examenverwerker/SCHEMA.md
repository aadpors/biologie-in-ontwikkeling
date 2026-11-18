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
