import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

import { healthStatusFromPayload } from "../src/features/health/system-health.ts";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("health state never stays green when readiness is unavailable", () => {
  assert.equal(healthStatusFromPayload(true, { status: "healthy" }), "healthy");
  assert.equal(healthStatusFromPayload(true, { status: "unexpected" }), "degraded");
  assert.equal(healthStatusFromPayload(true, null), "degraded");
  assert.equal(healthStatusFromPayload(false, { status: "healthy" }), "unavailable");
});

test("health BFF exposes only a sanitized status and polls without request spam", async () => {
  const route = await source("src/app/api/health/route.ts");
  const indicator = await source("src/features/health/system-health-indicator.tsx");
  assert.match(route, /backendFetch\("\/health\/ready"/);
  assert.match(route, /payload\?\.status === "ready" \? "healthy" : "degraded"/);
  assert.doesNotMatch(route, /checks:/);
  assert.match(indicator, /POLL_INTERVAL_MS = 30_000/);
  assert.match(indicator, /setStatus\("unavailable"\)/);
});

test("USER deposit rows reopen authoritative detail with copy and expired handling", async () => {
  const page = await source("src/components/deposits/deposits-page.tsx");
  const api = await source("src/lib/api/deposits.ts");
  assert.match(api, /\/deposits\/\$\{id\}/);
  assert.match(page, /onClick=\{\(\) => void openDetail\(item\.id\)\}/);
  assert.match(page, /depositsApi\.get\(owner, id\)/);
  assert.match(page, /navigator\.clipboard\.writeText/);
  assert.match(page, /detail\.status === "expired"/);
  assert.match(page, /owner && <><span>\{t\("account"\)\}/);
});

test("OWNER Telegram delivery operations use backend list and retry contracts", async () => {
  const api = await source("src/lib/api/notifications.ts");
  const panel = await source("src/components/notifications/owner-delivery-operations.tsx");
  const page = await source("src/components/notifications/notifications-page.tsx");
  assert.match(api, /\/notifications\/owner\/deliveries\?/);
  assert.match(api, /\/notifications\/owner\/deliveries\/\$\{id\}\/retry/);
  assert.match(panel, /item\.status === "FAILED"/);
  assert.match(panel, /await notificationsApi\.retryOwnerDelivery\(id\)/);
  assert.match(panel, /await query\.refetch\(\)/);
  assert.doesNotMatch(panel, /chat_id|telegram_id|bot_token|raw_payload/i);
  assert.match(page, /account\?\.role === "owner" && <OwnerDeliveryOperations/);
});

test("open payout and withdrawal details subscribe to scoped realtime invalidation", async () => {
  const payout = await source("src/app/owner/payouts/page.tsx");
  const ownerWithdrawal = await source("src/app/owner/withdrawals/page.tsx");
  const merchantWithdrawal = await source("src/app/merchant/withdrawals/page.tsx");
  assert.match(payout, /owner-payout:\$\{id\}/);
  assert.match(ownerWithdrawal, /owner-withdrawal:\$\{id\}/);
  assert.match(merchantWithdrawal, /merchant-withdrawal:\$\{id\}/);
});
