// End-to-end browser test against the real committed Claude dataset.
// This test deliberately uses real JSON and PNG files, not synthetic fixtures.
const { chromium } = require("playwright");

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const failedRequests = [];

  // Record failed network requests for the real exam JSON, snippets and source PDFs.
  page.on("requestfailed", request => {
    if (/exam-data|examens\//.test(request.url())) {
      failedRequests.push({ url: request.url(), error: request.failure()?.errorText });
    }
  });
  page.on("response", response => {
    if (response.status() >= 400 && /exam-data|examens\//.test(response.url())) {
      failedRequests.push({ url: response.url(), status: response.status() });
    }
  });

  try {
    await page.goto("http://127.0.0.1:8000/examenoefenen-v2-preview.html");

    // Wait until all twelve real JSON files have been combined into the 519-question set.
    await page.waitForFunction(
      () => document.querySelector("#count")?.textContent === "519 van 519 vragen",
      null,
      { timeout: 30000 }
    );

    // Select an open question explicitly. The initial question may be multiple choice.
    await page.selectOption("#type", "open");
    await page.waitForSelector("#response");

    // Verify that the original, committed PNG snippet is downloaded and decoded.
    const image = page.locator("#question img").first();
    await image.waitFor({ state: "visible" });
    await page.waitForFunction(() => {
      const img = document.querySelector("#question img");
      return img && img.complete && img.naturalWidth > 0;
    }, null, { timeout: 20000 });

    const imageInfo = await image.evaluate(img => ({
      src: img.getAttribute("src"),
      width: img.naturalWidth,
      height: img.naturalHeight
    }));
    if (!imageInfo.src.includes("exam-data/claude-2024-2026/snippets/")) {
      throw new Error("Preview does not use the real committed PNG: " + imageInfo.src);
    }

    // The official marking scheme must remain closed until the learner enters an answer.
    const rubric = page.locator("#rubric");
    await page.locator("#rubric summary").click();
    if (await rubric.evaluate(el => el.open)) {
      throw new Error("Open-question rubric became visible before an answer was entered");
    }

    await page.locator("#response").fill("Testantwoord voor de echte dataset.");
    await page.locator("#rubric summary").click();
    if (!(await rubric.evaluate(el => el.open))) {
      throw new Error("Open-question rubric did not open after an answer was entered");
    }

    // Check that self-assessment accepts a score within the question's maximum.
    const score = page.locator("#score");
    const maxScore = Number(await score.getAttribute("max"));
    await score.fill(String(Math.min(1, maxScore)));
    await score.dispatchEvent("change");

    // Select a real multiple-choice question and verify the answer interaction.
    await page.selectOption("#type", "mcq");
    await page.waitForSelector('input[name="choice"]');
    await page.locator('input[name="choice"]').first().check();
    await page.locator("#feedback").waitFor({ state: "visible" });
    const feedback = (await page.locator("#feedback").textContent())?.trim();
    if (!feedback) throw new Error("No feedback rendered for a real multiple-choice question");

    // Source PDF links should resolve to actual repository files.
    await page.selectOption("#type", "open");
    const pdfLinks = await page.locator('#question a[href^="examens/"]').evaluateAll(
      links => links.map(link => link.getAttribute("href"))
    );
    if (!pdfLinks.length) throw new Error("No source PDF links are shown for the selected real question");

    for (const href of pdfLinks) {
      const response = await page.request.get("http://127.0.0.1:8000/" + href);
      if (!response.ok()) {
        throw new Error("Source PDF does not resolve: " + href + " (" + response.status() + ")");
      }
    }

    if (failedRequests.length) {
      throw new Error("Failed real dataset/image/PDF requests: " + JSON.stringify(failedRequests.slice(0, 10)));
    }

    console.log(
      "Real-data browser test: OK; 519 real questions loaded, PNG decoded (" +
      imageInfo.width + "x" + imageInfo.height + "), open rubric gate, self-score, MCQ interaction and source PDFs."
    );
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
