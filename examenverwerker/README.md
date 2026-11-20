# Examenverwerker

Een zelfstandige Windows-applicatie om examen-PDF's vakoverstijgend te verwerken. De basisworkflow is bedoeld voor onder meer biologie, aardrijkskunde en andere schoolvakken. Vakinhoudelijke publicatie- of beoordelingsvelden worden niet tijdens de fragmentselectie afgedwongen.

## Verwerkingsworkflow

De examenbibliotheek is het hoofdvenster. Elk geopend examen krijgt een eigen verwerkingsvenster; de bibliotheek blijft open en meerdere examens kunnen naast elkaar worden verwerkt.

1. **Documenteigenschappen** — bepaal op basis van bestandsnaam en eerste PDF-pagina het vak, niveau, jaar, tijdvak en documenttype. Bevestig de documenttypen: opgaven (`-o`), correctievoorschrift (`-c`), aanvulling CV (`-a`) en uitwerkbijlage (`-u`).
2. **Vraagstarts opgaven** — detecteer vraagstarts automatisch; beoordeel kandidaten, wijs onterechte signalen af en voeg ontbrekende vraagstarts handmatig toe.
3. **Context- en vraagfragmenten** — gebruik de opgeslagen visuele fragmentgrenzen en contextkoppelingen. Een eerder gecontroleerde structuur wordt niet opnieuw ter bevestiging voorgelegd.
4. **Vraaganalyse** — maak automatisch conceptrecords vanuit de bevestigde vraagfragmenten. Controleer per vraag de vraagtekst, het vraagtype, het puntenaantal en de antwoordopties.
5. **Vraagstarts uitwerkbijlage** — detecteer en beoordeel de vraagankers; bevestig expliciet wanneer er geen afzonderlijke ankers zijn.
6. **Uitwerkbijlagefragmenten** — baken de relevante delen per vraag af in de originele PDF.
7. **Vraagstarts correctievoorschrift** — detecteer en beoordeel de vraagankers in het officiële correctievoorschrift.
8. **CV-fragmenten** — baken per vraag alle beoordelingsregels en punten af. Dezelfde visuele uitsnij- en samenvoegtechniek wordt gebruikt als bij de opgaven.
9. **Aanvulling CV** — classificeer per vraag toevoeging, wijziging, vervanging, intrekking of ongewijzigd. Genereer en controleer daarna de samengestelde, herleidbare CV-PDF. Bron-CV en aanvulling blijven afzonderlijk en ongewijzigd.
10. **Correcte antwoorden** — controleer de antwoordsleutel, ook voor ja/nee-, waar/onwaar-, hoger/lager- en meer/minder-vraagvormen.
11. **Volledigheid** — controleer dubbele of ontbrekende vraagnummering, fragmenten, contextkoppelingen, bronintegriteit en puntenaantallen.
12. **Definitieve uitsneden** — genereer vraag- en contextuitsneden pas nadat de grenzen zijn vastgelegd. Witruimte aan boven- en onderzijde wordt op basis van de feitelijke beeldinhoud verwijderd; de broncoördinaten blijven behouden.
13. **Visuele eindcontrole** — controleer per vraag de originele opgavenpagina's, contextfragmenten, vraag, opties, uitwerkbijlage, CV en eventuele aanvulling. Herstelacties openen de betreffende editor; de eindcontrole keert terug naar dezelfde vraag.

## Ontwerpkeuzes

- Ingebedde PDF-tekst wordt eerst gebruikt. OCR wordt alleen geprobeerd op de eerste pagina of op pagina's/geselecteerde fragmenten waar de tekstlaag ontbreekt of aantoonbaar onvoldoende is. OCR vereist een beschikbare Tesseract-installatie; zonder die blijft beeldinhoud visueel te beoordelen en wordt geen vraagtype geraden.
- Automatische detecties zijn voorstellen. Alleen expliciet bevestigde vraagstarts, fragmenten, antwoorden en eindcontroles tellen als gecontroleerd.
- Vraagtype en punten worden uitsluitend bepaald vanuit het bevestigde vraagfragment, niet vanuit opnieuw gedetecteerde vraaggrenzen.
- Bestaande lokaal gecontroleerde fragmentgrenzen blijven behouden. Er worden geen extra vinkrondes voor dezelfde grenzen toegevoegd.
- Uitsneden worden rechtstreeks uit de originele PDF gerenderd. Opgaven, correctievoorschrift, aanvullingen en uitwerkbijlagen blijven als bronbestanden ongewijzigd.
- Wijzigingen aan bronfragmenten maken afgeleide controles opnieuw ongeldig. De applicatie gebruikt bronhashes en review-fingerprints om verouderde goedkeuringen te herkennen.
- De export is een afzonderlijk gecontroleerd pakket; er wordt niets automatisch naar de live website gepubliceerd.

## Installeren en starten

1. Download en pak de volledige ZIP-map uit.
2. Dubbelklik op **START.bat**.
3. De doelcomputer heeft geen Python-installatie of administratorrechten nodig.

Vervang bij een software-update alleen de programmamap. Projecten en de leerbank staan apart onder `%LOCALAPPDATA%\BiologieExamenverwerker\`; de bestaande projectbestanden worden niet door het vervangen van de programmamap overschreven. Maak desondanks regelmatig een reservekopie van deze gegevens.

## Ontwikkelomgeving

Voor ontwikkelen is Python 3.12 vereist:

```bat
python -m pip install -r requirements.txt
python app.py
```

De regressietests starten met:

```bat
python -m unittest discover -s tests -v
```

## Grenzen van deze versie

- De automatische vraaggrens is een voorstel; controleer altijd of de eerstvolgende witregel of kadergrens ook inhoudelijk de juiste grens is.
- Bij beeldvragen zonder uitleesbare tekst blijft de vraagtypeanalyse onzeker.
- De conceptexport is een overdraagbaar gegevenspakket, geen websitepublicatie.
- De portable Windows-build is automatisch getest in CI; test de gebruikersinterface daarnaast op een echte Windows-computer met eigen examens.
