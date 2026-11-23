# Wijzigingen Examenverwerker 0.16

## Herstel van stitch- en fragmentgrenzen

- De witruimte tussen opeenvolgende gecropte pagina's is vergroot van 12 naar 32 pixels. De witte strook is daardoor duidelijk zichtbaar, zonder de bronafbeeldingen te vervormen.
- De herkenning van witregels is conservatiever gemaakt. Gewone regelafstanden worden niet langer zo gemakkelijk als grens tussen context en vraag gezien.
- De bovengrens van een vraagfragment wordt gekoppeld aan het goedgekeurde vraagstartanker. Een witruimte vóór het vraagnummer kan daardoor niet langer de bovenkant van de vraag naar een eerdere contextregel verschuiven.
- Er is een integratietest toegevoegd die de volledige API-route voor stap 4 aanroept nadat de vraagstarts zijn goedgekeurd.

## Teststatus

De nieuwe regressietests worden door GitHub Actions uitgevoerd. Een geslaagde test van synthetische PDF's is geen vervanging voor visuele controle van een volledig echt examen.
