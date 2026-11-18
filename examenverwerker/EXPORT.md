# Veilige website-export

De exporter sluit aan op het bestaande contract dat \`examenoefenen.html\` gebruikt.

## Publicatiepoort
Een record wordt alleen geëxporteerd wanneer:
- een mens het expliciet heeft goedgekeurd;
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
