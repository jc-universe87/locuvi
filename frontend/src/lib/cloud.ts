/**
 * Signing in to Dropbox, Google Drive or OneDrive to sync (backend locuvi/sync/cloud.py).
 *
 * Locuvi sends the person to the company's sign-in page and remembers, on this device, what
 * they were doing (start or join, the device name, the sync code) for 15 minutes. The
 * company sends them back through Locuvi's return page to /oauth here, where the sign-in is
 * finished and sync started or joined.
 */
import { api } from "./api";
import { POCKET } from "./pocket";

export type CloudProvider = "dropbox" | "google" | "onedrive";
type Pending = {
  provider: CloudProvider;
  mode: "start" | "join";
  device: string;
  code: string;
  verifier: string;
  state: string;
  returnTo: string;
  at: number;
};
const KEY = "locuvi.cloud-signin";

/** Where the return page should send the person back to (cloud.py _check_return). */
function returnTo(): string {
  const n = (window as unknown as { LocuviNative?: { netStash?: unknown } }).LocuviNative;
  if (POCKET) return n?.netStash ? "app" : "web";
  return `local:${location.port || "80"}`;
}

export async function signIn(provider: CloudProvider, mode: "start" | "join", device: string, code: string) {
  const to = returnTo();
  const b = await api.post<{ url: string; state: string; verifier: string }>("/sync/cloud/begin", { provider, return_to: to });
  const pending: Pending = { provider, mode, device, code, verifier: b.verifier, state: b.state, returnTo: to, at: Date.now() };
  try {
    localStorage.setItem(KEY, JSON.stringify(pending));
  } catch {
    /* no storage: the return will ask to start again */
  }
  location.href = b.url; // in the Android app this opens the phone's browser
}

export type CloudResult = { mode: "start" | "join"; code?: string; account: string; provider: CloudProvider };

/** Back from signing in: finish, then start or join sync. Throws if it can't. */
export async function finishSignIn(query: URLSearchParams): Promise<CloudResult> {
  let pending: Pending | null = null;
  try {
    pending = JSON.parse(localStorage.getItem(KEY) ?? "null");
    localStorage.removeItem(KEY);
  } catch {
    pending = null;
  }
  if (!pending || Date.now() - pending.at > 15 * 60 * 1000 || pending.state !== query.get("state")) {
    throw new Error("expired");
  }
  if (query.get("error") || !query.get("code")) throw new Error("declined");
  const f = await api.post<{ connection: string; account: string }>("/sync/cloud/finish", {
    provider: pending.provider, code: query.get("code"), verifier: pending.verifier, return_to: pending.returnTo,
  });
  const body = { kind: "cloud", connection: f.connection, device_name: pending.device };
  if (pending.mode === "start") {
    const r = await api.post<{ code: string }>("/sync/start", body);
    return { mode: "start", code: r.code, account: f.account, provider: pending.provider };
  }
  await api.post("/sync/join", { ...body, code: pending.code });
  return { mode: "join", account: f.account, provider: pending.provider };
}
