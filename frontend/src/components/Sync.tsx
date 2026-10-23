import { useEffect, useState } from "react";
import { ErrorAlert } from "./ui";
import { useT } from "../i18n";
import { api, downloadBlob } from "../lib/api";
import { dateTime, todayLondon } from "../lib/format";
import { POCKET } from "../lib/pocket";

type Where = { kind: "folder" | "nextcloud"; path?: string };
type SyncState = {
  enabled: boolean;
  kind: "folder" | "nextcloud" | null;
  folder: string | null;
  device_name: string;
  last_ok: string | null;
  last_error: { code: string; message: string; at: string } | null;
  last_changes: number;
  cloud_folders: { name: string; path: string }[];
  can_choose_folder: boolean;
};

function folderName(st: SyncState): string {
  const known = st.cloud_folders.find((f) => f.path === st.folder);
  return known?.name ?? (st.folder ?? "").split(/[\\/]/).filter(Boolean).pop() ?? "";
}

/** Settings › Sync: keep every device's records in step, and everything in one file. */
export function SyncSection() {
  const { t } = useT();
  const [st, setSt] = useState<SyncState | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [mode, setMode] = useState<"start" | "join" | null>(null);
  const [where, setWhere] = useState<Where | null>(null);
  const [path, setPath] = useState("");
  const [device, setDevice] = useState("");
  const [code, setCode] = useState("");
  const [shownCode, setShownCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get<SyncState>("/sync").then(setSt, setError);
  }, []);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const target = (): Where | null => (where?.kind === "folder" && where.path === "" ? { kind: "folder", path } : where);
  const begin = () =>
    run(async () => {
      const w = target();
      if (!w) return;
      const body = { ...w, device_name: device };
      if (mode === "start") {
        const r = await api.post<SyncState & { code: string }>("/sync/start", body);
        setShownCode(r.code);
        setSt({ ...st!, ...r });
      } else {
        setSt({ ...st!, ...(await api.post<SyncState>("/sync/join", { ...body, code })) });
      }
      setMode(null);
    });
  if (!st) return <ErrorAlert error={error} />;
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("sync.intro")}</p>
      <ErrorAlert error={error} />
      {shownCode && (
        <div className="alert ok" role="status">
          <strong>{t("sync.code_title")}</strong>
          <p style={{ fontFamily: "monospace", fontSize: "1.4rem", letterSpacing: "0.08em", margin: "0.5rem 0" }}>{shownCode}</p>
          <span>{t("sync.code_hint")}</span>
        </div>
      )}
      {st.enabled ? (
        <>
          <div className="form-list">
            <div className="form-row stacked">
              <span>{t("sync.syncing_with")}</span>
              <strong>{st.kind === "nextcloud" ? t("sync.nextcloud") : folderName(st)}</strong>
              {st.kind === "folder" && <span className="hint" style={{ wordBreak: "break-all" }}>{st.folder}</span>}
            </div>
            <div className="form-row">
              <span>{t("sync.last")}</span>
              <span>{st.last_ok ? dateTime(st.last_ok) : t("sync.never")}</span>
            </div>
          </div>
          {st.last_error && <div className="alert warn" role="alert" style={{ marginTop: "0.5rem" }}>{st.last_error.message}</div>}
          <div className="actions" style={{ marginTop: "0.75rem" }}>
            <button className="btn" disabled={busy} onClick={() => run(async () => setSt({ ...st, ...(await api.post<SyncState>("/sync/now")) }))}>
              {busy ? t("sync.syncing") : t("sync.now")}
            </button>
            <button className="btn secondary" onClick={() => run(async () => setShownCode((await api.get<{ code: string }>("/sync/code")).code))}>
              {t("sync.show_code")}
            </button>
            <button className="btn ghost" onClick={() => run(async () => { setSt({ ...st, ...(await api.post<SyncState>("/sync/stop")) }); setShownCode(null); })}>
              {t("sync.stop")}
            </button>
          </div>
          <p className="form-foot">{t("sync.issue_note")}</p>
        </>
      ) : POCKET ? (
        <div className="alert info">{t("pocket.sync_note")}</div>
      ) : mode === null ? (
        <div className="actions">
          <button className="btn" onClick={() => setMode("start")}>{t("sync.start")}</button>
          <button className="btn secondary" onClick={() => setMode("join")}>{t("sync.join")}</button>
        </div>
      ) : (
        <>
          <h3>{mode === "start" ? t("sync.where_start") : t("sync.where_join")}</h3>
          <div className="form-list" role="radiogroup" aria-label={t("sync.where_start")}>
            {st.cloud_folders.map((f) => (
              <label key={f.path} className="list-row">
                <input type="radio" name="sync-where" checked={where?.kind === "folder" && where.path === f.path}
                  onChange={() => setWhere({ kind: "folder", path: f.path })} />
                <span className="list-main"><span className="list-title">{f.name}</span><span className="list-sub">{f.path}</span></span>
              </label>
            ))}
            {st.can_choose_folder && (
              <label className="list-row">
                <input type="radio" name="sync-where" checked={where?.kind === "folder" && where.path === ""}
                  onChange={() => setWhere({ kind: "folder", path: "" })} />
                <span className="list-main"><span className="list-title">{t("sync.other_folder")}</span></span>
              </label>
            )}
            <label className="list-row">
              <input type="radio" name="sync-where" checked={where?.kind === "nextcloud"} onChange={() => setWhere({ kind: "nextcloud" })} />
              <span className="list-main"><span className="list-title">{t("sync.nextcloud")}</span><span className="list-sub">{t("sync.nextcloud_sub")}</span></span>
            </label>
          </div>
          {where?.kind === "folder" && where.path === "" && (
            <div className="form-list" style={{ marginTop: "0.5rem" }}>
              <div className="form-row stacked">
                <label htmlFor="sync-path">{t("sync.folder_path")}</label>
                <input id="sync-path" value={path} onChange={(e) => setPath(e.target.value)} placeholder="C:\Users\…\Dropbox" />
              </div>
            </div>
          )}
          {st.cloud_folders.length === 0 && st.can_choose_folder && <p className="form-foot">{t("sync.no_cloud_app")}</p>}
          <div className="form-list" style={{ marginTop: "0.5rem" }}>
            <div className="form-row stacked">
              <label htmlFor="sync-device">{t("sync.device_name")}</label>
              <input id="sync-device" value={device} onChange={(e) => setDevice(e.target.value)} placeholder={t("sync.device_placeholder")} />
            </div>
            {mode === "join" && (
              <div className="form-row stacked">
                <label htmlFor="sync-code">{t("sync.code_label")}</label>
                <input id="sync-code" value={code} autoCapitalize="characters" autoComplete="off" spellCheck={false}
                  onChange={(e) => setCode(e.target.value)} placeholder="ABCD-EFGH-JKMN-PQRS-TUVW" />
              </div>
            )}
          </div>
          <div className="actions" style={{ marginTop: "0.75rem" }}>
            <button className="btn" disabled={busy || !target() || (mode === "join" && code.trim().length < 20)} onClick={() => void begin()}>
              {busy ? t("sync.syncing") : mode === "start" ? t("sync.start_go") : t("sync.join_go")}
            </button>
            <button className="btn ghost" onClick={() => setMode(null)}>{t("common.cancel")}</button>
          </div>
        </>
      )}
      <EverythingFile />
    </>
  );
}

function EverythingFile() {
  const { t } = useT();
  const [pass, setPass] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [inPass, setInPass] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);
  const exportNow = async () => {
    setError(null);
    try {
      const blob = await api.blob("POST", "/sync/export", { passphrase: pass });
      downloadBlob(blob, `Locuvi-everything-${todayLondon()}.locuvi`);
      setDone(t("sync.exported"));
    } catch (e) {
      setError(e);
    }
  };
  const importNow = async () => {
    if (!file) return;
    setError(null);
    const form = new FormData();
    form.append("file", file);
    form.append("passphrase", inPass);
    try {
      const r = await api.upload<{ brought: number }>("/sync/import", form);
      setDone(t("sync.imported", { n: r.brought }));
    } catch (e) {
      setError(e);
    }
  };
  return (
    <>
      <h3>{t("sync.file_title")}</h3>
      <p className="hint">{t("sync.file_intro")}</p>
      <ErrorAlert error={error} />
      {done && <div className="alert ok" role="status">✓ {done}</div>}
      <div className="form-list">
        <div className="form-row stacked">
          <label htmlFor="exp-pass">{t("sync.file_password")}</label>
          <input id="exp-pass" type="password" autoComplete="new-password" value={pass} placeholder={t("sync.file_password_placeholder")}
            onChange={(e) => setPass(e.target.value)} />
          <span className="hint">{t("sync.file_password_hint")}</span>
        </div>
      </div>
      <div className="actions" style={{ marginTop: "0.5rem" }}>
        <button className="btn secondary" disabled={pass.length < 12} onClick={() => void exportNow()}>{t("sync.export")}</button>
      </div>
      <div className="form-list" style={{ marginTop: "1rem" }}>
        <div className="form-row stacked">
          <label htmlFor="imp-file">{t("sync.import_file")}</label>
          <input id="imp-file" type="file" accept=".locuvi" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
        <div className="form-row stacked">
          <label htmlFor="imp-pass">{t("sync.file_password")}</label>
          <input id="imp-pass" type="password" autoComplete="off" value={inPass} placeholder={t("sync.file_password_placeholder")}
            onChange={(e) => setInPass(e.target.value)} />
        </div>
      </div>
      <div className="actions" style={{ marginTop: "0.5rem" }}>
        <button className="btn secondary" disabled={!file || inPass.length < 12} onClick={() => void importNow()}>{t("sync.import")}</button>
      </div>
      <p className="form-foot">{t("sync.import_note")}</p>
    </>
  );
}
