# Examenverwerker — geïntegreerde applicatie 0.15.0

Dit project is een nieuwe, samenhangende webapplicatie op basis van de
functionele blauwdruk `Implementatie Nog Niet Afgerond.txt`. De bibliotheek,
examenwerkruimte, originele PDF's, afgeleide fragmenten en workflowstatus
worden beheerd door één FastAPI-app en één SQLite-opslag.

## Starten

Vereist Python 3.10 of hoger.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn examenverwerker.main:app --reload
```

Op Windows kan dit ook met `start.ps1`; het script maakt de virtuele omgeving
aan, installeert de benodigde pakketten en start de server. Open daarna
`http://127.0.0.1:8000`.

## Geïntegreerde verwerkingsstappen

### 1. Bibliotheek, import en metadata

- Examenbibliotheek met persistente SQLite-opslag in een gedeelde map buiten de versiemappen.
- Bij de eerste start van 0.14 wordt bestaande lokale opslag uit `0.13/data` eenmalig gekopieerd als de gedeelde opslag nog niet bestaat; de oude map blijft als terugvalkopie behouden.
- Import van meerdere PDF's als één examenproject.
- Validatie van PDF-bestanden, ongewijzigde opslag van de bronbestanden,
  SHA-256-hash en paginatelling.
- Metadata-voorstellen op basis van bestandsnaam en eerste pagina.
- Herkenning van `-o`, `-u`, `-c` en `-a`; vak, niveau, jaar, tijdvak en
  documenttypen worden in één keer bevestigd.
- Een uitwerkbijlage is optioneel. Als die ontbreekt, worden de twee betreffende
  stappen expliciet als niet van toepassing gemarkeerd.

### 2. Vraagstarts

- Vraagstarts worden in opgaven, uitwerkbijlage en correctievoorschrift
  voorgesteld met PDF-puntcoördinaten.
- De herkenning ondersteunt zowel een los vraagnnummer als een vraagnummer
  voorafgegaan door een puntenlabel, zoals `1p 1`.
- Voor het correctievoorschrift begint de detectie bij het beoordelingsmodel;
  genummerde juridische voorschriften ervoor worden niet als examenvragen
  behandeld.
- Visuele markeringen op de originele PDF-pagina's.
- Kandidaten accepteren, afwijzen, nummer wijzigen, handmatig toevoegen,
  verwijderen, verplaatsen en opnieuw positioneren.
- Conceptreview tussentijds opslaan; alle pagina's moeten expliciet visueel
  worden gecontroleerd voordat de stap kan worden afgerond.
- Servervalidatie van paginagrenzen en bronhash.

### 3. Vraagfragmenten

- Voor het opgavenboekje wordt vanaf pagina 2 één lange verticale werkafbeelding opgebouwd.
- Herhaalde kop-/voetteksten en grote buitenmarges worden waar mogelijk verwijderd; de originele PDF blijft ongewijzigd.
- Contexten en vraagfragmenten worden rechtstreeks op deze ene afbeelding geselecteerd. De docent stelt boven- en ondergrens in en koppelt elk fragment aan één of meer vraagnummers.
- De rechter inspector toont per selectie het fragmenttype, de gekoppelde vraagnummers en de bewerkbare grenzen; het middendeel blijft de doorlopende examenafbeelding.
- Geselecteerde vraagfragmenten worden als bron gebruikt voor de vraaganalyse; geselecteerde contexten worden gebruikt in de snippetfase.
- Voor uitwerkbijlage en correctievoorschrift blijft de bestaande documentgerichte fragmentreview beschikbaar.
- Fragmenten worden rechtstreeks uit de originele PDF gerenderd.
- Vragen die over meerdere pagina's lopen, blijven één vraag met meerdere
  opeenvolgende pagina-afbeeldingen.
- De boven- en ondergrens zijn per vraag numeriek aanpasbaar in PDF-punten.
  Bij wijziging wordt de afbeelding opnieuw gegenereerd en vervalt de oude
  visuele goedkeuring van die vraag.
- Correctievoorschriftfragmenten worden per vraag verticaal samengevoegd.
- Aantoonbaar herhaalde kop-/voettekstregels en losse paginanummers in de
  buitenste marges worden gemaskeerd.
- De laatste CV-vraag stopt vóór de administratieve sectie `Aanleveren scores`
  wanneer die sectie herkenbaar is.
- Alleen buitenste witte randen worden getrimd; een extra marge blijft staan.
- De originele PDF wordt nooit gewijzigd.

### 4. Vraagtype, punten en antwoordopties

- Per vraag een controlekaart met het volledige opgavefragment.
- Voorstellen voor meerkeuze, gesloten antwoordvormen en open vragen.
- Meerkeuze kan ook uit de vraagformulering worden afgeleid wanneer opties niet
  als afzonderlijke regels zijn herkend.
- A-E-opties worden als voorstel geëxtraheerd en zijn handmatig aanpasbaar.
- Expliciete puntenaantallen worden voorgesteld; bij onduidelijkheid blijft het
  veld leeg.
- Iedere vraag moet afzonderlijk worden gecontroleerd.

### 5. Correctievoorschrift en aanvullingen

- Per vraag worden MC-antwoorden herkend wanneer het CV een eenduidige
  antwoordletter met scorekolom bevat, ook wanneer de PDF-tekstextractie de
  vraagnummer-, antwoord- en scorekolom samenvoegt.
- Genummerde gesloten antwoordvormen zoals juist/onjuist worden voorgesteld.
- Open beoordelingscriteria blijven als volledige CV-tekst beschikbaar; de
  app reduceert die niet tot een zelfbedacht kort antwoord.
- Maximumscores uit CV en opgave worden naast elkaar gezet.
- Een eventuele aanvulling op het CV wordt per pagina gecontroleerd. De docent
  kiest toevoegen, vervangen, handmatig beoordelen of negeren en kan de
  betrokken vraagnummers aanpassen.
- Een aanvulling wordt niet automatisch op het oorspronkelijke CV toegepast.
  De oorspronkelijke tekst en de aanvulling blijven naast elkaar zichtbaar in
  de antwoord- en eindcontrole.

### 6. Documentrelaties, contexten en snippets

- Per opgave wordt gecontroleerd of een CV-fragment bestaat en of een onderdeel
  in de uitwerkbijlage voorkomt. Niet iedere vraag hoeft in de uitwerkbijlage te
  staan.
- Contextvoorstellen worden gezocht boven de eerste vraagstart op een pagina.
  Het voorgestelde bereik loopt tot de vraag vóór de volgende contextstart en
  kan handmatig worden aangepast.
- Contexten, opgaven, uitwerkbijlagefragmenten en CV-fragmenten worden in een
  afzonderlijke snippetfase getoond en moeten allemaal visueel worden afgevinkt.
- Als geen contextvoorstel is gevonden, moet de docent expliciet bevestigen dat
  er geen afzonderlijke contexten gekoppeld hoeven te worden.

### 7. Integrale eindcontrole en publicatie

- Per vraag worden context, opgave, eventuele uitwerkbijlage, CV-fragment,
  antwoordopties, antwoord/beoordelingscriteria en maximumscores bij elkaar
  getoond.
- Een verschil tussen de maximumscore in opgave en CV vraagt een toelichting.
- Vanuit de eindcontrole kan worden teruggekeerd naar vraagfragmenten,
  CV-fragmenten of documentrelaties; afhankelijke goedkeuringen vervallen dan.
- Publicatie is alleen mogelijk na afronding van de integrale eindcontrole.
  De bibliotheek bewaart een expliciete publicatiestatus en publicatiedatum.

## Wijzigingen in 0.15.0

- Vraagfragmenten worden begrensd door de dichtstbijzijnde visuele witregel of brede kadergrens boven en onder de herkende vraagstart. Een vraag die over een paginaovergang doorloopt, blijft één fragment tot de eerstvolgende visuele scheiding.
- De ruimte tussen opeenvolgende vraagfragmenten wordt als contextfragment voorgesteld en aan de daaropvolgende vraag gekoppeld. De oude beperking waarbij contexten alleen boven de eerste vraagstart op een pagina werden gezocht, is voor deze stap vervallen.
- Iedere afgeronde stap in de workflow kan opnieuw worden geopend. De eerder opgeslagen invoer blijft als concept beschikbaar; alleen afhankelijke goedkeuringen worden ongeldig gemaakt. Metadata kan op dezelfde manier opnieuw worden bevestigd.
- Een examenimport wordt vergeleken met bestaande imports op basis van de SHA-256-hashes van alle bron-PDF's, onafhankelijk van bestandsvolgorde en bestandsnaam. Bij een identieke set moet de gebruiker expliciet bevestigen dat de oude import en alle bijbehorende verwerking mogen worden vervangen. Zonder bevestiging blijft de bestaande import intact.
- De oude import wordt pas verwijderd nadat de nieuwe import succesvol in de database is aangemaakt.
 
## Wijzigingen in 0.14.0

- Elke opgavenpagina wordt eerst afzonderlijk opgeschoond en bijgesneden; pas daarna worden de pagina-afbeeldingen verticaal samengevoegd.
- Geïsoleerde numerieke paginanummers in de onderste 7% van een pagina worden vóór het bijsnijden wit gemaskeerd. De cropdrempel is aangescherpt en de tussenruimte tussen pagina's is verkleind.
- Contextvoorstellen uit de contextdetector worden naar de coördinaten van de lange afbeelding omgerekend en tussen de vraagvoorstellen geplaatst. Een doorlopende vraag wordt waar nodig vóór de volgende context afgekapt.
- De grenzen van het geselecteerde fragment krijgen bij overlappende sleepzones voorrang.
- Metadata, vraagstartkeuzes, fragmentgrenzen, vraagtypen, punten, antwoordopties, CV-aanvullingskeuzes, antwoorden, documentkoppelingen, contextbereiken, snippetcontroles en de integrale eindcontrole worden na iedere veldwijziging automatisch als concept opgeslagen. Bij het verlaten van het tabblad of sluiten van de pagina wordt een laatste opslagrequest verstuurd.
- Verdachte nummerherkenningen worden expliciet aangeduid als mogelijke subnummering; het vinkje is nu voorzien van de betekenis ‘als hoofdvraagstart gebruiken’.

## Wijzigingen in 0.13.0

- Stap 3 maakt automatisch eerste vraagfragmentvoorstellen op basis van de goedgekeurde hoofdvraagstarts en de crop-/schaalmetadata van de lange examenafbeelding.
- Eerder opgeslagen docentselecties blijven leidend en worden niet overschreven.
- De boven- en ondergrenzen zijn rechtstreeks op de afbeelding versleepbaar met muis of touchscreen; de numerieke waarden blijven synchroon.
- Kandidaten buiten de langste strikt oplopende hoofdvraagreeks blijven zichtbaar, maar worden niet automatisch geaccepteerd.
- Regressietests controleren de coördinaatomrekening en fragmenten over paginaovergangen.

## Bekende beperkingen vóór praktijktest

- OCR voor gescande PDF's zonder tekstlaag is nog niet geïmplementeerd.
- De automatische vraagstartdetectie is een voorstelgenerator. Genummerde
  subonderdelen kunnen soms kandidaat worden; visuele correctie blijft nodig.
  Nummerterugloop wordt nu als waarschuwing getoond in plaats van kandidaten
  stilzwijgend te verwijderen. Daardoor kunnen ook fout-positieve kandidaten
  zichtbaar blijven; de docent beoordeelt ze in de paginavisualisatie.
- De witregel-/kaderdetectie is een voorstelgenerator. Ze gebruikt tekstregelafstanden en brede PDF-kaders; visuele controle blijft noodzakelijk, vooral bij vragen met meerdere tekstkolommen, tabellen of complexe kaders. Contexten tussen vraagfragmenten worden automatisch als voorstel opgenomen, maar moeten inhoudelijk en visueel worden gecontroleerd.
- De CV-aanvulling wordt in de reviewset gekoppeld en naast het originele CV
  getoond. Er wordt nog geen zelfstandig nieuw samengevoegd CV-PDF-bestand
  geëxporteerd.
- De paginacrop, paginanummermaskering en contextvoorstellen zijn met
  synthetische PDF's getest, maar nog niet visueel geaccepteerd op een echt
  examenbestand. De paginanummermaskering vereist een selecteerbare tekstlaag.
- De snippet- en eindcontroles zijn gebouwd en met synthetische PDF's getest,
  maar moeten nog op de echte examens worden doorlopen. Met name de volledige
  vraagnummering, contextbereiken, onderste tekstregels en het behoud van het
  woord `overerft` moeten in de vwo 2026 tijdvak 2-PDF's visueel worden bevestigd.

## Architectuur

- `examenverwerker/domain.py`: workflowvolgorde, afhankelijkheden en invalidatie.
- `examenverwerker/metadata.py`: metadataherkenning.
- `examenverwerker/storage.py`: SQLite, bronbestanden, hashes en publicatiestatus.
- `examenverwerker/main.py`: API, PDF-import, preview en servervalidatie.
- `examenverwerker/question_detection.py`: detectie, coördinaten en reviewvalidatie.
- `examenverwerker/question_fragments.py`: multi-page fragmenten, grenzen,
  renderen en trimmen van buitenste witruimte.
- `examenverwerker/question_analysis.py`: vraagtype, maximumscore en opties.
- `examenverwerker/answer_detection.py`: MC-/gesloten antwoorden, CV-scores en
  antwoordreview.
- `examenverwerker/cv_supplement.py`: veilige verwerking van CV-aanvullingen.
- `examenverwerker/context_detection.py`: contextvoorstellen en bereikvalidatie.
- `templates/index.html` en `static/`: bibliotheek en geïntegreerde werkruimte.
- `tests/`: tests met tijdelijke PDF's en API-integratietests.

Nieuwe en gewijzigde code bevat toelichtende commentaren over ontwerpkeuzes,
aannames, validatie en de reden voor de gekozen aanpak.

## Tests uitvoeren

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
node --check static/app.js
```

## Starten op Windows

Dubbelklik op `start.bat`. De eerste keer installeert het de benodigde pakketten in een lokale Python-omgeving en opent het de browser. Python 3.10 of hoger moet zijn geïnstalleerd. Laat het opdrachtvenster open zolang de applicatie draait.
