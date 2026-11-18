# Publicatie- en kwaliteitscontroles

Een examen is pas exporteerbaar wanneer alle verplichte controles groen zijn.

## Documenten
- Opgaven-PDF aanwezig en volledig leesbaar.
- Correctievoorschrift aanwezig en gekoppeld.
- Aanvullingen/errata gecontroleerd; expliciet vastgelegd als niet aanwezig indien dat na controle klopt.
- Uitwerkbijlage gekoppeld wanneer ernaar wordt verwezen; volledige originele PDF blijft downloadbaar.
- Bestanden uniek, ongewijzigd en voorzien van SHA-256.

## Vragen
- Alle vraag- en deelvraagstarts gecontroleerd, ook meerkeuzevragen.
- Nummering uniek en in de juiste volgorde; afwijkingen verklaard.
- Geen ontbrekende, dubbele of per ongeluk als vraag herkende paginanummers.
- Vraagtekst, antwoordopties, punten en bronverwijzingen compleet.
- CV-deelvraag en puntenverdeling corresponderen met de opgave.
- Contexten en figuren over pagina's heen correct gekoppeld.

## Snippets
- Iedere snippet komt rechtstreeks uit de originele PDF.
- Alle relevante labels, legenda's, bijschriften, assen, tabellen en figuuronderdelen zijn zichtbaar.
- Geen afgesneden tekst of onleesbare schaal.
- Beeldverhouding en resolutie behouden; geen inhoudelijke beeldbewerking.
- Bij context die op een eerdere pagina staat: meerdere bronfragmenten koppelen of ruimere contextsnip maken.
- Visuele vergelijking met de volledige originele pagina verplicht.

## Website-export
- Schema en verplichte velden gecontroleerd tegen bestaande JSON.
- ID's uniek; paden bestaan; afbeeldingen openen.
- Vraagtotalen per examen en vraagtype plausibel en verklaard.
- Bestaande examens worden niet stilzwijgend overschreven.
- Manifest bevat bronhashes, softwareversie, validatierapport en menselijke goedkeuring.
- Uitwerkbijlage-bestanden worden als volledige PDF meegeleverd en gelinkt.

## Blokkerende voorwaarden
Elke ontbrekende bron, onzekere vraaggrens, onvolledige context, niet-geverifieerde CV-koppeling, mislukte beeldcontrole of schemafout blokkeert publicatie. Een handmatige override vereist een expliciete reden en wordt in het auditlog vastgelegd.
