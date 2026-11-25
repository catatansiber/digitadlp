import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  workers: 1,
  outputDir: "test-results/playwright",
  use: {
    baseURL: "http://127.0.0.1:8765",
    trace: "off",
    acceptDownloads: true,
    deviceScaleFactor: 1,
    viewport: { width: 1280, height: 800 },
  },
  webServer: {
    command: "bash e2e/start-backend.sh",
    url: "http://127.0.0.1:8765/",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
