// The phone app syncs with a computer through Nextcloud (a stand-in: e2e/fake_nextcloud.py).
//
//   PHONE_URL=http://127.0.0.1:8790 DESKTOP_URL=http://127.0.0.1:8793 \
//   NC_DESKTOP=http://127.0.0.1:8791 NC_PHONE=https://nextcloud.example.invalid:8792 \
//   [NC_NO_CORS=https://nextcloud.example.invalid:8795] node e2e/pocket-sync.mjs
//
//   or, in the Android app on an emulator: ANDROID=1 NC_PHONE_HOME=http://10.0.2.2:8791 …
//
// DESKTOP_URL is a Locuvi on a computer (gateway sign-in), NC_DESKTOP the address it uses.
// The phone joins through Settings › Sync like a person would, using NC_PHONE:
// - in a browser (iPhone and iPad): the stand-in allows the phone app's address (CORS), and
//   NC_NO_CORS, which doesn't, must give a clear message instead (the browser is told that
//   nextcloud.example.invalid is this computer);
// - with ANDROID=1, inside the Android app (a test build on the emulator), where the app makes
//   the connection itself, so no CORS is needed. There NC_PHONE is an address that doesn't
//   answer and NC_PHONE_HOME a plain http:// home network address, which sync then uses.
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";

const { chromium, request } = createRequire(import.meta.url)("playwright");
const SHOTS = process.env.SHOTS;
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const USER = "alex";
const APP_PASSWORD = "fixture-app-password";
const step = (s) => console.log(`• ${s}`);

// ---------------------------------------------------------------- the computer, by its API
const desk = await request.newContext({ baseURL: process.env.DESKTOP_URL });
const csrf = (await (await desk.get("/api/v1/auth/session")).json()).csrf_token;
async function call(method, url, data) {
  const r = await desk.fetch(`/api/v1${url}`, { method, data, headers: { "X-CSRF-Token": csrf } });
  const body = await r.json();
  if (!r.ok()) throw new Error(`${method} ${url}: ${r.status()} ${JSON.stringify(body)}`);
  return body;
}

step("computer: a practice, then start syncing through Nextcloud");
await call("POST", "/practices", { name: "Example Surgery", billing_address: "1 Example Road\nSF1 1AA", default_rate: "300.00" });
const started = await call("POST", "/sync/start", {
  kind: "nextcloud", url: process.env.NC_DESKTOP, username: USER, password: APP_PASSWORD, device_name: "Laptop",
});
const code = started.code;

// ---------------------------------------------------------------- the phone, by its screens
let browser, page, device;
if (process.env.ANDROID) {
  // the Android app's own WebView (a test build on the emulator, through adb)
  const { _android } = createRequire(import.meta.url)("playwright");
  [device] = await _android.devices();
  const webview = await device.webView({ pkg: "uk.locuvi.app" });
  page = await webview.page();
  await page.evaluate(() => (location.hash = "#/settings/sync"));
} else {
  browser = await chromium.launch({
    args: ["--host-resolver-rules=MAP nextcloud.example.invalid 127.0.0.1"],
    ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
  });
  // the stand-in's certificate is made on the spot; a real Nextcloud has a proper one
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, ignoreHTTPSErrors: true });
  page = await ctx.newPage();
  await page.goto(`${process.env.PHONE_URL}/#/settings/sync`);
}
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
if (process.env.SHOW_CONSOLE) page.on("console", (m) => console.log(`  [${m.type()}] ${m.text()}`));
await page.getByRole("heading", { name: "Sync and backup file" }).waitFor({ timeout: 180000 });

async function join(address, home = "") {
  await page.getByLabel("Nextcloud address").fill(address);
  await page.getByLabel("Address at home or work (optional)").fill(home);
  await page.getByLabel("Nextcloud user name").fill(USER);
  await page.getByLabel("App password").fill(APP_PASSWORD);
  await page.getByLabel("Name for this device").fill("Phone");
  await page.getByLabel("Sync code from your other device").fill(code);
  await page.getByRole("button", { name: "Join and sync" }).click();
}

step("phone: Join, with Nextcloud already chosen (the only way on a phone)");
await page.getByRole("button", { name: "Join from another device" }).click();
if (!(await page.getByRole("radio", { name: /Nextcloud/ }).isChecked())) throw new Error("Nextcloud not chosen");
if (process.env.NC_NO_CORS) {
  step("a Nextcloud that doesn't allow Locuvi: a clear message, nothing changes");
  await join(process.env.NC_NO_CORS);
  await page.getByRole("button", { name: "Join and sync" }).waitFor({ timeout: 60000 });
  const said = await page.getByRole("alert").allInnerTexts();
  if (!said.some((s) => s.includes("must also allow Locuvi"))) throw new Error(`unexpected message: ${said.join(" | ")}`);
}
await join(process.env.NC_PHONE, process.env.NC_PHONE_HOME);
await page.getByText("Syncing with").waitFor({ timeout: 120000 }).catch(async (e) => {
  SHOTS && (await page.screenshot({ path: `${SHOTS}/phone-sync-failed.png`, fullPage: true }));
  throw new Error(`did not join: ${(await page.getByRole("alert").allInnerTexts()).join(" | ") || e.message}`);
});
SHOTS && (await page.screenshot({ path: `${SHOTS}/phone-sync-joined.png`, fullPage: true }));

step("the computer's practice is on the phone");
await page.evaluate(() => (location.hash = "#/settings/practices"));
await page.getByText("Example Surgery").first().waitFor({ timeout: 30000 });

step("phone: a change, Sync now, and the computer has it");
await page.evaluate(() => (location.hash = "#/settings/you"));
await page.getByLabel("Telephone").fill("07700 900000");
await page.getByText("✓ Saved").waitFor();
await page.evaluate(() => (location.hash = "#/settings/sync"));
await page.getByRole("button", { name: "Sync now" }).click();
await page.getByRole("button", { name: "Sync now" }).waitFor({ timeout: 60000 });
await page.getByText("Syncing with").waitFor();
if (await page.getByRole("alert").count()) throw new Error(`sync said: ${await page.getByRole("alert").first().innerText()}`);
await call("POST", "/sync/now");
const profile = await call("GET", "/settings/profile");
if (!JSON.stringify(profile).includes("07700 900000")) throw new Error("the phone's change did not reach the computer");

if (errors.length) throw new Error(`page errors: ${errors.join("; ")}`);
if (device) await device.close();
else await browser.close();
await desk.dispose();
console.log("Phone sync through Nextcloud: passed");
