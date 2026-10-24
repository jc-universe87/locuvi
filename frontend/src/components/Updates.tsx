import { useState } from "react";
import { ErrorAlert, SwitchRow } from "./ui";
import { useT } from "../i18n";
import { api } from "../lib/api";
import { POCKET } from "../lib/pocket";
import { androidUpdates, useComputerUpdates, useNewPageVersion, type UpdateState } from "../lib/updates";

const DISMISSED = "locuvi.update-dismissed";

function dismissedFor(): string | null {
  try {
    return sessionStorage.getItem(DISMISSED);
  } catch {
    return null;
  }
}

/** Says when a new version is ready, at the top of every page, with one tap to update. */
export function UpdateBanner() {
  const { t } = useT();
  const newPage = useNewPageVersion();
  const [st] = useComputerUpdates(!POCKET);
  const [hidden, setHidden] = useState(dismissedFor());
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (POCKET && newPage) {
    // iPhone and iPad: the new version is already on the device
    return (
      <div className="alert info update-banner" role="status">
        <span>{t("updates.page_ready")}</span>
        <button className="btn small" onClick={() => location.reload()}>{t("updates.restart")}</button>
      </div>
    );
  }
  if (!st?.available || hidden === st.latest) return null;
  if (installing) {
    return <div className="alert info update-banner" role="status">{t("updates.installing")}</div>;
  }
  const later = () => {
    try {
      sessionStorage.setItem(DISMISSED, st.latest ?? "");
    } catch {
      /* private window: it shows again on the next page */
    }
    setHidden(st.latest ?? "");
  };
  return (
    <div className="alert info update-banner" role="status">
      <span>{t(st.automatic ? "updates.ready_auto" : "updates.ready", { v: st.latest ?? "" })}</span>
      <span className="actions">
        <button className="btn small" onClick={() => void api.post("/updates/install").then(() => setInstalling(true), setError)}>
          {t("updates.update_now")}
        </button>
        <button className="btn ghost small" onClick={later}>{t("updates.later")}</button>
      </span>
      <ErrorAlert error={error} />
    </div>
  );
}

/** Settings › Phones, tablets and computers › Updates. */
export function UpdatesSection({ computer }: { computer: { update_check?: boolean } | null }) {
  const { t } = useT();
  const android = androidUpdates();
  const [st, load] = useComputerUpdates(!!computer);
  const [auto, setAuto] = useState(computer?.update_check ?? true);
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (android) {
    return (
      <>
        <h3>{t("updates.title")}</h3>
        <div className="form-list">
          <div className="form-row"><span>{t("updates.version")}</span><span>{android.appVersion()}</span></div>
        </div>
        <p className="form-foot">{t("updates.android_auto")}</p>
        <div className="actions" style={{ marginTop: "0.5rem" }}>
          <button className="btn secondary" onClick={() => android.checkUpdate(true)}>{t("updates.check")}</button>
        </div>
      </>
    );
  }
  if (POCKET) {
    return (
      <>
        <h3>{t("updates.title")}</h3>
        <div className="form-list">
          <div className="form-row"><span>{t("updates.version")}</span><span>{import.meta.env.VITE_LOCUVI_VERSION || "–"}</span></div>
        </div>
        <p className="form-foot">{t("updates.iphone_auto")}</p>
      </>
    );
  }
  if (!computer) return null;
  const s: UpdateState | null = st;
  const check = async () => {
    setChecking(true);
    setError(null);
    await load(true);
    setChecking(false);
  };
  const setAutomatic = async (on: boolean) => {
    setAuto(on);
    try {
      await api.put("/desktop", { update_check: on });
    } catch (e) {
      setError(e);
    }
  };
  if (s && !s.supported) return null; // run from the code, not an installed app
  return (
    <>
      <h3>{t("updates.title")}</h3>
      <ErrorAlert error={error} />
      <div className="form-list">
        <div className="form-row"><span>{t("updates.version")}</span><span>{s?.current ?? "…"}</span></div>
        <SwitchRow label={t("updates.automatic")} hint={t("updates.automatic_hint")} checked={auto} onChange={(v) => void setAutomatic(v)} />
      </div>
      {s?.error && <p className="form-foot">{t("updates.offline")}</p>}
      {installing ? (
        <div className="alert info" role="status" style={{ marginTop: "0.5rem" }}>{t("updates.installing")}</div>
      ) : s?.available ? (
        <div className="alert info" style={{ marginTop: "0.5rem" }}>
          <p style={{ marginTop: 0 }}>{t(auto ? "updates.ready_auto" : "updates.ready", { v: s.latest ?? "" })}</p>
          <button className="btn" onClick={() => void api.post("/updates/install").then(() => setInstalling(true), setError)}>
            {t("updates.update_now")}
          </button>
        </div>
      ) : (
        s?.latest && <p className="form-foot">{t("updates.latest")}</p>
      )}
      <div className="actions" style={{ marginTop: "0.5rem" }}>
        <button className="btn secondary" disabled={checking} onClick={() => void check()}>
          {checking ? t("updates.checking") : t("updates.check")}
        </button>
      </div>
    </>
  );
}
