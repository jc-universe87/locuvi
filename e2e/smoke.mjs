// UI smoke test: the owner's whole month, with fictional data, on a FRESH instance.
//
//   BASE_URL=http://127.0.0.1:8000 LOCUVI_PASSWORD=... SHOTS=./shots node e2e/smoke.mjs
//
// Requires `playwright` (a global install works via NODE_PATH) and Chromium
// (PLAYWRIGHT_BROWSERS_PATH or CHROMIUM_PATH).
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { deflateSync } from "node:zlib";

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

// A tiny solid-colour PNG, built here so the test needs no image files.
function makePng(w, h, [r, g, b]) {
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf) => {
    let c = 0xffffffff;
    for (const x of buf) c = crcTable[(c ^ x) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type), data]);
    const sum = Buffer.alloc(4);
    sum.writeUInt32BE(crc(body));
    return Buffer.concat([len, body, sum]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr.set([8, 2, 0, 0, 0], 8); // 8-bit RGB
  const row = Buffer.concat([Buffer.from([0]), Buffer.from(Array.from({ length: w }, () => [r, g, b]).flat())]);
  const raw = Buffer.concat(Array.from({ length: h }, () => row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw)), chunk("IEND", Buffer.alloc(0)),
  ]);
}
process.on("unhandledRejection", async (e) => {
  console.error(e);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/FAILED.png`, fullPage: true }).catch(() => {});
  process.exit(1);
});
const fail = async (msg) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/FAILED.png`, fullPage: true }).catch(() => {});
  throw new Error(msg);
};

await page.goto(`${BASE}/`);
if (await page.getByRole("heading", { name: "Sign in" }).isVisible().catch(() => false)) {
  step("sign in");
  await page.getByLabel("Password").fill(PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("heading", { name: "Sign in" }).waitFor({ state: "detached" });
}

step("welcome wizard (3 steps)");
await page.getByRole("heading", { name: "Let's set up your invoices" }).waitFor();
await shot("01-welcome");
await page.getByLabel("Legal name").fill("Dr Alex Example");
await page.getByLabel("Address").fill("1 Sample Street\nExampletown");
await page.getByLabel("Postcode").fill("ex1 1aa");
await page.getByLabel("Email").fill("alex@example.invalid");
await page.getByRole("button", { name: "Continue" }).click();
await page.getByRole("heading", { name: "Where practices should pay you" }).waitFor();
if ((await page.getByLabel("Name on bank account").inputValue()) !== "Dr Alex Example") await fail("account name not prefilled");
await page.getByLabel("Sort code").fill("00-00-00");
await page.getByLabel("Account number").fill("00000000");
await page.getByRole("button", { name: "Continue" }).click();
await page.getByRole("heading", { name: "Add your first practice" }).waitFor();
await page.getByLabel("Practice name").fill("Example Medical Practice");
await page.getByLabel("Billing address").fill("2 Test Road\nSampleford\nSF1 2BB");
await page.getByLabel("Agreed fee per session (£)").fill("600.00");
await shot("02-welcome-practice");
await page.getByRole("button", { name: "Get started" }).click();

step("today: greeting and caught up");
await page.getByRole("heading", { name: /Alex$/ }).waitFor();
await page.getByText("Nothing needs your attention").waitFor();
await shot("03-today-empty");

step("diary: tap three days last month");
await page.getByRole("link", { name: "Diary" }).first().click();
await page.getByText(/Tap a day to add/).waitFor();
await page.getByRole("button", { name: "Previous month" }).click();
const prevMonth = await page.locator(".month-nav h2").innerText();
const cell = (d) => page.locator(".day:not(.out)").nth(d - 1);
await cell(1).click();
await page.getByText(/^Added AM/).waitFor();
await cell(8).click();
await page.getByRole("group", { name: "Type of work" }).getByRole("button", { name: "PM" }).click();
await page.getByRole("button", { name: /£600.00/ }).waitFor(); // remembered rate
await cell(9).click();
await page.locator("#h-month").waitFor();
await page.getByText("3 sessions · £1,800.00 · not yet invoiced").waitFor();
await shot("04-diary");

step("today: month ready to invoice -> create invoice");
await page.getByRole("link", { name: "Today" }).first().click();
await page.getByText(`You can invoice for ${prevMonth}`).waitFor();
await shot("05-today-ready");
await page.getByRole("button", { name: "Create invoice" }).click();
await page.getByRole("heading", { name: "Draft invoice" }).waitFor();
const summary = page.locator("aside.summary");
await summary.getByText("£2,032.96").waitFor(); // 1800 -> 1620 -> 232.956 -> 232.96
await shot("06-editor");

step("preview opens in a new tab (not blocked as a pop-up)");
// Headless Chromium has no PDF viewer, so the PDF either renders (blob: URL) or downloads.
// Listen before clicking: the preview can arrive very quickly.
const previewShown = new Promise((resolve) => {
  ctx.once("page", (pg) => {
    pg.once("download", resolve);
    pg.waitForURL(/^blob:/, { waitUntil: "commit" }).then(resolve, () => {});
  });
});
const [popup] = await Promise.all([
  page.waitForEvent("popup"),
  page.getByRole("button", { name: "View PDF before issuing" }).click(),
]);
await Promise.race([previewShown, page.waitForTimeout(15000).then(() => fail("preview did not open"))]);
await popup.close().catch(() => {});

step("issue & download");
await page.getByRole("button", { name: "Issue invoice and download" }).first().click();
const dialog = page.getByRole("dialog");
await dialog.getByText("Invoice number: LOC-").waitFor();
const [download] = await Promise.all([
  page.waitForEvent("download"),
  dialog.getByRole("button", { name: "Issue invoice" }).click(),
]);
if (!/^LOC-\d{4}-0001\.pdf$/.test(download.suggestedFilename())) await fail(`bad filename ${download.suggestedFilename()}`);
const invoiceNumber = download.suggestedFilename().replace(/\.pdf$/, "");
await page.locator(".inv-hero .amount", { hasText: "£2,032.96" }).waitFor();
await page.locator(".pill", { hasText: /^Payment due / }).waitFor();
await shot("07-detail");

step("mark paid (one tap, undo available)");
await page.getByRole("button", { name: "Record as paid" }).click();
await page.getByRole("status").getByText(/Payment recorded for/).waitFor();
await page.locator(".inv-hero .pill", { hasText: "Paid" }).waitFor();
await shot("08-paid");

step("email sheet asks to set up email");
await page.getByRole("button", { name: "Send" }).click();
await page.getByRole("dialog").getByText("Connect your email account once. Then you can email an invoice with one click.").waitFor();
await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

step("pension: Form A for the work month, Form B for the month the fee was received");
await page.getByRole("link", { name: "Pension" }).first().click();
const row = page.locator(".list-row", { hasText: prevMonth });
await row.getByText(/1 Form A/).waitFor();
await row.click();
await page.getByRole("dialog").getByText("£1,620.00").first().waitFor();
const [ws] = await Promise.all([
  page.waitForEvent("download"),
  page.getByRole("dialog").getByRole("button", { name: "Download figures" }).click(),
]);
if (!ws.suggestedFilename().startsWith("nhs-pension-worksheet-")) await fail("worksheet name");
await page.getByRole("dialog").getByRole("group", { name: "Has the practice signed Form A?" }).getByRole("button", { name: "Signed by practice" }).click();
await page.getByRole("dialog").getByText(/^Signed on \d/).waitFor();
await page.getByRole("dialog").getByText("No payment for NHS pensionable work was recorded this month.").waitFor();
await shot("09-pension-month");
await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
await row.getByText(/1 signed/).waitFor();
// paid today: this month's Form B lists it, with the 7th-of-next-month deadline
const thisMonth = new Date().toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "Europe/London" });
const recRow = page.locator(".list-row", { hasText: thisMonth });
await recRow.getByText(/Received £1,620\.00 · Form B due/).waitFor();
step("pension guide explains Forms A and B and links to PCSE");
await page.getByRole("button", { name: "How to send your pension forms" }).click();
const guide = page.getByRole("dialog", { name: "How to send your NHS pension forms" });
await guide.getByRole("heading", { name: "Before your first month (once only)" }).waitFor();
const pcse = await guide.getByRole("link", { name: "Open the PCSE page for locum GPs" }).getAttribute("href");
if (!pcse?.startsWith("https://pcse.england.nhs.uk/")) await fail("PCSE link");
await shot("09b-pension-guide");
await guide.getByRole("button", { name: "Close" }).last().click();

step("reports");
await page.getByRole("link", { name: "Reports" }).first().click();
await page.locator(".stat", { hasText: "Invoiced" }).getByText("£2,033").waitFor();
await page.locator(".stat", { hasText: "Received" }).getByText("£2,033").waitFor();
await shot("10-reports");

step("today shows findings (backup reminder after first invoice)");
await page.getByRole("link", { name: "Today" }).first().click();
await page.getByRole("heading", { name: "Things to check" }).waitFor();
await page.getByText(/Your records haven't been backed up yet/).waitFor();
await shot("10b-today-findings");
if (await page.getByRole("button", { name: "Back up now" }).isVisible()) {
  await page.getByRole("button", { name: "Back up now" }).click();
  await page.getByText("Backup saved").waitFor();
  await page.getByText(/Your records haven't been backed up yet/).waitFor({ state: "detached" });
}

step("diary: paste a booking -> review -> add (rules engine, no AI)");
await page.getByRole("link", { name: "Diary" }).first().click();
await page.getByRole("button", { name: "Add bookings from a message" }).click();
const next = new Date(Date.now() + 40 * 86400000);
const nm = next.toLocaleDateString("en-GB", { month: "long", timeZone: "Europe/London" });
await page.getByLabel("Email or message confirming your work").fill(
  `Hi Dr Example,\nConfirming locum cover at Example Medical Practice:\n20 ${nm} AM\n21 ${nm} 14:00-18:00\nFee £600 per session.`,
);
await page.getByRole("button", { name: "Find work dates" }).click();
await page.getByText("Found in your message — please check the details").waitFor();
await shot("10c-booking-review");
await page.getByRole("dialog").getByRole("button", { name: "Add 2 sessions" }).click();
await page.getByRole("status").getByText("Added 2 sessions").waitFor();

step("diary: repeating booking (every Wednesday) with undo");
await page.getByRole("button", { name: "Add repeating sessions…" }).click();
await page.getByRole("dialog").getByRole("group", { name: "Days" }).getByRole("button", { name: "Wed" }).click();
const addRepeat = page.getByRole("dialog").getByRole("button", { name: /^Add \d+ sessions?$/ });
await addRepeat.waitFor();
await shot("10c2-repeat");
await addRepeat.click();
await page.getByRole("status").getByText(/^Added \d+ sessions?$/).waitFor();
await page.getByRole("status").getByRole("button", { name: "Undo" }).click();

step("inbox: pasted booking is filed as done; upload a file");
await page.getByRole("link", { name: /^Inbox/ }).click();
await page.getByRole("heading", { name: "Inbox" }).waitFor();
await page.locator("input[type=file]").setInputFiles({
  name: "remittance.txt", mimeType: "text/plain", buffer: Buffer.from(`Remittance advice: BACS payment £2,032.96 for ${invoiceNumber}`),
});
await page.getByText("Added 1 file").waitFor();
await page.getByRole("button", { name: /remittance\.txt/ }).click();
await page.getByRole("dialog").getByText("BACS payment").waitFor();
await shot("10d-inbox-doc");
await page.getByRole("dialog").getByRole("button", { name: "I've dealt with this" }).click();
await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
await page.getByRole("button", { name: "Done" }).click();
await page.getByRole("button", { name: /Locum cover|Hi Dr Example/ }).waitFor();

step("invoice shows its correspondence (remittance linked by number)");
await page.getByRole("link", { name: "Invoices" }).first().click();
await page.getByRole("link", { name: new RegExp(invoiceNumber) }).first().click();
await page.getByRole("heading", { name: "Emails and payment documents" }).waitFor();
await page.getByRole("link", { name: /remittance\.txt/ }).click();
await page.getByRole("dialog").getByText("BACS payment").waitFor();
await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

step("payments in: import a bank statement, mark a non-invoice credit");
await page.getByRole("link", { name: "Invoices" }).first().click();
await page.getByRole("link", { name: "Check bank payments" }).click();
await page.getByRole("heading", { name: "Check bank payments" }).waitFor();
const today = new Date().toLocaleDateString("en-GB", { timeZone: "Europe/London" });
await page.locator("input[type=file]").setInputFiles({
  name: "statement.csv", mimeType: "text/csv",
  buffer: Buffer.from(`Date,Description,Amount\n${today},TAX REFUND,50.00\n${today},COFFEE,-3.20\n`),
});
await page.getByText("Found 1 new payment").waitFor();
await page.getByText("TAX REFUND").waitFor();
if (await page.getByText("COFFEE").count()) await fail("debit should not be stored");
await shot("10e-bank");
await page.getByRole("button", { name: "Not payment for an invoice" }).click();
await page.getByText("No new payments need checking.").waitFor();

step("deleting asks first; Recently deleted can put it back");
await page.getByRole("link", { name: /^Inbox/ }).click();
await page.getByRole("button", { name: "Done" }).click();
await page.getByRole("button", { name: /remittance\.txt/ }).click();
await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
const askDelete = page.getByRole("dialog", { name: /^Delete “remittance\.txt” from your inbox\?$/ });
await askDelete.getByText("You can restore it from Settings › Recently deleted for 30 days.").waitFor();
await askDelete.getByRole("button", { name: "Cancel" }).click(); // Cancel keeps it
await askDelete.waitFor({ state: "hidden" });
await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
await askDelete.getByRole("button", { name: "Delete" }).click();
await page.getByRole("status").getByText("File deleted").waitFor();
await page.getByRole("link", { name: "Settings" }).click();
await page.getByRole("link", { name: /Recently deleted/ }).click();
await page.getByText(/^\d+ sessions · .+ · Example Medical Practice$/).waitFor(); // the undone repeat
const binRow = page.locator(".list-row", { hasText: "Inbox file · remittance.txt" });
await shot("10f-recently-deleted");
await binRow.getByRole("button", { name: "Restore" }).click();
await page.getByRole("status").getByText("Restored").waitFor();
await binRow.waitFor({ state: "detached" });
await page.getByRole("link", { name: "Today" }).first().click();
await page.waitForURL(`${BASE}/`);

step("settings hub and sections");
await page.getByRole("link", { name: "Settings" }).first().click();
await page.getByRole("link", { name: /Bank account/ }).click();
await page.getByLabel("Account number").waitFor();
if ((await page.getByLabel("Account number").getAttribute("placeholder")) !== "••••0000") await fail("masked account");
await page.getByRole("link", { name: "Settings" }).first().click();
await page.getByRole("link", { name: /^You/ }).click();
await page.getByLabel("Telephone").fill("01234 567890");
await page.getByText("✓ Saved").waitFor(); // autosave
await shot("11-settings-you");
await page.getByRole("link", { name: "Settings" }).first().click();
await page.getByRole("link", { name: /Connect another AI assistant/ }).click();
await page.getByRole("button", { name: "Create connection key" }).click();
await page.getByText("Copy this connection key now").waitFor();
await page.getByText(/Bevro · …/).waitFor();
await shot("11b-agents");
await page.getByRole("link", { name: "Settings" }).first().click();
await page.getByRole("link", { name: /Phone or computer calendar/ }).click();
await page.getByRole("switch", { name: "Share bookings with my calendar" }).click();
const icsUrl = (await page.locator("code").first().innerText()).trim();
const ics = await (await fetch(icsUrl)).text(); // no cookie, like a calendar app
if (!ics.startsWith("BEGIN:VCALENDAR") || !ics.includes("Example Medical Practice")) await fail("calendar feed");

step("personalisation: logo, colour, footer line, sample preview");
await page.getByRole("link", { name: "Settings" }).first().click();
await page.getByRole("link", { name: /Invoice appearance/ }).click();
await page.getByText("No logo yet").waitFor();
await page.locator("input[type=file]").setInputFiles({
  name: "logo.png", mimeType: "image/png", buffer: makePng(240, 80, [41, 77, 99]),
});
await page.getByRole("img", { name: "Your logo" }).waitFor();
await page.getByRole("radio", { name: "Teal" }).click();
await page.getByLabel(/Message at the bottom of each invoice/).fill("Thank you — GMC 0000000");
await page.getByText("✓ Saved").waitFor();
if ((await page.getByRole("radio", { name: "Teal" }).getAttribute("aria-checked")) !== "true") await fail("accent not selected");
const sampleShown = new Promise((resolve) => {
  ctx.once("page", (pg) => {
    pg.once("download", resolve);
    pg.waitForURL(/^blob:/, { waitUntil: "commit" }).then(resolve, () => {});
  });
});
const [samplePopup] = await Promise.all([
  page.waitForEvent("popup"),
  page.getByRole("button", { name: "Preview a sample invoice" }).click(),
]);
await Promise.race([sampleShown, page.waitForTimeout(15000).then(() => fail("sample preview did not open"))]);
await samplePopup.close().catch(() => {});
await shot("11d-personalisation");

step("credit note for one line (own number series, PDF downloads)");
await page.getByRole("link", { name: "Invoices" }).first().click();
await page.getByRole("link", { name: new RegExp(invoiceNumber) }).first().click();
await page.getByRole("button", { name: "More" }).click();
await page.getByRole("button", { name: "Correct with a credit note" }).click();
const creditSheet = page.getByRole("dialog");
await creditSheet.getByRole("checkbox").first().check();
await creditSheet.getByLabel("Why does the invoice need correcting?").fill("Session cancelled by the practice");
const [cnPdf] = await Promise.all([
  page.waitForEvent("download"),
  creditSheet.getByRole("button", { name: /Issue credit note for £677\.65/ }).click(),
]);
if (cnPdf.suggestedFilename() !== "CN-0001.pdf") await fail(`credit note file ${cnPdf.suggestedFilename()}`);
await page.getByRole("heading", { name: "Invoice corrections (credit notes)" }).waitFor();
// the invoice was already paid: the credit makes a refund owed
await page.locator(".inv-hero .pill", { hasText: "Refund needed" }).waitFor();
await shot("11c-credit-note");
await page.getByRole("button", { name: "Record a refund" }).click();
await page.getByRole("status").getByText("Refund saved").waitFor();
await page.locator(".inv-hero .pill", { hasText: "Paid" }).waitFor();

step("mobile layout");
const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
await mobile.addCookies(await ctx.cookies());
const mp = await mobile.newPage();
for (const [path, name] of [["/", "12-mobile-today"], ["/diary", "13-mobile-diary"], ["/invoices", "14-mobile-invoices"], ["/inbox", "15-mobile-inbox"], ["/bank", "16-mobile-bank"], ["/settings/mailbox", "17-mobile-mailbox"]]) {
  await mp.goto(`${BASE}${path}`);
  await mp.locator(".tabbar").waitFor();
  await mp.waitForTimeout(300);
  const overflow = await mp.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  if (overflow) await fail(`horizontal overflow on mobile ${path}`);
  await shot(name, mp);
}

step("household profiles: add one, sign in as them, separate data");
await page.goto(`${BASE}/settings/profiles`);
await page.getByRole("button", { name: "Add a profile" }).click();
const pf = page.getByRole("dialog");
await pf.getByLabel(/^Name/).fill("Sam");
await pf.getByLabel(/^Password/).fill("sam-e2e-password");
await pf.getByLabel("Type your new password again").fill("sam-e2e-password");
await pf.getByRole("button", { name: "Add profile" }).click();
await page.getByRole("status").getByText("Sam can now sign in").waitFor();
await shot("18-profiles");
await page.goto(`${BASE}/settings`);
await page.getByRole("button", { name: "Sign out" }).click();
await page.getByLabel("Your name").fill("Sam");
await page.getByLabel("Password").fill("sam-e2e-password");
await page.getByRole("button", { name: "Sign in" }).click();
// Sam starts with an empty Locuvi of their own
await page.getByRole("heading", { name: "Let's set up your invoices" }).waitFor();
await page.goto(`${BASE}/settings`);
await page.getByText("Signed in as Sam").waitFor();
if (await page.getByRole("link", { name: /Profiles/ }).count()) await fail("non-admin sees Profiles");
await page.getByRole("button", { name: "Sign out" }).click();
await page.getByLabel("Your name").fill("Owner");
await page.getByLabel("Password").fill(PASSWORD ?? "");
await page.getByRole("button", { name: "Sign in" }).click();
await page.getByRole("heading", { name: "Sign in" }).waitFor({ state: "detached" });

await browser.close();
if (errors.length) {
  console.error("Browser errors:\n" + errors.join("\n"));
  process.exit(1);
}
console.log("UI smoke test passed");
