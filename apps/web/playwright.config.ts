import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests: the real API in offline mode over SYNTHETIC price files, and the
 * production build of the web app. Locally, servers already running on these ports are
 * reused (then the data is whatever they serve: the tests never depend on values).
 */
const CI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 30_000 },
  retries: CI ? 1 : 0,
  reporter: CI ? [["github"], ["list"]] : "list",
  use: { baseURL: "http://127.0.0.1:3000", trace: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } }],
  webServer: [
    {
      command: "uv run python e2e/synthetic_data.py .e2e/data && uv run investinglab-api",
      url: "http://127.0.0.1:8000/health/live",
      env: {
        INVESTINGLAB_OFFLINE: "true",
        INVESTINGLAB_LOCAL_DATA_DIR: ".e2e/data",
        INVESTINGLAB_DATA_DIR: ".e2e/cache",
        INVESTINGLAB_LOG_LEVEL: "WARNING",
      },
      reuseExistingServer: !CI,
      timeout: 120_000,
    },
    {
      command: "pnpm exec next start --port 3000",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: !CI,
      timeout: 120_000,
    },
  ],
});
