# Examenverwerker 0.17

## Stap 3 — fragmentselectie en bediening

- De automatische fragmentvoorstellen worden naar rijen gesnapt die over de volledige breedte exact wit zijn.
- De server controleert dezelfde voorwaarde bij iedere opslag. Een grens op een rij met ook maar één niet-witte pixel wordt geweigerd.
- De lijst gebruikt inhoudelijke labels zoals "Vraag 1" en "Context bij vraag 1, 2 en 4". Technische fragmentnummers worden niet getoond; de volgorde volgt de fysieke positie in het document.
- Het onderdeel "Geselecteerd fragment" staat direct onder de actieve regel in de rechterkolom.
- Selecteren in de rechterkolom centreert het bijbehorende fragment in het middendeel. Selecteren in het middendeel brengt de juiste regel in de rechterkolom in beeld.
- De scrollpositie van de twee panelen wordt in beide richtingen gesynchroniseerd.

## Aanvullende correcties voor stap 3

- De knop **Nieuw fragment selecteren** staat buiten het interne scrollgebied van de examenafbeelding. Alleen de lange afbeelding en de fragmentenlijst hebben hun eigen scrollpositie.
- Selecteren en scrollen synchroniseren uitsluitend het afbeeldingspaneel en de fragmentenlijst. Navigatie gebruikt de eigen scrollcontainers en verplaatst de volledige pagina niet.
- De bovengrens wordt op de onderste volledig witte pixelrij van de scheidingsstrook geplaatst; de ondergrens op de bovenste volledig witte pixelrij.
- Oude automatisch aangemaakte contextfragmenten tussen twee vragen worden bij het heropenen hersteld naar de voorafgaande vraag. Handmatig samengestelde koppelingen blijven behouden.
- Een vertraagde, identieke autosave kan de goedkeuring van de vraagstartcontrole niet meer terugzetten. De statuscontrole en conceptopslag vinden nu in één SQLite-schrijftransactie plaats; echte wijzigingen maken de goedkeuring wel ongeldig.
- Regressietests toegevoegd voor de vertraagde autosave, herstel van oude contextkoppelingen en de exacte boven-/onderrand van fragmenten.

## Stap 4 — foutdiagnose en integratie

- Niet-JSON HTTP-fouten worden niet langer vervangen door een algemene foutmelding. De statuscode en servermelding blijven zichtbaar.
- Er is een end-to-end API-regressietest toegevoegd die stap 3 opslaat, afrondt en vervolgens de stap-4-analyse ophaalt.

## Testgrenzen

De witte-rijcontrole wordt op synthetische PDF's getest. Visuele beoordeling van de automatische segmentatie met een echt examen blijft noodzakelijk.

## Correctie na integratietest

- De afrondactie van stap 3 stuurt nu de volledige lijst met gecontroleerde vraagnummers door; het aantal wordt niet langer over hetzelfde opslagveld geschreven.
- Bestaande dossiers waarin een ouder 0.17-scherm al een integer had opgeslagen, openen stap 4 nu zonder serverfout. De individuele reviewvinkjes worden in dat geval niet automatisch als gecontroleerd beschouwd.
- Het verslepen en numeriek aanpassen van grenzen blijft binnen de geldige witte-rijintervallen, ook bij de minimale fragmenthoogte.

## Automatische fragmentvoorstellen op basis van echt examen (vwo 2026 tijdvak 2)

De CI-diagnose op het aanwezige echte examen liet twee concrete fouten zien:
vraagfragmenten konden overlappen bij meerdere vragen op één pagina, en lege
witruimtes werden soms als context voorgesteld. Daarom:

- Vraagfragmenten worden op leesvolgorde genormaliseerd en eindigen uiterlijk bij de witte grens van de volgende vraag.
- Als een heuristische ondergrens midden in een vraag valt, loopt het fragment door tot de volgende vraaggrens.
- Contexten worden opnieuw opgebouwd uit de ruimte tussen de vraagfragmenten, maar alleen wanneer daarin daadwerkelijk niet-witte inhoud staat. Een context tussen vraag 37 en 38 wordt aan vraag 37 gekoppeld, niet aan vraag 38.
- Lege contextstroken en vraagfragmenten zonder zichtbare inhoud worden niet als voorstel getoond.
- De regressietest controleert expliciet dat overlappende vraagfragmenten worden voorkomen en witruimte niet als context wordt aangemerkt.

De CI-diagnose op het echte vwo-examen 2026 tijdvak 2 controleert nu bovendien
dat alle 39 hoofdvragen precies één vraagfragment hebben, dat geen vraagfragmenten
overlappen en dat iedere context- en vraaggrens op een volledig witte rij ligt.
In de uitgevoerde diagnose leverde dit 39 vraagfragmenten en 23 contextfragmenten
op, zonder overlappende vraagfragmenten.
