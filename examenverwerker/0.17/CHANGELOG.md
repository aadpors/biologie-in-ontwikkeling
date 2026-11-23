# Examenverwerker 0.17

## Stap 3 — fragmentselectie en bediening

- De automatische fragmentvoorstellen worden naar rijen gesnapt die over de volledige breedte exact wit zijn.
- De server controleert dezelfde voorwaarde bij iedere opslag. Een grens op een rij met ook maar één niet-witte pixel wordt geweigerd.
- De lijst toont doorlopende fragmentnummers: "Fragment 1 context" of "Fragment 2 vraag". Daaronder staat "Vraag 1" of "Vragen 1, 2", afhankelijk van het aantal gekoppelde vragen.
- Het onderdeel "Geselecteerd fragment" staat direct onder de actieve regel in de rechterkolom.
- Selecteren in de rechterkolom centreert het bijbehorende fragment in het middendeel. Selecteren in het middendeel brengt de juiste regel in de rechterkolom in beeld.
- De scrollpositie van de twee panelen wordt in beide richtingen gesynchroniseerd.

## Stap 4 — foutdiagnose en integratie

- Niet-JSON HTTP-fouten worden niet langer vervangen door een algemene foutmelding. De statuscode en servermelding blijven zichtbaar.
- Er is een end-to-end API-regressietest toegevoegd die stap 3 opslaat, afrondt en vervolgens de stap-4-analyse ophaalt.

## Testgrenzen

De witte-rijcontrole wordt op synthetische PDF's getest. Visuele beoordeling van de automatische segmentatie met een echt examen blijft noodzakelijk.

## Correctie na integratietest

- De afrondactie van stap 3 stuurt nu de volledige lijst met gecontroleerde vraagnummers door; het aantal wordt niet langer over hetzelfde opslagveld geschreven.
- Bestaande dossiers waarin een ouder 0.17-scherm al een integer had opgeslagen, openen stap 4 nu zonder serverfout. De individuele reviewvinkjes worden in dat geval niet automatisch als gecontroleerd beschouwd.
- Het verslepen en numeriek aanpassen van grenzen blijft binnen de geldige witte-rijintervallen, ook bij de minimale fragmenthoogte.
