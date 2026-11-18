# Ontwerp en kwaliteitsprincipes

## Productdoel
Een docent kan een compleet biologie-examen verwerken door de PDF's toe te voegen en de uitzonderingen te beoordelen. Het systeem maakt reproduceerbare, controleerbare vraagrecords en exacte bronafbeeldingen. Het bestaande websiteformaat blijft de publicatie-interface.

## Architectuur: gescheiden lagen
1. **Inname** – originele bestanden, SHA-256, metadata, documenttypevoorstel.
2. **Extractie** – tekst per pagina, paginageometrie, afbeeldingen, tabellen en tekeningen.
3. **Structurering** – vraagstarts, vraaggrenzen, deelvragen, antwoordopties, contextblokken en verwijzingen.
4. **Bronkoppeling** – CV, aanvullingen/errata, uitwerkbijlagen en bronpagina's koppelen aan iedere vraag.
5. **Snippet-engine** – uitsluitend uitsneden/renders van originele PDF-pagina's; nooit inhoud natekenen of reconstrueren.
6. **Controle** – volledigheid, inhoudelijke samenhang, leesbaarheid, uitsnedegrenzen, bijschriften en paginaverwijzingen.
7. **Leren** – menselijke beslissingen opslaan als voorbeelden en regels met herkomst, scope en betrouwbaarheid.
8. **Export** – bestaande JSON-schema's en mappenstructuur valideren; publicatie als apart pakket.

## Vertrouwensmodel
- Regels en exacte tekstextractie zijn deterministisch.
- AI mag classificeren, relaties voorstellen en afwijkingen uitleggen.
- AI-uitvoer is nooit een bron en nooit automatisch een definitieve goedkeuring.
- Iedere voorgestelde koppeling bewaart bronbestand, pagina, coördinaten, methode, score en versie.
- Geen cloudverwerking van examenbestanden zonder expliciete keuze van de gebruiker.
- Geen publicatie zolang verplichte controles openstaan.

## Leren zonder fout te generaliseren
Een correctie wordt opgeslagen met:
- de oorspronkelijke situatie en document-/layoutkenmerken;
- de gekozen uitkomst en eventuele alternatieven;
- reden/categorie van de correctie;
- toepassingsgebied (exact document, examenlayout of generiek);
- aantal bevestigingen en eventuele latere tegenspraak.

Een enkele correctie wordt niet direct een algemene regel. Nieuwe regels worden eerst in schaduwmodus getest op eerder verwerkte examens. Alleen aantoonbaar betere regels promoveren naar automatische voorstellen.

## Gebruikservaring
- Eén wizard: examen aanmaken → PDF's toevoegen → documentrollen bevestigen → verwerking → uitzonderingen → kwaliteitsrapport → export.
- Gewone taal, geen technische foutcodes als primaire uitleg.
- Bij onzekerheid toont het programma de relevante originele pagina en het voorstel naast elkaar.
- Batchacties voor gelijksoortige bevestigingen, met mogelijkheid om terug te draaien.
- Automatisch opslaan en hervatten na afsluiten of crash.
- Overzicht met aantallen: herkend, gecontroleerd, onzeker, ontbrekend, afgekeurd en gereed.

## Portable uitgangspunt
Windows-mapapplicatie, zonder installatie op de doelcomputer. Python-runtime en bibliotheken worden tijdens de build in de applicatiemap gebundeld. Geen administratorrechten, services of systeemwijzigingen. Kernverwerking werkt offline. Optionele AI-adapters zijn uitgeschakeld totdat de gebruiker ze zelf activeert.
