import { chromium } from '../../frontend/node_modules/@playwright/test/index.mjs';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const imageDir = new URL('../../resources/images/', import.meta.url);
const bounds = JSON.parse(readFileSync(new URL('./agileplanner_llmops_architecture.bounds.json', import.meta.url), 'utf8'));
const svg = readFileSync(new URL('agileplanner_llmops_architecture.svg', imageDir), 'utf8');
const pngPath = fileURLToPath(new URL('agileplanner_llmops_architecture.png', imageDir));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 3000, height: 2020 }, deviceScaleFactor: 2 });
  await page.setContent(`<style>html,body{margin:0;padding:0;background:#080F1F}svg{display:block}</style>${svg}`);
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(async () => {
    await Promise.all([...document.querySelectorAll('image')].map(async (el) => {
      const img = new Image();
      img.src = el.getAttribute('href');
      await img.decode();
    }));
  });
  const issues = await page.evaluate((bounds) => {
    const errors = [];
    for (const el of document.querySelectorAll('text[data-check]')) {
      const b = el.getBBox();
      const entry = bounds[Number(el.dataset.check)];
      if (b.x < 0 || b.y < 0 || b.x+b.width > 3000 || b.y+b.height > 2020) errors.push(`Off canvas: ${entry.text}`);
      if (entry.maxWidth && b.width > entry.maxWidth) errors.push(`Text overflow: ${entry.text} (${b.width} > ${entry.maxWidth})`);
    }
    if (document.querySelectorAll('svg svg').length !== 17) errors.push('Technology SVG icons are missing');
    return errors;
  }, bounds);
  if (issues.length) throw new Error(JSON.stringify(issues, null, 2));
  await page.screenshot({ path: pngPath, fullPage: true });
  console.log(JSON.stringify({ labels: bounds.length, errors: issues, pngPath, width: 6000, height: 4040 }));
} finally {
  await browser.close();
}
