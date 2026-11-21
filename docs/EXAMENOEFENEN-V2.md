# Examenoefenen v2 — dataset staging

Deze documentatie hoort bij de afzonderlijke ontwikkelpagina `examenoefenen-v2-preview.html`.
De bestaande `examenoefenen.html` blijft de productiepagina totdat de nieuwe versie volledig is
gecontroleerd en bewust wordt omgeschakeld.

## Verwachte dataset

De Claude-export bevat twaalf examendatasets: havo en vwo, 2024 t/m 2026, tijdvak 1 en 2.
De import maakt deze structuur aan:

```text
exam-data/
└── claude-2024-2026/
    ├── manifest.json
    ├── data/
    │   ├── havo-2024-t1.json
    │   ├── ...
    │   └── vwo-2026-t2.json
    └── snippets/
        ├── havo-2024-t1/
        │   └── ...
        └── ...
```

De preview haalt JSON op uit `exam-data/claude-2024-2026/data/` en toont de originele
PNG-fragmenten vanaf `exam-data/claude-2024-2026/`. Bron-PDF's worden gekoppeld vanuit
de bestaande map `examens/`.

## Dataset veilig importeren

Voer de import uit naar een nieuwe, nog niet bestaande directory. Het script weigert bewust
een bestaande doelmap te overschrijven.

```bash
python scripts/import_claude_exam_dataset.py \
  /pad/naar/biologie-examens-havo-vwo-2024-2026.zip \
  --output-dir exam-data/claude-2024-2026
```

Het script controleert vóór het kopiëren onder meer:

- ZIP-integriteit en CRC-controle;
- volledigheid van het manifest, de twaalf examens en alle gedeclareerde bestanden;
- bestandsgrootte en SHA-256 van ieder bestand;
- examenniveau, jaar en tijdvak in de JSON-metadata;
- unieke vraag-ID's en toegestane vraagtypen;
- aanwezige bronfragmenten en unieke PNG-bestanden met geldige PNG-signatuur;
- het totale aantal vragen volgens het manifest.

Bij een fout wordt de import afgebroken. Als er tijdens het schrijven iets misgaat, wordt de
onvolledige staging-map opgeruimd. Bestaande examenbestanden worden niet aangepast.

## Tests

```bash
python -m compileall -q scripts/import_claude_exam_dataset.py tests
python -m unittest discover -s tests -p "test_*exam*.py" -v
```

De GitHub Actions-workflow voert deze regressietests automatisch uit bij relevante wijzigingen.

## Nakijkgedrag en kwaliteitsstatus

- Meerkeuzevragen worden alleen automatisch nagekeken als `answer_data.correct_answer`
  expliciet aanwezig is.
- Open vragen worden nooit automatisch beoordeeld. De leerling vergelijkt het eigen antwoord
  met het geëxtraheerde modelantwoord en de scorepunten en kent zelf een score toe.
- De oorspronkelijke vraagafbeelding blijft leidend; de preview reconstrueert geen figuren,
  tabellen of vraagtekst uit OCR.
- De Claude-audit is een voorlopige kwaliteitscontrole, geen onafhankelijke docentvalidatie.
  Antwoorden, scorepunten, bronverwijzingen en afbeeldingen moeten vóór publicatie inhoudelijk
  en visueel worden gecontroleerd.

## Publicatievoorwaarden

De preview is geen productiepagina. Publicatie is pas verantwoord nadat:

1. alle twaalf JSON-bestanden en alle 519 afbeeldingen zijn geïmporteerd;
2. alle bron-PDF-verwijzingen naar bestaande bestanden verwijzen;
3. aantallen, unieke ID's, contextkoppelingen en afbeeldingskoppelingen kloppen;
4. alle vragen en afbeeldingen systematisch visueel zijn nagelopen;
5. correctievoorschriften en antwoordextracties inhoudelijk zijn gecontroleerd;
6. filters, antwoorden, voortgang en navigatie in een browser zijn getest.

Tot die tijd blijven `main`, de bestaande oefenpagina en de huidige examenbestanden ongewijzigd.
