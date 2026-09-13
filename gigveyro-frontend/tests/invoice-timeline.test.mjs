import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("invoice timeline uses the real merchant backend route, not mocked data", async () => {
  const api = await source("src/lib/api/invoices.ts");
  assert.match(api, /timeline: \(id: string\) => apiFetch<InvoiceTimeline>\(`\/merchant\/invoices\/\$\{id\}\/timeline`\)/);
});

test("invoice detail modal fetches the timeline as a best-effort supplement, never blocking the detail view", async () => {
  const page = await source("src/app/merchant/invoices/page.tsx");
  assert.match(page, /void invoicesApi\.timeline\(id\)\.then\(setTimeline\)\.catch\(\(\) => undefined\)/);
  assert.match(page, /timeline && <InvoiceTimelineSection timeline=\{timeline\}\s*\/>/);
});

test("invoice timeline refetches on the same existing realtime key as the invoice detail, no new channel", async () => {
  const page = await source("src/app/merchant/invoices/page.tsx");
  assert.match(page, /queryInvalidation\.subscribe\(`merchant-invoice:\$\{id\}`, \(\) => \{[\s\S]{0,200}invoicesApi\.timeline\(id\)/);
});

test("invoice timeline component never renders raw ledger balance snapshots or webhook secrets", async () => {
  const component = await source("src/components/invoices/invoice-timeline.tsx");
  assert.doesNotMatch(component, /available_before|available_after|insurance_before|insurance_after|encrypted_secret|last_response_snippet/);
});

test("invoice timeline translation keys exist in RU/TG/EN", async () => {
  const catalogs = await Promise.all(["ru", "tg", "en"].map(async (locale) => JSON.parse(await source(`src/i18n/messages/${locale}.json`))));
  for (const catalog of catalogs) {
    assert.ok(catalog.invoices.timeline.title);
    assert.ok(catalog.invoices.timeline.empty);
    assert.ok(catalog.invoices.timeline.events.invoice_created);
    assert.ok(catalog.invoices.timeline.events.deposit_credited);
    assert.ok(catalog.invoices.timeline.events.webhook_failed);
    assert.ok(catalog.invoices.timeline.balanceCredited);
    assert.ok(catalog.invoices.timeline.attemptCount);
    assert.ok(catalog.invoices.timeline.webhooksTitle);
  }
});
