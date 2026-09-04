import { createHmac } from "node:crypto";
import { expect, type Page } from "@playwright/test";

export const personas = {
  owner: "e2e_owner",
  userA: "e2e_user_a",
  userB: "e2e_user_b",
  merchantA: "e2e_merchant_a",
  merchantB: "e2e_merchant_b",
  blocked: "e2e_blocked",
} as const;

const password = "E2e-Only-Password-42";
const ownerSecret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";

function decodeBase32(value: string) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const character of value.replace(/[=\s-]/g, "").toUpperCase()) {
    bits += alphabet.indexOf(character).toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let index = 0; index + 8 <= bits.length; index += 8) bytes.push(Number.parseInt(bits.slice(index, index + 8), 2));
  return Buffer.from(bytes);
}

export function totp(secret: string) {
  const counter = Math.floor(Date.now() / 1000 / 30);
  const buffer = Buffer.alloc(8);
  buffer.writeBigUInt64BE(BigInt(counter));
  const digest = createHmac("sha1", decodeBase32(secret)).update(buffer).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const code = ((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).toString();
  return code.padStart(6, "0");
}

export async function login(page: Page, username: string, credential = password) {
  await page.goto("/login");
  const submit = page.getByRole("button", { name: "Войти в кабинет" });
  await expect(submit).toBeEnabled();
  await page.getByLabel("Логин").fill(username);
  await page.getByLabel("Пароль").fill(credential);
  const [response] = await Promise.all([
    page.waitForResponse((candidate) => candidate.url().includes("/api/auth/login"), { timeout: 15_000 }),
    submit.click(),
  ]);
  expect(response.status(), await response.text()).toBe(200);
  if (username === personas.owner) {
    const challenge = await response.json();
    expect(challenge.two_factor_required).toBe(true);
    await page.getByLabel("Код подтверждения").fill(totp(ownerSecret));
    const [verifyResponse] = await Promise.all([
      page.waitForResponse((candidate) => candidate.url().includes("/api/auth/2fa/verify"), { timeout: 15_000 }),
      page.getByRole("button", { name: "Подтвердить" }).click(),
    ]);
    expect(verifyResponse.status(), await verifyResponse.text()).toBe(200);
  }
  await expect(page).toHaveURL(new RegExp(`/${username === personas.owner ? "owner" : username.includes("merchant") ? "merchant" : "user"}$`));
}

export async function expectNoRuntimeError(page: Page) {
  await expect(page.locator("main")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Application error");
  await expect(page.locator("body")).not.toContainText("Internal Server Error");
}
