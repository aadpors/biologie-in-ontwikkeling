/*
 * Front-end voor de geïntegreerde examenwerkruimte.
 * Alle blijvende gegevens worden via de API opgeslagen; deze JavaScript-code
 * bewaart alleen de tijdelijke selectie van het huidige scherm. Daardoor
 * verdwijnen metadata of voortgang niet wanneer de browser wordt vernieuwd.
 */
const state = { examId: null, exam: null, workflow: [] };
const $ = (selector) => document.querySelector(selector);

async function api(url, options = {}) {
  const response = await fetch(url, options);
  // Lees de body als tekst, zodat ook een niet-JSON serverfout bruikbare
  // informatie oplevert. De vorige versie verving zulke fouten door alleen
  // "Er is iets misgegaan", waardoor de echte oorzaak onzichtbaar bleef.
  const rawBody = await response.text();
  let body = {};
  try { body = rawBody ? JSON.parse(rawBody) : {}; } catch (_) {
    body = {detail: rawBody || response.statusText};
  }
  if (!response.ok) {
    const detail = body.detail;
    let message = typeof detail === 'string'
      ? detail
      : (detail?.message || JSON.stringify(detail) || `HTTP ${response.status} ${response.statusText}`);
    // Bij een blokkade door ontbrekende voorgangers tonen we voortaan de
    // concrete stapnamen. Alleen de algemene servermelding is onvoldoende
    // om te begrijpen welke workflowstatus nog ontbreekt.
    if (Array.isArray(detail?.missing) && detail.missing.length) {
      const titles = detail.missing.map(key =>
        state.workflow.find(step => step.key === key)?.title || key
      );
      message += ' Nog niet afgerond: ' + titles.join(', ') + '.';
    }
    const error = new Error(message);
    error.detail = detail;
    error.status = response.status;
    throw error;
  }
  return body;
}

/* Koppel een bestaande conceptopslagfunctie aan alle bewerkbare velden in
   een workflowstap. De server ontvangt zo na elke veldwijziging de complete
   momentopname van die stap; er is geen aparte opslagknop meer nodig om
   voortgang te behouden. Oude listeners worden verwijderd wanneer een
   andere stap in hetzelfde paneel wordt geopend. */
function bindStageAutoSave(panel, save, statusSelector) {
  if (panel._stageAutoSaveCleanup) panel._stageAutoSaveCleanup();
  let timer = null;
  let saveChain = Promise.resolve();

  const saveNow = () => {
    clearTimeout(timer);
    saveChain = saveChain.catch(() => {}).then(() => save({draft:true})).then(result => {
      const status = panel.querySelector(statusSelector);
      if (status) status.textContent = 'Wijziging automatisch opgeslagen.';
      return result;
    }).catch(error => {
      const status = panel.querySelector(statusSelector);
      if (status) status.textContent = 'Automatisch opslaan mislukt: ' + error.message;
      throw error;
    });
    return saveChain;
  };

  const schedule = event => {
    if (!event.target.matches('input, textarea, select')) return;
    if (event.target.type === 'file' || event.target.type === 'button') return;
    clearTimeout(timer);
    timer = setTimeout(() => saveNow().catch(() => {}), 300);
  };

  // change wordt afgevuurd bij checkbox/select-wijzigingen en wanneer een
  // tekstveld focus verliest, dus ook bij wegklikken naar een ander tabblad.
  panel.addEventListener('change', schedule);

  // Forceer een laatste opslag wanneer de gebruiker naar een ander tabblad
  // gaat of de pagina sluit. Dit voorkomt dat de debounce-timer wordt afgebroken
  // voordat de laatste wijziging de server bereikt.
  const flushOnHide = () => saveNow().catch(() => {});
  const onVisibilityChange = () => {
    if (document.visibilityState === 'hidden') flushOnHide();
  };
  document.addEventListener('visibilitychange', onVisibilityChange);
  window.addEventListener('pagehide', flushOnHide);

  panel._stageAutoSaveFlush = saveNow;
  panel._stageAutoSaveCleanup = () => {
    clearTimeout(timer);
    panel._stageAutoSaveFlush = null;
    panel.removeEventListener('change', schedule);
    document.removeEventListener('visibilitychange', onVisibilityChange);
    window.removeEventListener('pagehide', flushOnHide);
    panel._stageAutoSaveCleanup = null;
  };
}

/* De afrondknop is de expliciete bevestiging voor een complete stap.
   Losse vinkjes per vraag, pagina of fragment voegen geen extra controle toe.
   Houd de bestaande reviewed-velden intern op true voor compatibiliteit met
   opgeslagen bewijs, maar verberg de repetitieve bediening voor de gebruiker.
   Vraagstart-selectievakjes blijven zichtbaar: die bepalen de inhoudelijke
   structuur en zijn dus geen administratieve controlevinkjes. */
function prepareStageApproval(panel) {
  const reviewLabels = [...panel.querySelectorAll('.review-warning')];
  if (!reviewLabels.length) return;
  reviewLabels.forEach(label => {
    const checkbox = label.querySelector('input[type="checkbox"]');
    if (checkbox) {
      checkbox.checked = true;
      checkbox.disabled = true;
    }
    label.hidden = true;
  });
  // Sommige bestaande schermen schakelden de afrondknop uitsluitend uit
  // zolang deze vinkjes niet waren gezet. Die blokkade vervalt nu; eventuele
  // inhoudelijke blokkades worden direct daarna door de eigen refresh-functie
  // van de stap opnieuw toegepast.
  panel.querySelectorAll('button[id^="complete"]').forEach(button => {
    button.disabled = false;
  });
  if (!panel.querySelector('.stage-approval-note')) {
    const note = document.createElement('p');
    note.className = 'stage-approval-note muted';
    note.textContent = 'Afzonderlijke controlevinkjes zijn niet nodig. De knop onderaan bevestigt dat je de getoonde onderdelen hebt gecontroleerd.';
    const actions = [...panel.querySelectorAll('.review-actions')];
    const finalActions = actions[actions.length - 1];
    if (finalActions) finalActions.before(note);
    else panel.append(note);
  }
}

function showLibrary() {
  $('#libraryView').hidden = false;
  $('#workspaceView').hidden = true;
  $('#backLibrary').hidden = true;
  state.examId = null;
  state.exam = null;
  loadLibrary();
}

async function loadLibrary() {
  const exams = await api('/api/exams');
  $('#examCount').textContent = `${exams.length} ${exams.length === 1 ? 'examen' : 'examens'}`;
  $('#examList').innerHTML = exams.length ? exams.map(exam => `
    <article class="exam-row"><div class="doc-icon">PDF</div><div><strong>${escapeHtml(exam.title)}</strong><p>${exam.published ? 'Gepubliceerd in examenbibliotheek' : (exam.confirmed ? 'Metadata bevestigd · nog niet gepubliceerd' : 'Metadata nog te bevestigen')} · geïmporteerd ${new Date(exam.created_at + 'Z').toLocaleDateString('nl-NL')}</p></div><button class="quiet" data-open="${exam.id}">Open werkruimte →</button></article>
  `).join('') : '<p class="muted">Er zijn nog geen examens geïmporteerd.</p>';
  document.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', () => openWorkspace(button.dataset.open)));
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

$('#importForm').addEventListener('submit', async event => {
  event.preventDefault();
  $('#importError').textContent = '';
  const files = $('#pdfFiles').files;
  if (!files.length) return;

  // Bewaar de geselecteerde bestanden in één FormData-object. Bij een
  // dubbele import wordt hetzelfde uploadpakket nogmaals verstuurd, nu met
  // de expliciete opdracht om de oude verwerking te vervangen.
  const form = new FormData();
  [...files].forEach(file => form.append('files', file));
  const button = event.submitter;
  button.disabled = true;
  button.textContent = 'PDF-bestanden controleren…';
  try {
    let result;
    try {
      result = await api('/api/exams/import', { method: 'POST', body: form });
    } catch (error) {
      let detail = null;
      try { detail = JSON.parse(error.message); } catch (_) {}
      if (detail?.code !== 'duplicate_exam') throw error;

      const confirmed = window.confirm(
        `Dit examen is al geïmporteerd: "${detail.title}".\n\n` +
        'Wil je de bestaande import en alle bijbehorende verwerking verwijderen ' +
        'en vervangen door deze nieuwe import? Deze actie kan niet ongedaan worden gemaakt.'
      );
      if (!confirmed) {
        $('#importError').textContent = 'Import geannuleerd. De bestaande verwerking is behouden.';
        return;
      }
      form.append('replace_exam_id', detail.exam_id);
      button.textContent = 'Bestaande import vervangen…';
      result = await api('/api/exams/import', { method: 'POST', body: form });
    }
    $('#pdfFiles').value = '';
    await openWorkspace(result.exam_id);
  } catch (error) {
    $('#importError').textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = 'Importeren en verwerken';
  }
});

$('#backLibrary').addEventListener('click', showLibrary);

async function openWorkspace(examId) {
  state.examId = examId;
  state.exam = await api(`/api/exams/${examId}`);
  state.workflow = await api('/api/workflow');

  // Documenttypen die ontbreken zijn geen inhoudelijke reviewtaak. Rond
  // optionele fasen daarom automatisch als 'niet van toepassing' af; anders
  // moet de gebruiker later een overbodige bevestigingsknop indrukken en kan
  // een vervolgstap onterecht melden dat een voorganger nog openstaat.
  if (state.exam.confirmed) {
    let next = state.workflow.find(step => state.exam.steps[step.key]?.status !== 'complete');
    if (['uitwerk_starts', 'uitwerk_fragments'].includes(next?.key) && !examHasDocumentType('uitwerkbijlage')) {
      await api(`/api/exams/${examId}/skip-optional-workbook`, {method:'POST'});
      state.exam = await api(`/api/exams/${examId}`);
      next = state.workflow.find(step => state.exam.steps[step.key]?.status !== 'complete');
    }
    if (next?.key === 'cv_aanvulling' && !examHasDocumentType('aanvulling_correctievoorschrift')) {
      await api(`/api/exams/${examId}/steps/cv_aanvulling/complete`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({reviewed:true, not_required:true})
      });
      state.exam = await api(`/api/exams/${examId}`);
    }
  }

  $('#libraryView').hidden = true;
  $('#workspaceView').hidden = false;
  $('#backLibrary').hidden = false;
  renderWorkspace();
}

function renderWorkspace() {
  const stagePanel = $('#stagePanel');
  if (stagePanel?._stageAutoSaveCleanup) stagePanel._stageAutoSaveCleanup();
  const exam = state.exam;
  $('#examTitle').textContent = exam.title;
  const metadata = exam.metadata;
  $('#examMeta').textContent = exam.confirmed
    ? `${metadata.subject} · ${metadata.level} · ${metadata.year} · tijdvak ${metadata.period}`
    : `${exam.documents.length} documenten · metadata nog niet bevestigd`;
  const completed = Object.keys(exam.steps).filter(key => exam.steps[key].status === 'complete');
  const next = state.workflow.find(step => !completed.includes(step.key));
  $('#overallStatus').textContent = completed.includes('eindcontrole') ? 'Controle afgerond' : 'In verwerking';
  $('#stepList').innerHTML = state.workflow.map((step, index) => {
    const done = completed.includes(step.key);
    const current = next?.key === step.key;
    const canReopen = done && step.key !== 'publicatie';
    const tag = canReopen ? 'button' : 'div';
    const action = canReopen
      ? `type="button" data-reopen-step="${step.key}" title="Deze stap opnieuw openen"`
      : '';
    return `<${tag} class="step-item ${done ? 'complete step-item-button' : ''} ${current ? 'current' : ''}" ${action}><span class="step-number">${done ? '✓' : index + 1}</span><div><strong>${escapeHtml(step.title)}</strong><small>${canReopen ? 'Afgerond · klik om te herstellen' : done ? 'Gepubliceerd' : current ? 'Volgende stap' : 'Nog niet uitgevoerd'}</small></div></${tag}>`;
  }).join('');

  // Afgeronde stappen kunnen vanuit iedere latere fase opnieuw worden geopend.
  // De server bewaart de bestaande invoer als concept en verwijdert alleen
  // afhankelijke goedkeuringen, zodat de docent niet opnieuw hoeft te beginnen.
  $('#stepList').querySelectorAll('[data-reopen-step]').forEach(button => {
    button.addEventListener('click', async () => {
      const key = button.dataset.reopenStep;
      const step = state.workflow.find(item => item.key === key);
      const confirmed = window.confirm(
        `Wil je "${step?.title || key}" opnieuw openen?\n\n` +
        'De opgeslagen correcties blijven behouden. Goedgekeurde vervolgstappen ' +
        'worden opnieuw ter controle aangeboden.'
      );
      if (!confirmed) return;
      try {
        await api(`/api/exams/${state.examId}/steps/${key}/reopen`, {method:'POST'});
        await openWorkspace(state.examId);
      } catch (error) {
        window.alert('De stap kon niet worden heropend: ' + error.message);
      }
    });
  });
  if (!exam.confirmed) renderMetadataStage();
  else if (next?.key === 'opgaven_starts') renderQuestionStartsStage('opgaven_starts', 'opgaven', 'FASE 2 · OPGAVENDOCUMENT', 'Vraagstarts opgaven');
  else if (next?.key === 'opgaven_fragments') renderQuestionFragmentsStage('opgaven_fragments', 'opgaven', 'opgaven_starts', 'FASE 2 · OPGAVENDOCUMENT', 'Vraagfragmenten opgaven');
  else if (next?.key === 'opgaven_analyse') renderQuestionAnalysisStage();
  else if (next?.key === 'uitwerk_starts' && !examHasDocumentType('uitwerkbijlage')) renderSkipWorkbookStage();
  else if (next?.key === 'uitwerk_starts') renderQuestionStartsStage('uitwerk_starts', 'uitwerkbijlage', 'FASE 3 · UITWERKBIJLAGE', 'Vraagstarts uitwerkbijlage');
  else if (next?.key === 'uitwerk_fragments') renderStitchedOpgavenStage('uitwerk_fragments', 'uitwerk_starts', 'FASE 3 · UITWERKBIJLAGE', 'Fragmenten uitwerkbijlage', 'uitwerkbijlage');
  else if (next?.key === 'cv_starts') renderQuestionStartsStage('cv_starts', 'correctievoorschrift', 'FASE 4 · CORRECTIEVOORSCHRIFT', 'Vraagstarts correctievoorschrift');
  else if (next?.key === 'cv_fragments') renderStitchedOpgavenStage('cv_fragments', 'cv_starts', 'FASE 4 · CORRECTIEVOORSCHRIFT', 'Fragmenten correctievoorschrift', 'correctievoorschrift');
  else if (next?.key === 'cv_aanvulling') renderCvSupplementStage();
  else if (next?.key === 'antwoorden') renderAnswersStage();
  else if (next?.key === 'relaties') renderRelationsStage();
  else if (next?.key === 'snippets') renderSnippetsStage();
  else if (next?.key === 'eindcontrole') renderFinalReviewStage();
  else if (next?.key === 'publicatie') renderPublicationStage();
  else renderStageOverview(next, completed);
}

function renderMetadataStage() {
  // Bewaar de verwijzing naar het paneel lokaal. De opruimfunctie voor
  // autosave-listeners gebruikt dit element wanneer de gebruiker naar een
  // volgende stap gaat; zonder deze declaratie stopt het renderen hier met
  // een ReferenceError en wordt de submit-handler nooit gekoppeld.
  const panel = $('#stagePanel');
  const exam = state.exam;
  const first = exam.documents[0].metadata;
  // Onbevestigde metadata wordt als concept uit SQLite teruggelezen, zodat
  // een herstart niet betekent dat de gebruiker de invoer opnieuw moet doen.
  const draft = exam.steps.metadata_draft?.evidence || {};
  const common = (key) => draft[key] ?? exam.documents.map(doc => doc.metadata[key]).find(value => value !== '' && value != null) ?? '';
  const types = {opgaven:'Opgaven',uitwerkbijlage:'Uitwerkbijlage',correctievoorschrift:'Correctievoorschrift',aanvulling_correctievoorschrift:'Aanvulling correctievoorschrift'};
  $('#stagePanel').innerHTML = `
    <p class="eyebrow">FASE 1 · IMPORT EN DOCUMENTHERKENNING</p><h2>Documenteigenschappen bevestigen</h2>
    <p class="lead">Controleer de voorstellen en bevestig de eigenschappen in één keer. Daarna wordt deze stap niet opnieuw gevraagd.</p>
    <div class="document-list">${exam.documents.map(doc => `<div class="document-card"><strong>${escapeHtml(doc.filename)}</strong><small>${doc.page_count} pagina's · ${doc.sha256.slice(0,12)}…</small><button class="quiet" data-preview="${doc.id}">Eerste pagina bekijken</button></div>`).join('')}</div>
    <form id="metadataForm" class="metadata-form">
      <div class="fields">
        <div class="field"><label for="subject">Vak</label><input id="subject" value="${escapeHtml(common('subject') || 'biologie')}" required></div>
        <div class="field"><label for="level">Niveau</label><input id="level" value="${escapeHtml(common('level'))}" placeholder="vwo" required></div>
        <div class="field"><label for="year">Jaar</label><input id="year" type="number" min="2000" max="2099" value="${escapeHtml(common('year'))}" required></div>
        <div class="field"><label for="period">Tijdvak</label><input id="period" type="number" min="1" max="3" value="${escapeHtml(common('period'))}" required></div>
      </div>
      <h3>Documenttypen</h3><div class="type-list">${exam.documents.map(doc => `<div class="type-row"><span>${escapeHtml(doc.filename)}</span><select data-type-for="${escapeHtml(doc.filename)}">${Object.entries(types).map(([value,label]) => `<option value="${value}" ${(draft.document_types?.[doc.filename] || doc.metadata.document_type) === value ? 'selected' : ''}>${label}</option>`).join('')}</select></div>`).join('')}</div>
      <div class="notice">De originele PDF's blijven ongewijzigd. De eerste pagina wordt alleen gebruikt om de metadata te herkennen en als visueel voorbeeld te tonen.</div>
      <button class="primary" type="submit">Metadata bevestigen en doorgaan</button><p id="metadataDraftStatus" class="muted" role="status">Wijzigingen worden automatisch opgeslagen.</p><p id="metadataError" class="form-error" role="alert"></p>
    </form><div id="pagePreview"></div>`;
  document.querySelectorAll('[data-preview]').forEach(button => button.addEventListener('click', () => showPreview(button.dataset.preview)));
  // Sla metadata als concept op zodra een veld wordt verlaten of een
  // documenttype wordt gewijzigd. Definitief bevestigen blijft een aparte stap.
  let metadataDraftTimer = null;
  const saveMetadataDraft = async () => {
    clearTimeout(metadataDraftTimer);
    const payload = {
      subject: $('#subject').value.trim(),
      level: $('#level').value.trim(),
      year: $('#year').value ? Number($('#year').value) : null,
      period: $('#period').value ? Number($('#period').value) : null,
      document_types: Object.fromEntries([...document.querySelectorAll('[data-type-for]')]
        .map(select => [select.dataset.typeFor, select.value]))
    };
    try {
      await api(`/api/exams/${state.examId}/metadata/draft`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload)
      });
      $('#metadataDraftStatus').textContent = 'Metadatawijzigingen automatisch opgeslagen.';
    } catch (error) {
      $('#metadataDraftStatus').textContent = 'Automatisch opslaan mislukt: ' + error.message;
      throw error;
    }
  };
  const scheduleMetadataDraft = () => {
    clearTimeout(metadataDraftTimer);
    metadataDraftTimer = setTimeout(() => saveMetadataDraft().catch(() => {}), 250);
  };
  const flushMetadataDraft = () => saveMetadataDraft().catch(() => {});
  const metadataVisibilityChange = () => {
    if (document.visibilityState === 'hidden') flushMetadataDraft();
  };
  $('#metadataForm').addEventListener('change', scheduleMetadataDraft);
  document.addEventListener('visibilitychange', metadataVisibilityChange);
  window.addEventListener('pagehide', flushMetadataDraft);
  panel._stageAutoSaveCleanup = () => {
    clearTimeout(metadataDraftTimer);
    document.removeEventListener('visibilitychange', metadataVisibilityChange);
    window.removeEventListener('pagehide', flushMetadataDraft);
    panel._stageAutoSaveCleanup = null;
  };
  $('#metadataForm').addEventListener('submit', confirmMetadata);
}

async function showPreview(documentId) {
  const doc = state.exam.documents.find(item => String(item.id) === String(documentId));
  $('#pagePreview').innerHTML = `<div class="preview-wrap"><p class="muted">Eerste pagina · ${escapeHtml(doc.filename)}</p><img alt="Eerste pagina van ${escapeHtml(doc.filename)}" src="/api/exams/${state.examId}/documents/${documentId}/preview/0"></div>`;
}

async function confirmMetadata(event) {
  event.preventDefault();
  const payload = {
    subject: $('#subject').value.trim(), level: $('#level').value.trim(),
    year: Number($('#year').value), period: Number($('#period').value),
    document_types: Object.fromEntries([...document.querySelectorAll('[data-type-for]')].map(select => [select.dataset.typeFor, select.value]))
  };
  try {
    await api(`/api/exams/${state.examId}/metadata/confirm`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
    await openWorkspace(state.examId);
  } catch (error) { $('#metadataError').textContent = error.message; }
}


/* De aanvulling wordt nooit automatisch op het bestaande CV toegepast.
   Iedere pagina krijgt een expliciete keuze, zodat een onduidelijke wijziging
   niet ongemerkt een bestaande beoordelingsregel kan overschrijven. */

function examHasDocumentType(documentType) {
  // Gebruik de bevestigde exammetadata als primaire bron. Oudere examens
  // kunnen het documenttype alleen nog in de metadata van het bronbestand
  // hebben opgeslagen; die informatie blijft een geldige terugval.
  return state.exam.documents.some(doc =>
    state.exam.metadata.document_types?.[doc.filename] === documentType ||
    doc.metadata?.document_type === documentType
  );
}

async function renderSkipWorkbookStage() {
  const panel=$('#stagePanel');
  panel.innerHTML=`<p class="eyebrow">FASE 3 · UITWERKBIJLAGE</p><h2>Geen uitwerkbijlage aanwezig</h2><p class="lead">Voor dit examen is geen afzonderlijke uitwerkbijlage geïmporteerd. Deze twee stappen worden als niet van toepassing gemarkeerd; de overige verwerking gaat gewoon door.</p><button class="primary" id="skipWorkbook">Geen uitwerkbijlage bevestigen</button><p id="workbookMessage" class="form-error" role="status"></p>`;
  $('#skipWorkbook').addEventListener('click',async()=>{try{await api(`/api/exams/${state.examId}/skip-optional-workbook`,{method:'POST'});await openWorkspace(state.examId);}catch(error){$('#workbookMessage').textContent=error.message;}});
}

async function renderCvSupplementStage() {
  const panel = $('#stagePanel');
  panel.innerHTML = '<p class="muted">Aanvulling op het correctievoorschrift controleren…</p>';
  try {
    const result = await api(`/api/exams/${state.examId}/cv-supplement`);
    if (result.not_required) {
      panel.innerHTML = `<p class="eyebrow">FASE 5 · AANVULLING CORRECTIEVOORSCHRIFT</p><h2>Geen aanvulling aanwezig</h2><p class="lead">Er is geen document als aanvulling op het correctievoorschrift geïmporteerd. Het oorspronkelijke CV blijft ongewijzigd.</p><button class="primary" id="confirmNoSupplement">Geen aanvulling bevestigen en doorgaan</button><p id="supplementMessage" class="form-error" role="status"></p>`;
      $('#confirmNoSupplement').addEventListener('click', async () => {
        try {
          await api(`/api/exams/${state.examId}/steps/cv_aanvulling/complete`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({reviewed:true, not_required:true})
          });
          await openWorkspace(state.examId);
        } catch (error) { $('#supplementMessage').textContent = error.message; }
      });
      return;
    }
    const doc = result.document;
    panel.innerHTML = `<p class="eyebrow">FASE 5 · AANVULLING CORRECTIEVOORSCHRIFT</p><h2>Aanvulling per pagina beoordelen</h2><p class="lead">Het oorspronkelijke correctievoorschrift blijft intact. Kies per pagina of inhoud wordt toegevoegd, vervangen, genegeerd of handmatig beoordeeld. De app voert geen inhoudelijke vervanging automatisch uit.</p><div class="notice">${result.page_count} pagina's · ${escapeHtml(doc.filename)} · elke pagina moet afzonderlijk worden bekeken.</div>
      ${result.items.map(item => `<article class="analysis-card" data-supplement-page="${item.page_number}"><h3>Pagina ${item.page_number}${item.question_numbers.length ? ` · vraag ${item.question_numbers.join(', ')}` : ''}</h3><img class="fragment-image" loading="lazy" alt="Pagina ${item.page_number} van de CV-aanvulling" src="/api/exams/${state.examId}/documents/${doc.id}/preview/${item.page_index}"><p class="analysis-reason">${escapeHtml(item.reason)}</p><label>Verwerking<select data-supplement-action="${item.page_number}"><option value="toevoegen" ${item.action==='toevoegen'?'selected':''}>Toevoegen</option><option value="vervangen" ${item.action==='vervangen'?'selected':''}>Vervangen</option><option value="handmatig" ${item.action==='handmatig'?'selected':''}>Handmatig beoordelen</option><option value="negeren" ${item.action==='negeren'?'selected':''}>Geen inhoudelijke wijziging</option></select></label><label>Betrokken vraagnummers (komma's scheiden)<input type="text" data-supplement-questions="${item.page_number}" value="${item.question_numbers.join(', ')}" placeholder="bijvoorbeeld 12, 22"></label><details class="analysis-text"><summary>Tekst uit deze pagina</summary><pre>${escapeHtml(item.text || 'Geen selecteerbare tekstlaag; beoordeel de pagina-afbeelding.')}</pre></details><label class="review-warning"><input type="checkbox" data-supplement-reviewed="${item.page_number}" ${item.reviewed?'checked':''}> Ik heb deze pagina en de voorgestelde verwerking gecontroleerd.</label></article>`).join('')}
      <div class="review-actions"><button class="primary" id="saveSupplement" type="button">Controle opslaan</button><button class="primary" id="completeSupplement" type="button" disabled>Aanvulling beoordelen en doorgaan</button></div><p id="supplementMessage" class="form-error" role="status"></p>`;
    const cards = [...document.querySelectorAll('[data-supplement-page]')];
      prepareStageApproval(panel);
    const checks = () => [...document.querySelectorAll('[data-supplement-reviewed]')];
    const refresh = () => { $('#completeSupplement').disabled = checks().some(input => !input.checked); };
    checks().forEach(input => input.addEventListener('change', refresh)); refresh();
    const collect = () => cards.map(card => {
      const page = Number(card.dataset.supplementPage);
      const item = result.items.find(entry => entry.page_number === page);
      const numbersText=card.querySelector(`[data-supplement-questions="${page}"]`).value;
      const numbers=numbersText.split(',').map(value=>value.trim()).filter(Boolean).map(Number);
      return {page_number:page, action:card.querySelector(`[data-supplement-action="${page}"]`).value,
        question_numbers:numbers, reviewed:card.querySelector(`[data-supplement-reviewed="${page}"]`).checked};
    });
    const save = () => api(`/api/exams/${state.examId}/cv-supplement/review`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:collect()})});
    bindStageAutoSave(panel, save, '#supplementMessage');
    $('#saveSupplement').addEventListener('click', async () => { try { const r=await save(); $('#supplementMessage').textContent=`${r.reviewed_count} van ${r.page_count} pagina's gecontroleerd. Concept opgeslagen.`; } catch(error) { $('#supplementMessage').textContent=error.message; } });
    $('#completeSupplement').addEventListener('click', async () => { try { const r=await save(); if(!r.complete) throw new Error('Controleer eerst alle pagina’s.'); await api(`/api/exams/${state.examId}/steps/cv_aanvulling/complete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviewed:true,reviewed_all_pages:true})}); await openWorkspace(state.examId); } catch(error) { $('#supplementMessage').textContent=error.message; } });
  } catch (error) { panel.innerHTML = `<h2>Aanvulling correctievoorschrift</h2><p class="form-error">${escapeHtml(error.message)}</p>`; }
}

/* Antwoordvoorstellen komen uit de bijbehorende CV-fragmenten. De gebruiker
   ziet altijd de bronafbeelding en kan de tekst corrigeren. De expliciete
   afrondactie bevestigt de complete set; losse vinkjes per antwoord zijn niet
   nodig. De tekstherkenning is dus nooit een eindbeslissing. */
async function renderAnswersStage() {
  const panel = $('#stagePanel');
  panel.innerHTML = '<p class="muted">Antwoorden uit het correctievoorschrift analyseren…</p>';
  try {
    const result = await api(`/api/exams/${state.examId}/answers`);
    panel.innerHTML = `<p class="eyebrow">FASE 6 · ANTWOORDEN HERKENNEN</p><h2>Antwoorden controleren</h2><p class="lead">Per vraag staat het bijbehorende fragment uit het correctievoorschrift. Herkende meerkeuzeletters en gesloten antwoorden zijn voorstellen. Controleer de bronafbeelding en corrigeer de antwoordtekst waar nodig.</p><div class="notice">${result.question_count} CV-fragmenten · lage zekerheid betekent dat de tekst handmatig moet worden nagekeken.</div>
      ${result.questions.map(q => `<article class="analysis-card" data-answer-card="${q.question_number}"><div class="card-heading"><h3>Vraag ${q.question_number}</h3><span class="status-pill">${escapeHtml(q.confidence)} zekerheid</span></div><p class="analysis-reason">${escapeHtml(q.reason)} · Maximumscore CV: ${q.cv_max_points ?? 'onbekend'} · Opgaven: ${q.opgaven_max_points ?? 'onbekend'}${q.points_match===false?' · SCORES VERSCHILLEN':''}</p>${q.segments.map(seg=>`<img class="fragment-image" loading="lazy" alt="Correctievoorschrift vraag ${q.question_number}" src="${escapeHtml(seg.url)}">`).join('')}${(q.supplement_pages||[]).map(page=>`<div class="notice">CV-aanvulling · pagina ${page.page_number} · ${escapeHtml(page.action)}</div><img class="fragment-image" loading="lazy" alt="CV-aanvulling bij vraag ${q.question_number}" src="${escapeHtml(page.url)}">`).join('')}<div class="analysis-fields"><label>Antwoordvorm<select data-answer-kind="${q.question_number}"><option value="meerkeuze" ${q.answer_kind==='meerkeuze'?'selected':''}>Meerkeuze</option><option value="gesloten" ${q.answer_kind==='gesloten'?'selected':''}>Gesloten antwoord</option><option value="open" ${q.answer_kind==='open'?'selected':''}>Open antwoord / beoordelingscriteria</option><option value="handmatig" ${q.answer_kind==='handmatig'?'selected':''}>Handmatig bepalen</option></select></label></div><label class="answer-text-field">Antwoord of beoordelingscriteria<textarea class="answer-textarea" rows="2" data-answer-text="${q.question_number}">${escapeHtml(q.answer_text)}</textarea></label><label class="review-warning"><input type="checkbox" data-answer-reviewed="${q.question_number}" ${q.reviewed?'checked':''}> Ik heb het antwoord van vraag ${q.question_number} aan de hand van het CV-fragment gecontroleerd.</label></article>`).join('')}
      <div class="review-actions"><button class="primary" id="saveAnswers" type="button">Controle opslaan</button><button class="primary" id="completeAnswers" type="button" disabled>Antwoorden goedkeuren en doorgaan</button></div><p id="answersMessage" class="form-error" role="status"></p>`;
    const cards=[...document.querySelectorAll('[data-answer-card]')];
      prepareStageApproval(panel);
    // Het antwoordveld gebruikt de volledige breedte en groeit mee met de
    // ingevoerde antwoordtekst of beoordelingscriteria.
    const answerFields = [...document.querySelectorAll('[data-answer-text]')];
    const resizeAnswerField = field => {
      field.style.height = 'auto';
      field.style.height = `${Math.max(field.scrollHeight, 72)}px`;
    };
    answerFields.forEach(field => {
      resizeAnswerField(field);
      field.addEventListener('input', () => resizeAnswerField(field));
    });
    const checks=()=>[...document.querySelectorAll('[data-answer-reviewed]')];
    const refresh=()=>{$('#completeAnswers').disabled=checks().some(input=>!input.checked);};
    checks().forEach(input=>input.addEventListener('change',refresh)); refresh();
    const collect=()=>cards.map(card=>{const n=Number(card.dataset.answerCard);return {question_number:n,answer_kind:card.querySelector(`[data-answer-kind="${n}"]`).value,answer_text:card.querySelector(`[data-answer-text="${n}"]`).value,reviewed:card.querySelector(`[data-answer-reviewed="${n}"]`).checked};});
    const save=()=>api(`/api/exams/${state.examId}/answers/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({questions:collect()})});
    bindStageAutoSave(panel, save, '#answersMessage');
    $('#saveAnswers').addEventListener('click',async()=>{try{const r=await save();$('#answersMessage').textContent=`${r.reviewed_count} van ${result.question_count} antwoorden gecontroleerd. Concept opgeslagen.`;}catch(error){$('#answersMessage').textContent=error.message;}});
    let completingAnswers = false;
    $('#completeAnswers').addEventListener('click',async()=>{
      const button = $('#completeAnswers');
      if (completingAnswers) return;
      completingAnswers = true;
      button.disabled = true;
      button.textContent = 'Controleren en afronden…';
      try {
        // Wacht op de gedeelde autosaveketen zodat een recente wijziging
        // niet gelijktijdig met de definitieve goedkeuring wordt opgeslagen.
        const r = panel._stageAutoSaveFlush
          ? await panel._stageAutoSaveFlush()
          : await save();
        if(!r.complete) throw new Error('Controleer eerst alle antwoorden.');
        await api(`/api/exams/${state.examId}/steps/antwoorden/complete`,{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({reviewed:true,reviewed_all_questions:true})
        });
        await openWorkspace(state.examId);
      } catch(error) {
        completingAnswers = false;
        button.disabled = false;
        button.textContent = 'Antwoorden goedkeuren en doorgaan';
        $('#answersMessage').textContent=error.message;
      }
    });
  } catch(error) { panel.innerHTML=`<h2>Antwoorden herkennen</h2><p class="form-error">${escapeHtml(error.message)}</p>`; }
}

/* De relatiescherm controleert niet alleen aantallen, maar toont expliciet
   welke vragen een CV-fragment hebben en welke vragen ook in de uitwerkbijlage
   voorkomen. De uitwerkbijlage hoeft niet alle examenvragen te bevatten. */
async function renderRelationsStage() {
  const panel=$('#stagePanel');
  panel.innerHTML='<p class="muted">Automatische controles op document- en vraagkoppelingen uitvoeren…</p>';
  try {
    const result=await api(`/api/exams/${state.examId}/relations`);
    const previous = state.exam.steps.relaties?.evidence?.questions || [];
    const previousNotes = Object.fromEntries(previous.map(item=>[item.question_number,item.note||'']));
    const mismatches = result.score_mismatches || [];
    panel.innerHTML=`
      <p class="eyebrow">FASE 7 · AANVULLENDE CONTROLES</p>
      <h2>Automatische integriteitscontrole</h2>
      <p class="lead">De applicatie vergelijkt de vraagnummering en documentkoppelingen automatisch. Je hoeft normale koppelingen niet stuk voor stuk af te vinken. Alleen afwijkingen vragen om een beslissing of toelichting.</p>
      <div class="notice">${result.question_count} opgaven gecontroleerd · ${result.questions.filter(q=>q.has_cv).length} CV-koppelingen · ${result.uitwerk_questions.length} uitwerkbijlagevragen</div>
      <div class="relation-grid">
        <span>${result.missing_cv.length ? 'CV-fragmenten ontbreken: '+result.missing_cv.join(', ') : 'Alle opgaven hebben een CV-koppeling'}</span>
        <span>${result.extra_cv.length ? 'CV-vragen zonder opgave: '+result.extra_cv.join(', ') : 'Geen extra CV-vragen'}</span>
        <span>${result.missing_answers.length ? 'Antwoorden ontbreken: '+result.missing_answers.join(', ') : 'Antwoordrecords volledig gekoppeld'}</span>
        <span>${result.extra_answers.length ? 'Antwoorden zonder opgave: '+result.extra_answers.join(', ') : 'Geen extra antwoordrecords'}</span>
        <span>${mismatches.length ? mismatches.length+' afwijkende maximumscores' : 'Maximumscores komen overeen waar vergelijkbaar'}</span>
        <span>${result.uitwerk_questions.length} vragen in de uitwerkbijlage · gedeeltelijke dekking is toegestaan</span>
      </div>
      ${result.missing_cv.length ? `
        <section class="analysis-card">
          <h3>Ontbrekende CV-fragmenten</h3>
          <p class="form-error">Voor vraag ${result.missing_cv.join(', ')} is geen correctievoorschriftfragment gevonden. Herstel dit in stap 8 voordat je verdergaat.</p>
          <button class="quiet" type="button" id="repairMissingCv">CV-fragmenten herstellen</button>
        </section>` : ''}
      ${result.extra_cv.length ? `
        <section class="analysis-card">
          <h3>CV-vragen zonder opgave</h3>
          <p>Deze nummers komen wel in het CV voor, maar niet in de opgaven: ${result.extra_cv.join(', ')}. Controleer of het om een afwijkende nummering of een onbedoeld extra fragment gaat.</p><button class="quiet" type="button" id="repairExtraCv">CV-vraagstarts herstellen</button>
        </section>` : ''}
      ${result.missing_answers.length ? `
        <section class="analysis-card">
          <h3>Antwoorden ontbreken</h3>
          <p class="form-error">Er is geen antwoordrecord gekoppeld aan vraag ${result.missing_answers.join(', ')}. Controleer de antwoordherkenning in stap 10.</p>
          <button class="quiet" type="button" id="repairMissingAnswers">Antwoorden herstellen</button>
        </section>` : ''}
      ${result.extra_answers.length ? `
        <section class="analysis-card">
          <h3>Antwoorden zonder opgave</h3>
          <p class="form-error">Er zijn antwoordrecords voor vraag ${result.extra_answers.join(', ')}, maar deze nummers komen niet voor in de opgaven.</p>
          <button class="quiet" type="button" id="repairExtraAnswers">Antwoorden herstellen</button>
        </section>` : ''}
      ${mismatches.length ? `
        <h3>Afwijkende maximumscores</h3>
        <p class="lead">Leg alleen bij deze vragen vast waarom de scores verschillen, of herstel de brongegevens in de eerdere stap.</p>
        ${mismatches.map(item=>`<article class="analysis-card" data-relation-issue="${item.question_number}">
          <h3>Vraag ${item.question_number}</h3>
          <div class="relation-grid"><span>Opgave: ${item.opgaven_max_points} punten</span><span>CV: ${item.cv_max_points} punten</span></div>
          <label>Toelichting bij de afwijking<textarea rows="2" data-relation-note="${item.question_number}">${escapeHtml(previousNotes[item.question_number]||'')}</textarea></label>
        </article>`).join('')}` : ''}
      <details class="analysis-text">
        <summary>Alle ${result.question_count} automatische vraagkoppelingen bekijken</summary>
        <div class="relation-audit-list">
          ${result.questions.map(q=>`<div class="relation-audit-row"><strong>Vraag ${q.question_number}</strong><span>CV: ${q.has_cv?'gekoppeld':'ontbreekt'}</span><span>Uitwerkbijlage: ${q.has_uitwerkbijlage?'aanwezig':'niet van toepassing'}</span><span>Scores: ${q.points_match===true?'gelijk':q.points_match===false?'afwijkend':'niet vergelijkbaar'}</span></div>`).join('')}
        </div>
      </details>
      <div class="review-actions">
        <button class="primary" id="saveRelations" type="button">Toelichtingen opslaan</button>
        <button class="primary" id="completeRelations" type="button" ${result.missing_cv.length||result.extra_cv.length||result.missing_answers.length||result.extra_answers.length||mismatches.some(item=>!(previousNotes[item.question_number]||'').trim())?'disabled':''}>Controles afronden en doorgaan</button>
      </div>
      <p id="relationsMessage" class="form-error" role="status"></p>`;
    const cards=[...document.querySelectorAll('[data-relation-issue]')];
    const collect=()=>cards.map(card=>({
      question_number:Number(card.dataset.relationIssue),
      note:card.querySelector(`[data-relation-note="${card.dataset.relationIssue}"]`).value
    }));
    const save=()=>api(`/api/exams/${state.examId}/relations/review`,{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({questions:collect()})
    });
    bindStageAutoSave(panel,save,'#relationsMessage');
    const refresh=()=>{
      const unresolved=cards.some(card=>!card.querySelector('textarea').value.trim());
      $('#completeRelations').disabled=result.missing_cv.length>0||result.extra_cv.length>0||result.missing_answers.length>0||result.extra_answers.length>0||unresolved;
    };
    cards.forEach(card=>card.querySelector('textarea').addEventListener('input',refresh));
    $('#saveRelations').addEventListener('click',async()=>{
      try {
        const saved=await save();
        $('#relationsMessage').textContent='Toelichtingen opgeslagen. '+saved.reviewed_count+' koppelingen zijn automatisch gecontroleerd.';
        refresh();
      } catch(error) { $('#relationsMessage').textContent=error.message; }
    });
    $('#completeRelations').addEventListener('click',async()=>{
      const button=$('#completeRelations');
      button.disabled=true;
      try {
        const saved=await save();
        if(!saved.complete) throw new Error('Los eerst de getoonde afwijkingen op.');
        await api(`/api/exams/${state.examId}/steps/relaties/complete`,{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({reviewed:true,reviewed_all_questions:true})
        });
        await openWorkspace(state.examId);
      } catch(error) {
        $('#relationsMessage').textContent=error.message;
        refresh();
      }
    });
    $('#repairMissingCv')?.addEventListener('click',async()=>{
      try {
        await api(`/api/exams/${state.examId}/steps/cv_fragments/reopen`,{method:'POST'});
        await openWorkspace(state.examId);
      } catch(error) { $('#relationsMessage').textContent=error.message; }
    });
    $('#repairExtraCv')?.addEventListener('click',async()=>{
      try {
        await api(`/api/exams/${state.examId}/steps/cv_starts/reopen`,{method:'POST'});
        await openWorkspace(state.examId);
      } catch(error) { $('#relationsMessage').textContent=error.message; }
    });
    document.querySelectorAll('#repairMissingAnswers, #repairExtraAnswers').forEach(button=>{
      button.addEventListener('click',async()=>{
        try {
          await api(`/api/exams/${state.examId}/steps/antwoorden/reopen`,{method:'POST'});
          await openWorkspace(state.examId);
        } catch(error) { $('#relationsMessage').textContent=error.message; }
      });
    });
  } catch(error) {
    panel.innerHTML=`<h2>Integriteitscontrole</h2><p class="form-error">${escapeHtml(error.message)}</p>`;
  }
}

/* De snippetfase maakt contextkandidaten los van de vraagfragmenten. Een
   contextbereik wordt alleen als voorstel ingevuld; de docent controleert en
   corrigeert de reeks vragen waarop de context van toepassing is. */
async function renderSnippetsStage() {
  const panel=$('#stagePanel');
  panel.innerHTML='<p class="muted">Contexten en definitieve snippets voorbereiden…</p>';
  try {
    const result=await api(`/api/exams/${state.examId}/snippets`);
    const contextCards=result.contexts.map(context=>`<article class="analysis-card" data-context-card="${escapeHtml(context.id)}"><div class="card-heading"><h3>Context · pagina ${context.page_number}</h3><span class="muted">Voorstel: vraag ${context.suggested_from_question}–${context.to_question}</span></div><img class="fragment-image" loading="lazy" src="${escapeHtml(context.url)}" alt="Contextfragment op pagina ${context.page_number}"><p class="analysis-reason">${escapeHtml(context.label)}</p><div class="analysis-fields"><label>Vanaf vraag<input type="number" min="1" max="60" data-context-from="${escapeHtml(context.id)}" value="${context.from_question}"></label><label>Tot en met vraag<input type="number" min="1" max="60" data-context-to="${escapeHtml(context.id)}" value="${context.to_question}"></label></div><details class="analysis-text"><summary>Tekstlaag (hulpmiddel)</summary><pre>${escapeHtml(context.extracted_text)}</pre></details><label class="review-warning"><input type="checkbox" data-context-reviewed="${escapeHtml(context.id)}" ${context.reviewed?'checked':''}> Ik heb deze context en het vraagbereik gecontroleerd.</label></article>`).join('');
    const questionCards=result.opgaven.questions.map(q=>`<article class="analysis-card" data-snippet-question="${q.question_number}"><h3>Vraag ${q.question_number}</h3><div class="fragment-images">${q.segments.map(seg=>`<figure><figcaption>Pagina ${seg.page_number}</figcaption><img loading="lazy" src="${escapeHtml(seg.url)}" alt="Definitief vraagfragment ${q.question_number}"></figure>`).join('')}</div><label class="review-warning"><input type="checkbox" data-snippet-reviewed="${q.question_number}" ${q.reviewed?'checked':''}> Ik heb het definitieve vraagfragment gecontroleerd.</label></article>`).join('');
    const workbookCards=result.uitwerkbijlage.questions.map(q=>`<article class="analysis-card"><h3>Uitwerkbijlage · vraag ${q.question_number}</h3>${q.segments.map(seg=>`<img class="fragment-image" loading="lazy" src="${escapeHtml(seg.url)}" alt="Uitwerkbijlagevraag ${q.question_number}">`).join('')}<label class="review-warning"><input type="checkbox" data-snippet-uitwerk="${q.question_number}" ${q.reviewed?'checked':''}> Ik heb dit fragment gecontroleerd.</label></article>`).join('');
    const cvCards=result.correctievoorschrift.questions.map(q=>`<article class="analysis-card"><h3>Correctievoorschrift · vraag ${q.question_number}</h3>${q.segments.map(seg=>`<img class="fragment-image" loading="lazy" src="${escapeHtml(seg.url)}" alt="CV-fragment ${q.question_number}">`).join('')}<label class="review-warning"><input type="checkbox" data-snippet-cv="${q.question_number}" ${q.reviewed?'checked':''}> Ik heb dit CV-fragment gecontroleerd.</label></article>`).join('');
    panel.innerHTML=`<p class="eyebrow">FASE 8 · DEFINITIEVE SNIPPETS</p><h2>Contexten en snippets controleren</h2><p class="lead">De vraag-, uitwerkbijlage- en CV-fragmenten zijn uit de oorspronkelijke PDF's opgebouwd. Contexten worden afzonderlijk voorgesteld, zodat één context aan een reeks vragen gekoppeld kan worden.</p><div class="notice">${result.question_count} vragen · ${result.context_count} contextvoorstellen · ${result.uitwerkbijlage.question_count} uitwerkbijlagefragmenten · ${result.correctievoorschrift.question_count} CV-fragmenten.</div><h3>Contexten</h3>${contextCards||'<p class="muted">Geen contextvoorstellen op basis van de tekstlaag. Controleer de oorspronkelijke opgaven visueel en bevestig hieronder of er geen afzonderlijke contexten zijn.</p><label class="review-warning"><input type="checkbox" id="confirmNoContexts"> Ik heb gecontroleerd dat er geen afzonderlijke contextfragmenten gekoppeld hoeven te worden.</label>'}<h3>Vraagfragmenten</h3>${questionCards}<h3>Uitwerkbijlagefragmenten</h3>${workbookCards||'<p class="muted">Geen uitwerkbijlagefragmenten van toepassing.</p>'}<h3>Correctievoorschriftfragmenten</h3>${cvCards}<div class="review-actions"><button class="primary" id="saveSnippets">Snippetcontrole opslaan</button><button class="primary" id="completeSnippets" disabled>Snippets goedkeuren en doorgaan</button></div><p id="snippetsMessage" class="form-error" role="status"></p>`;
    const contextChecks=()=>[...document.querySelectorAll('[data-context-reviewed]')];
      prepareStageApproval(panel);
    const questionChecks=()=>[...document.querySelectorAll('[data-snippet-reviewed]')];
    const workbookChecks=()=>[...document.querySelectorAll('[data-snippet-uitwerk]')];
    const cvChecks=()=>[...document.querySelectorAll('[data-snippet-cv]')];
    const noContextConfirmed=()=>!result.contexts.length && $('#confirmNoContexts')?.checked;
    const refresh=()=>{$('#completeSnippets').disabled=contextChecks().some(x=>!x.checked)||questionChecks().some(x=>!x.checked)||workbookChecks().some(x=>!x.checked)||cvChecks().some(x=>!x.checked)||(!result.contexts.length&&!noContextConfirmed());};
    [...contextChecks(),...questionChecks(),...workbookChecks(),...cvChecks()].forEach(x=>x.addEventListener('change',refresh));
    $('#confirmNoContexts')?.addEventListener('change',refresh); refresh();
    const collect=()=>({contexts:result.contexts.map(c=>({id:c.id,from_question:Number(document.querySelector(`[data-context-from="${c.id}"]`).value),to_question:Number(document.querySelector(`[data-context-to="${c.id}"]`).value),reviewed:document.querySelector(`[data-context-reviewed="${c.id}"]`).checked})),reviewed_question_numbers:questionChecks().filter(x=>x.checked).map(x=>Number(x.dataset.snippetReviewed)),reviewed_uitwerk_numbers:workbookChecks().filter(x=>x.checked).map(x=>Number(x.dataset.snippetUitwerk)),reviewed_cv_numbers:cvChecks().filter(x=>x.checked).map(x=>Number(x.dataset.snippetCv)),confirmed_no_contexts:noContextConfirmed()});
    const save=(options={})=>api(`/api/exams/${state.examId}/snippets/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...collect(),...options})});
    bindStageAutoSave(panel, save, '#snippetsMessage');
    $('#saveSnippets').addEventListener('click',async()=>{try{const r=await save();$('#snippetsMessage').textContent=`${r.reviewed_count} vragen en ${r.reviewed_all_contexts?result.context_count:contextChecks().filter(x=>x.checked).length} contexten gecontroleerd.`;}catch(error){$('#snippetsMessage').textContent=error.message;}});
    $('#completeSnippets').addEventListener('click',async()=>{try{const r=await save();if(!r.complete)throw new Error('Controleer eerst alle contexten en vraagfragmenten.');await api(`/api/exams/${state.examId}/steps/snippets/complete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviewed:true,reviewed_all_questions:true,reviewed_all_contexts:true})});await openWorkspace(state.examId);}catch(error){$('#snippetsMessage').textContent=error.message;}});
  } catch(error) { panel.innerHTML=`<h2>Definitieve snippets</h2><p class="form-error">${escapeHtml(error.message)}</p>`; }
}

/* De integrale eindcontrole toont alle bronnen in één vraagkaart. Problemen
   worden niet verborgen: ontbrekende koppelingen en afwijkende scores blijven
   zichtbaar en vragen een toelichting voordat het examen kan worden afgerond.
   De afrondknop is de bevestiging; per vraag afvinken is overbodig. */
async function renderFinalReviewStage() {
  const panel=$('#stagePanel');
  panel.innerHTML='<p class="muted">Integrale eindcontrole samenstellen…</p>';
  try {
    const result=await api(`/api/exams/${state.examId}/final-review`);
    panel.innerHTML=`<p class="eyebrow">FASE 9 · INTEGRALE EINDCONTROLE</p><h2>Iedere vraag in samenhang controleren</h2><p class="lead">Controleer per vraag de context, opgave, eventuele uitwerkbijlage, correctievoorschrift, antwoord en punten. Bij een verschil tussen de maximumscore in opgave en CV moet de oplossing worden toegelicht.</p><div class="notice">${result.question_count} vragen · controleer de volledige visuele samenhang vóór publicatie.</div>
      ${result.questions.map(q=>`<article class="analysis-card final-review-card" data-final-card="${q.question_number}"><div class="card-heading"><h3>Vraag ${q.question_number}</h3><span class="status-pill">${q.points_match===false?'Scoreverschil':q.correctievoorschrift.length?'CV gekoppeld':'CV ontbreekt'}</span></div><h4>Gekoppelde context</h4>${q.context.length?q.context.map(c=>`<figure><figcaption>Context · pagina ${c.page_number} · vragen ${c.from_question}–${c.to_question}</figcaption><img class="fragment-image" loading="lazy" src="${escapeHtml(c.url)}" alt="Context bij vraag ${q.question_number}"></figure>`).join(''):'<p class="muted">Geen context gekoppeld.</p>'}<h4>Opgave</h4>${q.opgaven.map(seg=>`<figure><figcaption>Pagina ${seg.page_number}</figcaption><img class="fragment-image" loading="lazy" src="${escapeHtml(seg.url)}" alt="Opgave ${q.question_number}"></figure>`).join('')}<h4>Uitwerkbijlage</h4>${q.uitwerkbijlage.length?q.uitwerkbijlage.map(seg=>`<img class="fragment-image" loading="lazy" src="${escapeHtml(seg.url)}" alt="Uitwerkbijlage ${q.question_number}">`).join(''):'<p class="muted">Geen bijbehorend onderdeel in de uitwerkbijlage.</p>'}<h4>Correctievoorschrift</h4>${q.correctievoorschrift.length?q.correctievoorschrift.map(seg=>`<img class="fragment-image" loading="lazy" src="${escapeHtml(seg.url)}" alt="Correctievoorschrift ${q.question_number}">`).join(''):'<p class="form-error">Geen CV-fragment gekoppeld.</p>'}${(q.supplement_pages||[]).map(page=>`<p class="analysis-reason">Aanvulling · pagina ${page.page_number} · ${escapeHtml(page.action)}${page.action==='vervangen'?' (vervangt het oorspronkelijke antwoordvoorstel)':''}</p><img class="fragment-image" loading="lazy" src="${escapeHtml(page.url)}" alt="Aanvulling correctievoorschrift bij vraag ${q.question_number}">`).join('')}${q.options?.length?`<h4>Herkende antwoordopties</h4><ul>${q.options.map(option=>`<li><strong>${escapeHtml(option.letter)}.</strong> ${escapeHtml(option.text)}</li>`).join('')}</ul>`:''}<div class="relation-grid"><span>Vraagtype: ${escapeHtml(q.question_type)}</span><span>Maximumscore opgave: ${q.max_points??'onbekend'}</span><span>Maximumscore CV: ${q.cv_max_points??'onbekend'}</span><span>Antwoordvorm: ${escapeHtml(q.answer_kind)}</span></div><details><summary>Antwoord / beoordelingscriteria</summary><pre>${escapeHtml(q.answer_text)}</pre></details>${q.points_match===false?'<p class="form-error">De maximumscores komen niet overeen. Leg vast hoe dit verschil is gecontroleerd.</p>':''}<label>Toelichting bij afwijking / herstel<textarea rows="2" data-final-note="${q.question_number}">${escapeHtml(q.resolution_note)}</textarea></label><label class="review-warning"><input type="checkbox" data-final-reviewed="${q.question_number}" ${q.reviewed?'checked':''}> Ik heb vraag ${q.question_number} in samenhang gecontroleerd.</label><div class="review-actions"><button class="quiet" type="button" data-repair="opgaven_fragments">Opgavefragment herstellen</button><button class="quiet" type="button" data-repair="opgaven_analyse">Vraagtype / punten / opties</button>${examHasDocumentType('uitwerkbijlage')?'<button class="quiet" type="button" data-repair="uitwerk_fragments">Uitwerkfragment herstellen</button>':''}<button class="quiet" type="button" data-repair="cv_fragments">CV-fragment herstellen</button><button class="quiet" type="button" data-repair="cv_aanvulling">CV-aanvulling aanpassen</button><button class="quiet" type="button" data-repair="antwoorden">Antwoord aanpassen</button><button class="quiet" type="button" data-repair="relaties">Koppeling herstellen</button></div></article>`).join('')}
      <div class="review-actions"><button class="primary" id="saveFinalReview">Eindcontrole opslaan</button><button class="primary" id="completeFinalReview" disabled>Eindcontrole afronden</button></div><p id="finalReviewMessage" class="form-error" role="status"></p>`;
    const cards=[...document.querySelectorAll('[data-final-card]')];
      prepareStageApproval(panel);
    const checks=()=>[...document.querySelectorAll('[data-final-reviewed]')];
    const refresh=()=>{$('#completeFinalReview').disabled=checks().some(x=>!x.checked)||result.questions.some(q=>q.points_match===false&&!document.querySelector(`[data-final-note="${q.question_number}"]`).value.trim());};
    checks().forEach(x=>x.addEventListener('change',refresh));
    document.querySelectorAll('[data-final-note]').forEach(x=>x.addEventListener('input',refresh)); refresh();
    const collect=()=>cards.map(card=>{const n=Number(card.dataset.finalCard);return {question_number:n,reviewed:card.querySelector(`[data-final-reviewed="${n}"]`).checked,resolution_note:card.querySelector(`[data-final-note="${n}"]`).value};});
    const save=(options={})=>api(`/api/exams/${state.examId}/final-review/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({questions:collect(),...options})});
    bindStageAutoSave(panel, save, '#finalReviewMessage');
    $('#saveFinalReview').addEventListener('click',async()=>{try{const r=await save();$('#finalReviewMessage').textContent=`${r.reviewed_count} van ${result.question_count} vragen gecontroleerd.`;}catch(error){$('#finalReviewMessage').textContent=error.message;}});
    $('#completeFinalReview').addEventListener('click',async()=>{try{const r=await save();if(!r.complete)throw new Error('Controleer eerst alle vragen.');await api(`/api/exams/${state.examId}/steps/eindcontrole/complete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviewed:true,reviewed_all_questions:true})});await openWorkspace(state.examId);}catch(error){$('#finalReviewMessage').textContent=error.message;}});
    document.querySelectorAll('[data-repair]').forEach(button=>button.addEventListener('click',async()=>{try{await api(`/api/exams/${state.examId}/steps/${button.dataset.repair}/reopen`,{method:'POST'});await openWorkspace(state.examId);}catch(error){$('#finalReviewMessage').textContent=error.message;}}));
  } catch(error) { panel.innerHTML=`<h2>Integrale eindcontrole</h2><p class="form-error">${escapeHtml(error.message)}</p>`; }
}

async function renderPublicationStage() {
  const panel=$('#stagePanel');
  panel.innerHTML=`<p class="eyebrow">FASE 10 · PUBLICATIE</p><h2>Examen publiceren</h2><p class="lead">Alle verwerkingsstappen en de integrale eindcontrole zijn afgerond. Publiceer het examen nu in de examenbibliotheek.</p><div class="notice">Na publicatie wordt het examen in de bibliotheek als gepubliceerd gemarkeerd. De oorspronkelijke PDF's en alle afgeleide fragmenten blijven bewaard.</div><button class="primary" id="publishExam">Publiceren in examenbibliotheek</button><p id="publishMessage" class="form-error" role="status"></p>`;
  $('#publishExam').addEventListener('click',async()=>{try{await api(`/api/exams/${state.examId}/publish`,{method:'POST'});await openWorkspace(state.examId);}catch(error){$('#publishMessage').textContent=error.message;}});
}

function renderStageOverview(next, completed) {
  const exam = state.exam;
  const nextStep = next || state.workflow[state.workflow.length - 1];
  if (!next && exam.published) {
    $('#stagePanel').innerHTML = `<p class="eyebrow">EXAMENBIBLIOTHEEK</p><h2>Examen gepubliceerd</h2><p class="lead">Alle verwerkingsstappen zijn afgerond en het examen is gepubliceerd.</p><button class="primary" id="returnLibrary">Terug naar examenbibliotheek</button>`;
    $('#returnLibrary').addEventListener('click', showLibrary);
    return;
  }
  const docs = exam.documents.map(doc => `<div class="document-card"><strong>${escapeHtml(doc.filename)}</strong><small>${doc.page_count} pagina's · ${doc.metadata.document_type || 'documenttype bevestigd'}</small><button class="quiet" data-preview="${doc.id}">PDF bekijken</button></div>`).join('');
  $('#stagePanel').innerHTML = `
    <p class="eyebrow">EXAMENWERKRUIMTE</p><h2>${escapeHtml(nextStep.title)}</h2>
    <p class="lead">${escapeHtml(nextStep.description)}</p>
    <div class="notice">De centrale werkruimte en persistente workflow zijn actief. De gespecialiseerde bewerkingsschermen worden stapsgewijs in deze omgeving geïntegreerd. Een stap kan niet worden overgeslagen: de server controleert de voorgangers en vereist controlebewijs.</div>
    <h3>Bronbestanden</h3>${docs}
    <h3>Voortgang</h3><p>${completed.length} van ${state.workflow.length} workflowstappen afgerond.</p>
    <div class="locked-note">De inhoudelijke bewerkingsinterface voor deze stap is nog in ontwikkeling. Er wordt geen stap als afgerond gemarkeerd zolang de bijbehorende visuele controle en opslag nog niet beschikbaar zijn.</div>`;
  document.querySelectorAll('[data-preview]').forEach(button => button.addEventListener('click', () => showPreview(button.dataset.preview)));
}

loadLibrary().catch(error => { $('#examList').textContent = error.message; });


/* De vraagstartreview is de eerste echte inhoudelijke werkstap in de nieuwe
   geïntegreerde applicatie. De PDF blijft de bron; de overlays zijn alleen
   een reviewlaag. Menselijke beslissingen worden als concept in SQLite
   opgeslagen en pas na een expliciete afrondactie workflowbewijs. */
async function renderQuestionStartsStage(stepKey, documentType, stageLabel, stageTitle, existingResult = null) {
  const panel = $('#stagePanel');
  panel.innerHTML = '<p class="muted">Vraagstarts analyseren…</p>';
  try {
    // Bij een handmatige wijziging gebruiken we het reeds geladen model.
    // Daardoor blijven alle nog niet opgeslagen beslissingen behouden.
    const result = existingResult || await api(`/api/exams/${state.examId}/document-question-starts/${documentType}`);
    state.questionStartReview = result;

    const renderCandidate = (item) => `
      <label class="candidate-row ${item.sequence_warning ? 'candidate-suspect' : ''}">
        <input type="checkbox" data-candidate="${escapeHtml(item.id)}" aria-label="Als hoofdvraagstart gebruiken: ${item.question_number}" ${item.accepted ? 'checked' : ''}>
        <span><strong>${item.sequence_warning ? 'Mogelijke subnummering' : 'Hoofdvraag'} ${item.question_number}</strong><small>${escapeHtml(item.text)} · positie ${Math.round(item.pdf_bbox[1])} pt${item.source === 'manual' ? ' · handmatig' : ''}${item.sequence_warning ? ' · niet opgenomen als hoofdvraagstart: nummer past niet in de oplopende reeks (bijvoorbeeld een stelling of subvraag)' : ''}</small></span>
        <input aria-label="Vraagnummer" type="number" min="1" max="60" value="${item.question_number}" data-number="${escapeHtml(item.id)}" style="width:5rem">
        <select aria-label="Verplaats naar pagina" data-move="${escapeHtml(item.id)}">
          ${result.pages.map(page => `<option value="${page.page_index}" ${page.page_index === item.page_index ? 'selected' : ''}>P. ${page.page_index + 1}</option>`).join('')}
        </select>
        <button class="quiet small" type="button" data-reposition="${escapeHtml(item.id)}">Positie</button>
        <button class="quiet small" type="button" data-remove="${escapeHtml(item.id)}" aria-label="Vraagstart verwijderen">Verwijderen</button>
      </label>`;

    const renderPage = (page) => {
      const candidates = page.candidates.map(renderCandidate).join('');
      const rects = page.candidates.map(item => `<rect data-overlay="${escapeHtml(item.id)}" x="${item.preview_bbox[0]}" y="${item.preview_bbox[1]}" width="${item.preview_bbox[2]-item.preview_bbox[0]}" height="${Math.max(16,item.preview_bbox[3]-item.preview_bbox[1])}" />`).join('');
      return `<article class="question-page" data-page-card="${page.page_index}">
        <h4>Pagina ${page.page_index + 1} <span class="muted">· ${page.candidates.length} voorstellen</span></h4>
        <div class="page-canvas" data-page-canvas="${page.page_index}">
          <img src="/api/exams/${state.examId}/documents/${result.document.id}/preview/${page.page_index}" alt="Oorspronkelijke PDF-pagina ${page.page_index+1}">
          <svg viewBox="0 0 ${page.render_width} ${page.render_height}" preserveAspectRatio="none">${rects}</svg>
        </div>
        <div class="review-actions"><button class="quiet" type="button" data-add-manual="${page.page_index}">Vraagstart toevoegen op deze pagina</button></div>
        <div class="candidate-list" data-candidate-list="${page.page_index}">${candidates || '<p class="muted">Geen vraagstarts voorgesteld op deze pagina.</p>'}</div>
      </article>`;
    };

    const renderAll = () => {
      panel.innerHTML = `
        <p class="eyebrow">${stageLabel}</p>
        <h2>${escapeHtml(stageTitle)}</h2>
        <p class="lead">Controleer de markeringen op de oorspronkelijke pagina's. Je kunt starts toevoegen door op de juiste plek op een pagina te klikken, ze verwijderen of naar een andere pagina verplaatsen. De PDF blijft de bron.</p>
        <div class="notice"><strong>Betekenis van het vinkje:</strong> aangevinkt = dit nummer gebruiken als hoofdvraagstart. Uitgevinkt = de nummerherkenning is niet opgenomen in de hoofdvraagreeks en wordt niet gebruikt voor de automatische vraagfragmenten. Een oranje regel is mogelijk een stellingnummer, subvraag of ander genummerd onderdeel.</div>
        <div class="notice"><strong>${result.candidates.filter(item => !item.removed).length} herkenningen</strong> in ${result.page_count} pagina's van ${escapeHtml(result.document.filename)}. Controleer ook pagina's waarop geen kandidaat is gevonden.</div>
        <div class="review-actions"><button class="quiet" id="acceptAllStarts" type="button">Alle voorstellen accepteren</button><button class="quiet" id="rejectAllStarts" type="button">Alle voorstellen afwijzen</button></div>
        ${result.pages.map(renderPage).join('')}
        <label class="review-warning"><input type="checkbox" id="allPagesReviewed"> Ik heb alle pagina's van dit document visueel gecontroleerd, ook de pagina's zonder voorstellen.</label>
        <div class="review-actions"><button class="primary" id="saveStartReview" type="button">Review opslaan</button><button class="primary" id="completeStartReview" type="button" disabled>Vraagstarts goedkeuren en doorgaan</button></div>
        <p id="startReviewMessage" class="form-error" role="status"></p>`;
      prepareStageApproval(panel);

      const candidateById = new Map(result.candidates.map(item => [item.id, item]));
      const syncControls = () => {
        document.querySelectorAll('[data-candidate]').forEach(input => {
          const item = candidateById.get(input.dataset.candidate);
          if (item) item.accepted = input.checked;
        });
        document.querySelectorAll('[data-number]').forEach(input => {
          const item = candidateById.get(input.dataset.number);
          const value = Number(input.value);
          if (item && Number.isInteger(value) && value >= 1 && value <= 60) item.question_number = value;
        });
      };
      const saveReview = async () => {
        syncControls();
        return api(`/api/exams/${state.examId}/document-question-starts/${documentType}/review`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({candidates:result.candidates})
        });
      };

      // Ook de vraagstartreview wordt na iedere inhoudelijke wijziging
      // automatisch als concept opgeslagen. De expliciete knop blijft bestaan
      // als handmatige bevestiging dat de docent de opslag heeft uitgevoerd.
      let autosaveTimer = null;
      const scheduleStartAutosave = () => {
        clearTimeout(autosaveTimer);
        autosaveTimer = setTimeout(() => {
          saveReview().then(saved => {
            const status = $('#startReviewMessage');
            if (status) status.textContent = 'Wijziging automatisch opgeslagen.';
          }).catch(error => {
            const status = $('#startReviewMessage');
            if (status) status.textContent = 'Automatisch opslaan mislukt: ' + error.message;
          });
        }, 250);
      };
      panel.onchange = event => {
        if (event.target.matches('[data-candidate], [data-number], [data-move]')) {
          scheduleStartAutosave();
        }
      };
      panel.onclick = event => {
        if (event.target.closest('#acceptAllStarts, #rejectAllStarts')) {
          scheduleStartAutosave();
        }
      };
      const flushStartAutosave = () => {
        clearTimeout(autosaveTimer);
        saveReview().catch(error => {
          const status = $('#startReviewMessage');
          if (status) status.textContent = 'Automatisch opslaan mislukt: ' + error.message;
        });
      };
      const startVisibilityChange = () => {
        if (document.visibilityState === 'hidden') flushStartAutosave();
      };
      document.addEventListener('visibilitychange', startVisibilityChange);
      window.addEventListener('pagehide', flushStartAutosave);
      panel._stageAutoSaveCleanup = () => {
        clearTimeout(autosaveTimer);
        panel.onchange = null;
        panel.onclick = null;
        document.removeEventListener('visibilitychange', startVisibilityChange);
        window.removeEventListener('pagehide', flushStartAutosave);
        panel._stageAutoSaveCleanup = null;
      };

      $('#acceptAllStarts').addEventListener('click', () => document.querySelectorAll('[data-candidate]').forEach(input => input.checked = true));
      $('#rejectAllStarts').addEventListener('click', () => document.querySelectorAll('[data-candidate]').forEach(input => input.checked = false));
      $('#allPagesReviewed').addEventListener('change', event => { $('#completeStartReview').disabled = !event.target.checked; });

      // Handmatig plaatsen gebruikt de zichtbare afbeelding als meetvlak en
      // rekent de klik terug naar PDF-punten. De server controleert daarna
      // opnieuw of de rechthoek binnen de werkelijke pagina valt.
      document.querySelectorAll('[data-add-manual]').forEach(button => button.addEventListener('click', () => {
        const pageIndex = Number(button.dataset.addManual);
        const canvas = document.querySelector(`[data-page-canvas="${pageIndex}"]`);
        const image = canvas.querySelector('img');
        button.textContent = 'Klik nu op de positie van de vraagstart…';
        button.disabled = true;
        canvas.classList.add('placing-question-start');
        const place = event => {
          const bounds = image.getBoundingClientRect();
          const page = result.pages[pageIndex];
          const x = Math.max(0, Math.min(page.width - 1, (event.clientX - bounds.left) / bounds.width * page.width));
          const y = Math.max(0, Math.min(page.height - 1, (event.clientY - bounds.top) / bounds.height * page.height));
          // Sla eerst alle op dat moment zichtbare wijzigingen op in de
          // JavaScript-objecten. Zonder deze stap bevat result.candidates nog
          // de oude nummers en zou een latere handmatige toevoeging die oude
          // waarde opnieuw kunnen terugzetten.
          syncControls();

          // Maak een ruim genoeg zoekvak rond de klik. De docent klikt op het
          // gedrukte vraagnummer; de detector zoekt vervolgens het exacte
          // numerieke PDF-woord dat dit vak raakt. Zo komt het nummer uit de
          // bronpagina en niet uit een automatisch gekozen vrije nummerreeks.
          const searchBox = [Math.max(0, x - 12), Math.max(0, y - 8),
            Math.min(page.width, x + 24), Math.min(page.height, y + 12)];
          const numberWord = (page.words || []).find(word => {
            const [wx0, wy0, wx1, wy1] = word.bbox;
            const overlaps = wx1 >= searchBox[0] && wx0 <= searchBox[2] &&
              wy1 >= searchBox[1] && wy0 <= searchBox[3];
            return overlaps && /^\d{1,2}[.)]?$/.test(word.text);
          });
          const numberMatch = numberWord ? numberWord.text.match(/\d{1,2}/) : null;
          let number = numberMatch ? Number(numberMatch[0]) : NaN;

          // Als de PDF geen selecteerbare tekstlaag heeft, blijft handmatig
          // invoeren mogelijk. We vragen dan expliciet om het nummer; nooit
          // stilzwijgend een foutief, zelfgekozen volgnummer gebruiken.
          if (!Number.isInteger(number) || number < 1 || number > 60) {
            const entered = window.prompt('Het vraagnummer kon niet uit de PDF-tekst worden gelezen. Vul het nummer in dat in het geplaatste vakje staat:');
            if (entered === null) return;
            number = Number(entered.trim());
          }
          if (!Number.isInteger(number) || number < 1 || number > 60) {
            $('#startReviewMessage').textContent = 'Gebruik een vraagnummer van 1 tot en met 60.';
            return;
          }

          // Gebruik bij voorkeur de exacte tekstbbox als positie. Als het
          // nummer uit meerdere losse PDF-elementen bestaat, blijft het
          // klikvak als veilige geometrische terugval beschikbaar.
          const bbox = numberWord ? [...numberWord.bbox] : searchBox;
          const candidate = {
            id: `manual-${crypto.randomUUID()}`, question_number:number, page_index:pageIndex,
            text:numberWord ? numberWord.text : 'Handmatig toegevoegde vraagstart', pdf_bbox:bbox,
            preview_bbox:[Number((bbox[0] * page.scale_x).toFixed(2)), Number((bbox[1] * page.scale_y).toFixed(2)),
              Number((bbox[2] * page.scale_x).toFixed(2)), Number((bbox[3] * page.scale_y).toFixed(2))],
            font_size:0, accepted:true, source:'manual', duplicate_number:false
          };
          result.candidates.push(candidate);
          page.candidates.push(candidate);
          page.candidate_count = page.candidates.length;
          renderAll();
          saveReview().catch(error => { $('#startReviewMessage').textContent = 'Automatisch opslaan mislukt: ' + error.message; });
        };
        canvas.addEventListener('click', place, {once:true});
      }));

      // Verplaatsen behoudt de relatieve positie op de pagina. Daardoor komt
      // de vraagstart op dezelfde visuele hoogte/kolom op de doelpagina terecht.
      document.querySelectorAll('[data-move]').forEach(select => select.addEventListener('change', () => {
        syncControls();
        const item = candidateById.get(select.dataset.move);
        const targetIndex = Number(select.value);
        if (!item || targetIndex === item.page_index) return;
        const oldPage = result.pages[item.page_index];
        const newPage = result.pages[targetIndex];
        const [x0,y0,x1,y1] = item.pdf_bbox;
        const relX = x0 / oldPage.width;
        const relY = y0 / oldPage.height;
        const boxW = (x1-x0) / oldPage.width;
        const boxH = (y1-y0) / oldPage.height;
        item.page_index = targetIndex;
        item.pdf_bbox = [relX*newPage.width, relY*newPage.height,
          Math.min(newPage.width, (relX+boxW)*newPage.width),
          Math.min(newPage.height, (relY+boxH)*newPage.height)];
        item.preview_bbox = [Number((item.pdf_bbox[0]*newPage.scale_x).toFixed(2)),
          Number((item.pdf_bbox[1]*newPage.scale_y).toFixed(2)),
          Number((item.pdf_bbox[2]*newPage.scale_x).toFixed(2)),
          Number((item.pdf_bbox[3]*newPage.scale_y).toFixed(2))];
        oldPage.candidates = oldPage.candidates.filter(candidate => candidate.id !== item.id);
        newPage.candidates.push(item);
        oldPage.candidate_count = oldPage.candidates.length;
        newPage.candidate_count = newPage.candidates.length;
        renderAll();
        saveReview().catch(error => { $('#startReviewMessage').textContent = 'Automatisch opslaan mislukt: ' + error.message; });
      }));

      // Een bestaande vraagstart kan ook exact opnieuw worden geplaatst.
      // De klik wordt omgerekend naar PDF-punten; daarmee verschuift later
      // automatisch de grens tussen dit fragment en de voorgaande vraag.
      document.querySelectorAll('[data-reposition]').forEach(button => button.addEventListener('click', () => {
        syncControls();
        const item = candidateById.get(button.dataset.reposition);
        if (!item) return;
        const targetPage = item.page_index;
        const canvas = document.querySelector(`[data-page-canvas="${targetPage}"]`);
        const image = canvas.querySelector('img');
        button.textContent = 'Klik nieuwe positie…';
        button.disabled = true;
        canvas.classList.add('placing-question-start');
        canvas.addEventListener('click', event => {
          const bounds = image.getBoundingClientRect();
          const page = result.pages[targetPage];
          const x = Math.max(0, Math.min(page.width - 1, (event.clientX - bounds.left) / bounds.width * page.width));
          const y = Math.max(0, Math.min(page.height - 1, (event.clientY - bounds.top) / bounds.height * page.height));
          const width = Math.max(8, item.pdf_bbox[2] - item.pdf_bbox[0]);
          const height = Math.max(8, item.pdf_bbox[3] - item.pdf_bbox[1]);
          item.pdf_bbox = [Math.max(0, x - 2), Math.max(0, y - 3),
            Math.min(page.width, x + width - 2), Math.min(page.height, y + height - 3)];
          item.preview_bbox = [Number((item.pdf_bbox[0] * page.scale_x).toFixed(2)),
            Number((item.pdf_bbox[1] * page.scale_y).toFixed(2)),
            Number((item.pdf_bbox[2] * page.scale_x).toFixed(2)),
            Number((item.pdf_bbox[3] * page.scale_y).toFixed(2))];
          renderAll();
          saveReview().catch(error => { $('#startReviewMessage').textContent = 'Automatisch opslaan mislukt: ' + error.message; });
        }, {once:true});
      }));

      // Verwijderen verwijdert alleen de kandidaat uit de review. De bron-PDF
      // wordt niet aangepast; opnieuw analyseren kan de detectie herstellen.
      document.querySelectorAll('[data-remove]').forEach(button => button.addEventListener('click', () => {
        syncControls();
        const item = candidateById.get(button.dataset.remove);
        if (!item) return;
        // Niet fysiek uit de review verwijderen: de tombstone voorkomt dat
        // dezelfde automatische detectie na herladen weer terugkomt.
        item.removed = true;
        item.accepted = false;
        const page = result.pages[item.page_index];
        page.candidates = page.candidates.filter(candidate => candidate.id !== item.id);
        page.candidate_count = page.candidates.length;
        renderAll();
        saveReview().catch(error => { $('#startReviewMessage').textContent = 'Automatisch opslaan mislukt: ' + error.message; });
      }));

      $('#saveStartReview').addEventListener('click', async () => {
        try {
          const saved = await saveReview();
          $('#startReviewMessage').textContent = `${saved.review.accepted_count} vraagstarts geaccepteerd; ${saved.review.rejected_count} afgewezen. Conceptreview opgeslagen.`;
        } catch (error) { $('#startReviewMessage').textContent = error.message; }
      });
      $('#completeStartReview').addEventListener('click', async () => {
        try {
          const saved = await saveReview();
          if (!saved.review.accepted_count) throw new Error('Er is geen enkele vraagstart geaccepteerd. Controleer eerst de detectie.');
          await api(`/api/exams/${state.examId}/steps/${stepKey}/complete`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({reviewed:true, reviewed_all_pages:true, accepted_count:saved.review.accepted_count})
          });
          await openWorkspace(state.examId);
        } catch (error) { $('#startReviewMessage').textContent = error.message; }
      });
    };
    renderAll();
  } catch (error) {
    panel.innerHTML = `<h2>Vraagstarts controleren</h2><p class="form-error">${escapeHtml(error.message)}</p>`;
  }
}



/* Stap 3 voor het opgavenboekje gebruikt één doorlopende afbeelding. De docent
   selecteert daarop rechthoekige verticale bereiken en classificeert elk bereik
   als context of vraag. De rechter inspector beheert de koppeling met één of
   meer vraagnummers; de selectiecoördinaten blijven in pixels van de stitchbron. */
async function renderStitchedOpgavenStage(stepKey, startsStepKey, stageLabel, stageTitle, documentType = 'opgaven') {
  const panel = $('#stagePanel');
  panel.innerHTML = '<p class="muted">Het document wordt samengevoegd tot één lange afbeelding…</p>';
  // Dezelfde werkruimte wordt gebruikt voor opgaven en uitwerkbijlage.
  // Alleen de API-route en toegestane fragmentsoort verschillen.
  const isWorkbook = documentType === 'uitwerkbijlage';
  const isCv = documentType === 'correctievoorschrift';
  const isStitchedDocument = isWorkbook || isCv;
  const documentLabel = isWorkbook ? 'uitwerkbijlage' : isCv ? 'correctievoorschrift' : 'opgavenboekje';
  const stitchedReviewUrl = isStitchedDocument
    ? `/api/exams/${state.examId}/stitched-document/${documentType}/review`
    : `/api/exams/${state.examId}/stitched-opgaven/review`;
  const startsUrl = `/api/exams/${state.examId}/document-question-starts/${documentType}`;
  const fragmentsReviewUrl = `/api/exams/${state.examId}/document-question-fragments/${documentType}/review`;
  try {
    const result = await api(isStitchedDocument
      ? `/api/exams/${state.examId}/stitched-document/${documentType}`
      : `/api/exams/${state.examId}/stitched-opgaven`);
    // Herstel altijd de serverversie van eerder opgeslagen werk. Automatische
    // voorstellen worden alleen gebruikt als er nog geen concept bestaat.
    let selections = (result.selections?.length ? result.selections : (result.proposed_selections || []))
      .map(item => ({...item, question_numbers:[...(item.question_numbers || [])]}));
    let activeIndex = selections.length ? 0 : -1;
    let pendingTop = null;
    let pointerStart = null;
    let saveTimer = null;
    let saveChain = Promise.resolve();
    let completingStep = false;

    panel.innerHTML = `
      <p class="eyebrow">${stageLabel}</p><h2>${escapeHtml(stageTitle)}</h2>
      <p class="lead">${isStitchedDocument
        ? `De volledige pagina’s van het ${documentLabel} zijn samengevoegd tot één doorlopende afbeelding. Controleer de vraagfragmenten, verplaats zo nodig de grenzen en koppel elk fragment aan de juiste vraag.`
        : 'De volledige pagina’s zijn samengevoegd tot één doorlopende afbeelding. Contexten en vragen staan in dezelfde strook. Controleer de voorgestelde afwisseling, verplaats grenzen en koppel elk fragment aan de juiste vragen.'}</p>
      <div class="notice">${result.pages.length} pagina's verwerkt · paginanummers en grote buitenmarges verwijderd vóór het samenvoegen. Wijzigingen worden automatisch opgeslagen; de bron-PDF blijft ongewijzigd.</div>
      <div class="stitched-workspace">
        <section class="stitched-view"><div class="stitched-toolbar"><button class="quiet" id="beginFragment">Nieuw fragment selecteren</button><span id="selectionHint" class="muted">Kies ‘Nieuw fragment selecteren’.</span><span id="stitchedSaveStatus" class="muted" role="status">Opgeslagen versie geladen</span></div>
          <div class="stitched-image-scroll" id="stitchedImageScroll"><div class="stitched-image-wrap" id="stitchedImageWrap"><img id="stitchedImage" src="${result.image_url}" alt="Samengevoegd examen"><div id="stitchedOverlay" class="stitched-overlay"></div></div></div>
        </section>
        <aside class="stitched-inspector"><h3>Fragmenten</h3><div id="stitchedSelectionList"></div></aside>
      </div>
      <div class="review-actions"><button class="primary" id="saveStitched">Nu opslaan</button><button class="primary" id="completeStitched">Fragmentcontrole goedkeuren en doorgaan</button></div><p id="stitchedMessage" class="form-error" role="status"></p>`;

    const img = $('#stitchedImage');
    const wrap = $('#stitchedImageWrap');
    const imageScroll = $('#stitchedImageScroll');
    const overlay = $('#stitchedOverlay');
    const hint = $('#selectionHint');
    const list = $('#stitchedSelectionList');
    const saveStatus = $('#stitchedSaveStatus');
    const whiteRowRanges = result.white_row_ranges || [];
    if (!whiteRowRanges.length) {
      // Geen geldige grensrij betekent dat de selectie niet veilig kan worden
      // bewerkt. Toon een duidelijke fout in plaats van de grens op een
      // willekeurige (mogelijk bedrukte) beeldrij te laten vallen.
      throw new Error('In de examenafbeelding is geen volledig zuiver witte horizontale rij gevonden. Fragmentgrenzen kunnen niet veilig worden geplaatst.');
    }

    // Een grens mag uitsluitend op een rij liggen waarvan iedere RGB-pixel
    // exact wit is. De server levert alleen zulke rijen aan; de browser kiest
    // daaruit steeds de dichtstbijzijnde positie.
    const snapBoundary = (value, minimum = 0, maximum = result.height - 1, edge = 'nearest') => {
      const y = Math.max(minimum, Math.min(maximum, Number(value) || 0));
      let nearest = null;
      let distance = Infinity;

      for (const [rangeStart, rangeEnd] of whiteRowRanges) {
        // Houd de kandidaat binnen de geldige ruimte tussen de andere grens
        // en de rand van de afbeelding. Zo kunnen twee grenzen nooit kruisen.
        const start = Math.max(rangeStart, minimum);
        const end = Math.min(rangeEnd, maximum);
        if (start > end) continue;

        // De bovenrand van een fragment hoort op de onderste rij van de
        // witte strook te liggen; de onderrand op de bovenste rij. 'nearest'
        // blijft beschikbaar voor het eerste klikpunt, dat nog geen rol heeft.
        const candidate = edge === 'top'
          ? end
          : edge === 'bottom'
            ? start
            : Math.max(start, Math.min(end, Math.round(y)));
        const delta = Math.abs(candidate - y);
        if (delta < distance) {
          nearest = candidate;
          distance = delta;
        }
      }

      // Wanneer binnen de toegestane ruimte geen volledig witte rij ligt,
      // blijft de bestaande grens staan. null is nooit een geldige pixelrij.
      return nearest;
    };

    const imageY = event => {
      const rect = img.getBoundingClientRect();
      const raw = Math.max(0, Math.min(result.height - 1, (event.clientY - rect.top) * result.height / rect.height));
      return snapBoundary(raw);
    };

    // Synchroniseer de twee onafhankelijke scrollvakken op basis van hun
    // relatieve voortgang. Zo blijft de rechter fragmentlijst meelopen met de
    // lange examenstrook, en andersom. De guard voorkomt een scroll-lus.
    const stitchedView = imageScroll;
    const inspector = panel.querySelector('.stitched-inspector');
    let syncingScroll = false;
    let suppressScrollSync = false;
    let scrollSyncReleaseTimer = null;

    // Bij een klik op een fragment moet alleen het andere paneel naar de
    // bijbehorende regel springen. De automatische tweerichtingssynchronisatie
    // mag die programmatische sprong niet terugkaatsen naar het paneel waarop
    // de gebruiker zojuist heeft geklikt.
    const pauseScrollSync = () => {
      suppressScrollSync = true;
      clearTimeout(scrollSyncReleaseTimer);
      // scrollend wordt in moderne browsers gebruikt; de timer is de
      // terugval voor browsers die dat event niet ondersteunen.
      scrollSyncReleaseTimer = setTimeout(() => {
        suppressScrollSync = false;
      }, 1200);
    };
    const resumeScrollSync = () => {
      clearTimeout(scrollSyncReleaseTimer);
      suppressScrollSync = false;
    };
    imageScroll.addEventListener('scrollend', resumeScrollSync, {passive:true});
    inspector.addEventListener('scrollend', resumeScrollSync, {passive:true});

    const syncScroll = (source, target) => {
      if (syncingScroll || suppressScrollSync) return;
      syncingScroll = true;
      const sourceRange = Math.max(1, source.scrollHeight - source.clientHeight);
      const targetRange = Math.max(0, target.scrollHeight - target.clientHeight);
      target.scrollTop = source.scrollTop / sourceRange * targetRange;
      requestAnimationFrame(() => { syncingScroll = false; });
    };
    imageScroll.addEventListener('scroll', () => syncScroll(imageScroll, inspector), {passive:true});
    inspector.addEventListener('scroll', () => syncScroll(inspector, stitchedView), {passive:true});

    // Sla een momentopname van de selectie op. Een seriële promiseketen
    // voorkomt dat twee snelle wijzigingen elkaar op de server overschrijven.
    const persistSelections = () => {
      clearTimeout(saveTimer);
      const snapshot = JSON.parse(JSON.stringify(selections));
      saveStatus.textContent = 'Opslaan…';
      saveChain = saveChain.catch(() => {}).then(() => api(
        stitchedReviewUrl,
        {method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({selections:snapshot, reviewed:false})}
      )).then(response => {
        saveStatus.textContent = 'Alle wijzigingen opgeslagen';
        return response;
      }).catch(error => {
        saveStatus.textContent = 'Opslaan mislukt — probeer opnieuw';
        $('#stitchedMessage').textContent = error.message;
        throw error;
      });
      return saveChain;
    };
    // Kleine vertraging bundelt snelle toetsaanslagen, maar elke wijziging
    // wordt zelfstandig bewaard zonder dat de gebruiker op een knop drukt.
    const scheduleSave = () => {
      clearTimeout(saveTimer);
      saveStatus.textContent = 'Wijziging nog niet opgeslagen…';
      saveTimer = setTimeout(() => persistSelections().catch(() => {}), 250);
    };
    // pagehide/visibilitychange vangt ook het sluiten van het tabblad en het
    // wisselen naar een andere applicatie op. keepalive laat de request lopen
    // wanneer de browser de pagina direct daarna inactief maakt.
    const saveOnHide = () => {
      if (completingStep) return;
      clearTimeout(saveTimer);
      const body = JSON.stringify({selections, reviewed:false});
      fetch(stitchedReviewUrl, {
        method:'POST', keepalive:true,
        headers:{'Content-Type':'application/json'}, body
      }).catch(() => {});
    };
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') saveOnHide();
    });
    window.addEventListener('pagehide', saveOnHide, {once:true});

    // De actieve selectie krijgt een hogere stapellaag dan alle andere
    // selecties. Bij samenvallende grenslijnen wordt daardoor altijd de
    // geselecteerde grens geraakt in plaats van een achterliggende grens.
    let boundaryDrag = null;
    overlay.addEventListener('pointerdown', event => {
      const handle = event.target.closest('[data-boundary]');
      if (!handle) return;
      event.preventDefault();
      event.stopPropagation();
      const index = Number(handle.dataset.boundaryIndex);
      if (!selections[index]) return;
      activeIndex = index;
      boundaryDrag = {index, edge:handle.dataset.boundary};
      handle.setPointerCapture?.(event.pointerId);
      overlay.querySelectorAll('[data-overlay-select]').forEach((element, elementIndex) => {
        element.classList.toggle('active', elementIndex === index);
        // De actieve oranje selectie blijft als eigen laag herkenbaar, maar
      // wordt niet meer boven alle blauwe fragmentvlakken gelegd.
      element.style.zIndex = elementIndex === index ? '4' : '2';
      });
      list.querySelectorAll('[data-select-fragment]').forEach((button, buttonIndex) => {
        button.classList.toggle('active', buttonIndex === index);
      });
    });
    overlay.addEventListener('pointermove', event => {
      if (!boundaryDrag) return;
      const item = selections[boundaryDrag.index];
      if (!item) return;
      const y = imageY(event);
      if (y === null) return;
      if (boundaryDrag.edge === 'top') {
        const snappedTop = snapBoundary(y, 0, item.bottom - 12, 'top');
        if (snappedTop === null) return;
        item.top = snappedTop;
      } else {
        const snappedBottom = snapBoundary(y, item.top + 12, result.height - 1, 'bottom');
        if (snappedBottom === null) return;
        item.bottom = snappedBottom;
      }
      const element = overlay.querySelector(`[data-overlay-select="${boundaryDrag.index}"]`);
      if (element) {
        element.style.top = `${item.top / result.height * 100}%`;
        element.style.height = `${(item.bottom - item.top) / result.height * 100}%`;
      }
      const topInput = $('#fragmentTop');
      const bottomInput = $('#fragmentBottom');
      if (topInput) topInput.value = Math.round(item.top);
      if (bottomInput) bottomInput.value = Math.round(item.bottom);
      saveStatus.textContent = 'Grens verplaatst — opslaan na loslaten';
    });
    const stopBoundaryDrag = () => {
      if (!boundaryDrag) return;
      boundaryDrag = null;
      render();
      // Een grens wordt direct bij het loslaten opgeslagen, niet pas wanneer
      // de docent op ‘Nu opslaan’ of ‘Doorgaan’ klikt.
      persistSelections().catch(() => {});
    };
    overlay.addEventListener('pointerup', stopBoundaryDrag);
    overlay.addEventListener('pointercancel', stopBoundaryDrag);

    // Maak vraagbereiken compact leesbaar in de inspector. Een reeks van
    // zeven opeenvolgende vragen wordt bijvoorbeeld "1–7" in plaats van
    // "1, 2, 3, 4, 5, 6, 7".
    const formatQuestionRanges = values => {
      const numbers = [...new Set((values || []).map(Number).filter(n => Number.isInteger(n) && n > 0))]
        .sort((a, b) => a - b);
      const ranges = [];
      for (let index = 0; index < numbers.length;) {
        const start = numbers[index];
        let end = start;
        while (index + 1 < numbers.length && numbers[index + 1] === end + 1) {
          end = numbers[++index];
        }
        ranges.push(start === end ? String(start) : `${start}–${end}`);
        index += 1;
      }
      return ranges.join(', ');
    };

    // Accepteer losse nummers én compacte bereiken zoals "1-7, 10, 12-14".
    // De server ontvangt altijd de expliciete, unieke lijst met vraagnummers.
    const parseQuestionRanges = value => {
      const numbers = new Set();
      const tokens = value.split(/[;,]/).map(token => token.trim()).filter(Boolean);
      if (!tokens.length) return null;
      for (const token of tokens) {
        const range = token.match(/^(\d{1,2})\s*[-–]\s*(\d{1,2})$/);
        if (range) {
          let first = Number(range[1]);
          let last = Number(range[2]);
          if (first < 1 || last > 60) return null;
          if (first > last) [first, last] = [last, first];
          for (let number = first; number <= last; number += 1) numbers.add(number);
          continue;
        }
        if (!/^\d{1,2}$/.test(token)) return null;
        const number = Number(token);
        if (number < 1 || number > 60) return null;
        numbers.add(number);
      }
      return [...numbers].sort((a, b) => a - b);
    };

    // Toon geen technische fragmentnummers. De inhoudelijke naam volgt
    // uit het fragmenttype en de gekoppelde vraag-/vraagnummers.
    const questionLabel = item => {
      const numbers = [...(item.question_numbers || [])].sort((a, b) => a - b);
      if (!numbers.length) return 'Nog niet gekoppeld';
      if (item.type === 'vraag') return numbers.length === 1 ? `Vraag ${numbers[0]}` : `Vragen ${formatQuestionRanges(numbers)}`;
      return `Context bij vraag ${formatQuestionRanges(numbers)}`;
    };

    // Verplaats het middendeel naar het verticale midden van een fragment.
    // De pixelcoördinaten zijn gelijk aan die van de oorspronkelijke lange PNG.
    const scrollImageToFragment = index => {
      const item = selections[index];
      if (!item) return;
      const view = imageScroll;
      // Bereken de doelpositie ten opzichte van het scrollvak zelf. offsetTop
      // hangt af van de offsetParent en gaf bij deze geneste layout soms een
      // positie ten opzichte van de hele pagina in plaats van het werkpaneel.
      const viewRect = view.getBoundingClientRect();
      const imageRect = img.getBoundingClientRect();
      const imageY = (item.top + (item.bottom - item.top) / 2) / result.height * imageRect.height;
      const target = view.scrollTop + imageRect.top - viewRect.top + imageY;
      pauseScrollSync();
      view.scrollTo({top: Math.max(0, target - view.clientHeight / 2), behavior:'smooth'});
    };

    // Scroll de inspector naar het fragment binnen zijn eigen scrollvak.
    // scrollIntoView() kan ook de hele pagina laten bewegen; dat is hier
    // ongewenst omdat alleen de twee werkpanelen synchroon moeten blijven.
    const scrollInspectorToFragment = index => {
      const button = list.querySelector(`[data-select-fragment="${index}"]`);
      if (!button) return;
      const inspectorRect = inspector.getBoundingClientRect();
      const buttonRect = button.getBoundingClientRect();
      const target = inspector.scrollTop + buttonRect.top - inspectorRect.top;
      pauseScrollSync();
      inspector.scrollTo({top:Math.max(0, target - 18), behavior:'smooth'});
    };

    const render = () => {
      // Houd de actieve selectie vast op basis van haar stabiele ID terwijl
      // de volledige lijst op de fysieke documentpositie wordt gesorteerd.
      const activeId = selections[activeIndex]?.id;
      selections.sort((a, b) => Number(a.top) - Number(b.top) || Number(a.bottom) - Number(b.bottom));
      activeIndex = activeId ? selections.findIndex(item => item.id === activeId) : -1;

      // De inhoudelijke naam is voldoende; een los fragmentnummer voegt
      // voor de docent niets toe en verandert bovendien bij hersorteren.
      list.innerHTML = selections.map((item, index) => {
        const selectedEditor = index === activeIndex ? `
          <div class="stitched-editor" id="stitchedEditor">
            <h3>Geselecteerd fragment</h3>
            <label>Type fragment
              <select id="fragmentType" ${isStitchedDocument?'disabled':''}>
                ${isStitchedDocument ? `<option value="vraag" selected>Vraag uit het ${documentLabel}</option>` : `<option value="context" ${item.type==='context'?'selected':''}>Context</option><option value="vraag" ${item.type==='vraag'?'selected':''}>Vraag</option>`}
              </select>
            </label>
            <label>Bij welk(e) vraagnummer(s)?
              <input id="fragmentQuestions" value="${escapeHtml(formatQuestionRanges(item.question_numbers))}" placeholder="bijvoorbeeld 1–7, 9, 12–14" aria-describedby="fragmentQuestionsHelp">
              <small id="fragmentQuestionsHelp" class="field-help">Gebruik bijvoorbeeld 1–7 of 1, 3, 5–8.</small>
            </label>
            <label>Omschrijving (optioneel)
              <input id="fragmentLabel" value="${escapeHtml(item.label||'')}" placeholder="Korte herkenbare omschrijving">
            </label>
            <div class="analysis-fields">
              <label>Bovengrens (witte regel, px)<input id="fragmentTop" type="number" min="0" max="${result.height}" value="${Math.round(item.top)}"></label>
              <label>Ondergrens (witte regel, px)<input id="fragmentBottom" type="number" min="1" max="${result.height}" value="${Math.round(item.bottom)}"></label>
            </div>
            <div class="review-actions"><button type="button" class="quiet" id="deleteFragment">Fragment verwijderen</button></div>
          </div>` : '';
        return `
          <div class="stitched-list-entry">
            <button type="button" class="stitched-list-item ${index===activeIndex?'active':''}" data-select-fragment="${index}">
              <strong>${escapeHtml(questionLabel(item))}</strong>
              <small>${Math.round(item.bottom-item.top)} px</small>
            </button>
            ${selectedEditor}
          </div>`;
      }).join('') || '<p class="muted">Nog geen fragmenten geselecteerd.</p>';

      overlay.innerHTML = selections.map((item,index) =>
        `<div class="stitched-selection ${index===activeIndex?'active':''}" style="top:${item.top/result.height*100}%;height:${(item.bottom-item.top)/result.height*100}%;z-index:${index===activeIndex?4:2}" data-overlay-select="${index}">
          <button type="button" class="stitched-boundary stitched-boundary-top" data-boundary="top" data-boundary-index="${index}" aria-label="Bovengrens verslepen"></button>
          <span>${escapeHtml(questionLabel(item))}</span>
          <button type="button" class="stitched-boundary stitched-boundary-bottom" data-boundary="bottom" data-boundary-index="${index}" aria-label="Ondergrens verslepen"></button>
        </div>`
      ).join('') + (pendingTop!==null?`<div class="stitched-pending" style="top:${pendingTop/result.height*100}%"></div>`:'');

      // Het editorpaneel wordt na de actieve fragmentregel opgebouwd.
      // Daardoor hoeven gebruikers niet meer onderaan een lange lijst te zoeken.
      const editor = list.querySelector('#stitchedEditor');
      if (editor) {
        const item = selections[activeIndex];
        $('#fragmentType').addEventListener('change', event => {
          item.type = event.target.value;
          render();
          scrollInspectorToFragment(activeIndex);
          scheduleSave();
        });
        $('#fragmentQuestions').addEventListener('change', event => {
          const numbers = parseQuestionRanges(event.target.value);
          if (!numbers) {
            event.target.setCustomValidity('Gebruik losse vraagnummers of bereiken, bijvoorbeeld 1–7, 9, 12–14.');
            event.target.reportValidity();
            return;
          }
          event.target.setCustomValidity('');
          item.question_numbers = numbers;
          event.target.value = formatQuestionRanges(numbers);
          render();
          scrollInspectorToFragment(activeIndex);
          scheduleSave();
        });
        $('#fragmentLabel').addEventListener('change', event => {
          item.label = event.target.value;
          scheduleSave();
        });
        const updateBoundary = () => {
          const top = snapBoundary(Number($('#fragmentTop').value), 0, item.bottom - 12, 'top');
          const bottom = snapBoundary(Number($('#fragmentBottom').value), item.top + 12, result.height - 1, 'bottom');
          if (Number.isFinite(top) && Number.isFinite(bottom) && top >= 0 && bottom <= result.height && bottom > top) {
            item.top = top;
            item.bottom = bottom;
            render();
            scrollInspectorToFragment(activeIndex);
            scheduleSave();
          }
        };
        $('#fragmentTop').addEventListener('change', updateBoundary);
        $('#fragmentBottom').addEventListener('change', updateBoundary);
        $('#deleteFragment').addEventListener('click', () => {
          selections.splice(activeIndex, 1);
          activeIndex = selections.length ? Math.min(activeIndex, selections.length - 1) : -1;
          render();
          scheduleSave();
        });
      }

      list.querySelectorAll('[data-select-fragment]').forEach(button =>
        button.addEventListener('click', () => {
          activeIndex = Number(button.dataset.selectFragment);
          render();
          scrollImageToFragment(activeIndex);
        })
      );
      overlay.querySelectorAll('[data-overlay-select]').forEach(element =>
        element.addEventListener('click', () => {
          activeIndex = Number(element.dataset.overlaySelect);
          render();
          scrollInspectorToFragment(activeIndex);
        })
      );
    };

    $('#beginFragment').addEventListener('click',()=>{
      pendingTop=null;pointerStart=null;
      hint.textContent='Klik op de afbeelding bij de bovenrand van het fragment.';
      wrap.classList.add('selecting');render();
    });
    img.addEventListener('click',event=>{
      if(!wrap.classList.contains('selecting')) return;
      const y=imageY(event);
      if(y===null) return;
      if(pendingTop===null){
        pendingTop=y;hint.textContent='Klik nu bij de onderrand van hetzelfde fragment.';render();return;
      }
      const top=Math.min(pendingTop,y),bottom=Math.max(pendingTop,y);
      if(bottom-top<12){
        hint.textContent='Het fragment is te klein. Kies opnieuw.';
        pendingTop=null;render();return;
      }
      const snappedTop=snapBoundary(top, 0, result.height - 1, 'top');
      const snappedBottom=snapBoundary(bottom, 0, result.height - 1, 'bottom');
      if(snappedTop===null || snappedBottom===null || snappedBottom-snappedTop<12){
        hint.textContent='Tussen deze punten ligt geen bruikbare volledig witte grens. Kies opnieuw.';
        pendingTop=null;render();return;
      }
      selections.push({id:`fragment-${Date.now()}-${selections.length}`,type:'vraag',top:snappedTop,bottom:snappedBottom,question_numbers:[],label:''});
      activeIndex=selections.length-1;pendingTop=null;wrap.classList.remove('selecting');
      hint.textContent='Fragment toegevoegd. Vul rechts type en vraagnummers in.';
      render();scheduleSave();
    });

    $('#saveStitched').addEventListener('click',async()=>{
      try {
        await persistSelections();
        $('#stitchedMessage').textContent=`${selections.length} fragmentselecties opgeslagen.`;
      } catch(error) { $('#stitchedMessage').textContent=error.message; }
    });
    $('#completeStitched').addEventListener('click', async () => {
      const button = $('#completeStitched');
      if (completingStep) return;
      completingStep = true;
      button.disabled = true;
      button.textContent = 'Controleren en afronden…';
      try {
        if(!selections.length) throw new Error('Selecteer eerst de contexten en vragen.');
        if(selections.some(item=>!item.question_numbers.length)) throw new Error('Elk fragment moet aan minimaal één vraagnummer gekoppeld zijn.');
        if(!selections.some(item=>item.type==='vraag')) throw new Error('Er moet minimaal één vraagfragment zijn.');
        const starts=await api(startsUrl);
        const numbers=(starts.candidates||[]).filter(item=>item.accepted&&!item.removed).map(item=>item.question_number);
        const covered=new Set(selections.filter(item=>item.type==='vraag').flatMap(item=>item.question_numbers));
        const missing=numbers.filter(number=>!covered.has(number));
        if(missing.length) throw new Error(`Nog geen vraagfragment geselecteerd voor vraag/vraagvragen: ${missing.join(', ')}.`);
        // Eerst alle bestaande autosaves afwachten; daarna worden selectie,
        // inhoudelijke review en workflowstatus serieel opgeslagen.
        clearTimeout(saveTimer);
        await saveChain;
        await api(stitchedReviewUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selections,reviewed:true})});
        await api(fragmentsReviewUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviewed_question_numbers:[...new Set(numbers)],reviewed_all_questions:true,boundary_overrides:[]})});
        await api(`/api/exams/${state.examId}/steps/${stepKey}/complete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviewed:true,reviewed_all_questions:true,reviewed_question_numbers:[...new Set(numbers)]})});
        await openWorkspace(state.examId);
      } catch(error) {
        completingStep = false;
        button.disabled = false;
        button.textContent = 'Fragmentcontrole goedkeuren en doorgaan';
        $('#stitchedMessage').textContent=error.message;
      }
    });
    render();
  } catch(error) {
    panel.innerHTML=`<h2>${escapeHtml(stageTitle)}</h2><p class="form-error">${escapeHtml(error.message)}</p>`;
  }
}

async function renderQuestionFragmentsStage(stepKey, documentType, startsStepKey, stageLabel, stageTitle) {
  if (documentType === 'opgaven') return renderStitchedOpgavenStage(stepKey, startsStepKey, stageLabel, stageTitle);
  const panel = $('#stagePanel');
  panel.innerHTML = '<p class="muted">Vraagfragmenten samenstellen…</p>';
  try {
    const result = await api(`/api/exams/${state.examId}/document-question-fragments/${documentType}`);
    const questions = result.questions;
    const cards = questions.map(question => {
      // Bij een CV wordt het samengestelde plaatje getoond, maar de grenzen
      // worden afgeleid uit de onderliggende originele paginadelen. Bij
      // opgaven en uitwerkbijlage zijn de zichtbare segmenten zelf leidend.
      const sourceSegments = question.source_segments?.length ? question.source_segments : question.segments;
      const firstClip = sourceSegments[0]?.pdf_clip || [0, 0, 0, 0];
      const lastClip = sourceSegments[sourceSegments.length - 1]?.pdf_clip || [0, 0, 0, 0];
      const startY = Number(firstClip[1] || 0).toFixed(2);
      const endY = Number(lastClip[3] || 0).toFixed(2);
      return `
      <article class="fragment-card" data-fragment-card="${question.question_number}">
        <div class="fragment-heading"><h3>Vraag ${question.question_number}</h3><span class="muted">Pagina ${question.first_page}${question.last_page !== question.first_page ? `–${question.last_page}` : ''}</span></div>
        <div class="fragment-images">
          ${question.segments.map((segment, segmentIndex) => {
            // De eerste en laatste pagina krijgen een sleepbare grenslijn.
            // De lijn beweegt op de daadwerkelijke afbeelding; de bijbehorende
            // y-waarde wordt direct omgerekend naar PDF-punten voor opslag.
            const clip = segment.pdf_clip || segment.boundary_info || null;
            const isFirst = segmentIndex === 0 && Boolean(clip);
            const isLast = segmentIndex === question.segments.length - 1 && Boolean(clip);
            const clipData = clip ? escapeHtml(JSON.stringify(clip)) : '';
            return `<figure><figcaption>Originele pagina ${segment.page_number}</figcaption><div class="boundary-image-wrap">
              <img loading="lazy" src="${segment.url}" alt="Fragment van vraag ${question.question_number}, pagina ${segment.page_number}">
              ${isFirst ? `<div class="drag-boundary drag-boundary-start" role="slider" tabindex="0" aria-label="Sleep om de bovengrens van vraag ${question.question_number} aan te passen" data-boundary-drag="start" data-question="${question.question_number}" data-clip="${clipData}"><span>Bovengrens · sleep</span></div>` : ''}
              ${isLast ? `<div class="drag-boundary drag-boundary-end" role="slider" tabindex="0" aria-label="Sleep om de ondergrens van vraag ${question.question_number} aan te passen" data-boundary-drag="end" data-question="${question.question_number}" data-clip="${clipData}"><span>Ondergrens · sleep</span></div>` : ''}
            </div></figure>`;
          }).join('')}
        </div>
        <details class="boundary-editor"><summary>Over de fragmentgrenzen</summary><p class="muted">Sleep de blauwe lijn op de afbeelding om de uitsnede aan te passen. De onderliggende PDF-coördinaten worden automatisch bijgewerkt.</p></details>
        <input type="hidden" data-fragment-start="${question.question_number}" data-initial="${startY}" value="${startY}">
        <input type="hidden" data-fragment-end="${question.question_number}" data-initial="${endY}" value="${endY}">
        <label class="review-warning"><input type="checkbox" data-fragment-reviewed="${question.question_number}" ${question.reviewed ? 'checked' : ''}> Ik heb het volledige fragment van vraag ${question.question_number} gecontroleerd.</label>
      </article>`;
    }).join('');

    panel.innerHTML = `
      <p class="eyebrow">${stageLabel}</p>
      <h2>${escapeHtml(stageTitle)}</h2>
      <p class="lead">De fragmenten zijn afgeleid van de goedgekeurde vraagstarts. Een vraag die over meerdere pagina's loopt, wordt als één vraag met meerdere opeenvolgende pagina-afbeeldingen getoond.</p>
      <div class="notice"><strong>${result.question_count} fragmenten voorgesteld.</strong> Controleer of iedere vraag volledig is opgenomen, inclusief afbeeldingen, tabellen en de onderste tekstregel. De uitsneden zijn afgeleiden; de oorspronkelijke PDF blijft ongewijzigd.</div>
      <div class="review-actions"><button class="quiet" id="adjustQuestionStarts" type="button">Vraagstarts / fragmentgrenzen aanpassen</button></div>
      ${cards}
      <label class="review-warning"><input type="checkbox" id="allFragmentsReviewed"> Ik heb alle vraagfragmenten volledig visueel gecontroleerd.</label>
      <div class="review-actions"><button class="primary" id="saveFragmentReview" type="button">Controle opslaan</button><button class="primary" id="completeFragmentReview" type="button" disabled>Vraagfragmenten goedkeuren en doorgaan</button></div>
      <p id="fragmentReviewMessage" class="form-error" role="status"></p>`;

    $('#adjustQuestionStarts').addEventListener('click', async () => {
      prepareStageApproval(panel);
      try {
        // Bewaar de bestaande startcorrecties, maar maak deze stap opnieuw
        // actief en verwijder afgeleide goedkeuringen die nu verouderd zijn.
        await api(`/api/exams/${state.examId}/steps/${startsStepKey}/reopen`, {method:'POST'});
        await openWorkspace(state.examId);
      } catch (error) { $('#fragmentReviewMessage').textContent = error.message; }
    });

    // Maak de grenslijnen met muis of touchscreen versleepbaar. De positie
    // wordt relatief aan de zichtbare afbeelding bepaald en daarna omgerekend
    // naar de PDF-puntcoördinaten die de server al gebruikt.
    document.querySelectorAll('[data-boundary-drag]').forEach(handle => {
      const questionNumber = Number(handle.dataset.question);
      const role = handle.dataset.boundaryDrag;
      const clip = JSON.parse(handle.dataset.clip);
      const input = document.querySelector(role === 'start'
        ? `[data-fragment-start="${questionNumber}"]`
        : `[data-fragment-end="${questionNumber}"]`);
      const wrapper = handle.closest('.boundary-image-wrap');
      const updateFromPointer = event => {
        const rect = wrapper.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
        let y;
        if (Array.isArray(clip)) {
          // Normale pagina-afbeelding: de hele zichtbare hoogte hoort bij één
          // PDF-uitsnede.
          y = Number(clip[1]) + ratio * (Number(clip[3]) - Number(clip[1]));
        } else if (role === 'start') {
          // Gestitcht CV: de bovengrens hoort bij de eerste bronpagina. Alleen
          // het deel van de samengestelde afbeelding dat die pagina beslaat,
          // wordt naar de y-coördinaat van die bronpagina omgerekend.
          const local = Math.max(0, Math.min(1, ratio * clip.total_height / clip.first_height));
          y = Number(clip.start_clip[1]) + local * (Number(clip.start_clip[3]) - Number(clip.start_clip[1]));
        } else {
          // De ondergrens hoort bij de laatste bronpagina van het CV-fragment.
          const lastPageTop = clip.total_height - clip.last_height;
          const local = Math.max(0, Math.min(1, (ratio * clip.total_height - lastPageTop) / clip.last_height));
          y = Number(clip.end_clip[1]) + local * (Number(clip.end_clip[3]) - Number(clip.end_clip[1]));
        }
        input.value = y.toFixed(2);
        handle.style.top = `${ratio * 100}%`;
        handle.style.bottom = 'auto';
        const card = handle.closest('[data-fragment-card]');
        const check = card.querySelector(`[data-fragment-reviewed="${questionNumber}"]`);
        if (check) check.checked = false;
      };
      handle.addEventListener('pointerdown', event => {
        event.preventDefault();
        handle.setPointerCapture(event.pointerId);
        updateFromPointer(event);
      });
      handle.addEventListener('pointermove', event => {
        if (handle.hasPointerCapture(event.pointerId)) updateFromPointer(event);
      });
      handle.addEventListener('pointerup', event => {
        if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
        // Na het verslepen direct de nieuwe PDF-grens als concept opslaan.
        input.dispatchEvent(new Event('change', {bubbles:true}));
      });
      handle.addEventListener('keydown', event => {
        if (!['ArrowUp','ArrowDown'].includes(event.key)) return;
        event.preventDefault();
        const delta = event.key === 'ArrowUp' ? -1 : 1;
        input.value = (Number(input.value) + delta).toFixed(2);
        let ratio;
        if (Array.isArray(clip)) {
          const range = Number(clip[3]) - Number(clip[1]);
          ratio = (Number(input.value) - Number(clip[1])) / range;
        } else if (role === 'start') {
          const range = Number(clip.start_clip[3]) - Number(clip.start_clip[1]);
          ratio = ((Number(input.value) - Number(clip.start_clip[1])) / range) * clip.first_height / clip.total_height;
        } else {
          const range = Number(clip.end_clip[3]) - Number(clip.end_clip[1]);
          ratio = (clip.total_height - clip.last_height + ((Number(input.value) - Number(clip.end_clip[1])) / range) * clip.last_height) / clip.total_height;
        }
        handle.style.top = `${Math.max(0,Math.min(100,ratio*100))}%`;
        handle.style.bottom = 'auto';
        input.dispatchEvent(new Event('change', {bubbles:true}));
      });
    });

    const reviewedNumbers = () => [...document.querySelectorAll('[data-fragment-reviewed]:checked')]
      .map(input => Number(input.dataset.fragmentReviewed));
    const allCheckboxes = () => [...document.querySelectorAll('[data-fragment-reviewed]')];
    const refreshComplete = () => {
      $('#completeFragmentReview').disabled = !$('#allFragmentsReviewed').checked
        || allCheckboxes().some(input => !input.checked);
    };
    allCheckboxes().forEach(input => input.addEventListener('change', refreshComplete));
    $('#allFragmentsReviewed').addEventListener('change', refreshComplete);
    refreshComplete();

    const collectBoundaries = () => [...document.querySelectorAll('[data-fragment-card]')].map(card => {
      const number = Number(card.dataset.fragmentCard);
      const start = card.querySelector(`[data-fragment-start="${number}"]`);
      const end = card.querySelector(`[data-fragment-end="${number}"]`);
      return {question_number:number, start_y:Number(start.value), end_y:Number(end.value),
        changed:Math.abs(Number(start.value)-Number(start.dataset.initial))>0.01 || Math.abs(Number(end.value)-Number(end.dataset.initial))>0.01};
    });
    const save = async () => {
      const boundaries = collectBoundaries();
      const changedNumbers = new Set(boundaries.filter(item=>item.changed).map(item=>item.question_number));
      // Een vraag waarvan de uitsnede wijzigt, kan niet met de oude visuele
      // goedkeuring door. Na opnieuw renderen moet die vraag opnieuw worden bekeken.
      for (const number of changedNumbers) {
        const check = document.querySelector(`[data-fragment-reviewed="${number}"]`);
        if (check) check.checked = false;
      }
      const reviewed = reviewedNumbers();
      return {saved:await api(`/api/exams/${state.examId}/document-question-fragments/${documentType}/review`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({reviewed_question_numbers:reviewed,
          reviewed_all_questions:$('#allFragmentsReviewed').checked && changedNumbers.size===0,
          boundary_overrides:boundaries.map(({question_number,start_y,end_y})=>({question_number,start_y,end_y}))})
      }), changedNumbers};
    };
    bindStageAutoSave(panel, save, '#fragmentReviewMessage');
    $('#saveFragmentReview').addEventListener('click', async () => {
      try {
        const {saved,changedNumbers} = await save();
        if (changedNumbers.size) {
          $('#fragmentReviewMessage').textContent = `Grenzen van ${[...changedNumbers].map(n=>`vraag ${n}`).join(', ')} opgeslagen. De nieuwe fragmenten worden opnieuw gerenderd; controleer ze daarna opnieuw.`;
          await openWorkspace(state.examId);
          return;
        }
        $('#fragmentReviewMessage').textContent = `${saved.reviewed_count} van ${saved.expected_count} vraagfragmenten gecontroleerd. Conceptreview opgeslagen.`;
      } catch (error) { $('#fragmentReviewMessage').textContent = error.message; }
    });
    $('#completeFragmentReview').addEventListener('click', async () => {
      try {
        const {saved,changedNumbers} = await save();
        if (changedNumbers.size) {
          $('#fragmentReviewMessage').textContent = 'De gewijzigde grenzen zijn opgeslagen. Controleer eerst de opnieuw gerenderde fragmenten.';
          await openWorkspace(state.examId);
          return;
        }
        if (!saved.complete) throw new Error('Niet alle vraagfragmenten zijn gecontroleerd.');
        await api(`/api/exams/${state.examId}/steps/${stepKey}/complete`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({reviewed:true, reviewed_all_questions:true,
            reviewed_question_numbers:saved.reviewed_count})
        });
        await openWorkspace(state.examId);
      } catch (error) { $('#fragmentReviewMessage').textContent = error.message; }
    });
  } catch (error) {
    panel.innerHTML = `<h2>Vraagfragmenten controleren</h2><p class="form-error">${escapeHtml(error.message)}</p>`;
  }
}

/* De analysefase gebruikt het volledige vraagfragment als visuele bron.
   Tekstlaagherkenning levert alleen voorlopige suggesties voor type, score en
   antwoordopties; elk veld blijft door de docent aanpasbaar en moet per vraag
   expliciet worden gecontroleerd voordat de fase kan worden afgerond. */
async function renderQuestionAnalysisStage() {
  const panel = $('#stagePanel');
  panel.innerHTML = '<p class="muted">Vraagtypen en antwoordopties analyseren…</p>';
  try {
    const result = await api(`/api/exams/${state.examId}/question-analysis`);
    const questionCards = result.questions.map(question => {
      const optionText = question.options.map(option => `${option.letter}. ${option.text}`).join('\n');
      return `
        <article class="analysis-card" data-analysis-card="${question.question_number}">
          <div class="fragment-heading"><h3>Vraag ${question.question_number}</h3><span class="muted">Voorstel: ${escapeHtml(question.question_type)}</span></div>
          <div class="fragment-images">
            ${question.segments.map(segment => `<figure><figcaption>Pagina ${segment.page_number}</figcaption><img loading="lazy" src="${segment.url}" alt="Vraag ${question.question_number}, pagina ${segment.page_number}"></figure>`).join('')}
          </div>
          <div class="analysis-fields">
            <label>Vraagtype
              <select data-analysis-type="${question.question_number}">
                <option value="meerkeuze" ${question.question_type === 'meerkeuze' ? 'selected' : ''}>Meerkeuze</option>
                <option value="gesloten" ${question.question_type === 'gesloten' ? 'selected' : ''}>Gesloten antwoord</option>
                <option value="open" ${question.question_type === 'open' ? 'selected' : ''}>Open vraag</option>
                <option value="onbekend" ${question.question_type === 'onbekend' ? 'selected' : ''}>Nog onbekend</option>
              </select>
            </label>
            <label>Maximumscore (punten)
              <input type="number" min="0" max="20" step="1" value="${question.max_points ?? ''}" placeholder="Nog bepalen" data-analysis-points="${question.question_number}">
            </label>
          </div>
          <label class="analysis-options-label">Antwoordopties (één per regel, bijvoorbeeld A. …)
            <textarea rows="4" data-analysis-options="${question.question_number}">${escapeHtml(optionText)}</textarea>
          </label>
          <p class="analysis-reason">Type: ${escapeHtml(question.type_reason)} Score: ${escapeHtml(question.points_reason)}</p>
          ${question.closed_answer_form ? `<p class="analysis-reason closed-answer-form"><strong>Gesloten antwoordvorm:</strong> ${escapeHtml(question.closed_answer_form)}</p>` : ''}
          <details class="analysis-text"><summary>Tekstlaag uit dit fragment (hulpmiddel, niet leidend)</summary><pre>${escapeHtml(question.extracted_text || 'Geen selecteerbare tekstlaag aangetroffen. Controleer de afbeelding.')}</pre></details>
          <label class="review-warning"><input type="checkbox" data-analysis-reviewed="${question.question_number}" ${question.reviewed ? 'checked' : ''}> Ik heb vraag ${question.question_number}, het vraagtype, de maximumscore en eventuele antwoordopties visueel gecontroleerd.</label>
        </article>`;
    }).join('');

    panel.innerHTML = `
      <p class="eyebrow">FASE 2 · OPGAVENDOCUMENT</p>
      <h2>Vraagtype, punten en antwoordopties</h2>
      <p class="lead">Per vraag staat het volledige fragment uit de oorspronkelijke PDF. De automatische suggesties zijn hulpmiddelen: controleer de afbeelding en corrigeer het vraagtype, de maximumscore en de antwoordopties waar nodig.</p>
      <div class="notice"><strong>${result.question_count} vragen</strong> klaar voor inhoudelijke controle. Als het puntenaantal niet expliciet uit de vraag blijkt, blijft het veld leeg in plaats van dat er een score wordt gegokt.</div>
      ${questionCards}
      <div class="review-actions"><button class="primary" id="saveQuestionAnalysis" type="button">Controle opslaan</button><button class="primary" id="completeQuestionAnalysis" type="button" disabled>Vraaganalyse goedkeuren en doorgaan</button></div>
      <p id="questionAnalysisMessage" class="form-error" role="status"></p>`;

    const cards = [...document.querySelectorAll('[data-analysis-card]')];
      prepareStageApproval(panel);
    const reviewedInputs = () => [...document.querySelectorAll('[data-analysis-reviewed]')];
    const refreshComplete = () => {
      $('#completeQuestionAnalysis').disabled = reviewedInputs().length !== result.question_count
        || reviewedInputs().some(input => !input.checked);
    };
    reviewedInputs().forEach(input => input.addEventListener('change', refreshComplete));
    refreshComplete();

    const collect = () => cards.map(card => {
      const number = Number(card.dataset.analysisCard);
      const rawPoints = card.querySelector(`[data-analysis-points="${number}"]`).value.trim();
      const optionsText = card.querySelector(`[data-analysis-options="${number}"]`).value;
      const options = optionsText.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map((line, index) => {
        const match = line.match(/^([A-E])[.)]\s*(.*)$/i);
        return match ? {letter:match[1].toUpperCase(), text:match[2].trim()}
          : {letter:'ABCDE'[index] || 'E', text:line};
      });
      return {
        question_number:number,
        question_type:card.querySelector(`[data-analysis-type="${number}"]`).value,
        max_points:rawPoints === '' ? null : Number(rawPoints),
        options,
        reviewed:card.querySelector(`[data-analysis-reviewed="${number}"]`).checked
      };
    });
    const save = async () => api(`/api/exams/${state.examId}/question-analysis/review`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({questions:collect()})
    });
    bindStageAutoSave(panel, save, '#questionAnalysisMessage');
    $('#saveQuestionAnalysis').addEventListener('click', async () => {
      try {
        const saved = await save();
        $('#questionAnalysisMessage').textContent = `${saved.reviewed_count} van ${result.question_count} vragen gecontroleerd. Conceptreview opgeslagen.`;
      } catch (error) { $('#questionAnalysisMessage').textContent = error.message; }
    });
    $('#completeQuestionAnalysis').addEventListener('click', async () => {
      try {
        const saved = await save();
        if (!saved.complete) throw new Error('Controleer eerst alle vragen.');
        await api(`/api/exams/${state.examId}/steps/opgaven_analyse/complete`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({reviewed:true, reviewed_all_questions:true, reviewed_count:saved.reviewed_count})
        });
        await openWorkspace(state.examId);
      } catch (error) { $('#questionAnalysisMessage').textContent = error.message; }
    });
  } catch (error) {
    panel.innerHTML = `<h2>Vraagtype, punten en antwoordopties</h2><p class="form-error">${escapeHtml(error.message)}</p>`;
  }
}
