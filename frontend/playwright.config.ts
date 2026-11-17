import { defineConfig } from '@playwright/test'
export default defineConfig({ testDir: './e2e', workers: 1, timeout: 90000, use: { baseURL: 'http://127.0.0.1:5174', screenshot: 'only-on-failure', trace: 'retain-on-failure' }, reporter: [['list'], ['json', { outputFile: '../artifacts/browser-results.json' }]] })
