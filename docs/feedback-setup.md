# Gezamenlijke relevantiefeedback instellen

De website is een statische GitHub Pages-site. Supabase bewaart anonieme stemmen zodat bezoekers hun eigen stem kunnen wijzigen en de website gezamenlijke aantallen kan tonen.

## Status van de inrichting

- De tabel `public.publication_feedback` is aangemaakt in het Supabase-project.
- Row Level Security (RLS) staat aan; bezoekers kunnen uitsluitend hun eigen stem beheren.
- De totalen worden via een afgeschermde databasefunctie beschikbaar gemaakt.
- De Supabase Project URL en publieke publishable key zijn inmiddels in `index.html` gezet.
- De JavaScript is syntactisch gecontroleerd.
- **Nog handmatig nodig:** Anonymous Sign-Ins inschakelen in Supabase Auth en daarna de live website testen.

## Eenmalige handeling die nog nodig is

1. Open Supabase → **Authentication** → **Sign In / Providers** (de precieze menunaam kan iets verschillen).
2. Zoek **Anonymous Sign-Ins** en schakel dit in.
3. Wacht tot GitHub Pages de nieuwste commit heeft gepubliceerd en open de website in een privévenster.
4. Controleer of de feedbackfunctie aangeeft dat je anoniem verbonden bent. Breng een teststem uit en controleer of de aantallen veranderen.
5. Open de site in een tweede browser of privévenster en breng een andere stem uit. De eerste stem mag niet verdwijnen.

## Gegevens en privacy

- Een bezoeker krijgt een anonieme Supabase Auth-identiteit; er is geen naam, e-mailadres of school nodig.
- Per anonieme bezoeker kan per publicatie één actuele stem bestaan. Een wijziging vervangt de eerdere stem.
- De doelgroepkeuze (Havo, Vwo of Beide) wordt bij de stem opgeslagen.
- Ruwe stemmen zijn alleen voor de betreffende anonieme gebruiker leesbaar.
- De website kan alleen totalen per publicatie en doelgroep opvragen via de SQL-functie.
- Dit is geen waterdichte bescherming tegen misbruik: bezoekers kunnen meerdere browsers of apparaten gebruiken. Het is een laagdrempelige indicatie, geen representatieve enquête.
- Gebruik nooit een `service_role`-key of secret key in de browser. De website bevat uitsluitend de publieke publishable key.

## Interpretatie

Toon aantallen naast percentages en laat aantallen zien, bijvoorbeeld “7 van 9 havo-stemmen”. Gebruik bij weinig stemmen geen harde rangorde. Maak onderscheid tussen Havo, Vwo en Beide; een gecombineerde beoordeling mag niet automatisch aan beide niveaus worden toegeschreven.
