/// <reference lib="webworker" />
/**
 * Locuvi's backend on the phone: Pyodide (Python compiled to WebAssembly) with the Locuvi
 * package, records in the browser's own storage (IndexedDB, kept across restarts).
 * Messages: {id, method, url, headers, body} in, {id, status, headers, body} out.
 * The runtime files come from ./pocket/ next to the app (bundled in the Android app; cached
 * offline by the service worker on iPhone and iPad).
 */
type Req = { id: number; method: string; url: string; headers: Record<string, string>; body: ArrayBuffer | null };

const base = new URL("../pocket/", import.meta.url).href;
const ROOT = "/locuvi";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let py: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let handle: any = null;
const cookies = new Map<string, string>();
let saveTimer: ReturnType<typeof setTimeout> | null = null;
let queue: Promise<unknown> = Promise.resolve();

const say = (step: string) => postMessage({ type: "progress", step });

function syncfs(populate: boolean): Promise<void> {
  return new Promise((resolve, reject) => py.FS.syncfs(populate, (err: unknown) => (err ? reject(err) : resolve())));
}

function saveSoon() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    queue = queue.then(() => syncfs(false)).catch(() => undefined);
  }, 400);
}

async function start() {
  say("runtime");
  const manifest = await (await fetch(base + "manifest.json")).json();
  const { loadPyodide } = await import(/* @vite-ignore */ base + "pyodide/pyodide.mjs");
  py = await loadPyodide({ indexURL: base + "pyodide/" });
  say("packages");
  await py.loadPackage([...manifest.packages, ...manifest.wheels.map((w: string) => base + "wheels/" + w)], {
    messageCallback: () => undefined,
  });
  say("records");
  py.FS.mkdirTree(ROOT);
  py.FS.mount(py.FS.filesystems.IDBFS, {}, ROOT);
  await syncfs(true);
  await py.runPythonAsync(`from locuvi import pocket\nawait pocket.start(${JSON.stringify(ROOT)})`);
  handle = py.pyimport("locuvi.pocket").handle_js;
  await syncfs(false);
}

async function answer(req: Req) {
  const headers = { ...req.headers };
  if (cookies.size) headers["cookie"] = [...cookies].map(([k, v]) => `${k}=${v}`).join("; ");
  const body = req.body ? new Uint8Array(req.body) : null;
  const res = (await handle(req.method, req.url, JSON.stringify(headers), body)).toJs({ dict_converter: Object.fromEntries });
  const out: [string, string][] = res.headers;
  for (const [k, v] of out) {
    if (k.toLowerCase() !== "set-cookie") continue;
    const [pair] = v.split(";");
    const i = pair.indexOf("=");
    const name = pair.slice(0, i).trim();
    const value = pair.slice(i + 1).trim();
    if (/max-age=0|expires=thu, 01 jan 1970/i.test(v) || value === "") cookies.delete(name);
    else cookies.set(name, value);
  }
  const bytes: Uint8Array = res.body;
  const copy = bytes.slice().buffer as ArrayBuffer;
  postMessage({ id: req.id, status: res.status, headers: out.filter(([k]) => k.toLowerCase() !== "set-cookie"), body: copy }, [copy]);
  saveSoon();
}

const started = start().then(
  () => postMessage({ type: "ready" }),
  (e) => postMessage({ type: "failed", error: String(e?.message ?? e) }),
);

self.onmessage = (e: MessageEvent<Req | { type: "flush" }>) => {
  if ("type" in e.data) {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = null;
    queue = queue.then(() => started).then(() => syncfs(false)).catch(() => undefined);
    return;
  }
  const req = e.data;
  // one request at a time, in order: the Python side has no threads
  queue = queue
    .then(() => started)
    .then(() => answer(req))
    .catch((err) => postMessage({ id: req.id, status: 0, headers: [], body: null, error: String(err?.message ?? err) }));
};
