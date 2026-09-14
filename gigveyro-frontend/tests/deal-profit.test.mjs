import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("deal detail only reveals the platform's owner profit margin to the owner role", async () => {
  const component = await source("src/components/deals/deal-detail.tsx");
  assert.match(component, /role === "owner" && deal\.owner_profit_amount/);
  assert.match(component, /role: "user" \| "merchant" \| "owner"/);
});

test("owner deal detail page explicitly passes role=\"owner\" to the shared grid", async () => {
  const page = await source("src/app/owner/deals/[id]/page.tsx");
  assert.match(page, /<DealDetailGrid deal=\{deal\} role="owner" \/>/);
});

test("user/merchant deals page passes its own role through, never hardcoding owner", async () => {
  const page = await source("src/components/deals/deals-page.tsx");
  assert.match(page, /<DealDetailGrid deal=\{detail\} role=\{role\} \/>/);
});

test("deal profit translation keys exist in RU/TG/EN and profit is never labeled a commission", async () => {
  const catalogs = await Promise.all(["ru", "tg", "en"].map(async (locale) => JSON.parse(await source(`src/i18n/messages/${locale}.json`))));
  for (const catalog of catalogs) {
    assert.ok(catalog.deals.merchantReceives);
    assert.ok(catalog.deals.userProfit);
    assert.ok(catalog.deals.ownerProfit);
    assert.doesNotMatch(catalog.deals.userProfit.toLowerCase(), /commission|комисс|коммисс/);
  }
});
