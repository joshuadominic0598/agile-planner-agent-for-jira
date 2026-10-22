import { test, expect } from '@playwright/test';

const csv =
  'Issue key,Summary,Issue Type,Status,Description\nAPP-1,Login recovery,Story,To Do,Reset forgotten passwords securely\n';

test('private embedding choices, import persistence, retry and strict chunk policy', async ({
  page,
}, info) => {
  await page.goto('/');
  const choice = page.getByLabel('Embedding model and chunk size');
  await expect(choice).toBeEnabled();
  await expect(choice.locator('option')).toHaveCount(3);
  await choice.selectOption('small');
  await expect(page.getByText(/Maximum 1,000 characters per chunk/)).toBeVisible();
  await expect(page.getByText(/200 characters of narrative overlap/)).toBeVisible();
  await choice.selectOption('large');
  await expect(page.getByText(/Maximum 3,000 characters per chunk/)).toBeVisible();
  await expect(page.getByText(/500 characters of narrative overlap/)).toBeVisible();
  await expect(page.getByText(/Larger model uses more memory/)).toBeVisible();
  await page.getByLabel('Prepare the Sprint Agent index after import').uncheck();
  await page
    .getByLabel('Jira CSV file')
    .setInputFiles({ name: 'private.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  const imported = page.waitForResponse(
    (response) => response.url().endsWith('/api/imports') && response.request().method() === 'POST'
  );
  await page.getByRole('button', { name: 'Explore my project' }).click();
  const dataset = (await (await imported).json()).id;
  const setup = page.getByRole('region', { name: 'Sprint Agent setup' });
  await expect(setup).toBeVisible();
  await expect(setup.getByLabel('Embedding model and chunk size')).toHaveValue('large');
  const status = await (await page.request.get(`/api/datasets/${dataset}/agent/status`)).json();
  expect(status.embedding.private_local).toBe(true);
  expect(status.embedding.model).toBe('qwen3-embedding:4b');
  expect(status.status).toBe('missing');
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await page.screenshot({
    path: `../resources/screenshots/private-embedding-large-${info.project.name}.png`,
    fullPage: true,
  });
  // Exercise the actionable failure UI without requiring downloaded weights in CI.
  await page.route(`**/datasets/${dataset}/agent/index`, (route) =>
    route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Start Ollama and install the selected local model, then retry.' }),
    })
  );
  await setup.getByRole('button', { name: 'Prepare agent index' }).click();
  await expect(setup.getByRole('alert')).toContainText('Start Ollama');
  await page.unroute(`**/datasets/${dataset}/agent/index`);
  await setup.getByLabel('Embedding model and chunk size').selectOption('lexical');
  await setup.getByRole('button', { name: 'Prepare agent index' }).click();
  await expect(setup.getByText('Ticket context is ready')).toBeVisible();
  await expect(setup.getByText(/max 1,000 characters · 200 overlap/)).toBeVisible();
  const rebuilt = await (await page.request.get(`/api/datasets/${dataset}/agent/status`)).json();
  expect(rebuilt.metadata.chunk_characters).toBe(1000);
  expect(rebuilt.metadata.chunk_overlap).toBe(200);
  expect(rebuilt.embedding.preset).toBe('lexical');
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await page.screenshot({
    path: `../resources/screenshots/private-embedding-${info.project.name}.png`,
    fullPage: true,
  });
});
