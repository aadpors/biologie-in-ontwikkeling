import fs from 'node:fs';
import assert from 'node:assert/strict';

const html = fs.readFileSync('index.html', 'utf8');
const examPage = fs.readFileSync('examenoefenen.html', 'utf8');
const publications = JSON.parse(fs.readFileSync('publicaties.json', 'utf8'));
const examQuestions = JSON.parse(fs.readFileSync('exam-mcq.json', 'utf8'));
const examContexts = JSON.parse(fs.readFileSync('exam-contexts.json', 'utf8'));

function assertSnippetExists(path, where) {
  assert.equal(typeof path, 'string', `${where}: snippetverwijzing ontbreekt`);
  assert.ok(path.startsWith('exam-snippets/'), `${where}: snippet moet uit exam-snippets komen`);
  assert.ok(fs.existsSync(path), `${where}: afbeelding ontbreekt: ${path}`);
}

assert.ok(Array.isArray(examQuestions) && examQuestions.length > 0, 'exam-mcq.json moet examenvragen bevatten');
assert.ok(Array.isArray(examContexts) && examContexts.length > 0, 'exam-contexts.json moet contexten bevatten');
const examYears = new Set(examQuestions.map(question => question.year));
const sourceExamFiles = fs.readdirSync('examens');
const discoveredExamYears = new Set(
  sourceExamFiles
    .map(name => name.match(/^(?:ha|vw)-1018-a-(\\d{2})-\\d-o(?:-[a-z0-9]+)?\\.pdf$/i))
    .filter(Boolean)
    .map(match => `20${match[1]}`)
);
assert.ok(discoveredExamYears.size > 0, 'Geen examen-PDF’s gevonden');
for (const year of discoveredExamYears) {
  assert.ok(examYears.has(year), `Meerkeuzevragen voor beschikbaar examenjaar ${year} ontbreken`);
}
assert.ok(examPage.includes('(o.text?" "+o.text:"")'), 'Frontend verbergt de antwoordtekst bij vragen met een afbeelding');
assert.ok(!examPage.includes('(q.image?"":(o.text?" "+o.text:""))'), 'Frontend bevat nog de oude onderdrukking van antwoordteksten');
assert.ok(examPage.includes('antwoordteksten (A t/m F)'), 'De toelichting over zichtbare antwoordopties ontbreekt');
const open2024 = [...examPage.matchAll(/id:"[^"]+",level:"(?:Havo|Vwo)",year:"2024"/g)];
assert.ok(open2024.length > 0, 'Geselecteerde open vragen uit 2024 ontbreken');
assert.ok(examPage.includes('<option>2024</option>'), 'Examenoefenen-filter bevat 2024 niet');
assert.ok(examPage.includes('id:"ha24-1"') && examPage.includes('id:"ha24-8"'), 'Geselecteerde open vragen uit Havo 2024-I ontbreken');
for (const number of [1, 8]) {
  assert.ok(examContexts.some(context => context.level === 'Havo' && context.year === '2024' && context.period === '1' && context.n === number), `Contextafbeeldingen Havo 2024-I vraag ${number} ontbreken`);
}
const examIds = new Set();
for (const [index, question] of examQuestions.entries()) {
  const where = `exam-mcq.json vraag ${index + 1}`;
  assert.ok(question.id && !examIds.has(question.id), `${where}: ontbrekend of dubbel vraag-ID`);
  examIds.add(question.id);
  assertSnippetExists(question.image, where);
  for (const path of question.images || []) assertSnippetExists(path, where);
  assert.ok(Array.isArray(question.options) && question.options.length >= 3, `${where}: antwoordopties ontbreken`);
  const keys = question.options.map(option => option.key);
  assert.equal(new Set(keys).size, keys.length, `${where}: dubbele antwoordletter`);
  assert.deepEqual(keys, [...'ABCDEF'].slice(0, keys.length), `${where}: antwoordletters moeten aaneengesloten van A t/m F lopen`);
  for (const option of question.options) {
    assert.equal(typeof option.text, 'string', `${where}: antwoordtekst ${option.key} ontbreekt`);
    assert.ok(option.text.trim(), `${where}: antwoordtekst ${option.key} is leeg`);
  }
  assert.ok(question.options.length <= 6, `${where}: meer dan zes antwoordopties`);
  assert.ok(keys.includes(question.correct), `${where}: correct antwoord ${question.correct} ontbreekt bij de opties`);
}
for (const [index, context] of examContexts.entries()) {
  const where = `exam-contexts.json context ${index + 1}`;
  assertSnippetExists(context.image, where);
  for (const path of context.images || []) assertSnippetExists(path, where);
}

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

const inlineScripts = [html, examPage]
  .flatMap(page => [...page.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(match => match[1]))
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
console.log(`Validatie geslaagd: ${publications.length} publicaties (${counts.science || 0} vakinhoudelijk, ${counts.education || 0} pedagogisch-didactisch), ${examQuestions.length} examenvragen, ${examContexts.length} contexten en alle bijbehorende afbeeldingen aanwezig; ${inlineScripts.length} JavaScript-blok(ken) syntactisch geldig.`);
