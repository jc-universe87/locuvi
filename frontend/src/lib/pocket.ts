/**
 * The phone app ("pocket" build: npm run build:pocket): the whole of Locuvi runs on the phone,
 * in a Web Worker (../pocket/engine.worker.ts) that hosts the Python backend with Pyodide.
 * Requests the web app would send to a server go to that worker instead, and records stay on
 * the phone (synced with the owner's other devices through Settings › Sync).
 */
export const POCKET = import.meta.env.VITE_POCKET === "1";

type Reply = { id: number; status: number; headers: [string, string][]; body: ArrayBuffer | null; error?: string };
type Progress = { type: "progress"; step: string };

type NativeNet = { netStash: (id: string, request: string) => void };
const nativeNet = (): NativeNet | null => {
  const n = (window as unknown as { LocuviNative?: Partial<NativeNet> }).LocuviNative;
  return n?.netStash ? (n as NativeNet) : null;
};

let worker: Worker | null = null;
let ready: Promise<void> | null = null;
let next = 1;
const waiting = new Map<number, (r: Reply) => void>();
const progressListeners = new Set<(step: string) => void>();

/** "Opening Locuvi…" steps while the engine starts (the first start takes a few seconds). */
export function onPocketProgress(fn: (step: string) => void): () => void {
  progressListeners.add(fn);
  return () => progressListeners.delete(fn);
}

function boot(): Promise<void> {
  if (ready) return ready;
  ready = new Promise((resolve, reject) => {
    try {
      worker = new Worker(new URL("../pocket/engine.worker.ts", import.meta.url), { type: "module" });
      worker.postMessage({ type: "config", nativeNet: !!nativeNet() });
    } catch (err) {
      progressListeners.forEach((fn) => fn("failed"));
      return reject(err);
    }
    worker.onerror = (ev) => {
      console.error("Locuvi could not start on this device:", ev.message);
      progressListeners.forEach((fn) => fn("failed"));
      reject(new Error(ev.message || "worker failed"));
    };
    worker.onmessage = (e: MessageEvent<Reply | Progress | { type: "ready" } | { type: "failed"; error: string }>) => {
      const m = e.data as { type?: string };
      if (m.type === "ready") {
        console.info("Locuvi is ready on this device");
        return resolve();
      }
      if (m.type === "failed") {
        console.error("Locuvi could not start on this device:", (e.data as { error: string }).error);
        progressListeners.forEach((fn) => fn("failed"));
        return reject(new Error((e.data as { error: string }).error));
      }
      if (m.type === "progress") return progressListeners.forEach((fn) => fn((e.data as Progress).step));
      if (m.type === "net") {
        // the Android app makes this connection for the engine (see engine.worker.ts)
        const n = e.data as unknown as { id: string; request: string };
        return nativeNet()?.netStash(n.id, n.request);
      }
      const r = e.data as Reply;
      waiting.get(r.id)?.(r);
      waiting.delete(r.id);
    };
  });
  if ("storage" in navigator && navigator.storage.persist) void navigator.storage.persist();
  // Leaving the app (home button, switching apps): copy the last changes to storage now.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") worker?.postMessage({ type: "flush" });
  });
  return ready;
}

/** fetch(), answered by the Locuvi running on this phone. */
export async function pocketFetch(url: string, init: RequestInit = {}): Promise<Response> {
  await boot();
  const headers: Record<string, string> = {};
  new Headers(init.headers).forEach((v, k) => (headers[k] = v));
  let body: ArrayBuffer | null = null;
  if (init.body instanceof FormData) {
    const r = new Response(init.body); // encodes the multipart body and its boundary
    headers["content-type"] = r.headers.get("content-type") ?? "";
    body = await r.arrayBuffer();
  } else if (typeof init.body === "string") {
    body = new TextEncoder().encode(init.body).buffer as ArrayBuffer;
  }
  const id = next++;
  const reply = await new Promise<Reply>((resolve) => {
    waiting.set(id, resolve);
    worker!.postMessage({ id, method: init.method ?? "GET", url, headers, body }, body ? [body] : []);
  });
  if (reply.error) throw new TypeError(reply.error);
  const noBody = reply.status === 204 || reply.status === 304;
  return new Response(noBody ? null : reply.body, { status: reply.status, headers: reply.headers });
}
