import { test, expect, type Page } from '@playwright/test';

async function auditSurfaces(page: Page, state: string) {
  const leaks = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>('body *')].flatMap((el) => {
      if (!el.checkVisibility() || el.closest('svg') || el.matches('input[type="color"]')) return [];
      const rect = el.getBoundingClientRect();
      if (rect.width < 8 || rect.height < 8) return [];
      const bg = getComputedStyle(el).backgroundColor;
      const values = bg.match(/[\d.]+/g)?.map(Number);
      if (!values || (values[3] ?? 1) < 0.9) return [];
      const rgb = values
        .slice(0, 3)
        .map((value) => value / 255)
        .map((value) => (value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4));
      const luminance = rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
      return luminance > 0.62
        ? [{ element: `${el.tagName}.${el.className}`, background: bg, text: el.textContent?.slice(0, 70) }]
        : [];
    })
  );
  expect(leaks, `${state}: bright surfaces in dark mode`).toEqual([]);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    `${state}: viewport overflow`
  ).toBe(true);
}

const markdown = [
  'Review `sample_code` and the exported details.',
  '',
  '```sql',
  'SELECT key, summary FROM tickets;',
  '```',
  '',
  '> A snapshot is evidence, not a delivery promise.',
  '',
  '| Ticket | Status |',
  '| --- | --- |',
  '| DEMO-1 | To Do |',
  '',
  '- [x] Check requirements',
  '- [ ] Refine estimates',
  '',
  '[Public reference](https://example.invalid/docs)',
].join('\n');

test('shared dark palette covers pages, editors, ticket details and rich agent states', async ({ page }) => {
  test.setTimeout(45_000);
  page.setDefaultTimeout(10_000);
  await page.addInitScript(() => localStorage.setItem('agileplanner.theme', 'dark'));
  await page.route('**/agent/status', async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: {
        ...(await response.json()),
        status: 'ready',
        choices: [
          { id: '', name: 'UI fixture', model: 'test', provider: 'compatible', web_available: false },
        ],
      },
    });
  });
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await auditSurfaces(page, 'upload');
  await page.getByRole('button', { name: 'Try the fictional 100-ticket demo' }).click();
  await page.getByRole('button', { name: 'Explore my project' }).click();
  await expect(page.getByRole('heading', { name: 'Choose how your statuses appear.' })).toBeVisible();
  await auditSurfaces(page, 'import setup');
  await page.getByRole('button', { name: 'Use original statuses', exact: true }).click();
  await page.getByLabel('Project', { exact: true }).selectOption('DEMO');
  await page.getByRole('button', { name: 'Manage people', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save people profiles' })).toBeVisible();
  await auditSurfaces(page, 'overview and people editor');
  await page.getByLabel('Explore field').selectOption('Priority');
  await expect(page.getByRole('button', { name: 'Filter Priority: High', exact: true })).toBeVisible();
  await auditSurfaces(page, 'exported field explorer');
  await page.getByRole('button', { name: 'Configure statuses', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Status configuration' })).toBeVisible();
  await auditSurfaces(page, 'status editor');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('link', { name: 'Sprint explorer', exact: true }).click();
  await expect(page.locator('tbody .issue-key').first()).toBeVisible();
  await auditSurfaces(page, 'sprint');
  await page.locator('tbody .issue-key').first().click();
  const ticket = page.getByRole('dialog');
  await expect(ticket.getByRole('button', { name: 'Back to workspace' })).toBeVisible();
  for (const detail of await ticket.locator('details').all())
    await detail.evaluate((el) => {
      (el as HTMLDetailsElement).open = true;
    });
  await auditSurfaces(page, 'full ticket and exported fields');
  await ticket.getByRole('button', { name: 'Back to workspace' }).click();
  await page.getByRole('link', { name: 'Backlog Management', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Backlog Tickets', exact: true })).toBeVisible();
  await page.locator('.planning-person-details summary').first().click();
  await auditSurfaces(page, 'backlog charts, readiness, developer profiles and sprint points');
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await expect(chat.getByRole('heading', { name: 'Your project, in conversation.' })).toBeVisible();
  await auditSurfaces(page, 'agent welcome');
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await chat.getByRole('button', { name: 'Add model connection', exact: true }).click();
  for (const provider of ['openai', 'gemini', 'azure', 'compatible']) {
    await chat.getByLabel('Connection provider').selectOption(provider);
    await auditSurfaces(page, `connection ${provider}`);
  }
  await chat.getByRole('button', { name: 'Cancel connection editing' }).click();
  await chat.getByText('Project context & working agreements', { exact: true }).click();
  await chat.getByLabel('Project context prompt').fill('Fictional test goals and working agreements.');
  await chat.getByRole('button', { name: 'Save project context', exact: true }).click();
  await expect(chat.locator('.agent-context-confirmation')).toBeVisible();
  await auditSurfaces(page, 'saved project context');
  await chat.getByRole('button', { name: 'Close agent configuration' }).click();
  await page.route('**/agent/chat', async (route) => {
    await route.fulfill({
      json: {
        session_id: 'theme-fixture',
        content: markdown,
        model: 'test',
        mode: 'ai',
        sources: [
          {
            key: 'DEMO-1',
            summary: 'Fictional source',
            status: 'To Do',
            reason: 'Matched evidence',
            excerpt: 'Example',
          },
        ],
        tools: [{ tool: 'get_ticket', ok: true }],
        activity: [{ message: 'Retrieved ticket context.', tool: 'get_ticket', ok: true }],
        scope: { project: 'DEMO', sprint: 'Iteration 5' },
        context_description: 'Fictional planning context',
        charts: [
          {
            title: 'Status mix',
            unit: 'tickets',
            scope: { project: 'DEMO' },
            data: [{ label: 'To Do', value: 1 }],
          },
        ],
      },
    });
  });
  await chat.getByLabel('Message Sprint Agent').fill('Explain the example ticket');
  await chat.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(chat.locator('.agent-message-text code').first()).toHaveText('sample_code');
  await chat.getByLabel('Response details', { exact: true }).click();
  await auditSurfaces(page, 'markdown code, table, quote, chart and expanded sources');
  const code = chat.locator('.agent-message-text code').first();
  const contrast = await code.evaluate((el) => {
    const style = getComputedStyle(el);
    const luminance = (color: string) => {
      const rgb = color
        .match(/[\d.]+/g)!
        .slice(0, 3)
        .map(Number)
        .map((value) => value / 255)
        .map((value) => (value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4));
      return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
    };
    const text = luminance(style.color),
      background = luminance(style.backgroundColor);
    return (Math.max(text, background) + 0.05) / (Math.min(text, background) + 0.05);
  });
  expect(contrast, 'inline code text contrast').toBeGreaterThanOrEqual(4.5);
  await chat.getByRole('button', { name: 'Message context', exact: true }).click();
  await auditSurfaces(page, 'context popover');
  await chat.getByRole('button', { name: 'Close message context', exact: true }).click();
  await chat.getByRole('button', { name: 'Show agent activity', exact: true }).click();
  await auditSurfaces(page, 'expanded activity');
  await page.route(/\/agent\/sessions\?/, async (route) =>
    route.fulfill({
      json: {
        sessions: [
          {
            session_id: 'theme-fixture',
            title: 'Theme check conversation',
            preview: 'Fictional project discussion',
            filename: 'demo.csv',
            dataset_id: '',
            updated_at: '2026-10-20T12:00:00Z',
            message_count: 2,
          },
        ],
        has_more: false,
        next_offset: 1,
      },
    })
  );
  await chat.getByRole('button', { name: 'Conversation history', exact: true }).click();
  const history = chat.locator('.agent-history-item').first();
  await expect(history).toBeVisible();
  await history.hover();
  await auditSurfaces(page, 'selected and hovered history');
  await chat.getByRole('button', { name: 'Close conversation history', exact: true }).click();
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await chat.getByRole('button', { name: 'Add model connection', exact: true }).click();
  await chat.getByLabel('Connection provider').selectOption('compatible');
  await chat.getByLabel('Connection name', { exact: true }).fill('Theme fixture');
  await chat.getByLabel('Model API endpoint').fill('http://127.0.0.1:11434/v1');
  await chat.getByLabel('Model or deployment name').fill('test');
  let rejected = false;
  await page.route('**/api/agent/connections', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    if (!rejected) {
      rejected = true;
      return route.fulfill({ status: 422, json: { detail: 'Theme check validation message' } });
    }
    const { api_key: _secret, ...config } = route.request().postDataJSON();
    return route.fulfill({ status: 201, json: { ...config, id: 'theme-profile', has_key: false } });
  });
  await chat.getByRole('button', { name: 'Save model connection', exact: true }).click();
  await expect(chat.getByRole('alert')).toContainText('Theme check validation message');
  await auditSurfaces(page, 'validation notice');
  await chat.getByRole('button', { name: 'Save model connection', exact: true }).click();
  await expect(chat.locator('.agent-connection-notice')).toBeVisible();
  await auditSurfaces(page, 'saved connection notice');
  await chat.getByRole('button', { name: 'Close agent configuration' }).click();

  await page.screenshot({ path: `test-results/theme-rich-${test.info().project.name}.png` });
  await page.unrouteAll({ behavior: 'wait' });
});
