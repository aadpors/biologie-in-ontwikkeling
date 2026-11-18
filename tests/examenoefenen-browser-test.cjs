const { chromium } = require("playwright");
const assert = require("node:assert/strict");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  page.on("console", message => {
    if (message.type() === "error") pageErrors.push(message.text());
  });

  try {
    await page.goto("http://127.0.0.1:8000/examenoefenen.html", { waitUntil: "networkidle" });
    await page.waitForFunction(() => document.querySelector("#count")?.textContent.includes("519"));
    assert.match(await page.locator("#count").innerText(), /519 vragen/);
    await page.waitForFunction(() => typeof questions !== "undefined" && questions.length === 519 && questions.every(q => typeof q.repeatedContext === "string"));

    // Every question with a source-page context image must render that image,
    // not duplicate the same context as extracted text. Regression: Havo 2025-I Q27.
    await page.locator("#level").selectOption("Havo");
    await page.locator("#year").selectOption("2025");
    await page.locator("#period").selectOption("1");
    await page.locator("#questionType").selectOption("mcq");
    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 27); render(); });
    await page.waitForFunction(() => [...document.querySelectorAll(".exam-snippets img")].length >= 2);
    assert.equal(await page.locator(".sourceblock").count(), 0,
      "Havo 2025-I vraag 27: de algemene context moet als oorspronkelijke afbeelding worden getoond, niet als geëxtraheerde tekst");
    assert.equal(await page.locator(".exam-snippets img").count(), 2,
      "Havo 2025-I vraag 27: zowel context- als vraagafbeelding moeten zichtbaar zijn");
    const contextImageAudit = await page.evaluate(() => ({
      total: questions.length,
      withImageContext: questions.filter(q => (q.images || []).length >= 2 || ((q.images || []).length === 1 && /question-complete-.*\.jpg$/i.test(q.images[0]))).length,
      missingImageContext: questions.filter(q => !((q.images || []).length >= 2 || ((q.images || []).length === 1 && /question-complete-.*\.jpg$/i.test(q.images[0])))).map(q => q.id)
    }));
    assert.equal(contextImageAudit.total, 519);
    assert.deepEqual(contextImageAudit.missingImageContext, [],
      "Alle examenvragen moeten een afzonderlijke context- en vraagafbeelding hebben");

    // Binary statement questions use one mutually exclusive radio pair per row.
    const binaryInventory = await page.evaluate(() => ({
      total: questions.filter(q => q.binaryChoice).length,
      malformed: questions.filter(q => q.binaryChoice && (!q.binaryChoice.rows.length || q.binaryChoice.rows.some(row => !row.text))).map(q => q.id)
    }));
    assert.equal(binaryInventory.total, 72, "Alle genummerde juist/onjuist- en wel/niet-vragen, de tabelvraag en de benoemde en enkelvoudige binaire vraag moeten worden herkend");
    assert.deepEqual(binaryInventory.malformed, [], "Elke binaire keuzerij moet een uitspraak bevatten");
    const binaryKeyAudit = await page.evaluate(() => {
      const binary = questions.filter(q => q.binaryChoice);
      return {
        total: binary.length,
        missing: binary.filter(q => !Array.isArray(q.binaryCorrect) || q.binaryCorrect.length !== q.binaryChoice.rows.length || !Array.isArray(q.binaryScoreMap)).map(q => q.id),
        wrongMax: binary.filter(q => q.binaryScoreMap?.at(-1) !== q.points).map(q => q.id)
      };
    });
    assert.equal(binaryKeyAudit.total, 72);
    assert.deepEqual(binaryKeyAudit.missing, [], "Elke binaire vraag moet een antwoordmodel en puntenschaal uit het officiële CV hebben");
    assert.deepEqual(binaryKeyAudit.wrongMax, [], "De maximale score moet overeenkomen met het officiële CV");
    const legacyBinaryKeys = await page.evaluate(() => ["vw25-14","vw25t2-8","ha24-8","vw24-1","vw24t2-2"].map(id => ({id,found:questions.some(q=>q.id===id&&Array.isArray(q.binaryCorrect)&&q.binaryCorrect.length===q.binaryChoice?.rows.length)})));
    assert.deepEqual(legacyBinaryKeys.filter(x=>!x.found), [], "De oudere, handmatig ingevoerde binaire kaarten moeten eveneens hun officiële antwoordmodel behouden");



    await page.locator("#level").selectOption("Vwo");
    await page.locator("#year").selectOption("2024");
    await page.locator("#period").selectOption("1");
    await page.locator("#questionType").selectOption("open");
    await page.waitForFunction(() => document.querySelector(".qhead")?.textContent.includes("vraag 1"));
    assert.deepEqual(await page.locator(".binary-choice-table thead th").allTextContents(), ["Uitspraak", "Juist", "Onjuist"]);
    assert.equal(await page.locator(".binary-choice-table tbody tr").count(), 3);
    const firstBinaryRow = page.locator('.binary-choice-table [data-binary-row="0"]');
    await firstBinaryRow.locator('input[value="left"]').check();
    await firstBinaryRow.locator('input[value="right"]').check();
    assert.equal(await firstBinaryRow.locator('input:checked').count(), 1, "De twee opties binnen één uitspraak mogen niet tegelijk geselecteerd zijn");
    assert.equal(await firstBinaryRow.locator('input:checked').getAttribute("value"), "right");
    await page.locator('.binary-choice-table [data-binary-row="1"] input[value="left"]').check();
    const binaryQuestionId = await page.evaluate(() => questions.find(q => q.level === "Vwo" && q.year === "2024" && q.period === "1" && Number(q.n) === 1).id);
    const binarySaved = await page.evaluate(id => JSON.parse(localStorage.getItem("bioExamAnswersV2") || "{}")[id], binaryQuestionId);
    assert.deepEqual(binarySaved, {"0":"right","1":"left"});
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForFunction(() => document.querySelector(".binary-choice-table tbody tr")?.getAttribute("data-binary-row") === "0");
    assert.equal(await page.locator('.binary-choice-table [data-binary-row="0"] input:checked').getAttribute("value"), "right");
    assert.equal(await page.locator('.binary-choice-table [data-binary-row="1"] input:checked').getAttribute("value"), "left");

    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 12); render(); });
    assert.deepEqual(await page.locator(".binary-choice-table thead th").allTextContents(), ["Uitspraak", "Wel", "Niet"]);
    assert.equal(await page.locator(".binary-choice-table tbody tr").count(), 3);

    await page.locator("#level").selectOption("Vwo");
    await page.locator("#year").selectOption("2026");
    await page.locator("#period").selectOption("1");
    await page.locator("#questionType").selectOption("open");
    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 27); render(); });
    assert.deepEqual(await page.locator(".binary-choice-table thead th").allTextContents(), ["Uitspraak", "Wel", "Geen"]);
    assert.equal(await page.locator(".binary-choice-table tbody tr").count(), 4);

    await page.locator("#level").selectOption("Havo");
    await page.locator("#year").selectOption("2026");
    await page.locator("#period").selectOption("2");
    await page.locator("#questionType").selectOption("open");
    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 30); render(); });
    assert.equal(await page.locator(".binary-choice-table tbody tr").count(), 3);
    assert.match((await page.locator(".binary-choice-table tbody").innerText()).replace(/\s+/g, " "), /Isa[\s\S]*Kate[\s\S]*Mounir/);

    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 28); render(); });
    assert.equal(await page.locator(".binary-choice-table tbody tr").count(), 1);
    assert.equal(await page.locator(".binary-explanation textarea").count(), 1);
    assert.equal(await page.locator("#toggleCv").isDisabled(), true, "CV-knop moet geblokkeerd blijven totdat de uitleg is ingevuld");
    await page.locator('.binary-choice-table [data-binary-row="0"] input[value="left"]').check();
    assert.equal(await page.locator("#toggleCv").isDisabled(), true, "Alleen de binaire keuze is onvoldoende wanneer het CV ook een toelichting vereist");
    await page.locator(".binary-explanation textarea").fill("Het supplement is gemaakt door bacteriën en er zijn geen dieren gebruikt.");
    assert.equal(await page.locator("#toggleCv").isDisabled(), false);
    assert.match(await page.locator("#binaryFeedback").innerText(), /1 van 1 punten/);

    await page.locator("#reset").click();
    await page.waitForFunction(() => document.querySelector("#count")?.textContent.includes("519"));


    // Official CV scoring: three statements, threshold partial credit, CV gate and completion.
    await page.locator("#level").selectOption("Havo");
    await page.locator("#year").selectOption("2024");
    await page.locator("#period").selectOption("1");
    await page.locator("#questionType").selectOption("open");
    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 8); render(); });
    const cvGate = page.locator("#toggleCv");
    assert.equal(await cvGate.isDisabled(), true, "CV-knop mag niet actief zijn vóór beantwoording");
    const havoBinary = await page.evaluate(() => ({id:getFiltered()[currentIndex].id,correct:getFiltered()[currentIndex].binaryCorrect}));
    for (let i=0;i<havoBinary.correct.length;i++) {
      const value=i===2?(havoBinary.correct[i]==="left"?"right":"left"):havoBinary.correct[i];
      await page.locator('.binary-choice-table [data-binary-row="'+i+'"] input[value="'+value+'"]').check();
    }
    assert.equal(await cvGate.isDisabled(), false, "CV-knop moet actief worden na invullen van alle uitspraken");
    assert.match(await page.locator("#binaryFeedback").innerText(), /1 van 2 punten/, "CvTE-score: bij twee van drie juiste uitspraken is één punt toegekend");
    await cvGate.click();
    const cvViewed = await page.evaluate(id => JSON.parse(localStorage.getItem("bioExamCvViewedV1")||"{}")[id],havoBinary.id);
    assert.equal(cvViewed,true,"Openen van het CV moet de vraag als gemaakt registreren");
    assert.match(await page.locator("#selectionProgress").innerText(), /Gemaakt: 1 \/ .*punten: 1 \/ 2/);

    // The 2x2 digestion table awards one point per fully correct location pair.
    await page.locator("#level").selectOption("Havo");
    await page.locator("#year").selectOption("2026");
    await page.locator("#period").selectOption("1");
    await page.locator("#questionType").selectOption("open");
    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 29); render(); });
    assert.equal(await page.locator(".binary-choice-table tbody tr").count(), 4);
    const tableKey = await page.evaluate(() => getFiltered()[currentIndex].binaryCorrect);
    for (let i=0;i<4;i++) {
      const value=i<2?tableKey[i]:(i===2?(tableKey[i]==="left"?"right":"left"):tableKey[i]);
      await page.locator('.binary-choice-table [data-binary-row="'+i+'"] input[value="'+value+'"]').check();
    }
    assert.match(await page.locator("#binaryFeedback").innerText(), /1 van 2 punten/, "De tabelvraag kent één punt per volledig juiste locatiecombinatie toe");

    // Named binary statements use the same official automatic marking.
    await page.locator("#level").selectOption("Havo");
    await page.locator("#year").selectOption("2026");
    await page.locator("#period").selectOption("2");
    await page.locator("#questionType").selectOption("open");
    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 30); render(); });
    const namedKey = await page.evaluate(() => getFiltered()[currentIndex].binaryCorrect);
    for (let i=0;i<3;i++) await page.locator('.binary-choice-table [data-binary-row="'+i+'"] input[value="'+namedKey[i]+'"]').check();
    assert.match(await page.locator("#binaryFeedback").innerText(), /2 van 2 punten/);

    // Cards stay grouped by exam (year, time period, level), then follow original question order.
    const sortedCards = await page.evaluate(() => getFiltered().map(q => ({ year: Number(q.year), period: Number(q.period), level: q.level, n: Number(q.n) })));
    const levelOrder = { Havo: 0, Vwo: 1 };
    const sortKey = q => [q.year, q.period, levelOrder[q.level], q.n];
    for (let i = 1; i < sortedCards.length; i++) {
      const previous = sortKey(sortedCards[i - 1]);
      const current = sortKey(sortedCards[i]);
      let comparison = 0;
      for (let j = 0; j < previous.length; j++) {
        if (previous[j] !== current[j]) { comparison = previous[j] - current[j]; break; }
      }
      assert.ok(comparison <= 0, `Kaartvolgorde wijkt af bij positie ${i}: ${JSON.stringify(sortedCards[i - 1])} → ${JSON.stringify(sortedCards[i])}`);
    }

    // Shared context is carried forward to every follow-up card, then reset at a new context heading.
    const contextAudit = await page.evaluate(() => {
      const get = n => questions.find(q => q.level === 'Havo' && q.year === '2024' && q.period === '1' && Number(q.n) === n);
      const vwoHippo = questions.find(q => q.level === 'Vwo' && q.year === '2025' && q.period === '1' && Number(q.n) === 14);
      const havoNewContext = get(14);
      return { first: get(1)?.repeatedContext || '', followup: get(2)?.repeatedContext || '', laterFollowup: get(3)?.repeatedContext || '', nextContext: get(10)?.repeatedContext || '', havoNewContext: havoNewContext?.repeatedContext || '', vwoHippo: vwoHippo?.repeatedContext || '', questionCount: questions.filter(q => !q.repeatedContext).length, contextStarts: questions.filter(q => q.contextGroupStart).length };
    });
    assert.match(contextAudit.first, /Een nieuwe hartklep/);
    assert.match(contextAudit.followup, /Een nieuwe hartklep/);
    assert.match(contextAudit.followup, /Twee mogelijke hartafwijkingen/);
    assert.match(contextAudit.laterFollowup, /Een nieuwe hartklep/);
    assert.doesNotMatch(contextAudit.nextContext, /Een nieuwe hartklep/);
    assert.match(contextAudit.nextContext, /Op jacht met SnailSnap/);
    assert.match(contextAudit.havoNewContext, /Er zijn meerdere vlinders/);
    assert.doesNotMatch(contextAudit.havoNewContext, /Op jacht met SnailSnap/);
    assert.match(contextAudit.vwoHippo, /Hieronder staan uitspraken over de populatiegroei/);
    assert.doesNotMatch(contextAudit.vwoHippo, /Slangengifklieren uit het lab/);
    assert.equal(contextAudit.questionCount, 0, 'Elke kaart moet een herhaalde context hebben');
    assert.equal(contextAudit.contextStarts, 73, 'Alle 73 contextblokken uit de twaalf examens moeten expliciet zijn afgebakend');
    // Filters combine correctly and reset restores the full question set.
    await page.locator("#level").selectOption("Havo");
    await page.locator("#year").selectOption("2026");
    await page.locator("#questionType").selectOption("mcq");
    await page.waitForTimeout(150);
    const filteredCount = await page.locator("#count").innerText();
    assert.match(filteredCount, /van [1-9]\d* vragen/);
    assert.match(await page.locator(".qhead").innerText(), /Havo 2026/);
    assert.match(await page.locator(".qhead").innerText(), /vraagtype|vraag/i);
    await page.locator("#reset").click();
    await page.waitForFunction(() => document.querySelector("#count")?.textContent.includes("519"));

    // A question must not inherit unrelated labels from the broad syllabus end term.
    await page.locator("#level").selectOption("Havo");
    await page.locator("#year").selectOption("2024");
    await page.locator("#period").selectOption("1");
    await page.locator("#questionType").selectOption("open");
    await page.waitForFunction(() => document.querySelector(".qhead")?.textContent.includes("vraag 1"));
    const questionOneTopics = await page.locator(".tags .tag").allTextContents();
    assert.deepEqual(questionOneTopics.filter(tag => !tag.startsWith("Eindterm")), ["Hart en bloedsomloop"],
      "Havo 2024 tijdvak 1 vraag 1 moet uitsluitend aan Hart en bloedsomloop gekoppeld zijn");

    // Audit the topic output for the complete 519-question set, not only the example.
    const topicAudit = await page.evaluate(() => {
      const rows = questions.map(q => ({ id: q.id, topics: onderwerpenVanVraag(q) }));
      return {
        total: rows.length,
        unclassified: rows.filter(row => row.topics.length === 0).map(row => row.id),
        overTagged: rows.filter(row => row.topics.length > 3)
      };
    });
    assert.equal(topicAudit.total, 519, "De volledige vragenset moet zijn meegenomen in de onderwerpaudit");
    assert.deepEqual(topicAudit.unclassified, [], "Alle 519 vragen moeten een passende onderwerpclassificatie hebben");
    assert.deepEqual(topicAudit.overTagged, [], "Er zijn vragen met meer dan drie onderwerpstags; controleer op overmatige rubricering");

    // Context words must not create unrelated subjects on two known edge cases.
    const edgeTopicAudit = await page.evaluate(() => ({
      beetle: onderwerpenVanVraag(questions.find(q => q.id === "ha24t2-3")),
      vitamin: onderwerpenVanVraag(questions.find(q => q.id === "vw26t2-mcq-17")),
      flamingo: onderwerpenVanVraag(questions.find(q => q.id === "vw26t2-open-39"))
    }));
    assert.deepEqual(edgeTopicAudit.beetle, ["Ecologie: kringlopen"],
      "Havo 2024 tijdvak 2 vraag 3 mag geen onterechte labels voor eutrofiëring, planten of uitscheiding krijgen");
    assert.deepEqual(edgeTopicAudit.vitamin, ["Hart en bloedsomloop"],
      "Vwo 2026 tijdvak 2 vraag 17 toetst de bloedroute, niet huid, uitscheiding of vertering");
    assert.deepEqual(edgeTopicAudit.flamingo, ["Ecologie"],
      "Vwo 2026 tijdvak 2 vraag 39 gaat over populatiegroei en draagkracht");

    // Previous/next and question dots move through the filtered sequence.
    const firstHeading = await page.locator(".qhead").innerText();
    await page.locator("#nextQuestion").click();
    const secondHeading = await page.locator(".qhead").innerText();
    assert.notEqual(secondHeading, firstHeading);
    await page.locator("#prevQuestion").click();
    assert.equal(await page.locator(".qhead").innerText(), firstHeading);
    await page.locator("#questionDots button").nth(2).click();
    assert.notEqual(await page.locator(".qhead").innerText(), firstHeading);

    // MCQ choice is stored and restored after a reload.
    await page.locator("#questionType").selectOption("mcq");
    await page.locator('input[type="radio"]').first().check();
    const mcqSaved = await page.evaluate(() => JSON.parse(localStorage.getItem("bioExamAnswersV2") || "{}"));
    assert.ok(Object.keys(mcqSaved).length > 0);
    const selectedValue = await page.locator('input[type="radio"]:checked').getAttribute("value");
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForFunction(() => document.querySelector("#count")?.textContent.includes("519"));
    await page.locator("#questionType").selectOption("mcq");
    await page.waitForSelector('input[type="radio"]');
    assert.equal(await page.locator('input[type="radio"]:checked').getAttribute("value"), selectedValue);

    // The explicit zero-point option is selectable and survives reload.
    await page.locator("#questionType").selectOption("open");
    await page.waitForSelector("[data-zero]");
    await page.locator("[data-zero]").check();
    const zeroSaved = await page.evaluate(() => JSON.parse(localStorage.getItem("bioExamZeroScoresV1") || "{}"));
    assert.ok(Object.values(zeroSaved).includes(true), "0 punten is niet opgeslagen");
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForFunction(() => document.querySelector("#count")?.textContent.includes("519"));
    await page.locator("#questionType").selectOption("open");
    await page.waitForSelector("[data-zero]");
    assert.equal(await page.locator("[data-zero]").isChecked(), true);
    await page.locator("[data-zero]").uncheck();

    // Open-answer text and self-assessment survive reload.
    await page.locator("#questionType").selectOption("open");
    await page.waitForSelector("textarea");
    const answer = "Browserpraktijktest: opgeslagen antwoord.";
    await page.locator("textarea").fill(answer);
    const scoreBox = page.locator("[data-point]").first();
    await scoreBox.check();
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForFunction(() => document.querySelector("#count")?.textContent.includes("519"));
    await page.locator("#questionType").selectOption("open");
    await page.waitForSelector("textarea");
    assert.equal(await page.locator("textarea").inputValue(), answer);
    assert.equal(await page.locator("[data-point]").first().isChecked(), true);

    // Regression checks for the three reported Havo 2025-I image defects.
    await page.locator("#level").selectOption("Havo");
    await page.locator("#year").selectOption("2025");
    await page.locator("#period").selectOption("1");
    await page.locator("#questionType").selectOption("open");
    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 26); render(); });
    const q26Images = await page.locator(".exam-snippets img").evaluateAll(images => images.map(img => img.getAttribute("src")));
    assert.ok((q26Images[0] || "").includes("context-ha25t1-q26-complete.jpg"));
    assert.ok((q26Images[1] || "").includes("question-ha25t1-26-only.jpg"));
    assert.equal(await page.locator(".exam-snippets img").count(), 2, "Vraag 26 moet context en vraagtekst als twee afzonderlijke uitsneden tonen");
    const q26QuestionImage = page.locator(".exam-snippets img").nth(1);
    await q26QuestionImage.evaluate(img => img.decode());
    const q26QuestionDimensions = await q26QuestionImage.evaluate(img => ({width:img.naturalWidth,height:img.naturalHeight}));
    assert.ok(q26QuestionDimensions.width > 500 && q26QuestionDimensions.height > 200,
      "Vraag 26 moet de drie genummerde uitspraken én de vraaginstructie bevatten; alleen de instructieregel is onvoldoende");

    await page.locator("#questionType").selectOption("mcq");
    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 27); render(); });
    const q27Context = await page.locator(".exam-snippets img").first().getAttribute("src");
    assert.ok((q27Context || "").includes("context-ha25t1-q27-complete.jpg"), "Vraag 27 moet de eigen zeehondencontext tonen, niet de Bajau-context van vraag 26");
    await page.locator(".exam-snippets img").first().evaluate(img => img.decode());

    await page.locator("#questionType").selectOption("open");
    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 29); render(); });
    const q29Question = page.locator(".exam-snippets img").nth(1);
    assert.ok((await q29Question.getAttribute("src") || "").includes("question-ha25t1-29-only.jpg"));
    await q29Question.evaluate(img => img.decode());
    const q29Dimensions = await q29Question.evaluate(img => ({width:img.naturalWidth,height:img.naturalHeight}));
    assert.ok(q29Dimensions.width > 500 && q29Dimensions.height > 20 && q29Dimensions.height < 120, "Vraag 29 moet volledig worden getoond, zonder afgesneden tekst of een te grote lege onderrand");

    // Vwo 2026-I Q18 contains two bullet-point marking criteria. The CV crop
    // must not stop at the introductory phrase or a right-aligned score value.
    await page.locator("#level").selectOption("Vwo");
    await page.locator("#year").selectOption("2026");
    await page.locator("#period").selectOption("1");
    await page.locator("#questionType").selectOption("open");
    await page.evaluate(() => { currentIndex = getFiltered().findIndex(q => Number(q.n) === 18); render(); });
    await page.locator("textarea").fill("Browsercontrole van het correctievoorschrift.");
    await page.locator("#toggleCv").click();
    const q18Cv = page.locator("#cvSnippet img");
    await q18Cv.evaluate(img => img.decode());
    const q18CvDimensions = await q18Cv.evaluate(img => ({width:img.naturalWidth,height:img.naturalHeight}));
    assert.ok(q18CvDimensions.width > 500 && q18CvDimensions.height > 100,
      "Vwo 2026-I vraag 18 moet beide officiële beoordelingscriteria bevatten, niet alleen de inleidende zin");

    // Every one of the 373 open questions must resolve to a local CV image,
    // and every generated image must be reachable over the same origin.
    const cvInventory = await page.evaluate(() => questions.filter(q => !Array.isArray(q.options) || q.options.length === 0).map(q => ({id:q.id,src:q.cvImage})));
    assert.equal(cvInventory.length, 373, "De CV-audit moet alle 373 open vragen omvatten");
    assert.deepEqual(cvInventory.filter(q => !q.src || !q.src.startsWith("exam-snippets/cv-") || !q.src.endsWith(".jpg")).map(q => q.id), [], "Elke open vraag moet een lokale CV-afbeelding hebben");
    const cvAssetFailures = [];
    for (let i = 0; i < cvInventory.length; i += 20) {
      const batch = await Promise.all(cvInventory.slice(i, i + 20).map(async q => {
        const response = await page.request.get(new URL(q.src, page.url()).toString());
        return response.status() === 200 && (response.headers()["content-type"] || "").toLowerCase().startsWith("image/jpeg") ? null : {id:q.id,src:q.src,status:response.status(),type:response.headers()["content-type"]};
      }));
      cvAssetFailures.push(...batch.filter(Boolean));
    }
    assert.deepEqual(cvAssetFailures, [], "Elke lokale CV-afbeelding moet daadwerkelijk laden; geen ontbrekende of niet-JPEG assets toegestaan");

    // Official correction-scheme snippets are connected to their questions and reveal on click.
    await page.locator("#level").selectOption("Havo");
    await page.locator("#year").selectOption("2024");
    await page.locator("#period").selectOption("1");
    await page.locator("#questionType").selectOption("open");
    await page.waitForFunction(() => document.querySelector(".qhead")?.textContent.includes("vraag 1"));
    const cvButton = page.locator("#toggleCv");
    assert.equal(await cvButton.count(), 1, "Knop voor het correctievoorschrift ontbreekt");
    await cvButton.click();
    const cvImage = page.locator("#cvSnippet img");
    await cvImage.evaluate(img => img.decode());
    const cvImageState = await cvImage.evaluate(img => ({ complete: img.complete, width: img.naturalWidth, height: img.naturalHeight }));
    assert.ok(cvImageState.complete && cvImageState.width > 0 && cvImageState.height > 0, JSON.stringify(cvImageState));

    // A question image must load at its natural dimensions.
    const imageState = await page.locator(".exam-snippets img").first().evaluate(img => ({
      complete: img.complete,
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight
    }));
    assert.ok(imageState.complete && imageState.naturalWidth > 0 && imageState.naturalHeight > 0, JSON.stringify(imageState));

    // Appendix links must resolve to actual PDFs.
    await page.locator("#level").selectOption("Havo");
    await page.locator("#year").selectOption("2025");
    await page.locator("#period").selectOption("1");
    await page.locator("#questionType").selectOption("open");
    let appendix = page.locator('a[href$="-u.pdf"]');
    for (let i = 0; i < 60 && await appendix.count() === 0; i++) {
      const heading = await page.locator(".qhead").innerText();
      if (/vraag 12\b/.test(heading)) break;
      await page.locator("#nextQuestion").click();
      appendix = page.locator('a[href$="-u.pdf"]');
    }
    assert.ok(await appendix.count() > 0, "Geen uitwerkbijlage-link gevonden bij de betreffende havo 2025-vraag");
    const appendixHref = await appendix.first().getAttribute("href");
    const appendixResponse = await page.request.get(new URL(appendixHref, page.url()).toString());
    assert.equal(appendixResponse.status(), 200, "Uitwerkbijlage is niet bereikbaar");
    assert.match(appendixResponse.headers()["content-type"] || "", /pdf/i);

    // The second appendix PDF is also linked from the vwo 2026 time-window questions.
    await page.locator("#level").selectOption("Vwo");
    await page.locator("#year").selectOption("2026");
    await page.locator("#period").selectOption("2");
    await page.locator("#questionType").selectOption("open");
    let vwoAppendix = page.locator('a[href="examens/vw-1018-a-26-2-u.pdf"]');
    for (let i = 0; i < 35 && await vwoAppendix.count() === 0; i++) {
      await page.locator("#nextQuestion").click();
      vwoAppendix = page.locator('a[href="examens/vw-1018-a-26-2-u.pdf"]');
    }
    assert.ok(await vwoAppendix.count() > 0, "Geen vwo 2026 tijdvak 2-uitwerkbijlage-link gevonden");
    const vwoAppendixResponse = await page.request.get(new URL(await vwoAppendix.first().getAttribute("href"), page.url()).toString());
    assert.equal(vwoAppendixResponse.status(), 200, "Vwo-uitwerkbijlage is niet bereikbaar");
    assert.match(vwoAppendixResponse.headers()["content-type"] || "", /pdf/i);

    assert.deepEqual(pageErrors, [], "Browserconsole bevat fouten: " + pageErrors.join(" | "));
    console.log(JSON.stringify({
      result: "PASS",
      totalQuestions: 519,
      filters: "PASS",
      topicAudit,
      navigation: "PASS",
      mcqPersistence: "PASS",
      openAnswerPersistence: "PASS",
      selfAssessmentPersistence: "PASS",
      imageLoading: imageState,
      cvAssetsChecked: cvInventory.length,
      appendices: [{ href: appendixHref, status: appendixResponse.status() }, { href: "examens/vw-1018-a-26-2-u.pdf", status: vwoAppendixResponse.status() }],
      pageErrors
    }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
