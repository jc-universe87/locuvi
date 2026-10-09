import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorAlert, Icon, SavedIndicator, Toggle, useAutosave } from "../components/ui";
import { hasKey, localeNames, useT, type Locale } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api, setCsrf } from "../lib/api";
import { dateTime, pct, todayLondon, ukDate } from "../lib/format";
import { suggestYearPrefix } from "../lib/numbering";
import type { AssistantConfig, EmailConfig, MailboxConfig, ScanResult, Numbering, Policy, Practice, Profile, WebDavConfig } from "../lib/types";
import { PracticeSheet } from "./Diary";
import { scanSummary } from "./Inbox";

const SECTIONS = ["you", "bank", "practices", "invoicing", "pension", "email", "storage", "calendar", "mailbox", "assistant", "agents", "password"] as const;
type Section = (typeof SECTIONS)[number];
const ICON: Record<Section, string> = {
  you: "today", bank: "money", practices: "diary", invoicing: "invoices", pension: "pension", email: "send", storage: "cloud", calendar: "diary", mailbox: "inbox", assistant: "sparkle", agents: "send", password: "settings",
};

export default function SettingsPage({ onSignOut }: { onSignOut?: () => void }) {
  const { t, locale, setLocale } = useT();
  const { section } = useParams();
  if (section && (SECTIONS as readonly string[]).includes(section)) {
    return (
      <>
        <p style={{ margin: "0.5rem 0 0" }}>
          <Link to="/settings" className="btn ghost small"><Icon name="back" size={16} /> {t("nav.settings")}</Link>
        </p>
        <h1>{t(`settings.s_${section}` as MessageKey)}</h1>
        {section === "you" && <ProfileSection fields="you" />}
        {section === "bank" && <ProfileSection fields="bank" />}
        {section === "practices" && <PracticesSection />}
        {section === "invoicing" && <InvoicingSection />}
        {section === "pension" && <PensionSection />}
        {section === "email" && <EmailSection />}
        {section === "storage" && <StorageSection />}
        {section === "calendar" && <CalendarSection />}
        {section === "mailbox" && <MailboxSection />}
        {section === "assistant" && <AssistantSection />}
        {section === "agents" && <AgentsSection />}
        {section === "password" && <PasswordSection />}
      </>
    );
  }
  return (
    <>
      <h1>{t("nav.settings")}</h1>
      <div className="form-list">
        {SECTIONS.filter((s) => s !== "password" || onSignOut).map((s) => (
          <Link key={s} to={`/settings/${s}`} className="list-row">
            <span className="task-icon" style={{ width: "2rem", height: "2rem", borderRadius: 9 }}><Icon name={ICON[s]} size={18} /></span>
            <span className="list-main">
              <span className="list-title">{t(`settings.s_${s}` as MessageKey)}</span>
              <span className="list-sub">{t(`settings.s_${s}_sub` as MessageKey)}</span>
            </span>
            <span className="chev"><Icon name="chevron" size={18} /></span>
          </Link>
        ))}
      </div>
      <div className="form-list" style={{ marginTop: "1rem" }}>
        <div className="form-row">
          <label htmlFor="lang">{t("app.language")}</label>
          <select id="lang" value={locale} onChange={(e) => setLocale(e.target.value as Locale)}>
            {(Object.keys(localeNames) as Locale[]).map((l) => <option key={l} value={l}>{localeNames[l]}</option>)}
          </select>
        </div>
      </div>
      {onSignOut && (
        <div className="form-list" style={{ marginTop: "1rem" }}>
          <button className="list-row" onClick={onSignOut} style={{ color: "var(--err)", fontWeight: 600 }}>{t("nav.signout")}</button>
        </div>
      )}
      <p className="form-foot" style={{ textAlign: "center", marginTop: "1.5rem" }}>Locuvi · {t("app.tagline")}</p>
    </>
  );
}

function Row({ id, label, children, stacked, hint }: { id?: string; label: string; children: ReactNode; stacked?: boolean; hint?: string }) {
  return (
    <div className={`form-row ${stacked ? "stacked" : ""}`}>
      <label htmlFor={id}>{label}{hint && <span className="hint" style={{ display: "block", fontWeight: 400 }}>{hint}</span>}</label>
      {children}
    </div>
  );
}

function SwitchRow({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="form-row" style={{ gridTemplateColumns: "1fr auto" }}>
      <span><span style={{ fontWeight: 500 }}>{label}</span>{hint && <span className="hint" style={{ display: "block" }}>{hint}</span>}</span>
      <Toggle checked={checked} onChange={onChange} label={label} />
    </div>
  );
}

type ProfileEdit = Omit<Profile, "bank_account_number_masked" | "bank_account_number_set"> & { bank_account_number?: string };

function useProfile() {
  const [p, setP] = useState<ProfileEdit | null>(null);
  const [server, setServer] = useState<Profile | null>(null);
  useEffect(() => {
    api.get<Profile>("/settings/profile").then((x) => {
      setServer(x);
      const { bank_account_number_masked: _m, bank_account_number_set: _s, ...rest } = x;
      setP(rest);
    }, () => undefined);
  }, []);
  const save = useAutosave(p, async (v) => {
    if (!v) return;
    const body: Record<string, unknown> = { ...v };
    delete body.last_digest_sent_at; // read-only
    if (!v.bank_account_number) delete body.bank_account_number;
    const digits = String(v.bank_sort_code ?? "").replace(/\D/g, "");
    if (digits.length !== 0 && digits.length !== 6) delete body.bank_sort_code;
    if (v.bank_account_number && v.bank_account_number.replace(/\D/g, "").length !== 8) delete body.bank_account_number;
    if (v.employee_rate !== null && v.employee_rate !== "" && !/^0?\.\d{1,4}$/.test(String(v.employee_rate))) delete body.employee_rate;
    setServer(await api.patch<Profile>("/settings/profile", body));
  }, { enabled: p !== null, delay: 700 });
  return { p, setP, server, save };
}

function ProfileSection({ fields }: { fields: "you" | "bank" }) {
  const { t } = useT();
  const { p, setP, server, save } = useProfile();
  if (!p) return null;
  const set = (patch: Partial<ProfileEdit>) => setP({ ...p, ...patch });
  return (
    <>
      <ErrorAlert error={save.error} />
      {fields === "you" ? (
        <>
          <div className="form-list">
            <Row id="p-name" label={t("settings.legal_name")}><input id="p-name" type="text" autoComplete="name" value={p.legal_name} onChange={(e) => set({ legal_name: e.target.value })} /></Row>
            <Row id="p-trading" label={t("settings.trading_name")}><input id="p-trading" type="text" placeholder={t("common.optional")} value={p.trading_name ?? ""} onChange={(e) => set({ trading_name: e.target.value })} /></Row>
            <Row id="p-desig" label={t("settings.designation")}><input id="p-desig" type="text" placeholder={t("settings.designation_ph")} value={p.designation} onChange={(e) => set({ designation: e.target.value })} /></Row>
            <Row id="p-addr" label={t("settings.address")} stacked><textarea id="p-addr" rows={2} autoComplete="street-address" value={p.address_lines} onChange={(e) => set({ address_lines: e.target.value })} /></Row>
            <Row id="p-pc" label={t("settings.postcode")}><input id="p-pc" type="text" autoComplete="postal-code" value={p.postcode} onChange={(e) => set({ postcode: e.target.value.toUpperCase() })} /></Row>
            <Row id="p-email" label={t("settings.email")}><input id="p-email" type="email" autoComplete="email" value={p.email} onChange={(e) => set({ email: e.target.value })} /></Row>
            <Row id="p-phone" label={t("settings.phone")}><input id="p-phone" type="tel" autoComplete="tel" placeholder={t("common.optional")} value={p.phone ?? ""} onChange={(e) => set({ phone: e.target.value })} /></Row>
          </div>
          <p className="form-foot">{t("settings.sender_help")} <SavedIndicator state={save.state} /></p>
        </>
      ) : (
        <>
          <div className="form-list">
            <Row id="p-holder" label={t("settings.bank_holder")}><input id="p-holder" type="text" value={p.bank_account_holder} onChange={(e) => set({ bank_account_holder: e.target.value })} /></Row>
            <Row id="p-sort" label={t("settings.sort_code")}><input id="p-sort" type="text" inputMode="numeric" autoComplete="off" placeholder="00-00-00" value={p.bank_sort_code} onChange={(e) => set({ bank_sort_code: e.target.value })} /></Row>
            <Row id="p-acct" label={t("settings.account_number")}>
              <input id="p-acct" type="text" inputMode="numeric" autoComplete="off" maxLength={8}
                placeholder={server?.bank_account_number_set ? server.bank_account_number_masked : ""}
                value={p.bank_account_number ?? ""} onChange={(e) => set({ bank_account_number: e.target.value })} />
            </Row>
          </div>
          <p className="form-foot">{t("settings.bank_help")} <SavedIndicator state={save.state} /></p>
        </>
      )}
    </>
  );
}

function PracticesSection() {
  const { t } = useT();
  const [list, setList] = useState<Practice[]>([]);
  const [open, setOpen] = useState<Practice | "new" | null>(null);
  const load = () => api.get<Practice[]>("/practices?include_archived=true").then(setList, () => undefined);
  useEffect(() => {
    void load();
  }, []);
  return (
    <>
      <div className="form-list">
        {list.map((p) => (
          <button key={p.id} type="button" className="list-row" onClick={() => setOpen(p)}>
            <span className="list-main">
              <span className="list-title">{p.name}</span>
              <span className="list-sub">
                {p.default_rate ? `£${p.default_rate}` : t("practices.no_rate")}
                {p.default_pensionable ? ` · ${t("detail.pensionable_short")}` : ""}
                {p.is_archived ? ` · ${t("practices.archived_short")}` : ""}
              </span>
            </span>
            <span className="chev"><Icon name="chevron" size={18} /></span>
          </button>
        ))}
        <button type="button" className="list-row" onClick={() => setOpen("new")} style={{ color: "var(--steel)", fontWeight: 600 }}>
          <Icon name="plus" size={18} /> {t("practices.add")}
        </button>
      </div>
      {open && (
        <PracticeSheet practice={open === "new" ? undefined : open} onClose={() => setOpen(null)} onSaved={() => { setOpen(null); void load(); }} />
      )}
    </>
  );
}

function InvoicingSection() {
  const { t } = useT();
  const { p, setP, save } = useProfile();
  const [n, setN] = useState<Numbering | null>(null);
  const nSave = useAutosave(n, async (v) => {
    if (!v || !v.prefix || !v.next_number) return;
    setN(await api.put<Numbering>("/settings/numbering", { prefix: v.prefix, next_number: v.next_number, padding: v.padding }));
  }, { enabled: n !== null, delay: 900 });
  useEffect(() => {
    api.get<Numbering>("/settings/numbering").then(setN, () => undefined);
  }, []);
  if (!p || !n) return null;
  const preview = `${n.prefix}${String(n.next_number).padStart(n.padding, "0")}`;
  const suggested = suggestYearPrefix(n.prefix, Number(todayLondon().slice(0, 4)));
  return (
    <>
      <ErrorAlert error={nSave.error ?? save.error} />
      {suggested && (
        <div className="alert info">
          {t("settings.year_prefix_hint", { prefix: suggested })}{" "}
          <button type="button" className="btn secondary small" onClick={() => setN({ ...n, prefix: suggested, next_number: 1 })}>
            {t("settings.year_prefix_apply", { number: `${suggested}${"1".padStart(n.padding, "0")}` })}
          </button>
        </div>
      )}
      <h3>{t("settings.numbering")}</h3>
      <div className="form-list">
        <Row id="n-prefix" label={t("settings.prefix")}><input id="n-prefix" type="text" value={n.prefix} onChange={(e) => setN({ ...n, prefix: e.target.value })} /></Row>
        <Row id="n-next" label={t("settings.next_number")}><input id="n-next" type="number" min={1} value={n.next_number} onChange={(e) => setN({ ...n, next_number: Number(e.target.value) })} /></Row>
        <Row id="n-pad" label={t("settings.padding")}><input id="n-pad" type="number" min={1} max={8} value={n.padding} onChange={(e) => setN({ ...n, padding: Number(e.target.value) })} /></Row>
      </div>
      <p className="form-foot">{t("settings.number_preview", { number: preview })}. {t("settings.numbering_help")} <SavedIndicator state={nSave.state} /></p>
      <h3>{t("settings.terms_vat")}</h3>
      <div className="form-list">
        <Row id="n-terms" label={t("settings.terms")}><input id="n-terms" type="number" min={0} max={365} value={p.payment_terms_days} onChange={(e) => setP({ ...p, payment_terms_days: Number(e.target.value) })} /></Row>
        <Row id="n-vat" label={t("settings.vat_status")}>
          <select id="n-vat" value={p.vat_status} onChange={(e) => setP({ ...p, vat_status: e.target.value as Profile["vat_status"] })}>
            <option value="not_vat_registered">{t("settings.vat_not_registered")}</option>
            <option value="vat_registered">{t("settings.vat_registered")}</option>
          </select>
        </Row>
      </div>
      <p className="form-foot">{t("settings.vat_help")} <SavedIndicator state={save.state} /></p>
    </>
  );
}

function PensionSection() {
  const { t } = useT();
  const { p, setP, save } = useProfile();
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [np, setNp] = useState({ effective_from: "", employer_rate: "", pensionable_fraction: "0.90", label: "" });
  const [addError, setAddError] = useState<unknown>(null);
  const load = () => api.get<Policy[]>("/settings/pension-policies").then(setPolicies, () => undefined);
  useEffect(() => {
    void load();
  }, []);
  if (!p) return null;
  return (
    <>
      <ErrorAlert error={save.error} />
      <div className="form-list">
        <SwitchRow label={t("settings.pension_default")} checked={p.pension_default_enabled} onChange={(v) => setP({ ...p, pension_default_enabled: v })} />
      </div>
      <p className="form-foot">{t("settings.pension_help")}</p>
      <h3>{t("settings.pension_forms")}</h3>
      <div className="form-list">
        <Row id="pe-tier" label={t("settings.employee_rate")} hint={t("settings.employee_rate_hint")}>
          <input id="pe-tier" type="text" inputMode="decimal" placeholder="0.098" value={p.employee_rate ?? ""} onChange={(e) => setP({ ...p, employee_rate: e.target.value })} />
        </Row>
        <Row id="pe-ref" label={t("settings.pension_ref")}><input id="pe-ref" type="text" placeholder={t("common.optional")} value={p.pension_ref ?? ""} onChange={(e) => setP({ ...p, pension_ref: e.target.value })} /></Row>
        <Row id="pe-gmc" label={t("settings.professional_number")}><input id="pe-gmc" type="text" placeholder={t("common.optional")} value={p.professional_number ?? ""} onChange={(e) => setP({ ...p, professional_number: e.target.value })} /></Row>
      </div>
      <p className="form-foot">{t("settings.pension_forms_help")} <SavedIndicator state={save.state} /></p>
      <h3>{t("settings.policies")}</h3>
      <div className="form-list">
        {policies.map((x) => (
          <div key={x.id} className="list-row">
            <span className="list-main">
              <span className="list-title">{t("settings.policy_line", { rate: pct(x.employer_rate), fraction: pct(x.pensionable_fraction) })}</span>
              <span className="list-sub">{t("settings.policy_from_date", { date: ukDate(x.effective_from) })}{x.label ? ` · ${x.label}` : ""}</span>
            </span>
          </div>
        ))}
      </div>
      <h3>{t("settings.policy_add")}</h3>
      <ErrorAlert error={addError} />
      <div className="form-list">
        <Row id="pp-from" label={t("settings.policy_from")}><input id="pp-from" type="date" value={np.effective_from} onChange={(e) => setNp({ ...np, effective_from: e.target.value })} /></Row>
        <Row id="pp-rate" label={t("settings.policy_rate")} hint={t("settings.policy_rate_hint")}><input id="pp-rate" type="text" inputMode="decimal" value={np.employer_rate} onChange={(e) => setNp({ ...np, employer_rate: e.target.value })} /></Row>
      </div>
      <button className="btn secondary" style={{ marginTop: "0.5rem" }} disabled={!np.effective_from || !np.employer_rate}
        onClick={async () => {
          try {
            await api.post("/settings/pension-policies", np);
            setNp({ effective_from: "", employer_rate: "", pensionable_fraction: "0.90", label: "" });
            setAddError(null);
            await load();
          } catch (e) {
            setAddError(e);
          }
        }}>{t("common.add")}</button>
    </>
  );
}

function EmailSection() {
  const { t } = useT();
  const [cfg, setCfg] = useState<EmailConfig | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    api.get<EmailConfig>("/settings/email").then(setCfg, setError);
  }, []);
  if (!cfg) return <ErrorAlert error={error} />;
  const set = (patch: Partial<EmailConfig>) => setCfg({ ...cfg, ...patch });
  const save = async (enabled = cfg.enabled) => {
    setError(null);
    setMsg(null);
    try {
      const { password_set: _p, ...rest } = cfg;
      setCfg(await api.put<EmailConfig>("/settings/email", { ...rest, enabled, password: password || null }));
      setPassword("");
      setMsg(t("common.saved"));
      return true;
    } catch (e) {
      setError(e);
      return false;
    }
  };
  const test = async () => {
    if (!(await save())) return;
    try {
      await api.post("/settings/email/test");
      setMsg(t("email.test_sent", { address: cfg.from_address }));
    } catch (e) {
      setError(e);
    }
  };
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("email.settings_lead")}</p>
      <ErrorAlert error={error} />
      {msg && <div className="alert ok" role="status">{msg}</div>}
      <div className="form-list">
        <Row id="e-from" label={t("email.from_address")}><input id="e-from" type="email" value={cfg.from_address} onChange={(e) => set({ from_address: e.target.value, username: cfg.username || e.target.value })} /></Row>
        <Row id="e-name" label={t("email.from_name")}><input id="e-name" type="text" value={cfg.from_name} onChange={(e) => set({ from_name: e.target.value })} /></Row>
        <Row id="e-host" label={t("email.host")}><input id="e-host" type="text" placeholder="smtp.example.com" autoCapitalize="none" value={cfg.host} onChange={(e) => set({ host: e.target.value })} /></Row>
        <Row id="e-port" label={t("email.port")}>
          <select id="e-port" value={`${cfg.security}:${cfg.port}`} onChange={(e) => {
            const [sec, port] = e.target.value.split(":");
            set({ security: sec as EmailConfig["security"], port: Number(port) });
          }}>
            <option value="starttls:587">587 · STARTTLS</option>
            <option value="ssl:465">465 · SSL/TLS</option>
          </select>
        </Row>
        <Row id="e-user" label={t("email.username")}><input id="e-user" type="text" autoCapitalize="none" value={cfg.username} onChange={(e) => set({ username: e.target.value })} /></Row>
        <Row id="e-pass" label={t("email.password")}>
          <input id="e-pass" type="password" autoComplete="new-password" placeholder={cfg.password_set ? "••••••••" : ""} value={password} onChange={(e) => setPassword(e.target.value)} />
        </Row>
        <SwitchRow label={t("email.bcc_self")} checked={cfg.bcc_self} onChange={(v) => set({ bcc_self: v })} />
      </div>
      <p className="form-foot">{t("email.password_hint")}</p>
      <div className="actions">
        <button className="btn" onClick={() => save(true)}>{cfg.enabled ? t("common.save") : t("email.turn_on")}</button>
        <button className="btn secondary" onClick={test} disabled={!cfg.host || !cfg.from_address}>{t("email.send_test")}</button>
        {cfg.enabled && <button className="btn ghost" onClick={() => save(false)}>{t("email.turn_off")}</button>}
      </div>
      {cfg.enabled && <DigestSetting />}
    </>
  );
}

function DigestSetting() {
  const { t } = useT();
  const { p, setP, save } = useProfile();
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  if (!p) return null;
  const sendNow = async () => {
    setError(null);
    try {
      const r = await api.post<{ sent: boolean }>("/digest/send");
      setMsg(r.sent ? t("digest.sent") : t("digest.nothing"));
    } catch (e) {
      setError(e);
    }
  };
  return (
    <>
      <h3>{t("digest.title")}</h3>
      <ErrorAlert error={error ?? save.error} />
      {msg && <div className="alert ok" role="status">{msg}</div>}
      <div className="form-list">
        <SwitchRow label={t("digest.toggle")} hint={t("digest.hint")} checked={p.digest_enabled}
          onChange={(v) => setP({ ...p, digest_enabled: v })} />
      </div>
      <div className="actions" style={{ marginTop: "0.5rem" }}>
        <button className="btn secondary small" onClick={sendNow}>{t("digest.send_now")}</button>
        <SavedIndicator state={save.state} />
      </div>
    </>
  );
}

type Backlog = { not_archived: number; pending: number; synced: number; failed: number; conflict: number };

function StorageSection() {
  const { t, tn } = useT();
  const [cfg, setCfg] = useState<WebDavConfig | null>(null);
  const [password, setPassword] = useState("");
  const [test, setTest] = useState<{ ok: boolean; error_class?: string; folder_exists?: boolean } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [backlog, setBacklog] = useState<Backlog | null>(null);
  const [queued, setQueued] = useState<number | null>(null);
  useEffect(() => {
    api.get<WebDavConfig>("/storage/webdav").then(setCfg, setError);
  }, []);
  useEffect(() => {
    if (cfg?.enabled && cfg.password_set) api.get<Backlog>("/storage/webdav/backlog").then(setBacklog, () => undefined);
  }, [cfg?.enabled, cfg?.password_set]);
  if (!cfg) return <ErrorAlert error={error} />;
  const set = (patch: Partial<WebDavConfig>) => {
    setCfg({ ...cfg, ...patch });
    setTest(null);
    setSaved(false);
  };
  const body = (enabled = cfg.enabled) => ({
    enabled, target_url: cfg.target_url, username: cfg.username, base_path: cfg.base_path,
    auto_upload: cfg.auto_upload, password: password || null,
  });
  const save = async (enabled = cfg.enabled) => {
    setError(null);
    try {
      setCfg(await api.put<WebDavConfig>("/storage/webdav", body(enabled)));
      setPassword("");
      setSaved(true);
    } catch (e) {
      setError(e);
    }
  };
  const runTest = async () => {
    setTest(null);
    try {
      const { enabled: _e, auto_upload: _a, ...rest } = body();
      setTest(await api.post("/storage/webdav/test", rest));
    } catch (e) {
      setError(e);
    }
  };
  const reason = (cls?: string) => (cls && hasKey(`archive_error.${cls}`) ? t(`archive_error.${cls}` as MessageKey) : cls ?? "");
  const todo = backlog ? backlog.not_archived + backlog.failed : 0;
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("settings.local_help")}</p>
      <ErrorAlert error={error} />
      {test && (
        <div className={`alert ${test.ok ? "ok" : "error"}`} role="status">
          {test.ok
            ? t("settings.webdav_test_ok", { folder: test.folder_exists ? t("settings.webdav_folder_exists") : t("settings.webdav_folder_missing") })
            : t("settings.webdav_test_failed", { reason: reason(test.error_class) })}
        </div>
      )}
      {saved && <div className="alert ok" role="status">✓ {t("common.saved")}</div>}
      <div className="form-list">
        <Row id="w-url" label={t("settings.webdav_url")} stacked hint={t("settings.webdav_url_hint")}>
          <input id="w-url" type="url" autoComplete="off" spellCheck={false} value={cfg.target_url} onChange={(e) => set({ target_url: e.target.value })} />
        </Row>
        <Row id="w-user" label={t("settings.webdav_user")}><input id="w-user" type="text" autoCapitalize="none" value={cfg.username} onChange={(e) => set({ username: e.target.value })} /></Row>
        <Row id="w-pass" label={t("settings.webdav_password")}>
          <input id="w-pass" type="password" autoComplete="new-password" disabled={cfg.password_source === "secret_file"}
            placeholder={cfg.password_set ? "••••••••" : ""} value={password} onChange={(e) => { setPassword(e.target.value); setTest(null); }} />
        </Row>
        <Row id="w-folder" label={t("settings.webdav_folder")}><input id="w-folder" type="text" value={cfg.base_path} onChange={(e) => set({ base_path: e.target.value })} /></Row>
        <SwitchRow label={t("settings.webdav_auto")} checked={cfg.auto_upload} onChange={(v) => set({ auto_upload: v })} />
      </div>
      <p className="form-foot">{t("settings.webdav_password_hint")} {t("settings.webdav_privacy", { example: `${cfg.base_path || "Locuvi/Invoices"}/2026/10/LOC-2026-0001.pdf` })}</p>
      <div className="actions">
        <button className="btn" onClick={() => save(true)}>{cfg.enabled ? t("common.save") : t("settings.webdav_turn_on")}</button>
        <button className="btn secondary" onClick={runTest} disabled={!cfg.target_url}>{t("settings.webdav_test")}</button>
        {cfg.enabled && <button className="btn ghost" onClick={() => save(false)}>{t("settings.webdav_turn_off")}</button>}
      </div>
      {backlog && cfg.enabled && (
        <>
          <h3>{t("settings.archive_all_title")}</h3>
          <p className="muted" style={{ marginTop: 0 }}>{t("settings.archive_all_counts", { synced: backlog.synced, pending: backlog.pending, todo, conflict: backlog.conflict })}</p>
          {queued !== null && <div className="alert ok" role="status">{tn("settings.archive_all_queued", queued)}</div>}
          <button className="btn secondary" disabled={todo === 0} onClick={async () => {
            try {
              const r = await api.post<{ queued: number; backlog: Backlog }>("/storage/webdav/archive-all");
              setQueued(r.queued);
              setBacklog(r.backlog);
            } catch (e) {
              setError(e);
            }
          }}>{tn("settings.archive_all_button", todo)}</button>
        </>
      )}
    </>
  );
}

function AssistantSection() {
  const { t } = useT();
  const [cfg, setCfg] = useState<AssistantConfig | null>(null);
  const [key, setKey] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    api.get<AssistantConfig>("/settings/assistant").then(setCfg, setError);
  }, []);
  if (!cfg) return <ErrorAlert error={error} />;
  const save = async (enabled: boolean, clear = false) => {
    setError(null);
    setSaved(false);
    try {
      setCfg(await api.put<AssistantConfig>("/settings/assistant", { enabled, api_key: key || null, clear_key: clear }));
      setKey("");
      setSaved(true);
    } catch (e) {
      setError(e);
    }
  };
  const hasKey = cfg.key_saved || cfg.key_from_server;
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("assistant.intro")}</p>
      <ErrorAlert error={error} />
      {saved && <div className="alert ok" role="status">✓ {cfg.ready ? t("assistant.on") : t("common.saved")}</div>}
      <div className="form-list">
        <SwitchRow label={t("assistant.toggle")} hint={t("assistant.toggle_hint")} checked={cfg.enabled}
          onChange={(v) => { if (!v || hasKey || key) void save(v); else setCfg({ ...cfg, enabled: true }); }} />
        {cfg.enabled && (
          <Row id="ai-key" label={t("assistant.key")} hint={cfg.key_from_server ? t("assistant.key_server") : t("assistant.key_hint")}>
            <input id="ai-key" type="password" autoComplete="off" spellCheck={false} disabled={cfg.key_from_server}
              placeholder={cfg.key_saved ? "••••••••" : "sk-ant-…"} value={key} onChange={(e) => setKey(e.target.value.trim())} />
          </Row>
        )}
      </div>
      {cfg.enabled && !cfg.key_from_server && (
        <div className="actions" style={{ marginTop: "0.5rem" }}>
          <button className="btn" disabled={!key && !cfg.key_saved} onClick={() => void save(true)}>{t("common.save")}</button>
          {cfg.key_saved && <button className="btn ghost" onClick={() => void save(false, true)}>{t("assistant.forget_key")}</button>}
        </div>
      )}
      <h3>{t("assistant.privacy_title")}</h3>
      <ul className="muted bullets">
        <li>{t("assistant.privacy_1")}</li>
        <li>{t("assistant.privacy_2")}</li>
        <li>{t("assistant.privacy_3")}</li>
        <li>{t("assistant.privacy_4")}</li>
      </ul>
      <p className="form-foot">{t("assistant.model", { model: cfg.model })}</p>
    </>
  );
}

type Folder = { name: string; label: string };

function MailboxSection() {
  const { t, tn } = useT();
  const [cfg, setCfg] = useState<MailboxConfig | null>(null);
  const [password, setPassword] = useState("");
  const [folders, setFolders] = useState<Folder[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get<MailboxConfig>("/settings/mailbox").then(setCfg, setError);
  }, []);
  if (!cfg) return <ErrorAlert error={error} />;
  const set = (patch: Partial<MailboxConfig>) => { setCfg({ ...cfg, ...patch }); setMsg(null); };
  const body = (over: Partial<MailboxConfig> = {}) => {
    const c = { ...cfg, ...over };
    return { enabled: c.enabled, host: c.host, port: c.port, security: c.security, username: c.username,
      password: password || null, folders: c.folders, since_days: c.since_days, auto_scan: c.auto_scan };
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null); setMsg(null);
    try { await fn(); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const connect = () => run(async () => {
    setCfg(await api.put<MailboxConfig>("/settings/mailbox", body({ enabled: false })));
    setPassword("");
    const r = await api.post<{ folders: Folder[] }>("/settings/mailbox/folders");
    setFolders(r.folders);
  });
  const save = (enabled: boolean) => run(async () => {
    setCfg(await api.put<MailboxConfig>("/settings/mailbox", body({ enabled })));
    setPassword("");
    setMsg(enabled ? t("mailbox.on") : t("common.saved"));
  });
  const scan = () => run(async () => {
    const r = await api.post<ScanResult>("/mailbox/scan");
    setMsg(scanSummary(t, tn, r));
    setCfg(await api.get<MailboxConfig>("/settings/mailbox"));
  });
  const toggleFolder = (name: string, on: boolean) =>
    set({ folders: on ? [...cfg.folders, name] : cfg.folders.filter((f) => f !== name) });
  const shown: Folder[] = folders ?? cfg.folders.map((f) => ({ name: f, label: f }));
  const lastErr = cfg.last_error && hasKey(`error.${cfg.last_error}`) ? t(`error.${cfg.last_error}` as MessageKey) : cfg.last_error;
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("mailbox.intro")}</p>
      <ErrorAlert error={error} />
      {msg && <div className="alert ok" role="status">{msg}</div>}
      {cfg.enabled && lastErr && <div className="alert warn" role="status">{t("mailbox.last_failed", { reason: lastErr })}</div>}
      <div className="form-list">
        <Row id="m-host" label={t("mailbox.host")} hint={t("mailbox.host_hint")}>
          <input id="m-host" type="text" autoCapitalize="none" spellCheck={false} value={cfg.host} placeholder="imap.gmail.com"
            onChange={(e) => set({ host: e.target.value.trim() })} />
        </Row>
        <Row id="m-security" label={t("mailbox.security")}>
          <select id="m-security" value={cfg.security} onChange={(e) => {
            const security = e.target.value as "ssl" | "starttls";
            set({ security, port: security === "ssl" ? 993 : 143 });
          }}>
            <option value="ssl">SSL/TLS (993)</option>
            <option value="starttls">STARTTLS (143)</option>
          </select>
        </Row>
        <Row id="m-user" label={t("mailbox.username")}>
          <input id="m-user" type="email" autoCapitalize="none" value={cfg.username} onChange={(e) => set({ username: e.target.value.trim() })} />
        </Row>
        <Row id="m-pass" label={t("mailbox.password")} hint={t("mailbox.password_hint")}>
          <input id="m-pass" type="password" autoComplete="new-password" placeholder={cfg.password_set ? "••••••••" : ""}
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </Row>
      </div>
      <div className="actions" style={{ marginTop: "0.5rem" }}>
        <button className="btn secondary" disabled={busy || !cfg.host || !cfg.username || (!password && !cfg.password_set)} onClick={connect}>
          {busy && !folders ? t("mailbox.connecting") : t("mailbox.connect")}
        </button>
      </div>

      {shown.length > 0 && (
        <>
          <h3>{t("mailbox.folders_title")}</h3>
          <p className="muted" style={{ marginTop: 0 }}>{t("mailbox.folders_hint")}</p>
          <div className="form-list">
            {shown.map((f) => (
              <label key={f.name} className="form-row" style={{ gridTemplateColumns: "auto 1fr", cursor: "pointer" }}>
                <input type="checkbox" checked={cfg.folders.includes(f.name)} onChange={(e) => toggleFolder(f.name, e.target.checked)} />
                <span>{f.label}</span>
              </label>
            ))}
          </div>
          <div className="form-list" style={{ marginTop: "1rem" }}>
            <Row id="m-since" label={t("mailbox.since")}>
              <select id="m-since" value={cfg.since_days} onChange={(e) => set({ since_days: Number(e.target.value) })}>
                {[30, 90, 180, 365].map((d) => <option key={d} value={d}>{tn("mailbox.since_days", d)}</option>)}
              </select>
            </Row>
            <SwitchRow label={t("mailbox.auto")} hint={t("mailbox.auto_hint")} checked={cfg.auto_scan} onChange={(v) => set({ auto_scan: v })} />
          </div>
          <div className="actions" style={{ marginTop: "0.75rem" }}>
            <button className="btn" disabled={busy || cfg.folders.length === 0} onClick={() => save(true)}>
              {cfg.enabled ? t("common.save") : t("mailbox.turn_on")}
            </button>
            {cfg.enabled && <button className="btn secondary" disabled={busy} onClick={scan}>{busy ? t("mailbox.checking") : t("mailbox.check_now")}</button>}
            {cfg.enabled && <button className="btn ghost" disabled={busy} onClick={() => save(false)}>{t("mailbox.turn_off")}</button>}
          </div>
          {cfg.last_scan_at && <p className="form-foot">{t("mailbox.last_scan", { when: dateTime(cfg.last_scan_at) })}</p>}
        </>
      )}
      <h3>{t("mailbox.privacy_title")}</h3>
      <ul className="muted bullets">
        <li>{t("mailbox.privacy_1")}</li>
        <li>{t("mailbox.privacy_2")}</li>
        <li>{t("mailbox.privacy_3")}</li>
        <li>{t("mailbox.privacy_4")}</li>
      </ul>
    </>
  );
}

interface AgentTok { id: string; name: string; hint: string; allow_drafts: boolean; created_at: string; last_used_at: string | null; revoked: boolean }

function AgentsSection() {
  const { t } = useT();
  const [tokens, setTokens] = useState<AgentTok[] | null>(null);
  const [name, setName] = useState("Bevro");
  const [drafts, setDrafts] = useState(false);
  const [fresh, setFresh] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const endpoint = `${window.location.origin}/mcp`;
  const load = () => api.get<{ tokens: AgentTok[] }>("/settings/agents").then((r) => setTokens(r.tokens), setError);
  useEffect(() => { void load(); }, []);
  const create = async () => {
    setError(null);
    try {
      const r = await api.post<AgentTok & { token: string }>("/settings/agents", { name: name.trim() || "Bevro", allow_drafts: drafts });
      setFresh(r.token);
      await load();
    } catch (e) {
      setError(e);
    }
  };
  const revoke = async (id: string) => {
    try {
      await api.del(`/settings/agents/${id}`);
      await load();
    } catch (e) {
      setError(e);
    }
  };
  const copy = (text: string) => void navigator.clipboard?.writeText(text).catch(() => undefined);
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("agents.intro")}</p>
      <ErrorAlert error={error} />
      <div className="form-list">
        <Row id="ag-url" label={t("agents.endpoint")} hint={t("agents.endpoint_hint")}>
          <span className="row" style={{ gap: "0.4rem", justifyContent: "flex-end" }}>
            <code id="ag-url" style={{ wordBreak: "break-all" }}>{endpoint}</code>
            <button className="btn ghost small" onClick={() => copy(endpoint)} aria-label={t("agents.copy_url")}><Icon name="copy" size={16} /></button>
          </span>
        </Row>
      </div>
      {fresh && (
        <div className="alert ok" role="status">
          <strong>{t("agents.token_once")}</strong>
          <div className="row" style={{ gap: "0.4rem", marginTop: "0.4rem" }}>
            <code style={{ wordBreak: "break-all", flex: 1 }}>{fresh}</code>
            <button className="btn small secondary" onClick={() => copy(fresh)}>{t("agents.copy")}</button>
          </div>
        </div>
      )}
      <h3>{t("agents.new_title")}</h3>
      <div className="form-list">
        <Row id="ag-name" label={t("agents.name")}>
          <input id="ag-name" type="text" value={name} onChange={(e) => setName(e.target.value)} />
        </Row>
        <SwitchRow label={t("agents.allow_drafts")} hint={t("agents.allow_drafts_hint")} checked={drafts} onChange={setDrafts} />
      </div>
      <div className="actions" style={{ marginTop: "0.5rem" }}>
        <button className="btn" onClick={create}>{t("agents.create")}</button>
      </div>
      {tokens && tokens.length > 0 && (
        <>
          <h3>{t("agents.tokens")}</h3>
          <div className="form-list">
            {tokens.map((k) => (
              <div key={k.id} className="form-row" style={{ gridTemplateColumns: "1fr auto" }}>
                <span>
                  <span style={{ fontWeight: 500 }}>{k.name} · …{k.hint}</span>
                  <span className="hint" style={{ display: "block" }}>
                    {k.allow_drafts ? t("agents.scope_drafts") : t("agents.scope_read")} ·{" "}
                    {k.revoked ? t("agents.revoked") : k.last_used_at ? t("agents.last_used", { when: dateTime(k.last_used_at) }) : t("agents.never_used")}
                  </span>
                </span>
                {!k.revoked && <button className="btn ghost small" onClick={() => void revoke(k.id)}>{t("agents.revoke")}</button>}
              </div>
            ))}
          </div>
        </>
      )}
      <h3>{t("agents.safety_title")}</h3>
      <ul className="muted bullets">
        <li>{t("agents.safety_1")}</li>
        <li>{t("agents.safety_2")}</li>
        <li>{t("agents.safety_3")}</li>
      </ul>
    </>
  );
}

function CalendarSection() {
  const { t } = useT();
  const [cfg, setCfg] = useState<{ enabled: boolean; include_fees: boolean; path: string | null } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    api.get<typeof cfg>("/settings/calendar").then(setCfg, setError);
  }, []);
  if (!cfg) return <ErrorAlert error={error} />;
  const put = async (body: { enabled: boolean; include_fees?: boolean; regenerate?: boolean }) => {
    try {
      setCfg(await api.put("/settings/calendar", { include_fees: cfg.include_fees, ...body }));
      setCopied(false);
    } catch (e) {
      setError(e);
    }
  };
  const url = cfg.path ? `${window.location.origin}${cfg.path}` : "";
  const webcal = url.replace(/^https?:/, "webcal:");
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("calendar.intro")}</p>
      <ErrorAlert error={error} />
      <div className="form-list">
        <SwitchRow label={t("calendar.toggle")} checked={cfg.enabled} onChange={(v) => void put({ enabled: v })} />
        {cfg.enabled && (
          <SwitchRow label={t("calendar.fees")} hint={t("calendar.fees_hint")} checked={cfg.include_fees}
            onChange={(v) => void put({ enabled: true, include_fees: v })} />
        )}
      </div>
      {cfg.enabled && url && (
        <>
          <h3>{t("calendar.link")}</h3>
          <div className="form-list">
            <div className="form-row stacked"><code style={{ wordBreak: "break-all" }}>{url}</code></div>
          </div>
          <div className="actions" style={{ marginTop: "0.5rem" }}>
            <a className="btn" href={webcal}>{t("calendar.subscribe")}</a>
            <button className="btn secondary" onClick={() => {
              void navigator.clipboard?.writeText(url).then(() => setCopied(true), () => undefined);
            }}>{copied ? t("ask.copied") : t("calendar.copy")}</button>
            <button className="btn ghost" onClick={() => void put({ enabled: true, regenerate: true })}>{t("calendar.new_link")}</button>
          </div>
          <p className="form-foot">{t("calendar.private")}</p>
        </>
      )}
    </>
  );
}

function PasswordSection() {
  const { t } = useT();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const mismatch = again.length > 0 && next !== again;
  const save = async () => {
    setError(null);
    try {
      const r = await api.post<{ csrf_token: string }>("/auth/password", { current, new: next });
      setCsrf(r.csrf_token);
      setDone(true);
      setCurrent(""); setNext(""); setAgain("");
    } catch (e) {
      setError(e);
    }
  };
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("password.intro")}</p>
      <ErrorAlert error={error} />
      {done && <div className="alert ok" role="status">✓ {t("password.changed")}</div>}
      <div className="form-list">
        <Row id="pw-cur" label={t("password.current")}>
          <input id="pw-cur" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </Row>
        <Row id="pw-new" label={t("password.new")} hint={t("password.new_hint")}>
          <input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </Row>
        <Row id="pw-again" label={t("password.again")}>
          <input id="pw-again" type="password" autoComplete="new-password" value={again} aria-invalid={mismatch}
            onChange={(e) => setAgain(e.target.value)} />
        </Row>
      </div>
      {mismatch && <p className="hint" style={{ color: "var(--err)" }}>{t("password.mismatch")}</p>}
      <div className="actions" style={{ marginTop: "0.5rem" }}>
        <button className="btn" disabled={!current || next.length < 10 || next !== again} onClick={save}>{t("password.save")}</button>
      </div>
      <p className="form-foot">{t("password.forgot")}</p>
    </>
  );
}
