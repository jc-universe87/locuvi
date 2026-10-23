import { useEffect } from "react";
import { api } from "./api";

/**
 * The Windows and macOS app stops by itself a few minutes after its window closes
 * (backend locuvi/desktop.py). While this page is open it says "still here" every 30 s.
 * On a server or a phone /desktop answers {available: false} and nothing is sent.
 */
export function useDesktopHeartbeat(on: boolean) {
  useEffect(() => {
    if (!on) return;
    let timer: number | undefined;
    let stopped = false;
    api.get<{ available: boolean }>("/desktop").then(
      (d) => {
        if (!d.available || stopped) return;
        const beat = () => void api.post("/desktop/alive").catch(() => undefined);
        beat();
        timer = window.setInterval(beat, 30_000);
      },
      () => undefined,
    );
    return () => {
      stopped = true;
      if (timer) window.clearInterval(timer);
    };
  }, [on]);
}
