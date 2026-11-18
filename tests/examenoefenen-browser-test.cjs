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
      return { first: get(1)?.repeatedContext || '', followup: get(2)?.repeatedContext || '', laterFollowup: get(3)?.repeatedContext || '', nextContext: get(10)?.repeatedContext || '', questionCount: questions.filter(q => !q.repeatedContext).length };
    });
    assert.match(contextAudit.first, /Een nieuwe hartklep/);
    assert.match(contextAudit.followup, /Een nieuwe hartklep/);
    assert.match(contextAudit.followup, /Twee mogelijke hartafwijkingen/);
    assert.match(contextAudit.laterFollowup, /Een nieuwe hartklep/);
    assert.doesNotMatch(contextAudit.nextContext, /Een nieuwe hartklep/);
    assert.match(contextAudit.nextContext, /Op jacht met SnailSnap/);
    assert.equal(contextAudit.questionCount, 0, 'Iedere kaart moet een herhaalde context hebben');
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
