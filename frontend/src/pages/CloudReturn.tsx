import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ErrorAlert, PageHead } from "../components/ui";
import { useT } from "../i18n";
import { finishSignIn, type CloudResult } from "../lib/cloud";

/** Back from signing in to Dropbox, Google Drive or OneDrive (lib/cloud.ts). */
export default function CloudReturn() {
  const { t } = useT();
  const loc = useLocation();
  const [done, setDone] = useState<CloudResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // once: the sign-in code works only once
    started.current = true;
    finishSignIn(new URLSearchParams(loc.search)).then(setDone, setError);
  }, [loc.search]);
  const known = error instanceof Error && ["expired", "declined"].includes(error.message) ? error.message : null;
  return (
    <>
      <PageHead title={t("settings.s_sync")} />
      {!done && !error && <p role="status">{t("sync.cloud_finishing")}</p>}
      {known ? <div className="alert error" role="alert">{t(known === "expired" ? "sync.cloud_expired" : "sync.cloud_declined")}</div> : <ErrorAlert error={error} />}
      {done && (
        <div className="alert ok" role="status">
          <strong>{t(done.mode === "start" ? "sync.cloud_done_start" : "sync.cloud_done_join", { name: t(`sync.cloud_${done.provider}`) })}</strong>
          {done.code && (
            <>
              <p style={{ margin: "0.75rem 0 0.25rem" }}>{t("sync.code_title")}</p>
              <p style={{ fontFamily: "monospace", fontSize: "1.4rem", letterSpacing: "0.08em", margin: "0.25rem 0" }}>{done.code}</p>
              <span>{t("sync.code_hint")}</span>
            </>
          )}
        </div>
      )}
      {(done !== null || error !== null) && (
        <div className="actions" style={{ marginTop: "0.75rem" }}>
          <Link className="btn secondary" to="/settings/sync">{t("sync.cloud_back")}</Link>
        </div>
      )}
    </>
  );
}
