import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'offline-pwa.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm --prefix apps/web run build && npm --prefix apps/web run preview',
    url: 'http://127.0.0.1:4173/app/',
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium-pwa', use: { ...devices['Desktop Chrome'] } }],
})
