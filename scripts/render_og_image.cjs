// Render the fixed SVG source; the website only serves the resulting PNG.
const { readFile } = require("node:fs/promises");
const { resolve } = require("node:path");
const { chromium } = require("playwright");

async function main() {
  const assetPath = resolve(__dirname, "../docs/assets/og-image");
  const svg = await readFile(`${assetPath}.svg`, "utf8");
  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  try {
    const page = await browser.newPage({
      viewport: { width: 1200, height: 630 },
      deviceScaleFactor: 1,
    });
    await page.setContent(`<html><head><style>body{margin:0}svg{display:block}</style></head><body>${svg}</body></html>`);
    await page.evaluate(() => document.fonts.ready);
    const problems = await page.evaluate(() => {
      const svg = document.querySelector("svg");
      const issues = [];
      if (!document.fonts.check('500 24px "Geist OG"')) issues.push("Embedded font did not load");
      if (svg.width.baseVal.value !== 1200 || svg.height.baseVal.value !== 630) {
        issues.push("Expected a 1200 × 630 SVG");
      }
      for (const text of svg.querySelectorAll("text")) {
        const box = text.getBBox();
        if (box.x < 70 || box.x + box.width > 1130 || box.y < 50 || box.y + box.height > 590) {
          issues.push(`Text outside safe area: ${text.textContent}`);
        }
      }
      return issues;
    });
    if (problems.length) throw new Error(problems.join("\n"));
    await page.locator("body > svg").screenshot({ path: `${assetPath}.png`, animations: "disabled" });
    console.log(`Rendered and checked ${assetPath}.png (1200 × 630)`);
  } finally {
    await browser.close();
  }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
