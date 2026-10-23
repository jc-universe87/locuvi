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

// ---------------------------------------------------------------- connections (Nextcloud)
// Python has no network of its own here; locuvi.webdav.browser calls locuviNet and waits.
// In the Android app the app connects (LocuviNative.netStash, then /__net/<id> answered by
// the app), so any Nextcloud works, http:// at home too. Elsewhere the browser connects,
// which needs the Nextcloud to allow this address (CORS) and https://.
type NetAnswer = { status: number; headers: string; body: Uint8Array | null; error: string };
let nativeNet = false;
let netId = 0;

function bytesOf(body: unknown): Uint8Array | null {
  if (body == null) return null;
  if (body instanceof Uint8Array) return body;
  // a Python bytes object (PyProxy): copy its buffer
  const proxy = body as { getBuffer?: (t: string) => { data: Uint8Array; release: () => void } };
  if (proxy.getBuffer) {
    const buf = proxy.getBuffer("u8");
    try {
      return buf.data.slice();
    } finally {
      buf.release();
    }
  }
  return null;
}

function headerPairs(raw: string): [string, string][] {
  return raw
    .trim()
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      const i = line.indexOf(":");
      return [line.slice(0, i).trim(), line.slice(i + 1).trim()] as [string, string];
    });
}

function locuviNet(method: string, url: string, headersJson: string, body: unknown, timeoutMs: number): NetAnswer {
  const headers: [string, string][] = JSON.parse(headersJson);
  const data = bytesOf(body);
  const x = new XMLHttpRequest();
  try {
    if (nativeNet) {
      const id = `${Date.now()}-${++netId}`;
      let b64 = "";
      if (data) {
        let bin = "";
        for (let i = 0; i < data.length; i += 0x8000) bin += String.fromCharCode(...data.subarray(i, i + 0x8000));
        b64 = btoa(bin);
      }
      postMessage({ type: "net", id, request: JSON.stringify({ method, url, headers, body: b64, timeout: timeoutMs }) });
      x.open("GET", `${self.location.origin}/__net/${id}`, false);
      x.responseType = "arraybuffer";
      x.send();
      const meta = JSON.parse(atob(x.getResponseHeader("X-Locuvi-Net") ?? "") || "{}");
      if (meta.error) return { status: 0, headers: "[]", body: null, error: meta.error };
      return { status: meta.status, headers: JSON.stringify(meta.headers), body: new Uint8Array(x.response), error: "" };
    }
    x.open(method, url, false);
    x.responseType = "arraybuffer";
    x.timeout = timeoutMs;
    for (const [k, v] of headers) x.setRequestHeader(k, v);
    x.send(data as XMLHttpRequestBodyInit | null);
  } catch (e) {
    return { status: 0, headers: "[]", body: null, error: (e as Error)?.name === "TimeoutError" ? "timeout" : "unreachable" };
  }
  if (x.status === 0) return { status: 0, headers: "[]", body: null, error: "unreachable" };
  return {
    status: x.status,
    headers: JSON.stringify(headerPairs(x.getAllResponseHeaders())),
    body: new Uint8Array(x.response as ArrayBuffer),
    error: "",
  };
}
(self as unknown as { locuviNet: typeof locuviNet }).locuviNet = locuviNet;

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

self.onmessage = (e: MessageEvent<Req | { type: "flush" } | { type: "config"; nativeNet: boolean }>) => {
  if ("type" in e.data && e.data.type === "config") {
    nativeNet = e.data.nativeNet;
    return;
  }
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
