const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));

  await page.goto("http://127.0.0.1:8123/", { waitUntil: "networkidle" });

  const counts = await page.evaluate(() => ({
    scatterDots: document.querySelectorAll("#scatter .dot").length,
    tagChips: document.querySelectorAll("#tag-filter .chip").length,
    kaitaiChips: document.querySelectorAll("#kaitai-chips .chip").length,
    footer: !!document.querySelector(".app-footer"),
  }));
  console.log("zahyo:", JSON.stringify(counts));
  await page.screenshot({ path: process.env.SHOT_DIR + "/zahyo.png" });

  // 座標: 点をクリックして縦書き詳細
  await page.locator('#scatter .dot[data-id="nikuki-mono"]').click();
  const vertical = await page.evaluate(() =>
    getComputedStyle(document.querySelector("#detail-zahyo .tatext")).writingMode);
  console.log("writing-mode:", vertical);

  // 解体
  await page.locator('.tab[data-view="kaitai"]').click();
  const kaitaiDots = await page.evaluate(() => document.querySelectorAll("#kaitai-scatter .dot").length);
  console.log("kaitai dots:", kaitaiDots);
  await page.locator("#kaitai-scatter .dot").first().click();
  await page.screenshot({ path: process.env.SHOT_DIR + "/kaitai.png" });

  // 沈黙
  await page.locator('.tab[data-view="chinmoku"]').click();
  const tl = await page.evaluate(() => ({
    dots: document.querySelectorAll("#timeline .dot").length,
    bands: document.querySelectorAll("#timeline rect").length,
  }));
  console.log("chinmoku:", JSON.stringify(tl));
  await page.locator("#timeline .dot").last().click();
  await page.screenshot({ path: process.env.SHOT_DIR + "/chinmoku.png" });

  // 升目
  await page.locator('.tab[data-view="masume"]').click();
  const grid = await page.evaluate(() => ({
    cells: document.querySelectorAll(".masume-cell").length,
    filled: document.querySelectorAll(".masume-cell:not(.is-empty)").length,
  }));
  console.log("masume:", JSON.stringify(grid));
  await page.locator(".masume-cell:not(.is-empty)").first().click();
  await page.screenshot({ path: process.env.SHOT_DIR + "/masume.png" });

  console.log("console errors:", errors.length ? errors : "none");
  await browser.close();
  process.exit(errors.length ? 1 : 0);
})();
