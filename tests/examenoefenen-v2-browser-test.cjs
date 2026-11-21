// Browser smoke test for the isolated Examenoefenen v2 page.
//
// The real 519-question export is not committed yet. This test therefore serves
// deterministic fixture JSON for all twelve exam IDs and exercises the actual
// page in Chromium. It validates browser behavior, not the content of Claude's
// eventual exam dataset.
const { chromium } = require("playwright");

const EXAM_IDS = [
  "havo-2024-t1", "havo-2024-t2", "havo-2025-t1", "havo-2025-t2",
  "havo-2026-t1", "havo-2026-t2", "vwo-2024-t1", "vwo-2024-t2",
  "vwo-2025-t1", "vwo-2025-t2", "vwo-2026-t1", "vwo-2026-t2",
];

// A tiny valid PNG avoids network failures while preserving the page's real
// image-rendering path. The question content itself remains fixture data.
const ONE_PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p1sAAAAASUVORK5CYII=",
  "base64",
);

function makeExam(examId, examIndex) {
  const [level, year, timePeriod] = examId.split("-");
  const period = Number(timePeriod.slice(1));
  const questionCount = 43 + (examIndex < 3 ? 1 : 0);
  const questions = Array.from({ length: questionCount }, (_, index) => {
    const number = index + 1;
    const isMcq = number === 2;
    return {
      id: `${examId}-q${String(number).padStart(2, "0")}`,
      number,
      main_question_number: number,
      type: isMcq ? "mcq" : "open",
      context_ids: ["ctx-1"],
      snippet_file: `snippets/${examId}/q${String(number).padStart(2, "0")}.png`,
      snippet_size_px: { width: 1000, height: 400 },
      max_points_exam: 1,
      source_fragments: [{ source_pdf: "fixture-opgavenboekje.pdf", pdf_page: 2 }],
      answer_data: isMcq
        ? { correct_answer: "B", model_answer: "", scoring: [], remarks: [] }
        : {
            correct_answer: null,
            model_answer: "Een testantwoord met de kern van de uitleg.",
            scoring: [{ criterion: "Noemt het juiste biologische verband.", points: 1 }],
            remarks: [],
          },
      quality_check: { status: "fixture-only" },
    };
  });
  return {
    schema_version: "1.0",
    exam: { level, year: Number(year), period },
    source_documents: [],
    contexts: [{
      id: "ctx-1",
      title: "Testcontext",
      description: "Een context om de zoekfunctie en de contextweergave te testen.",
    }],
    questions,
  };
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.route("**/exam-data/claude-2024-2026/data/*.json", async route => {
      const url = new URL(route.request().url());
      const examId = url.pathname.split("/").pop().replace(/\.json$/, "");
      const index = EXAM_IDS.indexOf(examId);
      if (index < 0) return route.fulfill({ status: 404, body: "Unknown fixture exam" });
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(makeExam(examId, index)),
      });
    });
    await page.route("**/*.png", route => route.fulfill({
      status: 200,
      contentType: "image/png",
      body: ONE_PIXEL_PNG,
    }));

    await page.goto("http://127.0.0.1:8000/examenoefenen-v2-preview.html");
    await page.locator("#count").waitFor();
    await page.waitForFunction(() => document.querySelector("#count").textContent.includes("519 van 519"));

    // First question is an open question. The marking scheme must stay closed
    // until the learner has entered an answer.
    const rubric = page.locator("#rubric");
    await page.locator("#rubric summary").click();
    if (await rubric.evaluate(el => el.open)) throw new Error("Rubric opened before an answer was entered");
    await page.locator("#response").fill("Mijn onderbouwde antwoord.");
    await page.locator("#rubric summary").click();
    if (!(await rubric.evaluate(el => el.open))) throw new Error("Rubric did not open after an answer was entered");
    await page.locator("#score").fill("1");
    await page.locator("#score").dispatchEvent("change");
    const savedScore = await page.evaluate(() => JSON.parse(localStorage.getItem("bioExamV2Scores") || "{}"));
    if (Object.values(savedScore)[0] !== 1) throw new Error("Self-assessment score was not saved");

    // The type filter must isolate the MCQ fixtures, and explicit answer data
    // must enable the automatic check.
    await page.selectOption("#type", "mcq");
    await page.locator('input[name="choice"][value="B"]').check();
    await page.locator("#feedback").waitFor({ state: "visible" });
    const feedback = await page.locator("#feedback").textContent();
    if (!feedback.includes("Correct")) throw new Error("MCQ answer was not checked correctly");

    // Context search and level filtering must continue to work after rerender.
    await page.selectOption("#type", "");
    await page.selectOption("#level", "vwo");
    await page.locator("#search").fill("Testcontext");
    const count = await page.locator("#count").textContent();
    if (!count.includes("van 519 vragen") || count.startsWith("0 ")) {
      throw new Error("Context search or level filter did not return the expected fixture questions");
    }

    console.log("Examenoefenen v2 browser smoke test: OK (519 fixture questions, rubric gate, self-score, MCQ check, filters).");
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
