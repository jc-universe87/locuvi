// Phone app: records stay on the device when the app is closed and opened again.
//
//   BASE_URL=http://127.0.0.1:8790 node e2e/pocket-keeps.mjs   (the pocket build, served)
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const BASE = process.env.BASE_URL ?? "http://127.0.0.1:8790";
const profile = mkdtempSync(join(tmpdir(), "locuvi-phone-"));
const opts = { viewport: { width: 390, height: 844 }, ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) };

async function open() {
  const ctx = await chromium.launchPersistentContext(profile, opts);
  const page = ctx.pages()[0] ?? (await ctx.newPage());
  await page.goto(`${BASE}/#/settings/you`);
  await page.getByLabel("Telephone").waitFor({ timeout: 120000 });
  return { ctx, page };
}

let { ctx, page } = await open();
console.log("• first start: type a phone number (saves itself)");
await page.getByLabel("Telephone").fill("07700 900000");
await page.getByText("✓ Saved").waitFor();
await page.waitForTimeout(1500); // the copy to the phone's storage follows each change
await ctx.close();

console.log("• open again: the number is still there");
({ ctx, page } = await open());
await page.waitForFunction(() => (document.querySelector("#you-phone, input[autocomplete=tel]") ?? null) !== null, null, { timeout: 5000 }).catch(() => {});
const value = await page.getByLabel("Telephone").inputValue();
await ctx.close();
if (value !== "07700 900000") throw new Error(`records were not kept: got "${value}"`);
console.log("Phone app keeps records: passed");
