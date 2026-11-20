# Examenverwerker

Een zelfstandige Windows-applicatie om examen-PDF's vakoverstijgend te verwerken. De basisworkflow is bedoeld voor onder meer biologie, aardrijkskunde en andere schoolvakken. Vakinhoudelijke publicatie- of beoordelingsvelden worden niet tijdens de fragmentselectie afgedwongen.

## Werkwijze

1. Kies **Examens importeren** en selecteer de PDF's van één vak. Vul bij de vraag naar het vak bijvoorbeeld *Biologie* of *Aardrijkskunde* in.
2. Controleer de voorgestelde documenttypen en examenmetadata. De applicatie groepeert examens op niveau, jaar en tijdvak. De vaknaam wordt in de projectmap opgenomen, zodat vakken elkaar niet overschrijven.
3. Laat de vraagstarts analyseren. Bevestig, wijs af of markeer twijfel. Voeg ontbrekende vraagstarts zo nodig handmatig toe.
4. Open **Structuur bewerken**. Er zijn precies twee fragmenttypen:
   - **Context**: tekst, afbeelding, tabel of ander materiaal dat bij één of meer vragen hoort.
   - **Vraag**: de vraag vanaf de vraagstart tot de eerstvolgende witregel of kadergrens (wat het eerst komt). Controleer en corrigeer de voorgestelde grens.
5. Koppel contextfragmenten aan de juiste vragen. Fragmenten mogen over meerdere pagina's lopen. De oorspronkelijke PDF wordt niet aangepast.
6. Klik op **Fragmenten klaar**. Daarna bepaalt het programma automatisch de vraagtypen op basis van de gekozen vraagfragmenten en maakt het per vraag een eenvoudig conceptrecord met vraagnummer, vraagtekst, vraagtype en gekoppelde context. Er is geen aparte knop om vraagrecords te maken.
7. Bekijk zo nodig **Eindcontrole** om de vraagtekst of het vraagtype eenvoudig aan te passen.
8. Kies **Exportpakket** voor een overdraagbaar conceptexportbestand. Het pakket bevat de conceptvragen, fragmentstructuur en bron-PDF's. Dit is geen automatische publicatie naar een website.

## Ontwerpkeuzes

- De vraagtypeanalyse gebruikt de opgeslagen, geselecteerde vraagfragmenten. De oorspronkelijke PDF wordt niet opnieuw gebruikt om vraaggrenzen of vraaginhoud te bepalen.
- Bij bestaande projecten met eerder gecontroleerde fragmenten vult de applicatie ontbrekende fragmenttekst automatisch aan binnen de al opgeslagen grenzen. De fragmenten hoeven niet opnieuw te worden afgevinkt.
- Bij een scan zonder uitleesbare tekst wordt het vraagtype als onbekend gemarkeerd; het programma verzint geen tekst of antwoordopties.
- Het programma maakt geen onnodige biologische metadata aan voor andere vakken.
- Biologie-specifieke correctietools worden alleen bij een biologieproject getoond.
- Originele PDF's blijven ongewijzigd. Exportbestanden worden niet over bestaande bestanden heen geschreven.

## Installeren en starten

1. Download en pak de volledige ZIP-map uit.
2. Dubbelklik op **START.bat**.
3. De doelcomputer heeft geen Python-installatie of administratorrechten nodig.

Vervang bij een software-update alleen de programmamap. Projecten en de leerbank staan apart onder `%LOCALAPPDATA%\BiologieExamenverwerker\`; de bestaande projectbestanden worden niet door het vervangen van de programmamap overschreven. Maak desondanks regelmatig een reservekopie van deze gegevens.

## Ontwikkelomgeving

Voor ontwikkelen is Python 3.12 vereist:

```bat
python -m pip install -r requirements.txt
python app.py
```

De regressietests starten met:

```bat
python -m unittest discover -s tests -v
```

## Grenzen van deze versie

- De automatische vraaggrens is een voorstel; controleer altijd of de eerstvolgende witregel of kadergrens ook inhoudelijk de juiste grens is.
- Bij beeldvragen zonder uitleesbare tekst blijft de vraagtypeanalyse onzeker.
- De conceptexport is een overdraagbaar gegevenspakket, geen websitepublicatie.
- De portable Windows-build is automatisch getest in CI; test de gebruikersinterface daarnaast op een echte Windows-computer met eigen examens.
