## 0.13.4
- Importdialoog gebruikt nu een grid-indeling met een vaste onderste actiebalk. De knoppen **Annuleren** en **Opslaan en doorgaan naar examenverwerking** blijven zichtbaar, ook wanneer het middenpaneel uitrekt.
- Versienummer verhoogd voor de gecorrigeerde Windows-build.

## 0.13.3
- Importcontrole: vaste voettekst met een expliciete knop **Opslaan en doorgaan naar examenverwerking**.
- De knop voert de volledige batchvalidatie uit, slaat de gecontroleerde metadata en groepering op, maakt de examenprojecten aan en opent het eerste examen. Bij validatiefouten blijft het controlescherm geopend.

## 0.13.6
- Vraagstartleren gebruikt genormaliseerde layout-/taalfeatures in plaats van alleen twee grove patroonklassen; exacte vraagtekst, nummer en PDF-positie worden niet in de leersleutel opgenomen.
- Een leeradvies vereist nu minimaal drie onafhankelijke examen-PDF's en ten minste 80% overeenstemming. Herhaalde keuzes binnen één PDF tellen niet als onafhankelijke examens; conflicten blijven zichtbaar en niets wordt automatisch toegepast.
- De structuurvoorstellen bevatten naast vraagbanden ook afzonderlijke, controleerbare contextvoorstellen rond gedetecteerde afbeeldingen, schema's, tabellen en bijschriften.
- De structuur-editor toont per voorstel de zekerheid en de herkenningsreden, zodat duidelijk is waarop de koppeling is gebaseerd.
- Regressietests toegevoegd voor generaliseerbare leersleutels, onafhankelijke examensteun, conflicterende feedback en contextvoorstellen uit visuele PDF-elementen.

# Wijzigingen

## 0.13.2
- Verwerkingsstatus van ieder examen wordt centraal en zonder Tkinter-afhankelijkheden afgeleid; dezelfde regels sturen de hoofdwerkruimte en de examenbibliotheek aan.
- De bibliotheek toont de concrete eerstvolgende stap per examen en heeft een actie **Volgend openstaand examen**.
- Een bulkimportbatch wordt vanuit het importmanifest aan ieder aangemaakt examen gekoppeld en na herstart van de applicatie hersteld.
- Na afronding van een examen kan de gebruiker direct doorgaan met het volgende examen uit dezelfde batch.
- Na een geslaagde export wordt een inhoudsfingerprint opgeslagen; een gewijzigd examen wordt daardoor niet ten onrechte als afgerond getoond.
- De batchvolgorde wordt na herstart veilig uit het importmanifest hersteld; ongeldige regels en paden buiten de examenroot worden geweigerd.
- Als het volgende examen niet kan worden geopend, blijven de huidige werkruimte en batchpositie behouden.
- Regressietests toegevoegd voor alle verwerkingsstappen, exportvoltooiing, verouderde exports, batchherstel en padbeveiliging.

## 0.13.1
- Importcontrole opnieuw ingericht als één werkruimte met PDF-lijst links, voorblad in het midden en bewerkbare metadata rechts.
- Bij selectie van een PDF wordt het voorblad direct getoond en worden de voorgestelde documentrol, niveau, jaar en tijdvak geladen.
- Metadata kunnen direct in het rechterpaneel worden aangepast en per PDF worden toegepast; de aparte pop-up voor herkenningscorrectie is vervallen.
- Batchvalidatie en één finale importbevestiging blijven behouden.

## 0.13.0
- Hoofdinterface herbouwd als geïntegreerde examenwerkplek: documentlijst en vraagkandidaten links, originele PDF groot in beeld en beoordelingsvelden direct naast de bron.
- PDF-navigatie en zoom met rode markering van de exacte kandidaatpositie.
- Kandidaten direct beoordelen als vraag, geen vraag of twijfel; vraagnummer, vraagtekst en notities zijn meteen aanpasbaar en worden in het project bewaard.
- Filters voor nog te beoordelen kandidaten, sterke/zwakke signalen en dubbele nummers.
- Ontbrekende vraagstarts kunnen op de exacte positie in de originele PDF worden toegevoegd; de PDF-coördinaten worden bewaard.
- Correcties uit Biologie-controle v1.0.x kunnen worden geïmporteerd en als compact `biologie-correcties-v1` JSON-bestand worden geëxporteerd; de centrale correctiebibliotheek wordt automatisch op alle examenprojecten toegepast.
- Handmatige besluiten, vraagnummercorrecties, notities en posities blijven behouden bij heranalyse; handmatig toegevoegde vragen worden niet stilzwijgend verwijderd.
- Na bulkimport opent het eerste aangemaakte examen automatisch in de werkruimte.
- Onzekere documentrollen en metadata worden niet automatisch als menselijk bevestigd opgeslagen; correctie blijft verplicht vóór import.

## 0.12.0
- Volledig nieuw dashboard in plaats van de eerdere bestandsbeheerindeling: burgundy welkomstbanner, herkenbare kleuraccenten en ruime kaarten, geïnspireerd op de oorspronkelijke website.
- Overzicht, documentbibliotheek en verwerkroute zijn gescheiden in eigen tabbladen.
- Startscherm toont direct projectstatus en live aantallen bronbestanden, vraagstartkandidaten, open controles en vraagrecords.
- Verwerkroute is als visuele stappenlijst opgebouwd met duidelijke acties en korte uitleg per stap.
- Activiteitenlog blijft onderin permanent zichtbaar; alle bestaande verwerkingsfuncties en veiligheidscontroles blijven behouden.

## 0.11.0
- Vraagstartcontrole vernieuwd: kandidaten en vraagtekst staan naast elkaar in één doorlopend werkvenster; bevestigen/afwijzen opent geen apart venster per vraag.
- Na iedere beslissing springt de controle automatisch naar de volgende nog niet beoordeelde kandidaat.
- Projecten worden automatisch aangemaakt in `projecten/` binnen de programmamap; geen map- of naamdialoog meer.
- Bulkimport gebruikt dezelfde programmamap-root en groepeert examens onder `projecten/<jaar>/<niveau>-tijdvak-<nummer>/`.
- Foutafhandeling bij projectaanmaak verbeterd en de programmamap wordt expliciet als opslaglocatie gebruikt.

## 0.10.1
- Metadata-controle toont het originele voorblad naast de automatisch herkende document- en examenvelden.
- Dit geldt zowel voor bulkimport als voor document- en projectmetadata in bestaande projecten.
- Ontbrekende waarden blijven leeg; standaardwaarden worden niet langer als automatische herkenning gepresenteerd.
- Lage metadatabetrouwbaarheid wordt in de controlelijst als handmatige controle gemarkeerd.

## 0.10.0
- Desktopinterface opnieuw vormgegeven met vaste navigatie, gegroepeerde project- en verwerkacties, duidelijke projectstatus en afzonderlijke panelen voor bronbestanden en activiteit.
- Meer ruimte voor de documentlijst, verbeterde tabelkoppen, afwisselende rijen en horizontale/verticale scrollondersteuning.
- Rustige lichte werkruimte met donker navigatiepaneel en bordeauxrode accenten; bestaande verwerkingsfuncties en veiligheidsregels behouden.

# Wijzigingen

## 0.9.0
- Bulkimport accepteert in één selectie examens uit meerdere jaren, niveaus en tijdvakken.
- Geen handmatige keuze of aanmaak van een doelmap meer; de applicatie gebruikt automatisch de bestaande map `examens` naast de programmamap of maakt die standaardlocatie aan.
- Examens worden rechtstreeks gegroepeerd in `examens/<jaar>/<niveau>-tijdvak-<nummer>/`.
- Een importmanifest wordt automatisch in de map `examens` opgeslagen.
- Bestaande examenmappen worden nooit overschreven; bij een botsing wordt de import afgebroken en worden uitsluitend nieuw aangemaakte mappen van die poging opgeruimd.
- De herkenningscontrole blijft verplicht voor onzekere metadata en documenttypen.

## 0.8.0
- Jaarset-import toegevoegd zonder vooraf projecten aan te maken: selecteer alle examen-PDF's van een jaar in één keer.
- Automatische groepering op exacte combinatie van niveau, jaar en tijdvak; havo en vwo en alle tijdvakken blijven strikt gescheiden.
- Controlevenster toont per PDF documenttype, herkenningszekerheid, niveau, jaar, tijdvak en pagina-aantal; onzekere of ontbrekende herkenning moet handmatig worden gecorrigeerd.
- Import maakt pas na expliciete bevestiging afzonderlijke, bestaande-compatibele examenprojecten aan en bewaart een jaarset-manifest.
- Waarschuwingen voor ontbrekende of dubbele opgaven/CV-documenten; bestaande projecten worden niet overschreven.
- Tests toegevoegd voor exacte groepering, onvolledige metadata en importblokkades.

## 0.7.1
- Alle handmatige uitsneden gebruiken uitsluitend horizontale stroken over de volledige paginabreedte.
- De strookselectie toont en verplaatst alleen twee horizontale grenzen; verticale grenslijnen zijn verwijderd.
- De exportcontrole verifieert de volledige paginabreedte en blokkeert nieuwe uitsneden met linker- of rechtermarges.
- Oude opgeslagen rechthoekige uitsneden blijven leesbaar voor compatibiliteit; nieuwe uitsneden worden alleen als paginabrede strook opgeslagen.
- Regressietests toegevoegd voor volledige breedte en het afwijzen van verticale uitsnedengrenzen.


## 0.6.0
- Afzonderlijke visuele vraag/contextstructuur per opgaven-PDF.
- Versleepbare paginabrede grenzen met genormaliseerde coördinaten.
- Grenzen kunnen op bestaande pagina's worden bijgewerkt en over meerdere pagina's worden uitgebreid.
- Handmatige visuele afbakening van het correctievoorschrift per vraag.
- Handmatige afbakening van iedere geselecteerde officiële CV-aanvulling.
- Vraag-, context-, CV- en aanvullingsuitsneden worden rechtstreeks uit de oorspronkelijke PDF gerenderd.
- Contextafbeeldingen en bijschriften worden gescheiden van vraagafbeeldingen; captions moeten expliciet worden bevestigd.
- Contexttekst uit afgebakende bronregio's kan worden nagelezen en gecorrigeerd.
- Export blokkeert ontbrekende, gewijzigde of verkeerd gekoppelde bronregio's.
- Auditmanifest bevat bronhashes, fragmentkoppelingen, contextassets en CV-regio's.
- Extra regressietests voor multi-page fragmenten, bronherkomst, contextscheiding en exportblokkades.
- Bestaande records worden ongeldig verklaard wanneer vraag-/contextgrenzen of CV-regio's worden gewijzigd.
- SHA-256-controle van alle gegenereerde vraag-, context-, CV- en aanvullingsuitsneden.
- Scrollbare formulieren en volledige originele pagina's rond geselecteerde regio's in de eindcontrole.
- Praktijktestplan toegevoegd aan de portable map.
