import { expect, test } from "@playwright/test";

import { expectNoRuntimeError, login, personas, totp } from "./support";

test.describe.configure({ mode: "serial" });

test("closed registration, localized login and theme preferences", async ({ page }) => {
  const register = await page.goto("/register");
  expect(register?.status()).toBe(404);

  await page.goto("/login");
  await expect(page.getByText("Нет аккаунта? Обратитесь к администратору GigaPay.")).toBeVisible();
  await expect(page.getByRole("link", { name: /создать|register|sign up/i })).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("GIGVEYRO");

  // The controls are present in SSR HTML before React attaches handlers.
  // ThemeProvider marks the document once hydration is complete.
  await expect(page.locator("html")).toHaveClass(/theme-ready/);
  await expect(page.locator("html")).toHaveClass(/theme-ready/);
  await page.getByRole("button", { name: "Светлая тема" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme-preference", "light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Тёмная тема" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme-preference", "dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Системная тема" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme-preference", "system");

  await page.getByLabel("Выбор языка").selectOption("en");
  await expect(page.getByText("No account? Contact your GigaPay administrator.")).toBeVisible();
  await page.getByLabel("Language").selectOption("tg");
  await expect(page.getByText("Ҳисоб надоред? Ба маъмури GigaPay муроҷиат кунед.")).toBeVisible();
});

test("owner authentication, 2FA, session persistence and account provisioning", async ({ page }) => {
  await page.goto("/login");
  const invalidSubmit = page.getByRole("button", { name: "Войти в кабинет" });
  await expect(invalidSubmit).toBeEnabled();
  await page.getByLabel("Логин").fill(personas.owner);
  await page.getByLabel("Пароль").fill("wrong-password");
  const [invalidResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().includes("/api/auth/login"), { timeout: 15_000 }),
    invalidSubmit.click(),
  ]);
  expect(invalidResponse.status()).toBe(401);
  await expect(page.locator("main").getByRole("alert")).toBeVisible();

  await page.getByLabel("Выбор языка").selectOption("ru");
  await login(page, personas.owner);
  await page.reload();
  await expect(page).toHaveURL(/\/owner$/);
  await expect(page.getByText("GigaPay", { exact: true }).first()).toBeVisible();

  await page.goto("/owner/accounts");
  for (const [username, role] of [["e2e_created_user", "user"], ["e2e_created_merchant", "merchant"]] as const) {
    await page.getByRole("button", { name: /Создать аккаунт/ }).click();
    const dialog = page.getByRole("dialog");
    await dialog.locator("select").selectOption(role);
    await dialog.getByLabel("Логин").fill(username);
    await dialog.getByLabel("Полное имя").fill(`E2E ${role}`);
    await dialog.getByLabel("Пароль").fill("Provisioned-Only-42");
    await dialog.getByRole("button", { name: "Создать", exact: true }).click();
    await expect(dialog.getByText("Аккаунт активен и готов ко входу")).toBeVisible();
    await expect(dialog).not.toContainText("Provisioned-Only-42");
    await expect(dialog.getByText(`@${username}`)).toBeVisible();
    await dialog.getByRole("button", { name: "Готово" }).click();
    await expect(page.getByText(`@${username}`)).toBeVisible();
  }

  const duplicate = await page.request.post("/api/backend/owner/accounts", {
    data: { username: "e2e_created_user", password: "Duplicate-Only-42", role: "user", full_name: "Duplicate" },
  });
  expect(duplicate.status()).toBe(409);
  await page.goto("/owner");
  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("owner critical routes render and payout stays non-live", async ({ page }) => {
  await login(page, personas.owner);
  for (const route of [
    "/owner", "/owner/accounts", "/owner/deals", "/owner/deposits", "/owner/withdrawals",
    "/owner/payouts", "/owner/appeals", "/owner/notifications", "/owner/analytics",
    "/owner/fees", "/owner/treasury", "/owner/integrations", "/owner/audit", "/owner/settings",
  ]) {
    await test.step(route, async () => { await page.goto(route); await expectNoRuntimeError(page); });
  }
  await page.goto("/owner/payouts");
  await expect(page.getByText("РЕАЛЬНЫЕ ВЫПЛАТЫ ОТКЛЮЧЕНЫ")).toBeVisible();
  await expect(page.getByText("НЕ ГОТОВО")).toBeVisible();
  await expect(page.getByText("На этом экране нет кнопки включения или отправки live-выплаты.")).toBeVisible();
  await page.goto("/owner/treasury");
  await expect(page.locator("body")).not.toContainText(/BYBIT_API_(KEY|SECRET)|Authorization:\s*Bearer/i);
});

test("user routes, RBAC, security, Telegram UI and data isolation", async ({ page }) => {
  await login(page, personas.userA);
  for (const route of ["/user", "/user/wallet", "/user/deposits", "/user/requisites", "/user/deals", "/user/appeals", "/user/notifications", "/user/settings"]) {
    await test.step(route, async () => { await page.goto(route); await expectNoRuntimeError(page); });
  }
  await page.goto("/user/settings");
  await expect(page.getByText("Информация об аккаунте")).toBeVisible();
  await expect(page.getByText("Активные сессии")).toBeVisible();
  await expect(page.getByText("Уведомления безопасности в Telegram")).toBeVisible();

  const forbidden = await page.request.get("/api/backend/owner/accounts");
  expect(forbidden.status()).toBe(403);
  const invalidDeposit = await page.request.post("/api/backend/deposits", { data: { amount: "-1" } });
  expect(invalidDeposit.status()).toBe(422);
  await page.goto("/owner/accounts");
  await expect(page).toHaveURL(/\/user$/);

  await page.goto("/user/notifications");
  await expect(page.locator("body")).not.toContainText("USER B PRIVATE MARKER");
  await expect(page.locator("body")).not.toContainText("security.password_changed");
  await expect(page.getByRole("button").filter({ hasText: "Пароль изменён" })).toBeVisible();
  await page.getByLabel("Выбор языка").selectOption("en");
  await expect(page.getByRole("navigation")).toContainText("Notifications");
  await expect(page.getByRole("button").filter({ hasText: "Password changed" })).toBeVisible();
  await page.getByLabel("Language").selectOption("tg");
  await expect(page.getByRole("navigation")).toContainText("Огоҳиҳо");
  const tajikSecurity = page.getByRole("button").filter({ hasText: "Парол иваз шуд" });
  await expect(tajikSecurity).toBeVisible();
  await tajikSecurity.click();
  await expect(page).toHaveURL(/\/user\/settings$/);
});

test("user sessions, password change, 2FA setup and recovery login", async ({ browser }) => {
  const primaryContext = await browser.newContext();
  const secondaryContext = await browser.newContext();
  const primary = await primaryContext.newPage();
  const secondary = await secondaryContext.newPage();
  await login(primary, personas.userB);
  await login(secondary, personas.userB);

  await primary.goto("/user/settings");
  const logoutOthers = primary.getByRole("button", { name: "Завершить все остальные сессии" });
  await expect(logoutOthers).toBeVisible();
  await logoutOthers.click();
  await expect(logoutOthers).toHaveCount(0);
  await expect.poll(async () => (await secondary.request.get("/api/auth/session")).status()).toBe(401);

  await primary.getByRole("button", { name: "Изменить пароль" }).click();
  let dialog = primary.getByRole("dialog");
  await dialog.getByLabel("Текущий пароль").fill("E2e-Only-Password-42");
  await dialog.getByLabel("Новый пароль").fill("E2e-Rotated-Password-43");
  await dialog.getByRole("button", { name: "Изменить пароль" }).click();
  await expect(primary.getByRole("status")).toContainText("Пароль успешно изменён");

  await primary.getByRole("button", { name: "Включить 2FA" }).click();
  dialog = primary.getByRole("dialog");
  await dialog.getByLabel("Текущий пароль").fill("E2e-Rotated-Password-43");
  await dialog.getByRole("button", { name: "Продолжить" }).click();
  const manualSecret = (await dialog.getByTestId("two-factor-manual-key").textContent())?.trim();
  expect(manualSecret).toBeTruthy();
  await dialog.getByLabel("Введите 6-значный код из приложения").fill(totp(manualSecret!));
  await dialog.getByRole("button", { name: "Включить", exact: true }).click();
  const recoveryCodes = dialog.getByTestId("two-factor-recovery-codes").locator("span");
  await expect(recoveryCodes.first()).toBeVisible();
  const recoveryCode = (await recoveryCodes.first().textContent())?.trim();
  expect(recoveryCode).toBeTruthy();
  await dialog.getByRole("button", { name: "Готово" }).click();

  await primary.getByRole("button", { name: "Выйти" }).click();
  await expect(primary).toHaveURL(/\/login$/);
  const submit = primary.getByRole("button", { name: "Войти в кабинет" });
  await expect(submit).toBeEnabled();
  await primary.getByLabel("Логин").fill(personas.userB);
  await primary.getByLabel("Пароль").fill("E2e-Rotated-Password-43");
  const [loginResponse] = await Promise.all([
    primary.waitForResponse((response) => response.url().includes("/api/auth/login")),
    submit.click(),
  ]);
  expect(loginResponse.status()).toBe(200);
  await primary.getByRole("button", { name: "Использовать резервный код" }).click();
  await primary.getByLabel("Резервный код").fill(recoveryCode!);
  await primary.getByRole("button", { name: "Подтвердить" }).click();
  await expect(primary).toHaveURL(/\/user$/);

  await primaryContext.close();
  await secondaryContext.close();
});

test("blocked account is denied and anonymous protected navigation returns to login", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Логин").fill(personas.blocked);
  await page.getByLabel("Пароль").fill("E2e-Only-Password-42");
  await page.getByRole("button", { name: "Войти в кабинет" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.goto("/user/wallet");
  await expect(page).toHaveURL(/\/login$/);
});

test("health, auth errors, unknown routes and basic accessibility", async ({ page }) => {
  const health = await page.request.get("/api/health");
  expect(health.status()).toBe(200);
  expect((await health.json()).status).toBe("healthy");
  const unauthorized = await page.request.get("/api/backend/auth/me");
  expect(unauthorized.status()).toBe(401);
  const unknown = await page.goto("/definitely-not-a-gigapay-route");
  expect(unknown?.status()).toBe(404);

  await page.goto("/login");
  const duplicateIds = await page.locator("[id]").evaluateAll((nodes) => {
    const ids = nodes.map((node) => node.id);
    return ids.filter((id, index) => ids.indexOf(id) !== index);
  });
  expect(duplicateIds).toEqual([]);
  await expect(page.getByRole("button", { name: "Войти в кабинет" })).toBeEnabled();
});
