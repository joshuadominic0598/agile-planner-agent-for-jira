import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';
export default defineConfig({
  testDir: './tests',
  testMatch: 'operations.spec.ts',
  workers: 1,
  timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:8014', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } },
  ],
  webServer: {
    command:
      '../.venv/bin/python -m uvicorn app.observability.dashboard:app --app-dir ../backend --host 127.0.0.1 --port 8014',
    url: 'http://127.0.0.1:8014/api/health',
    env: {
      JIRA_MONGO_URI: 'mongodb://127.0.0.1:27018',
      JIRA_MONGO_DATABASE: 'sprintlens_e2e',
      JIRA_DATA_DIR: resolve('../resources/tests/operations'),
      JIRA_EVAL_APP_BASE_URL: 'http://127.0.0.1:8011',
      JIRA_STATIC_DIR: resolve('dist'),
    },
  },
});
