# Inhoudelijke controle examendataset — eerste bevindingen

Status: lopende controle; dataset nog niet geschikt voor publicatie zonder inhoudelijke correcties en docentvalidatie.

## Waarom deze controle nodig is

De eerdere importer- en browsertests bevestigen dat alle 519 vragen technisch geladen kunnen worden. Dat bewijst niet dat de geëxtraheerde antwoorden en vraagtypen inhoudelijk correct zijn. Een eerste gerichte controle van de twaalf JSON-bestanden heeft hieronder concrete extractieproblemen gevonden.

## Gevonden afwijkingen

### 1. Antwoordvelden lopen door in administratieve tekst

Bij de laatste vraag van zeven examens bevat `answer_data.raw_text` niet alleen het antwoord en eventuele beoordelingsopmerkingen, maar ook tekst uit de administratieve slotpagina's van het correctievoorschrift (onder andere 'Aanleveren scores' en 'Bronvermeldingen').

| Examen | Vraag-ID | Probleem |
|---|---|---|
| havo 2024 tijdvak 1 | `ha24t1-45` | Antwoordtekst loopt door in instructies en bronvermeldingen |
| havo 2025 tijdvak 1 | `ha25t1-48` | Antwoordtekst loopt door in instructies en bronvermeldingen |
| havo 2025 tijdvak 2 | `ha25t2-44` | Antwoordtekst loopt door in instructies en bronvermeldingen |
| vwo 2024 tijdvak 1 | `vw24t1-42` | Antwoordtekst loopt door in instructies en bronvermeldingen |
| vwo 2024 tijdvak 2 | `vw24t2-41` | Antwoordtekst loopt door in bronvermeldingen |
| vwo 2026 tijdvak 1 | `vw26t1-41` | Antwoordtekst loopt door in instructies en bronvermeldingen |
| vwo 2026 tijdvak 2 | `vw26t2-39` | Antwoordtekst loopt door in bronvermeldingen |

De velden `model_answer`, `scoring` en `remarks` moeten per vraag afzonderlijk tegen het officiële correctievoorschrift worden gecontroleerd. Het afkappen van tekst op basis van alleen een herkenbare slotmarker is geen veilige inhoudelijke correctie.

### 2. Mogelijk verkeerd vraagtype of foutieve antwoordsleutel

- `ha24t1-1` is als `open` opgeslagen.
- Het modelantwoord is letterlijk `(alleen de letter) Q`.
- `correct_answer` is `null`.

Dit is verdacht: een enkelletterig antwoord past niet bij de gebruikelijke verwerking van een open vraag, terwijl 'Q' geen gangbare antwoordoptieletter is. De oorspronkelijke opgave en het correctievoorschrift moeten worden geraadpleegd. De juiste letter of het juiste vraagtype wordt nadrukkelijk niet automatisch geraden.

## Nieuwe automatische controle

`scripts/audit_claude_exam_dataset.py` controleert voortaan onder meer:
- doorlopende vraagnummering en documentvolgorde;
- verwijzingen naar bestaande contexten en bron-PDF's;
- grenzen van uitsnede-coördinaten;
- administratieve tekst die in antwoordvelden terechtkomt;
- enkelletterige modelantwoorden bij open vragen;
- meerkeuzevragen zonder expliciete antwoordsleutel.

De controle is niet-destructief: zij wijzigt geen examendata. Waarschuwingen blijven zichtbaar, zodat ze handmatig aan de originele PDF's kunnen worden getoetst. Structurele fouten laten de controle falen.

## Aanvullende structurele steekproeven over alle 519 vragen

Een afzonderlijke scan van alle twaalf JSON-bestanden geeft de volgende structurele uitkomsten:
- Alle 369 open vragen hebben zowel een niet-leeg `raw_text`- als `model_answer`-veld.
- Alle 150 meerkeuzevragen hebben een expliciete antwoordsleutel.
- De maximumscore in de vraagmetadata komt bij alle 519 vragen overeen met `answer_data.maximum_score`.
- De bronfragmenten hebben bij alle 519 vragen een opeenvolgende `order`-volgorde.

Dit bevestigt alleen aanwezigheid en onderlinge consistentie van velden. Het bevestigt niet dat de antwoorden, scorepunten of gekozen fragmenten inhoudelijk juist zijn.

## Nog uit te voeren vóór publicatie

1. De zeven vervuilde antwoordvelden vergelijken met de officiële correctievoorschriften en de antwoord-/scorevelden corrigeren.
2. Vraag `ha24t1-1` controleren aan de hand van opgavenboekje en correctievoorschrift; type en sleutel pas daarna aanpassen.
3. De overige 511 vragen systematisch controleren op antwoordinhoud, scoreverdeling, contextkoppeling en volledigheid van afbeeldingen/tabellen.
4. De 519 snippets op volledige resolutie nalopen, in het bijzonder kleine tekst, bijschriften, grafieken en uitsnederanden.
5. De geconstateerde correcties opnieuw testen in de preview.

De bestaande productiepagina en `main` blijven buiten deze controle ongewijzigd. De pull request blijft een draft totdat de inhoudelijke controle is afgerond.
