import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

import {
  notificationMessageKeys,
  renderNotificationMessage,
} from "../src/features/notifications/messages.ts";

const locales = ["ru", "en", "tg"];

async function messages(locale) {
  return JSON.parse(
    await readFile(
      new URL(`../src/i18n/messages/${locale}.json`, import.meta.url),
      "utf8",
    ),
  );
}

function getNested(object, path) {
  return path.split(".").reduce((value, key) => value?.[key], object);
}

function translator(catalog) {
  return (key, values = {}) => {
    const template = getNested(catalog.notificationMessages, key);
    if (typeof template !== "string") throw new Error(`missing ${key}`);
    return template.replace(/\{(\w+)\}/g, (_, name) => String(values[name]));
  };
}

test("every production notification key has nested title and body in RU, EN, and TG", async () => {
  for (const locale of locales) {
    const catalog = await messages(locale);
    for (const key of notificationMessageKeys) {
      assert.equal(typeof getNested(catalog.notificationMessages, `${key}.title`), "string");
      assert.equal(typeof getNested(catalog.notificationMessages, `${key}.body`), "string");
    }
  }
});

test("semantic notifications render localized params and preserve decimal strings", async () => {
  const expected = { ru: "зачислен", en: "credited", tg: "ворид шуд" };
  for (const locale of locales) {
    const rendered = renderNotificationMessage(
      {
        title: "legacy title",
        message: "legacy message",
        message_key: "deposit.credited",
        message_params: { reference: "DEP-42", amount: "10.5000", currency: "USDT" },
      },
      translator(await messages(locale)),
    );
    assert.match(rendered.message, new RegExp(expected[locale]));
    assert.match(rendered.message, /DEP-42/);
    assert.match(rendered.message, /10\.5000 USDT/);
  }
});

test("legacy and unknown notification keys use stored fallback without exposing raw keys", async () => {
  const translate = translator(await messages("en"));
  for (const message_key of [null, "future.unknown"]) {
    const rendered = renderNotificationMessage(
      {
        title: "Legacy title",
        message: "Legacy body",
        message_key,
        message_params: null,
      },
      translate,
    );
    assert.deepEqual(rendered, { title: "Legacy title", message: "Legacy body" });
    assert.doesNotMatch(`${rendered.title} ${rendered.message}`, /future\.unknown/);
  }
});

test("notification renderer does not change authoritative deep-link payloads", async () => {
  const item = {
    title: "",
    message: "",
    message_key: "withdrawal.approved",
    message_params: { reference: "WD-7" },
    payload: { withdrawal_id: "authoritative-id" },
  };
  renderNotificationMessage(item, translator(await messages("en")));
  assert.deepEqual(item.payload, { withdrawal_id: "authoritative-id" });
});
