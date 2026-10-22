import { test, expect, type Page } from '@playwright/test';

async function demo(page: Page) {
  await page.goto('/');
  await expect(
    page.getByText('No Jira export yet? Start with our fictional 100-ticket software project.')
  ).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download demo CSV' })).toHaveAttribute(
    'href',
    '/api/demo.csv'
  );
  await page.getByRole('button', { name: 'Try the fictional 100-ticket demo' }).click();
  await expect(page.getByText('agileplanner-demo.csv', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Explore my project' }).click();
  await page.getByRole('button', { name: 'Use original statuses', exact: true }).click();
  await page.getByLabel('Project', { exact: true }).selectOption('DEMO');
}

test('demo import, persistent theme, full-screen ticket with inline streamed AI', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await demo(page);
  await page.getByRole('button', { name: 'Switch to dark theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.route('**/agent/status', async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: {
        ...(await response.json()),
        status: 'ready',
        choices: [{ id: 'test', name: 'Test model', model: 'test' }],
      },
    });
  });
  await page.getByRole('link', { name: 'Sprint explorer', exact: true }).click();
  await page.locator('tbody .issue-key').first().click();
  const ticket = page.getByRole('dialog', { name: /.+/ });
  await expect(ticket.getByRole('button', { name: 'Generate AI Summary and Suggestions' })).toBeEnabled();
  const bounds = await ticket.boundingBox();
  expect(bounds?.width).toBe(page.viewportSize()!.width);
  expect(bounds?.x).toBe(0);
  let request: Record<string, unknown> = {};
  await page.route('**/analysis', async (route) => {
    request = route.request().postDataJSON();
    await route.fulfill({
      contentType: 'application/x-ndjson',
      body:
        [
          { event: 'activity', message: 'Reading acceptance criteria and similar work.' },
          { event: 'text_delta', text: 'Check the requirements and add a regression test.' },
          {
            event: 'done',
            content: 'Check the requirements and add a regression test.',
            model: 'test',
            sources: [],
            tools: [{ tool: 'get_ticket', ok: true }],
            groups: [],
            assignments: [],
          },
        ]
          .map((e) => JSON.stringify(e))
          .join('\n') + '\n',
    });
  });
  await ticket.getByRole('button', { name: 'Generate AI Summary and Suggestions' }).click();
  await expect(ticket.getByText('Check the requirements and add a regression test.')).toBeVisible();
  expect(request.kind).toBe('ticket');
  expect(request.key).toMatch(/^DEMO-/);
  await ticket.getByRole('button', { name: 'Back to workspace' }).click();
  await expect(ticket).not.toBeVisible();
  await page
    .getByRole('navigation', { name: 'Workspace' })
    .getByRole('button', { name: 'Sprint Agent', exact: true })
    .click();
  await expect(page.getByLabel('Message Sprint Agent')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  expect(errors).toEqual([]);
});

test('backlog management filters, pages, people profiles and bounded AI continuation', async ({
  page,
}, info) => {
  await demo(page);
  await page.getByRole('button', { name: 'Manage people', exact: true }).click();
  await page
    .getByRole('checkbox', { name: /^Developer / })
    .first()
    .check();
  await page
    .getByLabel(/^Work areas for /)
    .first()
    .fill('Backend, Data');
  await page.getByRole('button', { name: 'Save people profiles', exact: true }).click();
  let snapshot: {
    fingerprint: string;
    tickets: { key: string }[];
    config: { scope: string; sprint: string };
  };
  await page.route('**/planning/report', async (route) => {
    const response = await route.fetch();
    snapshot = await response.json();
    await route.fulfill({ response, json: snapshot });
  });
  await page.getByRole('link', { name: 'Backlog Management', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your planning rules' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save rules and update report' })).toBeEnabled();
  await page.getByLabel('Backlog scope', { exact: true }).selectOption('project');
  await page.getByLabel('Finished work', { exact: true }).selectOption('statuses');
  await page.getByRole('checkbox', { name: 'Prod', exact: true }).check();
  await page.getByLabel('Budget per person').fill('10');
  await expect(page.getByLabel('Estimate counting')).toHaveText(/Exclude parents\/epics/);
  await expect(page.getByText('Individual capacity per sprint', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Priorities needing attention (optional)', { exact: true })).toHaveCount(0);
  await expect(
    page.getByText('Priority values still awaiting refinement (optional)', { exact: true })
  ).toHaveCount(0);
  await expect(page.getByLabel('Backlog sprint', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Project', { exact: true })).toHaveCount(1);
  await page.getByRole('button', { name: 'Save rules and update report' }).click();
  await expect(page.getByText('✓ Rules saved · Report updated')).toBeVisible();
  const metrics = page.getByRole('group', { name: 'Backlog metrics' });
  await expect(metrics.locator('article')).toHaveCount(6);
  await expect(metrics).toContainText('Estimated tickets');
  await expect(metrics).toContainText('Unestimated tickets');
  await expect(metrics).toContainText('Overloaded devs');
  await expect(
    metrics.locator('article').filter({ hasText: 'Total active devs' }).locator('strong')
  ).toHaveText('1');
  await expect(page.getByRole('heading', { name: 'Backlog by status', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Backlog by priority' })).toBeVisible();
  const records = page.getByRole('region', { name: 'Backlog Tickets', exact: true });
  const rows = records.locator('tbody tr');
  await expect(rows).toHaveCount(20);
  const firstKey = await rows.first().locator('.issue-key').textContent();
  await records.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(rows).toHaveCount(20);
  expect(await rows.first().locator('.issue-key').textContent()).not.toBe(firstKey);
  await expect(records).toContainText('Page 2 of');
  await records.getByRole('button', { name: 'Previous', exact: true }).click();
  await expect(rows.first().locator('.issue-key')).toHaveText(firstKey!);
  await page.getByLabel('Backlog priority', { exact: true }).selectOption('High');
  expect(await rows.count()).toBeGreaterThan(0);
  for (const row of await rows.all()) await expect(row.locator('td').nth(2)).toHaveText('High');
  await page.getByLabel('Backlog priority', { exact: true }).selectOption('');
  const priorityChart = page.getByRole('region', { name: 'Backlog by priority', exact: true });
  const high = priorityChart.locator('button').filter({ has: page.getByText('High', { exact: true }) });
  await high.click();
  await expect(page.getByLabel('Backlog priority', { exact: true })).toHaveValue('High');
  await high.click();
  await page
    .getByRole('combobox', { name: 'Planning readiness', exact: true })
    .selectOption('owner_refinement');
  await expect(rows.first()).toContainText('Assignee refinement');
  await expect(rows.first()).toContainText('Ask ');
  await page.getByRole('combobox', { name: 'Planning readiness', exact: true }).selectOption('');
  const people = page.getByRole('region', { name: 'People & planning', exact: true });
  await expect(people.locator('.planning-person')).toHaveCount(1);
  await expect(people).toContainText('Backend · Data');
  await expect(people).toContainText('Avg. points per sprint');
  await expect(people.getByText(/Finished story points by sprint/)).toHaveCount(0);
  await people.getByText('Story sizes & recent work', { exact: true }).first().click();
  await expect(people.locator('.planning-person-details[open] > p')).toHaveCount(5);
  await expect(people.locator('.planning-person-details[open]')).toContainText('pts');
  await expect(people).not.toContainText('Below 3 points');
  await expect(people.getByRole('checkbox', { name: 'Show all assignees' })).toHaveCount(0);
  await people.getByRole('button', { name: 'Manage people', exact: true }).click();
  const editor = people.getByRole('region', { name: 'Manage planning people' });
  await expect(editor.getByRole('button', { name: 'Save people profiles', exact: true })).toBeVisible();
  for (const checkbox of await editor.getByRole('checkbox', { name: /^Developer / }).all())
    await checkbox.check();
  await editor
    .getByLabel(/^Work areas for /)
    .nth(1)
    .fill('QA');
  await editor.getByRole('button', { name: 'Save people profiles', exact: true }).click();
  await expect(editor).toHaveCount(0);
  await expect(people.getByRole('status')).toContainText('Planning report updated');
  await expect(people.getByRole('button', { name: 'Manage people', exact: true })).toBeVisible();
  await expect(people).toContainText('QA');
  expect(await people.locator('.planning-person').count()).toBeGreaterThan(5);
  const columns = await people
    .locator('.planning-people-list')
    .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').length);
  expect(columns).toBe(info.project.name === 'desktop' ? 5 : 1);
  await people.screenshot({ path: `test-results/people-cards-${info.project.name}.png` });
  await page.reload();
  await expect(page.getByLabel('Budget per person')).toHaveValue('10');
  await expect(page.getByRole('checkbox', { name: 'Prod', exact: true })).toBeChecked();
  await expect(page.getByLabel('Backlog scope', { exact: true })).toHaveValue('project');
  await page.route('**/agent/status', async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: {
        ...(await response.json()),
        status: 'ready',
        choices: [{ id: 'test', name: 'Test model', model: 'test' }],
      },
    });
  });
  const requests: { review_id?: string; batch_limit: number }[] = [];
  await page.route('**/analysis', async (route) => {
    requests.push(route.request().postDataJSON());
    const reviewed = Math.min(20 * requests.length, snapshot.tickets.length);
    const keys = snapshot.tickets.slice(0, reviewed).map((ticket) => ticket.key);
    await route.fulfill({
      contentType: 'application/x-ndjson',
      body:
        JSON.stringify({
          event: 'done',
          content: `Review batch ${requests.length}: refine estimate gaps before allocating more work.`,
          model: 'test',
          sources: [],
          tools: [{ tool: 'record_backlog_plan', ok: true }],
          groups: [
            { name: 'Engineering', keys: keys.slice(0, 3) },
            { name: 'Delivery', keys: keys.slice(3) },
          ],
          assignments: [],
          assessments: keys.slice(-20).map((key) => ({
            key,
            summary: 'Review software delivery requirement',
            assignee: 'Demo developer',
            priority: 'High',
            readiness: 'owner_refinement',
            estimate: null,
            assessment: `Confirm acceptance criteria and the missing estimate for ${key} with its current owner.`,
          })),
          fingerprint: snapshot.fingerprint,
          review_id: 'test-review',
          coverage: {
            reviewed,
            total: snapshot.tickets.length,
            remaining: snapshot.tickets.length - reviewed,
            batch_start: reviewed - 19,
            batch_count: 20,
            has_more: reviewed < snapshot.tickets.length,
          },
        }) + '\n',
    });
  });
  await page.reload();
  await page.getByRole('button', { name: 'Generate AI Analysis and Plan' }).click();
  await expect(
    page.getByText('Review batch 1: refine estimate gaps before allocating more work.')
  ).toBeVisible();
  await expect(page.getByText(/20 of \d+ tickets reviewed/)).toBeVisible();
  const assessment = page.getByRole('region', { name: 'Ticket-by-ticket assessment' });
  await expect(assessment.locator('article')).toHaveCount(20);
  await expect(assessment).toContainText('Estimate missing');
  expect(await assessment.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.getByLabel('AI work theme').selectOption('Engineering');
  await expect(rows).toHaveCount(3);
  await page.getByLabel('AI work theme').selectOption('__unreviewed__');
  await expect(rows).toHaveCount(20);
  await page.getByRole('button', { name: 'Continue with next tickets' }).click();
  await expect(
    page.getByText('Review batch 2: refine estimate gaps before allocating more work.')
  ).toBeVisible();
  await expect(page.getByText(/40 of \d+ tickets reviewed/)).toBeVisible();
  expect(requests[0]).toMatchObject({ batch_limit: 20, review_id: '' });
  expect(requests[1]).toMatchObject({ batch_limit: 20, review_id: 'test-review' });
  await expect(page.getByText('Previous review summaries · 1', { exact: true })).toBeVisible();
  await page.getByLabel('Backlog scope', { exact: true }).selectOption('sprint');
  await page.getByLabel('Backlog sprint', { exact: true }).selectOption('Iteration 5');
  await page.getByRole('button', { name: 'Save rules and update report' }).click();
  await expect(rows).toHaveCount(16);
  expect(snapshot!.config).toMatchObject({ scope: 'sprint', sprint: 'Iteration 5' });
  await page.getByRole('button', { name: 'Switch to dark theme' }).click();
  await expect(rows.locator('td').first()).toHaveCSS('color', 'rgb(226, 234, 248)');
  expect((await records.boundingBox())!.y).toBeLessThan((await people.boundingBox())!.y);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await records.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `test-results/backlog-management-${info.project.name}.png` });
  await page.getByLabel('Project', { exact: true }).selectOption('');
  await expect(page.getByText('Choose a project to see its planning rules and tickets.')).toBeVisible();
  await page.getByLabel('Project', { exact: true }).selectOption('DEMO');
  await expect(page.getByLabel('Backlog scope', { exact: true })).toHaveValue('sprint');
  await expect(rows).toHaveCount(16);
  await page.unrouteAll({ behavior: 'wait' });
});
