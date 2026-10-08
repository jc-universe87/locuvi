// Thin fetch wrapper: same-origin cookies, CSRF header on mutations, typed errors.

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
  if (body !== undefined) h["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) h["X-CSRF-Token"] = csrfToken;
  let res: Response;
  try {
    res = await fetch(`/api/v1${url}`, {
      method,
      headers: h,
      body: body === undefined ? undefined : JSON.stringify(body),
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
  async del(url: string): Promise<void> {
    await request("DELETE", url);
  },
  async blob(method: "GET" | "POST", url: string): Promise<Blob> {
    return (await request(method, url, method === "POST" ? {} : undefined)).blob();
  },
};

export function downloadBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
}

export function openBlob(blob: Blob) {
  const href = URL.createObjectURL(blob);
  window.open(href, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(href), 60_000);
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}
