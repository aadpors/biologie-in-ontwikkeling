# Examenverwerker 0.18

Versie 0.18 bouwt voort op de stabiele documentverwerking van 0.17 en introduceert een uitlegbare, feedbackgestuurde detectielaag.

## Zelflerende detectie

De applicatie bewaart expliciet gecontroleerde docentbeslissingen als leervoorbeelden. Voor vraagstarts worden kenmerken zoals kandidaatvorm, relatieve nummerkolom, verticale paginazone, lettergrootte en detectiewaarschuwingen vastgelegd. Absolute pixelcoördinaten worden niet als algemene leerregel gebruikt.

Een kenmerk wordt pas actief nadat er minimaal vijf gecontroleerde voorbeelden beschikbaar zijn. De geleerde informatie levert uitsluitend een beperkte rangschikkingshint op. De detector blijft conservatief: geen automatische goedkeuring, geen stilzwijgende verwijdering en geen overschrijving van eerder opgeslagen docentbeslissingen.

De leerprofielen zijn per documenttype gescheiden. Zo worden opgaven, uitwerkbijlagen en correctievoorschriften niet zonder bewijs als dezelfde lay-out behandeld.

## Visuele antwoordopties in stap 4

Meerkeuzeopties worden als afzonderlijke records opgeslagen. Een optie kan tekst, een afbeelding of een combinatie bevatten. Wanneer een antwoordmogelijkheid uit een grafiek, schema, stamboom of respirogram bestaat, kan de docent de uitsnede rechtstreeks op de zichtbare vraagafbeelding selecteren.

- Gebruik de knop onder een bronpagina om nieuwe afbeeldingsopties in lettervolgorde A–F toe te voegen.
- Wanneer OCR de antwoordletters al heeft herkend, kan de docent via de betreffende optie een afbeelding toevoegen of vervangen.
- Bij meerpagina-vragen kiest de docent eerst de bronpagina.
- De selectie wordt uit de oorspronkelijke pixels van de gerenderde PDF-pagina gemaakt en als PNG opgeslagen; de bron-PDF verandert niet.
- De uitsnede wordt samen met de overige vraaganalyse in de bestaande examenevidence bewaard en verschijnt opnieuw in de integrale eindcontrole.
- Zodra de docent de antwoordoptielijst zelf wijzigt, wordt die lijst expliciet leidend. Verwijderde OCR-opties keren daardoor niet terug bij het opnieuw openen.
- Een vraag kan pas als gecontroleerde meerkeuzevraag worden goedgekeurd wanneer minimaal twee complete antwoordopties zijn vastgelegd.

De afbeelding wordt niet door OCR geïnterpreteerd. De docent controleert de visuele inhoud en de koppeling met de antwoordletter.

## API

- `GET /api/exams/{exam_id}/learning-profile`: transparant overzicht van beschikbare leervoorbeelden en actieve kenmerken.
- Vraagstartreviews worden als leervoorbeeld opgeslagen bij het expliciet afronden van de betreffende detectiestap.

## Uitbreiding

De leerkring omvat vraagstarts, fragmentgrenzen en contextgroepen. Vraagstartkenmerken worden gebruikt als uitlegbare rangschikkingshint. Handmatig aangepaste fragmentgrenzen worden als offsets ten opzichte van de automatische referentie bewaard en per documenttype samengevat. Correcties op contextgroepen leveren mediane verschuivingen van het vraagbereik op; vanaf vijf voorbeelden worden die toegepast op nieuwe tekstgebaseerde contextvoorstellen. Handmatig geselecteerde contexten en eerder opgeslagen docentbeslissingen blijven onaangetast.

 
## Veilige testomgeving

- `start.bat` gebruikt de gedeelde gegevensmap van de examenverwerker. Bestaande examens blijven daarin beschikbaar.
- `start-test.bat` start dezelfde applicatie met een **afzonderlijke** gegevensmap (`test-data/` in deze versie-map). Daarmee kunnen nieuwe imports en bugtests worden uitgevoerd zonder de bestaande examendatabase te wijzigen. Stop een eventueel draaiende server eerst met `Ctrl+C`; de testlauncher gebruikt eveneens poort 8000.
- De testbibliotheek is bewust leeg. Importeer er een kopie of nieuw testexamen; de bestaande tweede examenimport staat niet in deze testbibliotheek.
- `test-data/` is uitgesloten van Git.
