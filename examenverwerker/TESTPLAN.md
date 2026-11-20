# Praktijktestplan — Examenverwerker 0.17.0

Voer de eerste praktijktest uit met een kopie van één volledig examen: opgaven, correctievoorschrift, eventuele CV-aanvulling en uitwerkbijlage. Bewaar de originele PDF's en maak een reservekopie van het project.

## 1. Bibliotheek en werkruimten
- [ ] Start via `START.bat`; de examenbibliotheek is het hoofdvenster.
- [ ] Open één examen en controleer dat een afzonderlijk verwerkingsvenster opent.
- [ ] Open een tweede examen; controleer dat beide werkruimten onafhankelijk blijven bestaan.
- [ ] Sluit een verwerkingsvenster; controleer dat de bibliotheek open blijft.
- [ ] Controleer dat projectgegevens buiten de programmamap staan onder `%LOCALAPPDATA%\BiologieExamenverwerker\projecten`.

## 2. Documenteigenschappen
- [ ] Importeer de opgaven, CV, aanvulling en uitwerkbijlage.
- [ ] Controleer de suffixherkenning: `-o`, `-c`, `-a` en `-u`.
- [ ] Controleer documenttype en examenmetadata uitsluitend aan de hand van bestandsnaam en eerste pagina.
- [ ] Corrigeer en bevestig niveau, jaar, tijdvak en documenttype.
- [ ] Controleer dat documenten van andere examens of tijdvakken niet worden gekoppeld.

## 3. Vraagstarts en opgavenfragmenten
- [ ] Analyseer de vraagstarts in de opgaven.
- [ ] Bekijk iedere kandidaat op de originele PDF-pagina; bevestig echte starts en wijs onterechte signalen af.
- [ ] Voeg ten minste één ontbrekende vraagstart handmatig toe.
- [ ] Controleer dat dubbele of ontbrekende nummering zichtbaar wordt gemeld.
- [ ] Open de opgeslagen examenstructuur. Controleer dat eerder bevestigde fragmentgrenzen niet opnieuw ter bevestiging worden voorgelegd.
- [ ] Controleer vraag- en contextfragmenten, inclusief een fragment dat over twee pagina's loopt.
- [ ] Verplaats een contextgrens en controleer dat de gekoppelde vraagcontext meebeweegt.
- [ ] Controleer dat de bron-PDF en de oorspronkelijke coördinaten behouden blijven.

## 4. Vraaganalyse
- [ ] Open elk conceptvraagrecord dat uit de bevestigde fragmenten is opgebouwd.
- [ ] Controleer en corrigeer de vraagtekst.
- [ ] Stel het vraagtype vast: meerkeuze, open, juist/onjuist, ja/nee, hoger/lager, meer/minder of onbekend.
- [ ] Vul het gehele puntenaantal in.
- [ ] Controleer antwoordopties en antwoordsleutel bij meerkeuzevragen.
- [ ] Controleer dat een onbekend vraagtype niet stilzwijgend als open vraag wordt gepubliceerd.

## 5. Uitwerkbijlage
- [ ] Laat vraagankers automatisch detecteren en beoordeel de kandidaten.
- [ ] Bevestig expliciet wanneer geen afzonderlijke vraagankers aanwezig zijn.
- [ ] Baken voor relevante vragen de bijbehorende uitwerkbijlagefragmenten af.
- [ ] Controleer een fragment over meerdere pagina's en de koppeling aan het juiste vraagnummer.

## 6. Correctievoorschrift
- [ ] Laat vraagankers in het officiële CV detecteren en visueel beoordelen.
- [ ] Bevestig expliciet wanneer geen afzonderlijke vraagankers aanwezig zijn.
- [ ] Baken per vraag alle relevante beoordelingsregels en punten af.
- [ ] Controleer een CV-fragment over meerdere pagina's.
- [ ] Vergelijk de uitsnede met de originele CV-pagina's; controleer dat geen tekst of afbeelding is afgeknipt.

## 7. Aanvulling CV en consolidatie
- [ ] Voeg een officiële aanvulling toe met suffix `-a`.
- [ ] Classificeer per vraag: toevoeging, wijziging, vervanging, intrekking of ongewijzigd.
- [ ] Baken de relevante aanvullingsfragmenten af voor gewijzigde vragen.
- [ ] Genereer de geconsolideerde CV-PDF.
- [ ] Controleer de PDF visueel; controleer dat vervangingen, toevoegingen en intrekkingen correct zijn weergegeven.
- [ ] Controleer dat de originele CV en aanvulling ongewijzigd blijven.
- [ ] Controleer dat de geconsolideerde CV-PDF en bronverwijzingen in het exportpakket terechtkomen.

## 8. Correcte antwoorden en volledigheid
- [ ] Controleer de correcte antwoorden aan de hand van het officiële CV.
- [ ] Controleer ook binaire en vergelijkende antwoordvormen: ja/nee, waar/onwaar, hoger/lager en meer/minder.
- [ ] Voer de volledigheidscontrole uit.
- [ ] Controleer dubbele/ontbrekende nummering, losse contextfragmenten, ontbrekende vraagfragmenten, puntenaantallen en bronintegriteit.
- [ ] Controleer de som van de ingevulde punten.

## 9. Definitieve uitsneden
- [ ] Genereer de definitieve vraag- en contextuitsneden nadat de grenzen vaststaan.
- [ ] Controleer dat de boven- en ondermarge op basis van niet-witte beeldinhoud zijn bijgesneden.
- [ ] Controleer dat tekst, figuren en onderschriften niet zijn afgeknipt.
- [ ] Controleer dat bron-PDF's en fragmentcoördinaten niet zijn gewijzigd.

## 10. Visuele eindcontrole en herstel
- [ ] Open de eindcontrole per vraag.
- [ ] Controleer achtereenvolgens context, vraag, antwoordopties, uitwerkbijlage, oorspronkelijk CV en geconsolideerd CV.
- [ ] Gebruik de herstelacties voor een vraagtekst, vraag/contextgrens, CV-fragment, uitwerkbijlage of aanvulling.
- [ ] Controleer dat de juiste vraag en het juiste fragment in de editor geselecteerd zijn.
- [ ] Sla een wijziging op en controleer dat de eindcontrole terugkeert naar dezelfde vraag.
- [ ] Controleer dat een inhoudelijke wijziging verouderde goedkeuringen ongeldig maakt.
- [ ] Keur een vraag pas goed als alle relevante onderdelen werkelijk zijn gecontroleerd.

## 11. Export en gegevensbehoud
- [ ] Maak het exportpakket nadat alle vragen zijn goedgekeurd.
- [ ] Controleer de vraaggegevens, contextuitsneden, CV-fragmenten, bronmanifesten en eventuele geconsolideerde CV-PDF.
- [ ] Controleer dat er niets automatisch naar de live website wordt gepubliceerd.
- [ ] Sluit de applicatie en open het project opnieuw.
- [ ] Controleer dat fragmentgrenzen, goedkeuringen, uitsneden en bronbestanden behouden zijn.
- [ ] Voer een software-update uit door alleen de programmamap te vervangen; wijzig of overschrijf de lokale map `projecten` niet.

## Verwacht resultaat
Alle opgaven, vragen, contexten, uitwerkbijlagen en CV-fragmenten zijn volledig gekoppeld en visueel gecontroleerd. Het exportpakket bevat de gecontroleerde vraaggegevens, uitsneden, bronhashes en indien van toepassing de geconsolideerde CV-PDF. Bronbestanden blijven ongewijzigd en er vindt geen automatische websitepublicatie plaats.
