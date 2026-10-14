import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function login(page: Page, subject: string) {
  await page.goto("/login");
  await page.getByLabel("Demo user").selectOption(subject);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Election overview" })).toBeVisible();
}

async function axe(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
}

test("unconnected U.S. sources are shown as unavailable, never substituted", async ({ page }) => {
  await login(page, "demo-viewer");
  await expect(page.getByText(/data source\(s\) for United States are not connected/)).toBeVisible();
  await expect(page.getByText("No contests are loaded for this cycle.")).toBeVisible();
  await expect(page.getByText("2 U.S.C. 7", { exact: false })).toBeVisible();
  await axe(page);
});

test("explorer -> contest detail shows status, history, provenance and no automatic call", async ({ page }) => {
  await login(page, "demo-analyst");
  await page.getByRole("link", { name: "Contests & districts", exact: true }).click();
  await expect(page.getByText("SYNTHETIC DEMO DATA.")).toBeVisible();
  await expect(page.getByRole("group", { name: "District map" })).toBeVisible();
  await axe(page);
  await page.getByRole("link", { name: "Assembly NM-03 (2024)", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Assembly NM-03 (2024)" })).toBeVisible();
  await expect(page.getByText("Correction:", { exact: false })).toBeVisible();
  await expect(page.getByText("No race call recorded.")).toBeVisible();
  await expect(page.getByRole("table").filter({ hasText: "Every published snapshot" })).toContainText("preliminary");
  await page.getByRole("button", { name: "Show data table" }).first().click();
  await expect(page.getByRole("table").first()).toBeVisible();
  await axe(page);
});

test("assistant answers with citations and refuses individual profiling", async ({ page }) => {
  await login(page, "demo-analyst");
  await page.getByRole("link", { name: "Research assistant", exact: true }).click();
  await page.getByLabel("Question").fill("What were the 2024 results in NM-03 in the Synthetic Federation?");
  await page.getByRole("button", { name: "Ask" }).click();
  const answer = page.locator("article").first();
  await expect(answer).toContainText("[E1]");
  await expect(answer).toContainText("SYNTHETIC DEMO DATA");
  await expect(answer).toContainText("grounding passed");
  await page.getByLabel("Question").fill("How did my neighbor vote?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.locator("article").first()).toContainText("can't infer");
  await axe(page);
});

test("report editorial workflow: draft, review by another user, publish, synthetic blocked", async ({ page, browser }) => {
  await login(page, "demo-analyst");
  await page.getByRole("link", { name: "Reports", exact: true }).click();
  await page.getByLabel("New report title").fill("E2E brief " + Date.now());
  await page.getByRole("button", { name: "Create draft" }).click();
  await page.getByLabel("Body (Markdown)").fill("Synthetic district results summary.");
  await page.getByLabel("Methodology").fill("Compared certified snapshots.");
  await page.getByLabel("Uncertainty").fill("Certified totals; no sampling error.");
  await page.getByLabel(/Synthetic demo generator/).check();
  await page.getByRole("button", { name: "Save version" }).click();
  await expect(page.getByText("Cites SYNTHETIC data")).toBeVisible();
  await page.getByRole("button", { name: "Submit for review" }).click();
  await expect(page.getByText("in_review")).toBeVisible();
  const url = page.url();

  const reviewer = await (await browser.newContext()).newPage();
  await login(reviewer, "demo-reviewer");
  await reviewer.goto(url);
  await reviewer.getByLabel("Review comment").fill("Checked against sources.");
  await reviewer.getByRole("button", { name: "Approve" }).click();
  await reviewer.getByRole("button", { name: "Publish" }).click();
  await expect(reviewer.getByRole("alert").filter({ hasText: "publication blocked" })).toContainText("SYNTHETIC");
  await axe(reviewer);
});

test("viewer sees restricted states; forecast gates are visible", async ({ page }) => {
  await login(page, "demo-viewer");
  await page.getByRole("link", { name: "Administration", exact: true }).click();
  await expect(page.getByText("Administration requires the admin role.")).toBeVisible();
  await page.getByRole("link", { name: "Research assistant", exact: true }).click();
  await expect(page.getByText("does not include the research assistant")).toBeVisible();
  await page.getByRole("link", { name: "Forecasts & methodology", exact: true }).click();
  await expect(page.getByText("published only when every gate passes")).toBeVisible();
  await axe(page);
});

test("source registry documents remediation for every unavailable source", async ({ page }) => {
  await login(page, "demo-viewer");
  await page.getByRole("link", { name: "Source registry", exact: true }).click();
  await expect(page.getByRole("heading", { name: /OpenFEC API/ })).toBeVisible();
  const unavailable = page.locator(".banner.warn");
  expect(await unavailable.count()).toBeGreaterThanOrEqual(5);
  await expect(unavailable.first()).toContainText("Remediation:");
  await axe(page);
});
