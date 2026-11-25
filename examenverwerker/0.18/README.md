# Examenverwerker 0.18

Versie 0.18 bouwt voort op de stabiele documentverwerking van 0.17 en introduceert een uitlegbare, feedbackgestuurde detectielaag.

## Zelflerende detectie

De applicatie bewaart expliciet gecontroleerde docentbeslissingen als leervoorbeelden. Voor vraagstarts worden kenmerken zoals kandidaatvorm, relatieve nummerkolom, verticale paginazone, lettergrootte en detectiewaarschuwingen vastgelegd. Absolute pixelcoördinaten worden niet als algemene leerregel gebruikt.

Een kenmerk wordt pas actief nadat er minimaal vijf gecontroleerde voorbeelden beschikbaar zijn. De geleerde informatie levert uitsluitend een beperkte rangschikkingshint op. De detector blijft conservatief: geen automatische goedkeuring, geen stilzwijgende verwijdering en geen overschrijving van eerder opgeslagen docentbeslissingen.

De leerprofielen zijn per documenttype gescheiden. Zo worden opgaven, uitwerkbijlagen en correctievoorschriften niet zonder bewijs als dezelfde lay-out behandeld.

## API

- `GET /api/exams/{exam_id}/learning-profile`: transparant overzicht van beschikbare leervoorbeelden en actieve kenmerken.
- Vraagstartreviews worden als leervoorbeeld opgeslagen bij het expliciet afronden van de betreffende detectiestap.

## Uitbreiding

De eerste leerkring betreft vraagstarts. Dezelfde feedbackopslag wordt in volgende iteraties aangesloten op fragmentgrenzen en contextgroepen. Daarbij worden voorgestelde en definitief gecorrigeerde grenzen afzonderlijk bewaard, zodat de leerfunctie alleen leert van expliciete menselijke correcties.
