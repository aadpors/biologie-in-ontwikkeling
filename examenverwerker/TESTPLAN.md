# Praktijktestplan — Biologie Examenverwerker 0.7.0

Gebruik voor de eerste praktijktest één examen waarvan de opgaven, het correctievoorschrift en eventuele aanvullingen beschikbaar zijn. Test eerst met een kopie van de PDF's en bewaar het project buiten de programmamap.

## 1. Eerste project
- [ ] Maak een nieuw project voor één examen.
- [ ] Voeg de opgaven-PDF, het officiële correctievoorschrift, alle relevante aanvullingen en eventuele uitwerkbijlage toe.
- [ ] Controleer per document het herkende type.
- [ ] Bevestig niveau, jaar en tijdvak bij **Examengegevens controleren**.
- [ ] Controleer dat opgaven en CV exact bij elkaar horen.

## 2. Vraagnummering
- [ ] Analyseer de vraagstarts.
- [ ] Bekijk iedere kandidaat op de originele pagina.
- [ ] Bevestig iedere echte vraagstart en wijs iedere onjuiste kandidaat af.
- [ ] Controleer de nummering met het officiële CV; gebruik het CV als onafhankelijke controle, niet als automatische waarheid.

## 3. Opgavenstructuur
- [ ] Open **Examenstructuur bewerken**.
- [ ] Maak een contextinleiding en controleer dat deze standaard aan alle vragen gekoppeld wordt.
- [ ] Maak voor ten minste één vraag een vraagcontext en koppel die uitsluitend aan de juiste vraag.
- [ ] Maak voor ten minste één vraag een vraagfragment.
- [ ] Maak waar aanwezig een tussenliggende context.
- [ ] Laat ten minste één fragment over twee pagina's lopen.
- [ ] Verplaats een bestaande grens en controleer dat de wijziging wordt opgeslagen.
- [ ] Controleer dat de grijze arcering buiten de lijnen staat en dat de originele PDF niet verandert.

## 4. Correctievoorschrift en aanvullingen
- [ ] Open een vraagrecord en kies het juiste correctievoorschrift.
- [ ] Baken de beoordelingsregels voor de vraag af.
- [ ] Laat een CV-fragment over twee pagina's lopen.
- [ ] Controleer dat bij paginawisselen geen onbedoelde volledige pagina wordt toegevoegd.
- [ ] Selecteer een officiële aanvulling en bak ook daarvan de relevante regels af.
- [ ] Controleer de gerenderde CV- en aanvullingsuitsneden tegen de originele PDF-pagina's.

## 5. Context, figuren en bijschriften
- [ ] Controleer de automatisch voorgestelde figuur-/tabeluitsneden.
- [ ] Selecteer alleen materiaal dat bij de context of vraag hoort.
- [ ] Corrigeer of bevestig ieder bijschrift; bevestig expliciet wanneer een uitsnede geen bijschrift heeft.
- [ ] Controleer de volledige originele pagina naast de uitsnede.
- [ ] Controleer en corrigeer de geëxtraheerde contexttekst in het vraagrecord.

## 6. Eindcontrole en export
- [ ] Controleer de vraagtekst, het vraagtype, de antwoordopties en het puntenaantal.
- [ ] Controleer vraagfragment, contextfragmenten, contextafbeeldingen en captions.
- [ ] Controleer CV en eventuele aanvullingen.
- [ ] Controleer alle pagina's van de uitwerkbijlage.
- [ ] Vink alleen onderdelen af die werkelijk zijn gecontroleerd.
- [ ] Keur het vraagrecord expliciet goed.
- [ ] Maak een exportpakket.
- [ ] Controleer `exam-open.json`, `exam-mcq.json`, `exam-contexts.json`, `cv-snippets.json`, `examens/` en `manifest.json`.

## 7. Veiligheids- en regressietests
- [ ] Wijzig na het opslaan een vraaggrens. Het bestaande vraagrecord moet opnieuw gecontroleerd en opgeslagen moeten worden.
- [ ] Wijzig na het opslaan een CV-grens. Het bestaande vraagrecord moet opnieuw gecontroleerd en opgeslagen moeten worden.
- [ ] Wijzig een bron-PDF na afbakening. Export moet worden geblokkeerd.
- [ ] Verwijder een benodigde uitsnede of wijzig het PNG-bestand handmatig. Export moet worden geblokkeerd.
- [ ] Probeer een vraagrecord zonder handmatig vraagfragment of CV-fragment goed te keuren. Dit moet worden geblokkeerd.

## Verwacht resultaat
De vraagafbeelding bevat alleen het handmatig afgebakende vraagfragment. Contextafbeeldingen en contexttekst zijn afzonderlijk gekoppeld. De CV-uitsnede bevat alle beoordelingsregels voor de juiste vraag. Het exportmanifest bevat bronhashes, fragmentgrenzen, koppelingen en hashes van de uitsneden. Geen enkele stap publiceert iets naar de live website.
