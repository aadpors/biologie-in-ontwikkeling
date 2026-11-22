# Biologie-examens havo/vwo 2024–2026 – snippets en gegevens

Dit ZIP-bestand bevat **12 van de 12** gevraagde examens (519 vragen). Zie `audit/totaalrapport.md` voor status en beperkingen.

## Inhoud
- `data/<niveau>-<jaar>-t<tijdvak>.json`: gegevens per examen (contexten, vragen, bronfragmenten, antwoordgegevens, controlestatus).
- `snippets/<examen>/<examen>-qNN.png`: één samengestelde PNG per vraag.
- `audit/`: totaalrapport en een rapport per verwerkt examen. `manifest.json`: bestandslijst met SHA-256.

## Naamgeving
Bestanden `havo-2024-t1-q07.png`; ID's `ha24t1-7` (havo) / `vw24t1-7` (vwo). `snippet_file` is een pad relatief aan de ZIP-root.

## Opbouw van een snippet
Fragmenten uit de originele opgavenboekje-PDF (300 dpi) staan verticaal onder elkaar, op gelijke breedte, met witruimte ertussen, in documentvolgorde: algemene opmerking, contextintroductie, voorafgaande informatie en verwezen afbeeldingen/tabellen, daarna de vraag met antwoordopties. Er is geen OCR, hertekening of retouche toegepast; antwoorden en beoordeling staan alleen in de JSON. Snijlijnen liggen in witruimte tussen blokken (automatisch gecontroleerd: geen tekst of figuur doorgesneden).

## JSON-koppeling
`questions[].snippet_file` verwijst naar de PNG; `source_fragments[]` geeft per fragment het bronbestand, het 1-gebaseerde PDF-paginanummer, genormaliseerde coördinaten (x, y, width, height; linksboven = 0,0 op de volledige pagina), de volgorde en de reden. `answer_data`: meerkeuze `correct_answer`; open vragen `model_answer`, `scoring` (best effort, `kind` = criterion of tier), `raw_text` (volledige correctietekst), `remarks`, `maximum_score`, evt. `supplement`. `quality_check.automatic_checks` zijn geautomatiseerd; de overige velden zijn door Claude na visuele controle gezet.

## Beperkingen
- Contextkeuze per vraag is regelgebaseerd + handmatige aanvulling na visuele controle; geen controle door een vakdocent.
- Uitwerkbijlagen (alleen havo 2025 t1 en vwo 2026 t2): het relevante deel is bij de betreffende vragen als laatste fragment in de snippet opgenomen (`source_document` = `uitwerkbijlage`).
- Aanvullingen op het correctievoorschrift (havo 2026 t1 vraag 16, vwo 2024 t1 vraag 32) staan in `answer_data.supplement`.
- Geen deelvragen (a/b) aangetroffen in de verwerkte examens; alle vragen zijn genummerd 1..N.
