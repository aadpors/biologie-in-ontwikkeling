# Veilige website-export

De exporter schrijft uitsluitend naar een nieuwe, lege uitvoermap. Hij overschrijft nooit de live website, bestaande JSON of eerdere export.

## Publicatiepoort
Een record wordt alleen geëxporteerd wanneer:
- een mens het expliciet heeft goedgekeurd;
- status op goedgekeurd staat;
- examenmetadata compleet is;
- opgaven-PDF en correctievoorschrift aanwezig zijn;
- een snippetbestand aanwezig is;
- vraagtekst compleet is;
- eventuele uitwerkbijlagen aanwezig zijn.

## Resultaat
- `exam-mcq.json`
- `exam-open.json`
- `examens/` met originele opgaven, correctievoorschriften en volledige uitwerkbijlagen
- `exam-snippets/` met goedgekeurde PDF-renders
- `manifest.json` met hashes en goedkeuringsherkomst

De volledige uitwerkbijlage wordt fysiek in het exportpakket opgenomen. De bestaande website kent nog geen bevestigd veld voor een afzonderlijke uitwerkbijlage-link; daarom wordt geen onbekend JSON-veld stilzwijgend in de productiegegevens geschreven. De uiteindelijke websitekoppeling moet eerst worden gecontroleerd en getest.
