import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("USER and MERCHANT expose role-gated security settings routes", async () => {
  const shell = await source("src/components/layout/dashboard-shell.tsx");
  const userPage = await source("src/app/user/settings/page.tsx");
  const merchantPage = await source("src/app/merchant/settings/page.tsx");
  const userLayout = await source("src/app/user/layout.tsx");
  const merchantLayout = await source("src/app/merchant/layout.tsx");

  assert.match(shell, /href: "\/user\/settings"/);
  assert.match(shell, /href: "\/merchant\/settings"/);
  assert.match(userPage, /<SecuritySettingsPage/);
  assert.match(merchantPage, /<SecuritySettingsPage/);
  assert.match(userLayout, /<RoleGate role="user">/);
  assert.match(merchantLayout, /<RoleGate role="merchant">/);
});

test("shared settings UI covers complete self-service lifecycle", async () => {
  const page = await source("src/components/security/security-settings-page.tsx");
  const api = await source("src/lib/api/security.ts");

  for (const contract of [
    "/auth/2fa/status",
    "/auth/2fa/setup/start",
    "/auth/2fa/setup/confirm",
    "/auth/2fa/disable",
    "/auth/2fa/recovery/regenerate",
    "/auth/sessions",
    "/auth/logout-all",
    "/auth/password/change",
  ]) {
    assert.match(api, new RegExp(contract.replaceAll("/", "\\/")));
  }
  assert.match(page, /status\?\.required/);
  assert.match(page, /securityApi\.changePassword/);
  assert.match(page, /securityApi\.regenerateRecoveryCodes/);
  assert.match(page, /securityApi\.revokeSession/);
  assert.match(page, /securityApi\.logoutAll/);
  assert.match(page, /localizeError\(reason\)/);
  assert.match(page, /recoveryCodes\.map/);
  assert.match(page, /setRecoveryCodes\(\[\]\)/);
});

test("security mutations stay behind same-origin cookie BFF without JS token persistence", async () => {
  const api = await source("src/lib/api/security.ts");
  const client = await source("src/lib/api/client.ts");
  const proxy = await source("src/app/api/backend/[...path]/route.ts");

  assert.match(client, /fetch\(`\/api\/backend/);
  assert.match(client, /credentials: "same-origin"/);
  assert.match(proxy, /origin !== request\.nextUrl\.origin/);
  assert.match(proxy, /request\.cookies\.get\(ACCESS_COOKIE\)/);
  assert.doesNotMatch(api + client, /localStorage|sessionStorage|refresh_token|access_token/);
});

test("security settings translations are complete for RU EN and TG", async () => {
  const requiredKeys = [
    "accountTitle",
    "passwordTitle",
    "changePassword",
    "passwordChangeSuccess",
    "twoFactorTitle",
    "ownerRequiredPolicy",
    "regenerateCodes",
    "sessionsTitle",
    "telegramTitle",
  ];
  for (const locale of ["ru", "en", "tg"]) {
    const messages = JSON.parse(await source(`src/i18n/messages/${locale}.json`));
    for (const key of requiredKeys) assert.equal(typeof messages.security[key], "string");
  }
});
