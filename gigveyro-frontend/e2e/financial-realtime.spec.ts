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
