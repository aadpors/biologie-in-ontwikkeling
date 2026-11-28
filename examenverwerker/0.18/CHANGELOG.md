# Versie 0.18.6 — stap 3 fragmentreview

- Contextgroepoverzicht is compacter: de losse vraagfragmentkaartjes worden niet langer onder iedere contextgroep herhaald; de details blijven beschikbaar via Contextdelen bekijken.
- Scrollposities van de examenstrook en inspector worden bij het opnieuw renderen behouden, zodat het beeld niet springt na het verschuiven van fragmentgrenzen.
- De automatische opslagdebounce na veldwijzigingen is verkort tot 90 ms om sneller door te kunnen werken.
- De titelrespons bij autosave triggert geen volledige DOM-herbouw meer, die onnodig scrollverschuiving veroorzaakte.
- In stap 3 is een zichtbare leerstatus toegevoegd met het aantal opgeslagen vraagstart-, grens- en contextcorrectievoorbeelden. De minimumdrempel voor activering blijft expliciet.
- Regressietests toegevoegd voor de compacte inspector, scrollbehoud, snelle autosave en zichtbare leerstatus.

# Reparatie na eerste CI-controle
- De eerste volledige CI-run vond twee testproblemen: een foutief pad in een bestaande frontend-contracttest en een CV-regel waarin regeleinden als de letterlijke tekens `\\n` waren opgeslagen.
- Beide zijn hersteld; de CV-scoreherkenning normaliseert nu zowel echte regeleinden als ge-escapete regeleinden voordat het scorelabel wordt gelezen.
- De CI-run voerde 153 tests uit; de overige tests slaagden, maar door deze twee bevindingen was de totale run niet geslaagd. De nieuwe testuitvoering moet de reparaties bevestigen.

# CV-maximumscores: gerichte OCR-terugval
- De herkenning leest maximumscores eerst uit de selecteerbare tekstlaag van het goedgekeurde CV-fragment.
- Alleen wanneer daar geen score wordt gevonden, wordt de lokale RapidOCR-engine op de exacte fragmentafbeelding gestart. Volledige pagina's en niet-goedgekeurde fragmenten worden niet verwerkt.
- De API geeft bij de score aan of deze uit de PDF-tekstlaag of via OCR is herkend, zodat de herkomst zichtbaar blijft in de analysegegevens.
- Regressietests toegevoegd voor beide routes, voor het overslaan van OCR wanneer die niet nodig is en voor schrijfvarianten als `Maximumscore: 2`.

# CV-tekstextractie: regressietest op afwijkende renderfactor

- Een regressietest controleert nu dat selectiecoördinaten uit een stitch met renderfactor 2.0 correct teruggezet worden naar PDF-coördinaten, zodat tekstlabels zoals `maximumscore 2` binnen de clip blijven.

# Reparatie CV-tekstextractie — renderfactor

- De omzetting van stitchpixel naar PDF-coördinaten gebruikt voortaan de werkelijke renderfactor uit paginametadata, in plaats van een vaste factor 1.25.
- Dit voorkomt verschoven tekstclips bij afwijkende paginagrootte of schaal, waardoor inhoud zoals maximumscores buiten het geselecteerde CV-tekstgebied kan vallen.
- De vaste factor blijft uitsluitend fallback voor metadata zonder bronbreedte.

## Herstel stap 12 — compatibiliteit met oudere antwoordreviews\n\n- Het ophalen van herkende antwoorden crasht niet meer wanneer een bestaande opgeslagen review het nieuwe veld `supplement_fragments` nog niet bevat. Ontbrekende velden worden veilig uit de actuele analyse overgenomen.\n\n## Herstel CV-aanvulling — volledige pagina zichtbaar en scrollbaar

- De fragmentselectiestap van de CV-aanvulling krijgt nu een eigen afbeeldingsvenster van minimaal 360 px en ongeveer 70% van de schermhoogte (met een maximum van 900 px).
- Het venster heeft altijd een verticale scrollbar; de samengevoegde PDF-afbeelding behoudt haar natuurlijke volledige hoogte en wordt niet tot één regel teruggebracht.
- De wijziging is beperkt tot de CV-aanvulling en lekt niet door naar de andere documentstappen.

## CV-aanvulling als volwaardig fragmentdocument

- Voeg afzonderlijke vraagstartdetectie en visuele vraagstartcontrole toe voor het aanvullingsdocument.
- Herken ook expliciete koppen als `Vraag 22:` in aanvullings-PDF's; deze worden als controleerbare kandidaten aan de bestaande visuele vraagstartreview toegevoegd.
- Gebruik voor de aanvulling dezelfde paginabrede stitchwerkruimte en versleepbare fragmentgrenzen als voor de uitwerkbijlage en het correctievoorschrift.
- Laat de docent per uitgesneden fragment kiezen voor toevoegen, vervangen, handmatig beoordelen of negeren.
- Stap 10 ontvangt uitsluitend de goedgekeurde fragmentuitsneden; volledige pagina-afbeeldingen worden niet meer aan antwoordvoorstellen toegevoegd.
- Neem in de definitieve snippetcontrole alleen goedgekeurde, niet-genegeerde fragmenten op.
- Sla bronhashes, pixelgrenzen, fragmentkoppelingen en verwerkingsbeslissingen afzonderlijk op. Een wijziging in eerdere stappen maakt afhankelijke goedkeuringen opnieuw controleplichtig.
- Sla de twee verwerkingsstappen automatisch over wanneer geen aanvullings-PDF is geïmporteerd.
- Voeg regressietests toe voor workflowafhankelijkheden, optionele afhandeling en de fragmentbron bij antwoordherkenning.

# Wijzigingen Examenverwerker 0.18

## Snippets uit CV-aanvullingen

- De snippetfase toont nu ook afzonderlijke pagina-snippets uit de gecontroleerde CV-aanvulling. Pagina’s die als negeren zijn beoordeeld, worden niet meegenomen.
- De gekozen verwerking (toevoegen/vervangen/handmatig) en vraagkoppeling worden zichtbaar bij ieder snippet.
- Regressietest toegevoegd voor de aanwezigheid van de aanvulling-snippets in API en interface.

## Nieuwe correcties na praktijktest

- Stap 4 toont de antwoordoptie-editor alleen bij vragen die meerkeuze zijn; bij het wijzigen van het vraagtype schakelt de editor direct mee.
- Bij het goedkeuren van de vraaganalyse geeft de knop onmiddellijk feedback dat de opslag en afronding bezig zijn.
- Bij het verslepen van fragmentgrenzen scrollt het documentleesvenster geleidelijk wanneer de cursor dicht bij de boven- of onderrand komt.
- Stap 9 (CV-aanvulling) haalt het examenrecord eerst op voordat de controle op gekoppelde vraagnummering plaatsvindt; dit voorkwam de Internal Server Error.
- Regressietests toegevoegd voor de zichtbaarheid van de optie-editor, rand-scroll en het ontbrekende examenrecord.



## Visuele antwoordopties en compacte stap-3-inspector

- Maak contextgroepkaarten in de rechter inspector compacter, zodat de lange examenstrook in het middendeel visueel leidend blijft.
- Ondersteun meerkeuzeopties als tekst, afbeelding of combinatie van beide.
- Laat de docent grafische antwoordopties rechtstreeks uit een vraagfragment uitsnijden met een sleepkader; de crop gebruikt de originele afbeeldingspixels.
- Sla uitsneden als begrensde lokale PNG/JPEG-data op in de bestaande vraaganalyse-evidence. De bron-PDF blijft ongewijzigd.
- Laat bestaande automatisch herkende antwoordletters behouden en koppel er een afbeelding aan; de bronpagina is selecteerbaar bij meerpagina-vragen.
- Behoud beeldopties bij heropenen en toon ze opnieuw in de integrale eindcontrole.
- Vereis bij een expliciet goedgekeurde meerkeuzevraag minimaal twee complete antwoordopties.
- Voeg regressietests toe voor beeldopties, PNG-validatie, heropenen, opslag en de compacte inspector.
- Trek de vraagreview automatisch in wanneer vraagtype, maximumscore of antwoordopties na controle worden gewijzigd.


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


### Reparatie CV-aanvulling – vraagstartreview

- De opslagroute voor vraagstartcorrecties ondersteunt nu ook `aanvulling_correctievoorschrift` en bewaart de controle onder workflowstap `supplement_starts`.
- Een regressietest doorloopt voor de CV-aanvulling dezelfde volledige API-keten als voor de uitwerkbijlage en het correctievoorschrift: detecteren, review opslaan, stap afronden, fragmenten ophalen en fragmentreview opslaan.


### Leesvenster CV-aanvulling

- Vergroot het leesvenster in de stap met fragmenten van de CV-aanvulling tot een groot deel van de beschikbare schermhoogte (met een bruikbare minimumhoogte).
- De extra leesruimte geldt uitsluitend voor deze stap; de weergave van opgaven, uitwerkbijlage en regulier correctievoorschrift blijft ongewijzigd.
- Voeg een frontend-regressietest toe voor de stapgebonden hoogte-instelling en het resetten van de layoutklasse.


### Leesvenster tekst CV-aanvulling gecorrigeerd

- Pas de hoogtevergroting toe op het uitklapbare tekstleesvenster in de stap waarin CV-aanvullingsfragmenten worden beoordeeld. De eerdere wijziging vergrootte ten onrechte de afbeeldingviewport van de voorafgaande fragmentstap.
- Toon minimaal 12 rem teksthoogte en maximaal 32 rem, met regelafbreking en een eigen scrollbar voor lange fragmentteksten.
- Reset de tijdelijke layoutklasse bij het wisselen van workflowstap en dek de juiste koppeling af met een frontend-regressietest.


### Herstel afbeelding CV-aanvulling in fragmentreview
- De afbeeldingsserverroute accepteert nu ook `aanvulling_correctievoorschrift`. De lange afbeelding werd wel opgebouwd, maar de whitelist van de afbeeldingsroute sloot dit documenttype uit, waardoor de browser de PNG niet kon ophalen.
- Regressiecontract toegevoegd om deze route-toegang te bewaken.


- **Maximumscores uit CV herkennen:** herkenning uitgebreid met varianten zoals `max. score`, `maxscore` en labels die over meerdere regels zijn verdeeld; regressietests toegevoegd.

### Herstel: maximumscores van stap 12 naar stap 15
- Oorzaak: de browser stuurde bij het opslaan van stap 12 alleen antwoordvorm, antwoordtekst en reviewstatus mee. De herkende CV- en opgavenscores stonden daardoor wel op het scherm, maar ontbraken in de opgeslagen `antwoorden`-evidence die stap 15 uitleest.
- De browser stuurt de herkende scores nu expliciet mee. De API vult ontbrekende scorevelden bovendien zelf aan vanuit de actuele serveranalyse, zodat ook oudere browserclients geen scores meer verliezen.
- Bestaande niet-lege opgeslagen scorecorrecties blijven behouden. De integrale eindcontrole leest vervolgens de opgeslagen scores zoals bedoeld.
- Er is een regressietest toegevoegd voor de overdracht en opslag van beide scorevelden.

### Meerdere examenbundels tegelijk importeren
- De bibliotheek accepteert nu bestanden van meerdere examens in één selectieronde of in meerdere rondes.
- PDF's worden op basis van de bestandsnaam-basis en documentcode (-o, -u, -c, -a en CV-aanvullingen) in afzonderlijke examenbundels gegroepeerd. Elke bundel wordt als eigen examenwerkruimte geïmporteerd.
- De selectie wordt vóór upload getoond, inclusief bundelindeling en bestandsgrootte. Een afzonderlijk bestand kan met één actie uit de selectie worden verwijderd.
- Dubbelen binnen de selectie worden tegengehouden. Bij een importfout blijft de selectie beschikbaar om opnieuw te proberen.
- Reeds bestaande examens worden per bundel afzonderlijk afgehandeld; een bestaande verwerking wordt nooit automatisch vervangen.


## 0.18.3 — betrouwbare lokale start en versieherkenning

- De startbestanden zoeken nu eerst een vrije lokale poort vanaf 8000. Als een oude Examenverwerker nog actief is, wordt die niet afgesloten en wordt de nieuwe versie op de eerstvolgende vrije poort gestart.
- De browser wordt geopend op exact de poort waarop de nieuwe server start; een oude server kan daardoor niet ongemerkt als de nieuwe versie worden getoond.
- De startpagina toont zichtbaar versienummer 0.18.3. De HTML krijgt no-cache-headers en de CSS- en JavaScript-verwijzingen gebruiken een nieuwe cacheversie.
- De selectie van meerdere importbestanden heeft nu expliciete opmaak voor examenbundels en individuele verwijderknoppen.

- Bij een gedeeltelijk mislukte batchimport blijven alleen nog niet verwerkte examenbundels in de selectie staan. Eerder geslaagde of bewust overgeslagen bundels worden direct verwijderd, zodat opnieuw proberen geen dubbele import veroorzaakt.
- Regressietests toegevoegd voor de importretry, poortkeuze en versie-/cacheherkenning.

## 0.18.4 — afronding importpresentatie

- De opmaak van de geselecteerde bestanden sluit nu aan op de daadwerkelijke lijststructuur van de interface.
- Versie- en cacheaanduidingen verhoogd naar 0.18.4, zodat ook deze laatste presentatiecorrectie gegarandeerd als nieuwe browserasset wordt geladen.


## 0.18.5 — documenten beheren in bestaande werkruimte

- Een afzonderlijke PDF kan in fase 1 uit een bestaande, nog niet bevestigde werkruimte worden verwijderd; herimport is niet nodig.
- Na verwijderen wordt de werkruimte direct opnieuw geladen. Het laatste bestand en bestanden in bevestigde examens zijn beschermd.
- Metadata-concepten worden bijgewerkt zodat verwijderde bestandsnamen niet blijven hangen.
