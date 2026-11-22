// End-to-end browser test against the real committed Claude dataset.
// Unlike the fixture smoke test, this loads all 12 real JSON files and PNG snippets.
const { chromium } = require("playwright");

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const failedRequests = [];
  page.on("requestfailed", request => failedRequests.push({url:request.url(),error:request.failure()?.errorText}));
  page.on("response", response => {
    if (response.status() >= 400 && /exam-data|examens\//.test(response.url())) {
      failedRequests.push({url:response.url(),status:response.status()});
    }
  });

  try {
    await page.goto("http://127.0.0.1:8000/examenoefenen-v2-preview.html");
    await page.waitForFunction(() => document.querySelector("#count")?.textContent === "519 van 519 vragen", null, {timeout:30000});

    // Verify that all real exam JSONs were loaded, and that the first real snippet
    // resolves to a decoded image rather than a mocked or missing asset.
    const firstImage = page.locator("#question .snippet img");
    await firstImage.waitFor({state:"visible"});
    await page.waitForFunction(() => {
      const image = document.querySelector("#question .snippet img");
      return image && image.complete && image.naturalWidth > 0;
    }, null, {timeout:20000});
    const imageInfo = await firstImage.evaluate(img => ({
      src: img.getAttribute("src"),
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight,
    }));
    if (!imageInfo.src.includes("exam-data/claude-2024-2026/snippets/")) {
      throw new Error("The page is not using the committed real PNG snippets: " + imageInfo.src);
    }

    // Check a real open question: no rubric before a response, rubric after response.
    const rubric = page.locator("#rubric");
    await page.locator("#rubric summary").click();
    if (await rubric.evaluate(el => el.open)) throw new Error("Real open-question rubric opened before an answer");
    await page.locator("#response").fill("Testantwoord voor de echte dataset.");
    await page.locator("#rubric summary").click();
    if (!(await rubric.evaluate(el => el.open))) throw new Error("Real open-question rubric stayed closed after an answer");
    const score = page.locator("#score");
    const max = Number(await score.getAttribute("max"));
    await score.fill(String(Math.min(1,max)));
    await score.dispatchEvent("change");

    // A real MCQ with a declared correct answer must expose the answer controls.
    await page.selectOption("#type", "mcq");
    await page.locator('input[name="choice"]').first().check();
    await page.locator("#feedback").waitFor({state:"visible"});
    const feedback = await page.locator("#feedback").textContent();
    if (!feedback || !feedback.trim()) throw new Error("No feedback was rendered for a real MCQ");

    // Real source PDFs should be linked from the question card when the exam
    // metadata declares them, and their repository paths must resolve.
    await page.selectOption("#type", "");
    const pdfLinks = await page.locator("#question a[href^="examens/"]').evaluateAll(links => links.map(a => a.getAttribute("href")));
    if (pdfLinks.length === 0) throw new Error("No original exam/correction PDF links are shown for a real question");
    for (const href of pdfLinks) {
      const response = await page.request.get("http://127.0.0.1:8000/" + href);
      if (!response.ok()) throw new Error("Source PDF does not resolve: " + href + " (" + response.status() + ")");
    }

    if (failedRequests.length) throw new Error("Failed dataset/image/PDF requests: " + JSON.stringify(failedRequests.slice(0,10)));
    console.log("Real-data browser test: OK; 519 questions, real PNG decoded ("+imageInfo.naturalWidth+"x"+imageInfo.naturalHeight+"), open-question rubric gate, self-score, MCQ interaction, source PDFs.");
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
