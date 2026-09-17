import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("owner account detail page fetches and renders the per-user insurance target view", async () => {
  const page = await source("src/app/owner/accounts/[accountId]/page.tsx");
  assert.match(page, /ownerAccountsApi\.insuranceTarget\(accountId\)/);
  assert.match(page, /targetQuery\.data\.insurance_balance/);
  assert.match(page, /targetQuery\.data\.insurance_target/);
  assert.match(page, /targetQuery\.data\.remaining_to_target/);
});

test("owner account detail page lets Owner change the target via a direct PATCH, never a versioned policy", async () => {
  const page = await source("src/app/owner/accounts/[accountId]/page.tsx");
  assert.match(page, /updateInsuranceTarget/);
  assert.doesNotMatch(page, /createInsuranceReservePolicy|activateInsuranceReservePolicy/);
});

test("insurance target API client scopes per-user calls under /owner/accounts/{id}, never fabricates a value", async () => {
  const accountsClient = await source("src/lib/api/owner-accounts.ts");
  assert.match(accountsClient, /insuranceTarget: \(id: string\) => apiFetch<InsuranceTargetView>\(`\/owner\/accounts\/\$\{id\}\/wallet\/insurance-target`\)/);
  assert.match(accountsClient, /updateInsuranceTarget: \(id: string, insurance_target: string\) =>/);
  const operationsClient = await source("src/lib/api/owner-operations.ts");
  assert.doesNotMatch(operationsClient, /insuranceReservePolicy|createInsuranceReservePolicy|activateInsuranceReservePolicy/);
});

test("insurance target translation keys exist in RU/EN/TG", async () => {
  const catalogs = await Promise.all(
    ["ru", "en", "tg"].map(async (locale) => JSON.parse(await source(`src/i18n/messages/${locale}.json`)))
  );
  for (const catalog of catalogs) {
    assert.ok(catalog.accounts.insuranceTargetTitle);
    assert.ok(catalog.accounts.insuranceTargetLabel);
    assert.ok(catalog.accounts.remainingToTargetLabel);
    assert.ok(catalog.accounts.insuranceTargetHint);
  }
});
