# Indicatoren voor bronkwaliteit, bewijssterkte en relevantie

## Waarom drie aparte indicatoren?

De website gebruikt drie onafhankelijke redactionele beoordelingen. Ze beantwoorden verschillende vragen en worden daarom niet samengevoegd tot één totaalscore.

1. **Bronkwaliteit** – waar komt de informatie vandaan en welke redactionele toetsing heeft plaatsgevonden?
2. **Bewijssterkte** – hoe sterk ondersteunt de onderzoeksopzet de conclusies die in de publicatie worden getrokken?
3. **Curriculum- of onderwijsrelevantie** – hoe bruikbaar is de inhoud voor de havo/vwo-examenstof of voor de biologieles?

Een peer-reviewed artikel kan methodologisch zwak zijn. Een praktijkbron kan zeer bruikbaar zijn zonder een effectstudie te zijn. Een sterke wetenschappelijke studie kan specialistisch zijn en slechts indirect aansluiten op de examenstof.

## 1. Bronkwaliteit

| Label | Betekenis | Wat het nadrukkelijk niet betekent |
|---|---|---|
| Peer-reviewed tijdschrift | Wetenschappelijk tijdschrift waarin manuscripten vooraf door vakgenoten worden beoordeeld. | Geen garantie voor correcte conclusies, onafhankelijkheid, replicatie of hoge bewijskracht. |
| Institutionele kennisbron | Kennisoverzicht of publicatie van een herkenbaar kennisinstituut/platform, met een redactionele of inhoudelijke selectie. | Niet automatisch primair onderzoek of een systematische review. Controleer de achterliggende bronnen. |
| Professionele praktijkbron | Professionele publicatie, praktijkbeschrijving of ontwikkelproduct, bijvoorbeeld van een onderwijsplatform of vakorganisatie. | Geen peer-reviewed effectonderzoek; praktijkwaarde kan wel degelijk hoog zijn. |

De bronsoort wordt op basis van de concrete publicatie en haar uitgever bepaald. De indicator is geen ranglijst van organisaties.

## 2. Bewijssterkte

De korte labels op kaarten zijn samenvattingen; de tooltip bevat de onderbouwing en beperkingen.

| Label op kaart | Interpretatie |
|---|---|
| Sterke synthese | Meerdere studies zijn systematisch samengebracht (bijvoorbeeld een meta-analyse). Kijk ook naar heterogeniteit, kwaliteit van de primaire studies en toepasbaarheid. |
| Ondersteunend onderzoek | Primair onderzoek levert relevante empirische of mechanistische aanwijzingen. De bewijskracht hangt af van design, controlegroepen, steekproef, modelorganisme en replicatie. |
| Beperkt / voorzichtig | Er zijn duidelijke beperkingen, bijvoorbeeld observationeel of cross-sectioneel design, kleine steekproef, geen controlegroep of onzekere causaliteit. |
| Voorlopig bewijs | Exploratief of vroeg bewijs; conclusies vragen om onafhankelijke bevestiging of sterker vervolgonderzoek. |
| Achtergrond / review | Review of conceptuele synthese die context en verklaringsmodellen biedt; niet noodzakelijk een systematische effect- of bewijssynthese. |
| Kennisoverzicht | Secundair redactioneel overzicht; geen zelfstandige primaire effectmeting. |
| Praktijkbron | Ontwerp, ervaring of praktijkmateriaal zonder gecontroleerde effectmeting. |

Dit is geen universele hiërarchie die los van de onderzoeksvraag kan worden toegepast. Een kwalitatieve studie kan bijvoorbeeld zeer geschikt zijn om ervaringen of denkprocessen te beschrijven, maar niet om een causaal leereffect vast te stellen.

## 3. Curriculum- of onderwijsrelevantie

### Vakinhoudelijke pagina
- **Direct:** de biologische kern sluit rechtstreeks aan op een herkenbaar onderdeel of eindterm van het huidige of toekomstige programma.
- **Aansluitend:** de publicatie ondersteunt een aangrenzend concept of biedt een bruikbare context, maar de relatie met de eindterm is minder direct.
- **Verdieping:** de inhoud gaat duidelijk verder dan de vereiste examenstof en is vooral geschikt voor verdieping, docentkennis of kritische bespreking.

De kaart vermeldt afzonderlijk de schoolsoort, de huidige syllabus en/of de conceptprogramma's. Conceptprogramma's zijn niet definitief; de koppeling is een redactionele duiding en geen officiële CvTE-classificatie.

### Pedagogisch-didactische pagina
Dezelfde schaal geeft aan hoe direct de bron toepasbaar is op de biologieles:
- **Direct:** concrete, overdraagbare implicaties voor biologielessen, practica of toetsing.
- **Aansluitend:** relevante onderwijsinzichten die een vertaalslag naar biologie vragen.
- **Verdieping:** vooral theoretisch, specialistisch of indirect bruikbaar.

## 4. Redactionele werkwijze

- De drie beoordelingen worden onafhankelijk van elkaar toegekend.
- Elke indicator heeft een toelichting die uitlegt waarop het oordeel berust.
- Bronkwaliteit wordt niet afgeleid uit de effectgrootte of uit het soort onderzoeksdesign.
- Bewijssterkte wordt niet afgeleid uit de reputatie van het tijdschrift.
- Relevantie wordt niet afgeleid uit bewijssterkte: een zwak onderbouwde bron kan een relevante lesvraag opleveren.
- Bij observationeel onderzoek wordt correlatie niet als causaliteit gepresenteerd.
- Bij modelorganismen, kleine steekproeven en contextgebonden studies wordt de generaliseerbaarheid expliciet begrensd.
- De beoordelingen zijn redactionele hulpmiddelen, geen formele kwaliteitskeurmerken of automatische beoordeling van individuele onderzoekers.

## 5. Technische velden

Elk record bevat:
- `sourceQualityLevel` en `sourceQualityNote`
- `evidenceLevel` en `evidenceNote`
- `relevanceLevel` en `relevanceNote`

De toegestane bronkwaliteitswaarden worden gecontroleerd door `scripts/validate-site.mjs`. Bij nieuwe records moeten alle zes velden gevuld zijn.


## 6. Canonieke waarden voor bewijssterkte

De database bewaart de volgende waarden in `evidenceLevel`; de frontend vertaalt ze naar korte labels:

| Databasewaarde | Weergavelabel | Gebruik |
|---|---|---|
| `Breed onderbouwd` | Sterke synthese | Systematische synthese/meta-analyse of brede, transparante basis van meerdere studies. |
| `Ondersteunend bewijs` | Ondersteunend onderzoek | Empirische ondersteuning; sterkte hangt af van onderzoeksdesign en beperkingen. |
| `Achtergrondbron` | Achtergrond / review | Review, scoping review, perspectief of conceptuele context zonder gepoolde effectschatting. |
| `Voorzichtig interpreteren` | Beperkt / voorzichtig | Beperkingen in steekproef, design, causaliteit of generaliseerbaarheid zijn bepalend. |
| `Voorlopig bewijs` | Voorlopig bewijs | Exploratief, vroeg of zeer kleinschalig onderzoek dat onafhankelijke bevestiging vraagt. |
| `Kennisoverzicht` | Kennisoverzicht | Redactionele synthese door een kennisinstituut of platform. |
| `Praktijkbron` | Praktijkbron | Praktijkervaring, ontwerp of materiaal zonder gecontroleerde effectmeting. |

Gebruik geen vrije tekstlabels in `evidenceLevel`. Nuance hoort in `evidenceNote`, niet in een nieuwe enumwaarde. Bronkwaliteit, bewijssterkte en relevantie blijven afzonderlijke dimensies.
