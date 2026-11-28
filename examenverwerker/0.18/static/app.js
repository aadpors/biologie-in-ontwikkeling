/*
 * Front-end voor de geïntegreerde examenwerkruimte.
 * Alle blijvende gegevens worden via de API opgeslagen; deze JavaScript-code
 * bewaart alleen de tijdelijke selectie van het huidige scherm. Daardoor
 * verdwijnen metadata of voortgang niet wanneer de browser wordt vernieuwd.
 */
const state = { examId: null, exam: null, workflow: [] };
// Houd de gekozen PDF-bestanden los van de native file-input bij; zo kan de gebruiker
// meerdere selectierondes combineren en afzonderlijke bestanden weer verwijderen.
let selectedImportFiles = [];

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
  // 'input' saves while a field is still focused; 'change' remains the fallback
  // for controls whose final value is committed on blur. The completion hook
  // below cancels either pending debounce and flushes the latest snapshot.
  panel.addEventListener('input', schedule);
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
    panel.removeEventListener('input', schedule);
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
    <article class="exam-row"><div class="doc-icon">PDF</div><div><strong>${escapeHtml(exam.title)}</strong><p>${exam.published ? 'Gepubliceerd in examenbibliotheek' : (exam.confirmed ? 'Metadata bevestigd · nog niet gepubliceerd' : 'Metadata nog te bevestigen')} · geïmporteerd ${new Date(exam.created_at + 'Z').toLocaleDateString('nl-NL')}</p></div><button class="quiet" data-open="${exam.id}">Open werkruimte →</button>${exam.published ? `<button class="quiet" data-reopen-published="${exam.id}">Publicatie bewerken</button>` : ''}</article>
  `).join('') : '<p class="muted">Er zijn nog geen examens geïmporteerd.</p>';
  document.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', () => openWorkspace(button.dataset.open)));
  // Een gepubliceerd examen kan via een expliciete actie worden heropend.
  // De server houdt de vorige publicatie als immutable snapshot beschikbaar.
  document.querySelectorAll('[data-reopen-published]').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      await api(`/api/exams/${button.dataset.reopenPublished}/reopen-published`, {method:'POST'});
      await openWorkspace(button.dataset.reopenPublished);
    } catch (error) {
      button.disabled = false;
      alert(error.message);
    }
  }));
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/* Toon een eigen, toegankelijke dialoog voor beslissingen rond importeren.
   De Promise geeft uitsluitend de expliciete waarde van de gekozen knop terug.
   Escape en sluiten leveren een lege waarde op en voeren dus nooit een
   destructieve actie uit. */
function showImportDialog({title, message, actions}) {
  const dialog = $('#importDecisionDialog');
  dialog.innerHTML = `
    <div class="import-dialog-content">
      <p class="eyebrow">EXAMEN IMPORTEREN</p>
      <h2 id="importDialogTitle">${escapeHtml(title)}</h2>
      <p>${escapeHtml(message)}</p>
      <div class="import-dialog-actions">
        ${actions.map(action => `
          <button type="button"
            class="${action.danger ? 'danger' : action.primary ? 'primary' : 'quiet'}"
            data-dialog-value="${escapeHtml(action.value)}">${escapeHtml(action.label)}</button>
        `).join('')}
      </div>
    </div>`;
  return new Promise(resolve => {
    // Een dialoog die al openstaat wijst op een programmeerfout; voorkom dat
    // een tweede beslissing stilzwijgend de eerste dialoog overschrijft.
    if (dialog.open) {
      resolve('');
      return;
    }
    const finish = () => resolve(dialog.returnValue || '');
    dialog.addEventListener('close', finish, {once:true});
    dialog.querySelectorAll('[data-dialog-value]').forEach(button => {
      button.addEventListener('click', () => dialog.close(button.dataset.dialogValue));
    });
    dialog.showModal();
  });
}

// Bepaal de bundelsleutel op basis van de documentcode aan het einde van de
// bestandsnaam. Opgaven, CV, uitwerkbijlage en aanvulling met dezelfde basis
// horen bij één examen; verschillende bases worden aparte examenimports.
function importBundleKey(file) {
  let stem = file.name.replace(/\\.pdf$/i, '').trim();
  stem = stem.replace(/-c-a[\\w.-]*$/i, '');
  stem = stem.replace(/-(?:o|u|c|a)$/i, '');
  return stem.toLocaleLowerCase('nl');
}

// Toon de selectie vóór importeren. Verwijderen raakt alleen de browserselectie;
// er is nog niets naar de examenbibliotheek geüpload.
function renderImportSelection() {
  const target = $('#selectedImportFiles');
  if (!target) return;
  if (!selectedImportFiles.length) {
    target.innerHTML = '<p class="muted">Nog geen PDF-bestanden geselecteerd.</p>';
    $('#importSubmit').disabled = true;
    return;
  }
  const groups = new Map();
  selectedImportFiles.forEach((file, index) => {
    const key = importBundleKey(file);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({file, index});
  });
  target.innerHTML = [...groups.entries()].map(([key, entries], groupIndex) => `
    <section class="import-bundle">
      <div class="section-heading"><strong>Examenbundel ${groupIndex + 1}</strong><span class="muted">${entries.length} bestand(en)</span></div>
      <ul class="selected-file-list">${entries.map(({file,index}) => `
        <li><span>${escapeHtml(file.name)} <small>(${(file.size / 1024 / 1024).toFixed(1)} MB)</small></span>
          <button type="button" class="quiet" data-remove-import-file="${index}" aria-label="Verwijder ${escapeHtml(file.name)}">Verwijderen</button>
        </li>`).join('')}</ul>
    </section>`).join('');
  target.querySelectorAll('[data-remove-import-file]').forEach(button => {
    button.addEventListener('click', () => {
      selectedImportFiles.splice(Number(button.dataset.removeImportFile), 1);
      renderImportSelection();
    });
  });
  $('#importSubmit').disabled = false;
}

// Selecteer in meerdere rondes: nieuwe bestanden worden toegevoegd in plaats
// van de vorige selectie te vervangen. Dubbelen worden op naam en bestandsgrootte
// tegengehouden; de inhoudelijke SHA-controle blijft op de server plaatsvinden.
$('#pdfFiles').addEventListener('change', event => {
  const incoming = [...event.target.files];
  incoming.forEach(file => {
    const duplicate = selectedImportFiles.some(existing =>
      existing.name === file.name && existing.size === file.size && existing.lastModified === file.lastModified
    );
    if (!duplicate) selectedImportFiles.push(file);
  });
  event.target.value = '';
  renderImportSelection();
});

async function uploadImportBundle(files) {
  const form = new FormData();
  files.forEach(file => form.append('files', file));
  try {
    return await api('/api/exams/import', {method:'POST', body:form});
  } catch (error) {
    // De bestaande importbeslissing blijft per examenbundel afzonderlijk:
    // nooit wordt een tweede examen stilzwijgend als vervanging behandeld.
    const detail = error.detail || null;
    if (detail?.code !== 'duplicate_exam') throw error;
    const action = await showImportDialog({
      title: 'Dit examen is al geïmporteerd',
      message: `"${detail.title}" staat al in de examenbibliotheek. Open de bestaande verwerking of start deze bundel opnieuw.`,
      actions: [
        {value:'continue', label:'Bestaande verwerking openen', primary:true},
        {value:'restart', label:'Opnieuw importeren'},
        {value:'cancel', label:'Deze bundel overslaan'}
      ]
    });
    if (action === 'continue') return {existing_exam_id: detail.exam_id};
    if (action !== 'restart') return {skipped:true};
    const confirmation = await showImportDialog({
      title:'Bestaande verwerking vervangen?',
      message:'De bestaande verwerking en alle bijbehorende correcties worden definitief verwijderd. Alleen deze examenbundel wordt opnieuw geïmporteerd.',
      actions:[
        {value:'replace',label:'Deze import vervangen',danger:true},
        {value:'back',label:'Terug'}
      ]
    });
    if (confirmation !== 'replace') return {skipped:true};
    form.append('replace_exam_id', detail.exam_id);
    return await api('/api/exams/import', {method:'POST', body:form});
  }
}

$('#importForm').addEventListener('submit', async event => {
  event.preventDefault();
  $('#importError').textContent = '';
  if (!selectedImportFiles.length) return;
  const submit = $('#importSubmit');
  submit.disabled = true;
  submit.textContent = 'Examenbundels importeren…';
  try {
    const groups = new Map();
    selectedImportFiles.forEach(file => {
      const key = importBundleKey(file);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(file);
    });
    const completed = [];
    const skipped = [];
    let processed = 0;
    // Bundels worden sequentieel aangemaakt om piekgeheugen te beperken en
    // om elke upload als zelfstandige, herstelbare examenimport af te handelen.
    // Verwijder een bundel direct uit de selectie zodra deze is geïmporteerd
    // of bewust overgeslagen. Als een latere bundel faalt, kan de gebruiker
    // daardoor veilig opnieuw proberen zonder eerdere examens dubbel te doen.
    for (const [key, files] of groups) {
      submit.textContent = `Importeren: ${processed + 1} van ${groups.size}…`;
      const result = await uploadImportBundle(files);
      if (result?.existing_exam_id) completed.push(result.existing_exam_id);
      else if (result?.exam_id) completed.push(result.exam_id);
      else skipped.push(files.map(file => file.name).join(', '));

      const processedFiles = new Set(files);
      selectedImportFiles = selectedImportFiles.filter(file => !processedFiles.has(file));
      processed += 1;
      renderImportSelection();
    }
    if (completed.length === 1 && groups.size === 1) {
      await openWorkspace(completed[0]);
    } else {
      await showLibrary();
      const summary = `${completed.length} examen(s) toegevoegd aan de bibliotheek.` +
        (skipped.length ? ` Overgeslagen bundels: ${skipped.join(' | ')}.` : '');
      $('#importError').textContent = summary;
    }
  } catch (error) {
    $('#importError').textContent = error.message;
    // De selectie blijft staan, zodat een mislukte import eenvoudig opnieuw
    // kan worden geprobeerd zonder alle PDF's opnieuw te selecteren.
  } finally {
    submit.disabled = selectedImportFiles.length === 0;
    submit.textContent = 'Importeren en verwerken';
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
    if (['supplement_starts', 'supplement_fragments'].includes(next?.key) && !examHasDocumentType('aanvulling_correctievoorschrift')) {
      await api(`/api/exams/${examId}/skip-optional-supplement`, {method:'POST'});
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
  // Een eerdere documentstap mag de extra leesruimte van de CV-aanvulling
  // niet onbedoeld meenemen. De betreffende klasse wordt hieronder alleen
  // opnieuw aangezet wanneer juist die fragmentstap wordt geopend.
  stagePanel?.classList.remove('supplement-fragments-stage', 'supplement-merge-stage');
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
        'De opgeslagen correcties blijven behouden. Vervolgstappen worden alleen ' +
        'opnieuw ter controle aangeboden als je de inhoud daadwerkelijk wijzigt.'
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
  else if (next?.key === 'supplement_starts') renderQuestionStartsStage('supplement_starts', 'aanvulling_correctievoorschrift', 'FASE 5 · AANVULLING CORRECTIEVOORSCHRIFT', 'Vraagstarts CV-aanvulling');
  else if (next?.key === 'supplement_fragments') renderStitchedOpgavenStage('supplement_fragments', 'supplement_starts', 'FASE 5 · AANVULLING CORRECTIEVOORSCHRIFT', 'Fragmenten CV-aanvulling', 'aanvulling_correctievoorschrift');
  else if (next?.key === 'cv_aanvulling') renderCvSupplementStage();
  else if (next?.key === 'antwoorden') renderAnswersStage();
  else if (next?.key === 'relaties') renderRelationsStage();
  else if (next?.key === 'snippets') renderSnippetsStage();
  else if (next?.key === 'eindcontrole') renderFinalReviewStage();
  else if (next?.key === 'publicatie') renderPublicationStage();
  else renderStageOverview(next, completed);

  // Iedere nieuwe workflowstap begint bovenaan het scherm. Dit gebeurt
  // centraal na het renderen, zodat alle routes (afronden, heropenen en
  // opnieuw laden) hetzelfde navigatiegedrag gebruiken.
  window.scrollTo(0, 0);
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
    <div class="document-list">${exam.documents.map(doc => `<div class="document-card"><strong>${escapeHtml(doc.filename)}</strong><small>${doc.page_count} pagina's · ${doc.sha256.slice(0,12)}…</small><div class="document-actions"><button class="quiet" data-preview="${doc.id}">Eerste pagina bekijken</button><button class="quiet danger" data-remove-document="${doc.id}" ${exam.documents.length <= 1 ? 'disabled title="Het laatste bestand kan niet worden verwijderd"' : ''}>Verwijderen</button></div></div>`).join('')}</div>
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

  // Verwijder een PDF rechtstreeks uit deze importwerkruimte. Na succesvolle
  // verwijdering wordt fase 1 opnieuw geladen met de bijgewerkte documentlijst.
  document.querySelectorAll('[data-remove-document]').forEach(button => button.addEventListener('click', async () => {
    const documentId = Number(button.dataset.removeDocument);
    const doc = state.exam.documents.find(item => Number(item.id) === documentId);
    if (!doc || state.exam.documents.length <= 1) return;
    if (!confirm('Bronbestand "' + doc.filename + '" uit deze werkruimte verwijderen?')) return;
    button.disabled = true;
    try {
      await api('/api/exams/' + state.examId + '/documents/' + documentId, {method:'DELETE'});
      await openWorkspace(state.examId);
    } catch (error) {
      const errorBox = $('#metadataError');
      if (errorBox) errorBox.textContent = error.message;
      button.disabled = false;
    }
  }));

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
  // Dit is de stap waarin de docent de herkende tekst uit ieder CV-fragment
  // leest. Geef juist dit leesvenster extra hoogte; de eerdere aanpassing aan
  // de afbeeldingviewport raakte niet het tekstvenster waar het om gaat.
  panel.classList.add('supplement-merge-stage');
  panel.innerHTML = '<p class="muted">Goedgekeurde fragmenten van de CV-aanvulling laden…</p>';
  try {
    const result = await api(`/api/exams/${state.examId}/cv-supplement`);
    if (result.not_required) {
      panel.innerHTML = `<p class="eyebrow">FASE 5 · AANVULLING CORRECTIEVOORSCHRIFT</p><h2>Geen aanvulling aanwezig</h2><p class="lead">Er is geen aanvullingsdocument geïmporteerd. Het oorspronkelijke correctievoorschrift blijft ongewijzigd.</p><button class="primary" id="confirmNoSupplement">Geen aanvulling bevestigen en doorgaan</button><p id="supplementMessage" class="form-error" role="status"></p>`;
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
    const fragments = result.fragments || [];
    const saved = new Map((result.fragments || []).map(item => [item.selection_id, item]));
    if (!fragments.length) {
      panel.innerHTML = '<h2>Geen vraagfragmenten beschikbaar</h2><p class="form-error">Controleer eerst de vraagstarts en fragmentgrenzen van de aanvulling.</p>';
      return;
    }
    panel.innerHTML = `<p class="eyebrow">FASE 5 · AANVULLING CORRECTIEVOORSCHRIFT</p>
      <h2>Aanvulling per fragment samenvoegen</h2>
      <p class="lead">De pagina’s zijn in de vorige stappen verdeeld in afzonderlijke vraagfragmenten. Beoordeel ieder fragment. Alleen de hier goedgekeurde uitsneden worden straks bij de antwoordherkenning getoond; de volledige PDF-pagina wordt niet meer ingevoegd.</p>
      <div class="notice">${fragments.length} fragmenten · ${escapeHtml(result.document.filename)} · bron-PDF blijft ongewijzigd.</div>
      ${fragments.map((fragment, index) => {
        const decision = saved.get(fragment.selection_id) || {};
        const number = (fragment.question_numbers || [fragment.question_number]).filter(Boolean);
        const urls = (fragment.segments || []).map(segment => segment.url).filter(Boolean);
        return `<article class="analysis-card" data-supplement-fragment="${escapeHtml(fragment.selection_id)}">
          <h3>Fragment ${index + 1} · vraag ${number.join(', ')}</h3>
          ${urls.map(url => `<img class="fragment-image" loading="lazy" alt="Uitgesneden CV-aanvulling voor vraag ${number.join(', ')}" src="${escapeHtml(url)}">`).join('')}
          <label>Verwerking<select data-supplement-action="${escapeHtml(fragment.selection_id)}">
            <option value="toevoegen" ${decision.action==='toevoegen'?'selected':''}>Toevoegen aan het bestaande CV</option>
            <option value="vervangen" ${decision.action==='vervangen'?'selected':''}>Bestaand onderdeel vervangen</option>
            <option value="handmatig" ${decision.action==='handmatig'?'selected':''}>Handmatig beoordelen in stap 10</option>
            <option value="negeren" ${decision.action==='negeren'?'selected':''}>Niet verwerken</option>
          </select></label>
          <details class="analysis-text"><summary>Herkenbare tekst uit dit fragment</summary><pre>${escapeHtml(fragment.extracted_text || 'Geen selecteerbare tekstlaag; beoordeel de afbeelding.')}</pre></details>
          <label class="review-warning"><input type="checkbox" data-supplement-reviewed="${escapeHtml(fragment.selection_id)}" ${decision.reviewed?'checked':''}> Ik heb dit fragment en de verwerkingskeuze gecontroleerd.</label>
        </article>`;
      }).join('')}
      <div class="review-actions"><button class="primary" id="saveSupplement" type="button">Controle opslaan</button><button class="primary" id="completeSupplement" type="button" disabled>Aanvulling beoordelen en doorgaan</button></div><p id="supplementMessage" class="form-error" role="status"></p>`;
    prepareStageApproval(panel);
    const cards = [...panel.querySelectorAll('[data-supplement-fragment]')];
    const checks = [...panel.querySelectorAll('[data-supplement-reviewed]')];
    const refresh = () => { $('#completeSupplement').disabled = checks.some(input => !input.checked); };
    checks.forEach(input => input.addEventListener('change', refresh));
    refresh();
    const collect = () => cards.map(card => ({
      selection_id: card.dataset.supplementFragment,
      action: card.querySelector('[data-supplement-action]').value,
      reviewed: card.querySelector('[data-supplement-reviewed]').checked
    }));
    const save = () => api(`/api/exams/${state.examId}/cv-supplement/review`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({fragments:collect()})
    });
    bindStageAutoSave(panel, save, '#supplementMessage');
    $('#saveSupplement').addEventListener('click', async () => {
      try { const savedResult = await save(); $('#supplementMessage').textContent = `${savedResult.reviewed_count} van ${savedResult.fragment_count} fragmenten gecontroleerd. Concept opgeslagen.`; }
      catch(error) { $('#supplementMessage').textContent = error.message; }
    });
    let completing = false;
    $('#completeSupplement').addEventListener('click', async () => {
      if (completing) return;
      completing = true;
      const button = $('#completeSupplement');
      button.disabled = true;
      try {
        const savedResult = panel._stageAutoSaveFlush ? await panel._stageAutoSaveFlush() : await save();
        if (!savedResult.complete) throw new Error('Controleer eerst alle aanvullingsfragmenten.');
        await api(`/api/exams/${state.examId}/steps/cv_aanvulling/complete`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({reviewed:true, reviewed_all_fragments:true})
        });
        await openWorkspace(state.examId);
      } catch(error) {
        completing = false;
        refresh();
        $('#supplementMessage').textContent = error.message;
      }
    });
  } catch (error) {
    panel.innerHTML = `<h2>Aanvulling correctievoorschrift</h2><p class="form-error">${escapeHtml(error.message)}</p>`;
  }
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
      ${result.questions.map(q => `<article class="analysis-card" data-answer-card="${q.question_number}"><div class="card-heading"><h3>Vraag ${q.question_number}</h3><span class="status-pill">${escapeHtml(q.confidence)} zekerheid</span></div><p class="analysis-reason">${escapeHtml(q.reason)} · Maximumscore CV: ${q.cv_max_points ?? 'onbekend'} · Opgaven: ${q.opgaven_max_points ?? 'onbekend'}${q.points_reason ? ' · ' + escapeHtml(q.points_reason) : ''}${q.points_match===false?' · SCORES VERSCHILLEN':''}</p>${q.segments.map(seg=>`<img class="fragment-image" loading="lazy" alt="Correctievoorschrift vraag ${q.question_number}" src="${escapeHtml(seg.url)}">`).join('')}${(q.supplement_fragments||[]).map(fragment=>`<div class="notice">CV-aanvulling · ${escapeHtml(fragment.action)}</div>${(fragment.urls||[]).map(url=>`<img class="fragment-image" loading="lazy" alt="CV-aanvulling bij vraag ${q.question_number}" src="${escapeHtml(url)}">`).join('')}`).join('')}<div class="analysis-fields"><label>Antwoordvorm<select data-answer-kind="${q.question_number}"><option value="meerkeuze" ${q.answer_kind==='meerkeuze'?'selected':''}>Meerkeuze</option><option value="gesloten" ${q.answer_kind==='gesloten'?'selected':''}>Gesloten antwoord</option><option value="open" ${q.answer_kind==='open'?'selected':''}>Open antwoord / beoordelingscriteria</option><option value="handmatig" ${q.answer_kind==='handmatig'?'selected':''}>Handmatig bepalen</option></select></label></div><label class="answer-text-field">Antwoord of beoordelingscriteria<textarea class="answer-textarea" rows="2" data-answer-text="${q.question_number}">${escapeHtml(q.answer_text)}</textarea></label><label class="review-warning"><input type="checkbox" data-answer-reviewed="${q.question_number}" ${q.reviewed?'checked':''}> Ik heb het antwoord van vraag ${q.question_number} aan de hand van het CV-fragment gecontroleerd.</label></article>`).join('')}
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
    const collect=()=>cards.map(card=>{const n=Number(card.dataset.answerCard);const detected=result.questions.find(question=>question.question_number===n)||{};return {question_number:n,answer_kind:card.querySelector(`[data-answer-kind="${n}"]`).value,answer_text:card.querySelector(`[data-answer-text="${n}"]`).value,cv_max_points:detected.cv_max_points,opgaven_max_points:detected.opgaven_max_points,reviewed:card.querySelector(`[data-answer-reviewed="${n}"]`).checked};});
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
        <span>${result.uncertain_analysis.length ? 'Onzekere vraaganalyse: '+result.uncertain_analysis.join(', ') : 'Vraagtypen en scores zijn bepaald'}</span>
        <span>${result.uncertain_answers.length ? 'Handmatige/onzekere antwoorden: '+result.uncertain_answers.join(', ') : 'Antwoorden zijn ingevuld'}</span>
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
      ${result.uncertain_analysis.length ? `
        <section class="analysis-card">
          <h3>Onzekere vraaganalyse</h3>
          <p>Bij vraag ${result.uncertain_analysis.join(', ')} is het vraagtype nog onbekend of ontbreekt een maximumscore. Dit is niet automatisch een fout, maar verdient aandacht in stap 4.</p>
          <button class="quiet" type="button" id="repairQuestionAnalysis">Vraaganalyse bekijken</button>
        </section>` : ''}
      ${result.uncertain_answers.length ? `
        <section class="analysis-card">
          <h3>Onzekere of handmatige antwoorden</h3>
          <p>Bij vraag ${result.uncertain_answers.join(', ')} is de antwoordvorm handmatig bepaald of staat nog geen antwoordtekst. Controleer of dit bewust zo is.</p>
          <button class="quiet" type="button" id="repairUncertainAnswers">Antwoorden bekijken</button>
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
    let completingRelations=false;
    $('#completeRelations').addEventListener('click',async()=>{
      const button=$('#completeRelations');
      if(completingRelations) return;
      completingRelations=true;
      button.disabled=true;
      button.textContent='Controleren en afronden…';
      try {
        // Wacht eerst op een eventuele autosave van de laatste toelichting.
        // Zo kan een vertraagde conceptopslag de afgeronde stap niet terugzetten.
        const saved=panel._stageAutoSaveFlush
          ? await panel._stageAutoSaveFlush()
          : await save();
        if(!saved.complete) throw new Error('Los eerst de getoonde afwijkingen op.');
        await api(`/api/exams/${state.examId}/steps/relaties/complete`,{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({reviewed:true,reviewed_all_questions:true})
        });
        await openWorkspace(state.examId);
      } catch(error) {
        completingRelations=false;
        button.textContent='Controles afronden en doorgaan';
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
    $('#repairUncertainAnswers')?.addEventListener('click',async()=>{
      try {
        await api(`/api/exams/${state.examId}/steps/antwoorden/reopen`,{method:'POST'});
        await openWorkspace(state.examId);
      } catch(error) { $('#relationsMessage').textContent=error.message; }
    });
    $('#repairQuestionAnalysis')?.addEventListener('click',async()=>{
      try {
        await api(`/api/exams/${state.examId}/steps/opgaven_analyse/reopen`,{method:'POST'});
        await openWorkspace(state.examId);
      } catch(error) { $('#relationsMessage').textContent=error.message; }
    });
  } catch(error) {
    panel.innerHTML=`<h2>Integriteitscontrole</h2><p class="form-error">${escapeHtml(error.message)}</p>`;
  }
}

/* De snippetfase maakt contextkandidaten los van de vraagfragmenten. Een
   contextbereik wordt alleen als voorstel ingevuld; de docent controleert en
   corrigeert de reeks vragen waarop de context van toepassing is. */
async function renderSnippetsStage() {
  const panel = $('#stagePanel');
  panel.innerHTML = '<p class="muted">Contexten en definitieve snippets voorbereiden…</p>';

  try {
    const result = await api(`/api/exams/${state.examId}/snippets`);

    // De fragmenten zijn inhoudelijk al afgebakend in de eerdere stappen.
    // Hier worden alleen contextbereiken gecontroleerd en de volledige set
    // visueel beoordeeld. Er zijn daarom geen losse controlevinkjes nodig.
    // Maak van contexten en vragen één chronologische lijst.
    // Contexten worden vóór de eerste vraag geplaatst waarvoor ze gelden.
    // Bij meerdere contexten die bij dezelfde vraag beginnen, tonen we eerst
    // de breedste context (bijvoorbeeld 1–6), daarna de specifiekere (1–2).
    // Vervolgens komt de vraag zelf; op de volgende vraagpositie kunnen weer
    // nieuwe contextblokken volgen. Dit voorkomt dat contexten los bovenaan
    // worden verzameld of telkens binnen iedere vraag worden herhaald.
    const contextHtml = context => `
      <article class="analysis-card" data-context-card="${escapeHtml(context.id)}">
        <div class="card-heading">
          <h3>Context · pagina ${context.page_number}</h3>
          <span class="muted">Voorstel: vraag ${context.suggested_from_question}–${context.to_question}${context.learning_adjusted ? ` · leerfunctie aangepast (${context.learning_correction.examples} eerdere correcties)` : ""}</span>
        </div>
        <img class="fragment-image" loading="lazy" src="${escapeHtml(context.url)}" alt="Contextfragment op pagina ${context.page_number}">
        <p class="analysis-reason">${escapeHtml(context.label)}</p>
        <div class="analysis-fields">
          <label>Contexttitel
            <input type="text" maxlength="200" data-context-title="${escapeHtml(context.id)}" value="${escapeHtml(context.title || context.label || '')}" placeholder="Titel van deze context">
          </label>
          <label>Vanaf vraag
            <input type="number" min="1" max="60" data-context-from="${escapeHtml(context.id)}" value="${context.from_question}">
          </label>
          <label>Tot en met vraag
            <input type="number" min="1" max="60" data-context-to="${escapeHtml(context.id)}" value="${context.to_question}">
          </label>
        </div>
        <details class="analysis-text">
          <summary>Tekstlaag (hulpmiddel)</summary>
          <pre>${escapeHtml(context.extracted_text || context.text || '')}</pre>
        </details>
      </article>`;

    const renderQuestionCard = question => `
      <article class="analysis-card">
        <h3>Opgave · vraag ${question.question_number}</h3>
        <div class="fragment-images">
          ${question.segments.map(segment => `
            <figure>
              <figcaption>Pagina ${segment.page_number}</figcaption>
              <img loading="lazy" src="${escapeHtml(segment.url)}" alt="Definitief vraagfragment ${question.question_number}">
            </figure>`).join('')}
        </div>
      </article>`;

    // Gebruik de daadwerkelijke, door de docent bevestigde contextbereiken.
    // Als twee contexten dezelfde startvraag hebben, sorteer dan op eindvraag
    // aflopend zodat de grotere gedeelde context eerst zichtbaar wordt.
    const orderedItems = [
      ...result.contexts.map(context => ({
        kind: 'context',
        start: Number(context.from_question ?? context.suggested_from_question),
        end: Number(context.to_question),
        context
      })),
      ...result.opgaven.questions.map(question => ({
        kind: 'question',
        start: Number(question.question_number),
        end: Number(question.question_number),
        question
      }))
    ].sort((a, b) =>
      a.start - b.start ||
      (a.kind === 'context' && b.kind === 'question' ? -1 :
       a.kind === 'question' && b.kind === 'context' ? 1 : 0) ||
      (a.kind === 'context' && b.kind === 'context' ? b.end - a.end : 0)
    );

    const orderedReviewCards = orderedItems.map(item =>
      item.kind === 'context' ? contextHtml(item.context) : renderQuestionCard(item.question)
    ).join('');
    const renderFragmentCards = (questions, heading, altPrefix) => questions.map(question => `
      <article class="analysis-card">
        <h3>${heading} · vraag ${question.question_number}</h3>
        <div class="fragment-images">
          ${question.segments.map(segment => `
            <figure>
              ${segment.page_number ? `<figcaption>Pagina ${segment.page_number}</figcaption>` : ''}
              <img class="fragment-image" loading="lazy" src="${escapeHtml(segment.url)}" alt="${altPrefix} vraag ${question.question_number}">
            </figure>`).join('')}
        </div>
      </article>`).join('');

    const questionCards = result.opgaven.questions.map(question => `
      <article class="analysis-card">
        <h3>Opgave · vraag ${question.question_number}</h3>
        <div class="fragment-images">
          ${question.segments.map(segment => `
            <figure>
              <figcaption>Pagina ${segment.page_number}</figcaption>
              <img loading="lazy" src="${escapeHtml(segment.url)}" alt="Definitief vraagfragment ${question.question_number}">
            </figure>`).join('')}
        </div>
      </article>`).join('');

    panel.innerHTML = `
      <p class="eyebrow">FASE 8 · DEFINITIEVE SNIPPETS</p>
      <h2>Contexten en snippets controleren</h2>
      <p class="lead">Bekijk de definitieve uitsneden en controleer of context, vraag, uitwerkbijlage en correctievoorschrift volledig en correct zijn weergegeven. Pas alleen een contextbereik aan als de koppeling met de vragen niet klopt.</p>
      <div class="notice">
        ${result.question_count} vragen · ${result.context_count} contextvoorstellen ·
        ${result.uitwerkbijlage.question_count} uitwerkbijlagefragmenten ·
        ${result.correctievoorschrift.question_count} CV-fragmenten.
      </div>
      <h3>Contexten en vraagfragmenten in documentvolgorde</h3>
      ${orderedReviewCards || '<p class="muted">Er zijn geen context- of vraagfragmenten beschikbaar.</p>'}
      <h3>Uitwerkbijlagefragmenten</h3>
      ${renderFragmentCards(result.uitwerkbijlage.questions, 'Uitwerkbijlage', 'Uitwerkbijlage')}
      ${result.uitwerkbijlage.questions.length ? '' : '<p class="muted">Geen uitwerkbijlagefragmenten van toepassing.</p>'}
      <h3>Correctievoorschriftfragmenten</h3>
      ${renderFragmentCards(result.correctievoorschrift.questions, 'Correctievoorschrift', 'Correctievoorschrift')}
      <h3>Snippets uit de CV-aanvulling</h3>
      ${(result.cv_aanvulling?.snippets || []).map(fragment => `
        <article class="analysis-card">
          <h3>CV-aanvulling · vraag ${fragment.question_numbers.join(', ')}</h3>
          <p class="analysis-reason">${escapeHtml(fragment.action)} · gecontroleerde uitsnede</p>
          ${(fragment.urls || []).map(url => `<img class="fragment-image" loading="lazy" src="${escapeHtml(url)}" alt="Vraagfragment uit de CV-aanvulling">`).join('')}
        </article>`).join('')}
      ${(result.cv_aanvulling?.snippets || []).length ? '' : '<p class="muted">Geen beoordeelde fragmenten uit een CV-aanvulling.</p>'}
      <div class="review-actions">
        <button class="primary" id="saveSnippets" type="button">Controle opslaan</button>
        <button class="primary" id="completeSnippets" type="button">Snippets goedkeuren en doorgaan</button>
      </div>
      <p id="snippetsMessage" class="form-error" role="status"></p>`;

    // De server bewaart voor compatibiliteit nog steeds expliciete
    // reviewed-markeringen. Die worden nu in één keer gezet door de
    // afrondactie, niet door een reeks vinkjes naast afzonderlijke plaatjes.
    const collect = () => ({
      contexts: result.contexts.map(context => ({
        id: context.id,
        title: panel.querySelector(`[data-context-title="${CSS.escape(context.id)}"]`)?.value?.trim() || context.label || '',
        from_question: Number(panel.querySelector(`[data-context-from="${CSS.escape(context.id)}"]`)?.value),
        to_question: Number(panel.querySelector(`[data-context-to="${CSS.escape(context.id)}"]`)?.value),
        reviewed: true
      })),
      reviewed_question_numbers: result.opgaven.questions.map(item => Number(item.question_number)),
      reviewed_uitwerk_numbers: result.uitwerkbijlage.questions.map(item => Number(item.question_number)),
      reviewed_cv_numbers: result.correctievoorschrift.questions.map(item => Number(item.question_number)),
      confirmed_no_contexts: result.contexts.length === 0
    });

    const validate = () => {
      for (const context of collect().contexts) {
        if (!Number.isInteger(context.from_question) || !Number.isInteger(context.to_question)
            || context.from_question < 1 || context.to_question < context.from_question
            || context.to_question > 60) {
          return 'Controleer het vraagbereik van iedere context.';
        }
      }
      return null;
    };

    const save = (options = {}) => {
      const problem = validate();
      if (problem) throw new Error(problem);
      return api(`/api/exams/${state.examId}/snippets/review`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...collect(), ...options})
      });
    };

    bindStageAutoSave(panel, save, '#snippetsMessage');

    $('#saveSnippets').addEventListener('click', async event => {
      const button = event.currentTarget;
      const original = button.textContent;
      button.disabled = true;
      button.textContent = 'Opslaan…';
      try {
        const saved = await save({draft: true});
        $('#snippetsMessage').textContent =
          `${saved.reviewed_question_numbers.length} vraagfragmenten en ${result.context_count} contexten opgeslagen.`;
      } catch (error) {
        $('#snippetsMessage').textContent = error.message;
      } finally {
        if (button.isConnected) {
          button.disabled = false;
          button.textContent = original;
        }
      }
    });

    let completingSnippets = false;
    $('#completeSnippets').addEventListener('click', async event => {
      const button = event.currentTarget;
      if (completingSnippets) return;
      completingSnippets = true;
      button.disabled = true;
      button.textContent = 'Controleren en afronden…';
      try {
        // Flush de laatste contextwijziging vóór het expliciet afronden.
        const saved = panel._stageAutoSaveFlush
          ? await panel._stageAutoSaveFlush()
          : await save({draft: true});
        if (!saved.complete) throw new Error('De snippetcontrole is nog niet volledig opgeslagen.');

        await api(`/api/exams/${state.examId}/steps/snippets/complete`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({reviewed: true, reviewed_all_questions: true, reviewed_all_contexts: true})
        });
        button.textContent = 'Volgende stap openen…';
        await openWorkspace(state.examId);
      } catch (error) {
        completingSnippets = false;
        if (button.isConnected) {
          button.disabled = false;
          button.textContent = 'Snippets goedkeuren en doorgaan';
        }
        $('#snippetsMessage').textContent = error.message;
        if (/oudere versie van de lange afbeelding/i.test(error.message)) {
          $('#snippetsMessage').insertAdjacentHTML('afterend',
            '<button class="quiet" id="reopenOpgavenFragments" type="button">Terug naar stap 3 · fragmenten opnieuw controleren</button>');
          $('#reopenOpgavenFragments')?.addEventListener('click', async () => {
            await api(`/api/exams/${state.examId}/steps/opgaven_fragments/reopen`, {method: 'POST'});
            await openWorkspace(state.examId);
          });
        }
      }
    });
  } catch (error) {
    panel.innerHTML = `<h2>Definitieve snippets</h2><p class="form-error">${escapeHtml(error.message)}</p>`;
    if (/oudere versie van de lange afbeelding/i.test(error.message)) {
      panel.insertAdjacentHTML('beforeend',
        '<button class="primary" id="reopenOpgavenFragments" type="button">Terug naar stap 3 · fragmenten opnieuw controleren</button>');
      $('#reopenOpgavenFragments')?.addEventListener('click', async () => {
        try {
          await api(`/api/exams/${state.examId}/steps/opgaven_fragments/reopen`, {method: 'POST'});
          await openWorkspace(state.examId);
        } catch (reopenError) {
          panel.insertAdjacentHTML('beforeend', `<p class="form-error">${escapeHtml(reopenError.message)}</p>`);
        }
      });
    }
  }
}

/* De integrale eindcontrole toont alle bronnen in één vraagkaart. Problemen
   worden niet verborgen: ontbrekende koppelingen en afwijkende scores blijven
   zichtbaar en vragen een toelichting voordat het examen kan worden afgerond.
   De afrondknop is de bevestiging; per vraag afvinken is overbodig. */
async function renderFinalReviewStage() {
  const panel = $('#stagePanel');
  panel.innerHTML = '<p class="muted">Integrale eindcontrole samenstellen…</p>';

  try {
    const result = await api(`/api/exams/${state.examId}/final-review`);
    if (!result.questions?.length) {
      throw new Error('Er zijn geen vraagrecords beschikbaar voor de integrale eindcontrole.');
    }

    let currentIndex = 0;
    const visited = new Set(
      result.questions.filter(question => question.reviewed).map(question => question.question_number)
    );
    const notes = Object.fromEntries(
      result.questions.map(question => [question.question_number, question.resolution_note || ''])
    );
    let saveTimer = null;
    let saveChain = Promise.resolve();
    let completing = false;

    const currentQuestion = () => result.questions[currentIndex];
    const allVisited = () => visited.size === result.questions.length;
    const unresolvedMismatches = () => result.questions.filter(question =>
      question.points_match === false && !String(notes[question.question_number] || '').trim()
    );

    const contextHtml = question => question.context.length
      ? question.context.map(context => `
          <figure>
            <figcaption>Context · pagina ${context.page_number} · vragen ${context.from_question}–${context.to_question}</figcaption>
            <img class="fragment-image" loading="lazy" src="${escapeHtml(context.url)}" alt="Context bij vraag ${question.question_number}">
          </figure>`).join('')
      : '<p class="muted">Geen afzonderlijke context gekoppeld.</p>';

    const segmentHtml = (segments, alt, emptyMessage) => segments.length
      ? segments.map(segment => `
          <figure>
            ${segment.page_number ? `<figcaption>Pagina ${segment.page_number}</figcaption>` : ''}
            <img class="fragment-image" loading="lazy" src="${escapeHtml(segment.url)}" alt="${alt}">
          </figure>`).join('')
      : `<p class="muted">${emptyMessage}</p>`;

    const questionCardHtml = question => `
      <article class="analysis-card final-review-card" data-final-card="${question.question_number}">
        <div class="card-heading">
          <h3>Vraag ${question.question_number}</h3>
          <span class="status-pill">${question.points_match === false ? 'Scoreverschil' : question.correctievoorschrift.length ? 'CV gekoppeld' : 'CV ontbreekt'}</span>
        </div>

        <h4>Gekoppelde context</h4>
        ${contextHtml(question)}

        <h4>Opgave</h4>
        ${segmentHtml(question.opgaven, `Opgave ${question.question_number}`, 'Geen opgavefragment gevonden.')}

        <h4>Uitwerkbijlage</h4>
        ${segmentHtml(question.uitwerkbijlage, `Uitwerkbijlage vraag ${question.question_number}`, 'Geen bijbehorend onderdeel in de uitwerkbijlage.')}

        <h4>Correctievoorschrift</h4>
        ${segmentHtml(question.correctievoorschrift, `Correctievoorschrift vraag ${question.question_number}`, 'Geen CV-fragment gekoppeld.')}

        ${(question.supplement_pages || []).map(page => `
          <p class="analysis-reason">CV-aanvulling · pagina ${page.page_number} · ${escapeHtml(page.action)}${page.action === 'vervangen' ? ' (vervangt het oorspronkelijke antwoordvoorstel)' : ''}</p>
          <img class="fragment-image" loading="lazy" src="${escapeHtml(page.url)}" alt="CV-aanvulling bij vraag ${question.question_number}">
        `).join('')}

        ${question.options?.length ? `
          <h4>Herkende antwoordopties</h4>
          <ul class="final-answer-options">${question.options.map(option => `
            <li class="final-answer-option">
              <div><strong>${escapeHtml(option.letter)}.</strong> ${escapeHtml(option.text || '')}</div>
              ${option.image_data ? `<img class="final-answer-option-image" src="${option.image_data}" alt="Afbeelding bij antwoordoptie ${escapeHtml(option.letter)}">` : ''}
            </li>`).join('')}</ul>
        ` : ''}

        <div class="relation-grid">
          <span>Vraagtype: ${escapeHtml(question.question_type)}</span>
          <span>Maximumscore opgave: ${question.max_points ?? 'onbekend'}</span>
          <span>Maximumscore CV: ${question.cv_max_points ?? 'onbekend'}${question.points_reason ? ' · ' + escapeHtml(question.points_reason) : ''}</span>
          <span>Antwoordvorm: ${escapeHtml(question.answer_kind)}</span>
        </div>

        <details>
          <summary>Antwoord / beoordelingscriteria</summary>
          <pre>${escapeHtml(question.answer_text || 'Geen antwoordtekst opgeslagen.')}</pre>
        </details>

        ${question.points_match === false ? `
          <section class="analysis-card">
            <p class="form-error">De maximumscores komen niet overeen. Leg kort vast waarom dit verschil klopt of hoe het is hersteld.</p>
            <label>Toelichting scoreverschil
              <textarea rows="3" data-final-note="${question.question_number}">${escapeHtml(notes[question.question_number])}</textarea>
            </label>
          </section>
        ` : ''}

        <details>
          <summary>Herstelmogelijkheden voor deze vraag</summary>
          <div class="review-actions">
            <button class="quiet" type="button" data-repair="opgaven_fragments">Opgavefragment herstellen</button>
            <button class="quiet" type="button" data-repair="opgaven_analyse">Vraagtype / punten / opties</button>
            ${examHasDocumentType('uitwerkbijlage') ? '<button class="quiet" type="button" data-repair="uitwerk_fragments">Uitwerkfragment herstellen</button>' : ''}
            <button class="quiet" type="button" data-repair="cv_fragments">CV-fragment herstellen</button>
            <button class="quiet" type="button" data-repair="cv_aanvulling">CV-aanvulling aanpassen</button>
            <button class="quiet" type="button" data-repair="antwoorden">Antwoord aanpassen</button>
            <button class="quiet" type="button" data-repair="relaties">Koppeling herstellen</button>
          </div>
        </details>
      </article>`;

    const overviewHtml = () => result.questions.map((question, index) => {
      const number = question.question_number;
      const isVisited = visited.has(number);
      const hasIssue = question.points_match === false;
      const label = hasIssue ? `${number} · !` : isVisited ? `${number} · ✓` : String(number);
      return `<button class="quiet small" type="button" data-final-jump="${index}" aria-label="Ga naar vraag ${number}" title="${hasIssue ? 'Scoreverschil toelichten' : isVisited ? 'Bekeken' : 'Nog niet bekeken'}">${label}</button>`;
    }).join('');

    const collect = (markAllReviewed = false) => result.questions.map(question => ({
      question_number: question.question_number,
      reviewed: markAllReviewed || visited.has(question.question_number),
      resolution_note: String(notes[question.question_number] || '')
    }));

    const save = (options = {}) => {
      const questions = collect(Boolean(options.mark_all_reviewed));
      const payload = {...options, questions};
      delete payload.mark_all_reviewed;
      return api(`/api/exams/${state.examId}/final-review/review`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
    };

    const saveDraft = () => {
      clearTimeout(saveTimer);
      // Serialiseer autosaves. Een oudere, tragere request mag een nieuwere
      // vraagnotitie of bekeken-status nooit terugschrijven.
      saveChain = saveChain.catch(() => {}).then(() => save({draft: true}));
      return saveChain;
    };

    const scheduleSave = () => {
      clearTimeout(saveTimer);
      const status = $('#finalReviewSaveStatus');
      if (status) status.textContent = 'Wijziging wordt opgeslagen…';
      saveTimer = setTimeout(() => {
        saveDraft().then(() => {
          const currentStatus = $('#finalReviewSaveStatus');
          if (currentStatus) currentStatus.textContent = 'Opgeslagen';
        }).catch(error => {
          const currentStatus = $('#finalReviewSaveStatus');
          if (currentStatus) currentStatus.textContent = error.message;
        });
      }, 450);
    };

    const refreshControls = () => {
      const previousButtons = [$('#previousFinalQuestion'), $('#previousFinalQuestionBottom')].filter(Boolean);
      const nextButtons = [$('#nextFinalQuestion'), $('#nextFinalQuestionBottom')].filter(Boolean);
      const complete = $('#completeFinalReview');
      const progress = $('#finalReviewProgress');
      previousButtons.forEach(button => button.disabled = currentIndex === 0);
      nextButtons.forEach(button => button.disabled = currentIndex === result.questions.length - 1);
      if (progress) {
        const remaining = result.questions.length - visited.size;
        progress.textContent = `Vraag ${currentIndex + 1} van ${result.questions.length} · ${remaining} nog te bekijken`;
      }
      if (complete) {
        complete.disabled = !allVisited() || unresolvedMismatches().length > 0 || completing;
        complete.textContent = completing ? 'Eindcontrole afronden…' : 'Eindcontrole afronden';
      }
      panel.querySelectorAll('[data-final-jump]').forEach(button => {
        const index = Number(button.dataset.finalJump);
        button.classList.toggle('active', index === currentIndex);
        const question = result.questions[index];
        button.classList.toggle('candidate-suspect',
          question.points_match === false && !String(notes[question.question_number] || '').trim());
      });
    };

    const renderQuestion = () => {
      const question = currentQuestion();
      visited.add(question.question_number);
      panel.innerHTML = `
        <p class="eyebrow">FASE 9 · INTEGRALE EINDCONTROLE</p>
        <h2>Vraag voor vraag controleren</h2>
        <p class="lead">Bekijk per vraag de context, opgave, eventuele uitwerkbijlage, correctievoorschrift en antwoord. Met Vorige en Volgende doorloop je het examen. Een toelichting is alleen nodig bij een afwijkende maximumscore.</p>
        <div class="notice" id="finalReviewProgress"></div>
        <div class="final-review-overview" style="display:flex;flex-wrap:wrap;gap:0.35rem;margin:0.75rem 0 1rem">
          ${overviewHtml()}
        </div>
        <div class="review-actions" style="justify-content:space-between">
          <button class="quiet" id="previousFinalQuestion" type="button">← Vorige vraag</button>
          <button class="quiet" id="nextFinalQuestion" type="button">Volgende vraag →</button>
        </div>
        ${questionCardHtml(question)}
        <!-- Tweede navigatiepaar onder de vraagkaart: lange vragen kunnen scrollen. -->
        <div class="review-actions" style="justify-content:space-between">
          <button class="quiet" id="previousFinalQuestionBottom" type="button">← Vorige vraag</button>
          <button class="quiet" id="nextFinalQuestionBottom" type="button">Volgende vraag →</button>
        </div>
        <div class="review-actions">
          <button class="primary" id="saveFinalReview" type="button">Voortgang opslaan</button>
          <button class="primary" id="completeFinalReview" type="button">Eindcontrole afronden</button>
        </div>
        <p id="finalReviewSaveStatus" class="muted" role="status"></p>
        <p id="finalReviewMessage" class="form-error" role="status"></p>`;

      const noteField = panel.querySelector('[data-final-note]');
      if (noteField) {
        noteField.addEventListener('input', () => {
          notes[question.question_number] = noteField.value;
          refreshControls();
          scheduleSave();
        });
      }

      // Beide navigatieparen bedienen dezelfde index en dezelfde save-route.
      ['previousFinalQuestion', 'previousFinalQuestionBottom'].forEach(id => {
        panel.querySelector('#' + id)?.addEventListener('click', () => navigateTo(currentIndex - 1));
      });
      ['nextFinalQuestion', 'nextFinalQuestionBottom'].forEach(id => {
        panel.querySelector('#' + id)?.addEventListener('click', () => navigateTo(currentIndex + 1));
      });
      panel.querySelectorAll('[data-final-jump]').forEach(button => {
        button.addEventListener('click', () => navigateTo(Number(button.dataset.finalJump)));
      });

      $('#saveFinalReview').addEventListener('click', async event => {
        const button = event.currentTarget;
        const original = button.textContent;
        button.disabled = true;
        button.textContent = 'Opslaan…';
        try {
          await saveDraft();
          $('#finalReviewSaveStatus').textContent = 'Voortgang opgeslagen.';
        } catch (error) {
          $('#finalReviewMessage').textContent = error.message;
        } finally {
          if (button.isConnected) button.textContent = original;
          refreshControls();
        }
      });

      $('#completeFinalReview').addEventListener('click', async () => {
        if (completing || !allVisited() || unresolvedMismatches().length) return;
        completing = true;
        refreshControls();
        try {
          clearTimeout(saveTimer);
          await saveChain;
          // De expliciete afrondactie bevestigt de volledige reeks. De server
          // krijgt alle vragen als gecontroleerd, zonder verborgen vinkjes.
          const saved = await save({draft: false, mark_all_reviewed: true});
          if (!saved.complete) throw new Error('De integrale eindcontrole is nog niet volledig opgeslagen.');
          await api(`/api/exams/${state.examId}/steps/eindcontrole/complete`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({reviewed: true, reviewed_all_questions: true})
          });
          await openWorkspace(state.examId);
        } catch (error) {
          completing = false;
          const message = $('#finalReviewMessage');
          if (message) message.textContent = error.message;
          refreshControls();
        }
      });

      panel.querySelectorAll('[data-repair]').forEach(button => {
        button.addEventListener('click', async () => {
          const original = button.textContent;
          button.disabled = true;
          button.textContent = 'Stap heropenen…';
          try {
            await saveDraft();
            await api(`/api/exams/${state.examId}/steps/${button.dataset.repair}/reopen`, {method: 'POST'});
            await openWorkspace(state.examId);
          } catch (error) {
            button.disabled = false;
            button.textContent = original;
            const message = $('#finalReviewMessage');
            if (message) message.textContent = error.message;
          }
        });
      });

      refreshControls();
    };

    const navigateTo = nextIndex => {
      if (nextIndex < 0 || nextIndex >= result.questions.length || nextIndex === currentIndex) return;

      /*
       * Navigeren hoeft niet op de serverroundtrip te wachten: de bekeken-status
       * en eventuele toelichting staan al in de lokale arrays (visited/notes).
       * De debounced, seriële autosave schrijft die momentopname weg. Daardoor
       * wordt het scherm direct opgebouwd, terwijl opslag op de achtergrond
       * doorgaat. saveChain voorkomt dat overlappende saves elkaar overschrijven.
       */
      currentIndex = nextIndex;
      renderQuestion();
      scheduleSave();
    };

    // Expose one flush hook so any workflow navigation waits for the final
    // pending autosave before replacing this panel.
    const saveWhenHidden = () => {
      if (document.visibilityState === 'hidden') saveDraft().catch(() => {});
    };
    const saveOnPageHide = () => saveDraft().catch(() => {});
    document.addEventListener('visibilitychange', saveWhenHidden);
    window.addEventListener('pagehide', saveOnPageHide);

    panel._stageAutoSaveFlush = saveDraft;
    panel._stageAutoSaveCleanup = () => {
      clearTimeout(saveTimer);
      document.removeEventListener('visibilitychange', saveWhenHidden);
      window.removeEventListener('pagehide', saveOnPageHide);
      panel._stageAutoSaveFlush = null;
      panel._stageAutoSaveCleanup = null;
    };

    renderQuestion();
  } catch (error) {
    panel.innerHTML = `<h2>Integrale eindcontrole</h2><p class="form-error">${escapeHtml(error.message)}</p>`;
    if (/oudere versie van de lange afbeelding/i.test(error.message)) {
      /*
       * De eindcontrole kan worden geblokkeerd door verouderde fragment-
       * coördinaten uit verschillende documenten. De herstelstap staat in
       * het API-foutbericht zelf. Leid de knop daarom af van die aanwijzing,
       * in plaats van altijd terug te sturen naar de opgaven (stap 3).
       */
      const recoveryMatch = error.message.match(/heropen stap\s*(\d+)/i);
      const recoveryStep = recoveryMatch ? Number(recoveryMatch[1]) : 3;
      const recoveryMap = {
        3: {key: 'opgaven_fragments', label: 'stap 3 · opgavenfragmenten'},
        6: {key: 'uitwerk_fragments', label: 'stap 6 · fragmenten uitwerkbijlage'},
        8: {key: 'cv_fragments', label: 'stap 8 · CV-fragmenten'}
      };
      const target = recoveryMap[recoveryStep] || recoveryMap[3];
      panel.insertAdjacentHTML('beforeend',
        `<button class="primary" id="reopenStaleFragments" type="button">Terug naar ${escapeHtml(target.label)} · opnieuw controleren</button>`);
      $('#reopenStaleFragments')?.addEventListener('click', async () => {
        try {
          await api(`/api/exams/${state.examId}/steps/${target.key}/reopen`, {method: 'POST'});
          await openWorkspace(state.examId);
        } catch (reopenError) {
          panel.insertAdjacentHTML('beforeend', `<p class="form-error">${escapeHtml(reopenError.message)}</p>`);
        }
      });
    }
  }
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
        <span><strong>${item.sequence_warning ? 'Mogelijke subnummering' : 'Hoofdvraag'} ${item.question_number}</strong><small>${escapeHtml(item.text)} · positie ${Math.round(item.pdf_bbox[1])} pt${item.source === 'manual' ? ' · handmatig' : ''}${item.sequence_warning ? ' · niet opgenomen als hoofdvraagstart: nummer past niet in de oplopende reeks (bijvoorbeeld een stelling of subvraag)' : ''}${item.learning_active ? ' · leerfeedback: ' + Math.round(item.learning_score_adjustment * 100) + '% rangschikkingshint uit eerdere reviews' : ''}</small></span>
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
      let startSaveChain = Promise.resolve();
      const queueStartSave = () => {
        // Seriële opslag voorkomt dat twee snel opeenvolgende wijzigingen
        // elkaar in SQLite in een andere volgorde overschrijven.
        startSaveChain = startSaveChain.catch(() => {}).then(() => saveReview());
        return startSaveChain;
      };
      const scheduleStartAutosave = () => {
        clearTimeout(autosaveTimer);
        autosaveTimer = setTimeout(() => {
          queueStartSave().then(saved => {
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
        return queueStartSave().catch(error => {
          const status = $('#startReviewMessage');
          if (status) status.textContent = 'Automatisch opslaan mislukt: ' + error.message;
          throw error;
        });
      };
      const startVisibilityChange = () => {
        if (document.visibilityState === 'hidden') flushStartAutosave().catch(() => {});
      };
      const flushStartOnPageHide = () => flushStartAutosave().catch(() => {});
      document.addEventListener('visibilitychange', startVisibilityChange);
      window.addEventListener('pagehide', flushStartOnPageHide);
      panel._stageAutoSaveCleanup = () => {
        clearTimeout(autosaveTimer);
        panel.onchange = null;
        panel.onclick = null;
        document.removeEventListener('visibilitychange', startVisibilityChange);
        window.removeEventListener('pagehide', flushStartOnPageHide);
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
          queueStartSave().catch(error => { $('#startReviewMessage').textContent = 'Automatisch opslaan mislukt: ' + error.message; });
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
        queueStartSave().catch(error => { $('#startReviewMessage').textContent = 'Automatisch opslaan mislukt: ' + error.message; });
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
          queueStartSave().catch(error => { $('#startReviewMessage').textContent = 'Automatisch opslaan mislukt: ' + error.message; });
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
        queueStartSave().catch(error => { $('#startReviewMessage').textContent = 'Automatisch opslaan mislukt: ' + error.message; });
      }));

      $('#saveStartReview').addEventListener('click', async () => {
        try {
          const saved = await flushStartAutosave();
          $('#startReviewMessage').textContent = `${saved.review.accepted_count} vraagstarts geaccepteerd; ${saved.review.rejected_count} afgewezen. Conceptreview opgeslagen.`;
        } catch (error) { $('#startReviewMessage').textContent = error.message; }
      });
      $('#completeStartReview').addEventListener('click', async () => {
        try {
          const saved = await flushStartAutosave();
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
  // De CV-aanvulling gebruikt dezelfde lange, samengevoegde PDF-afbeelding
  // als de andere documenten. Geef deze stap een eigen klasse zodat het
  // afbeeldingsvenster hoog genoeg blijft en zelfstandig verticaal kan scrollen.
  panel.classList.toggle('supplement-fragments-stage', documentType === 'aanvulling_correctievoorschrift');
  panel.innerHTML = '<p class="muted">Het document wordt samengevoegd tot één lange afbeelding…</p>';
  // Dezelfde werkruimte wordt gebruikt voor opgaven en uitwerkbijlage.
  // Alleen de API-route en toegestane fragmentsoort verschillen.
  const isWorkbook = documentType === 'uitwerkbijlage';
  const isCv = documentType === 'correctievoorschrift';
  const isSupplement = documentType === 'aanvulling_correctievoorschrift';
  const isStitchedDocument = isWorkbook || isCv || isSupplement;
  const documentLabel = isWorkbook ? 'uitwerkbijlage' : isCv ? 'correctievoorschrift' : isSupplement ? 'aanvulling op het correctievoorschrift' : 'opgavenboekje';
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
    // Bij een oude afbeelding zijn de behouden grenzen slechts een
    // herstelvoorstel. Automatische saves en pagehide mogen de waarschuwing
    // niet stilzwijgend wissen; alleen de expliciete knop 'Nu opslaan' geldt
    // als bevestiging dat de docent de grenzen op de nieuwe afbeelding heeft
    // gecontroleerd.
    let recoveryNeedsExplicitSave = Boolean(result.selection_warning);

    panel.innerHTML = `
      <p class="eyebrow">${stageLabel}</p><h2>${escapeHtml(stageTitle)}</h2>
      <p class="lead">${isStitchedDocument
        ? `De volledige pagina’s van het ${documentLabel} zijn samengevoegd tot één doorlopende afbeelding. Controleer de vraagfragmenten, verplaats zo nodig de grenzen en koppel elk fragment aan de juiste vraag.`
        : 'De volledige pagina’s zijn samengevoegd tot één doorlopende afbeelding. Selecteer elk afzonderlijk contextdeel als fragment van het type Context en koppel het aan de vragen waarop het betrekking heeft. Contextdelen met overlappende vraagnummers worden automatisch samengevoegd tot één contextgroep. De titel wordt afgeleid van de eerste tekstregel van het eerste contextdeel. Selecteer daarnaast iedere opgave als fragment van het type Vraag en koppel die aan het eigen vraagnummer.'}</p>
      <div class="notice">${result.pages.length} pagina's verwerkt · paginanummers en grote buitenmarges verwijderd vóór het samenvoegen. Wijzigingen worden automatisch opgeslagen; de bron-PDF blijft ongewijzigd.</div>
      ${result.selection_warning ? `<p id="selectionRecoveryWarning" class="form-error">${escapeHtml(result.selection_warning)}</p>` : ''}
      <div class="stitched-workspace">
        <section class="stitched-view"><div class="stitched-toolbar"><button class="quiet" id="beginFragment">Nieuw fragment selecteren</button><span id="selectionHint" class="muted">Kies ‘Nieuw fragment selecteren’.</span><span id="stitchedSaveStatus" class="muted" role="status">Opgeslagen versie geladen</span></div>
          <div class="stitched-image-scroll" id="stitchedImageScroll"><div class="stitched-image-wrap" id="stitchedImageWrap"><img id="stitchedImage" src="${result.image_url}" alt="Samengevoegd examen"><div id="stitchedOverlay" class="stitched-overlay"></div></div></div>
        </section>
        <aside class="stitched-inspector">
            <div class="stitched-inspector-heading">
              <h3>Contextoverzicht</h3>
              <p class="field-help">Contextdelen worden op basis van overlappende vraagnummers gegroepeerd. De titel komt uit de eerste tekstregel van het eerste contextdeel.</p>
            </div>
            <div id="contextGroupSummary" class="context-group-summary"></div>
            <details class="stitched-fragments-panel" ${activeIndex >= 0 ? "open" : ""}>
              <summary>Fragmenten bewerken <span>${selections.length}</span></summary>
              <div id="stitchedSelectionList"></div>
            </details>
          </aside>
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
    const persistSelections = (explicitRecoverySave = false) => {
      // Zolang een oude selectie als herstelvoorstel wordt getoond, slaan we
      // niets automatisch op. Anders zou alleen het openen/sluiten van de
      // pagina de oude coördinaten aan de nieuwe afbeelding koppelen zonder
      // dat de docent ze heeft bekeken.
      if (recoveryNeedsExplicitSave && !explicitRecoverySave) {
        saveStatus.textContent = 'Controleer de behouden grenzen en klik daarna op Nu opslaan';
        return Promise.resolve(null);
      }
      clearTimeout(saveTimer);
      const snapshot = JSON.parse(JSON.stringify(selections));
      saveStatus.textContent = 'Opslaan…';
      saveChain = saveChain.catch(() => {}).then(() => api(
        stitchedReviewUrl,
        {method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({selections:snapshot, reviewed:false})}
      )).then(response => {
        // De server leest de eerste tekstregel opnieuw uit de PDF op basis
        // van de actuele pixelgrenzen. Daardoor blijft de contextgroeptitel
        // ook correct wanneer de docent de boven- of ondergrens verplaatst.
        if (response.context_titles) {
          selections.forEach(item => {
            if (item.type === 'context' && Object.prototype.hasOwnProperty.call(response.context_titles, item.id)) {
              item.context_title = response.context_titles[item.id];
            }
          });
          render();
        }
        saveStatus.textContent = 'Alle wijzigingen opgeslagen';
        if (explicitRecoverySave && recoveryNeedsExplicitSave) {
          recoveryNeedsExplicitSave = false;
          $('#selectionRecoveryWarning')?.remove();
        }
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
      if (completingStep || recoveryNeedsExplicitSave) return;
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
      // Wanneer de cursor tijdens het grensslepen de rand van het
      // leesvenster nadert, scrollen we het lange document geleidelijk mee.
      // Omdat de scrollcontainer en afbeelding verschuiven, berekenen we de
      // beeldcoördinaat pas na de scrollbeweging opnieuw.
      const scrollRect = imageScroll.getBoundingClientRect();
      const edgeZone = 48;
      if (event.clientY < scrollRect.top + edgeZone && imageScroll.scrollTop > 0) {
        const intensity = Math.min(1, (scrollRect.top + edgeZone - event.clientY) / edgeZone);
        imageScroll.scrollTop -= Math.max(2, 14 * intensity);
      } else if (event.clientY > scrollRect.bottom - edgeZone
          && imageScroll.scrollTop < imageScroll.scrollHeight - imageScroll.clientHeight) {
        const intensity = Math.min(1, (event.clientY - (scrollRect.bottom - edgeZone)) / edgeZone);
        imageScroll.scrollTop += Math.max(2, 14 * intensity);
      }
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

      /*
       * Contextstructuur voor de docent zichtbaar maken.
       *
       * Meerdere fysieke contextfragmenten kunnen samen één inhoudelijke
       * context vormen. De expliciete koppeling staat in question_numbers.
       * Fragmenten met overlappende vraagnummers worden daarom als één
       * contextgroep gepresenteerd. De onderliggende losse fragmenten en
       * hun coördinaten blijven afzonderlijk opgeslagen en bewerkbaar.
       */
      const contextSelections = selections
        .map((item, index) => ({item, index}))
        .filter(entry => entry.item.type === "context");
      const parent = contextSelections.map((_, index) => index);
      const findRoot = index => {
        while (parent[index] !== index) {
          parent[index] = parent[parent[index]];
          index = parent[index];
        }
        return index;
      };
      const joinGroups = (left, right) => {
        const a = findRoot(left), b = findRoot(right);
        if (a !== b) parent[b] = a;
      };
      const questionSetsOverlap = (left, right) => {
        // Een gedeeld vraagnummer is het expliciete bewijs dat twee fysieke
        // contextdelen bij dezelfde inhoudelijke context kunnen horen.
        // Lege vraagsets worden bewust niet gekoppeld: zonder nummer is er
        // geen betrouwbare relatie waarmee een groep kan worden afgeleid.
        const leftNumbers = new Set(
          (left.question_numbers || []).map(Number).filter(Number.isInteger)
        );
        return (right.question_numbers || []).some(number => leftNumbers.has(Number(number)));
      };
      for (let left = 0; left < contextSelections.length; left++) {
        for (let right = left + 1; right < contextSelections.length; right++) {
          // Union-find maakt de relatie transitief. Als A overlapt met B en
          // B overlapt met C, worden A, B en C één contextgroep, ook wanneer
          // A en C zelf geen vraagnummers delen.
          if (questionSetsOverlap(contextSelections[left].item, contextSelections[right].item)) {
            joinGroups(left, right);
          }
        }
      }
      const contextGroups = new Map();
      contextSelections.forEach((entry, index) => {
        const root = findRoot(index);
        if (!contextGroups.has(root)) contextGroups.set(root, {parts: [], questionNumbers: new Set()});
        const group = contextGroups.get(root);
        group.parts.push(entry);
        (entry.item.question_numbers || []).forEach(number => group.questionNumbers.add(Number(number)));
      });
      // Sorteer de fysieke contextdelen altijd op hun positie in de
      // doorlopende examenstrook. De bovenste context bepaalt de titel,
      // ongeacht de volgorde waarin de docent de fragmenten heeft geselecteerd.
      for (const group of contextGroups.values()) {
        group.parts.sort((left, right) => Number(left.item.top) - Number(right.item.top));
      }
      const orderedContextGroups = [...contextGroups.values()].sort((left, right) =>
        Number(left.parts[0]?.item.top || 0) - Number(right.parts[0]?.item.top || 0)
      );
      const questionSelections = selections.filter(item => item.type === "vraag");
      const formatNumbers = numbers => {
        const sorted = [...numbers].sort((a, b) => a - b);
        return sorted.length ? formatQuestionRanges(sorted) : "nog niet gekoppeld";
      };
      const summary = $("#contextGroupSummary");
      summary.innerHTML = contextGroups.size ? orderedContextGroups.map((group, groupIndex) => {
        const numbers = [...group.questionNumbers].sort((a, b) => a - b);
        const missingNumbers = numbers.filter(number =>
          !questionSelections.some(item => (item.question_numbers || []).map(Number).includes(number))
        );
        // De fragmenten zijn hierboven op documentpositie gesorteerd.
        // Het eerste fragment bepaalt daarom de titel van de hele groep.
        const title = group.parts[0]?.item.context_title || "Titel niet beschikbaar in de PDF-tekstlaag";
        return `<section class="context-group-card">
          <div class="context-group-meta">
            <span class="context-group-index">CONTEXT ${String(groupIndex + 1).padStart(2, "0")}</span>
            <span class="context-group-count">${group.parts.length} fragment${group.parts.length === 1 ? "" : "en"}</span>
          </div>
          <h4 class="context-group-title">${escapeHtml(title)}</h4>
          <p class="context-group-range">${numbers.length ? `Vragen ${escapeHtml(formatNumbers(numbers))}` : "Nog geen vragen gekoppeld"}</p>
          ${missingNumbers.length ? `<p class="context-group-warning">Vraagfragment ontbreekt bij ${escapeHtml(formatNumbers(missingNumbers))}</p>` : ""}
          <div class="context-group-questions">${questionSelections.filter(question => (question.question_numbers || []).some(number => numbers.includes(Number(number)))).map(question => `<div class="context-group-question-card"><strong>${escapeHtml(questionLabel(question))}</strong><small>Bij deze contextgroep</small></div>`).join("") || '<p class="muted">Nog geen vraagfragmenten aan deze groep gekoppeld.</p>'}</div>
          <details class="context-group-details">
            <summary>Contextdelen bekijken</summary>
            <ul>${group.parts.map(entry => `<li>${escapeHtml(questionLabel(entry.item))}</li>`).join("")}</ul>
          </details>
        </section>`;
      }).join("") : '<p class="muted">Selecteer op de examenstrook een fragment van het type Context en koppel het aan de bijbehorende vraagnummers. Contextdelen met overlappende vraagnummers vormen automatisch één groep.</p>';

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
      // Een handmatig nieuw fragment is standaard context. Dat sluit aan bij
      // de gebruikelijke werkwijze: eerst contextblokken markeren en daarna
      // de daadwerkelijke vraagfragmenten. De docent kan het type rechts
      // altijd expliciet wijzigen naar 'Vraag'.
      selections.push({id:`fragment-${Date.now()}-${selections.length}`,type:'context',top:snappedTop,bottom:snappedBottom,question_numbers:[],label:''});
      activeIndex=selections.length-1;pendingTop=null;wrap.classList.remove('selecting');
      hint.textContent='Fragment toegevoegd. Vul rechts type en vraagnummers in.';
      render();scheduleSave();
    });

    $('#saveStitched').addEventListener('click',async event=>{
      const button = event.currentTarget;
      const original = button.textContent;
      button.disabled = true;
      button.textContent = 'Opslaan…';
      try {
        await persistSelections(true);
        $('#stitchedMessage').textContent=`${selections.length} fragmentselecties opgeslagen.`;
      } catch(error) {
        $('#stitchedMessage').textContent=error.message;
      } finally {
        if (button.isConnected) {
          button.disabled = false;
          button.textContent = original;
        }
      }
    });
    $('#completeStitched').addEventListener('click', async () => {
      const button = $('#completeStitched');
      if (completingStep) return;
      completingStep = true;
      button.disabled = true;
      button.textContent = 'Controleren en afronden…';
      try {
        if (recoveryNeedsExplicitSave) {
          throw new Error('Controleer eerst alle behouden fragmentgrenzen op de nieuwe afbeelding en klik op ‘Nu opslaan’. Pas daarna kun je de fragmentcontrole goedkeuren.');
        }
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
        // Doorgaan is tevens een expliciete opslagactie.
        await persistSelections(true);
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
    let completingFragmentReview=false;
    $('#completeFragmentReview').addEventListener('click', async () => {
      const button=$('#completeFragmentReview');
      if(completingFragmentReview) return;
      completingFragmentReview=true;
      button.disabled=true;
      try {
        // Flush de laatste grenswijziging voordat de stap wordt afgerond.
        const {saved,changedNumbers} = panel._stageAutoSaveFlush
          ? await panel._stageAutoSaveFlush()
          : await save();
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
      } catch (error) {
        completingFragmentReview=false;
        refreshComplete();
        $('#fragmentReviewMessage').textContent = error.message;
      }
    });
  } catch (error) {
    panel.innerHTML = `<h2>Vraagfragmenten controleren</h2><p class="form-error">${escapeHtml(error.message)}</p>`;
  }
}

/* De analysefase gebruikt het volledige vraagfragment als visuele bron.
   Tekstlaagherkenning levert alleen voorlopige suggesties voor type, score en
   antwoordopties; elk veld blijft door de docent aanpasbaar. De afrondknop
   bevestigt de complete analyse, zonder een vinkje per vraag te verlangen. */
async function renderQuestionAnalysisStage() {
  const panel = $('#stagePanel');
  panel.innerHTML = '<p class="muted">Vraagtypen en antwoordopties analyseren…</p>';
  try {
    const result = await api(`/api/exams/${state.examId}/question-analysis`);

    // Houd de antwoordopties per vraag als gestructureerde gegevens bij.
    // Een optie heeft een letter, optionele tekst en optioneel een afbeelding.
    // Daardoor kunnen grafieken, schema's en andere beeldopties naast gewone
    // tekstopties bestaan zonder OCR als verplichte tussenstap.
    const optionState = new Map(result.questions.map(question => [
      Number(question.question_number),
      (question.options || []).map(option => ({...option})).sort((a, b) => a.letter.localeCompare(b.letter))
    ]));
    // Zodra de docent de antwoordoptielijst zelf wijzigt, bewaren we die
    // lijst als expliciete keuze. Anders kan een verwijderde OCR-optie bij
    // het heropenen ongemerkt opnieuw verschijnen.
    const optionReviewState = new Set(
      result.questions.filter(question => question.options_reviewed).map(question => Number(question.question_number))
    );
    let activeCrop = null;

    const notifyOptionChange = card => {
      // De bestaande autosave luistert naar change-events op formuliervelden.
      // Een verborgen revisieveld laat ook acties zonder tekstinvoer (zoals
      // het toevoegen of uitsnijden van een afbeelding) direct opslaan.
      const questionNumber = Number(card.dataset.analysisCard);
      const reviewed = card.querySelector(`[data-analysis-reviewed="${questionNumber}"]`);
      if (reviewed) reviewed.checked = false;
      const revision = card.querySelector('[data-option-revision]');
      if (revision) {
        revision.value = String(Number(revision.value || 0) + 1);
        revision.dispatchEvent(new Event('change', {bubbles:true}));
      }
    };

    const renderOptionRows = (card, questionNumber) => {
      const host = card.querySelector('[data-option-list]');
      const options = (optionState.get(questionNumber) || []).sort((a, b) => a.letter.localeCompare(b.letter));
      const sourceQuestion = result.questions.find(item => Number(item.question_number) === questionNumber);
      host.innerHTML = options.map(option => `
        <div class="analysis-option-row" data-option-row="${questionNumber}" data-option-letter="${option.letter}">
          <strong class="analysis-option-letter">${option.letter}</strong>
          <div class="analysis-option-content">
            <input type="text" data-option-text="${questionNumber}" data-option-letter="${option.letter}"
              value="${escapeHtml(option.text || '')}" placeholder="Tekst (optioneel bij een afbeelding)"
              aria-label="Tekst van antwoordoptie ${option.letter}">
            ${option.image_data ? `<img class="analysis-option-preview" src="${option.image_data}" alt="Afbeelding bij antwoordoptie ${option.letter}">` : '<span class="analysis-option-no-image">Geen afbeelding toegevoegd</span>'}
            <small>${option.image_data ? (option.text ? 'Combinatie van tekst en afbeelding' : 'Afbeeldingsoptie') : 'Tekstoptie'}</small>
          </div>
          <div class="analysis-option-actions">
            <select class="analysis-option-source" data-option-crop-segment="${questionNumber}" data-option-letter="${option.letter}" aria-label="Bronpagina voor optie ${option.letter}">
              ${(sourceQuestion?.segments || []).map((segment, index) => `<option value="${index}">Pagina ${segment.page_number}</option>`).join('')}
            </select>
            <button type="button" class="quiet analysis-option-crop-existing" data-option-crop-existing="${questionNumber}" data-option-letter="${option.letter}">Afbeelding toevoegen / vervangen</button>
            <button type="button" class="quiet analysis-option-remove" data-option-remove="${questionNumber}" data-option-letter="${option.letter}" aria-label="Verwijder optie ${option.letter}">Verwijderen</button>
          </div>
        </div>`).join('') || '<p class="muted">Nog geen antwoordopties vastgelegd. Voeg tekstopties toe of snijd de opties uit de afbeelding.</p>';
      const addTextButton = card.querySelector('[data-option-add-text]');
      if (addTextButton) addTextButton.disabled = options.length >= 6;
    };

    const questionCards = result.questions.map(question => {
      const number = Number(question.question_number);
      const optionRows = (question.options || []).map(option => `
        <div class="analysis-option-row" data-option-row="${number}" data-option-letter="${option.letter}">
          <strong class="analysis-option-letter">${option.letter}</strong>
          <div class="analysis-option-content">
            <input type="text" data-option-text="${number}" data-option-letter="${option.letter}"
              value="${escapeHtml(option.text || '')}" placeholder="Tekst (optioneel bij een afbeelding)"
              aria-label="Tekst van antwoordoptie ${option.letter}">
            ${option.image_data ? `<img class="analysis-option-preview" src="${option.image_data}" alt="Afbeelding bij antwoordoptie ${option.letter}">` : '<span class="analysis-option-no-image">Geen afbeelding toegevoegd</span>'}
            <small>${option.image_data ? (option.text ? 'Combinatie van tekst en afbeelding' : 'Afbeeldingsoptie') : 'Tekstoptie'}</small>
          </div>
          <div class="analysis-option-actions">
            <select class="analysis-option-source" data-option-crop-segment="${number}" data-option-letter="${option.letter}" aria-label="Bronpagina voor optie ${option.letter}">
              ${question.segments.map((segment, index) => `<option value="${index}">Pagina ${segment.page_number}</option>`).join('')}
            </select>
            <button type="button" class="quiet analysis-option-crop-existing" data-option-crop-existing="${number}" data-option-letter="${option.letter}">Afbeelding toevoegen / vervangen</button>
            <button type="button" class="quiet analysis-option-remove" data-option-remove="${number}" data-option-letter="${option.letter}" aria-label="Verwijder optie ${option.letter}">Verwijderen</button>
          </div>
        </div>`).join('');
      return `
        <article class="analysis-card" data-analysis-card="${number}">
          <div class="fragment-heading"><h3>Vraag ${number}</h3><span class="muted">Voorstel: ${escapeHtml(question.question_type)}</span></div>
          <div class="analysis-fragment-sources">
            ${question.segments.map((segment, segmentIndex) => `
              <figure class="analysis-source-figure">
                <figcaption>Pagina ${segment.page_number}</figcaption>
                <div class="analysis-source-image" data-question="${number}" data-segment-index="${segmentIndex}">
                  <img loading="eager" src="${segment.url}" alt="Vraag ${number}, pagina ${segment.page_number}">
                  <div class="analysis-crop-selection" hidden></div>
                </div>
                <button type="button" class="quiet analysis-crop-button" data-option-crop="${number}" data-segment-index="${segmentIndex}">Afbeeldingsoptie uit deze pagina selecteren</button>
              </figure>`).join('')}
          </div>
          <div class="analysis-fields">
            <label>Vraagtype
              <select data-analysis-type="${number}">
                <option value="meerkeuze" ${question.question_type === 'meerkeuze' ? 'selected' : ''}>Meerkeuze</option>
                <option value="gesloten" ${question.question_type === 'gesloten' ? 'selected' : ''}>Gesloten antwoord</option>
                <option value="open" ${question.question_type === 'open' ? 'selected' : ''}>Open vraag</option>
                <option value="onbekend" ${question.question_type === 'onbekend' ? 'selected' : ''}>Nog onbekend</option>
              </select>
            </label>
            <label>Maximumscore (punten)
              <input type="number" min="0" max="20" step="1" value="${question.max_points ?? ''}" placeholder="Nog bepalen" data-analysis-points="${number}">
            </label>
          </div>
          <section class="analysis-options-editor" aria-label="Antwoordopties van vraag ${number}" ${question.question_type === 'meerkeuze' ? '' : 'hidden'}>
            <input type="hidden" data-option-revision="${number}" value="0">
            <div class="analysis-options-heading">
              <div><h4>Antwoordopties</h4><p>Een optie kan tekst, een afbeelding of beide bevatten.</p></div>
              <button type="button" class="quiet" data-option-add-text="${number}" ${(question.options || []).length >= 6 ? 'disabled' : ''}>Tekstantwoord toevoegen</button>
            </div>
            <div data-option-list>${optionRows || '<p class="muted">Nog geen antwoordopties vastgelegd. Voeg tekstopties toe of snijd de opties uit de afbeelding.</p>'}</div>
            <p class="analysis-crop-help" data-crop-help="${number}">Zijn de letters al herkend? Gebruik dan bij die letter de knop ‘Afbeelding toevoegen / vervangen’ en kies de bronpagina. Zijn er nog geen opties? Gebruik de knop onder de vraagafbeelding; nieuwe uitsneden krijgen A tot en met F in volgorde. Sleep daarna een kader om precies één antwoordoptie.</p>
          </section>
          <p class="analysis-reason">Type: ${escapeHtml(question.type_reason)} Score: ${escapeHtml(question.points_reason)}</p>
          ${question.closed_answer_form ? `<p class="analysis-reason closed-answer-form"><strong>Gesloten antwoordvorm:</strong> ${escapeHtml(question.closed_answer_form)}</p>` : ''}
          <details class="analysis-text"><summary>Tekstlaag uit dit fragment (hulpmiddel, niet leidend)</summary><pre>${escapeHtml(question.extracted_text || 'Geen selecteerbare tekstlaag aangetroffen. Controleer de afbeelding.')}</pre></details>
          <label class="review-warning"><input type="checkbox" data-analysis-reviewed="${number}" ${question.reviewed ? 'checked' : ''}> Ik heb vraag ${number}, het vraagtype, de maximumscore en alle antwoordopties visueel gecontroleerd.</label>
        </article>`;
    }).join('');

    panel.innerHTML = `
      <p class="eyebrow">FASE 2 · OPGAVENDOCUMENT</p>
      <h2>Vraagtype, punten en antwoordopties</h2>
      <p class="lead">Controleer het volledige vraagfragment. Antwoordopties mogen ook uitsluitend uit afbeeldingen bestaan. Snijd zulke opties rechtstreeks uit de zichtbare PDF-afbeelding; OCR is daarvoor niet nodig.</p>
      <div class="notice"><strong>${result.question_count} vragen</strong> klaar voor inhoudelijke controle. Als het puntenaantal niet expliciet uit de vraag blijkt, blijft het veld leeg in plaats van dat er een score wordt gegokt. Afbeeldingsuitsneden worden lokaal in de examenevidence bewaard.</div>
      ${questionCards}
      <div class="review-actions"><button class="primary" id="saveQuestionAnalysis" type="button">Controle opslaan</button><button class="primary" id="completeQuestionAnalysis" type="button" disabled>Vraaganalyse goedkeuren en doorgaan</button></div>
      <p id="questionAnalysisMessage" class="form-error" role="status"></p>`;

    const cards = [...panel.querySelectorAll('[data-analysis-card]')];
    // De docent beoordeelt iedere vraag bewust zelf; verberg deze controles
    // niet via prepareStageApproval zoals bij administratieve reviewstappen.

    // Event delegation houdt de bediening intact wanneer een optiekaart
    // opnieuw wordt opgebouwd na toevoegen, uitsnijden of verwijderen.
    panel.addEventListener('click', event => {
      const addButton = event.target.closest('[data-option-add-text]');
      if (addButton) {
        const number = Number(addButton.dataset.optionAddText);
        const options = optionState.get(number) || [];
        if (options.length >= 6) return;
        const used = new Set(options.map(option => option.letter));
        const letter = [...'ABCDEF'].find(candidate => !used.has(candidate));
        if (!letter) return;
        options.push({letter, text:''});
        optionState.set(number, options);
        optionReviewState.add(number);
        const card = addButton.closest('[data-analysis-card]');
        renderOptionRows(card, number);
        notifyOptionChange(card);
        refreshComplete();
        return;
      }

      const removeButton = event.target.closest('[data-option-remove]');
      if (removeButton) {
        const number = Number(removeButton.dataset.optionRemove);
        const letter = removeButton.dataset.optionLetter;
        optionState.set(number, (optionState.get(number) || []).filter(option => option.letter !== letter));
        optionReviewState.add(number);
        const card = removeButton.closest('[data-analysis-card]');
        renderOptionRows(card, number);
        notifyOptionChange(card);
        refreshComplete();
        return;
      }

      const cropButton = event.target.closest('[data-option-crop], [data-option-crop-existing]');
      if (cropButton) {
        const number = Number(cropButton.dataset.optionCrop || cropButton.dataset.optionCropExisting);
        const options = optionState.get(number) || [];
        const targetLetter = cropButton.dataset.optionLetter || null;
        const nextLetter = [...'ABCDEF'].find(candidate => !options.some(option => option.letter === candidate));
        if (!targetLetter && (!nextLetter || options.length >= 6)) {
          $('#questionAnalysisMessage').textContent = `Vraag ${number} heeft al zes antwoordopties. Verwijder eerst een optie als er een correctie nodig is.`;
          return;
        }
        const card = cropButton.closest('[data-analysis-card]');
        const sourceSelector = targetLetter
          ? card.querySelector(`[data-option-crop-segment="${number}"][data-option-letter="${targetLetter}"]`)
          : null;
        const segmentIndex = Number(cropButton.dataset.segmentIndex ?? sourceSelector?.value ?? 0);
        activeCrop = {questionNumber:number, segmentIndex, letter:targetLetter || nextLetter};
        panel.querySelectorAll('.analysis-source-image').forEach(source => {
          source.classList.toggle('is-cropping',
            Number(source.dataset.question) === number && Number(source.dataset.segmentIndex) === activeCrop.segmentIndex);
        });
        const help = panel.querySelector(`[data-crop-help="${number}"]`);
        help.textContent = targetLetter
          ? `Selectiemodus actief voor optie ${targetLetter}: sleep een kader om de afbeelding. Druk op Escape om te annuleren.`
          : `Selectiemodus actief voor de volgende vrije letter ${nextLetter}: sleep een kader om de antwoordoptie. Druk op Escape om te annuleren.`;
        $('#questionAnalysisMessage').textContent = targetLetter
          ? `Selecteer nu de afbeelding voor optie ${targetLetter} van vraag ${number}.`
          : `Selecteer nu met de muis antwoordoptie ${nextLetter || ''} uit vraag ${number}.`;
      }
    });

    panel.addEventListener('keydown', event => {
      if (event.key !== 'Escape' || !activeCrop) return;
      const number = activeCrop.questionNumber;
      activeCrop = null;
      // Een Escape tijdens het slepen beëindigt ook de lopende pointerselectie.
      // Zo kan een later pointerup-event geen half afgebroken uitsnede opslaan.
      dragSelection = null;
      panel.querySelectorAll('.analysis-source-image').forEach(source => {
        source.classList.remove('is-cropping');
        const overlay = source.querySelector('.analysis-crop-selection');
        if (overlay) overlay.hidden = true;
      });
      const help = panel.querySelector(`[data-crop-help="${number}"]`);
      if (help) help.textContent = 'Selectie geannuleerd. Je kunt een andere afbeelding kiezen.';
      $('#questionAnalysisMessage').textContent = 'Selectie van de afbeeldingsoptie geannuleerd.';
    });

    panel.addEventListener('input', event => {
      const field = event.target.closest('[data-option-text]');
      if (!field) return;
      const number = Number(field.dataset.optionText);
      const letter = field.dataset.optionLetter;
      const option = (optionState.get(number) || []).find(item => item.letter === letter);
      if (option) option.text = field.value;
      optionReviewState.add(number);
      const reviewed = panel.querySelector(`[data-analysis-reviewed="${number}"]`);
      if (reviewed) reviewed.checked = false;
      refreshComplete();
    });

    // Selecteer met slepen een rechthoek op de echte fragmentafbeelding.
    // De selectiecoördinaten worden teruggerekend naar de intrinsieke
    // afbeeldingspixels; daardoor blijft de uitsnede scherp en onafhankelijk
    // van de breedte waarop de afbeelding op het scherm wordt getoond.
    let dragSelection = null;
    panel.querySelectorAll('.analysis-source-image').forEach(source => {
      const img = source.querySelector('img');
      const overlay = source.querySelector('.analysis-crop-selection');
      const point = event => {
        const rect = img.getBoundingClientRect();
        return {
          x: Math.max(0, Math.min(rect.width, event.clientX - rect.left)),
          y: Math.max(0, Math.min(rect.height, event.clientY - rect.top)),
          width: rect.width,
          height: rect.height
        };
      };
      source.addEventListener('pointerdown', event => {
        if (!activeCrop || Number(source.dataset.question) !== activeCrop.questionNumber
            || Number(source.dataset.segmentIndex) !== activeCrop.segmentIndex) return;
        if (!img.complete || !img.naturalWidth || !img.naturalHeight) {
          $('#questionAnalysisMessage').textContent = 'De afbeelding wordt nog geladen. Probeer het opnieuw zodra zij zichtbaar is.';
          return;
        }
        event.preventDefault();
        const p = point(event);
        dragSelection = {source, img, overlay, startX:p.x, startY:p.y, currentX:p.x, currentY:p.y};
        overlay.hidden = false;
        overlay.style.left = `${p.x}px`;
        overlay.style.top = `${p.y}px`;
        overlay.style.width = '0';
        overlay.style.height = '0';
        source.setPointerCapture(event.pointerId);
      });
      source.addEventListener('pointermove', event => {
        if (!dragSelection || dragSelection.source !== source) return;
        const p = point(event);
        dragSelection.currentX = p.x;
        dragSelection.currentY = p.y;
        overlay.style.left = `${Math.min(dragSelection.startX,p.x)}px`;
        overlay.style.top = `${Math.min(dragSelection.startY,p.y)}px`;
        overlay.style.width = `${Math.abs(p.x-dragSelection.startX)}px`;
        overlay.style.height = `${Math.abs(p.y-dragSelection.startY)}px`;
      });
      source.addEventListener('pointercancel', () => {
        if (!dragSelection || dragSelection.source !== source) return;
        dragSelection = null;
        overlay.hidden = true;
      });
      source.addEventListener('pointerup', event => {
        if (!dragSelection || dragSelection.source !== source) return;
        const selection = dragSelection;
        dragSelection = null;
        if (source.hasPointerCapture(event.pointerId)) source.releasePointerCapture(event.pointerId);
        overlay.hidden = true;

        const left = Math.min(selection.startX, selection.currentX);
        const top = Math.min(selection.startY, selection.currentY);
        const width = Math.abs(selection.currentX - selection.startX);
        const height = Math.abs(selection.currentY - selection.startY);
        if (width < 12 || height < 12) {
          $('#questionAnalysisMessage').textContent = 'De uitsnede is te klein. Sleep een ruimer kader om de antwoordoptie.';
          return;
        }

        // Zet CSS-pixels om naar de oorspronkelijke pixels van de PDF-render.
        const scaleX = img.naturalWidth / selection.source.querySelector('img').getBoundingClientRect().width;
        const scaleY = img.naturalHeight / selection.source.querySelector('img').getBoundingClientRect().height;
        let sx = Math.round(left * scaleX);
        let sy = Math.round(top * scaleY);
        let sw = Math.round(width * scaleX);
        let sh = Math.round(height * scaleY);
        const maxDimension = 1200;
        const resize = Math.min(1, maxDimension / Math.max(sw, sh));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(sw * resize));
        canvas.height = Math.max(1, Math.round(sh * resize));
        const context = canvas.getContext('2d');
        context.drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
        // Gebruik PNG in plaats van JPEG: dunne lijnen, stippellijnen en
        // kleine labels in grafieken/respirogrammen blijven zo scherp. Alleen
        // wanneer de PNG te groot wordt, verkleinen we de uitsnede proportioneel.
        let imageData = canvas.toDataURL('image/png');
        if (imageData.length > 1_800_000) {
          const smallerCanvas = document.createElement('canvas');
          smallerCanvas.width = Math.max(1, Math.round(canvas.width * 0.7));
          smallerCanvas.height = Math.max(1, Math.round(canvas.height * 0.7));
          smallerCanvas.getContext('2d').drawImage(
            canvas, 0, 0, canvas.width, canvas.height,
            0, 0, smallerCanvas.width, smallerCanvas.height
          );
          imageData = smallerCanvas.toDataURL('image/png');
        }
        if (imageData.length > 2_000_000) {
          $('#questionAnalysisMessage').textContent = 'Deze uitsnede is te groot om veilig op te slaan. Maak een kleiner kader.';
          return;
        }

        const number = activeCrop.questionNumber;
        const options = optionState.get(number) || [];
        const used = new Set(options.map(option => option.letter));
        const letter = activeCrop.letter || [...'ABCDEF'].find(candidate => !used.has(candidate));
        if (!letter) {
          $('#questionAnalysisMessage').textContent = 'Alle zes antwoordletters zijn al in gebruik.';
          return;
        }
        const existingOption = options.find(option => option.letter === letter);
        if (existingOption) {
          // Koppel de uitsnede aan de gekozen bestaande letter. Dit is nodig
          // wanneer OCR de labels A-D al als tekstopties heeft voorgesteld.
          existingOption.image_data = imageData;
          existingOption.option_type = existingOption.text ? 'combinatie' : 'afbeelding';
        } else {
          options.push({letter, text:'', option_type:'afbeelding', image_data:imageData});
        }
        optionState.set(number, options);
        optionReviewState.add(number);
        activeCrop = null;
        source.classList.remove('is-cropping');
        const card = panel.querySelector(`[data-analysis-card="${number}"]`);
        renderOptionRows(card, number);
        card.querySelector(`[data-crop-help="${number}"]`).textContent =
          `Afbeeldingsoptie ${letter} toegevoegd. Je kunt eventueel nog tekst bij deze optie invullen.`;
        $('#questionAnalysisMessage').textContent = `Afbeeldingsoptie ${letter} van vraag ${number} toegevoegd.`;
        notifyOptionChange(card);
        refreshComplete();
      });
    });

    const reviewedInputs = () => [...panel.querySelectorAll('[data-analysis-reviewed]')];
    const getOptionIssues = () => {
      const issues = [];
      for (const card of cards) {
        const number = Number(card.dataset.analysisCard);
        const type = card.querySelector(`[data-analysis-type="${number}"]`).value;
        const options = optionState.get(number) || [];
        if (type !== 'meerkeuze') continue;
        if (options.length < 2) {
          issues.push(`vraag ${number}: minder dan twee antwoordopties`);
          continue;
        }
        const incomplete = options.filter(option => !String(option.text || '').trim() && !option.image_data);
        if (incomplete.length) issues.push(`vraag ${number}: optie(s) ${incomplete.map(option=>option.letter).join(', ')} zijn leeg`);
      }
      return issues;
    };
    const refreshComplete = () => {
      const allReviewed = reviewedInputs().length === result.question_count
        && reviewedInputs().every(input => input.checked);
      const optionIssues = getOptionIssues();
      $('#completeQuestionAnalysis').disabled = !allReviewed || optionIssues.length > 0;
      const warning = panel.querySelector('#questionAnalysisMessage');
      if (optionIssues.length && allReviewed) {
        warning.textContent = 'Nog niet compleet: ' + optionIssues.join('; ') + '.';
      }
    };
    reviewedInputs().forEach(input => input.addEventListener('change', refreshComplete));
    // Elke inhoudelijke wijziging na een eerdere review maakt die review
    // ongeldig. De docent moet de aangepaste vraag opnieuw visueel afvinken.
    panel.querySelectorAll('[data-analysis-type], [data-analysis-points]').forEach(input => {
      input.addEventListener('change', () => {
        const number = Number(input.dataset.analysisType ?? input.dataset.analysisPoints);
        const reviewed = panel.querySelector(`[data-analysis-reviewed="${number}"]`);
        if (reviewed) reviewed.checked = false;
        if (input.dataset.analysisType) {
          const editor = panel.querySelector(`[data-analysis-card="${number}"] .analysis-options-editor`);
          if (editor) editor.hidden = input.value !== 'meerkeuze';
        }
        refreshComplete();
      });
    });
    refreshComplete();

    const collect = () => cards.map(card => {
      const number = Number(card.dataset.analysisCard);
      const rawPoints = card.querySelector(`[data-analysis-points="${number}"]`).value.trim();
      const options = (optionState.get(number) || []).map(option => ({
        letter:option.letter,
        text:String(card.querySelector(`[data-option-text="${number}"][data-option-letter="${option.letter}"]`)?.value ?? option.text ?? '').trim(),
        ...(option.image_data ? {image_data:option.image_data} : {})
      }));
      return {
        question_number:number,
        question_type:card.querySelector(`[data-analysis-type="${number}"]`).value,
        max_points:rawPoints === '' ? null : Number(rawPoints),
        options,
        options_reviewed:optionReviewState.has(number),
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
    let completingQuestionAnalysis=false;
    $('#completeQuestionAnalysis').addEventListener('click', async () => {
      const button=$('#completeQuestionAnalysis');
      if(completingQuestionAnalysis) return;
      completingQuestionAnalysis=true;
      button.disabled=true;
      button.textContent='Review opslaan en stap afronden…';
      $('#questionAnalysisMessage').textContent='De gecontroleerde vragen worden opgeslagen. Dit kan even duren…';
      try {
        const optionIssues = getOptionIssues();
        if (optionIssues.length) throw new Error('Controleer eerst de antwoordopties: ' + optionIssues.join('; ') + '.');
        const saved = panel._stageAutoSaveFlush ? await panel._stageAutoSaveFlush() : await save();
        if (!saved.complete) throw new Error('Controleer eerst alle vragen.');
        await api(`/api/exams/${state.examId}/steps/opgaven_analyse/complete`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({reviewed:true, reviewed_all_questions:true, reviewed_count:saved.reviewed_count})
        });
        $('#questionAnalysisMessage').textContent='Vraaganalyse afgerond. Workflow wordt bijgewerkt…';
        await openWorkspace(state.examId);
      } catch (error) {
        completingQuestionAnalysis=false;
        button.textContent='Vraaganalyse goedkeuren en doorgaan';
        refreshComplete();
        $('#questionAnalysisMessage').textContent = error.message;
      }
    });
  } catch (error) {
    panel.innerHTML = `<h2>Vraagtype, punten en antwoordopties</h2><p class="form-error">${escapeHtml(error.message)}</p>`;
  }
}