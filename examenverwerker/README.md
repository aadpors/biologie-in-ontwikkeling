# Biologie Examenverwerker

Een zelfstandige Windows-mapapplicatie voor het zorgvuldig verwerken van biologie-examens. De bestaande website en examendata worden niet gewijzigd.

## Wat deze ontwikkelversie al kan
- Examenprojecten aanmaken, openen en hervatten.
- Originele PDF's ongewijzigd opnemen en SHA-256-dedupliceren.
- Documenttypen voorstellen: opgaven, correctievoorschrift, uitwerkbijlage en aanvulling.
- PDF-tekst, metadata, pagina's en geometrie uitlezen.
- Rasterafbeeldingen en grotere vectorregio's in originele PDF's inventariseren.
- Figuur- en tabelverwijzingen koppelen aan mogelijke bijschriften en beeldregio's, zonder automatische goedkeuring.
- Pagina's zonder bruikbare tekst markeren voor OCR-controle.
- Mogelijke vraagstarts detecteren, ook bij losse nummerregels en dubbele nummers.
- Opgaven- en CV-nummering als controlesignaal vergelijken.
- Originele bronpagina's visueel tonen.
- Voorlopige vraagfragmenten renderen uit exacte PDF-paginaregio's, ook over paginagrenzen.
- Concept-vraagrecords samenstellen met bewerkbare vraagtekst, metadata, antwoordopties, exact gekoppelde CV's, uitwerkbijlagen en officiële CV-aanvullingen.
- Volledige CV-antwoorden over meerdere pagina's samenvoegen tot één controleerbare afbeelding.
- Een expliciete menselijke eindcontrole uitvoeren met checklist, visuele bronvoorbeelden en herroepbare goedkeuring.
- Per opgaven-PDF een afzonderlijke visuele structuur vastleggen, met volledige paginabrede vraag- en contextgrenzen.
- Alle handmatige uitsneden zijn horizontale stroken over de volledige paginabreedte; alleen boven- en ondergrens zijn instelbaar, nooit linker- of rechtergrenzen.
- Per vraag het originele correctievoorschrift én geselecteerde officiële aanvullingen met dezelfde versleepbare grenzen afbakenen.
- Vraag-, context-, CV- en aanvullingsuitsneden rechtstreeks uit de oorspronkelijke PDF's renderen; contextafbeeldingen en bijschriften gescheiden houden van de vraagafbeelding.
- Selecteerbare contexttekst uit handmatig begrensde bronregio's bewaren.
- Een veilig exportpakket samenstellen; de exportpoort controleert de checklist, bronhashes, vraaggrenzen, CV-regio's en contextbestanden opnieuw.
- Correctievoorschriftfragmenten over meerdere pagina's samenvoegen tot één controleerbare afbeelding.
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
5. Bekijk kandidaten op de originele pagina en bevestig of wijs iedere kandidaat af. Alle kandidaten moeten een menselijke beslissing hebben.
6. Open 'Examenstructuur bewerken' voor iedere opgaven-PDF. Maak voor elke vraag een vraagfragment en leg contextinleidingen, vraagcontexten en tussenliggende contexten vast. Koppel ieder contextfragment aan de juiste vragen.
7. Maak per vraag een voorlopig snippetvoorstel om mogelijke figuren, tabellen en tekstregio's te inventariseren. Dit zijn alleen kandidaten.
8. Maak het concept-vraagrecord. Selecteer de juiste CV-PDF en bak het beoordelingsmodel voor die vraag handmatig af. Voeg alle vervolgpagina's toe. Doe hetzelfde voor iedere geselecteerde officiële CV-aanvulling.
9. Selecteer alleen figuren, tabellen en tekstregio's die aantoonbaar bij de vraag horen. Corrigeer of bevestig per geselecteerde figuur/tabel het bijschrift (ook expliciet als er geen bijschrift is). Controleer uitsneden en contexttekst. De handmatig afgebakende contextfragmenten en hun tekst worden automatisch gekoppeld.
10. Controleer alle pagina's van uitwerkbijlagen en CV-aanvullingen.
11. Open 'Vraagrecords beoordelen en goedkeuren', vergelijk alle fragmenten met de volledige originele PDF's, vink alleen werkelijk gecontroleerde onderdelen af en keur ieder record expliciet goed.
12. Maak pas daarna een exportpakket. Ontbrekende of verouderde vraag- en CV-afbakeningen blokkeren export. Dit wijzigt of publiceert niets op de live website.

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
- Vraaggrenzen, contextkoppelingen, CV-fragmenten en beeldselecties vragen menselijke bevestiging.
- De visuele CV-editor en de volledige exportketen zijn door CI getest; de gebruikersinterface moet nog praktisch op Windows 11 met echte examens worden beproefd.
- CV-nummering is een signaal en moet inhoudelijk worden gecontroleerd.
- De eindcontrole is expliciet en handmatig; visuele signalen of AI mogen nooit een vinkje of goedkeuring zetten.
- Automatische contextkoppelingen zijn uitsluitend kandidaten op basis van PDF-geometrie en bijschriften; inhoudelijke koppeling blijft handwerk.
- De portable build moet nog op een echte Windows 11-computer worden gestart en met representatieve examenbestanden worden getest.

Zie ook \`ONTWERP.md\`, \`SCHEMA.md\`, \`VALIDATIE.md\`, \`LEERBANK.md\`, \`EXPORT.md\` en \`PRIVACY.md\`.
