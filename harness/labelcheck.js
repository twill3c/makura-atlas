const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto("http://127.0.0.1:8123/", { waitUntil: "networkidle" });
  const res = await page.evaluate(() => {
    const labels = [...document.querySelectorAll("#scatter .dot-label")];
    const boxes = labels.map((l) => {
      const b = l.getBBox();
      return { t: l.textContent, x: b.x, y: b.y, w: b.width, h: b.height };
    });
    let overlapPairs = 0;
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) overlapPairs++;
      }
    return { labelCount: labels.length, overlapPairs, hasPlacer: typeof window.__placerMissing === "undefined" };
  });
  console.log(JSON.stringify(res));
  await browser.close();
})();
