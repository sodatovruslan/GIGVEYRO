import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createTranslator } from "next-intl";
import { test } from "vitest";

import { AuthOperationGate } from "../src/features/auth/auth-operation-gate.ts";
import { loginErrorKey } from "../src/features/auth/login-error.ts";
import { auditMessagePath } from "../src/features/audit/i18n.ts";
import { mapWithdrawalFieldErrors } from "../src/features/withdrawals/validation.ts";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("OWNER -> MERCHANT -> USER logins supersede every previous operation", () => {
  const gate = new AuthOperationGate();
  const owner = gate.startExclusive();
  gate.startExclusive(); // logout
  const merchant = gate.startExclusive();
  gate.startExclusive(); // logout
  const user = gate.startExclusive();
  assert.equal(gate.isCurrent(owner), false);
  assert.equal(gate.isCurrent(merchant), false);
  assert.equal(gate.isCurrent(user), true);
});

test("expired restore cannot overwrite a successful fresh login", () => {
  const gate = new AuthOperationGate();
  const stale = gate.startSession();
  const login = gate.startExclusive();
  assert.equal(stale.controller.signal.aborted, true);
  assert.equal(gate.isCurrent(stale.id), false);
  assert.equal(gate.isCurrent(login), true);
});

test("login 401 is presented as invalid credentials, not an expired session", async () => {
  assert.equal(loginErrorKey({ status: 401 }), "invalidCredentials");
  assert.equal(loginErrorKey({ status: 500 }), null);
  const catalogs = await Promise.all(["ru", "tg", "en"].map(async (locale) => JSON.parse(await source(`src/i18n/messages/${locale}.json`))));
  for (const catalog of catalogs) {
    assert.ok(catalog.auth.invalidCredentials);
    assert.notEqual(catalog.auth.invalidCredentials, catalog.errors["401"]);
  }
});

test("stale 401 responses cannot clear refreshed cookies", async () => {
  const sessionRoute = await source("src/app/api/auth/session/route.ts");
  const backendRoute = await source("src/app/api/backend/[...path]/route.ts");
  assert.doesNotMatch(sessionRoute, /cookies\.set\([^,]+,\s*""/);
  assert.doesNotMatch(sessionRoute, /maxAge:\s*0/);
  assert.doesNotMatch(backendRoute, /backendResponse\.status === 401[\s\S]*maxAge:\s*0/);
  const provider = await source("src/features/auth/auth-provider.tsx");
  assert.equal((provider.match(/abortApiGeneration\(\)/g) || []).length, 2);
});

test("long Telegram codes use visible wrapping and remain selectable", async () => {
  const component = await source("src/components/notifications/notifications-page.tsx");
  assert.match(component, /overflowWrap: "anywhere"/);
  assert.match(component, /wordBreak: "break-word"/);
  assert.match(component, /userSelect: "all"/);
});

test("merchant withdrawal maps structured and backend TRC20 validation to destination", () => {
  const messages = { invalidAmount: "amount", invalidDestination: "destination", invalidTrc20: "trc20", invalidComment: "comment" };
  assert.deepEqual(mapWithdrawalFieldErrors({ message: "validation", issues: [{ loc: ["body", "amount"] }] }, messages), { amount: "amount" });
  assert.deepEqual(mapWithdrawalFieldErrors({ message: "invalid TRC20 address length", issues: [] }, messages), { destination: "trc20" });
});

test("analytics renders only the real backend deal timeseries", async () => {
  const api = await source("src/lib/api/analytics.ts");
  const page = await source("src/app/owner/analytics/page.tsx");
  assert.match(api, /analytics\/deals\/timeseries/);
  assert.match(page, /data\.timeseries/);
  assert.doesNotMatch(page, /mock|fake/i);
});

test("audit filters use the canonical server-side actions and entity types", async () => {
  const api = await source("src/lib/api/owner-operations.ts");
  const page = await source("src/app/owner/audit/page.tsx");
  assert.match(api, /account\.reset_password/);
  assert.match(api, /wallet\.allocate/);
  assert.match(page, /auditActions\.map/);
  assert.match(page, /auditEntityTypes\.map/);
  assert.equal(auditMessagePath("actions", "account.create"), "actions.account.create");
  assert.equal(auditMessagePath("entities", "account"), "entities.account");
  assert.equal(auditMessagePath("actions", "unsafe.key.extra"), null);
});

test("changed analytics, integrations, audit and withdrawal keys exist in RU/TG/EN", async () => {
  const catalogs = await Promise.all(["ru", "tg", "en"].map(async (locale) => JSON.parse(await source(`src/i18n/messages/${locale}.json`))));
  for (const catalog of catalogs) {
    assert.ok(catalog.analytics.dealsTrend);
    assert.ok(catalog.analytics.integrityStatus.ok);
    assert.ok(catalog.integrations.values.mock);
    assert.ok(catalog.integrations.values.fallback);
    assert.ok(catalog.audit.actions.account.reset_password);
    assert.ok(catalog.withdrawals.validation.trc20);
  }
});

test("locale catalogs contain no literal message keys with dots", async () => {
  const catalogs = await Promise.all(["ru", "tg", "en"].map(async (locale) => JSON.parse(await source(`src/i18n/messages/${locale}.json`))));
  const dotted = [];
  const visit = (value, path = []) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return;
    for (const [key, child] of Object.entries(value)) {
      if (key.includes(".")) dotted.push([...path, key].join("."));
      visit(child, [...path, key]);
    }
  };
  catalogs.forEach((catalog) => visit(catalog));
  assert.deepEqual(dotted, []);
});

test("next-intl resolves every canonical backend audit action in RU/TG/EN", async () => {
  const locales = ["ru", "tg", "en"];
  for (const locale of locales) {
    const messages = JSON.parse(await source(`src/i18n/messages/${locale}.json`));
    const translate = createTranslator({ locale, messages, namespace: "audit" });
    for (const backendAction of ["account.create", "account.reset_password", "wallet.allocate", "wallet.adjust_insurance", "wallet.manual_adjust", "deal.complete", "deal.release", "appeal.review", "appeal.resolve", "withdrawal.approve", "withdrawal.reject", "withdrawal.mark_paid"]) {
      const path = auditMessagePath("actions", backendAction);
      assert.ok(path);
      assert.notEqual(translate(path), backendAction);
    }
  }
});
