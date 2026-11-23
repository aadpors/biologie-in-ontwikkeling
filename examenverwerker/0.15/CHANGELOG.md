# Wijzigingen Examenverwerker

## 0.15.0

- Begrens vraagfragmenten met visuele witregels en brede kadergrenzen rondom vraagstarts.
- Maak contextfragmenten van de tussenruimtes tussen opeenvolgende vraagfragmenten.
- Behoud doorlopende vragen over paginaovergangen tot de eerstvolgende visuele scheiding.
- Maak afgeronde workflowstappen aanklikbaar om ze opnieuw te openen; bewaar invoer als concept en invalideer afhankelijke goedkeuringen.
- Maak metadata opnieuw bewerkbaar via dezelfde herstelroute.
- Detecteer identieke examens via de SHA-256-verzameling van de bron-PDF's.
- Vraag expliciete bevestiging voordat een bestaande import en de volledige verwerking worden vervangen.
- Verwijder de oude import pas nadat de nieuwe import succesvol is aangemaakt.

# Changelog

## 0.14.0

- Crop elke pagina vóór het stitchen; maskeer geïsoleerde paginanummers in de onderste paginamarge.
- Voeg contextvoorstellen toe aan de doorlopende fragmentindeling en knip overlappende vraagfragmenten bij de volgende contextgrens af.
- Geef sleepgrepen van het geselecteerde fragment voorrang bij samenvallende grenzen.
- Sla metadata en wijzigingen in alle bewerkbare workflowstappen automatisch als concept op, inclusief vraagstarts, fragmentgrenzen, analyse, CV-aanvulling, antwoorden, koppelingen, snippets en eindcontrole.
- Forceer een laatste conceptopslag bij tabbladwissel of het sluiten van de pagina.
- Maak de betekenis van de vraagstartvinkjes expliciet.

# Wijzigingen

## 0.13.0
- Automatische eerste segmentatie van goedgekeurde hoofdvragen op de lange examenafbeelding.
- Fragmentgrenzen zijn rechtstreeks met muis en touchscreen versleepbaar.
- Bestaande docentselecties blijven behouden bij het opnieuw openen van stap 3.
- Kandidaten buiten de langste strikt oplopende hoofdvraagreeks worden niet automatisch geaccepteerd.
- Regressietests toegevoegd voor segmentatie en paginaovergangen.

# Wijzigingen

## 0.12
- Stap 3 voor het opgavenboekje gebruikt nu één lange, verticaal gestitchte afbeelding vanaf pagina 2.
- Pagina's worden opgeschoond van herhaalde kop-/voetteksten en grote buitenmarges; de bron-PDF blijft ongewijzigd.
- Contexten en vragen kunnen op dezelfde lange afbeelding worden geselecteerd en gekoppeld aan één of meer vraagnummers.
- Rechter inspector toont type, vraagkoppeling en aanpasbare boven-/ondergrens; het middendeel toont de doorlopende afbeelding.
- De geselecteerde vraagfragmenten en contexten worden doorgegeven aan de latere analyse- en snippetstappen.
- Vraagstartdetectie verwijdert kandidaten niet langer automatisch bij een nummerterugloop of afwijkende horizontale uitlijning. Zulke kandidaten blijven zichtbaar met een waarschuwing.
- Regressietest toegevoegd voor het overslaan van de omslag en de coördinatenkaart van de lange afbeelding.
- Code voorzien van toelichting bij de nieuwe stitch-, selectie- en validatiestappen.


## 0.11
- Nieuw Windows-startbestand `start.bat`: starten met dubbelklik, zonder PowerShell-opdrachten of wijziging van de uitvoeringspolicy.
- De eerste start maakt automatisch een lokale virtuele Python-omgeving aan en installeert de vereiste pakketten.
- De standaardbrowser wordt automatisch geopend; het opdrachtvenster blijft zichtbaar voor servermeldingen.
- `start.ps1` blijft als alternatief beschikbaar.


## 0.10.0

- Nummerkolomuitlijning wordt expliciet per PDF-pagina beoordeeld; even en oneven pagina's mogen dus verschillende linkermarges hebben.
- De paginadata bevat de exacte PDF-woordposities, zodat een handmatig geplaatste vraagstart het nummer uit het aangeklikte tekstvak kan uitlezen.
- Als de PDF geen selecteerbare tekst voor het nummer bevat, vraagt de interface om het nummer in plaats van automatisch een willekeurig vrij nummer te kiezen.
- Vóór het toevoegen van een handmatige vraagstart worden alle wijzigingen in de bestaande vraagnummervelden eerst naar de onderliggende gegevens gesynchroniseerd. Latere toevoegingen kunnen eerder gecorrigeerde nummers daardoor niet meer overschrijven.
- Toegevoegd: regressietests voor wisselende paginamarges, PDF-woordposities en het behouden van handmatig gecorrigeerde vraagnummers.

## 0.9.0

- Vraagstartdetectie gebruikt de vaste horizontale nummerkolom als extra signaal; één- en tweecijferige nummers blijven ondersteund.
- Getallen midden in lopende tekst en kleine genummerde verwijzingen worden conservatiever gefilterd.
- De hoofdvraagreeks moet oplopen; een terugval van bijvoorbeeld vraag 12 naar vraag 1 wordt niet automatisch geaccepteerd.
- Voor het correctievoorschrift wordt de nummerreeks pas gecontroleerd nadat de inleiding en genummerde antwoordonderdelen zijn uitgesloten.
- Fragmenten krijgen een voorlopig eindpunt bij de eerste herkende witregel of kadergrens tussen twee vragen.
- De fragmentreview heeft sleepbare horizontale grenslijnen op de PDF-afbeeldingen; de gekozen positie wordt automatisch naar PDF-punten vertaald.
- Handmatige numerieke invoer is uit de normale interface verwijderd; de waarden blijven intern opgeslagen voor reproduceerbare uitsneden.
- Nieuwe regressietest voor eenheden, genummerde uitspraken en teruglopende vraagnummering.

## 0.8.0

- Aanvullende verwerking van CV-antwoorden: meerkeuzeletters, genummerde gesloten antwoorden en volledige open beoordelingscriteria.
- Maximumscores uit opgave en CV worden naast elkaar vergeleken.
- CV-aanvullingen kunnen per pagina als toevoegen, vervangen, handmatig of negeren worden beoordeeld; betrokken vraagnummers zijn aanpasbaar.
- Correctievoorschriftvragen worden onderscheiden van genummerde regels vóór het beoordelingsmodel en genummerde gesloten antwoorditems.
- Fragmentgrenzen kunnen numeriek worden aangepast; gewijzigde uitsneden worden opnieuw gegenereerd en moeten opnieuw visueel worden goedgekeurd.
- Contextvoorstellen worden uit de oorspronkelijke PDF-pagina gerenderd en aan een controleerbaar vraagbereik gekoppeld.
- Snippetfase controleert opgaven, uitwerkbijlage, correctievoorschrift en contexten.
- Integrale eindcontrole toont per vraag alle beschikbare bronnen, antwoordopties, antwoordtekst en scores.
- Herstelknoppen vanuit de eindcontrole openen de relevante verwerkingsstap en laten afhankelijke goedkeuringen vervallen.
- Publicatie krijgt een persistente status en tijdstempel in de examenbibliotheek.
- Uitwerkbijlage is optioneel; ontbrekende bijlagen kunnen expliciet als niet van toepassing worden bevestigd.
- SQLite-migratie voor publicatiestatus toegevoegd.
- Tests uitgebreid met synthetische PDF's en API-integratietests.

## 0.6.0

- Geïntegreerde bibliotheek en examenwerkruimte.
- Metadata- en documenttypebevestiging.
- Automatische vraagstartdetectie met visuele review.
- Handmatig toevoegen, verwijderen, verplaatsen en opnieuw positioneren van vraagstarts.
- Fragmenten over meerdere pagina's, CV-pagina's samenvoegen en buitenste witruimte trimmen.
- Vraagtype, punten en antwoordopties voorstellen.
