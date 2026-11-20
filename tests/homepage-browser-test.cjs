const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");

(async () => {
  fs.mkdirSync("artifacts", { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(() => localStorage.setItem("bioAudience", "Beide"));
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));

  try {
    await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
    await page.waitForFunction(() => document.querySelector("#count")?.textContent.includes("48"));
    const initialCount = await page.locator("#count").innerText();
    assert.match(initialCount, /48 bron/);

    const desktopLayout = await page.evaluate(() => ({
      viewport: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      groupColumns: getComputedStyle(document.querySelector("#science-filter-groups")).gridTemplateColumns.split(" ").length,
      fieldsPerGroup: getComputedStyle(document.querySelector("#science-filters")).gridTemplateColumns.split(" ").length,
      searchColumns: getComputedStyle(document.querySelector(".search-row")).gridTemplateColumns.split(" ").length,
      duplicateIds: [...document.querySelectorAll("[id]")].map(el => el.id).filter((id, i, ids) => ids.indexOf(id) !== i)
    }));
    assert.equal(desktopLayout.groupColumns, 2, "Desktop: de twee filtergroepen moeten naast elkaar staan");
    assert.equal(desktopLayout.fieldsPerGroup, 3, "Desktop: de drie filters per groep moeten in één rij staan");
    assert.equal(desktopLayout.searchColumns, 3, "Desktop: zoekterm, waardering en wissen moeten één bedieningsrij vormen");
    assert.ok(desktopLayout.documentWidth <= desktopLayout.viewport, "Desktop: horizontale overflow in de pagina");
    assert.deepEqual(desktopLayout.duplicateIds, [], "De pagina bevat dubbele element-ID's");
    await page.locator(".filter-shell").screenshot({ path: "artifacts/science-filters-desktop.png" });

    // Search must include curriculum codes and biological classification, not just titles.
    await page.locator("#search").fill("M5 DNA-replicatie");
    await page.waitForFunction(() => Number(document.querySelector("#count")?.textContent.match(/\d+/)?.[0] || 0) > 0);
    const curriculumSearchCount = Number((await page.locator("#count").innerText()).match(/\d+/)[0]);
    assert.ok(curriculumSearchCount < 48, "Zoeken op syllabuscode moet een gerichte selectie opleveren");

    await page.locator("#search").fill("");
    await page.locator("#concept").selectOption({ label: "Biodiversiteit en ecosystemen" });
    await page.waitForTimeout(100);
    const themeCount = Number((await page.locator("#count").innerText()).match(/\d+/)[0]);
    assert.ok(themeCount >= 5 && themeCount < 48, "Hoofdthemafilter moet meerdere, maar niet alle publicaties tonen");

    await page.locator("#level-filter").selectOption("Vwo");
    await page.locator("#evidence-filter").selectOption("Ondersteunend bewijs");
    await page.locator("#clear").click();
    await page.waitForFunction(() => document.querySelector("#count")?.textContent.includes("48"));
    assert.equal(await page.locator("#search").inputValue(), "");
    assert.equal(await page.locator("#concept").inputValue(), "all");
    assert.equal(await page.locator("#level-filter").inputValue(), "all");
    assert.equal(await page.locator("#evidence-filter").inputValue(), "all");
    assert.equal(await page.locator("#rating-filter").inputValue(), "all");

    // Mobile layout must stack the groups and controls without horizontal scrolling.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(100);
    const mobileLayout = await page.evaluate(() => ({
      viewport: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      groupColumns: getComputedStyle(document.querySelector("#science-filter-groups")).gridTemplateColumns.split(" ").length,
      fieldsPerGroup: getComputedStyle(document.querySelector("#science-filters")).gridTemplateColumns.split(" ").length,
      searchColumns: getComputedStyle(document.querySelector(".search-row")).gridTemplateColumns.split(" ").length
    }));
    assert.equal(mobileLayout.groupColumns, 1, "Mobiel: filtergroepen moeten onder elkaar staan");
    assert.equal(mobileLayout.fieldsPerGroup, 1, "Mobiel: filtervelden moeten onder elkaar staan");
    assert.equal(mobileLayout.searchColumns, 1, "Mobiel: zoekbediening moet één kolom gebruiken");
    assert.ok(mobileLayout.documentWidth <= mobileLayout.viewport, "Mobiel: horizontale overflow in de pagina");
    await page.locator(".filter-shell").screenshot({ path: "artifacts/science-filters-mobile.png" });

    assert.deepEqual(pageErrors, [], "JavaScript-fouten in de homepage: " + pageErrors.join(" | "));
    console.log(JSON.stringify({
      result: "PASS",
      initialCount,
      curriculumSearchCount,
      themeCount,
      desktopLayout,
      mobileLayout,
      screenshots: ["artifacts/science-filters-desktop.png", "artifacts/science-filters-mobile.png"],
      pageErrors
    }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
