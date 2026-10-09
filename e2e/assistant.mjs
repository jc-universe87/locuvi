// AI paths end to end against e2e/fake_anthropic.py (never the real API).
//   python e2e/fake_anthropic.py 8901 &
//   ANTHROPIC_BASE_URL=http://127.0.0.1:8901 <start Locuvi>   (after smoke.mjs set it up)
//   BASE_URL=... LOCUVI_PASSWORD=... node e2e/assistant.mjs
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright");
const BASE = process.env.BASE_URL ?? "http://127.0.0.1:8000";
const SHOTS = process.env.SHOTS;
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
const step = (s) => console.log(`• ${s}`);
await page.goto(`${BASE}/`);
if (await page.getByRole("heading", { name: "Sign in" }).isVisible().catch(() => false)) {
  await page.getByLabel("Password").fill(process.env.LOCUVI_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
}
step("turn on the assistant");
await page.goto(`${BASE}/settings/assistant`);
await page.getByRole("switch").click();
await page.getByLabel("Anthropic API key").fill("sk-ant-e2e-fake-key-0000000000000000000000");
await page.getByRole("button", { name: "Save" }).click();
await page.getByText("Assistant is on").waitFor();
if (await page.getByText("sk-ant-e2e").count()) throw new Error("key echoed");

step("paste a booking -> AI suggestion, clearly labelled");
await page.goto(`${BASE}/diary`);
await page.getByRole("button", { name: "Paste a booking" }).click();
await page.getByLabel("Booking email or message").fill("Could you do 1st Dec morning and 2nd Dec afternoon?");
await page.getByRole("button", { name: "Read booking" }).click();
await page.getByText("Suggested by the assistant — please check").waitFor();
await page.getByRole("dialog").getByRole("button", { name: "Add 2 sessions" }).click();
await page.getByRole("status").getByText("Added 2 sessions").waitFor();

step("ask Locuvi");
await page.getByRole("link", { name: "Ask Locuvi" }).click();
await page.getByRole("button", { name: "Check all my outstanding admin" }).click();
await page.getByText("Your records look up to date.").waitFor();
await page.getByText(/Looked at: overview, uninvoiced sessions/).waitFor();
if (SHOTS) await page.screenshot({ path: `${SHOTS}/20-ask.png`, fullPage: true });
await browser.close();
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log("Assistant e2e passed");
