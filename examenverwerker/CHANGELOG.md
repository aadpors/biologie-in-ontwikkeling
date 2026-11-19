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
