import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

const frontend = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const repository = (path) => readFile(new URL(`../../${path}`, import.meta.url), "utf8");

test("Playwright commands stay separate from the unit test command", async () => {
  const pkg = JSON.parse(await frontend("package.json"));
  assert.equal(pkg.scripts.test, "vitest run");
  assert.equal(pkg.scripts["test:e2e"], "node scripts/run-e2e.mjs");
  assert.match(pkg.devDependencies["@playwright/test"], /^\^1\./);

  const config = await frontend("playwright.config.ts");
  assert.match(config, /name: "chromium"/);
  assert.match(config, /trace: "on-first-retry"/);
  assert.match(config, /screenshot: "only-on-failure"/);
  assert.match(config, /video: "retain-on-failure"/);
  assert.match(config, /workers: 1/);
});

test("E2E harness always derives and cleans a disposable database and Redis namespace", async () => {
  const runner = await repository("GIGVEYRO_Backend/scripts/run_playwright_e2e.py");
  assert.match(runner, /_e2e_\{os\.getpid\(\)\}_\{uuid\.uuid4\(\)\.hex\[:6\]\}/);
  assert.match(runner, /database\("create"/);
  assert.match(runner, /database\("drop"/);
  assert.match(runner, /redis_prefix = f"gigapay:e2e:/);
  assert.match(runner, /cleanup_redis\(str\(redis_url\), redis_prefix\)/);
  assert.match(runner, /"PAYOUT_ENABLED": "false"/);
  assert.match(runner, /"BYBIT_WRITE_ENABLED": "false"/);
  assert.match(runner, /"--webpack"/);
});

test("E2E personas and synthetic finance fixtures are explicitly test-only", async () => {
  const seed = await repository("GIGVEYRO_Backend/scripts/e2e_seed.py");
  for (const persona of ["e2e_owner", "e2e_user_a", "e2e_user_b", "e2e_merchant_a", "e2e_merchant_b", "e2e_blocked"]) {
    assert.match(seed, new RegExp(persona));
  }
  assert.match(seed, /TMOCK_GIGVEYRO_DEPOSIT_ADDRESS/);
  assert.match(seed, /tx-e2e-link/);
  assert.doesNotMatch(seed, /BYBIT_API_KEY|BYBIT_API_SECRET|TELEGRAM_BOT_TOKEN/);
});

test("development CSP enables local tooling without relaxing production WebSockets", async () => {
  const config = await frontend("next.config.ts");
  assert.match(config, /process\.env\.NODE_ENV === "development"/);
  assert.match(config, /connect-src 'self' https: wss: ws:/);
  assert.match(config, /: "connect-src 'self' https: wss:"/);
  assert.match(config, /script-src 'self' 'unsafe-inline' 'unsafe-eval'/);
  assert.match(config, /: "script-src 'self' 'unsafe-inline'"/);
});

test("CI installs Chromium and preserves failure artifacts", async () => {
  const ci = await repository(".github/workflows/ci.yml");
  assert.match(ci, /name: Browser E2E \(Chromium\)/);
  assert.match(ci, /playwright install --with-deps chromium/);
  assert.match(ci, /run: npm run test:e2e/);
  assert.match(ci, /if: failure\(\)/);
  assert.match(ci, /path: gigveyro-frontend\/test-results/);
});
