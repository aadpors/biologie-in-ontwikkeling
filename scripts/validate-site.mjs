import fs from 'node:fs';
import assert from 'node:assert/strict';

const html = fs.readFileSync('index.html', 'utf8');
const examPage = fs.readFileSync('examenoefenen.html', 'utf8');
const publications = JSON.parse(fs.readFileSync('publicaties.json', 'utf8'));
const examQuestions = JSON.parse(fs.readFileSync('exam-mcq.json', 'utf8'));
const openExamQuestions = JSON.parse(fs.readFileSync('exam-open.json', 'utf8'));
const examContexts = JSON.parse(fs.readFileSync('exam-contexts.json', 'utf8'));

function assertSnippetExists(path, where) {
  assert.equal(typeof path, 'string', `${where}: snippetverwijzing ontbreekt`);
  assert.ok(path.startsWith('exam-snippets/'), `${where}: snippet moet uit exam-snippets komen`);
  assert.ok(fs.existsSync(path), `${where}: afbeelding ontbreekt: ${path}`);
}

assert.ok(Array.isArray(examQuestions) && examQuestions.length > 0, 'exam-mcq.json moet examenvragen bevatten');
assert.ok(Array.isArray(openExamQuestions), 'exam-open.json moet open examenvragen bevatten');
assert.ok(Array.isArray(examContexts) && examContexts.length > 0, 'exam-contexts.json moet contexten bevatten');
const examYears = new Set(examQuestions.map(question => question.year));
const sourceExamFiles = fs.readdirSync('examens');
const discoveredExamYears = new Set(
  sourceExamFiles
    .map(name => name.match(/^(?:ha|vw)-1018-a-(\d{2})-\d-o(?:-[a-z0-9]+)?\.pdf$/i))
    .filter(Boolean)
    .map(match => `20${match[1]}`)
    .filter(year => ["2024", "2025", "2026"].includes(year))
);
assert.ok(discoveredExamYears.size > 0, 'Geen examen-PDF’s gevonden');
for (const year of discoveredExamYears) {
  assert.ok(examYears.has(year), `Meerkeuzevragen voor beschikbaar examenjaar ${year} ontbreken`);
}
assert.ok(examPage.includes('/^\\d+$/'), 'Binaire tabellen tonen bij genummerde uitspraken niet uitsluitend het uitspraaknummer');
const havo2025Question26 = openExamQuestions.find(question => question.id === 'ha25t1-open-26');
assert.ok(havo2025Question26, 'Havo 2025-I vraag 26 ontbreekt');
assert.ok(!havo2025Question26.source.includes('Hieronder staan drie uitspraken'), 'De inleiding van vraag 26 staat nog ten onrechte in de context');
assert.ok(havo2025Question26.q.startsWith('Hieronder staan drie uitspraken.'), 'De inleiding van vraag 26 moet bij de vraagtekst staan');
assert.ok(
  [
    ['exam-snippets/context-ha25t1-q26-context.svg', 'exam-snippets/question-ha25t1-26-with-intro.svg'],
    ['exam-snippets/context-ha25t1-q26-complete.jpg', 'exam-snippets/question-ha25t1-26-only.jpg'],
  ].some(expected => JSON.stringify(havo2025Question26.images) === JSON.stringify(expected)),
  'Havo 2025-I vraag 26 moet een contextuitsnede zonder vraaginleiding en een vraaguitsnede met vraaginleiding tonen'
);
const havo2025Question32 = openExamQuestions.find(question => question.id === 'ha25t1-open-32');
assert.ok(havo2025Question32, 'Havo 2025-I vraag 32 ontbreekt');
assert.deepEqual(
  havo2025Question32.images?.slice(0, 2),
  ['exam-snippets/context-ha25t1-q31-complete.jpg', 'exam-snippets/context-ha25t1-q32-complete.jpg'],
  'Havo 2025-I vraag 32 moet zowel de contextuitsnede van vraag 31 als de vervolgcontext van vraag 32 tonen'
);
assert.deepEqual(
  havo2025Question32.images,
  ['exam-snippets/context-ha25t1-q31-complete.jpg', 'exam-snippets/context-ha25t1-q32-complete.jpg', 'exam-snippets/question-ha25t1-32-only.jpg'],
  'Havo 2025-I vraag 32 moet de context van vraag 31, de vervolgcontext van vraag 32 en de afzonderlijke vraaguitsnede tonen'
);
assert.ok(!examPage.includes('(q.image?"":(o.text?" "+o.text:""))'), 'Frontend bevat nog de oude onderdrukking van antwoordteksten');
assert.ok(examPage.includes('Meerkeuzevragen én juist/onjuist- en wel/niet-vragen worden automatisch nagekeken volgens het officiële correctievoorschrift.'), 'De toelichting over de automatische nakijkinteractie ontbreekt');
const open2024 = [...examPage.matchAll(/id:"[^"]+",level:"(?:Havo|Vwo)",year:"2024"/g)];
assert.ok(open2024.length >= 3, 'Te weinig geselecteerde open vragen uit 2024');
assert.ok(examQuestions.some(question => question.year === '2024' && question.options.length === 6), 'Meerkeuzevragen met zes antwoordopties (A-F) uit 2024 ontbreken');

const selected2024OpenQuestions = [
  { id: 'ha24t1-10', level: 'Havo', period: '1', n: 10, cv: 'exam-snippets/cv-ha24t1-10.jpg' },
  { id: 'vw24-1', level: 'Vwo', period: '1', n: 1, cv: 'exam-snippets/cv-vw24-1.jpg' },
  { id: 'vw24t2-1', level: 'Vwo', period: '2', n: 1, cv: 'exam-snippets/cv-vw24t2-1.jpg' },
  { id: 'ha24t2-3', level: 'Havo', period: '2', n: 3, cv: 'exam-snippets/cv-ha24t2-3.jpg' },
  { id: 'ha24t2-6', level: 'Havo', period: '2', n: 6, cv: 'exam-snippets/cv-ha24t2-6.jpg' },
  { id: 'ha24t2-7', level: 'Havo', period: '2', n: 7, cv: 'exam-snippets/cv-ha24t2-7.jpg' },
  { id: 'vw24t2-2', level: 'Vwo', period: '2', n: 2, cv: 'exam-snippets/cv-vw24t2-2.jpg' },
];
for (const question of selected2024OpenQuestions) {
  assert.ok(examPage.includes(`id:"${question.id}"`), `Geselecteerde open vraag ${question.id} ontbreekt in examenoefenen.html`);
  const context = examContexts.find(item =>
    item.level === question.level && item.year === '2024' &&
    item.period === question.period && item.n === question.n
  );
  assert.ok(context, `Bronafbeeldingen voor open vraag ${question.id} ontbreken`);
  assertSnippetExists(context.image, `open vraag ${question.id}`);
  for (const path of context.images || []) assertSnippetExists(path, `open vraag ${question.id}`);
  assertSnippetExists(question.cv, `correctievoorschrift open vraag ${question.id}`);
}

assert.ok(examPage.includes('<option>2024</option>'), 'Examenoefenen-filter bevat 2024 niet');
assert.ok(examPage.includes('id:"ha24-1"') && examPage.includes('id:"ha24-8"'), 'Geselecteerde open vragen uit Havo 2024-I ontbreken');
for (const number of [1, 8]) {
  assert.ok(examContexts.some(context => context.level === 'Havo' && context.year === '2024' && context.period === '1' && context.n === number), `Contextafbeeldingen Havo 2024-I vraag ${number} ontbreken`);
}
const sortKey = question => [Number(question.year), Number(question.period), Number(question.n), question.level].join("|");
const sortedExamQuestions = [...examQuestions].sort((a, b) =>
  Number(a.year) - Number(b.year) ||
  Number(a.period) - Number(b.period) ||
  Number(a.n) - Number(b.n) ||
  a.level.localeCompare(b.level, 'nl')
);
assert.deepEqual(examQuestions.map(sortKey), sortedExamQuestions.map(sortKey),
  'Meerkeuzevragen moeten oplopend op examenjaar, tijdvak en vraagnummer staan');

const openIds = new Set();
for (const [index, question] of openExamQuestions.entries()) {
  const where = `exam-open.json vraag ${index + 1}`;
  assert.ok(question.id && !openIds.has(question.id), `${where}: ontbrekend of dubbel vraag-ID`);
  openIds.add(question.id);
  assert.ok(['Havo', 'Vwo'].includes(question.level), `${where}: onbekend niveau`);
  assert.ok(['2024', '2025', '2026'].includes(question.year), `${where}: examenjaar buiten de opdracht`);
  assert.ok(['1', '2'].includes(question.period), `${where}: ongeldig tijdvak`);
  assert.ok(Number.isInteger(question.n) && question.n > 0, `${where}: ongeldig vraagnummer`);
  assert.ok(Number.isInteger(question.points) && question.points > 0, `${where}: ontbrekende score`);
  assert.ok(typeof question.q === 'string' && question.q.trim(), `${where}: vraagtekst ontbreekt`);
  assertSnippetExists(question.image, where);
  for (const path of question.images || []) assertSnippetExists(path, where);
  const questionImages = question.images || [];
  const hasSeparateContextAndQuestionImages = questionImages.length >= 2;
  const hasSingleCompleteSourcePage =
    questionImages.length === 1 &&
    questionImages[0] === question.image &&
    questionImages[0].endsWith(`question-complete-${question.id}.jpg`);
  assert.ok(
    hasSeparateContextAndQuestionImages || hasSingleCompleteSourcePage,
    `${where}: aparte context-/vraagafbeeldingen of één volledige bronpagina ontbreken`
  );
  assert.ok(question.pdf && question.cv, `${where}: originele opgave of correctievoorschrift ontbreekt`);
}
const allQuestionKeys = [...examQuestions, ...openExamQuestions].map(q => [q.level, q.year, q.period, q.n].join('|'));
assert.equal(new Set(allQuestionKeys).size, allQuestionKeys.length, 'Een examenvraag staat dubbel als open en/of meerkeuzevraag');
assert.ok(openExamQuestions.length > 0, 'Geen open vragen uit de volledige examenextractie gevonden');

assert.ok(examPage.includes('Volledige uitwerkbijlage'), 'Frontend biedt geen link naar de volledige uitwerkbijlage');
for (const [index, question] of [...examQuestions, ...openExamQuestions].entries()) {
  for (const attachment of question.attachmentPdfs || []) {
    assert.equal(typeof attachment, 'string', `examenvraag ${index + 1}: ongeldige uitwerkbijlageverwijzing`);
    assert.ok(attachment.startsWith('examens/'), `examenvraag ${index + 1}: uitwerkbijlage moet uit examens komen`);
    assert.ok(fs.existsSync(attachment), `examenvraag ${index + 1}: volledige uitwerkbijlage ontbreekt: ${attachment}`);
  }
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
  const images = context.images || [];
  const hasSeparateContextAndQuestion = images.length >= 2 && images[0] !== images.at(-1);
  const hasSingleCompleteSourcePage = images.length === 1 &&
    /question-complete-.*\.jpg$/i.test(images[0]);
  assert.ok(hasSeparateContextAndQuestion || hasSingleCompleteSourcePage,
    `${where}: aparte context-/vraagafbeeldingen of één volledige bronpagina ontbreken`);
  for (const path of images) assertSnippetExists(path, where);
}
// Every one of the 519 indexed questions must have a matching image-based
// context record. This prevents OCR text from silently replacing source art.
for (const [index, question] of [...examQuestions, ...openExamQuestions].entries()) {
  const context = examContexts.find(item =>
    item.level === question.level && item.year === question.year &&
    item.period === question.period && item.n === question.n
  );
  assert.ok(context, `examenvraag ${index + 1}: contextrecord ontbreekt`);
  const images = context.images || [];
  const hasSeparateContextAndQuestion = images.length >= 2 && images[0] !== images.at(-1);
  const hasSingleCompleteSourcePage = images.length === 1 &&
    /question-complete-.*\.jpg$/i.test(images[0]);
  assert.ok(hasSeparateContextAndQuestion || hasSingleCompleteSourcePage,
    `examenvraag ${index + 1}: context moet als uitsnede of volledige bronpagina beschikbaar zijn`);
}

// Every question in both inventories must have a local official CV snippet.
const cvManifest = JSON.parse(fs.readFileSync('scripts/cv-snippets.json', 'utf8'));
assert.ok(Array.isArray(cvManifest), 'CV-snippetsmanifest moet een array zijn');
const cvById = new Map(cvManifest.map(item => [item.id, item]));
assert.equal(cvById.size, cvManifest.length, 'Dubbele vraag-ID in CV-snippetsmanifest');
for (const question of openExamQuestions) {
  const item = cvById.get(question.id);
  assert.ok(item, `Officiële CV-snippet ontbreekt voor ${question.id}`);
  assert.ok(item.pdf && fs.existsSync(item.pdf), `Bron-PDF correctievoorschrift ontbreekt voor ${question.id}`);
  assert.ok(typeof item.output === 'string' && item.output.endsWith('.jpg'), `Ongeldige lokale CV-snippetnaam voor ${question.id}`);
  assertSnippetExists(`exam-snippets/${item.output}`, `Lokale CV-afbeelding voor ${question.id}`);
  if (item.amendment_pdf) {
    assert.ok(fs.existsSync(item.amendment_pdf), `Aanvulling correctievoorschrift ontbreekt voor ${question.id}`);
    assert.ok(typeof item.amendment_output === 'string' && item.amendment_output.endsWith('.jpg'), `Ongeldige lokale CV-aanvulling voor ${question.id}`);
    assertSnippetExists(`exam-snippets/${item.amendment_output}`, `Lokale CV-aanvulling voor ${question.id}`);
  }
}
assert.ok(!examPage.includes('window.open(cv,\"_blank\"'), 'CV-knop mag niet terugvallen op een externe PDF in plaats van de lokale snippet');


assert.ok(Array.isArray(publications), 'publicaties.json moet een array bevatten');
assert.ok(publications.length > 0, 'publicatiedatabase mag niet leeg zijn');

// Regression checks for the homepage search/filter redesign.
for (const id of ['publication-controls', 'science-filter-groups', 'science-content-group', 'science-assessment-group', 'science-filters', 'science-assessment-filters', 'education-filter-group', 'education-filters', 'search', 'rating-filter', 'clear', 'count']) {
  assert.ok(html.includes(`id="${id}"`), `Homepage mist filteronderdeel #${id}`);
}
assert.ok(html.includes('class="filter-groups"'), 'De wetenschappelijke filters moeten in één gegroepeerd paneel staan');
assert.ok(html.includes('.filter-groups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))'), 'Desktopindeling van de filtergroepen ontbreekt');
assert.ok(html.includes('@media(max-width:430px)'), 'Mobiele filterindeling ontbreekt');
assert.ok(html.includes("(x.concept||'')") && html.includes("(x.studyType||'')") && html.includes("(x.subdomain||'')") && html.includes("(x.alignment||'')"),
  'Zoeken moet ook hoofdthema, syllabuscode en curriculumkoppeling doorzoeken');
const conceptFilter = html.match(/<select id="concept">([\s\S]*?)<\/select>/)?.[1] || '';
const conceptOptions = [...conceptFilter.matchAll(/<option(?:\s+value="[^"]*")?>([^<]+)<\/option>/g)].map(match => match[1].trim());
const scienceConcepts = [...new Set(publications.filter(item => item.page === 'science').map(item => item.concept))];
for (const concept of scienceConcepts) assert.ok(conceptOptions.includes(concept), `Hoofdthema ontbreekt in de filterlijst: ${concept}`);
const studyTypeFilter = html.match(/<select id="study-type">([\s\S]*?)<\/select>/)?.[1] || '';
const studyTypeOptions = [...studyTypeFilter.matchAll(/<option(?:\s+value="[^"]*")?>([^<]+)<\/option>/g)].map(match => match[1].trim());
const scienceStudyTypes = [...new Set(publications.filter(item => item.page === 'science').map(item => item.studyType))];
for (const studyType of scienceStudyTypes) assert.ok(studyTypeOptions.includes(studyType), `Onderzoekstype ontbreekt in de filterlijst: ${studyType}`);

assert.ok(html.includes("$('science-filter-groups').hidden=p!=='science'") && html.includes("$('education-filter-group').hidden=p!=='education'"),
  'Paginawisseling moet volledige filtergroepen tonen/verbergen, niet losse filteronderdelen');
const siteVersion = JSON.parse(fs.readFileSync('site-version.json', 'utf8')).version;
assert.ok(html.includes(`const currentSiteVersion='${siteVersion}'`), 'Siteversie in index.html loopt niet gelijk met site-version.json');
assert.ok(html.includes(`./publicaties.json?v=${siteVersion.replace('.000Z', 'Z')}`), 'Databasecache moet met dezelfde siteversie worden vernieuwd');


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
    assert.ok(['Primair onderzoek', 'Review / synthese', 'Perspectiefartikel'].includes(item.studyType), `${where}: onbekend onderzoekstype "${item.studyType}"`);
    assert.ok(['Huidig', 'Toekomstig', 'Beide'].includes(item.programme), `${where}: onbekend programma "${item.programme}"`);
    assert.ok(['Direct', 'Aansluitend', 'Verdieping'].includes(item.relevanceLevel), `${where}: onbekende relevantie-indicatie "${item.relevanceLevel}"`);
    for (const field of ['level', 'programme', 'concept', 'studyType', 'alignment', 'evidence', 'evidenceNote', 'relevanceNote']) {
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
console.log(`Validatie geslaagd: ${publications.length} publicaties (${counts.science || 0} vakinhoudelijk, ${counts.education || 0} pedagogisch-didactisch), ${examQuestions.length + openExamQuestions.length} examenvragen (${examQuestions.length} meerkeuze, ${openExamQuestions.length} open), ${examContexts.length} contexten en alle bijbehorende afbeeldingen aanwezig; ${inlineScripts.length} JavaScript-blok(ken) syntactisch geldig.`);
