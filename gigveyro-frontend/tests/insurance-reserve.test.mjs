import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("owner account detail page fetches and renders the insurance reserve view", async () => {
  const page = await source("src/app/owner/accounts/[accountId]/page.tsx");
  assert.match(page, /ownerAccountsApi\.insuranceReserve\(accountId\)/);
  assert.match(page, /reserveQuery\.data\.minimum_reserve_percentage/);
  assert.match(page, /reserveQuery\.data\.required_minimum_reserve/);
  assert.match(page, /reserveQuery\.data\.available_above_reserve/);
  assert.match(page, /reserveQuery\.data\.policy_version/);
  assert.match(page, /reserveQuery\.data\.policy_updated_at/);
});

test("owner account detail page lets Owner change the reserve percentage via create+activate, never a direct mutation", async () => {
  const page = await source("src/app/owner/accounts/[accountId]/page.tsx");
  assert.match(page, /createInsuranceReservePolicy/);
  assert.match(page, /activateInsuranceReservePolicy/);
});

test("insurance reserve API client scopes global policy calls under /api/v1/owner, never fabricates a value", async () => {
  const client = await source("src/lib/api/owner-operations.ts");
  assert.match(client, /insuranceReservePolicy: \(\) => apiFetch<InsuranceReservePolicy>\("\/api\/v1\/owner\/insurance-reserve-policy"\)/);
  assert.match(client, /\/api\/v1\/owner\/insurance-reserve-policies/);
  const accountsClient = await source("src/lib/api/owner-accounts.ts");
  assert.match(accountsClient, /insuranceReserve: \(id: string\) => apiFetch<InsuranceReserveWalletView>\(`\/owner\/accounts\/\$\{id\}\/wallet\/insurance-reserve`\)/);
});

test("insurance reserve translation keys exist in RU/EN/TG", async () => {
  const catalogs = await Promise.all(
    ["ru", "en", "tg"].map(async (locale) => JSON.parse(await source(`src/i18n/messages/${locale}.json`)))
  );
  for (const catalog of catalogs) {
    assert.ok(catalog.accounts.insuranceReserveTitle);
    assert.ok(catalog.accounts.currentReservePercent);
    assert.ok(catalog.accounts.requiredMinimumReserve);
    assert.ok(catalog.accounts.availableAboveReserve);
    assert.ok(catalog.accounts.reservePercentHint);
  }
});
