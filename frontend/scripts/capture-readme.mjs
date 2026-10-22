import { chromium, expect } from '@playwright/test';
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, mkdir, rm, readFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const output = join(root, 'resources/images');
await mkdir(join(root, 'resources/screenshots'), { recursive: true });
const data = await mkdtemp(join(root, 'resources/screenshots/run-'));
const mongoDatabase = `sprintlens_screenshots_${Date.now()}`;
const socket = createServer();
socket.listen(0, '127.0.0.1');
await once(socket, 'listening');
const port = socket.address().port;
await new Promise((done) => socket.close(done));
const base = `http://127.0.0.1:${port}`;
const server = spawn(join(root, '.venv/bin/python'), [
  '-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend',
  '--host', '127.0.0.1', '--port', String(port),
], {
  cwd: root,
  env: {
    ...process.env,
    JIRA_DATA_DIR: data,
    JIRA_MONGO_DATABASE: mongoDatabase,
    JIRA_STATIC_DIR: join(root, 'frontend/dist'),
    JIRA_AI_PROVIDER: process.env.SCREENSHOT_MODEL ? 'compatible' : 'disabled',
    JIRA_AI_MODEL: process.env.SCREENSHOT_MODEL || '',
    JIRA_AI_BASE_URL: process.env.SCREENSHOT_MODEL_BASE_URL || 'http://127.0.0.1:11434/v1',
    JIRA_AI_MODELS: '',
    JIRA_EMBEDDING_PROVIDER: 'local',
  },
  stdio: ['ignore', 'ignore', 'pipe'],
});
let logs = '';
server.stderr.on('data', (chunk) => { logs = (logs + chunk).slice(-4000); });
let browser;

try {
  await expect.poll(async () => {
    if (server.exitCode !== null) throw new Error(logs);
    try { return (await fetch(`${base}/api/health`)).ok; } catch { return false; }
  }, { timeout: 20_000 }).toBe(true);
  browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH } : {}),
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1040 }, deviceScaleFactor: 1,
    colorScheme: 'light', reducedMotion: 'reduce', locale: 'en-US', timezoneId: 'UTC',
  });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await mkdir(output, { recursive: true });
  async function capture(name) {
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: join(output, `readme_${name}.png`), fullPage: false, animations: 'disabled' });
    console.log(`Captured ${name}: 1440 × 1040`);
  }

  await page.goto(base);
  await expect(page.getByLabel('Jira CSV file')).toBeAttached();
  await capture('upload');
  const csv = await readFile(join(root, 'resources/demo/agileplanner-demo.csv'));
  await page.getByLabel('Jira CSV file').setInputFiles({ name: 'agileplanner-demo.csv', mimeType: 'text/csv', buffer: csv });
  await page.getByRole('button', { name: 'Explore my project' }).click();
  await expect(page.getByRole('heading', { name: 'Choose how your statuses appear.' })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('button', { name: 'Use original statuses', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Use original statuses', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your project, in focus.' })).toBeVisible();
  await page.getByLabel('Project', { exact: true }).selectOption('DEMO');
  await page.evaluate(() => scrollTo(0, 0));
  await expect(page.getByText('Where work stands', { exact: true })).toBeVisible();
  await capture('overview');
  await page.getByRole('link', { name: 'Sprint explorer', exact: true }).click();
  await expect(page.getByLabel('Sprint', { exact: true })).toHaveValue('Iteration 5');
  await expect(page.getByRole('button', { name: 'DEMO-100', exact: true })).toBeAttached();
  await page.evaluate(() => scrollTo(0, 0));
  await capture('sprint');
  await page.getByRole('link', { name: 'Backlog Management', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save rules and update report' })).toBeEnabled();
  await capture('backlog');
  await page.getByRole('link', { name: 'Sprint explorer', exact: true }).click();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  if (process.env.SCREENSHOT_MODEL) {
    await expect(chat.getByLabel('Message Sprint Agent')).toBeEnabled({ timeout: 20_000 });
    await chat.getByLabel('Message Sprint Agent').fill('Summarize this sprint');
    await chat.getByRole('button', { name: 'Send message', exact: true }).click();
    await expect(chat.locator('.agent-assistant').last()).not.toBeEmpty({ timeout: 420_000 });
    await expect(chat.getByLabel('Message Sprint Agent')).toBeEnabled({ timeout: 420_000 });
  }
  await capture('agent');
  await chat.getByRole('button', { name: 'Message context', exact: true }).click();
  await capture('agent_context');
  await chat.getByRole('button', { name: 'Message context', exact: true }).click();
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await capture('agent_settings');
  if (errors.length) throw new Error(errors.join('\n'));
} finally {
  await browser?.close();
  if (server.exitCode === null) {
    const closed = once(server, 'exit');
    server.kill('SIGTERM');
    await closed;
  }
  spawnSync(join(root, '.venv/bin/python'), ['-c', 'import os; from pymongo import MongoClient; c=MongoClient(os.environ.get("JIRA_MONGO_URI", "mongodb://127.0.0.1:27018")); c.drop_database(os.environ["JIRA_MONGO_DATABASE"]); c.close()'], { env: { ...process.env, JIRA_MONGO_DATABASE: mongoDatabase }, stdio: 'ignore' });
  await rm(data, { recursive: true, force: true });
}
