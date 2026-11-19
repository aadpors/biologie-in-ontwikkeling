# Veilige website-export

De exporter sluit aan op het bestaande contract dat \`examenoefenen.html\` gebruikt.

## Publicatiepoort
Een record wordt alleen geëxporteerd wanneer:
- een mens het expliciet heeft goedgekeurd;
- alle verplichte onderdelen van de menselijke eindcontrolechecklist zijn afgevinkt;
- het record niet ongeldig is geworden door een nieuwe analyse van de bron-PDF;
- de handmatige vraagafbakening aan het exacte opgavenbestand en het juiste vraagnummer gekoppeld is;
- de volledige CV-regio handmatig is afgebakend, gekoppeld aan het juiste CV en niet gewijzigd is;
- iedere geselecteerde officiële CV-aanvulling een eigen vraaggebonden afbakening en uitsnede heeft;
- alle contextbestanden bestaan, aan dezelfde opgavenbron zijn gekoppeld, bijschriften expliciet zijn bevestigd en afzonderlijk van de vraagafbeelding worden geëxporteerd;
- opgaven, CV, uitwerkbijlagen en CV-aanvullingen aantoonbaar bij hetzelfde niveau, jaar en tijdvak horen (of de koppeling per document expliciet handmatig is bevestigd);
- status op goedgekeurd staat;
- examenmetadata compleet is;
- opgaven-PDF en correctievoorschrift aanwezig zijn;
- de vraag- en contextsnippets bestaan;
- bij open vragen een CV-snippet bestaat (de huidige website verwacht één primaire CV-afbeelding en eventueel één aanvulling);
- vraagtekst compleet is;
- eventuele uitwerkbijlagen aanwezig zijn.

## Resultaat
- \`exam-mcq.json\`
- \`exam-open.json\`
- \`exam-contexts.json\`
- \`scripts/cv-snippets.json\`
- \`examens/\` met originele opgaven, correctievoorschriften en volledige uitwerkbijlagen
- \`exam-snippets/\` met goedgekeurde PDF-renders
- \`manifest.json\` met bronhashes en menselijke goedkeuring

De exporter gebruikt het bestaande veld \`attachmentPdfs\` voor volledige uitwerkbijlagen. De huidige website toont die als afzonderlijke PDF-links bij de vraag. Officiële CV-aanvullingen worden volledig in `examens/` bewaard en in het manifest verantwoord; het bestaande website-JSON-contract wordt daarvoor niet uitgebreid.

De uitvoermap moet nieuw of leeg zijn. De exporter overschrijft nooit bestaande bestanden en publiceert nooit rechtstreeks naar de live website.


Vraagafbeeldingen in `exam-open.json` zijn uitsluitend de handmatig begrensde vraagregio's. Contextafbeeldingen worden apart opgenomen in `exam-contexts.json` (`contextImages` en `contextAssets`), met bijschriften en eventuele tekstregio's. Het manifest bewaart de exacte genormaliseerde paginagrenzen en bronhashes. De oorspronkelijke PDF's blijven volledig beschikbaar in `examens/`.

Bij contextfiguren en -tabellen wordt de caption afzonderlijk bewaard. Een automatische caption is slechts een voorstel; de gebruiker moet deze bevestigen of corrigeren voordat export mogelijk is. Een ontbrekend bijschrift kan expliciet als zodanig worden bevestigd.


Voor compatibiliteit met de huidige `examenoefenen.html` bevat `exam-contexts.json` per vraag `images` in deze vaste volgorde: eerst alle geselecteerde contextuitsneden, daarna de handmatig afgebakende vraaguitsnede als laatste afbeelding. De website gebruikt de laatste afbeelding als de oorspronkelijke vraag en eerdere afbeeldingen als context. `contextImages` blijft daarnaast als expliciete context-only lijst beschikbaar voor toekomstige weergaven.
