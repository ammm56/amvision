import { defineConfig, devices } from 'playwright/test'

const runningInCi = Boolean(process.env.CI)
const browserChannel = process.env.PLAYWRIGHT_BROWSER_CHANNEL?.trim()
  || (runningInCi ? undefined : 'chrome')

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  fullyParallel: false,
  forbidOnly: runningInCi,
  retries: runningInCi ? 2 : 0,
  workers: 1,
  reporter: runningInCi ? [['line'], ['html', { open: 'never' }]] : 'line',
  use: {
    baseURL: 'http://127.0.0.1:5601',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        channel: browserChannel,
      },
    },
  ],
  webServer: {
    command: 'npm run dev -- --strictPort',
    url: 'http://127.0.0.1:5601',
    reuseExistingServer: !runningInCi,
    timeout: 120_000,
  },
})
