# Biologie Examenverwerker

Een zelfstandige Windows-mapapplicatie voor het zorgvuldig verwerken van biologie-examens. De bestaande website en examendata worden niet gewijzigd.

## Wat deze ontwikkelversie al kan
- Examenprojecten aanmaken, openen en hervatten.
- Originele PDF's ongewijzigd opnemen en SHA-256-dedupliceren.
- Documenttypen voorstellen: opgaven, correctievoorschrift, uitwerkbijlage en aanvulling.
- PDF-tekst, metadata, pagina's en geometrie uitlezen.\n- Rasterafbeeldingen en grotere vectorregio's in originele PDF's inventariseren.\n- Figuur- en tabelverwijzingen koppelen aan mogelijke bijschriften en beeldregio's, zonder automatische goedkeuring.
- Pagina's zonder bruikbare tekst markeren voor OCR-controle.
- Mogelijke vraagstarts detecteren, ook bij losse nummerregels en dubbele nummers.
- Opgaven- en CV-nummering als controlesignaal vergelijken.
- Originele bronpagina's visueel tonen.
- Voorlopige vraagfragmenten renderen uit exacte PDF-paginaregio's, ook over paginagrenzen.\n- Concept-vraagrecords samenstellen met bewerkbare vraagtekst, metadata, antwoordopties, CV-koppeling en uitwerkbijlagen.\n- Correctievoorschriftfragmenten over meerdere pagina's samenvoegen tot één controleerbare afbeelding.
- Menselijke beslissingen opslaan in een lokale leerbank.
- Optionele externe AI-adapter gebruiken na expliciete toestemming; standaard volledig offline.
- Een exportpoort gebruiken die niet-goedgekeurde of onvolledige records blokkeert en originele uitwerkbijlagen volledig meeneemt.

## Starten voor ontwikkeling
1. Installeer Python 3.12.
2. Open deze map in een terminal.
3. Voer uit: \`python -m pip install -r requirements.txt\`
4. Start met \`python app.py\` of dubbelklik op \`START.bat\`.

## Portable Windows-programma bouwen
Op een Windows-machine met Python 3.12:
1. Dubbelklik op \`BUILD_PORTABLE.bat\`.
2. Wacht tot de bouw klaar is.
3. Kopieer de volledige map \`dist\\BiologieExamenverwerker\\\` naar een USB-stick of gewenste locatie.
4. Start daar \`START.bat\`.

De doelcomputer heeft daarna geen Python-installatie of administratorrechten nodig. De applicatie installeert niets in Windows. De centrale map `kennisbank/` staat naast het programma; bewaar deze map bij updates om de opgebouwde leerervaring te behouden.

Een GitHub Actions-workflow kan daarnaast een Windows-portable artifact bouwen.

## Werkwijze
1. Maak één project per examen.
2. Voeg alle beschikbare PDF's tegelijk toe.
3. Controleer de voorgestelde documentrollen én de examenidentiteit per PDF (niveau, jaar en tijdvak).
4. Laat vraagstarts analyseren.
5. Bekijk kandidaten op de originele pagina en bevestig of wijs ze af.
6. Maak voorlopige snippets en controleer de volledige context, figuren, tabellen, bijschriften en leesbaarheid.
7. Controleer CV, aanvullingen en uitwerkbijlagen.
8. Exporteer pas nadat ieder record volledig en menselijk goedgekeurd is.

## Betrouwbaarheidsregels
- Originele PDF's worden nooit aangepast.
- Een nummerpatroon is nooit automatisch een examenvraag.
- Een voorlopige snippet is nooit automatisch compleet.
- Gedeelde context, figuren en bijschriften kunnen buiten een vraagfragment vallen; controle is verplicht.
- Scans zonder tekstlaag worden gemarkeerd; OCR wordt niet stilzwijgend gesimuleerd.
- AI mag voorstellen doen, maar nooit bronmateriaal verzinnen of iets goedkeuren.
- Geen automatische publicatie naar de live website.
- Bestaande uitvoermappen worden nooit overschreven.

## Bekende grenzen van deze ontwikkelfase
- OCR voor gescande pagina's is nog niet ingebouwd.
- Vraaggrenzen en contextkoppelingen vragen nog menselijke bevestiging.
- CV-nummering is een signaal en moet inhoudelijk worden gecontroleerd.
- De aparte eindcontrole-/goedkeuringsinterface en exportbediening moeten nog worden afgerond; de exportpoort zelf blokkeert onvolledige records.\n- Automatische contextkoppelingen zijn uitsluitend kandidaten op basis van PDF-geometrie en bijschriften; inhoudelijke koppeling blijft handwerk.
- De portable build moet nog op een echte Windows 11-computer worden gestart en met representatieve examenbestanden worden getest.

Zie ook \`ONTWERP.md\`, \`SCHEMA.md\`, \`VALIDATIE.md\`, \`LEERBANK.md\`, \`EXPORT.md\` en \`PRIVACY.md\`.
