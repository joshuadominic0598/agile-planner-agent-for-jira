import { test, expect, type Page } from '@playwright/test';

const csv = `Issue key,Summary,Issue Type,Status,Status Category,Project key,Description,Assignee,Reporter,Sprint,Parent,Labels,Component/s
APP-1,Authentication platform,Epic,In Progress,In Progress,APP,Build secure login,Ana,Lee,Sprint 1,,identity,Platform
APP-2,Rotate refresh tokens,Story,Testing,In Progress,APP,OAuth refresh token rotation,Ana,Lee,Sprint 2,1,identity,API
APP-3,Improve login telemetry,Task,Done,Done,APP,Capture login tracing,Bo,Ana,Sprint 1,1,observability,API
OTHER-2,Separate database migration,Bug,To Do,To Do,OTHER,Unrelated storage,Cy,Cy,Other 1,,storage,Database`;

async function upload(page: Page, prepare = true, contents = csv) {
  // UI requests AI; metadata integration cases explicitly bridge to diagnostic mode in this test harness.
  await page.route('**/agent/status', async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: {
        ...body,
        choices: body.choices.length
          ? body.choices
          : [
              {
                id: '',
                name: 'Metadata test connection',
                model: 'test-model',
                provider: 'compatible',
                web_available: false,
              },
            ],
      },
    });
  });
  await page.route('**/agent/chat', async (route) => {
    await route.continue({
      postData: JSON.stringify({ ...route.request().postDataJSON(), mode: 'retrieval', connection_id: null }),
    });
  });
  await page.goto('/');
  await page.getByLabel('Prepare the Sprint Agent index after import').setChecked(prepare);
  await page
    .getByLabel('Jira CSV file')
    .setInputFiles({ name: 'agent-demo.csv', mimeType: 'text/csv', buffer: Buffer.from(contents) });
  await page.getByRole('button', { name: 'Explore my project' }).click();
  await expect(page.getByRole('region', { name: 'Sprint Agent setup' })).toBeVisible();
}
async function enter(page: Page) {
  await page.getByRole('button', { name: 'Use original statuses', exact: true }).click();
  await page.getByLabel('Project', { exact: true }).selectOption('APP');
  await expect(page.getByRole('heading', { name: 'Your project, in focus.' })).toBeVisible();
}
async function ask(page: Page, text: string) {
  await page.getByLabel('Message Sprint Agent').fill(text);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Finding context' })).toHaveCount(0);
}

test('agent unavailable without CSV; optional late index; retrieval, attachments, scope and sessions', async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Agent unavailable' })).toBeVisible();
  await expect(page.getByLabel('Message Sprint Agent')).toBeEnabled();
  await page.getByRole('button', { name: 'Close Sprint Agent' }).click();
  await upload(page, false);
  await expect(page.getByRole('region', { name: 'Sprint Agent setup' })).toContainText(
    'prepare the ticket index first'
  );
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await expect(chat.getByLabel('Message Sprint Agent')).toBeEnabled();
  await ask(page, 'Find my tickets');
  await expect(page.getByRole('alertdialog')).toContainText('Agent index is not ready');
  await page.getByRole('button', { name: 'OK', exact: true }).click();
  await chat.getByRole('button', { name: 'Prepare agent index', exact: true }).click();
  await expect(chat.getByRole('button', { name: 'Prepare agent index', exact: true })).toHaveCount(0);
  await ask(page, 'Tell me about 2 and related work');
  await expect(chat.locator('.agent-assistant').last()).toContainText('Rotate refresh tokens');
  await expect(chat.locator('.agent-assistant').last()).toContainText('APP-1');
  await expect(chat.locator('.agent-assistant').last()).not.toContainText('OTHER-2');
  await chat.getByLabel('Response details', { exact: true }).click();
  await chat.getByRole('button', { name: /APP-2.*Rotate refresh tokens/ }).click();
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByRole('heading', { name: 'Rotate refresh tokens' })).toBeVisible();
  await drawer.getByRole('button', { name: 'Ask Sprint Agent' }).click();
  await expect(drawer).not.toBeVisible();
  await expect(chat.getByRole('button', { name: 'Remove attached APP-2' })).toBeVisible();
  await ask(page, 'Analyze this ticket');
  await expect(chat.locator('.agent-assistant')).toHaveCount(2);
  await expect(chat.locator('.agent-assistant').last()).toContainText('OAuth refresh');
  await page.screenshot({ path: `test-results/agent-${info.project.name}.png` });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await chat.boundingBox())!.x).toBeGreaterThanOrEqual(0);
  await page.reload();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  await expect(chat.locator('.agent-assistant')).toHaveCount(2);
  await page.getByRole('button', { name: 'Close Sprint Agent' }).click();
  await page.getByRole('link', { name: 'Sprint explorer', exact: true }).click();
  await page.getByLabel('Sprint', { exact: true }).selectOption('Sprint 2');
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  await ask(page, 'Summarize this sprint');
  await expect(
    chat
      .locator('.agent-assistant')
      .last()
      .getByRole('cell', { name: 'Total tickets', exact: true })
      .locator('..')
  ).toContainText('1');
  await expect(
    chat
      .locator('.agent-assistant')
      .last()
      .getByRole('cell', { name: 'Distinct reporters', exact: true })
      .locator('..')
  ).toContainText('1');
  await chat.getByRole('button', { name: 'Close Sprint Agent' }).click();
  await page.getByLabel('Project', { exact: true }).selectOption('OTHER');
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  await expect(chat.locator('.agent-assistant')).toHaveCount(3);
  await expect(chat.getByRole('button', { name: 'Remove attached APP-2' })).toHaveCount(0);
  await ask(page, 'Tell me about 2');
  await expect(chat.locator('.agent-assistant').last()).toContainText('Separate database migration');
  await chat.getByRole('button', { name: 'New chat', exact: true }).click();
  await expect(chat.locator('.agent-assistant')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('automatic index in setup and failed chat keeps the draft for retry', async ({ page }) => {
  await upload(page);
  await expect(page.getByRole('region', { name: 'Sprint Agent setup' })).toContainText(
    'Ticket context is ready'
  );
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  const offline = (route: import('@playwright/test').Route) =>
    route.fulfill({
      status: 502,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Model connection unavailable. Retry shortly.' }),
    });
  await page.route('**/agent/chat', offline);
  await chat.getByLabel('Message Sprint Agent').fill('Find OAuth rotation');
  await chat.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(chat.getByRole('alert')).toContainText('Model connection unavailable');
  await expect(chat.getByLabel('Message Sprint Agent')).toHaveValue('');
  await expect(chat.getByLabel('Pending messages')).toContainText('Find OAuth rotation');
  await page.unroute('**/agent/chat', offline);
  await chat.getByRole('button', { name: 'Resume pending messages', exact: true }).click();
  await expect(chat.locator('.agent-assistant')).toContainText('Rotate refresh tokens');
});

test('model switcher and GPT connection settings save, edit, redact and remove keys', async ({
  page,
}, info) => {
  await upload(page);
  await enter(page);
  const local = ['qwen3:8b', 'qwen3:14b'].map((model) => ({
    id: `env:${model}`,
    name: model,
    model,
    provider: 'compatible',
    web_available: false,
  }));
  await page.route('**/agent/status', async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: {
        ...body,
        choices: [...local, ...body.choices],
        model: { ...body.model, available: true, name: 'qwen3:8b', provider: 'compatible' },
      },
    });
  });
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  const picker = chat.getByLabel('Agent model', { exact: true });
  await picker.selectOption('env:qwen3:14b');
  await page.route('**/agent/chat', async (route) => {
    const body = route.request().postDataJSON();
    expect(body.connection_id).toBe('env:qwen3:14b');
    await route.fulfill({
      json: {
        session_id: 'test-model-session',
        mode: 'ai',
        model: 'qwen3:14b',
        content: 'APP-2 is ready for testing.',
        sources: [],
        tools: [],
        web_sources: [],
      },
    });
  });
  await chat.getByRole('button', { name: 'Close agent configuration' }).click();
  await ask(page, 'Review the selected ticket');
  await expect(chat.locator('.agent-assistant').last()).toContainText('qwen3:14b');
  await chat.getByRole('button', { name: 'Configure agent' }).click();
  await chat.getByRole('button', { name: 'Add model connection' }).click();
  await chat.getByLabel('Connection name', { exact: true }).fill('Browser GPT test');
  await chat.getByLabel('Model or deployment name').fill('test-gpt');
  await chat.getByLabel('Model API key', { exact: true }).fill('sk-browser-private-test');
  await chat.getByLabel('OpenAI project ID', { exact: true }).fill('proj_browser');
  let profileId = '';
  try {
    const saved = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/agent/connections') && response.request().method() === 'POST'
    );
    await chat.getByRole('button', { name: 'Save model connection', exact: true }).click();
    const response = await saved;
    const profile = await response.json();
    profileId = profile.id;
    expect(profile.has_key).toBe(true);
    expect(JSON.stringify(profile)).not.toContain('sk-browser-private-test');
    await expect(picker).toHaveValue(profileId);
    await expect(chat.getByRole('button', { name: 'Edit Browser GPT test' })).toBeVisible();
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('sk-browser-private-test');
    await chat.getByRole('button', { name: 'Edit Browser GPT test' }).click();
    await expect(chat.getByLabel('Model API key', { exact: true })).toHaveValue('');
    await expect(chat.getByLabel('OpenAI project ID', { exact: true })).toHaveValue('proj_browser');
    await chat.getByRole('button', { name: 'Cancel connection editing' }).click();
    await page.screenshot({ path: `test-results/model-settings-${info.project.name}.png` });
    await chat.getByRole('button', { name: 'Remove Browser GPT test' }).click();
    await expect(chat.getByRole('button', { name: 'Edit Browser GPT test' })).toHaveCount(0);
    await picker.selectOption('env:qwen3:14b');
    await chat.getByRole('button', { name: 'New chat', exact: true }).click();
    await page.reload();
    await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
    await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
    await expect(picker).toHaveValue('env:qwen3:14b');
  } finally {
    if (profileId) await page.request.delete('/api/agent/connections/' + profileId);
  }
});

test('Gemini free-tier setup and OpenAI Platform project guidance stay separate from Azure', async ({
  page,
}, info) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await chat.getByRole('button', { name: 'Configure agent' }).click();
  await chat.getByRole('button', { name: 'Add model connection', exact: true }).click();
  await expect(chat.getByLabel('Connection provider')).toHaveValue('openai');
  await expect(chat.getByRole('link', { name: 'Project usage dashboard', exact: true })).toHaveAttribute(
    'href',
    'https://platform.openai.com/usage'
  );
  await expect(chat.getByLabel('OpenAI project ID', { exact: true })).toBeVisible();
  await expect(chat.getByLabel('API compatibility', { exact: true })).toHaveValue('auto');
  await chat.getByLabel('Model or deployment name').fill('gpt-3.5-turbo');
  await expect(chat.getByLabel('Model thinking setting')).toBeDisabled();
  await expect(
    chat.getByRole('checkbox', { name: 'Offer public web search for this connection' })
  ).toBeDisabled();
  await expect(chat.getByText('GPT-3.5 Turbo uses Model default;', { exact: false })).toBeVisible();
  await chat.getByLabel('Model API key', { exact: true }).fill('synthetic-old-provider-key');
  await chat.getByLabel('Connection provider').selectOption('azure');
  await expect(chat.getByLabel('Model API key', { exact: true })).toHaveValue('');
  await chat.getByRole('button', { name: 'Cancel connection editing' }).click();
  await chat.getByRole('button', { name: 'Set up Gemini free-tier option', exact: true }).click();
  await expect(chat.getByLabel('Connection provider')).toHaveValue('gemini');
  await expect(chat.getByLabel('Model or deployment name')).toHaveValue('gemini-3.5-flash-lite');
  await expect(chat.getByLabel('Model API endpoint')).toHaveCount(0);
  await expect(chat.getByLabel('OpenAI project ID', { exact: true })).toHaveCount(0);
  await expect(chat.getByRole('link', { name: 'Google AI Studio', exact: true })).toHaveAttribute(
    'href',
    'https://aistudio.google.com/api-keys'
  );
  await expect(chat.getByText('Google may use free-tier content', { exact: false })).toBeVisible();
  await chat.getByText('Conversation context settings', { exact: true }).click();
  await expect(chat.getByLabel('Model context window')).toHaveAttribute('min', '2048');
  await chat.getByLabel('Model context window').fill('4096');
  const key = chat.getByLabel('Model API key', { exact: true });
  expect(await key.evaluate((input: HTMLInputElement) => input.required)).toBe(true);
  await key.fill('synthetic-gemini-private');
  let profileId = '';
  try {
    const saved = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/agent/connections') && response.request().method() === 'POST'
    );
    await chat.getByRole('button', { name: 'Save model connection', exact: true }).click();
    const response = await saved;
    const profile = await response.json();
    profileId = profile.id;
    expect(response.status()).toBe(201);
    expect(profile.provider).toBe('gemini');
    expect(profile.context_window).toBe(4096);
    expect(JSON.stringify(profile)).not.toContain('synthetic-gemini-private');
    await expect(chat.getByLabel('Agent model', { exact: true })).toHaveValue(profileId);
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('synthetic-gemini-private');
    await chat.getByRole('button', { name: 'Edit Gemini free-tier option' }).click();
    await expect(key).toHaveValue('');
    await page.screenshot({ path: `test-results/gemini-setup-${info.project.name}.png` });
    await chat.getByRole('button', { name: 'Cancel connection editing' }).click();
    await chat.getByRole('button', { name: 'Remove Gemini free-tier option' }).click();
    await expect(chat.getByRole('button', { name: 'Edit Gemini free-tier option' })).toHaveCount(0);
    await chat.getByRole('button', { name: 'Add model connection', exact: true }).click();
    await chat.getByLabel('Connection provider').selectOption('azure');
    await expect(chat.getByLabel('Model API endpoint')).toBeVisible();
    await expect(chat.getByLabel('OpenAI project ID', { exact: true })).toHaveCount(0);
  } finally {
    if (profileId) await page.request.delete('/api/agent/connections/' + profileId);
  }
});

test('streamed activity, safe Markdown, charts and answer provenance render together', async ({
  page,
}, info) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  const events = [
    { event: 'activity', message: 'Resolving Sprint 43 across the export.' },
    { event: 'activity', message: 'Calculating Done share: 1 / 4 * 100 = 25.' },
    { event: 'answer_start' },
    { event: 'text_delta', text: '## Sprint 43\n\n**Evidence-based summary**\n\n' },
    {
      event: 'text_delta',
      text: '| Metric | Tickets |\n| --- | ---: |\n| Total | 4 |\n\n- APP-2 requires testing.\n\n<script>window.agentUnsafe=true</script>',
    },
    {
      event: 'chart',
      title: 'Status categories',
      unit: 'tickets',
      scope: { project: 'All projects', sprint: 'Example Sprint 43' },
      data: [
        { label: 'To Do', value: 2 },
        { label: 'In Progress', value: 1 },
        { label: 'Done', value: 1 },
      ],
    },
    {
      event: 'done',
      session_id: 'markdown-test',
      mode: 'ai',
      model: 'qwen3:8b',
      skill: 'sprint',
      content:
        '## Sprint 43\n\n**Evidence-based summary**\n\n| Metric | Tickets |\n| --- | ---: |\n| Total | 4 |\n\n- APP-2 requires testing.\n\n<script>window.agentUnsafe=true</script>',
      scope: { project: 'All projects', sprint: 'Example Sprint 43' },
      activity: [
        { message: 'Resolved sprint name from exported metadata.' },
        { message: 'Calculated Done share: 25% (1/4).' },
      ],
      sources: [
        {
          key: 'APP-2',
          summary: 'Rotate refresh tokens',
          status: 'Testing',
          reason: 'Sprint analysis example',
          excerpt: '',
        },
      ],
      tools: [
        { tool: 'sprint_summary', ok: true, result_count: 0 },
        { tool: 'calculator', ok: true, result_count: 0 },
      ],
      charts: [
        {
          title: 'Status categories',
          unit: 'tickets',
          scope: { project: 'All projects', sprint: 'Example Sprint 43' },
          data: [
            { label: 'To Do', value: 2 },
            { label: 'In Progress', value: 1 },
            { label: 'Done', value: 1 },
          ],
        },
      ],
      web_sources: [],
    },
  ];
  await page.route('**/agent/chat', (route) =>
    route.fulfill({
      contentType: 'application/x-ndjson',
      body: events.map((e) => JSON.stringify(e)).join('\n') + '\n',
    })
  );
  await ask(page, 'Summarize sprint 43');
  await expect(chat.getByRole('heading', { name: 'Sprint 43', exact: true })).toBeVisible();
  await expect(chat.locator('strong').filter({ hasText: 'Evidence-based summary' })).toBeVisible();
  await expect(chat.getByRole('table')).toBeVisible();
  await expect(chat.getByRole('cell', { name: 'Total', exact: true })).toBeVisible();
  await expect(chat.getByRole('figure', { name: 'Status categories', exact: true })).toBeVisible();
  await chat.getByRole('button', { name: 'Show agent activity', exact: true }).click();
  await expect(chat.getByText('Calculated Done share: 25% (1/4).', { exact: true })).toBeVisible();
  expect(
    await page.evaluate(() => Boolean((window as unknown as { agentUnsafe?: boolean }).agentUnsafe))
  ).toBe(false);
  await page.screenshot({ path: `test-results/agent-analysis-${info.project.name}.png` });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await chat.locator('.agent-message-text').getByRole('button', { name: 'APP-2', exact: true }).click();
  await expect(
    page.getByRole('dialog').getByRole('heading', { name: 'Rotate refresh tokens' })
  ).toBeVisible();
});

test('employee metadata lookup and numbered sprint summaries work across page projects', async ({ page }) => {
  await upload(page);
  await enter(page);
  await page.getByLabel('Project', { exact: true }).selectOption('OTHER');
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await ask(page, 'tell me about Ana work items');
  await expect(
    chat
      .locator('.agent-assistant')
      .last()
      .getByRole('cell', { name: 'Assigned tickets', exact: true })
      .locator('..')
  ).toContainText('2');
  await ask(page, 'summarise sprint 2');
  await expect(
    chat.locator('.agent-assistant').last().getByRole('heading', { name: 'Sprint 2', exact: true })
  ).toBeVisible();
  await expect(
    chat
      .locator('.agent-assistant')
      .last()
      .getByRole('cell', { name: 'Total tickets', exact: true })
      .locator('..')
  ).toContainText('1');
  await ask(page, 'tell me about Taylor work items');
  await expect(chat.locator('.agent-assistant').last()).toContainText(
    'No exported assignee or reporter matches'
  );
  await expect(chat.locator('.agent-assistant').last().getByRole('button', { name: /APP-/ })).toHaveCount(0);
});

test('historical retrieval-fallback messages remain readable without relabeling them as AI', async ({
  page,
}) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  const content =
    '**Verified retrieval fallback**\n\nAI synthesis was unavailable for this turn.\n\n- **APP-2** — Rotate refresh tokens · Testing';
  const events = [
    { event: 'activity', message: 'The model skipped retrieval. Retrying once with a focused tool list.' },
    { event: 'text_delta', text: content },
    {
      event: 'done',
      session_id: 'fallback-test',
      mode: 'retrieval',
      model: null,
      attempted_model: 'test-model',
      fallback_reason: 'tool_use_unavailable',
      content,
      scope: { project: 'All projects', sprint: 'All issues' },
      activity: [{ message: 'The model skipped retrieval. Retrying once with a focused tool list.' }],
      sources: [
        {
          key: 'APP-2',
          summary: 'Rotate refresh tokens',
          status: 'Testing',
          reason: 'Title/description search candidate',
          excerpt: '',
        },
      ],
      tools: [{ tool: 'search_tickets', ok: true, result_count: 1 }],
      charts: [],
      web_sources: [],
    },
  ];
  await page.route('**/agent/chat', (route) =>
    route.fulfill({
      contentType: 'application/x-ndjson',
      body: events.map((e) => JSON.stringify(e)).join('\n') + '\n',
    })
  );
  await ask(page, 'Find tickets about OAuth');
  await expect(chat.locator('.agent-message-label').filter({ hasText: 'Retrieval preview' })).toBeVisible();
  await expect(chat.getByText('Verified retrieval fallback', { exact: true })).toBeVisible();
  await expect(chat.getByRole('alert')).toHaveCount(0);
  await expect(chat.getByLabel('Message Sprint Agent')).toBeEnabled();
  await chat.locator('.agent-message-text').getByRole('button', { name: 'APP-2', exact: true }).click();
  await expect(
    page.getByRole('dialog').getByRole('heading', { name: 'Rotate refresh tokens' })
  ).toBeVisible();
});

test('conversation scope survives priority followups, history resume and reload', async ({ page }, info) => {
  const contents = csv
    .replace('Project key,Description', 'Project key,Priority,Description')
    .replaceAll(',APP,', ',APP,High,')
    .replaceAll(',OTHER,', ',OTHER,High,');
  await upload(page, true, contents);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await ask(page, 'Tell me about Ana work items');
  await expect(chat.locator('.agent-assistant').last()).toContainText('Assigned tickets');
  await expect(chat.locator('.agent-conversation-scope')).toContainText('Assignee: Ana');
  await ask(page, 'What are the high priority tickets?');
  const last = chat.locator('.agent-assistant').last();
  await expect(last.getByRole('heading', { name: 'Matching tickets' })).toBeVisible();
  await expect(last.getByRole('cell', { name: 'APP-1', exact: true })).toBeVisible();
  await expect(last.getByRole('cell', { name: 'APP-2', exact: true })).toBeVisible();
  await expect(last.getByRole('cell', { name: 'APP-3', exact: true })).toHaveCount(0);
  await expect(chat.locator('.agent-conversation-scope')).toContainText('Priority: High');
  await chat.getByRole('button', { name: 'New chat', exact: true }).click();
  await expect(chat.locator('.agent-messages article')).toHaveCount(0);
  await ask(page, 'Tell me about Bo work items');
  await expect(chat.locator('.agent-conversation-scope')).toContainText('Assignee: Bo');
  await chat.getByRole('button', { name: 'Conversation history', exact: true }).click();
  const history = chat.getByRole('region', { name: 'Conversation history' });
  await expect(history.getByRole('button').filter({ hasText: 'Tell me about Ana work items' })).toBeVisible();
  await expect(history.getByRole('button').filter({ hasText: 'Tell me about Bo work items' })).toBeVisible();
  await page.screenshot({ path: `test-results/conversation-history-${info.project.name}.png` });
  await history.getByRole('button').filter({ hasText: 'Tell me about Ana work items' }).click();
  await expect(chat.locator('.agent-conversation-scope')).toContainText('Assignee: Ana');
  await expect(chat.locator('.agent-conversation-scope')).toContainText('Priority: High');
  await page.reload();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  await expect(chat.locator('.agent-conversation-scope')).toContainText('Assignee: Ana');
  await ask(page, 'Only stories');
  await expect(
    chat.locator('.agent-assistant').last().getByRole('heading', { name: 'Matching tickets' })
  ).toBeVisible();
  await expect(chat.locator('.agent-conversation-scope')).toContainText('Type: Story');
  await chat.getByRole('button', { name: 'Message context', exact: true }).click();
  await chat.getByRole('button', { name: 'Clear context for next message' }).click();
  await ask(page, 'Show high priority tickets');
  await expect(chat.locator('.agent-conversation-scope')).not.toContainText('Assignee: Ana');
  await expect(
    chat.locator('.agent-assistant').last().getByRole('cell', { name: 'APP-3', exact: true })
  ).toBeVisible();
});

test('history can restore a conversation with its original CSV import', async ({ page }) => {
  await upload(page);
  await enter(page);
  const filename = `archived-snapshot-${Date.now()}.csv`;
  const imported = await page.request.post('/api/imports', {
    multipart: {
      file: { name: filename, mimeType: 'text/csv', buffer: Buffer.from(csv) },
      prepare_agent: 'true',
    },
  });
  const foreign = await imported.json();
  expect(imported.ok()).toBe(true);
  await expect
    .poll(
      async () => (await (await page.request.get(`/api/datasets/${foreign.id}/agent/status`)).json()).status
    )
    .toBe('ready');
  const saved = await page.request.post(`/api/datasets/${foreign.id}/agent/chat`, {
    data: { message: 'Tell me about Bo work items', mode: 'retrieval' },
  });
  expect(saved.ok()).toBe(true);
  const conversation = await saved.json();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  let chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await chat.getByRole('button', { name: 'Conversation history', exact: true }).click();
  await chat.getByLabel('Include conversations from all CSV imports').check();
  const entry = chat
    .getByRole('region', { name: 'Conversation history' })
    .getByRole('button')
    .filter({ hasText: filename })
    .filter({ hasText: 'Tell me about Bo work items' });
  await expect(entry).toBeVisible();
  await entry.click();
  chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await expect(chat).toBeVisible();
  await expect(chat.locator('.agent-conversation-scope')).toContainText('Assignee: Bo');
  await expect(page.locator('.source-line')).toContainText(filename);
  expect(await page.evaluate(() => localStorage.getItem('sprintlens.dataset'))).toBe(foreign.id);
  expect(await page.evaluate((id) => localStorage.getItem(`sprintlens.chat.${id}`), foreign.id)).toBe(
    conversation.session_id
  );
});

test('chat can move, resize and enter full screen while preserving readable bounds', async ({
  page,
}, info) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  const start = (await chat.boundingBox())!;
  const handle = chat.locator('.agent-header');
  await handle.focus();
  await handle.press('ArrowDown');
  expect((await chat.boundingBox())!.y).toBeGreaterThan(start.y);
  const moved = (await chat.boundingBox())!;
  await chat.getByRole('button', { name: 'Resize agent chat', exact: true }).focus();
  await page.keyboard.press('ArrowUp');
  expect((await chat.boundingBox())!.height).toBeLessThan(moved.height);
  if (info.project.name === 'desktop') {
    const target = (await handle.locator('h2').boundingBox())!;
    const before = (await chat.boundingBox())!;
    await page.mouse.move(target.x + 8, target.y + 8);
    await page.mouse.down();
    await page.mouse.move(target.x - 70, target.y + 8, { steps: 5 });
    await page.mouse.up();
    expect((await chat.boundingBox())!.x).toBeLessThan(before.x);
    for (const edge of ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']) {
      const original = (await chat.boundingBox())!;
      const grip = (await chat.locator(`.agent-resize-${edge}`).boundingBox())!;
      const dx = edge.includes('w') ? 25 : edge.includes('e') ? -25 : 0;
      const dy = edge.includes('n') ? 25 : edge.includes('s') ? -25 : 0;
      await page.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2);
      await page.mouse.down();
      await page.mouse.move(grip.x + grip.width / 2 + dx, grip.y + grip.height / 2 + dy, { steps: 4 });
      await page.mouse.up();
      const resized = (await chat.boundingBox())!;
      if (dx) expect(resized.width).toBeLessThan(original.width);
      if (dy) expect(resized.height).toBeLessThan(original.height);
      // Restore dimensions to exercise each edge independently above minimum size.
      await chat.getByRole('button', { name: 'Resize agent chat', exact: true }).focus();
      if (dx) {
        await page.keyboard.press('ArrowRight');
        await page.keyboard.press('ArrowRight');
      }
      if (dy) {
        await page.keyboard.press('ArrowDown');
        await page.keyboard.press('ArrowDown');
      }
    }
    const stationary = (await chat.boundingBox())!;
    await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
    expect((await chat.boundingBox())!.x).toBe(stationary.x);
    await chat.getByRole('button', { name: 'Close agent configuration' }).click();
  }
  await chat.getByRole('button', { name: 'Full screen chat' }).click();
  const fullChat = page.getByRole('dialog', { name: 'Sprint Agent chat' });
  const full = (await fullChat.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(full.width).toBe(viewport.width);
  expect(full.height).toBe(viewport.height);
  await expect(fullChat.getByRole('button', { name: 'Exit full screen' })).toBeVisible();
  await fullChat.getByLabel('Message Sprint Agent').focus();
  await page.keyboard.press('Escape');
  await expect(chat.getByRole('button', { name: 'Full screen chat' })).toBeVisible();
  const saved = (await chat.boundingBox())!;
  await page.reload();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  expect((await chat.boundingBox())!.height).toBe(saved.height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('streaming leaves manual scrolling alone and progress can remain closed', async ({ page }, info) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await page.clock.install();
  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    let count = 0;
    window.fetch = (input, init) => {
      if (!String(input).endsWith('/agent/chat')) return original(input, init);
      count++;
      const encoder = new TextEncoder();
      const long = Array.from(
        { length: 100 },
        (_, i) => `Paragraph ${i + 1}: verified context for reading.\n\n`
      ).join('');
      const body = count === 1 ? long : '## A concise answer\n\n';
      return Promise.resolve(
        new Response(
          new ReadableStream({
            start(controller) {
              const emit = (event: object) =>
                controller.enqueue(encoder.encode(JSON.stringify(event) + '\n'));
              emit({ event: 'activity', message: 'Model is analyzing the retrieved evidence.' });
              if (count === 1) {
                emit({ event: 'text_delta', text: body });
                emit({
                  event: 'done',
                  session_id: 'scroll-test',
                  content: body,
                  mode: 'ai',
                  model: 'test',
                  activity: [],
                });
                controller.close();
                return;
              }
              let n = 0;
              const timer = setInterval(() => {
                n++;
                if (n === 12) emit({ event: 'text_delta', text: body });
                if (n >= 12) emit({ event: 'text_delta', text: `Finding ${n}.\n\n` });
                if (n === 20) {
                  clearInterval(timer);
                  emit({
                    event: 'done',
                    session_id: 'scroll-test',
                    content: body + Array.from({ length: 20 }, (_, i) => `Finding ${i + 1}.\n\n`).join(''),
                    mode: 'ai',
                    model: 'test',
                    activity: [{ message: 'Model is analyzing the retrieved evidence.' }],
                  });
                  controller.close();
                }
              }, 1000);
            },
          }),
          { headers: { 'Content-Type': 'application/x-ndjson' } }
        )
      );
    };
  });
  await ask(page, 'First question');
  await expect(chat.getByRole('button', { name: 'Read full answer' })).toBeVisible();
  await chat.getByRole('button', { name: 'Read full answer' }).click();
  await ask(page, 'Explain a related point');
  await expect(chat.getByRole('button', { name: 'Stop generating' })).toBeVisible();
  const scroller = chat.locator('.agent-body');
  await scroller.evaluate((el) => {
    el.scrollTop = 0;
  });
  await page.clock.runFor(9000);
  expect(await scroller.evaluate((el) => el.scrollTop)).toBeLessThan(5);
  await expect(chat.getByRole('button', { name: 'Answer start', exact: true })).toHaveCount(0);
  await expect(chat.getByRole('button', { name: 'Latest', exact: true })).toHaveCount(0);
  const current = chat.locator('.agent-assistant').last();
  await current.scrollIntoViewIfNeeded();
  await expect(current.locator('.agent-progress-current')).toContainText('retrieved context');
  await current.getByRole('button', { name: 'Collapse agent activity' }).click();
  await page.clock.runFor(3000);
  await expect(current.getByRole('button', { name: 'Show agent activity', exact: true })).toBeVisible();
  await expect(current.locator('.agent-progress-current')).toHaveCount(0);
  await scroller.evaluate((el) => {
    el.scrollTop = 0;
  });
  await page.clock.runFor(10000);
  await expect(chat.getByRole('button', { name: 'Stop generating' })).toHaveCount(0);
  expect(await scroller.evaluate((el) => el.scrollTop)).toBeLessThan(5);
  const color = await chat
    .locator('.agent-user')
    .first()
    .evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(color).toBe('rgb(16, 63, 145)');
  await scroller.evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
  expect(await scroller.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThan(5);
  await scroller.evaluate((el) => {
    el.scrollTop = 0;
  });
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await chat.getByRole('button', { name: 'Close agent configuration' }).click();
  expect(await scroller.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThan(5);
  await scroller.evaluate((el) => {
    el.scrollTop = 0;
  });
  await chat.getByRole('button', { name: 'Conversation history', exact: true }).click();
  await chat.getByRole('button', { name: 'Conversation history', exact: true }).click();
  expect(await scroller.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThan(5);
  await scroller.evaluate((el) => {
    el.scrollTop = 0;
  });
  await chat.getByRole('button', { name: 'Close Sprint Agent' }).click();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  expect(await scroller.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThan(5);
  await chat.getByRole('button', { name: 'Full screen chat' }).click();
  await page.screenshot({ path: `test-results/chat-reading-${info.project.name}.png` });
});

test('backlog theme followup groups only its open stories with compact output', async ({ page }, info) => {
  await upload(
    page,
    true,
    csv.replace('APP-3,Improve login telemetry,Task', 'APP-3,Improve login telemetry,Story')
  );
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await ask(page, 'Review the backlog');
  await ask(page, 'Classify the story tickets by topics');
  const answer = chat.locator('.agent-assistant').last();
  await expect(answer.getByRole('heading', { name: 'Suggested work themes' })).toBeInViewport();
  await expect(answer).toContainText('1 ticket');
  await expect(answer).not.toContainText('APP-3');
  await expect(answer.getByRole('figure')).toHaveCount(0);
  await expect(chat.locator('.agent-conversation-scope')).toContainText('Backlog');
  await page.screenshot({ path: `test-results/chat-themes-${info.project.name}.png` });
});

test('clean header configuration and composer context control real retrieval', async ({ page }) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await expect(chat.locator('.agent-scope')).toHaveCount(0);
  await expect(chat.getByLabel('Agent model', { exact: true })).toHaveCount(0);
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await expect(chat.getByLabel('Agent model', { exact: true })).toBeVisible();
  await expect(chat.getByRole('heading', { name: 'Configure agent', exact: true })).toBeVisible();
  await chat.getByRole('button', { name: 'Close agent configuration' }).click();
  await ask(page, 'Tell me about Ana work items');
  const memory = chat.locator('.agent-composer .agent-conversation-scope');
  await expect(memory).toContainText('Remembering: Assignee: Ana');
  await chat.getByRole('button', { name: 'Message context', exact: true }).click();
  const pageToggle = chat.getByLabel('Use current page', { exact: true });
  await pageToggle.uncheck();
  await chat.getByRole('button', { name: 'Clear context for next message' }).click();
  await expect(memory).toContainText('Messages stay in chat history');
  const request = page.waitForRequest(
    (request) => request.url().endsWith('/agent/chat') && request.method() === 'POST'
  );
  await ask(page, 'Summarize this sprint');
  const body = (await request).postDataJSON();
  expect(body.use_page_context).toBe(false);
  expect(body.reset_context).toBe(true);
  await expect(chat.locator('.agent-assistant').last()).toContainText('Which sprint');
  await ask(page, 'Tell me about OTHER-2');
  await expect(chat.locator('.agent-assistant').last()).toContainText('Separate database migration');
  await expect(chat.locator('.agent-message.agent-user')).toHaveCount(3);
  await chat.getByRole('button', { name: 'Message context', exact: true }).click();
  await chat.getByLabel('Use conversation history', { exact: true }).uncheck();
  await expect(memory).toContainText('won’t reuse earlier people');
  await page.reload();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  await chat.getByRole('button', { name: 'Message context', exact: true }).click();
  await expect(pageToggle).not.toBeChecked();
  await expect(chat.getByLabel('Use conversation history', { exact: true })).not.toBeChecked();
  expect(await chat.locator('.agent-composer').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
});

test('project context persists per scope and chat has no diagnostic answer selector', async ({ page }) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await chat.locator('summary').filter({ hasText: 'Project context & working agreements' }).click();
  const prompt = chat.getByLabel('Project context prompt', { exact: true });
  await expect(prompt).toBeEnabled();
  await prompt.fill('Goal: reliable sign-in. Plan with 10 story points per developer per sprint.');
  await chat.getByRole('button', { name: 'Save project context', exact: true }).click();
  await expect(chat.getByRole('status')).toContainText('Project context saved');
  await expect(chat.getByRole('button', { name: 'Saved', exact: true })).toBeVisible();
  await prompt.fill('Goal: reliable sign-in. Plan with 10 story points per developer per sprint.\nUpdated');
  await expect(chat.getByRole('button', { name: 'Save project context', exact: true })).toBeVisible();
  await expect(chat.locator('.agent-context-confirmation')).toHaveCount(0);
  await prompt.fill('Goal: reliable sign-in. Plan with 10 story points per developer per sprint.');
  await chat.getByLabel('Project context scope').selectOption('');
  await expect(prompt).toHaveValue('');
  await chat.getByLabel('Project context scope').selectOption('APP');
  await expect(prompt).toHaveValue(
    'Goal: reliable sign-in. Plan with 10 story points per developer per sprint.'
  );
  await chat.getByRole('button', { name: 'Close agent configuration' }).click();
  await page.reload();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await chat.locator('summary').filter({ hasText: 'Project context & working agreements' }).click();
  await expect(prompt).toHaveValue(
    'Goal: reliable sign-in. Plan with 10 story points per developer per sprint.'
  );
  await expect(chat.getByLabel('Agent answer mode')).toHaveCount(0);
});

test('AI-written answer streams with compact repeated tool counts', async ({ page }) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await page.route('**/agent/chat', async (route) => {
    expect(route.request().postDataJSON().mode).toBe('ai');
    const tools = Array.from({ length: 8 }, () => ({ tool: 'calculator', ok: true, result_count: 1 }));
    const content =
      'The current focus is sign-in reliability. Review the testing handoff before pulling additional work.';
    const events = [
      { event: 'activity', message: 'Intent: project health · hybrid', tool: 'plan_investigation', ok: true },
      { event: 'tool_usage', tools },
      { event: 'text_delta', text: content.slice(0, 42) },
      { event: 'text_delta', text: content.slice(42) },
      {
        event: 'done',
        session_id: 'streamed-ai',
        mode: 'ai',
        model: 'test-model',
        content,
        tools,
        charts: [],
        sources: [],
        activity: [{ message: 'Intent: project health · hybrid', tool: 'plan_investigation', ok: true }],
      },
    ];
    await route.fulfill({
      contentType: 'application/x-ndjson',
      body: events.map((e) => JSON.stringify(e)).join('\n') + '\n',
    });
  });
  await ask(page, 'Give me a project overview');
  const answer = chat.locator('.agent-assistant').last();
  await expect(answer).toContainText('Review the testing handoff');
  await expect(answer.getByLabel('Tool usage summary')).toHaveCount(0);
  await answer.getByRole('button', { name: 'Show agent activity', exact: true }).click();
  await expect(answer.getByLabel('Tool usage summary')).toContainText('calculator ×8');
  await expect(answer.getByRole('table')).toHaveCount(0);
  await expect(answer.getByRole('figure')).toHaveCount(0);
  await expect(answer.getByText('More details', { exact: true })).toHaveCount(0);
});

test('chat stays unavailable without a model instead of generating a report', async ({ page }) => {
  await page.route('**/agent/status', async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: { ...body, choices: [], model: { ...body.model, available: false } },
    });
  });
  await page.goto('/');
  await page
    .getByLabel('Jira CSV file')
    .setInputFiles({ name: 'no-model.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  await page.getByRole('button', { name: 'Explore my project' }).click();
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await expect(chat.getByLabel('Message Sprint Agent')).toBeEnabled();
  await ask(page, 'Who works here?');
  await expect(page.getByRole('alertdialog')).toContainText('AI model is not configured');
  await page.getByRole('button', { name: 'OK', exact: true }).click();
  await expect(chat.getByLabel('Message Sprint Agent')).toHaveValue('Who works here?');
  await expect(chat).toContainText('Connect a model');
  await expect(chat).toContainText('automatic reports are disabled');
  await expect(chat.locator('.agent-assistant')).toHaveCount(0);
});

test('response details stay in one footer and full remembered context opens beside Send', async ({
  page,
}, info) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  const memory =
    'Assignee: Ana · Discussed tickets: ' + Array.from({ length: 40 }, (_, i) => `APP-${i + 1}`).join(', ');
  await page.route('**/agent/chat', async (route) => {
    await route.fulfill({
      json: {
        session_id: 'footer-test',
        role: 'assistant',
        content: 'Ana handles these work items.',
        context_description: memory,
        scope: { project: 'APP', sprint: 'Sprint 2' },
        sources: [
          {
            key: 'APP-2',
            summary: 'Rotate refresh tokens',
            reason: 'Ticket metadata',
            status: 'Testing',
            excerpt: 'OAuth',
          },
        ],
        tools: [
          { tool: 'get_ticket', ok: true, result_count: 1 },
          { tool: 'get_ticket', ok: true, result_count: 1 },
        ],
      },
    });
  });
  await ask(page, 'Who handles these?');
  const answer = chat.locator('.agent-assistant').last();
  const footer = answer.locator('.agent-response-footer');
  await expect(footer).toHaveCount(1);
  await expect(footer.locator('summary')).toContainText('APP · Sprint 2');
  await expect(footer.locator('summary')).toContainText('1 ticket · 2 tool calls');
  await expect(footer.locator('.agent-footer-content')).not.toBeVisible();
  await expect(chat.getByRole('dialog', { name: 'Message context and memory' })).not.toBeVisible();
  await footer.getByLabel('Response details', { exact: true }).click();
  await expect(footer.getByRole('region', { name: 'Tools used' })).toContainText('get ticket ×2');
  await expect(footer.getByRole('region', { name: 'Ticket sources' })).toContainText('Rotate refresh tokens');
  await footer.getByLabel('Response details', { exact: true }).click();
  const toggle = chat.getByRole('button', { name: 'Message context', exact: true });
  const send = chat.getByRole('button', { name: 'Send message', exact: true });
  expect(Math.abs((await toggle.boundingBox())!.x - (await send.boundingBox())!.x)).toBeLessThan(2);
  await toggle.click();
  const popup = chat.getByRole('dialog', { name: 'Message context and memory' });
  await expect(popup).toBeVisible();
  await popup.getByLabel('Investigation effort').selectOption('high');
  expect(await page.evaluate(() => localStorage.getItem('agileplanner.agent.effort'))).toBe('high');
  await expect(popup.locator('.agent-conversation-scope')).toHaveText(`Remembering: ${memory}Start fresh`);
  await expect(popup.locator('.agent-conversation-scope > span')).toHaveCSS('-webkit-line-clamp', 'none');
  expect(await popup.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.screenshot({ path: `test-results/chat-context-footer-${info.project.name}.png` });
  await page.keyboard.press('Escape');
  await expect(popup).not.toBeVisible();
  await expect(toggle).toBeFocused();
  await toggle.click();
  await chat.locator('.agent-header h2').click();
  await expect(popup).not.toBeVisible();
});

test('live agent flow collapses at the first answer token and can be reopened during streaming', async ({
  page,
}) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await page.clock.install();
  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    window.fetch = (input, init) => {
      if (!String(input).endsWith('/agent/chat')) return original(input, init);
      const encoder = new TextEncoder();
      return Promise.resolve(
        new Response(
          new ReadableStream({
            start(controller) {
              const emit = (event: object) =>
                controller.enqueue(encoder.encode(JSON.stringify(event) + '\n'));
              emit({
                event: 'context',
                context_description: 'Focus: Overall Sprint 2 report · Project: APP · Sprint: Sprint 2',
              });
              emit({ event: 'activity', message: 'Reading your question.' });
              emit({ event: 'activity', message: 'Checking ticket metadata.', tool: 'query_metadata' });
              setTimeout(() => {
                emit({
                  event: 'activity',
                  message: 'Ticket evidence ready.',
                  tool: 'query_metadata',
                  ok: true,
                });
                emit({ event: 'text_delta', text: 'Two tickets need review.' });
              }, 3000);
              setTimeout(() => {
                emit({
                  event: 'done',
                  session_id: 'flow-test',
                  context_description: 'Focus: Overall Sprint 2 report · Project: APP · Sprint: Sprint 2',
                  content: 'Two tickets need review.',
                  activity: [
                    { message: 'Reading your question.' },
                    { message: 'Checking ticket metadata.' },
                    { message: 'Ticket evidence ready.', tool: 'query_metadata', ok: true },
                  ],
                });
                controller.close();
              }, 7000);
            },
          }),
          { headers: { 'Content-Type': 'application/x-ndjson' } }
        )
      );
    };
  });
  await ask(page, 'Review work');
  const answer = chat.locator('.agent-assistant').last();
  await expect(answer.getByRole('log', { name: 'Agent activity' })).toBeVisible();
  await expect(answer.getByRole('log')).toContainText('Checking ticket metadata.');
  await chat.getByRole('button', { name: 'Message context', exact: true }).click();
  const contextPopup = chat.getByRole('dialog', { name: 'Message context and memory' });
  await expect(contextPopup).toContainText('Remembering: Focus: Overall Sprint 2 report');
  await expect(contextPopup).not.toContainText('Assignee:');
  await chat.getByRole('button', { name: 'Close message context', exact: true }).click();
  await page.clock.runFor(3500);
  await expect(answer.locator('.agent-message-text')).toContainText('Two tickets need review.');
  await expect(answer.getByRole('log')).toHaveCount(0);
  await expect(answer.locator('.agent-activity-content')).toHaveCount(0);
  const toggle = answer.getByRole('button', { name: 'Show agent activity', exact: true });
  await expect(toggle).toContainText('Actions · 1 tool call');
  await toggle.click();
  await expect(answer.locator('.agent-activity-log')).toContainText('Ticket evidence ready.');
  await page.clock.runFor(4000);
  await expect(answer.locator('.agent-activity-log')).toBeVisible();
  await answer.getByRole('button', { name: 'Collapse agent activity' }).click();
  await expect(answer.locator('.agent-activity-content')).toHaveCount(0);
});

test('open ticket drawer is optional page context without attaching it', async ({ page }) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await ask(page, 'Explain APP-2');
  await chat
    .locator('.agent-message-text')
    .getByRole('button', { name: 'APP-2', exact: true })
    .first()
    .click();
  const drawer = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('heading', { name: 'Rotate refresh tokens', exact: true }) });
  await expect(drawer).toBeVisible();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  await chat.getByRole('button', { name: 'New chat', exact: true }).click();
  await expect(drawer).toBeVisible();
  await chat.getByRole('button', { name: 'Message context', exact: true }).click();
  const popup = chat.getByRole('dialog', { name: 'Message context and memory' });
  await expect(popup).toContainText('Open ticket: APP-2');
  await page.keyboard.press('Escape');
  await expect(popup).not.toBeVisible();
  await expect(drawer).toBeVisible();
  const request = page.waitForRequest((r) => r.url().endsWith('/agent/chat') && r.method() === 'POST');
  await ask(page, 'explain this ticket');
  const body = (await request).postDataJSON();
  expect(body.page_ticket).toBe('APP-2');
  expect(body.attachments).toEqual([]);
  await expect(chat.locator('.agent-assistant').last()).toContainText('Rotate refresh tokens');
  await expect(drawer).toBeVisible();
  await chat.getByRole('button', { name: 'New chat', exact: true }).click();
  await chat.getByRole('button', { name: 'Message context', exact: true }).click();
  await chat.getByLabel('Use current page', { exact: true }).uncheck();
  await ask(page, 'explain this ticket');
  await expect(chat.locator('.agent-assistant').last()).toContainText('Which ticket');
  await chat.getByRole('button', { name: 'Message context', exact: true }).click();
  await chat.getByLabel('Use current page', { exact: true }).check();
  await chat.getByRole('button', { name: 'Close message context', exact: true }).click();
  await chat.getByRole('button', { name: 'Close Sprint Agent' }).click();
  await drawer.getByRole('button', { name: 'Close issue details' }).click();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  await chat.getByRole('button', { name: 'New chat', exact: true }).click();
  const closed = page.waitForRequest((r) => r.url().endsWith('/agent/chat') && r.method() === 'POST');
  await ask(page, 'explain this ticket');
  expect((await closed).postDataJSON().page_ticket).toBe('');
  await expect(chat.locator('.agent-assistant').last()).toContainText('Which ticket');
});

async function controlledChat(page: Page) {
  await page.evaluate(() => {
    const realFetch = window.fetch.bind(window);
    const w = window as unknown as {
      deliveries: Record<string, unknown>[];
      finishDelivery: (text: string) => void;
      steerDelivery: () => void;
    };
    w.deliveries = [];
    window.fetch = (input, init) => {
      if (!String(input).endsWith('/agent/chat')) return realFetch(input, init);
      w.deliveries.push(JSON.parse(String(init?.body)));
      const encoder = new TextEncoder();
      return Promise.resolve(
        new Response(
          new ReadableStream({
            start(controller) {
              const emit = (event: object) =>
                controller.enqueue(encoder.encode(JSON.stringify(event) + '\n'));
              emit({ event: 'run', request_id: w.deliveries[w.deliveries.length - 1].request_id });
              emit({ event: 'activity', message: 'Checking the request.' });
              w.steerDelivery = () =>
                emit({ event: 'steering', count: 1, message: 'Applying your steering messages.' });
              w.finishDelivery = (content) => {
                emit({ event: 'done', session_id: 'delivery-session', content });
                controller.close();
              };
              init?.signal?.addEventListener('abort', () =>
                controller.error(new DOMException('Stopped', 'AbortError'))
              );
            },
          }),
          { headers: { 'Content-Type': 'application/x-ndjson' } }
        )
      );
    };
  });
}

test('queue default keeps drafts editable and delivers sequentially with conversation history', async ({
  page,
}, info) => {
  await upload(page);
  await expect(page.getByRole('region', { name: 'Sprint Agent setup' })).toContainText(
    'Ticket context is ready'
  );
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await controlledChat(page);
  await ask(page, 'First question');
  await expect(chat.getByLabel('Message Sprint Agent')).toBeEnabled();
  await ask(page, 'Second question');
  await ask(page, 'Third question');
  await expect(chat.getByLabel('Pending messages')).toContainText('2 queued');
  await chat.getByLabel('Message Sprint Agent').fill('Still drafting');
  expect(await page.evaluate(() => (window as any).deliveries.length)).toBe(1);
  await page.evaluate(() => (window as any).finishDelivery('First answer'));
  await expect.poll(() => page.evaluate(() => (window as any).deliveries.length)).toBe(2);
  expect(await page.evaluate(() => (window as any).deliveries[1].session_id)).toBe('delivery-session');
  await expect(chat.getByLabel('Message Sprint Agent')).toHaveValue('Still drafting');
  await page.evaluate(() => (window as any).finishDelivery('Second answer'));
  await expect.poll(() => page.evaluate(() => (window as any).deliveries.length)).toBe(3);
  await page.evaluate(() => (window as any).finishDelivery('Third answer'));
  await expect(chat.locator('.agent-assistant').last()).toContainText('Third answer');
  await expect(chat.getByLabel('Pending messages')).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).deliveries.map((d: any) => d.message))).toEqual([
    'First question',
    'Second question',
    'Third question',
  ]);
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await expect(chat.getByLabel('Message delivery mode')).toHaveValue('queue');
  await chat.getByRole('button', { name: 'Close agent configuration' }).click();
  await page.screenshot({ path: `test-results/agent-delivery-${info.project.name}.png` });
});

test('steer mode accepts four followups, blocks the fifth and keeps one final response', async ({ page }) => {
  await upload(page);
  await expect(page.getByRole('region', { name: 'Sprint Agent setup' })).toContainText(
    'Ticket context is ready'
  );
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await chat.getByLabel('Message delivery mode').selectOption('steer');
  await chat.getByRole('button', { name: 'Close agent configuration' }).click();
  await controlledChat(page);
  const steering: string[] = [];
  await page.route('**/agent/chat/*/steer', async (route) => {
    steering.push(route.request().postDataJSON().message);
    await route.fulfill({ json: { accepted: true, count: steering.length } });
  });
  await ask(page, 'Summarize my sprint');
  for (let i = 1; i <= 4; i++) {
    await ask(page, `Follow-up ${i}`);
    await expect(chat.locator('.agent-steer-status')).toContainText(`${i}/4 steering messages`);
    if (i === 2) await page.evaluate(() => (window as any).steerDelivery());
  }
  await ask(page, 'Fifth message');
  await expect(page.getByRole('alertdialog')).toContainText('Please wait for responses');
  expect(steering).toHaveLength(4);
  await page.getByRole('button', { name: 'OK', exact: true }).click();
  await expect(chat.getByLabel('Message Sprint Agent')).toHaveValue('Fifth message');
  await page.evaluate(() => (window as any).finishDelivery('Updated answer considers your corrections.'));
  await expect(chat.locator('.agent-assistant')).toHaveCount(1);
  await expect(chat.locator('.agent-assistant')).toContainText('Updated answer');
  await expect(chat.locator('.agent-user')).toHaveCount(5);
  expect(await page.evaluate(() => (window as any).deliveries.length)).toBe(1);
});

test('stopping a response preserves new drafts and pending messages until resumed', async ({ page }) => {
  await upload(page);
  await expect(page.getByRole('region', { name: 'Sprint Agent setup' })).toContainText(
    'Ticket context is ready'
  );
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await controlledChat(page);
  await ask(page, 'Original question');
  await ask(page, 'Queued question');
  await chat.getByLabel('Message Sprint Agent').fill('A new draft');
  await chat.getByRole('button', { name: 'Stop generating' }).click();
  await expect(chat.getByLabel('Pending messages')).toContainText('2 pending');
  await expect(chat.getByLabel('Message Sprint Agent')).toHaveValue('A new draft');
  expect(await page.evaluate(() => (window as any).deliveries.length)).toBe(1);
  await chat.getByRole('button', { name: 'Resume pending messages' }).click();
  await expect.poll(() => page.evaluate(() => (window as any).deliveries.length)).toBe(2);
  await page.evaluate(() => (window as any).finishDelivery('Retried answer'));
  await expect.poll(() => page.evaluate(() => (window as any).deliveries.length)).toBe(3);
  await page.evaluate(() => (window as any).finishDelivery('Queued answer'));
  await expect(chat.locator('.agent-assistant').last()).toContainText('Queued answer');
});

test('workspace back and agent right swipe have separate navigation without losing sprint scope', async ({
  page,
}) => {
  await upload(page);
  await enter(page);
  await page.getByRole('link', { name: 'Sprint explorer', exact: true }).click();
  await page.getByLabel('Sprint', { exact: true }).selectOption('Sprint 2');
  await page.getByRole('button', { name: 'APP-2', exact: true }).first().click();
  const ticket = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('heading', { name: 'Rotate refresh tokens', exact: true }) });
  await expect(ticket).toBeVisible();
  await page.goBack();
  await expect(ticket).toHaveCount(0);
  await expect(page.getByLabel('Sprint', { exact: true })).toHaveValue('Sprint 2');
  await expect(page.getByRole('heading', { name: 'Your sprint, in focus.' })).toBeVisible();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  const history = await page.evaluate(() => ({
    length: window.history.length,
    state: window.history.state,
    url: location.href,
  }));
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await expect(chat.getByRole('heading', { name: 'Configure agent' })).toBeVisible();
  expect(
    await page.evaluate(() => ({
      length: window.history.length,
      state: window.history.state,
      url: location.href,
    }))
  ).toEqual(history);
  await chat.getByRole('heading', { name: 'Configure agent' }).evaluate((element) => {
    const touch = (x: number) => new Touch({ identifier: 1, target: element, clientX: x, clientY: 200 });
    element.dispatchEvent(new TouchEvent('touchstart', { bubbles: true, touches: [touch(35)] }));
    element.dispatchEvent(
      new TouchEvent('touchend', { bubbles: true, cancelable: true, changedTouches: [touch(190)] })
    );
  });
  await expect(chat.getByRole('heading', { name: 'Configure agent' })).toHaveCount(0);
  await expect(page.getByLabel('Sprint', { exact: true })).toHaveValue('Sprint 2');
  await expect(chat).toBeVisible();
  expect(
    await page.evaluate(() => ({
      length: window.history.length,
      state: window.history.state,
      url: location.href,
    }))
  ).toEqual(history);
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Your project, in focus.' })).toBeVisible();
  await expect(chat.getByRole('heading', { name: 'Configure agent' })).toBeVisible();
});

for (const fullScreen of [false, true]) {
  test(`agent trackpad back stays local in ${fullScreen ? 'full screen' : 'floating chat'}`, async ({
    page,
  }) => {
    await upload(page);
    await enter(page);
    await page.getByRole('link', { name: 'Sprint explorer', exact: true }).click();
    await page.getByLabel('Sprint', { exact: true }).selectOption('Sprint 2');
    await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
    const chat = page.locator('.agent-panel');
    if (fullScreen) await chat.getByRole('button', { name: 'Full screen chat', exact: true }).click();
    const history = await page.evaluate(() => ({
      length: window.history.length,
      state: window.history.state,
      url: location.href,
    }));
    await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
    const heading = chat.getByRole('heading', { name: 'Configure agent' });
    const body = chat.locator('.agent-body');
    await body.dispatchEvent('wheel', { deltaX: -3, deltaY: 120 });
    await expect(heading).toBeVisible();
    await body.dispatchEvent('wheel', { deltaX: -20, deltaY: 0, ctrlKey: true });
    await expect(heading).toBeVisible();
    const consumed = await heading.evaluate((element) => {
      const fire = (x: number) =>
        !element.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX: x }));
      return [fire(-50), fire(-50), fire(-180)];
    });
    expect(consumed).toEqual([true, true, true]);
    await expect(heading).toHaveCount(0);
    await expect(chat).toBeVisible();
    expect(
      await page.evaluate(() => ({
        length: window.history.length,
        state: window.history.state,
        url: location.href,
      }))
    ).toEqual(history);
    await chat.getByRole('button', { name: 'Conversation history', exact: true }).click();
    await expect(chat.getByRole('region', { name: 'Conversation history', exact: true })).toBeVisible();
    await page.waitForTimeout(260);
    await body.dispatchEvent('wheel', { deltaX: -100, deltaY: 0 });
    await expect(chat.getByRole('region', { name: 'Conversation history', exact: true })).toHaveCount(0);
    await chat.getByRole('button', { name: 'Message context', exact: true }).click();
    await expect(chat.getByRole('dialog', { name: 'Message context and memory' })).toBeVisible();
    await chat.getByRole('button', { name: 'Message context', exact: true }).press('Alt+ArrowLeft');
    await expect(chat.getByRole('dialog', { name: 'Message context and memory' })).toHaveCount(0);
    expect(
      await page.evaluate(() => ({
        length: window.history.length,
        state: window.history.state,
        url: location.href,
      }))
    ).toEqual(history);
    if (fullScreen) await chat.getByRole('button', { name: 'Exit full screen', exact: true }).click();
    await expect(page.getByLabel('Sprint', { exact: true })).toHaveValue('Sprint 2');
  });
}

test('a failed message can be retried after configuration and response feedback is collected', async ({
  page,
}) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  let requests = 0;
  const prompts: string[] = [];
  await page.route('**/agent/chat', async (route) => {
    requests++;
    prompts.push(route.request().postDataJSON().message);
    await route.fulfill(
      requests === 1
        ? { status: 502, json: { detail: 'Model quota reached. Update the connection.' } }
        : {
            json: {
              session_id: 'retry-feedback',
              run_id: 'feedback-run',
              content: 'The ticket describes refresh token rotation.',
              mode: 'ai',
              sources: [],
              tools: [],
            },
          }
    );
  });
  const feedback: any[] = [];
  await page.route('**/agent/runs/feedback-run/feedback', async (route) => {
    const value = route.request().postDataJSON();
    feedback.push(value);
    await route.fulfill({ json: { saved: true, feedback: value } });
  });
  await ask(page, 'Explain refresh token rotation');
  await expect(chat.getByRole('alert')).toContainText('Model quota reached');
  await chat.getByRole('button', { name: 'Configure agent', exact: true }).click();
  await chat.getByRole('button', { name: 'Close agent configuration' }).click();
  await chat.getByRole('button', { name: 'Retry last message' }).click();
  await expect(chat.locator('.agent-assistant')).toContainText(
    'The ticket describes refresh token rotation.'
  );
  expect(prompts).toEqual(['Explain refresh token rotation', 'Explain refresh token rotation']);
  const answer = chat.locator('.agent-assistant');
  await answer.getByRole('button', { name: 'Helpful response', exact: true }).click();
  await expect(answer.getByRole('button', { name: 'Helpful response', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true'
  );
  await answer.getByRole('button', { name: 'Respond', exact: true }).click();
  await answer.getByLabel('Response feedback note').fill('Useful answer, add acceptance criteria next time.');
  await answer.getByLabel('Response feedback note').press('Enter');
  await expect(answer.getByRole('status')).toContainText('Feedback saved');
  expect(feedback).toContainEqual({ vote: 1 });
  expect(feedback).toContainEqual({ note: 'Useful answer, add acceptance criteria next time.' });
});

test('a failed request survives refresh and retries without retyping', async ({ page }) => {
  await upload(page);
  await enter(page);
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  let attempts = 0;
  await page.route('**/agent/chat', async (route) => {
    attempts++;
    await route.fulfill(
      attempts === 1
        ? { status: 502, json: { detail: 'Model quota reached.' } }
        : {
            json: {
              session_id: 'refresh-retry',
              content: 'Recovered the original request.',
              mode: 'ai',
              sources: [],
              tools: [],
            },
          }
    );
  });
  await ask(page, 'Describe the authentication work');
  await expect(page.getByRole('alert')).toContainText('Model quota reached');
  await page.reload();
  await page.getByRole('button', { name: 'Open Sprint Agent', exact: true }).click();
  const chat = page.getByRole('region', { name: 'Sprint Agent chat' });
  await expect(chat.getByLabel('Pending messages')).toContainText('Describe the authentication work');
  await chat.getByRole('button', { name: 'Retry last message' }).click();
  await expect(chat.locator('.agent-assistant')).toContainText('Recovered the original request.');
  expect(attempts).toBe(2);
});
