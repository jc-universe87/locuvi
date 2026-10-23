/**
 * New versions of Locuvi.
 *
 * - Windows and Mac app: the Locuvi on the computer asks GitHub now and then
 *   (GET /updates) and installs a new version when the owner taps Update now.
 * - Android app: the app itself checks and installs (LocuviNative.checkUpdate, MainActivity).
 * - iPhone and iPad: the page updates itself in the background (service worker); once the new
 *   version is ready, the owner restarts it with one tap.
 */
import { useEffect, useState } from "react";
import { api } from "./api";
import { POCKET } from "./pocket";

export type UpdateState = {
  supported: boolean;
  current?: string | null;
  latest?: string | null;
  available?: boolean;
  automatic?: boolean;
  error?: boolean;
  notes?: string;
};

type AndroidUpdates = { checkUpdate: (manual: boolean) => void; appVersion: () => string };

export function androidUpdates(): AndroidUpdates | null {
  const n = (window as unknown as { LocuviNative?: Partial<AndroidUpdates> }).LocuviNative;
  return n?.checkUpdate && n.appVersion ? (n as AndroidUpdates) : null;
}

// ------------------------------------------------------------------ iPhone and iPad

let swReady = false;
const swListeners = new Set<() => void>();

/** Register the service worker and notice when a new version has taken over (main.tsx). */
export function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  const hadOne = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!hadOne) return; // the very first install: nothing to restart
    swReady = true;
    swListeners.forEach((fn) => fn());
  });
  void navigator.serviceWorker.register("./sw.js").then((reg) => {
    // Home Screen apps stay open for days: look for a new version each time Locuvi comes back
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") void reg.update().catch(() => undefined);
    });
  });
}

export function useNewPageVersion(): boolean {
  const [ready, setReady] = useState(swReady);
  useEffect(() => {
    const fn = () => setReady(true);
    swListeners.add(fn);
    return () => void swListeners.delete(fn);
  }, []);
  return ready;
}

// ------------------------------------------------------------------ Windows and Mac

/** The computer app's update state: checked when Locuvi opens and every few hours. */
export function useComputerUpdates(on: boolean): [UpdateState | null, (check?: boolean) => Promise<void>] {
  const [st, setSt] = useState<UpdateState | null>(null);
  const load = async (check = false) => {
    try {
      setSt(await api.get<UpdateState>(`/updates${check ? "?check=1" : ""}`));
    } catch {
      setSt({ supported: false });
    }
  };
  useEffect(() => {
    if (!on || POCKET) return;
    void load();
    const every = window.setInterval(() => void load(), 6 * 60 * 60 * 1000);
    return () => window.clearInterval(every);
  }, [on]);
  return [st, load];
}
