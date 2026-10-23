// Sync between two devices, through the Settings screens, with fictional data.
//
//   OPEN_A=<laptop's /desktop/open link> OPEN_B=<phone's> SHOTS=./shots node e2e/sync.mjs
//
// Both are fresh desktop apps (desktop/locuvi_desktop.py --headless) whose home folder has a
// "Dropbox" folder, standing for any folder a cloud app keeps in step.
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const SHOTS = process.env.SHOTS;
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const step = (s) => console.log(`• ${s}`);

async function device(open) {
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(open);
  await page.waitForLoadState("networkidle");
  const call = (method, url, body) =>
    page.evaluate(async ([method, url, body]) => {
      const s = await (await fetch("/api/v1/auth/session")).json();
      const r = await fetch(`/api/v1${url}`, {
        method, headers: { "Content-Type": "application/json", "X-CSRF-Token": s.csrf_token },
        body: body ? JSON.stringify(body) : undefined,
      });
      return r.json();
    }, [method, url, body]);
  return { page, call, errors };
}

async function setUp(dev, mode, name, code) {
  const { page } = dev;
  await page.goto(new URL("/settings/sync", page.url()).href);
  await page.getByRole("heading", { name: "Sync and backup file" }).waitFor();
  await page.getByRole("button", { name: mode === "start" ? "Start syncing from this device" : "Join from another device" }).click();
  await page.getByRole("radio", { name: /^Dropbox(?! account)/ }).check();
  await page.getByLabel("Name for this device").fill(name);
  if (code) await page.getByLabel("Sync code from your other device").fill(code);
  await page.getByRole("button", { name: mode === "start" ? "Start syncing" : "Join and sync" }).click();
  await page.getByText("Syncing with").waitFor();
}

step("laptop: start syncing into the Dropbox folder, and get a code");
const laptop = await device(process.env.OPEN_A);
await laptop.call("POST", "/practices", { name: "Example Surgery", billing_address: "1 Example Road\nSF1 1AA", default_rate: "300.00" });
await setUp(laptop, "start", "Laptop");
const code = (await laptop.page.locator(".alert.ok p").innerText()).trim();
if (!/^[A-Z2-9]{4}(-[A-Z2-9]{4}){4}$/.test(code)) throw new Error(`no sync code shown: ${code}`);
SHOTS && (await laptop.page.screenshot({ path: `${SHOTS}/sync-started.png`, fullPage: true }));

step("phone: join with the code, and the laptop's practice arrives");
const phone = await device(process.env.OPEN_B);
await setUp(phone, "join", "Phone", code.toLowerCase());
const onPhone = await phone.call("GET", "/practices");
if (!JSON.stringify(onPhone).includes("Example Surgery")) throw new Error("practice did not reach the phone");
SHOTS && (await phone.page.screenshot({ path: `${SHOTS}/sync-joined.png`, fullPage: true }));

step("phone adds a practice; the laptop gets it with Sync now");
await phone.call("POST", "/practices", { name: "Example Health Centre", billing_address: "2 Test Lane\nSF1 1AA", default_rate: "320.00" });
await phone.call("POST", "/sync/now");
await laptop.page.reload();
await laptop.page.getByRole("button", { name: "Sync now" }).click();
await laptop.page.getByRole("button", { name: "Sync now" }).waitFor();
const onLaptop = await laptop.call("GET", "/practices");
if (!JSON.stringify(onLaptop).includes("Example Health Centre")) throw new Error("practice did not reach the laptop");

step("everything in one file");
await laptop.page.getByLabel("Password for the file").first().fill("a long export passphrase");
const [dl] = await Promise.all([laptop.page.waitForEvent("download"), laptop.page.getByRole("button", { name: "Download everything" }).click()]);
if (!dl.suggestedFilename().endsWith(".locuvi")) throw new Error(`unexpected file ${dl.suggestedFilename()}`);

const errors = [...laptop.errors, ...phone.errors];
if (errors.length) throw new Error(`page errors: ${errors.join("; ")}`);
await browser.close();
console.log("Sync test passed");
