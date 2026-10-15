/**
 * Browser tests of the contributor flow against the real API (docs/TESTING_STRATEGY.md).
 * They need PostgreSQL running; see README.md (Browser tests).
 */
import { defineConfig, devices } from '@playwright/test'

const CI = !!process.env.CI

export default defineConfig({
  testDir: 'e2e',
  testMatch: '*.e2e.ts',
  fullyParallel: false,
  // One at a time: each test migrates and seeds the same development database first.
  workers: 1,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  reporter: CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      // A phone-sized screen: the flow is built for 360 px wide phones.
      name: 'phone',
      use: {
        ...devices['Pixel 7'],
        launchOptions: {
          // A fake microphone that plays a tone, and no permission prompt.
          args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
          // Set when the installed browser differs from the one this Playwright expects.
          executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined,
        },
      },
    },
  ],
  webServer: [
    {
      command: 'uv run uvicorn app.main:app --port 8000',
      cwd: '../backend',
      url: 'http://localhost:8000/healthz',
      reuseExistingServer: !CI,
    },
    {
      command: 'npm run dev -- --port 5173 --strictPort',
      url: 'http://localhost:5173',
      reuseExistingServer: !CI,
    },
  ],
})
