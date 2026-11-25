# Wijzigingen Examenverwerker 0.18

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
