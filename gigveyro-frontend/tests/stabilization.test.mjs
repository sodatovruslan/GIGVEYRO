import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createTranslator } from "next-intl";
import { test } from "vitest";

import { mapAppealFieldErrors } from "../src/features/appeals/validation.ts";
import { AuthOperationGate } from "../src/features/auth/auth-operation-gate.ts";
import { loginErrorKey } from "../src/features/auth/login-error.ts";
import { auditMessagePath } from "../src/features/audit/i18n.ts";
import { notificationLink } from "../src/features/notifications/links.ts";
import { isWithdrawalStateConflict, mapWithdrawalFieldErrors } from "../src/features/withdrawals/validation.ts";

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
  // login, verifyTwoFactor, confirmForcedTwoFactorSetup, and logout each
  // start an exclusive operation and must abort any in-flight request
  // generation before mutating state.
  assert.equal((provider.match(/abortApiGeneration\(\)/g) || []).length, 4);
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

test("appeal open/resolve maps backend business-rule errors to the deal/message fields", () => {
  const messages = { dealNotEligible: "not-eligible", activeAppealExists: "already-open", dealNotFound: "not-found", invalidMessage: "bad-message", invalidOwnerNote: "bad-note" };
  assert.deepEqual(mapAppealFieldErrors({ message: "cannot open appeal for deal in status completed", issues: [] }, messages), { deal_id: "not-eligible" });
  assert.deepEqual(mapAppealFieldErrors({ message: "an active appeal already exists for this deal", issues: [] }, messages), { deal_id: "already-open" });
  assert.deepEqual(mapAppealFieldErrors({ message: "deal not found", issues: [] }, messages), { deal_id: "not-found" });
  assert.deepEqual(mapAppealFieldErrors({ message: "validation", issues: [{ loc: ["body", "owner_note"] }] }, messages), { owner_note: "bad-note" });
});

test("owner deposits list wires search/tx-hash/date filters and a detail lookup through the real backend routes", async () => {
  const api = await source("src/lib/api/deposits.ts");
  const page = await source("src/components/deposits/deposits-page.tsx");
  assert.match(api, /tx_hash: filters\.txHash/);
  assert.match(api, /date_from: filters\.dateFrom/);
  assert.match(api, /date_to: filters\.dateTo/);
  assert.match(api, /get: \(owner: boolean, id: string\)/);
  assert.match(page, /openDetail/);
  assert.doesNotMatch(page, /mock|fake/i);
});

test("sidebar notifications badge reflects the real unread-count endpoint and updates after mark-read", async () => {
  const shell = await source("src/components/layout/dashboard-shell.tsx");
  const notificationsPage = await source("src/components/notifications/notifications-page.tsx");
  assert.match(shell, /notificationsApi\.unreadCount\(\)/);
  assert.match(shell, /gigveyro:notifications-updated/);
  assert.match(notificationsPage, /gigveyro:notifications-updated/);
});

test("changed appeals and deposits keys exist in RU/TG/EN", async () => {
  const catalogs = await Promise.all(["ru", "tg", "en"].map(async (locale) => JSON.parse(await source(`src/i18n/messages/${locale}.json`))));
  for (const catalog of catalogs) {
    assert.ok(catalog.appeals.validation.activeAppealExists);
    assert.ok(catalog.appeals.validation.dealNotEligible);
    assert.ok(catalog.deposits.detailTitle);
    assert.ok(catalog.deposits.dateFrom);
    assert.ok(catalog.deposits.dateTo);
  }
});

test("owner withdrawal actions detect a stale-state conflict and refetch instead of retrying blindly", () => {
  assert.equal(isWithdrawalStateConflict({ message: "cannot approve withdrawal in status approved" }), true);
  assert.equal(isWithdrawalStateConflict({ message: "cannot cancel withdrawal in status paid" }), true);
  assert.equal(isWithdrawalStateConflict({ message: "amount must be a positive, finite number" }), false);
});

test("notification deep links only target routes that actually exist for the recipient's role", () => {
  assert.equal(notificationLink({ type: "APPEAL_OPENED", payload: { appeal_id: "a1" } }, "merchant"), "/merchant/appeals");
  assert.equal(notificationLink({ type: "WITHDRAWAL_STATUS_CHANGED", payload: { withdrawal_id: "w1" } }, "owner"), "/owner/withdrawals");
  assert.equal(notificationLink({ type: "DEPOSIT_CONFIRMED", payload: { deposit_id: "d1" } }, "merchant"), null);
  assert.equal(notificationLink({ type: "WITHDRAWAL_STATUS_CHANGED", payload: { withdrawal_id: "w1" } }, "user"), null);
  assert.equal(notificationLink({ type: "DEAL_CREATED", payload: { deal_id: "x1" } }, "owner"), null);
  assert.equal(notificationLink({ type: "APPEAL_OPENED", payload: null }, "owner"), null);
});

test("unmatched-transfers panel is a real named export wired into the owner deposits page", async () => {
  const panelSource = await source("src/components/deposits/unmatched-transfers-panel.tsx");
  const pageSource = await source("src/components/deposits/deposits-page.tsx");
  assert.match(panelSource, /export function UnmatchedTransfersPanel/);
  assert.match(pageSource, /import \{ UnmatchedTransfersPanel \} from "\.\/unmatched-transfers-panel"/);
  assert.match(pageSource, /<UnmatchedTransfersPanel \/>/);
});

test("owner and participant deal detail views fetch through the real backend routes, not mocked data", async () => {
  const api = await source("src/lib/api/deals.ts");
  const ownerDetailPage = await source("src/app/owner/deals/[id]/page.tsx");
  const listPage = await source("src/components/deals/deals-page.tsx");
  assert.match(api, /ownerGet: \(id: string\) => apiFetch<Deal>\(`\/owner\/deals\/\$\{id\}`\)/);
  assert.match(api, /merchantGet: \(id: string\) => apiFetch<Deal>\(`\/merchant\/deals\/\$\{id\}`\)/);
  assert.match(api, /userGet: \(id: string\) => apiFetch<Deal>\(`\/deals\/\$\{id\}`\)/);
  assert.match(ownerDetailPage, /dealsApi\.ownerGet\(id\)/);
  assert.match(listPage, /openDetail/);
  assert.doesNotMatch(ownerDetailPage, /mock|fake/i);
  assert.doesNotMatch(listPage, /mock|fake/i);
});

test("withdrawal detail is available to both owner and merchant through the real backend routes", async () => {
  const ownerApi = await source("src/lib/api/owner-operations.ts");
  const merchantApi = await source("src/lib/api/merchant.ts");
  const detailGrid = await source("src/components/withdrawals/withdrawal-detail.tsx");
  const ownerPage = await source("src/app/owner/withdrawals/page.tsx");
  const merchantPage = await source("src/app/merchant/withdrawals/page.tsx");
  assert.match(ownerApi, /getWithdrawal: \(id: string\) => apiFetch<MerchantWithdrawal>\(`\/owner\/withdrawals\/\$\{id\}`\)/);
  assert.match(merchantApi, /getWithdrawal: \(id: string\) => apiFetch<MerchantWithdrawal>\(`\/merchant\/withdrawals\/\$\{id\}`\)/);
  assert.match(ownerPage, /WithdrawalDetailGrid/);
  assert.match(merchantPage, /WithdrawalDetailGrid/);
  assert.doesNotMatch(detailGrid, /mock|fake/i);
});

test("appeals list resubscribes to the realtime invalidation key independent of the paginated query key", async () => {
  const page = await source("src/components/appeals/appeals-page.tsx");
  assert.match(page, /queryInvalidation\.subscribe\(`\$\{role\}-appeals`/);
  assert.match(page, /appealsApi\.list\(owner, PAGE_SIZE, offset\)/);
});

test("business mutations refetch the list on failure so stale actions don't linger after a 409/conflict", async () => {
  const dealsPage = await source("src/components/deals/deals-page.tsx");
  const ownerDealDetail = await source("src/app/owner/deals/[id]/page.tsx");
  const appealsPage = await source("src/components/appeals/appeals-page.tsx");
  for (const page of [dealsPage, ownerDealDetail, appealsPage]) {
    const catchBlockIndex = page.indexOf("catch");
    assert.ok(catchBlockIndex > -1, "expected a catch block");
    assert.match(page.slice(catchBlockIndex), /refetch\(\)/);
  }
});

test("business list views paginate instead of hardcoding limit=100", async () => {
  const appealsApi = await source("src/lib/api/appeals.ts");
  const depositsApi = await source("src/lib/api/deposits.ts");
  const merchantApi = await source("src/lib/api/merchant.ts");
  const ownerOpsApi = await source("src/lib/api/owner-operations.ts");
  const notificationsApi = await source("src/lib/api/notifications.ts");
  assert.match(appealsApi, /list: \(owner: boolean, limit = 20, offset = 0\)/);
  assert.match(depositsApi, /list: \(owner: boolean, status\?: DepositStatus, filters: DepositOwnerFilters = \{\}, limit = 20, offset = 0\)/);
  assert.match(merchantApi, /withdrawals: \(status\?: MerchantWithdrawal\["status"\], limit = 20, offset = 0\)/);
  assert.match(ownerOpsApi, /withdrawals: \(status\?: MerchantWithdrawal\["status"\], limit = 20, offset = 0\)/);
  assert.match(notificationsApi, /list: \(limit = 20, offset = 0\)/);
  const appealsPage = await source("src/components/appeals/appeals-page.tsx");
  const depositsPage = await source("src/components/deposits/deposits-page.tsx");
  const ownerWithdrawalsPage = await source("src/app/owner/withdrawals/page.tsx");
  const merchantWithdrawalsPage = await source("src/app/merchant/withdrawals/page.tsx");
  const notificationsPage = await source("src/components/notifications/notifications-page.tsx");
  for (const page of [appealsPage, depositsPage, ownerWithdrawalsPage, merchantWithdrawalsPage, notificationsPage]) {
    assert.match(page, /Pager/);
  }
});

test("owner deposit unmatched-transfer visibility is real, read-only, and not a manual-credit shortcut", async () => {
  const api = await source("src/lib/api/deposits.ts");
  const panel = await source("src/components/deposits/unmatched-transfers-panel.tsx");
  assert.match(api, /\/owner\/deposits\/unmatched/);
  assert.doesNotMatch(panel, /method:\s*"POST"/);
  assert.doesNotMatch(panel, /method:\s*"PATCH"/);
  assert.doesNotMatch(panel, /credit/i);
  assert.match(panel, /Pager/);
});

test("login page clears two-factor challenge state on a fresh credentials submit", async () => {
  const page = await source("src/app/login/page.tsx");
  assert.match(page, /resetTwoFactorState\(\)/);
  assert.match(page, /async function handleCredentialsSubmit/);
});

test("two-factor verify uses a dedicated BFF route and never proxies the challenge through /api/backend", async () => {
  const verifyRoute = await source("src/app/api/auth/2fa/verify/route.ts");
  const provider = await source("src/features/auth/auth-provider.tsx");
  assert.match(verifyRoute, /\/auth\/2fa\/verify/);
  assert.match(verifyRoute, /ACCESS_COOKIE/);
  assert.match(verifyRoute, /REFRESH_COOKIE/);
  assert.match(provider, /api\/auth\/2fa\/verify/);
});

test("2FA and security settings keys exist in RU/TG/EN", async () => {
  const catalogs = await Promise.all(["ru", "tg", "en"].map(async (locale) => JSON.parse(await source(`src/i18n/messages/${locale}.json`))));
  for (const catalog of catalogs) {
    assert.ok(catalog.auth.twoFactorTitle);
    assert.ok(catalog.auth.useRecoveryCode);
    assert.ok(catalog.auth.codeExpired);
    assert.ok(catalog.security.title);
    assert.ok(catalog.security.recoveryCodesWarning);
    assert.ok(catalog.security.enableSuccess);
    assert.ok(catalog.navigation.settings);
  }
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
