/**
 * The Android app (mobile/android) shows Locuvi in a WebView and adds `window.LocuviNative`,
 * because a WebView can't save downloads or open new tabs by itself. In a browser and the
 * desktop app this is undefined and everything works as on the web.
 */
interface LocuviNativeBridge {
  /** Save a file to the phone's Downloads and offer to open it. */
  saveFile(name: string, mime: string, base64: string): void;
  /** Forget this server address and show the app's "connect" screen. */
  changeServer(): void;
  /** The server address the app is connected to. */
  serverUrl(): string;
}

export function nativeApp(): LocuviNativeBridge | null {
  const n = (window as unknown as { LocuviNative?: LocuviNativeBridge }).LocuviNative;
  return n && typeof n.saveFile === "function" ? n : null;
}

function base64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).replace(/^data:[^,]*,/, ""));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

/** True when the Android app took the file. */
export async function nativeSave(blob: Blob, filename: string): Promise<boolean> {
  const n = nativeApp();
  if (!n) return false;
  n.saveFile(filename, blob.type || "application/octet-stream", await base64(blob));
  return true;
}
