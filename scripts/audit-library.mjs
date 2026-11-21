import fs from 'node:fs';
import assert from 'node:assert/strict';

const publications = JSON.parse(fs.readFileSync('publicaties.json', 'utf8'));
const html = fs.readFileSync('index.html', 'utf8');
const science = publications.filter(item => item.page === 'science');
const education = publications.filter(item => item.page === 'education');
const roles = ['Kernleskaart', 'Vwo-verdieping', 'Docentachtergrond'];
const relevance = ['Direct', 'Aansluitend', 'Verdieping'];
const evidence = ['Breed onderbouwd', 'Ondersteunend bewijs', 'Achtergrondbron', 'Voorzichtig interpreteren', 'Voorlopig bewijs', 'Praktijkbron', 'Kennisoverzicht'];

assert.equal(publications.length, science.length + education.length, 'Paginatelling klopt niet');
assert.ok(science.length > 0 && education.length > 0, 'Beide bibliotheekdelen moeten gevuld zijn');
const ids = new Set(), dois = new Set(), urls = new Set();
for (const item of publications) {
  assert.ok(item.id && item.title && item.summary && item.article, 'Elk record moet ID, titel, samenvatting en artikelbron hebben');
  assert.ok(!ids.has(item.id), 'Dubbel ID: ' + item.id); ids.add(item.id);
  assert.ok(relevance.includes(item.relevanceLevel), 'Onbekende relevantie bij ' + item.id + ': ' + item.relevanceLevel);
  assert.ok(evidence.includes(item.evidenceLevel), 'Onbekende bewijssterkte bij ' + item.id + ': ' + item.evidenceLevel);
  const url = item.article.trim().replace(/\/$/, '').toLowerCase();
  assert.ok(!urls.has(url), 'Dubbele artikel-URL: ' + url); urls.add(url);
  if (item.doi) { const doi = item.doi.trim().toLowerCase(); assert.ok(!dois.has(doi), 'Dubbele DOI: ' + doi); dois.add(doi); }
  if (item.page === 'science') {
    assert.ok(roles.includes(item.lessonRole), 'Onbekende lesrol bij ' + item.id);
    assert.ok(item.relevanceNote && item.lessonRoleNote, 'Relevantie-/lesroltoelichting ontbreekt bij ' + item.id);
    assert.ok(item.themeCluster && item.concept && item.alignment, 'Thematische of curriculumkoppeling ontbreekt bij ' + item.id);
    assert.ok(!(item.lessonRole === 'Kernleskaart' && item.relevanceLevel === 'Verdieping'), 'Kernleskaart is tegelijk uitsluitend verdieping: ' + item.id);
  }
}
function options(id) {
  const start = html.indexOf('<select id="' + id + '">');
  assert.ok(start >= 0, 'Filter ontbreekt: ' + id);
  const end = html.indexOf('</select>', start);
  const body = html.slice(start, end);
  return [...body.matchAll(/<option(?:\s+value="([^"]*)")?>([^<]+)<\/option>/g)].map(m => (m[1] || m[2]).trim());
}
for (const [id, field] of [['concept','concept'],['cluster-filter','themeCluster'],['lesson-role-filter','lessonRole'],['study-type','studyType'],['evidence-filter','evidenceLevel']]) {
  const available = new Set(options(id));
  for (const value of new Set(science.map(item => item[field]))) assert.ok(available.has(value), 'Filter ' + id + ' mist waarde: ' + value);
}
assert.ok(options('lesson-role-filter').includes('all'), 'Alle kaarten moeten selecteerbaar blijven');
assert.ok(html.includes('function matchesSearch(') && html.includes('tokens.every('), 'Zoeken moet alle losse zoektermen kunnen combineren');
assert.ok(html.includes('function updateRoleFilterSummary()'), 'De standaardweergave moet de verborgen verdiepingslaag zichtbaar toelichten');
const count = list => list.reduce((out, item) => (out[item.lessonRole] = (out[item.lessonRole] || 0) + 1, out), {});
console.log('Bibliotheek-audit geslaagd:', JSON.stringify({
  total: publications.length, science: science.length, education: education.length,
  roles: count(science),
  relevance: relevance.reduce((out, value) => (out[value] = science.filter(item => item.relevanceLevel === value).length, out), {}),
  doiCount: dois.size, uniqueArticleUrls: urls.size
}, null, 2));
