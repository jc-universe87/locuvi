// Screenshots for the user guide (docs/images), taken from the fictional data that
// e2e/smoke.mjs and e2e/assistant.mjs leave behind. Run those first, on a fresh instance:
//
//   BASE_URL=http://127.0.0.1:8000 LOCUVI_PASSWORD=... SHOTS=./shots node e2e/docs-shots.mjs
//
// UK date formats and London time; waits for pop-up messages to clear before each picture.
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const BASE = process.env.BASE_URL ?? "http://127.0.0.1:8000";
const SHOTS = process.env.SHOTS ?? "./shots";
mkdirSync(SHOTS, { recursive: true });

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
);
const common = { locale: "en-GB", timezoneId: "Europe/London", colorScheme: "light" };
const ctx = await browser.newContext({ ...common, viewport: { width: 1200, height: 820 } });
const page = await ctx.newPage();

const settle = async (p = page) => {
  await p.waitForLoadState("networkidle").catch(() => {});
  await p.waitForTimeout(400);
  await p.locator(".toast").first().waitFor({ state: "detached", timeout: 8000 }).catch(() => {});
};
const shot = async (name, p = page, opts = {}) => {
  await settle(p);
  await p.screenshot({ path: `${SHOTS}/docs-${name}.png`, fullPage: true, ...opts });
  console.log(`• ${name}`);
};
const visit = async (path, name) => {
  await page.goto(`${BASE}${path}`);
  await shot(name);
};

await page.goto(`${BASE}/`);
await shot("sign-in");
const who = page.getByLabel("Your name");
if (await who.isVisible().catch(() => false)) await who.fill("Owner");
await page.getByLabel("Password").fill(process.env.LOCUVI_PASSWORD ?? "");
await page.getByRole("button", { name: "Sign in" }).click();
await page.getByRole("heading", { name: "Sign in" }).waitFor({ state: "detached" });

await visit("/", "today");

await page.goto(`${BASE}/diary`);
await settle();
// show a month that has sessions in it
for (let i = 0; i < 3 && !(await page.locator(".cal .day .s").count()); i++) {
  const prev = page.getByRole("button", { name: "Previous month" });
  if (!(await prev.count())) break;
  await prev.first().click();
  await settle();
}
await shot("diary");

await page.getByRole("button", { name: "Add bookings from a message" }).click();
await page.getByLabel("Email or message confirming your work").fill(
  "Hi Alex, thanks for covering. Confirming Tuesday 3 November AM and Thursday 5 November PM " +
    "at Example Medical Practice, £600 per session. Best wishes, Practice Manager",
);
await page.getByRole("button", { name: "Find work dates" }).click();
await page.getByRole("dialog").getByText(/Suggested by AI|Found/).first().waitFor();
await shot("booking-review", page, { fullPage: false });
await page.keyboard.press("Escape");

await visit("/invoices", "invoices");
await page.locator("a[href^='/invoices/']:not([href='/invoices/new'])").first().click();
await page.locator(".inv-hero").waitFor();
await shot("invoice");

await visit("/pension", "pension");
const month = page.locator("button, a").filter({ hasText: /September 2026/ }).first();
if (await month.count()) {
  await month.click();
  await page.getByRole("dialog").waitFor();
  await shot("pension-month", page, { fullPage: false });
  await page.keyboard.press("Escape");
}

await visit("/reports", "reports");
await visit("/inbox", "inbox");
await visit("/bank", "bank");
await visit("/ask", "ask");
await visit("/settings", "settings");
for (const s of ["personalisation", "assistant", "mailbox", "profiles", "trash", "calendar"]) {
  await visit(`/settings/${s}`, `settings-${s}`);
}

const mobile = await browser.newContext({
  ...common, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2,
});
await mobile.addCookies(await ctx.cookies());
const mp = await mobile.newPage();
for (const [path, name] of [["/", "today"], ["/diary", "diary"], ["/invoices", "invoices"], ["/pension", "pension"]]) {
  await mp.goto(`${BASE}${path}`);
  await mp.locator(".tabbar").waitFor();
  await shot(`mobile-${name}`, mp, { fullPage: false });
}
await browser.close();
console.log("Docs screenshots saved");
