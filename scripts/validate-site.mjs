import fs from 'node:fs';
import assert from 'node:assert/strict';

const html = fs.readFileSync('index.html', 'utf8');
const publications = JSON.parse(fs.readFileSync('publicaties.json', 'utf8'));

assert.ok(Array.isArray(publications), 'publicaties.json moet een array bevatten');
assert.ok(publications.length > 0, 'publicatiedatabase mag niet leeg zijn');

const ids = new Set();
for (const [index, item] of publications.entries()) {
  const where = `publicaties.json item ${index + 1}`;
  for (const field of ['id', 'page', 'date', 'title', 'summary', 'article', 'why', 'evidenceLevel', 'evidenceNote', 'relevanceLevel', 'relevanceNote', 'sourceQualityLevel', 'sourceQualityNote']) {
    assert.equal(typeof item[field], 'string', `${where}: veld "${field}" ontbreekt of is geen tekst`);
    assert.ok(item[field].trim(), `${where}: veld "${field}" is leeg`);
  }
  assert.ok(['science', 'education'].includes(item.page), `${where}: onbekende pagina "${item.page}"`);
  assert.ok(['Peer-reviewed tijdschrift', 'Institutionele kennisbron', 'Professionele praktijkbron'].includes(item.sourceQualityLevel), `${where}: onbekende bronkwaliteitsindicatie "${item.sourceQualityLevel}"`);
  // Strikte ISO-datumcontrole: Date.parse alleen accepteert soms onmogelijke kalenderdatums.
  assert.ok(/^\d{4}-\d{2}-\d{2}$/.test(item.date), `${where}: datum moet YYYY-MM-DD zijn`);
  const parsedDate = new Date(item.date + 'T00:00:00.000Z');
  assert.equal(parsedDate.toISOString().slice(0, 10), item.date, `${where}: ongeldige kalenderdatum ${item.date}`);

  for (const field of ['article']) {
    let url;
    try { url = new URL(item[field]); }
    catch { throw new Error(`${where}: ongeldige URL in veld "${field}"`); }
    assert.equal(url.protocol, 'https:', `${where}: veld "${field}" moet HTTPS gebruiken`);
  }
  if (item.pdf) {
    let pdfUrl;
    try { pdfUrl = new URL(item.pdf); }
    catch { throw new Error(`${where}: ongeldige PDF-URL`); }
    assert.equal(pdfUrl.protocol, 'https:', `${where}: PDF-link moet HTTPS gebruiken`);
  }
  if (item.doi) assert.ok(/^10\.\d{4,9}\/.+/.test(item.doi), `${where}: ongeldige DOI ${item.doi}`);

  assert.ok(!ids.has(item.id), `Dubbel publicatie-ID: ${item.id}`);
  ids.add(item.id);
  assert.ok(!Number.isNaN(Date.parse(item.date)), `${where}: ongeldige datum ${item.date}`);
  assert.ok(/^https:\/\//.test(item.article), `${where}: artikelbron moet HTTPS gebruiken`);
  if (item.doi) assert.ok(/^10\.\d{4,9}\//.test(item.doi), `${where}: ongeldige DOI ${item.doi}`);
  if (item.pdf) assert.ok(/^https:\/\//.test(item.pdf), `${where}: PDF-link moet HTTPS gebruiken`);
  if (item.page === 'science') {
    assert.ok(['Havo', 'Vwo', 'Havo/vwo'].includes(item.level), `${where}: onbekend niveau "${item.level}"`);
    assert.ok(['Huidig', 'Toekomstig', 'Beide'].includes(item.programme), `${where}: onbekend programma "${item.programme}"`);
    assert.ok(['Direct', 'Aansluitend', 'Verdieping'].includes(item.relevanceLevel), `${where}: onbekende relevantie-indicatie "${item.relevanceLevel}"`);
    for (const field of ['level', 'programme', 'concept', 'alignment', 'evidence', 'evidenceNote', 'relevanceNote']) {
      assert.equal(typeof item[field], 'string', `${where}: vakinhoudelijk veld "${field}" ontbreekt`);
    }
  } else {
    assert.ok(['Nederlands', 'Engels'].includes(item.language), `${where}: onbekende taal "${item.language}"`);
    assert.ok(['Wetenschappelijk onderzoek', 'Vakdidactiek', 'Praktijkonderzoek', 'Kennisplatform'].includes(item.source), `${where}: onbekend brontype "${item.source}"`);
    for (const field of ['language', 'source', 'theme']) {
      assert.equal(typeof item[field], 'string', `${where}: didactisch veld "${field}" ontbreekt`);
    }
  }
}

const inlineScripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
  .map(match => match[1])
  .filter(source => source.trim());
assert.ok(inlineScripts.length, 'Geen inline JavaScript gevonden');
for (const [index, source] of inlineScripts.entries()) {
  // Compileert JavaScript zonder browsercode uit te voeren.
  try { new Function(source); }
  catch (error) { throw new Error(`JavaScript-blok ${index + 1} bevat een syntaxfout: ${error.message}`); }
}

assert.ok(html.includes('publication_feedback'), 'Supabase-feedbacktabel ontbreekt in frontend');
assert.ok(html.includes('publication_feedback_totals'), 'Supabase-totalenfunctie ontbreekt in frontend');
assert.ok(html.includes('signInAnonymously'), 'Anonieme authenticatie ontbreekt in frontend');

const counts = publications.reduce((result, item) => {
  result[item.page] = (result[item.page] || 0) + 1;
  return result;
}, {});
console.log(`Validatie geslaagd: ${publications.length} publicaties (${counts.science || 0} vakinhoudelijk, ${counts.education || 0} pedagogisch-didactisch); ${inlineScripts.length} JavaScript-blok(ken) syntactisch geldig.`);
