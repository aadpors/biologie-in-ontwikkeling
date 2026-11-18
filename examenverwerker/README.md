# Biologie Examenverwerker

Nieuwe, zelfstandige verwerker binnen de bestaande repository. De website en bestaande examendata blijven onaangeraakt.

## Starten (ontwikkelversie)
1. Installeer Python 3.12 (alleen voor ontwikkeling).
2. Open deze map in een terminal.
3. Voer uit: `python -m pip install -r requirements.txt`
4. Start met `python app.py` of dubbelklik op `START.bat`.

## Portable Windows-build
Voer op een Windows-machine met Python 3.12 uit: `BUILD_PORTABLE.bat`. Het resultaat komt in `dist\BiologieExamenverwerker\`. De doelcomputer heeft daarna geen Python-installatie nodig. De build is een map-applicatie; niets wordt in Windows geïnstalleerd.

## Wat deze eerste fundering doet
- Maakt een zelfstandig examenproject aan.
- Neemt originele PDF's ongewijzigd op en berekent SHA-256-controlesommen.
- Herkent voorlopig op basis van inhoud en bestandsnaam opgaven, correctievoorschriften, uitwerkbijlagen en aanvullingen.
- Leest PDF-metadata, pagina-aantallen en tekst per pagina.
- Bewaart voortgang, bronbestanden en tekstextracties in een hervatbaar project.
- Markeert onzekere documentherkenning expliciet voor controle.

## Betrouwbaarheidsregels
- Originele PDF's worden nooit aangepast.
- Automatische herkenning is een voorstel, geen inhoudelijke goedkeuring.
- Er wordt niets naar de website gepubliceerd.
- Een project kan altijd opnieuw worden geopend; bestanden met dezelfde inhoud worden niet dubbel geïmporteerd.

## Ontwikkelstatus
Dit is fase 1: portable fundament en documentinname. Vraagdetectie, koppeling van contexten/figuren, CV-controle, snippetproductie, leren van correcties en publicatiecontrole volgen als afzonderlijke modules. Er wordt pas gepubliceerd na volledige inhoudelijke én visuele kwaliteitscontrole.
