import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("login exposes managed onboarding without a public signup CTA", async () => {
  const login = await source("src/app/login/page.tsx");
  const auth = await source("src/features/auth/auth-provider.tsx");

  assert.match(login, /t\("managedOnboarding"\)/);
  assert.match(login, /dashboardPath\(result\.account\.role\)/);
  assert.match(auth, /fetch\("\/api\/auth\/login"/);
  assert.doesNotMatch(login, /href=[{]?['"]\/register|href=[{]?['"]\/signup/);
  assert.doesNotMatch(login, /registerApi|signupApi|registerAccount|signupAccount/);
});

test("OWNER provisioning flow remains role-limited and clears the initial password", async () => {
  const page = await source("src/app/owner/accounts/page.tsx");
  const api = await source("src/lib/api/owner-accounts.ts");

  assert.match(api, /create:.*\/owner\/accounts/);
  assert.match(page, /<option value="user">/);
  assert.match(page, /<option value="merchant">/);
  assert.doesNotMatch(page, /<option value="owner">/);
  assert.match(page, /const account = await ownerAccountsApi\.create/);
  assert.match(page, /setForm\(emptyForm\);\s*setCreatedAccount\(account\)/);
  assert.match(page, /passwordNotShownAgain/);
  assert.doesNotMatch(page, /createdAccount\.password/);
});

test("managed onboarding guidance is complete in RU EN and TG", async () => {
  const accountKeys = [
    "managedPolicy",
    "initialPasswordHint",
    "accountReady",
    "accountReference",
    "onboardingNext",
    "userOnboarding",
    "merchantOnboarding",
    "passwordNotShownAgain",
    "securitySetupInstruction",
    "done",
  ];

  for (const locale of ["ru", "en", "tg"]) {
    const messages = JSON.parse(await source(`src/i18n/messages/${locale}.json`));
    assert.equal(typeof messages.auth.managedOnboarding, "string");
    assert.ok(messages.auth.managedOnboarding.length > 10);
    for (const key of accountKeys) assert.equal(typeof messages.accounts[key], "string");
  }
});
