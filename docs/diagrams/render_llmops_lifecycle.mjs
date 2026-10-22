// Render the SVG at 2× resolution and validate every text element fits the canvas.
// Run with Node.js and the frontend's installed Playwright package.
import { chromium } from '../../frontend/node_modules/@playwright/test/index.mjs';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const svgPath = fileURLToPath(new URL('../../resources/images/agileplanner_llmops_lifecycle.svg', import.meta.url));
const pngPath = fileURLToPath(new URL('../../resources/images/agileplanner_llmops_lifecycle.png', import.meta.url));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 2600, height: 1640 }, deviceScaleFactor: 2 });
  await page.setContent(`<style>html,body{margin:0;padding:0;background:#080F1F}svg{display:block}</style>${readFileSync(svgPath, 'utf8')}`);
  await page.evaluate(() => document.fonts.ready);
  const problems = await page.evaluate(() => {
    const all = [...document.querySelectorAll('text')];
    const errors = [];
    for (const el of all) {
      const b = el.getBBox();
      if (b.x < 0 || b.y < 0 || b.x+b.width > 2600 || b.y+b.height > 1640) errors.push(`Off canvas: ${el.textContent}`);
      // Lifecycle cards have a deliberately shared 318px text column.
      if (b.y > 520 && b.y < 730 && b.width > 318) errors.push(`Card overflow: ${el.textContent} (${b.width}px)`);
    }
    return { labels: all.length, errors };
  });
  if (problems.errors.length) throw new Error(JSON.stringify(problems, null, 2));
  await page.screenshot({ path: pngPath, fullPage: true });
  console.log(JSON.stringify({ ...problems, pngPath, width: 5200, height: 3280 }));
} finally {
  await browser.close();
}
