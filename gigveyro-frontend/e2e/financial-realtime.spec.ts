import { expect, test } from "@playwright/test";

import { login, personas } from "./support";

test.describe.configure({ mode: "serial" });

test("synthetic deposit credits once through the authoritative backend path", async ({ browser }) => {
  const userContext = await browser.newContext();
  const ownerContext = await browser.newContext();
  const user = await userContext.newPage();
  const owner = await ownerContext.newPage();
  await login(user, personas.userA);
  await login(owner, personas.owner);

  const beforeResponse = await user.request.get("/api/backend/wallet");
  const before = await beforeResponse.json();
  const createdResponse = await user.request.post("/api/backend/deposits", { data: { amount: "10" } });
  expect(createdResponse.status()).toBe(201);
  const deposit = await createdResponse.json();
  const txHash = `e2e-deposit-${Date.now()}`;
  const payload = { tx_hash: txHash, amount: "10", confirmations: 20, network: "TRC20", asset: "USDT", destination_address: deposit.deposit_address };
  const credited = await owner.request.post(`/api/backend/owner/dev/deposits/${deposit.id}/simulate`, { data: payload });
  expect(credited.status()).toBe(200);
  expect((await credited.json()).status).toBe("credited");
  const afterFirstCredit = await (await user.request.get("/api/backend/wallet")).json();
  const duplicate = await owner.request.post(`/api/backend/owner/dev/deposits/${deposit.id}/simulate`, { data: payload });
  expect(duplicate.status()).toBe(200);
  expect((await duplicate.json()).status).toBe("credited");

  const after = await (await user.request.get("/api/backend/wallet")).json();
  expect(Number(after.available_balance) - Number(before.available_balance)).toBe(10);
  expect(after.available_balance).toBe(afterFirstCredit.available_balance);
  await user.goto("/user/deposits");
  await expect(user.getByText(deposit.public_id)).toBeVisible();
  await expect(user.getByRole("table").getByText("Зачислен", { exact: true })).toBeVisible();
  await user.goto("/user/notifications");
  await expect(user.getByText(/Депозит .* 10.* USDT зачислен/)).toBeVisible();
  await expect(user.locator("body")).not.toContainText("deposit.credited");

  await userContext.close();
  await ownerContext.close();
});

test("owner reconciles an exact match and safely ignores a no-match transfer", async ({ browser }) => {
  const ownerContext = await browser.newContext();
  const userContext = await browser.newContext();
  const owner = await ownerContext.newPage();
  const user = await userContext.newPage();
  await login(owner, personas.owner);
  await login(user, personas.userA);
  const before = await (await user.request.get("/api/backend/wallet")).json();

  await owner.goto("/owner/deposits");
  await owner.getByText("tx-e2e-link", { exact: true }).click();
  const linkDialog = owner.getByRole("dialog");
  await linkDialog.getByText("DEP-E2E-LINK", { exact: true }).click();
  await linkDialog.getByRole("button", { name: "Связать с выбранным депозитом" }).click();
  await owner.getByRole("button", { name: "Подтвердить действие" }).click();
  await expect(owner.getByRole("status")).toContainText("безопасно связан и зачислен");
  const linked = await owner.request.get("/api/backend/owner/deposits/unmatched/00000000-0000-4000-8000-000000000201");
  expect((await linked.json()).reconciliation_status).toBe("CREDITED");
  const repeatLink = await owner.request.post("/api/backend/owner/deposits/unmatched/00000000-0000-4000-8000-000000000201/link", {
    data: { deposit_id: "00000000-0000-4000-8000-000000000101", idempotency_key: "e2e-repeat-link" },
  });
  expect(repeatLink.status()).toBe(409);

  await owner.getByRole("button", { name: "Готово" }).click();
  await owner.getByText("tx-e2e-ignore", { exact: true }).click();
  await owner.getByRole("button", { name: "Проверить повторно" }).click();
  await owner.getByRole("button", { name: "Подтвердить действие" }).click();
  await expect(owner.getByRole("status")).toContainText("проверен повторно");
  await owner.getByPlaceholder("Обязательная причина по результатам проверки").fill("E2E verified no matching intent");
  await owner.getByRole("button", { name: "Игнорировать перевод" }).click();
  await owner.getByRole("button", { name: "Подтвердить действие" }).click();
  await expect(owner.getByRole("status")).toContainText("игнорирован");
  const ignored = await owner.request.get("/api/backend/owner/deposits/unmatched/00000000-0000-4000-8000-000000000202");
  expect((await ignored.json()).reconciliation_status).toBe("IGNORED");
  const after = await (await user.request.get("/api/backend/wallet")).json();
  expect(Number(after.available_balance) - Number(before.available_balance)).toBe(12);

  await ownerContext.close();
  await userContext.close();
});

test("Redis WebSocket event triggers authoritative owner REST refetch", async ({ browser }) => {
  const ownerContext = await browser.newContext();
  const merchantContext = await browser.newContext();
  const owner = await ownerContext.newPage();
  const merchant = await merchantContext.newPage();
  const sockets: string[] = [];
  owner.on("websocket", (socket) => sockets.push(socket.url()));
  await login(owner, personas.owner);
  await owner.goto("/owner/deals");
  await login(merchant, personas.merchantA);

  await expect.poll(() => sockets.some((url) => url.includes("/api/v1/ws"))).toBe(true);
  const createdResponse = await merchant.request.post("/api/backend/merchant/deals", { data: { amount_tjs: "109" } });
  expect(createdResponse.status()).toBe(201);
  const deal = await createdResponse.json();
  await expect(owner.getByText(deal.public_id)).toBeVisible({ timeout: 12_000 });

  await ownerContext.close();
  await merchantContext.close();
});

test("merchant withdrawal is isolated and owner sees safe pending state", async ({ browser }) => {
  const merchantContext = await browser.newContext();
  const otherMerchantContext = await browser.newContext();
  const ownerContext = await browser.newContext();
  const merchant = await merchantContext.newPage();
  const otherMerchant = await otherMerchantContext.newPage();
  const owner = await ownerContext.newPage();
  await login(merchant, personas.merchantA);
  await login(otherMerchant, personas.merchantB);
  await login(owner, personas.owner);

  const createdResponse = await merchant.request.post("/api/backend/merchant/withdrawals", {
    data: { amount: "5", destination_type: "bybit_uid", destination: "12345678", comment: "E2E safe pending withdrawal" },
  });
  expect(createdResponse.status()).toBe(201);
  const withdrawal = await createdResponse.json();
  expect(withdrawal.status).toBe("pending");
  const hidden = await otherMerchant.request.get(`/api/backend/merchant/withdrawals/${withdrawal.id}`);
  expect(hidden.status()).toBe(404);

  await owner.goto("/owner/withdrawals");
  await expect(owner.getByText(withdrawal.public_id)).toBeVisible();
  await merchant.goto("/merchant/notifications");
  await expect(merchant.locator("body")).not.toContainText("MERCHANT B PRIVATE MARKER");
  await owner.goto("/owner/payouts");
  await expect(owner.getByText("РЕАЛЬНЫЕ ВЫПЛАТЫ ОТКЛЮЧЕНЫ")).toBeVisible();

  await merchantContext.close();
  await otherMerchantContext.close();
  await ownerContext.close();
});

test("user withdrawal completes end to end: create, approve, mark paid", async ({ browser }) => {
  const userContext = await browser.newContext();
  const ownerContext = await browser.newContext();
  const user = await userContext.newPage();
  const owner = await ownerContext.newPage();
  await login(user, personas.userA);
  await login(owner, personas.owner);

  // Fund the user deterministically regardless of prior test state/order.
  const depositResponse = await user.request.post("/api/backend/deposits", { data: { amount: "77" } });
  expect(depositResponse.status()).toBe(201);
  const deposit = await depositResponse.json();
  const txHash = `e2e-withdrawal-fund-${Date.now()}`;
  const credit = await owner.request.post(`/api/backend/owner/dev/deposits/${deposit.id}/simulate`, {
    data: { tx_hash: txHash, amount: "77", confirmations: 20, network: "TRC20", asset: "USDT", destination_address: deposit.deposit_address },
  });
  expect(credit.status()).toBe(200);
  const before = await (await user.request.get("/api/backend/wallet")).json();

  const createdResponse = await user.request.post("/api/backend/withdrawals", {
    data: { amount: "30", destination_type: "usdt_trc20_address", destination: `T${"e2e".padEnd(33, "a")}`, comment: "E2E full lifecycle" },
  });
  expect(createdResponse.status()).toBe(201);
  const withdrawal = await createdResponse.json();
  expect(withdrawal.status).toBe("pending");

  const afterHold = await (await user.request.get("/api/backend/wallet")).json();
  expect(Number(before.available_balance) - Number(afterHold.available_balance)).toBe(30);
  expect(Number(afterHold.frozen_balance)).toBe(30);

  const approveResponse = await owner.request.post(`/api/backend/owner/user-withdrawals/${withdrawal.id}/approve`);
  expect(approveResponse.status()).toBe(200);
  expect((await approveResponse.json()).status).toBe("approved");

  // The old dead-end: this used to return 409 CONTROLLED_PAYOUT_REQUIRED
  // forever, leaving the user's funds frozen with no way out.
  const paidResponse = await owner.request.post(`/api/backend/owner/user-withdrawals/${withdrawal.id}/mark-paid`);
  expect(paidResponse.status()).toBe(200);
  expect((await paidResponse.json()).status).toBe("paid");

  const afterPaid = await (await user.request.get("/api/backend/wallet")).json();
  expect(Number(afterPaid.frozen_balance)).toBe(0);
  expect(Number(afterPaid.available_balance)).toBe(Number(afterHold.available_balance));

  const userView = await (await user.request.get(`/api/backend/withdrawals/${withdrawal.id}`)).json();
  expect(userView.status).toBe("paid");
  const ownerView = await (await owner.request.get(`/api/backend/owner/user-withdrawals/${withdrawal.id}`)).json();
  expect(ownerView.status).toBe("paid");

  await user.goto("/user/withdrawals");
  await expect(user.getByText(withdrawal.public_id)).toBeVisible();

  await userContext.close();
  await ownerContext.close();
});

test("user withdrawal rejected by owner returns funds", async ({ browser }) => {
  const userContext = await browser.newContext();
  const ownerContext = await browser.newContext();
  const user = await userContext.newPage();
  const owner = await ownerContext.newPage();
  await login(user, personas.userA);
  await login(owner, personas.owner);

  const before = await (await user.request.get("/api/backend/wallet")).json();
  const createdResponse = await user.request.post("/api/backend/withdrawals", {
    data: { amount: "5", destination_type: "usdt_trc20_address", destination: `T${"e2e".padEnd(33, "b")}` },
  });
  expect(createdResponse.status()).toBe(201);
  const withdrawal = await createdResponse.json();

  const rejectResponse = await owner.request.post(`/api/backend/owner/user-withdrawals/${withdrawal.id}/reject`);
  expect(rejectResponse.status()).toBe(200);
  expect((await rejectResponse.json()).status).toBe("rejected");

  const after = await (await user.request.get("/api/backend/wallet")).json();
  expect(after.available_balance).toBe(before.available_balance);
  expect(Number(after.frozen_balance)).toBe(0);

  await userContext.close();
  await ownerContext.close();
});

test("user cancels own pending withdrawal and funds are released", async ({ browser }) => {
  const userContext = await browser.newContext();
  const user = await userContext.newPage();
  await login(user, personas.userA);

  const before = await (await user.request.get("/api/backend/wallet")).json();
  const createdResponse = await user.request.post("/api/backend/withdrawals", {
    data: { amount: "5", destination_type: "usdt_trc20_address", destination: `T${"e2e".padEnd(33, "c")}` },
  });
  expect(createdResponse.status()).toBe(201);
  const withdrawal = await createdResponse.json();

  const cancelResponse = await user.request.post(`/api/backend/withdrawals/${withdrawal.id}/cancel`);
  expect(cancelResponse.status()).toBe(200);
  expect((await cancelResponse.json()).status).toBe("cancelled");

  const after = await (await user.request.get("/api/backend/wallet")).json();
  expect(after.available_balance).toBe(before.available_balance);
  expect(Number(after.frozen_balance)).toBe(0);

  await userContext.close();
});

test("merchant views a paid invoice's full timeline: deposit, balance credit, and webhook delivery", async ({ browser }) => {
  const merchantContext = await browser.newContext();
  const ownerContext = await browser.newContext();
  const merchant = await merchantContext.newPage();
  const owner = await ownerContext.newPage();
  await login(merchant, personas.merchantA);
  await login(owner, personas.owner);

  const webhookResponse = await merchant.request.post("/api/backend/merchant/webhooks", {
    data: { url: "https://example.com/e2e-timeline-hook", event_types: ["invoice.paid"] },
  });
  expect(webhookResponse.status()).toBe(201);

  const createdResponse = await merchant.request.post("/api/backend/merchant/invoices", { data: { amount: "17" } });
  expect(createdResponse.status()).toBe(201);
  const invoice = await createdResponse.json();

  const freshTimelineResponse = await merchant.request.get(`/api/backend/merchant/invoices/${invoice.id}/timeline`);
  expect(freshTimelineResponse.status()).toBe(200);
  const freshTimeline = await freshTimelineResponse.json();
  expect(freshTimeline.events.map((event: { type: string }) => event.type)).toEqual(["invoice.created"]);
  expect(freshTimeline.webhook_deliveries).toEqual([]);

  // The dev-simulate route only accepts a deposit id, and the merchant API
  // never exposes one directly - resolve it the same way an owner would,
  // through their own deposit oversight list, scoped to this merchant's
  // single still-WAITING deposit right after invoice creation.
  const ownerDeposits = await (
    await owner.request.get(`/api/backend/owner/deposits?account_id=${invoice.merchant_id}&status=waiting&limit=5`)
  ).json();
  const linkedDeposit = ownerDeposits.items.find((item: { expected_amount: string }) => item.expected_amount === "17.00000000");
  expect(linkedDeposit).toBeTruthy();

  const txHash = `e2e-invoice-timeline-${Date.now()}`;
  const credited = await owner.request.post(`/api/backend/owner/dev/deposits/${linkedDeposit.id}/simulate`, {
    data: { tx_hash: txHash, amount: "17", confirmations: 20, network: "TRC20", asset: "USDT", destination_address: linkedDeposit.deposit_address },
  });
  expect(credited.status()).toBe(200);
  expect((await credited.json()).status).toBe("credited");

  const paidTimelineResponse = await merchant.request.get(`/api/backend/merchant/invoices/${invoice.id}/timeline`);
  expect(paidTimelineResponse.status()).toBe(200);
  const paidTimeline = await paidTimelineResponse.json();
  const eventTypes = paidTimeline.events.map((event: { type: string }) => event.type);
  for (const expected of ["invoice.created", "deposit.detected", "deposit.confirmed", "deposit.credited", "invoice.balance_credited", "invoice.paid"]) {
    expect(eventTypes).toContain(expected);
  }
  expect(paidTimeline.deposit.tx_hash).toBe(txHash);
  expect(paidTimeline.ledger_entry.amount).toBe("17.00000000");
  expect(paidTimeline.webhook_deliveries).toHaveLength(1);
  expect(paidTimeline.webhook_deliveries[0].event_type).toBe("invoice.paid");

  await merchant.goto("/merchant/invoices");
  await merchant.getByText(invoice.public_id).click();
  // The tx hash appears twice (the deposit.detected event and the deposit
  // summary block) - either instance proves the timeline actually rendered.
  await expect(merchant.getByText(txHash).first()).toBeVisible();

  await merchantContext.close();
  await ownerContext.close();
});

test("merchant cannot view another merchant's invoice timeline", async ({ browser }) => {
  const merchantAContext = await browser.newContext();
  const merchantBContext = await browser.newContext();
  const merchantA = await merchantAContext.newPage();
  const merchantB = await merchantBContext.newPage();
  await login(merchantA, personas.merchantA);
  await login(merchantB, personas.merchantB);

  const createdResponse = await merchantA.request.post("/api/backend/merchant/invoices", { data: { amount: "3" } });
  expect(createdResponse.status()).toBe(201);
  const invoice = await createdResponse.json();

  const ownTimeline = await merchantA.request.get(`/api/backend/merchant/invoices/${invoice.id}/timeline`);
  expect(ownTimeline.status()).toBe(200);

  const crossTenantAttempt = await merchantB.request.get(`/api/backend/merchant/invoices/${invoice.id}/timeline`);
  expect(crossTenantAttempt.status()).toBe(404);

  await merchantAContext.close();
  await merchantBContext.close();
});

test("deal settlement splits into merchant/user-profit/owner-profit and the UI reflects it", async ({ browser }) => {
  const merchantContext = await browser.newContext();
  const userContext = await browser.newContext();
  const ownerContext = await browser.newContext();
  const merchant = await merchantContext.newPage();
  const user = await userContext.newPage();
  const owner = await ownerContext.newPage();
  await login(merchant, personas.merchantA);
  await login(user, personas.userA);
  await login(owner, personas.owner);

  // 10.90 TJS at the fixed demo rate (10.90 USDT/TJS) converts to exactly
  // 1.00000000 USDT - small enough to never collide with userA's balance
  // from the other tests in this file, and round enough to hand-verify.
  const created = await merchant.request.post("/api/backend/merchant/deals", {
    data: { amount_tjs: "10.90" },
  });
  expect(created.status()).toBe(201);
  const deal = await created.json();

  const requisites = await (await user.request.get("/api/backend/requisites")).json();
  const requisite = requisites.find((item: { is_active: boolean }) => item.is_active);
  expect(requisite).toBeTruthy();

  const accepted = await user.request.post(`/api/backend/deals/${deal.id}/accept`, {
    data: { payment_requisite_id: requisite.id },
  });
  expect(accepted.status()).toBe(200);
  const acceptedDeal = await accepted.json();
  expect(acceptedDeal.amount_usdt).toBe("1.00000000");

  const completed = await owner.request.post(`/api/backend/owner/deals/${deal.id}/complete`);
  expect(completed.status()).toBe(200);
  const settled = await completed.json();
  // 1.00 USDT deal: owner 7% = 0.07, user profit 10% = 0.10, merchant gets
  // the residual 0.83 - the three always sum back to exactly 1.00.
  expect(settled.owner_profit_amount).toBe("0.07000000");
  expect(settled.user_profit_amount).toBe("0.10000000");
  expect(settled.merchant_settlement_amount).toBe("0.83000000");

  // USER and MERCHANT views never receive the platform's own margin.
  const userView = await user.request.get(`/api/backend/deals/${deal.id}`);
  expect(Object.keys(await userView.json())).not.toContain("owner_profit_amount");
  const merchantView = await merchant.request.get(`/api/backend/merchant/deals/${deal.id}`);
  expect(Object.keys(await merchantView.json())).not.toContain("owner_profit_amount");

  await user.goto("/user/deals");
  await user.getByText(deal.public_id).click();
  await expect(user.getByText("0.10000000 USDT")).toBeVisible();

  await merchantContext.close();
  await userContext.close();
  await ownerContext.close();
});

test("team lead cabinet: assignment, deal profit accrual, withdrawal lifecycle, and isolation", async ({ browser }) => {
  const ownerContext = await browser.newContext();
  const teamLeadContext = await browser.newContext();
  const otherLeadContext = await browser.newContext();
  const merchantContext = await browser.newContext();
  const userContext = await browser.newContext();
  const owner = await ownerContext.newPage();
  const teamLead = await teamLeadContext.newPage();
  const otherLead = await otherLeadContext.newPage();
  const merchant = await merchantContext.newPage();
  const user = await userContext.newPage();
  await login(owner, personas.owner);

  const teamLeadPassword = "E2e-TeamLead-Password-9";
  const teamLeadUsername = `e2e_team_lead_${Date.now()}`;
  const created = await owner.request.post("/api/backend/owner/accounts", {
    data: {
      username: teamLeadUsername,
      password: teamLeadPassword,
      role: "team_lead",
      full_name: "E2E Team Lead",
    },
  });
  expect(created.status()).toBe(201);
  const teamLeadAccount = await created.json();

  const otherLeadUsername = `e2e_team_lead_other_${Date.now()}`;
  const createdOther = await owner.request.post("/api/backend/owner/accounts", {
    data: {
      username: otherLeadUsername,
      password: teamLeadPassword,
      role: "team_lead",
      full_name: "E2E Other Team Lead",
    },
  });
  expect(createdOther.status()).toBe(201);

  // 1. Team Lead login.
  await login(teamLead, teamLeadUsername, teamLeadPassword);
  await login(otherLead, otherLeadUsername, teamLeadPassword);
  await login(merchant, personas.merchantA);
  await login(user, personas.userA);

  // Assign userA to the new Team Lead.
  const userProfile = await user.request.get("/api/backend/auth/me");
  const userId = (await userProfile.json()).id;
  const assign = await owner.request.post(`/api/backend/owner/accounts/${userId}/team-lead`, {
    data: { team_lead_id: teamLeadAccount.id },
  });
  expect(assign.status()).toBe(200);

  // 2. Open dashboard. 3. See team.
  await teamLead.goto("/team_lead");
  await expect(teamLead.locator("main")).toBeVisible();
  const teamResponse = await teamLead.request.get("/api/backend/team-lead/team");
  const teamBody = await teamResponse.json();
  expect(teamBody.total).toBe(1);
  expect(teamBody.items[0].id).toBe(userId);

  // A completed deal by userA (10.90 TJS at the fixed 10.90 demo rate = exactly
  // 1.00000000 USDT) accrues the Team Lead's 1.5% share = 0.01500000.
  const dealCreated = await merchant.request.post("/api/backend/merchant/deals", {
    data: { amount_tjs: "10.90" },
  });
  expect(dealCreated.status()).toBe(201);
  const deal = await dealCreated.json();
  const requisites = await (await user.request.get("/api/backend/requisites")).json();
  const requisite = requisites.find((item: { is_active: boolean }) => item.is_active);
  const accepted = await user.request.post(`/api/backend/deals/${deal.id}/accept`, {
    data: { payment_requisite_id: requisite.id },
  });
  expect(accepted.status()).toBe(200);
  const completed = await owner.request.post(`/api/backend/owner/deals/${deal.id}/complete`);
  expect(completed.status()).toBe(200);
  expect((await completed.json()).team_lead_profit_amount).toBe("0.01500000");

  // 4. See profit.
  const dashboard = await teamLead.request.get("/api/backend/team-lead/dashboard");
  const dashboardBody = await dashboard.json();
  expect(dashboardBody.profit_available).toBe("0.01500000");
  expect(dashboardBody.deal_count).toBe(1);

  // 5. Create withdrawal.
  const withdrawalCreated = await teamLead.request.post("/api/backend/team-lead/withdrawals", {
    data: { amount: "0.015", destination_type: "usdt_trc20_address", destination: "T" + "a".repeat(33) },
  });
  expect(withdrawalCreated.status()).toBe(201);
  const withdrawal = await withdrawalCreated.json();
  expect(withdrawal.status).toBe("pending");

  // 6. Owner sees withdrawal. 7. Owner approves.
  const ownerList = await owner.request.get("/api/backend/owner/team-lead-withdrawals");
  const ownerListBody = await ownerList.json();
  expect(ownerListBody.items.some((item: { id: string }) => item.id === withdrawal.id)).toBe(true);
  const approve = await owner.request.post(`/api/backend/owner/team-lead-withdrawals/${withdrawal.id}/approve`);
  expect(approve.status()).toBe(200);

  // 8. Team Lead sees APPROVED.
  const afterApprove = await teamLead.request.get(`/api/backend/team-lead/withdrawals/${withdrawal.id}`);
  expect((await afterApprove.json()).status).toBe("approved");

  // 9. Complete payment using the existing supported flow (owner mark-paid).
  const markPaid = await owner.request.post(`/api/backend/owner/team-lead-withdrawals/${withdrawal.id}/mark-paid`);
  expect(markPaid.status()).toBe(200);

  // 10. Team Lead sees PAID.
  const afterPaid = await teamLead.request.get(`/api/backend/team-lead/withdrawals/${withdrawal.id}`);
  expect((await afterPaid.json()).status).toBe("paid");

  // 11. Verify balance/ledger.
  const finalWallet = await owner.request.get(`/api/backend/owner/accounts/${teamLeadAccount.id}/wallet`);
  const finalWalletBody = await finalWallet.json();
  expect(finalWalletBody.available_balance).toBe("0.00000000");
  expect(finalWalletBody.frozen_balance).toBe("0.00000000");

  // 12. Verify Team Lead cannot access Owner pages.
  await teamLead.goto("/owner");
  await expect(teamLead).toHaveURL(/\/team_lead$/);
  const ownerApiAttempt = await teamLead.request.get("/api/backend/owner/accounts");
  expect(ownerApiAttempt.status()).toBe(403);

  // 13. Verify another Team Lead cannot see this team's data.
  const otherTeam = await otherLead.request.get("/api/backend/team-lead/team");
  expect((await otherTeam.json()).total).toBe(0);
  const otherWithdrawalAttempt = await otherLead.request.get(`/api/backend/team-lead/withdrawals/${withdrawal.id}`);
  expect(otherWithdrawalAttempt.status()).toBe(404);

  await ownerContext.close();
  await teamLeadContext.close();
  await otherLeadContext.close();
  await merchantContext.close();
  await userContext.close();
});

test("merchant critical routes render without owner navigation", async ({ page }) => {
  await login(page, personas.merchantA);
  for (const route of ["/merchant", "/merchant/wallet", "/merchant/deals", "/merchant/withdrawals", "/merchant/appeals", "/merchant/notifications", "/merchant/settings"]) {
    await page.goto(route);
    await expect(page.locator("main")).toBeVisible();
  }
  await expect(page.getByRole("navigation")).not.toContainText("Казначейство");
  await page.goto("/owner/treasury");
  await expect(page).toHaveURL(/\/merchant$/);
  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login$/);
});
