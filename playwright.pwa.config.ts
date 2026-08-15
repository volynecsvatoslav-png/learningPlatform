import { defineConfig, devices } from '@playwright/test'
import { readFileSync } from 'node:fs'

const offlineFixture = JSON.parse(readFileSync('apps/api/learner/tests/fixtures/offline_license.json', 'utf8')) as { publicJwk: JsonWebKey }

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
    env: { VITE_OFFLINE_LICENSE_PUBLIC_JWK: JSON.stringify(offlineFixture.publicJwk) },
    url: 'http://127.0.0.1:4173/app/',
    reuseExistingServer: true,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium-pwa', use: { ...devices['Desktop Chrome'] } }],
})
