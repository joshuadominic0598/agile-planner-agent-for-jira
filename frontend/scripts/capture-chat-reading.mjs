/** Capture one real, local-model conversation; never substitute a canned answer. */
import { chromium, expect } from '@playwright/test';
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const model = process.env.SCREENSHOT_MODEL || 'qwen3:8b';
const modelBase = process.env.SCREENSHOT_MODEL_BASE_URL || 'http://127.0.0.1:11434/v1';
const artifacts = join(root, 'resources/screenshots/chat-reading');
await mkdir(artifacts, { recursive: true });
const data = await mkdtemp(join(artifacts, 'run-'));
const database = `sprintlens_screenshots_reading_${Date.now()}`;
const socket = createServer();
socket.listen(0, '127.0.0.1');
await once(socket, 'listening');
const port = socket.address().port;
await new Promise((done) => socket.close(done));
const base = `http://127.0.0.1:${port}`;
const server = spawn(
  join(root, '.venv/bin/python'),
  ['-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', String(port)],
  {
    cwd: root,
    env: {
      ...process.env,
      JIRA_DATA_DIR: data,
      JIRA_MONGO_DATABASE: database,
      JIRA_STATIC_DIR: join(root, 'frontend/dist'),
      JIRA_AI_PROVIDER: 'compatible',
      JIRA_AI_MODEL: model,
      JIRA_AI_MODELS: '',
      JIRA_AI_BASE_URL: modelBase,
      JIRA_AI_MODEL_ALIASES: JSON.stringify(
        model === 'qwen3:8b' ? { 'qwen3:8b': 'sprintlens-qwen3:8b' } : {}
      ),
      JIRA_AI_MODEL_CONTEXT_WINDOWS: JSON.stringify({ [model]: 32768 }),
      JIRA_AI_REASONING_EFFORT: 'none',
      JIRA_AI_API_KEY: '',
      OPENAI_API_KEY: '',
      JIRA_AI_WEB_ENABLED: 'false',
      JIRA_EMBEDDING_PROVIDER: 'local',
      JIRA_EMBEDDING_API_KEY: '',
      JIRA_LOCAL_EMBEDDING_BASE_URL: 'http://127.0.0.1:11434/v1',
      LANGFUSE_PUBLIC_KEY: '',
      LANGFUSE_SECRET_KEY: '',
      JIRA_WORKSPACE_RESTORE: 'false',
    },
    stdio: ['ignore', 'ignore', 'pipe'],
  }
);
let logs = '';
server.stderr.on('data', (chunk) => {
  logs = (logs + chunk).slice(-6000);
});
let browser;
const rows = [
  [
    'Issue key',
    'Summary',
    'Issue Type',
    'Status',
    'Status Category',
    'Project key',
    'Project name',
    'Description',
    'Custom field (Acceptance Criteria)',
    'Custom field (Comments)',
  ],
  [
    'DEMO-41',
    'Password reset and account recovery',
    'Story',
    'To Do',
    'To Do',
    'DEMO',
    'Nimbus Workspace · fictional demo',
    'Let users request a password reset from sign-in. A one-time email link lets them choose a new password. Define security and failure states before implementation.',
    'A registered user can reset a password using a valid emailed link.',
    'Fictional refinement note: expiry, token reuse and request throttling still need explicit acceptance checks.',
  ],
  [
    'DEMO-18',
    'Protect account emails from enumeration',
    'Story',
    'Done',
    'Done',
    'DEMO',
    'Nimbus Workspace · fictional demo',
    'Use the same confirmation for known and unknown accounts. Apply request-rate limits to authentication email endpoints.',
    'Confirmation wording does not reveal whether an email is registered. Repeated requests are rate limited.',
    'Fictional demo note: use a neutral response and a per-account request limit.',
  ],
  [
    'DEMO-23',
    'Expire and revoke email verification tokens',
    'Task',
    'Done',
    'Done',
    'DEMO',
    'Nimbus Workspace · fictional demo',
    'Store a token hash with expiration and used_at. Reject expired and replayed tokens; show a recoverable error.',
    'A valid token succeeds once. Expired or reused tokens cannot change account state.',
    'Fictional demo note: mark used_at in the same transaction as the account update to prevent token reuse.',
  ],
  [
    'DEMO-09',
    'Improve navigation sidebar',
    'Task',
    'To Do',
    'To Do',
    'DEMO',
    'Nimbus Workspace · fictional demo',
    'Show the selected project name in the navigation sidebar.',
    'The selected project name remains readable.',
    '',
  ],
];
const csv = rows.map((row) => row.map((value) => `"${value.replaceAll('"', '""')}"`).join(',')).join('\n');

try {
  await expect
    .poll(
      async () => {
        if (server.exitCode !== null) throw new Error(logs);
        try {
          return (await fetch(`${base}/api/health`)).ok;
        } catch {
          return false;
        }
      },
      { timeout: 20_000 }
    )
    .toBe(true);
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1120 },
    deviceScaleFactor: 1,
    colorScheme: 'light',
    reducedMotion: 'reduce',
    locale: 'en-US',
    timezoneId: 'UTC',
  });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(base);
  await expect(page.getByLabel('Embedding model and chunk size')).toBeEnabled();
  await page.getByLabel('Embedding model and chunk size').selectOption('small');
  await page
    .getByLabel('Jira CSV file')
    .setInputFiles({ name: 'nimbus-security-fictional.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  await page.getByRole('button', { name: 'Explore my project' }).click();
  await expect(
    page.getByRole('region', { name: 'Sprint Agent setup' }).getByText('Ticket context is ready')
  ).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: 'Use original statuses', exact: true }).click();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  await page
    .getByRole('region', { name: 'Sprint Agent chat' })
    .getByRole('button', { name: 'Full screen chat', exact: true })
    .click();
  const chat = page.getByRole('dialog', { name: 'Sprint Agent chat' });
  const question =
    'Improve DEMO-41 using similar tickets and their comments. Give three testable acceptance criteria covering neutral confirmations, expired or reused tokens, and throttling. Add one implementation note. Start directly with the criteria and keep it under 110 words.';
  await expect(chat.getByLabel('Message Sprint Agent')).toBeEnabled();
  await chat.getByLabel('Message Sprint Agent').fill(question);
  const completed = page.waitForResponse(
    (response) => response.url().endsWith('/agent/chat') && response.request().method() === 'POST',
    { timeout: 420_000 }
  );
  await chat.getByRole('button', { name: 'Send message', exact: true }).click();
  console.log('Waiting for a real local-model answer…');
  const response = await completed;
  const stream = await response.text();
  const events = stream
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line));
  const result = events.findLast((event) => event.event === 'done');
  if (!result || !response.ok) throw new Error(`Local model did not finish: ${stream.slice(-1800)}`);
  if (!result.tools?.some((tool) => tool.tool === 'search_tickets'))
    throw new Error('Similar-ticket search was not used.');
  if (!result.sources?.some((source) => source.key !== 'DEMO-41'))
    throw new Error('The answer has no related-ticket sources.');
  await expect(chat.getByLabel('Message Sprint Agent')).toBeEnabled({ timeout: 420_000 });
  await expect(chat.locator('.agent-assistant').last()).not.toBeEmpty();
  await chat.getByLabel('Response details', { exact: true }).click();
  await chat.locator('.agent-body').evaluate((element) => {
    element.scrollTop = 0;
  });
  await page.evaluate(() => document.fonts.ready);
  await expect(chat.getByRole('region', { name: 'Tools used' }))
    .toBeVisible()
    .catch(async () => {
      await expect(chat.getByRole('heading', { name: 'Tools used' })).toBeVisible();
    });
  if (errors.length) throw new Error(errors.join('\n'));
  await page.screenshot({
    path: join(root, 'resources/images/chat_reading_desktop.png'),
    fullPage: false,
    animations: 'disabled',
  });
  await writeFile(
    join(artifacts, 'evidence.json'),
    JSON.stringify({ fictional: true, question, model, result }, null, 2)
  );
  console.log(
    JSON.stringify({
      model,
      sources: result.sources.map((source) => source.key),
      tools: result.tools.map((tool) => tool.tool),
      content: result.content,
    })
  );
} finally {
  await browser?.close();
  if (server.exitCode === null) {
    const stopped = once(server, 'exit');
    server.kill('SIGTERM');
    await stopped;
  }
  spawnSync(
    join(root, '.venv/bin/python'),
    [
      '-c',
      'import os; from pymongo import MongoClient; c=MongoClient(os.environ.get("JIRA_MONGO_URI", "mongodb://127.0.0.1:27018")); c.drop_database(os.environ["JIRA_MONGO_DATABASE"]); c.close()',
    ],
    { env: { ...process.env, JIRA_MONGO_DATABASE: database }, stdio: 'ignore' }
  );
  await rm(data, { recursive: true, force: true });
}
