import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const MUTATION_AUTH_ROUTES = [
  "src/app/api/auth/login/route.ts",
  "src/app/api/auth/logout/route.ts",
  "src/app/api/auth/2fa/verify/route.ts",
  "src/app/api/auth/2fa/setup-required/start/route.ts",
  "src/app/api/auth/2fa/setup-required/confirm/route.ts",
];

test("every auth mutation BFF route validates the request Origin", async () => {
  for (const path of MUTATION_AUTH_ROUTES) {
    const content = await source(path);
    assert.match(
      content,
      /origin\s*&&\s*origin\s*!==\s*request\.nextUrl\.origin/,
      `${path} is missing Origin validation`,
    );
    assert.match(content, /status:\s*403/, `${path} should reject a mismatched Origin with 403`);
  }
});

test("session cookies stay HttpOnly/Secure-in-production/SameSite=Lax", async () => {
  const backend = await source("src/lib/server/backend.ts");
  assert.match(backend, /httpOnly:\s*true/);
  assert.match(backend, /secure:\s*process\.env\.NODE_ENV\s*===\s*"production"/);
  assert.match(backend, /sameSite:\s*"lax"/);
});

test("2FA challenge and forced-setup tokens are never persisted as cookies themselves", async () => {
  // challenge_token / setup_token are short-lived, purpose-specific bearer
  // credentials carried in page/component state and request bodies only
  // (see SECURITY.md) - only the *resulting* session (ACCESS_COOKIE /
  // REFRESH_COOKIE) is ever written to a cookie, never the token that
  // authorized minting it.
  const setupStartRoute = await source("src/app/api/auth/2fa/setup-required/start/route.ts");
  const setupConfirmRoute = await source("src/app/api/auth/2fa/setup-required/confirm/route.ts");
  assert.doesNotMatch(setupStartRoute, /cookies\.set/);
  assert.match(setupConfirmRoute, /cookies\.set\(ACCESS_COOKIE/);
  assert.doesNotMatch(setupConfirmRoute, /cookies\.set\([^)]*setup_token/i);
  assert.doesNotMatch(setupConfirmRoute, /cookies\.set\([^)]*"setup/i);

  const provider = await source("src/features/auth/auth-provider.tsx");
  assert.doesNotMatch(provider, /localStorage/);
  assert.doesNotMatch(provider, /sessionStorage/);
});

test("recovery codes and TOTP secrets never touch localStorage/sessionStorage", async () => {
  const loginPage = await source("src/app/login/page.tsx");
  const settingsPage = await source("src/app/owner/settings/page.tsx");
  for (const content of [loginPage, settingsPage]) {
    assert.doesNotMatch(content, /localStorage/);
    assert.doesNotMatch(content, /sessionStorage/);
  }
});

test("forced 2FA onboarding and session-management flows exist in RU/TG/EN", async () => {
  const catalogs = await Promise.all(
    ["ru", "tg", "en"].map(async (locale) =>
      JSON.parse(await source(`src/i18n/messages/${locale}.json`)),
    ),
  );
  for (const catalog of catalogs) {
    assert.ok(catalog.auth.twoFactorSetupRequiredTitle);
    assert.ok(catalog.auth.twoFactorSetupRequiredSubtitle);
    assert.ok(catalog.security.sessionsTitle);
    assert.ok(catalog.security.revokeSession);
    assert.ok(catalog.security.logoutAllDevices);
    assert.ok(catalog.security.currentDevice);
    assert.ok(catalog.enums.notification.SECURITY_EVENT);
  }
});

test("revoking the current session logs the browser out instead of leaving a stale authenticated UI", async () => {
  const settingsPage = await source("src/app/owner/settings/page.tsx");
  assert.match(settingsPage, /isCurrent\)\s*\{[\s\S]*?await logout\(\)/);
  assert.match(settingsPage, /router\.replace\("\/login"\)/);
});
