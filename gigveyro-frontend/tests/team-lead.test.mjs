import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "vitest";

const source = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("team_lead role is wired into dashboard navigation without any owner-only routes", async () => {
  const shell = await source("src/components/layout/dashboard-shell.tsx");
  assert.match(shell, /team_lead: \[/);
  const teamLeadBlock = shell.slice(shell.indexOf("team_lead: ["), shell.indexOf("};", shell.indexOf("team_lead: [")));
  assert.doesNotMatch(teamLeadBlock, /\/owner\//);
  assert.match(teamLeadBlock, /\/team_lead\/team/);
  assert.match(teamLeadBlock, /\/team_lead\/profit/);
  assert.match(teamLeadBlock, /\/team_lead\/withdrawals/);
});

test("team_lead layout gates on role=\"team_lead\" via the same RoleGate every other role uses", async () => {
  const layout = await source("src/app/team_lead/layout.tsx");
  assert.match(layout, /<RoleGate role="team_lead">/);
  assert.match(layout, /<DashboardShell role="team_lead">/);
});

test("team lead API client scopes every call under /team-lead, never /owner", async () => {
  const client = await source("src/lib/api/team-lead.ts");
  assert.match(client, /\/team-lead\/dashboard/);
  assert.match(client, /\/team-lead\/team\?/);
  assert.match(client, /\/team-lead\/deals\?/);
  assert.match(client, /\/team-lead\/withdrawals/);
  assert.doesNotMatch(client, /\/owner\//);
});

test("deals page component role prop excludes team_lead (team lead never uses the shared Deals cabinet)", async () => {
  const component = await source("src/components/deals/deals-page.tsx");
  assert.match(component, /role: Exclude<UserRole, "team_lead">/);
});

test("team lead translation keys exist in RU/TG/EN", async () => {
  const catalogs = await Promise.all(["ru", "tg", "en"].map(async (locale) => JSON.parse(await source(`src/i18n/messages/${locale}.json`))));
  for (const catalog of catalogs) {
    assert.ok(catalog.roles.team_lead);
    assert.ok(catalog.enums.role.team_lead);
    assert.ok(catalog.navigation.team);
    assert.ok(catalog.navigation.profit);
    assert.ok(catalog.navigation.teamLeadWithdrawals);
    assert.ok(catalog.dashboard.teamLeadTitle);
    assert.ok(catalog.teamLead.teamTitle);
    assert.ok(catalog.teamLead.profitTitle);
    assert.ok(catalog.teamLead.withdrawalTitle);
    assert.ok(catalog.teamLead.ownerWithdrawalsTitle);
    assert.ok(catalog.accounts.assignedTeamLead);
  }
});

test("owner account detail page never exposes team lead assignment controls to non-USER accounts", async () => {
  const page = await source("src/app/owner/accounts/[accountId]/page.tsx");
  assert.match(page, /isUser &&.*<div className=\{styles\.userOperations\}>\s*\n\s*<article>\s*\n\s*<span>\{t\("teamLeadEyebrow"\)\}/);
});
