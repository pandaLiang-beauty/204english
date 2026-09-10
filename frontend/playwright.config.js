import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  workers: 2,
  timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:5214', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'phone', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } }
  ],
  webServer: {
    command: 'npm run preview -- --outDir .e2e-dist --host 127.0.0.1 --port 5214 --strictPort',
    url: 'http://127.0.0.1:5214', reuseExistingServer: false,
    env: { STUDY_LOCAL_BACKEND: 'http://127.0.0.1:1' }
  }
})
