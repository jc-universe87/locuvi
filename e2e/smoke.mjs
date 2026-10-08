// UI smoke test: drives the real app through the key acceptance flow with fictional data.
//
//   BASE_URL=http://127.0.0.1:8000 LOCUVI_PASSWORD=... SHOTS=./shots node e2e/smoke.mjs
//
// Requires the `playwright` package (npm i -g playwright, or NODE_PATH to an install)
// and a Chromium build (PLAYWRIGHT_BROWSERS_PATH or CHROMIUM_PATH).
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";

// require() honours NODE_PATH, so a global playwright install works too.
const { chromium } = createRequire(import.meta.url)("playwright");

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:8000";
const PASSWORD = process.env.LOCUVI_PASSWORD;
const SHOTS = process.env.SHOTS;
if (SHOTS) mkdirSync(SHOTS, { recursive: true });

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
);
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
const shot = async (name, p = page) => SHOTS && p.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
const step = (s) => console.log(`• ${s}`);
process.on("unhandledRejection", async (e) => {
  console.error(e);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/FAILED.png`, fullPage: true }).catch(() => {});
  process.exit(1);
});

await page.goto(`${BASE}/`);
if (await page.getByRole("heading", { name: "Sign in" }).isVisible().catch(() => false)) {
  step("sign in");
  await shot("00-login");
  await page.getByLabel("Password").fill(PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
}
await page.getByRole("heading", { name: "Invoices" }).waitFor();
await shot("01-invoices-empty");

step("settings: sender & bank (fictional)");
await page.getByRole("link", { name: "Settings" }).click();
await page.getByLabel("Legal name").fill("Dr Alex Example");
await page.getByLabel("Professional label").fill("General Practitioner (Locum)");
await page.getByLabel("Address", { exact: true }).fill("1 Sample Street\nExampletown");
await page.getByLabel("Postcode").fill("EX1 1AA");
await page.getByLabel("Email").fill("alex@example.invalid");
await page.getByLabel("Account name").fill("Dr Alex Example");
await page.getByLabel("Sort code").fill("00-00-00");
await page.getByLabel("Account number").fill("00000000");
await page.locator("#sender").getByRole("button", { name: "Save" }).click();
await page.locator("#sender").getByRole("status").waitFor();
await shot("02-settings");

step("practice");
await page.getByRole("link", { name: "Practices" }).click();
await page.getByRole("button", { name: "+ Add practice" }).click();
await page.getByLabel("Practice name").fill("Example Medical Practice");
await page.getByLabel("Billing address").fill("2 Test Road\nSampleford\nSF1 2BB");
await page.getByLabel(/Usual rate/).fill("600.00");
await page.getByRole("button", { name: "Save" }).click();
await page.getByRole("cell", { name: /Example Medical Practice/ }).waitFor();
await shot("03-practices");

step("new invoice with two October sessions");
await page.getByRole("link", { name: "Invoices" }).first().click();
await page.getByRole("link", { name: /New invoice/ }).click();
await page.getByLabel("Practice", { exact: true }).selectOption({ label: "Example Medical Practice" });
await page.getByLabel("Issue date").fill("2026-10-20");
await page.getByRole("button", { name: /Add next date/ }).click();
await page.locator("#d0").fill("2026-10-08");
await page.getByRole("button", { name: /Add next date/ }).click();
await page.locator("#d1").fill("2026-10-15");
await page.locator("#u1").selectOption("pm");
await page.locator("#desc1").fill("GP locum PM session");
await page.locator("#r1").fill("550.00");
const summary = page.locator("aside.summary");
await summary.getByText("£1,298.83").waitFor();
await summary.getByText("£148.83").waitFor();
await shot("04-editor");

step("multi-month guard");
await page.locator("#d1").fill("2026-11-02");
await summary.getByText(/more than one calendar month/).waitFor();
await page.locator("#d1").fill("2026-10-15");
await summary.getByText(/more than one calendar month/).waitFor({ state: "detached" });

step("save draft, preview has no number");
await page.getByRole("button", { name: "Save draft" }).click();
await page.getByRole("status").getByText("Saved").waitFor();

step("issue & download");
await page.getByRole("button", { name: "Issue & download" }).first().click();
const dialog = page.getByRole("dialog");
await dialog.getByText("Number to be allocated: LOC-2026-0001").waitFor();
await shot("05-issue-confirm");
const [download] = await Promise.all([
  page.waitForEvent("download"),
  dialog.getByRole("button", { name: "Issue invoice" }).click(),
]);
if (download.suggestedFilename() !== "LOC-2026-0001.pdf") throw new Error(`bad filename ${download.suggestedFilename()}`);
await page.getByRole("heading", { name: "Invoice LOC-2026-0001" }).waitFor();
await page.locator(".badge", { hasText: "PDF saved locally" }).waitFor();
await shot("06-detail");

step("issued invoice listed");
await page.getByRole("link", { name: "Invoices" }).first().click();
await page.getByRole("link", { name: "LOC-2026-0001" }).first().waitFor();
await shot("07-invoices-list");

step("mobile layout");
const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
await mobile.addCookies(await ctx.cookies());
const mp = await mobile.newPage();
await mp.goto(`${BASE}/invoices`);
await mp.locator(".cards").getByText("LOC-2026-0001").waitFor();
const overflow = await mp.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
if (overflow) throw new Error("horizontal overflow on mobile invoices list");
await shot("08-mobile-invoices", mp);
await mp.goto(`${BASE}/invoices/new`);
await mp.getByRole("button", { name: /Add next date/ }).click();
await mp.locator(".mobile-total").waitFor();
await shot("09-mobile-editor", mp);

await browser.close();
if (errors.length) {
  console.error("Browser errors:\n" + errors.join("\n"));
  process.exit(1);
}
console.log("UI smoke test passed");
