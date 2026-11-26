# Wijzigingen Examenverwerker 0.18


## Visuele antwoordopties en compacte stap-3-inspector

- Maak contextgroepkaarten in de rechter inspector compacter, zodat de lange examenstrook in het middendeel visueel leidend blijft.
- Ondersteun meerkeuzeopties als tekst, afbeelding of combinatie van beide.
- Laat de docent grafische antwoordopties rechtstreeks uit een vraagfragment uitsnijden met een sleepkader; de crop gebruikt de originele afbeeldingspixels.
- Sla uitsneden als begrensde lokale PNG/JPEG-data op in de bestaande vraaganalyse-evidence. De bron-PDF blijft ongewijzigd.
- Laat bestaande automatisch herkende antwoordletters behouden en koppel er een afbeelding aan; de bronpagina is selecteerbaar bij meerpagina-vragen.
- Behoud beeldopties bij heropenen en toon ze opnieuw in de integrale eindcontrole.
- Vereis bij een expliciet goedgekeurde meerkeuzevraag minimaal twee complete antwoordopties.
- Voeg regressietests toe voor beeldopties, PNG-validatie, heropenen, opslag en de compacte inspector.


## Zelflerende detectie

- Voeg een uitlegbare leerlaag toe die expliciete docentcorrecties bewaart als gelabelde detectievoorbeelden.
- Leg feedback op vraagstartdetecties pas vast wanneer de docent de betreffende stap expliciet afrondt; autosaves worden niet als trainingsdata gebruikt.
- Bereken acceptatiepercentages per detectiekenmerk, uitgesplitst naar documenttype.
- Gebruik alleen kenmerken met minimaal vijf gecontroleerde voorbeelden als beperkt rangschikkingssignaal.
- Beperk de invloed van geleerde feedback tot maximaal 0,15 scorepunt.
- Toon bij ieder voorstel de geleerde kenmerken en de onderliggende voorbeeldtelling.
- Automatische detectie mag nooit een vraagstart goedkeuren, verwijderen of een bestaande docentbeslissing overschrijven.

## Reikwijdte van deze eerste iteratie

De eerste werkende leerkring betreft vraagstarts. De opslag en feedbackstructuur is voorbereid op uitbreiding naar fragmentgrenzen en contextgroepen. Die twee detectietypen worden in volgende iteraties aangesloten, met aparte labels voor verplaatste boven- en ondergrenzen en gewijzigde contextbereiken.
