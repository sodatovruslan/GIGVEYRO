import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

import { queryKeysForRealtimeEvent } from "../src/features/realtime/event-map.ts";
import { RealtimeClient } from "../src/features/realtime/realtime-client.ts";
import { QueryInvalidationBus } from "../src/lib/query/invalidation.ts";

const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

class FakeSocket {
  onopen = null;
  onmessage = null;
  onclose = null;
  onerror = null;
  sent = [];
  closed = false;

  send(value) { this.sent.push(value); }
  close() { this.closed = true; }
  emitOpen() { this.onopen?.(); }
  emitClose() { this.closed = true; this.onclose?.(); }
  emit(value) { this.onmessage?.({ data: JSON.stringify(value) }); }
}

function harness() {
  const sockets = [];
  const events = [];
  const timers = [];
  let ticketRequests = 0;
  const client = new RealtimeClient({
    getTicket: async () => {
      ticketRequests += 1;
      return { ticket: `ticket-${ticketRequests}`, expires_in: 30, websocket_path: "/api/v1/ws" };
    },
    createSocket: (url, protocols) => {
      const socket = new FakeSocket();
      socket.url = url;
      socket.protocols = protocols;
      sockets.push(socket);
      return socket;
    },
    resolveUrl: (path) => `ws://backend.test${path}`,
    onEvent: (event) => events.push(event),
    schedule: (callback, delay) => {
      timers.push({ callback, delay });
      return timers.length;
    },
    cancelSchedule: () => {},
    random: () => 0,
  });
  return { client, sockets, events, timers, ticketRequests: () => ticketRequests };
}

const dealEvent = {
  version: 1,
  id: "event-1",
  event: "deal.created",
  entity_id: "deal-1",
  occurred_at: "2026-08-22T00:00:00Z",
  data: { status: "available" },
};

test("realtime connects with a short-lived ticket and handles heartbeat", async () => {
  const state = harness();
  state.client.start();
  await flush();

  assert.equal(state.ticketRequests(), 1);
  assert.equal(state.sockets.length, 1);
  assert.equal(state.sockets[0].url, "ws://backend.test/api/v1/ws");
  assert.deepEqual(state.sockets[0].protocols, [
    "gigveyro.realtime.v1",
    "gigveyro.ticket.ticket-1",
  ]);
  state.sockets[0].emit({ type: "ping" });
  assert.deepEqual(state.sockets[0].sent, [JSON.stringify({ type: "pong" })]);
});

test("logout or account switch closes and isolates the stale socket", async () => {
  const state = harness();
  state.client.start();
  await flush();
  const staleSocket = state.sockets[0];

  state.client.stop();
  staleSocket.emit(dealEvent);

  assert.equal(staleSocket.closed, true);
  assert.deepEqual(state.events, []);
});

test("temporary disconnect reconnects with exponential backoff", async () => {
  const state = harness();
  state.client.start();
  await flush();

  state.sockets[0].emitClose();
  assert.equal(state.timers.length, 1);
  assert.equal(state.timers[0].delay, 800);
  state.timers[0].callback();
  await flush();

  assert.equal(state.ticketRequests(), 2);
  assert.equal(state.sockets.length, 2);
});

test("duplicate events only signal one REST refresh", async () => {
  const state = harness();
  state.client.start();
  await flush();

  state.sockets[0].emit(dealEvent);
  state.sockets[0].emit(dealEvent);

  assert.equal(state.events.length, 1);
});

test("deal events invalidate only role-relevant REST resources", () => {
  assert.deepEqual(queryKeysForRealtimeEvent("deal.created", "user"), ["available-deals"]);
  assert.ok(queryKeysForRealtimeEvent("deal.completed", "user").includes("wallet-page"));
  assert.ok(queryKeysForRealtimeEvent("deal.completed", "merchant").includes("merchant-wallet"));
  assert.ok(queryKeysForRealtimeEvent("deal.completed", "owner").includes("analytics:*"));
});

test("fiat events refetch exact owner/user resources without merchant leakage", () => {
  assert.deepEqual(queryKeysForRealtimeEvent("fiat.allocated", "owner"), ["owner-fiat:*"]);
  assert.deepEqual(queryKeysForRealtimeEvent("fiat.converted", "user"), ["user-fiat:*"]);
  assert.deepEqual(queryKeysForRealtimeEvent("fiat.converted", "merchant"), []);

  const bus = new QueryInvalidationBus();
  let balances = 0;
  let ledger = 0;
  let usdt = 0;
  bus.subscribe("user-fiat:balances", () => { balances += 1; });
  bus.subscribe("user-fiat:ledger", () => { ledger += 1; });
  bus.subscribe("wallet-page", () => { usdt += 1; });
  assert.equal(bus.invalidate(queryKeysForRealtimeEvent("fiat.allocated", "user")), 2);
  assert.deepEqual({ balances, ledger, usdt }, { balances: 1, ledger: 1, usdt: 0 });
});

test("payout and withdrawal events invalidate only role-owned REST resources", () => {
  assert.deepEqual(queryKeysForRealtimeEvent("payout.updated", "user"), []);
  assert.deepEqual(queryKeysForRealtimeEvent("withdrawal.updated", "user"), []);

  const ownerPayout = queryKeysForRealtimeEvent("payout.updated", "owner");
  assert.ok(ownerPayout.includes("owner-payouts:*"));
  assert.ok(ownerPayout.includes("owner-payout:*"));
  assert.ok(ownerPayout.includes("owner-summary"));
  assert.ok(!ownerPayout.includes("owner-withdrawals:*"));

  const ownerWithdrawal = queryKeysForRealtimeEvent("withdrawal.updated", "owner");
  assert.ok(ownerWithdrawal.includes("owner-withdrawals:*"));
  assert.ok(ownerWithdrawal.includes("owner-withdrawal:*"));
  assert.ok(ownerWithdrawal.includes("owner-payouts:*"));

  const merchant = queryKeysForRealtimeEvent("withdrawal.updated", "merchant");
  assert.ok(merchant.includes("merchant-withdrawals:*"));
  assert.ok(merchant.includes("merchant-withdrawal:*"));
  assert.ok(merchant.includes("merchant-wallet"));
  assert.ok(!merchant.includes("owner-payouts:*"));
});

test("query invalidation supports exact and scoped prefix keys", () => {
  const bus = new QueryInvalidationBus();
  let deals = 0;
  let analytics = 0;
  let accounts = 0;
  bus.subscribe("owner-deals", () => { deals += 1; });
  bus.subscribe("analytics:30d", () => { analytics += 1; });
  bus.subscribe("accounts:search:user", () => { accounts += 1; });

  assert.equal(bus.invalidate(["owner-deals", "analytics:*"]), 2);
  assert.deepEqual({ deals, analytics, accounts }, { deals: 1, analytics: 1, accounts: 0 });
});

test("realtime handlers revalidate REST and never mutate financial values", async () => {
  const provider = await readFile(
    new URL("../src/features/realtime/realtime-provider.tsx", import.meta.url),
    "utf8",
  );
  assert.match(provider, /queryInvalidation\.invalidate/);
  assert.doesNotMatch(provider, /balance\s*[+\-*/]?=/);
  assert.doesNotMatch(provider, /setData\s*\(/);
});
