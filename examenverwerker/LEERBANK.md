# Leerbank: beslissingen en herbruikbare kennis

De leerbank is lokaal per gebruiker/project te bewaren en kan desgewenst worden geëxporteerd. Er worden geen examen-PDF's of persoonsgegevens naar een externe dienst gestuurd.

## Kennissoorten
- Documentpatronen: bestandsnamen, kopteksten, examenmetadata en rolherkenning.
- Vraagpatronen: nummerposities, typografie, antwoordopties en doorlopende vragen.
- Layoutprofielen: paginamarges, kolommen, vaste koppen, vraagnummering en figuurposities.
- Contextrelaties: contextstart/einde, figuur- en tabelverwijzingen, bijschriften en doorlopende contexten.
- Correcties: goedgekeurde of afgewezen voorstellen plus reden.
- Exportprofielen: mapping naar de bestaande websitevelden.

## Voorbeeld van een beslissing
Een beslissing bevat minimaal `id`, `tijd`, `project_id`, `document_hash`, `pagina`, `objecttype`, `voorgesteld`, `gekozen`, `reden`, `scope`, `softwareversie` en `bevestigingsstatus`.

## Toepassing
Bij een nieuw examen toont het systeem passende eerdere voorbeelden als onderbouwing. De docent kan een patroon accepteren, aanpassen of afwijzen. De uitkomst wordt weer opgeslagen. Een patroon krijgt pas meer automatische invloed na herhaalde bevestiging en regressietests.
