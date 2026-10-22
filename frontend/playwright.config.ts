import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

export default defineConfig({
  testDir: './tests',
  testIgnore: 'operations.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:8011', trace: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH } : {},
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } },
  ],
  webServer: {
    command: '../.venv/bin/python -m uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 8011',
    url: 'http://127.0.0.1:8011/api/health',
    reuseExistingServer: false,
    env: { JIRA_WORKSPACE_RESTORE: 'false', JIRA_MONGO_DATABASE: 'sprintlens_e2e', JIRA_MONGO_URI: process.env.JIRA_MONGO_URI || 'mongodb://127.0.0.1:27018', JIRA_DATA_DIR: resolve('../resources/tests/e2e'), JIRA_STATIC_DIR: resolve('dist') },
  },
});
