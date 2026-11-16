# Gezamenlijke relevantiefeedback instellen

De website is een statische GitHub Pages-site. Om stemmen van verschillende bezoekers samen te tellen is een backend nodig. Deze map bevat het databaseschema voor Supabase.

## Eenmalige inrichting

1. Maak een gratis project aan op https://supabase.com/.
2. Ga in **Authentication → Providers / Sign In** en schakel **Anonymous Sign-Ins** in.
3. Open **SQL Editor** en voer de volledige inhoud van `feedback-schema.sql` uit.
4. Ga naar **Project Settings → API** en noteer de Project URL en de publishable/anon key.
5. Open in GitHub het bestand `index.html` en zoek bovenaan het script naar:
   ```js
   const SUPABASE_URL='VUL_HIER_PROJECT_URL_IN';
   const SUPABASE_ANON_KEY='VUL_HIER_PUBLISHABLE_KEY_IN';
   ```
   Vervang de eerste placeholder door de **Project URL** en de tweede door de **Publishable key** (of de legacy `anon` public key). Commit de wijziging. De frontend gebruikt de Supabase-JavaScriptbibliotheek via jsDelivr.
6. Gebruik nooit de `service_role`-key of een secret key in de browser of in GitHub Pages.

## Gegevens en privacy

- Een bezoeker krijgt een anonieme Supabase Auth-identiteit; er is geen naam, e-mailadres of school nodig.
- Per anonieme bezoeker kan per publicatie één actuele stem bestaan. Een wijziging vervangt de eerdere stem.
- De doelgroepkeuze (Havo, Vwo of Beide) wordt bij de stem opgeslagen.
- Ruwe stemmen zijn alleen voor de betreffende anonieme gebruiker leesbaar.
- De website kan alleen totalen per publicatie en doelgroep opvragen via de SQL-functie.
- Dit is geen waterdichte bescherming tegen misbruik: bezoekers kunnen meerdere browsers of apparaten gebruiken. Voor een onderwijswebsite is het een privacyvriendelijke, laagdrempelige indicatie, geen representatieve enquête.

## Controle na configuratie

- Open de website in een privévenster en controleer of de melding aangeeft dat je anoniem verbonden bent.
- Breng een teststem uit. De gekozen knop moet actief worden en de aantallen moeten worden bijgewerkt.
- Open de website in een tweede browser of privévenster en breng een andere stem uit. De eerste stem mag niet verdwijnen.
- Controleer in Supabase → Table Editor → `publication_feedback` dat er afzonderlijke rijen met verschillende `user_id`-waarden zijn.
- Verwijder teststemmen na de controle eventueel via de Table Editor.

## Interpretatie

Toon aantallen naast percentages en laat aantallen zien, bijvoorbeeld “7 van 9 havo-stemmen”. Gebruik bij weinig stemmen geen harde rangorde. Maak onderscheid tussen Havo, Vwo en Beide; een gecombineerde beoordeling mag niet automatisch aan beide niveaus worden toegeschreven.
