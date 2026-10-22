// Thin fetch wrapper: same-origin cookies, CSRF header on mutations, typed errors.
import { nativeApp, nativeSave } from "./native";

export interface ApiErrorBody {
  code: string;
  message: string;
  params: Record<string, unknown>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: ApiErrorBody,
  ) {
    super(body.message);
  }
}

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrf(token: string | null) {
  csrfToken = token;
}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

async function request(method: string, url: string, body?: unknown, headers?: Record<string, string>) {
  const h: Record<string, string> = { Accept: "application/json", ...headers };
  const form = body instanceof FormData;
  if (body !== undefined && !form) h["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) h["X-CSRF-Token"] = csrfToken;
  let res: Response;
  try {
    res = await fetch(`/api/v1${url}`, {
      method,
      headers: h,
      body: body === undefined ? undefined : form ? body : JSON.stringify(body),
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, { code: "network", message: "Network error", params: {} });
  }
  if (res.status === 401 && onUnauthorized && !url.startsWith("/auth/")) onUnauthorized();
  if (!res.ok) {
    let err: ApiErrorBody = { code: "generic", message: res.statusText, params: {} };
    try {
      const data = await res.json();
      if (data?.error) err = data.error;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, err);
  }
  return res;
}

export const api = {
  async get<T>(url: string): Promise<T> {
    return (await request("GET", url)).json();
  },
  async post<T>(url: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
    const res = await request("POST", url, body ?? {}, headers);
    return res.status === 204 ? (undefined as T) : res.json();
  },
  async put<T>(url: string, body: unknown): Promise<T> {
    return (await request("PUT", url, body)).json();
  },
  async patch<T>(url: string, body: unknown): Promise<T> {
    return (await request("PATCH", url, body)).json();
  },
  /** Deletes answer with JSON (e.g. the Recently deleted id) or 204 No Content. */
  async del<T = void>(url: string): Promise<T> {
    const res = await request("DELETE", url);
    return res.status === 204 ? (undefined as T) : res.json();
  },
  /** multipart upload (the browser sets the boundary) */
  async upload<T>(url: string, form: FormData): Promise<T> {
    return (await request("POST", url, form)).json();
  },
  async blob(method: "GET" | "POST", url: string): Promise<Blob> {
    return (await request(method, url, method === "POST" ? {} : undefined)).blob();
  },
};

export function downloadBlob(blob: Blob, filename: string) {
  if (nativeApp()) {
    void nativeSave(blob, filename);
    return;
  }
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
}

/**
 * Open a tab synchronously inside the click handler (before any await), so browsers
 * don't block it as a pop-up; fill it once the content is ready.
 */
export function openPendingTab(): { show: (blob: Blob) => void; close: () => void } {
  if (nativeApp()) {
    // the Android app has no tabs: save the preview and open it in the phone's PDF viewer
    return { show: (blob: Blob) => void nativeSave(blob, "preview.pdf"), close: () => undefined };
  }
  const w = window.open("", "_blank");
  if (w) w.opener = null;
  return {
    show(blob: Blob) {
      const href = URL.createObjectURL(blob);
      if (w && !w.closed) w.location.href = href;
      else window.location.assign(href); // pop-ups fully blocked: show in this tab
      setTimeout(() => URL.revokeObjectURL(href), 60_000);
    },
    close() {
      if (w && !w.closed) w.close();
    },
  };
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}
