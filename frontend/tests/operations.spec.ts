import { test, expect } from '@playwright/test';

test('monitoring scopes all cards and charts to the selected conversation and opens a trace', async ({
  page,
}, info) => {
  const requests: string[] = [];
  await page.route('**/api/ops/**', async (route) => {
    const url = new URL(route.request().url());
    requests.push(url.pathname + url.search);
    let body: any = {};
    if (url.pathname.endsWith('/summary'))
      body = {
        metrics: {
          requests: url.searchParams.get('session_id') ? 1 : 2,
          input_tokens: 1000,
          output_tokens: 100,
          model_calls: 2,
          tool_calls: 1,
          avg_latency_ms: 2400,
          p95_latency_ms: 2400,
          p95_sample_size: 1,
          avg_first_token_ms: 1300,
          avg_output_tokens_per_second: 41.7,
          requests_per_minute: 0.2,
          chunks_returned: 3,
          avg_chunk_chars: 620,
          avg_prompt_chars: 2400,
          thumbs_up: 1,
          thumbs_down: 0,
          blocked_inputs: 0,
          unpriced_calls: 1,
        },
        models: [{ _id: 'demo-model', count: url.searchParams.get('session_id') ? 1 : 2 }],
        tools: [{ _id: 'query_metadata', count: 1 }],
        skills: [{ _id: 'sprint', count: 1 }],
        timeline: [{ _id: '2026-10-21T01', count: url.searchParams.get('session_id') ? 1 : 2 }],
        langfuse: { configured: false },
      };
    else if (url.pathname.endsWith('/conversations'))
      body = {
        sessions: [
          {
            session_id: 'conversation-one',
            title: 'Summarize Sprint 2',
            message_count: 2,
            filename: 'demo.csv',
          },
        ],
      };
    else if (url.pathname.endsWith('/runs'))
      body = {
        items: [
          {
            id: 'run-one',
            question: 'Summarize Sprint 2',
            status: 'success',
            model: 'demo-model',
            usage: { input_tokens: 1000, output_tokens: 100 },
            latency_ms: 2400,
          },
        ],
        total: 1,
      };
    else if (url.pathname.endsWith('/runs/run-one'))
      body = {
        id: 'run-one',
        question: 'Summarize Sprint 2',
        response: 'Two tickets need testing.',
        model: 'demo-model',
        status: 'success',
        context: { chunks_returned: 3, average_chunk_chars: 620 },
        usage: { input_tokens: 1000, output_tokens: 100 },
        model_calls: [
          {
            model: 'demo-model',
            usage: { source: 'provider' },
            input: 'Verified metadata packet',
            output: 'Two tickets need testing.',
          },
        ],
        tool_calls: [{ tool: 'query_metadata', arguments: { sprint: 'Sprint 2' }, result: 'Two tickets' }],
        events: [],
      };
    else if (url.pathname.endsWith('/pricing'))
      body = {
        checked_at: '2026-10-21',
        source: 'https://developers.openai.com/api/docs/pricing',
        models: {},
      };
    await route.fulfill({ json: body });
  });
  await page.goto('/monitoring');
  await expect(page.getByRole('heading', { name: 'The agent, in view.' })).toBeVisible();
  await page.getByRole('button', { name: 'Summarize Sprint 2 2 messages · demo.csv' }).click();
  await expect
    .poll(() => requests.some((r) => r.includes('/summary?') && r.includes('session_id=conversation-one')))
    .toBe(true);
  await expect
    .poll(() => requests.some((r) => r.includes('/runs?') && r.includes('session_id=conversation-one')))
    .toBe(true);
  await expect(
    page.locator('.ops-cards article').filter({ hasText: 'Recorded requests' }).locator('strong')
  ).toHaveText('1');
  await page.screenshot({ path: `test-results/monitoring-overview-${info.project.name}.png` });
  await page.getByRole('button', { name: 'Summarize Sprint 2', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Response trace' })).toBeVisible();
  await expect(page.getByText('Two tickets need testing.', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Context & retrieval', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/monitoring-${info.project.name}.png`, fullPage: false });
});

test('evaluation supports model comparison and human 1–5 scoring with feedback', async ({ page }, info) => {
  const reviews: any[] = [];
  await page.route('**/api/ops/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/datasets')) {
      await route.fulfill({ json: { datasets: [], exports: [], connections: [] } });
      return;
    }
    if (path.endsWith('/review')) {
      reviews.push(route.request().postDataJSON());
      await route.fulfill({ json: { saved: true } });
      return;
    }
    if (path.endsWith('/evaluation/runs')) {
      await route.fulfill({
        json: [
          { id: 'eval-one', model: 'demo-model', completed: 1, case_count: 1, started_at: '2026-10-21' },
          {
            id: 'eval-two',
            model: 'comparison-model',
            completed: 1,
            case_count: 1,
            started_at: '2026-10-21',
          },
        ],
      });
      return;
    }
    await route.fulfill({
      json: {
        id: path.endsWith('eval-two') ? 'eval-two' : 'eval-one',
        model: path.endsWith('eval-two') ? 'comparison-model' : 'demo-model',
        dataset_version: 'same-source',
        status: 'complete',
        completed: 1,
        failed: 0,
        case_count: 1,
        summary: { success_rate: 1, faithfulness: 0.9, context_precision: 0.8 },
        results: [
          {
            id: 'result-one',
            case_number: 1,
            question: 'Which tickets need testing?',
            response: 'APP-2 needs testing.',
            reference: 'APP-2 needs testing.',
            reference_status: 'needs_human_verification',
            model: 'demo-model',
            status: 'success',
            metrics: {},
            ragas: { metrics: { faithfulness: 0.9 } },
          },
        ],
      },
    });
  });
  await page.goto('/evaluation');
  await expect(page.getByRole('heading', { name: 'Better answers, with evidence.' })).toBeVisible();
  await page.getByRole('button', { name: 'Performance history', exact: true }).click();
  await page.getByLabel('Compare evaluation').selectOption('eval-two');
  await expect(page.getByRole('heading', { name: 'Model comparison' })).toBeVisible();
  await page.screenshot({ path: `test-results/evaluation-overview-${info.project.name}.png` });
  await page.getByRole('button', { name: '1. Which tickets need testing?' }).click();
  await page.getByRole('radio', { name: '5', exact: true }).check();
  await page.getByLabel('Evaluation feedback').fill('Correct answer and relevant source.');
  await page.getByRole('button', { name: 'Save human review' }).click();
  await expect(page.getByRole('status')).toContainText('Human review saved');
  expect(reviews[0].score).toBe(5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/evaluation-${info.project.name}.png`, fullPage: false });
});

const demoCase = {
  id: 'case-one',
  conversation_id: 'first',
  question: 'Which cache ticket needs testing?',
  reference: 'APP-2 needs testing.',
  reference_status: 'needs_human_verification',
  reference_contexts: ['APP-2 | Status: Testing'],
  context_status: 'needs_human_verification',
  context_source: 'Imported candidate evidence',
  enabled: true,
  expected: { ticket_keys: ['APP-2'], clarification: false },
};
const ng = {
  bleu: { '2': 0.8, '3': 0.7, '4': 0.6, '5': 0.5 },
  rouge: Object.fromEntries([2, 3, 4, 5].map((n) => [n, { precision: 0.8, recall: 0.7, f1: 0.75 }])),
  rouge_l: { precision: 0.8, recall: 0.7, f1: 0.75 },
};
async function evaluationFixture(page: import('@playwright/test').Page) {
  let versions: any[] = [
    {
      id: 'v1',
      dataset_id: 'gold',
      number: 1,
      parent_id: null,
      name: 'My conversation',
      notes: 'Baseline',
      ticket_dataset_id: 'export-one',
      source_snapshot_sha256: 'same',
      cases: [{ ...demoCase }],
      case_count: 1,
      enabled_count: 1,
      created_at: '2026-10-21T00:00',
      change_note: 'Imported',
    },
  ];
  const launches: any[] = [];
  let promptVersions = [
    {
      id: 'prompt-v1',
      number: 1,
      sha256: 'prompt-one',
      briefs: [{ project: '', content: 'Ship reliable cache updates.' }],
      change_note: 'Initial guidance',
    },
  ];
  let activePrompt = 'prompt-v1';
  await page.route('**/api/ops/evaluation/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let body: any;
    if (path.endsWith('/prompts/export-one/activate')) {
      activePrompt = route.request().postDataJSON().version_id;
      body = promptVersions.find((v) => v.id === activePrompt);
    } else if (path.endsWith('/prompts/export-one') && method === 'POST') {
      const value = route.request().postDataJSON();
      const v = {
        ...value,
        id: 'prompt-v' + (promptVersions.length + 1),
        number: promptVersions.length + 1,
        sha256: 'prompt-new',
      };
      promptVersions = [v, ...promptVersions];
      body = v;
    } else if (path.endsWith('/prompts/export-one'))
      body = {
        head_version_id: promptVersions[0].id,
        active_version_id: activePrompt,
        versions: promptVersions,
        projects: ['APP'],
      };
    else if (path.endsWith('/datasets'))
      body = {
        datasets: [
          {
            id: 'gold',
            name: 'My conversation',
            head_version_id: versions[0].id,
            version_number: versions[0].number,
            case_count: 1,
            ticket_dataset_id: 'export-one',
          },
        ],
        exports: [{ id: 'export-one', filename: 'test.csv', sha256: 'same' }],
        connections: [
          { id: 'gemini', name: 'Gemini test model', provider: 'gemini' },
          { id: 'gpt', name: 'GPT test model', provider: 'openai' },
        ],
        active_export_id: 'export-one',
      };
    else if (path.endsWith('/performance')) body = [];
    else if (path.endsWith('/versions') && method === 'POST') {
      const value = route.request().postDataJSON();
      const version = {
        ...versions[0],
        ...value,
        id: `v${versions.length + 1}`,
        number: versions.length + 1,
        created_at: '2026-10-21T01:00',
      };
      versions = [version, ...versions];
      body = version;
    } else if (path.endsWith('/versions')) body = versions.map(({ cases, ...v }) => v);
    else if (path.includes('/versions/')) body = versions.find((v) => path.endsWith('/' + v.id));
    else if (path.endsWith('/jobs') && method === 'POST') {
      const value = route.request().postDataJSON();
      launches.push(value);
      body = {
        id: 'job',
        status: 'queued',
        ...value,
        version_number: versions[0].number,
        case_count: 1,
        run_ids: ['run-a', 'run-b'],
        completed_models: 0,
      };
    } else if (path.endsWith('/jobs/job'))
      body = {
        id: 'job',
        status: 'complete',
        connection_ids: launches.at(-1)?.connection_ids || ['gemini'],
        version_number: 2,
        case_count: 1,
        completed_models: 2,
        runs: [
          { id: 'run-a', model: 'Gemini', completed: 1, failed: 0, case_count: 1 },
          { id: 'run-b', model: 'GPT', completed: 1, failed: 0, case_count: 1 },
        ],
      };
    else if (path.endsWith('/runs'))
      body = [
        { id: 'run-a', model: 'Gemini', completed: 1, case_count: 1, started_at: '2026-10-21' },
        { id: 'run-b', model: 'GPT', completed: 1, case_count: 1, started_at: '2026-10-21' },
      ];
    else if (path.includes('/runs/')) {
      const b = path.endsWith('run-b');
      body = {
        id: b ? 'run-b' : 'run-a',
        model: b ? 'GPT' : 'Gemini',
        status: 'complete',
        dataset_version: 'same',
        golden_version_number: 2,
        prompt_version_id: launches.at(-1)?.prompt_version_id || 'prompt-v1',
        prompt_version_number:
          promptVersions.find((v) => v.id === launches.at(-1)?.prompt_version_id)?.number || 1,
        prompt_snapshot:
          promptVersions.find((v) => v.id === launches.at(-1)?.prompt_version_id) || promptVersions.at(-1),
        case_count: 1,
        completed: 1,
        failed: 0,
        summary: {
          success_rate: 1,
          faithfulness: 0.9,
          context_precision: 0.8,
          bleu: ng.bleu,
          rouge: { '2': 0.75, '3': 0.75, '4': 0.75, '5': 0.75 },
          rouge_l: 0.75,
        },
        results: [
          {
            id: b ? 'res-b' : 'res-a',
            case_id: 'case-one',
            case_number: 1,
            question: demoCase.question,
            reference: demoCase.reference,
            reference_contexts: demoCase.reference_contexts,
            context_status: 'needs_human_verification',
            retrieved_contexts: ['APP-2 | Testing'],
            reference_status: 'needs_human_verification',
            response: 'APP-2 needs testing.',
            status: 'success',
            generation_latency_ms: b ? 2300 : 1200,
            model_calls: b ? 4 : 2,
            tool_calls: b ? 3 : 1,
            metrics: { ngrams: ng },
            ragas: { metrics: { faithfulness: 0.9, context_precision: 0.8, context_recall: 0.7 } },
          },
        ],
      };
    } else body = {};
    await route.fulfill({ json: body });
  });
  return { launches };
}

test('golden set edits create a version, old revisions are read-only, and one or two models can run', async ({
  page,
}, info) => {
  const { launches } = await evaluationFixture(page);
  await page.goto('/evaluation');
  await expect(page.getByLabel('Golden evaluation dataset')).toHaveValue('gold');
  await page
    .getByRole('region', { name: 'Evaluation dataset workspace' })
    .getByText('1. Which cache ticket needs testing?', { exact: true })
    .click();
  await expect(page.getByLabel('Expected context 1')).toHaveValue('APP-2 | Status: Testing');
  await page.getByLabel('Expected answer 1').fill('APP-2 is in Testing and needs verification.');
  await page.getByLabel('Version change note').fill('Clarify the expected answer');
  await page.getByRole('button', { name: 'Save as new version', exact: true }).click();
  await expect(page.getByLabel('Dataset version')).toHaveValue('v2');
  await expect(page.getByRole('status')).toContainText('Version 2 saved');
  await page.getByLabel('Dataset version').selectOption('v1');
  await page
    .getByRole('region', { name: 'Evaluation dataset workspace' })
    .getByText('1. Which cache ticket needs testing?', { exact: true })
    .click();
  await expect(page.getByLabel('Expected answer 1')).toBeDisabled();
  await expect(page.getByLabel('Expected answer 1')).toHaveValue('APP-2 needs testing.');
  await expect(page.getByRole('button', { name: 'Restore as new version' })).toBeEnabled();
  await page.getByLabel('Dataset version').selectOption('v2');
  await page.getByRole('button', { name: 'Run tests', exact: true }).click();
  await expect(page.getByLabel('Evaluation mode', { exact: true })).toHaveValue('one');
  await expect(page.getByRole('button', { name: 'Start evaluation' })).toBeEnabled();
  await page.getByLabel('Evaluation mode', { exact: true }).selectOption('two');
  await page.getByLabel('Evaluation model 2').selectOption('gpt');
  await page.getByRole('button', { name: 'Start evaluation' }).click();
  await expect(page.getByRole('region', { name: 'Evaluation job progress' })).toContainText('complete');
  expect(launches[0]).toMatchObject({ version_id: 'v2', connection_ids: ['gemini', 'gpt'] });
  await page.getByRole('button', { name: 'View evaluation results' }).click();
  await expect(page.getByRole('heading', { name: 'Compare each question' })).toBeVisible();
  const comparison = page.getByRole('region', { name: 'Per-question model comparison' });
  await comparison.getByText('1. Which cache ticket needs testing?', { exact: true }).click();
  await expect(comparison).toContainText('1.20s');
  await expect(comparison).toContainText('2.30s');
  await expect(comparison.getByRole('columnheader', { name: 'Model calls', exact: true })).toBeVisible();
  await expect(comparison).toContainText('BLEU-4');
  await expect(comparison).toContainText('5-gram');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Switch to dark theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.screenshot({ path: `test-results/evaluation-question-comparison-${info.project.name}.png` });
});

test('CSV criteria are visible and both dashboards retain their dark theme', async ({ page }, info) => {
  await evaluationFixture(page);
  await page.goto('/evaluation');
  await expect(page.getByText('CSV acceptance criteria & template', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download evaluation CSV template' })).toBeVisible();
  await expect(page.getByLabel('Import evaluation conversation')).toHaveAttribute(
    'accept',
    '.docx,.json,.csv'
  );
  await page.getByRole('button', { name: 'Switch to dark theme' }).click();
  await expect(page.locator('.ops-card').first()).toHaveCSS('background-color', 'rgb(27, 42, 62)');
  await expect(page.getByLabel('Golden evaluation dataset', { exact: true })).toHaveCSS(
    'background-color',
    'rgb(27, 42, 62)'
  );
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('link', { name: 'Monitoring', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.getByRole('button', { name: 'Switch to light theme' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'All conversations', exact: true })).toHaveCSS(
    'color',
    'rgb(191, 218, 255)'
  );
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/monitoring-dark-${info.project.name}.png` });
  await page.getByRole('button', { name: 'Switch to light theme' }).click();
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});

test('project prompts can be versioned, pinned for evaluation, and activated separately', async ({
  page,
}, info) => {
  if (info.project.name === 'desktop') await page.setViewportSize({ width: 1440, height: 1040 });
  const { launches } = await evaluationFixture(page);
  await page.goto('/evaluation');
  await page.getByRole('button', { name: 'Project prompts', exact: true }).click();
  await expect(page.getByLabel('Project prompt revision')).toHaveValue('prompt-v1');
  await expect(page.getByLabel('Versioned project prompt')).toHaveValue('Ship reliable cache updates.');
  await page
    .getByLabel('Versioned project prompt')
    .fill('Prioritize cache reliability. Explain uncertainty and ask about missing estimates.');
  await page.getByLabel('Prompt change note').fill('Clarify reliability goals');
  await page.getByRole('button', { name: 'Save new prompt version' }).click();
  await expect(page.getByLabel('Project prompt revision')).toHaveValue('prompt-v2');
  await expect(page.getByRole('status')).toContainText('Chat stays on its active revision');
  await expect(page.getByRole('button', { name: 'Use for chat' })).toBeEnabled();
  await page.screenshot({ path: `test-results/project-prompts-${info.project.name}.png` });
  await page.getByRole('button', { name: 'Run tests', exact: true }).click();
  await expect(page.getByLabel('Project prompt revision')).toHaveValue('prompt-v2');
  await page.getByRole('button', { name: 'Start evaluation' }).click();
  expect(launches.at(-1)).toMatchObject({ prompt_version_id: 'prompt-v2', connection_ids: ['gemini'] });
  await page.getByRole('button', { name: 'Project prompts', exact: true }).click();
  await page.getByRole('button', { name: 'Use for chat' }).click();
  await expect(page.getByRole('status')).toContainText('now active');
  await page.getByLabel('Project prompt revision').selectOption('prompt-v1');
  await expect(page.getByLabel('Versioned project prompt')).toHaveValue('Ship reliable cache updates.');
  await page
    .getByLabel('Versioned project prompt')
    .fill('Restored reliability guidance with a smaller scope.');
  await page.getByRole('button', { name: 'Save new prompt version' }).click();
  await expect(page.getByLabel('Project prompt revision')).toHaveValue('prompt-v3');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
