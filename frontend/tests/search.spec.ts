import { test, expect, type Page } from '@playwright/test';

const csv = `Issue key,Summary,Issue Type,Status,Status Category,Project key,Description,Priority,Assignee,Reporter,Sprint,Parent
APP-1,NUCC taxonomy mappings,Epic,In Progress,In Progress,APP,Map specialist categories,High,Ana,Lee,Sprint 2,
APP-2,Validate imports,Bug,Awaiting audit,In Progress,APP,Check NUCC taxonomy and ticket 999999,High,Ana,Rae,Sprint 2,1
APP-3,NUCC taxonomy,Story,Done,Done,APP,Publish names,Medium,Bo,Lee,Sprint 1,
APP-4,Provider classification,Task,To Do,To Do,APP,Specialist ontology and categories,Urgent,Bo,Rae,Sprint 2,
OTHER-1,Unrelated login,Bug,In Progress,In Progress,OTHER,Fix sign in,Medium,Cy,Cy,Other 1,`;

async function setup(page: Page) {
  await page.goto('/');
  await page.getByLabel('Prepare the Sprint Agent index after import').check();
  await page
    .getByLabel('Jira CSV file')
    .setInputFiles({ name: 'finder.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  await page.getByRole('button', { name: 'Explore my project' }).click();
  await page.getByRole('button', { name: 'Use original statuses', exact: true }).click();
  await page.getByLabel('Project', { exact: true }).selectOption('APP');
  return page.getByRole('region', { name: 'Find tickets' });
}

test('overview finder ranks title/description, parses numbers, filters dynamically and opens a ticket', async ({
  page,
}, info) => {
  const finder = await setup(page);
  const input = finder.getByRole('combobox', { name: 'Find tickets by number, title or topic' });
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(0);
  await input.fill('nucc taxonomy');
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(3);
  await expect(finder.locator('#ticket-finder-results').getByRole('option').first()).toContainText('APP-3');
  await expect(finder.locator('#ticket-finder-results').getByRole('option').nth(2)).toContainText(
    'Description match'
  );
  await expect(finder.locator('mark').first()).toHaveText(/nucc/i);
  await input.fill('ticket 1');
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(1);
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toContainText('APP-1');
  await input.press('ArrowDown');
  await input.press('Enter');
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByRole('heading', { name: 'NUCC taxonomy mappings', exact: true })).toBeVisible();
  await drawer.getByRole('button', { name: 'Close issue details' }).click();
  await input.fill('app 2');
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(1);
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toContainText(
    'Validate imports'
  );
  await input.fill('high priority');
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(2);
  await expect(finder.getByLabel('Applied search filters')).toContainText('Priority: High · from search');
  await finder.getByRole('button', { name: /Filters/ }).click();
  await expect(finder.locator('select')).toHaveCount(8);
  await finder.getByRole('button', { name: 'Clear ticket search' }).click();
  await finder.getByLabel('Ticket finder status', { exact: true }).selectOption('Awaiting audit');
  await finder.getByLabel('Ticket finder assignee', { exact: true }).selectOption('Ana');
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(1);
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toContainText('APP-2');
  await page.screenshot({ path: `test-results/ticket-finder-${info.project.name}.png` });
  expect(await finder.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
});

test('identifier ambiguity stays scoped and a missing ticket is not a description match', async ({
  page,
}) => {
  const finder = await setup(page);
  const input = finder.getByRole('combobox', { name: 'Find tickets by number, title or topic' });
  await input.fill('ticket 999999');
  await expect(finder.getByText('No matching tickets.', { exact: false })).toBeVisible();
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(0);
  await finder.getByRole('button', { name: /Filters/ }).click();
  await finder.getByLabel('Ticket finder project').selectOption('');
  await input.fill('1');
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(2);
  await expect(finder).toContainText('Several ticket identifiers match');
  await input.fill('other 1');
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(1);
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toContainText('OTHER-1');
  await input.press('Escape');
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(0);
  await input.press('ArrowUp');
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveAttribute(
    'aria-selected',
    'true'
  );
});

test('keyword results appear before similarity finishes and merged results remain title-first', async ({
  page,
}) => {
  const finder = await setup(page);
  const ident = await page.evaluate(() => localStorage.getItem('sprintlens.dataset'));
  const ticket = await (await page.request.get(`/api/datasets/${ident}/issues/APP-4`)).json();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route('**/ticket-search?**', async (route) => {
    const isSemantic = new URL(route.request().url()).searchParams.get('semantic') === 'true';
    const response = await route.fetch();
    const body = await response.json();
    if (isSemantic) {
      await gate;
      body.items = [
        ...body.items.filter((item: { ticket: { key: string } }) => item.ticket.key !== 'APP-4'),
        { ticket, match: 'Semantic match', excerpt: ticket.description },
      ];
      body.mode = 'hybrid';
    }
    await route.fulfill({ response, json: { ...body, can_expand: true } });
  });
  await finder
    .getByRole('combobox', { name: 'Find tickets by number, title or topic' })
    .fill('nucc taxonomy');
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(3);
  await expect(finder).toContainText('Finding similar tickets');
  release();
  await expect(finder.locator('#ticket-finder-results').getByRole('option')).toHaveCount(4);
  await expect(finder.locator('#ticket-finder-results').getByRole('option').first()).toContainText('APP-3');
  await expect(finder.locator('#ticket-finder-results').getByRole('option').last()).toContainText(
    'Semantic match'
  );
  await expect(finder.locator('#ticket-finder-results').getByRole('option').last()).toContainText('APP-4');
});
