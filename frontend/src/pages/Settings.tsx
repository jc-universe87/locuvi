import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { Dialog, ErrorAlert, Icon, SavedIndicator, SwitchRow, useAutosave, useConfirm, useToast } from "../components/ui";
import { UpdatesSection } from "../components/Updates";
import { PhoneLimits } from "../components/PhoneLimits";
import { SyncSection } from "../components/Sync";
import { TrashSection } from "../components/Trash";
import { hasKey, localeNames, useT, type Locale } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api, downloadBlob, openPendingTab, setCsrf } from "../lib/api";
import { APPS_GUIDE, DOWNLOADS } from "../lib/apps";
import { nativeApp } from "../lib/native";
import { POCKET } from "../lib/pocket";
import { dateTime, pct, todayLondon, ukDate } from "../lib/format";
import { suggestYearPrefix } from "../lib/numbering";
import type { AssistantConfig, Branding, HouseholdProfile, EmailConfig, MailboxConfig, ScanResult, Numbering, Policy, Practice, Profile, WebDavConfig } from "../lib/types";
import { PracticeSheet } from "./Diary";
import { scanSummary } from "./Inbox";

const SECTIONS = ["you", "look", "bank", "practices", "invoicing", "pension", "email", "storage", "calendar", "apps", "sync", "mailbox", "assistant", "agents", "trash", "password", "profiles"] as const;
type Section = (typeof SECTIONS)[number];
// The phone app can't open email or Nextcloud connections, or be reached by other apps: these
// are set up on a computer (or server), and what they bring in syncs to the phone.
const ON_A_COMPUTER = new Set<Section>(["email", "storage", "mailbox", "agents", "assistant"]);
const ICON: Record<Section, string> = {
  you: "today", look: "sparkle", bank: "money", practices: "diary", invoicing: "invoices", pension: "pension", email: "send", storage: "cloud", calendar: "diary", apps: "today", sync: "cloud", mailbox: "inbox", assistant: "sparkle", agents: "send", trash: "trash", password: "settings", profiles: "settings",
};

export default function SettingsPage({ onSignOut, profile = null }: { onSignOut?: () => void; profile?: HouseholdProfile | null }) {
  const { t, locale, setLocale } = useT();
  const { section } = useParams();
  // Password: always for a signed-in profile (a gateway admin sets one before adding profiles).
  const visible = (s: Section) =>
    (s !== "password" || !!onSignOut || !!profile) && (s !== "profiles" || !!profile?.is_admin) && !(POCKET && ON_A_COMPUTER.has(s));
  if (section && (SECTIONS as readonly string[]).includes(section) && visible(section as Section)) {
    return (
      <>
        <p style={{ margin: "0.5rem 0 0" }}>
          <Link to="/settings" className="btn ghost small"><Icon name="back" size={16} /> {t("nav.settings")}</Link>
        </p>
        <h1>{t(`settings.s_${section}` as MessageKey)}</h1>
        {section === "you" && <ProfileSection fields="you" />}
        {section === "look" && <LookSection />}
        {section === "bank" && <ProfileSection fields="bank" />}
        {section === "practices" && <PracticesSection />}
        {section === "invoicing" && <InvoicingSection />}
        {section === "pension" && <PensionSection />}
        {section === "email" && <EmailSection />}
        {section === "storage" && <StorageSection />}
        {section === "calendar" && <CalendarSection />}
        {section === "apps" && <AppsSection />}
        {section === "sync" && <SyncSection />}
        {section === "mailbox" && <MailboxSection />}
        {section === "assistant" && <AssistantSection />}
        {section === "agents" && <AgentsSection />}
        {section === "trash" && <TrashSection />}
        {section === "password" && <PasswordSection profile={profile} />}
        {section === "profiles" && profile && <ProfilesSection me={profile} />}
      </>
    );
  }
  return (
    <>
      <h1>{t("nav.settings")}</h1>
      <PhoneLimits />
      {profile && onSignOut && <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("profiles.signed_in_as", { name: profile.name })}</p>}
      <div className="form-list">
        {SECTIONS.filter(visible).map((s) => (
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
      <p className="form-foot" style={{ textAlign: "center", marginTop: "1.5rem" }}>
        Locuvi · {t("app.tagline")} · <a href="https://github.com/jc-universe87/locuvi" target="_blank" rel="noreferrer noopener">{t("app.source")}</a>
      </p>
    </>
  );
}

/** An image from the API, fetched like any other request (so it also works in the phone app). */
function ApiImage({ url, alt, className }: { url: string; alt: string; className?: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let gone = false;
    let made: string | null = null;
    api.blob("GET", url).then((b) => {
      if (gone) return;
      made = URL.createObjectURL(b);
      setSrc(made);
    }, () => undefined);
    return () => {
      gone = true;
      if (made) URL.revokeObjectURL(made);
    };
  }, [url]);
  return src ? <img className={className} src={src} alt={alt} /> : null;
}

function Row({ id, label, children, stacked, hint }: { id?: string; label: string; children: ReactNode; stacked?: boolean; hint?: string }) {
  return (
    <div className={`form-row ${stacked ? "stacked" : ""}`}>
      <label htmlFor={id}>{label}{hint && <span className="hint" style={{ display: "block", fontWeight: 400 }}>{hint}</span>}</label>
      {children}
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

// Not image-only on purpose: Android opens its photo picker for image-only lists, and that
// picker hides SVG files. The XML types make it offer Files/Downloads/Drive as well.
const LOGO_ACCEPT = "image/png,image/jpeg,image/webp,image/svg+xml,.svg,.png,.jpg,.jpeg,.webp,application/xml,text/xml";

function LookSection() {
  const { t } = useT();
  const confirm = useConfirm();
  const [b, setB] = useState<Branding | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const persist = (v: Branding) => api.patch<Branding>("/settings/branding", { accent: v.accent, invoice_footer: v.invoice_footer, email_signoff: v.email_signoff });
  const save = useAutosave(b, async (v) => {
    if (v) await persist(v);
  }, { enabled: b !== null, delay: 700 });
  useEffect(() => {
    api.get<Branding>("/settings/branding").then(setB, setError);
  }, []);
  if (!b) return <ErrorAlert error={error} />;
  const upload = async (file: File | undefined) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setBusy(true);
    setError(null);
    try {
      const out = await api.upload<Branding>("/settings/branding/logo", form);
      setB({ ...b, has_logo: out.has_logo, logo_sha256: out.logo_sha256 });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    const ok = await confirm({ title: t("trash.ask_logo"), body: t("trash.ask_logo_body"), confirm: t("look.remove_logo"), bin: false });
    if (!ok) return;
    setError(null);
    try {
      await api.del("/settings/branding/logo");
      setB({ ...b, has_logo: false, logo_sha256: null });
    } catch (e) {
      setError(e);
    }
  };
  const preview = async () => {
    const tab = openPendingTab(); // before any await, or the browser blocks the tab
    try {
      await persist(b); // the preview always shows what is on screen
      tab.show(await api.blob("GET", "/settings/branding/preview.pdf"));
    } catch (e) {
      tab.close();
      setError(e);
    }
  };
  return (
    <>
      <ErrorAlert error={error ?? save.error} />
      <h3>{t("look.logo")}</h3>
      <div className="form-list">
        <div className="form-row stacked">
          {b.has_logo ? (
            <ApiImage className="logo-preview" url={`/settings/branding/logo?v=${b.logo_sha256 ?? ""}`} alt={t("look.logo_alt")} />
          ) : (
            <span className="hint">{t("look.no_logo")}</span>
          )}
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <label className="btn secondary small" aria-disabled={busy}>
              <Icon name="upload" size={16} /> {b.has_logo ? t("look.replace_logo") : t("look.add_logo")}
              <input type="file" accept={LOGO_ACCEPT} hidden disabled={busy} onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ""; }} />
            </label>
            {b.has_logo && <button type="button" className="btn ghost small" onClick={remove}>{t("look.remove_logo")}</button>}
          </div>
        </div>
      </div>
      <p className="form-foot">{t("look.logo_help")}</p>

      <h3>{t("look.colour")}</h3>
      <div className="swatches" role="radiogroup" aria-label={t("look.colour")}>
        {Object.entries(b.accents).map(([key, hex]) => (
          <button key={key} type="button" role="radio" aria-checked={b.accent === key} aria-label={t(`look.c_${key}` as MessageKey)}
            title={t(`look.c_${key}` as MessageKey)} className={`swatch ${b.accent === key ? "on" : ""}`} style={{ background: hex }}
            onClick={() => setB({ ...b, accent: key })} />
        ))}
      </div>

      <h3>{t("look.words")}</h3>
      <div className="form-list">
        <Row id="l-footer" label={t("look.footer")} stacked hint={t("look.footer_hint")}>
          <input id="l-footer" type="text" maxLength={120} value={b.invoice_footer} placeholder={t("look.footer_placeholder")} onChange={(e) => setB({ ...b, invoice_footer: e.target.value })} />
        </Row>
        <Row id="l-signoff" label={t("look.signoff")} stacked hint={t("look.signoff_hint")}>
          <textarea id="l-signoff" rows={3} maxLength={500} value={b.email_signoff} placeholder={t("look.signoff_placeholder")} onChange={(e) => setB({ ...b, email_signoff: e.target.value })} />
        </Row>
      </div>
      <p className="form-foot"><SavedIndicator state={save.state} /></p>
      <button type="button" className="btn secondary block" onClick={preview}>{t("look.preview")}</button>
      <p className="form-foot">{t("look.frozen")}</p>
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
      <h3>{t("settings.pension_reminders_title")}</h3>
      <div className="form-list">
        <SwitchRow label={t("settings.pension_reminders")} hint={t("settings.pension_reminders_hint")}
          checked={p.pension_reminders} onChange={(v) => setP({ ...p, pension_reminders: v })} />
      </div>
      <p className="form-foot">{t("settings.pension_reminders_email")} <Link to="/settings/email">{t("settings.s_email")}</Link></p>
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

/** A country code as its flag emoji (regional indicator letters). */
function flag(code: string): string {
  if (!code) return "🖥"; // your own server
  return String.fromCodePoint(...[...code.toUpperCase()].map((c) => 0x1f1a5 + c.charCodeAt(0)));
}

function AssistantSection() {
  const { t, tn } = useT();
  const [cfg, setCfg] = useState<AssistantConfig | null>(null);
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    api.get<AssistantConfig>("/settings/assistant").then((c) => { setCfg(c); setModel(c.model); setBaseUrl(c.base_url); }, setError);
  }, []);
  if (!cfg) return <ErrorAlert error={error} />;
  const put = async (body: Record<string, unknown>) => {
    setError(null);
    setSaved(false);
    try {
      const next = await api.put<AssistantConfig>("/settings/assistant", body);
      setCfg(next);
      setModel(next.model);
      setBaseUrl(next.base_url);
      return next;
    } catch (e) {
      setError(e);
      return null;
    }
  };
  const save = async (enabled: boolean, clear = false) => {
    const custom = own || (model.trim() && model.trim() !== info?.default_model) ? model.trim() : "";
    const body: Record<string, unknown> = { enabled, api_key: key || null, clear_key: clear, model: custom };
    if (own) body.base_url = baseUrl.trim();
    if (await put(body)) {
      setKey("");
      setSaved(true);
    }
  };
  const choose = async (provider: string) => {
    setModels([]);
    setChecked(false);
    setKey("");
    await put({ enabled: cfg.enabled, provider });
  };
  const check = async () => {
    setError(null);
    setChecked(false);
    try {
      const r = await api.post<{ ok: boolean; models: string[] }>("/settings/assistant/check", {});
      setModels(r.models);
      setChecked(true);
    } catch (e) {
      setError(e);
    }
  };
  const info = cfg.providers.find((p) => p.id === cfg.provider);
  const own = cfg.provider === "custom";
  const hasKey = cfg.key_saved || cfg.key_from_server;
  const canSave = own ? !!baseUrl.trim() && !!model.trim() : !!key || hasKey;
  const placeholder = cfg.provider === "anthropic" ? "sk-ant-…" : cfg.provider === "gemini" ? "AIza…" : "sk-…";
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("assistant.intro")}</p>
      <ErrorAlert error={error} />
      {saved && <div className="alert ok" role="status">✓ {cfg.ready ? t("assistant.on") : t("common.saved")}</div>}
      <div className="form-list">
        <SwitchRow label={t("assistant.toggle")} hint={t("assistant.toggle_hint")} checked={cfg.enabled}
          onChange={(v) => { if (!v || (!own && (hasKey || key)) || (own && cfg.ready)) void save(v); else setCfg({ ...cfg, enabled: true }); }} />
        {cfg.enabled && (
          <>
            <Row id="ai-provider" label={t("assistant.provider")} hint={t("assistant.provider_hint")}>
              <select id="ai-provider" value={cfg.provider} onChange={(e) => void choose(e.target.value)}>
                {cfg.providers.map((p) => <option key={p.id} value={p.id}>{flag(p.country)} {p.label}</option>)}
              </select>
            </Row>
            {own && (
              <Row id="ai-url" label={t("assistant.base_url")} hint={t("assistant.base_url_hint")}>
                <input id="ai-url" type="url" autoComplete="off" spellCheck={false} placeholder="http://host.docker.internal:11434/v1"
                  value={baseUrl} onChange={(e) => setBaseUrl(e.target.value.trim())} />
              </Row>
            )}
            <Row id="ai-key" label={t("assistant.key")} hint={cfg.key_from_server ? t("assistant.key_server") : own ? t("assistant.key_optional") : t("assistant.key_hint")}>
              <input id="ai-key" type="password" autoComplete="off" spellCheck={false} disabled={cfg.key_from_server}
                placeholder={cfg.key_saved ? "••••••••" : own ? "" : placeholder} value={key} onChange={(e) => setKey(e.target.value.trim())} />
            </Row>
            <Row id="ai-model" label={t("assistant.model_label")} hint={own ? t("assistant.model_own_hint") : t("assistant.model_hint", { model: info?.default_model ?? "" })}>
              <input id="ai-model" type="text" list="ai-models" autoComplete="off" spellCheck={false} value={model}
                onChange={(e) => setModel(e.target.value.trim())} />
              <datalist id="ai-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
            </Row>
          </>
        )}
      </div>
      {cfg.enabled && own && <p className="form-foot">{t("assistant.own_hint")}</p>}
      {cfg.enabled && info && !own && !cfg.key_from_server && (
        <p className="form-foot">
          <a href={info.key_url} target="_blank" rel="noreferrer noopener">{t("assistant.get_key", { provider: info.label })}</a>
          {" · "}<a href={info.models_url} target="_blank" rel="noreferrer noopener">{t("assistant.models_link")}</a>
          {" · "}<a href={info.pricing_url} target="_blank" rel="noreferrer noopener">{t("assistant.pricing_link")}</a>
          {!cfg.reads_photos && <><br />{t("assistant.no_photos")}</>}
          {!info.ask && <><br />{t("assistant.no_ask")}</>}
        </p>
      )}
      {checked && <div className="alert ok" role="status">✓ {models.length ? tn("assistant.key_works", models.length) : t("assistant.key_works_plain")}</div>}
      {cfg.ready && (
        <div className="form-list" style={{ marginTop: "0.75rem" }}>
          <SwitchRow label={t("assistant.weekly_brief")} hint={t("assistant.weekly_brief_hint")} checked={cfg.weekly_brief}
            onChange={(v) => void put({ enabled: true, weekly_brief: v })} />
        </div>
      )}
      {cfg.enabled && (
        <div className="actions" style={{ marginTop: "0.5rem" }}>
          <button className="btn" disabled={!canSave} onClick={() => void save(true)}>{t("common.save")}</button>
          {(own ? !!cfg.base_url : hasKey) && <button className="btn ghost" onClick={() => void check()}>{t("assistant.check_key")}</button>}
          {cfg.key_saved && <button className="btn ghost" onClick={() => void save(false, true)}>{t("assistant.forget_key")}</button>}
        </div>
      )}
      <h3>{t("assistant.privacy_title")}</h3>
      <ul className="muted bullets">
        <li>{t("assistant.privacy_1", { provider: info?.label ?? "" })}</li>
        <li>{t("assistant.privacy_2")}</li>
        <li>{t("assistant.privacy_3")}</li>
        <li>{t("assistant.privacy_4")}</li>
      </ul>
      <p className="form-foot">{t("assistant.model", { model: cfg.model })}</p>
    </>
  );
}

type Folder = { name: string; label: string };
type MailKind = "gmail" | "outlook" | "nhsmail" | "other";
type SignIn = { user_code: string; verification_uri: string; interval: number };

const GUIDE = "https://github.com/jc-universe87/GP-Locum-Manager/blob/main/docs/EMAIL_SETUP.md";

function mailKind(c: MailboxConfig): MailKind {
  if (c.provider === "microsoft") return c.ms_tenant === "organizations" ? "nhsmail" : "outlook";
  return !c.host || c.host === "imap.gmail.com" ? "gmail" : "other";
}

const KIND_LABEL: Record<MailKind, MessageKey | null> = { gmail: null, outlook: "mailbox.kind_outlook", nhsmail: null, other: "mailbox.kind_other" };

/** A blank account of the chosen kind (saved on the first Connect / Sign in). */
function blankAccount(kind: MailKind, clientId: string): MailboxConfig {
  const microsoft = kind === "outlook" || kind === "nhsmail";
  return {
    id: 0, label: "", enabled: false, provider: microsoft ? "microsoft" : "imap", ms_client_id: clientId,
    ms_tenant: kind === "nhsmail" ? "organizations" : "common", ms_signed_in: false, folder_labels: {},
    host: kind === "gmail" ? "imap.gmail.com" : "", port: 993, security: "ssl", username: "", password_set: false,
    folders: [], since_days: 90, auto_scan: true, last_scan_at: null, last_error: null, last_result: null,
  };
}

/** Booking emails: several mailboxes, each with its own folders and sign-in. */
function MailboxSection() {
  const { t, tn } = useT();
  const toast = useToast();
  const [accounts, setAccounts] = useState<MailboxConfig[] | null>(null);
  const [open, setOpen] = useState<MailboxConfig | null>(null);
  const [newKind, setNewKind] = useState<MailKind>("gmail");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.get<{ accounts: MailboxConfig[] }>("/settings/mailboxes").then((r) => setAccounts(r.accounts), setError);
  useEffect(() => { void load(); }, []);
  if (!accounts) return <ErrorAlert error={error} />;
  const errText = (code: string | null) => code && hasKey(`error.${code}`) ? t(`error.${code}` as MessageKey) : code;
  if (open) {
    return (
      <MailAccountEditor key={open.id || "new"} initial={open}
        onBack={() => { setOpen(null); void load(); }}
        onRemoved={(acc) => {
          setOpen(null);
          void load();
          toast({ text: t("mailbox.removed", { name: acc.label || acc.username }), undo: () => void api.post(`/settings/mailboxes/${acc.id}/restore`).then(load) });
        }} />
    );
  }
  const scanAll = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api.post<ScanResult>("/mailbox/scan");
      toast({ text: scanSummary(t, tn, r) });
    } catch (e) { setError(e); } finally { setBusy(false); void load(); }
  };
  const clientId = accounts.find((a) => a.ms_client_id)?.ms_client_id ?? "";
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("mailbox.intro")}</p>
      <ErrorAlert error={error} />
      <div className="form-list">
        {accounts.map((a) => {
          const kind = mailKind(a);
          const status = a.enabled && a.last_error
            ? t("mailbox.last_failed", { reason: errText(a.last_error) ?? "" })
            : a.enabled
              ? (a.last_scan_at ? t("mailbox.last_scan", { when: dateTime(a.last_scan_at) }) : t("mailbox.on"))
              : t("mailbox.off");
          return (
            <button key={a.id} type="button" className="list-row" onClick={() => setOpen(a)}>
              <span className="list-main">
                <span className="list-title">{a.label || a.username || t("mailbox.unnamed")}</span>
                <span className="list-sub" style={a.enabled && a.last_error ? { color: "var(--warn)" } : undefined}>
                  {KIND_LABEL[kind] ? t(KIND_LABEL[kind]!) : kind === "gmail" ? "Gmail" : "NHSmail"}
                  {a.enabled ? ` · ${tn("mailbox.n_folders", a.folders.length)}` : ""} · {status}
                </span>
              </span>
              <span className="chev"><Icon name="chevron" size={18} /></span>
            </button>
          );
        })}
        <div className="form-row">
          <label htmlFor="m-new">{t("mailbox.add")}</label>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <select id="m-new" value={newKind} onChange={(e) => setNewKind(e.target.value as MailKind)}>
              <option value="gmail">Gmail</option>
              <option value="outlook">{t("mailbox.kind_outlook")}</option>
              <option value="nhsmail">NHSmail</option>
              <option value="other">{t("mailbox.kind_other")}</option>
            </select>
            <button className="btn secondary" onClick={() => setOpen(blankAccount(newKind, clientId))}>
              <Icon name="plus" size={16} /> {t("mailbox.add_button")}
            </button>
          </div>
        </div>
      </div>
      {accounts.some((a) => a.enabled) && (
        <div className="actions" style={{ marginTop: "0.75rem" }}>
          <button className="btn secondary" disabled={busy} onClick={() => void scanAll()}>{busy ? t("mailbox.checking") : t("mailbox.check_now")}</button>
        </div>
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

function MailAccountEditor({ initial, onBack, onRemoved }: {
  initial: MailboxConfig; onBack: () => void; onRemoved: (acc: MailboxConfig) => void;
}) {
  const { t, tn } = useT();
  const confirm = useConfirm();
  const [cfg, setCfg] = useState<MailboxConfig>(initial);
  const kind = mailKind(initial);
  const [password, setPassword] = useState("");
  const [folders, setFolders] = useState<Folder[] | null>(null);
  const [signin, setSignin] = useState<SignIn | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const microsoft = cfg.provider === "microsoft";
  const base = `/settings/mailboxes/${cfg.id}`;
  // While a Microsoft sign-in is waiting, ask the server every few seconds whether it was approved.
  useEffect(() => {
    if (!signin || !cfg.id) return;
    let stop = false;
    let timer = 0;
    let wait = signin.interval;
    const tick = async () => {
      try {
        const r = await api.post<{ status: string; interval?: number; account?: MailboxConfig }>(`/settings/mailboxes/${cfg.id}/microsoft/poll`);
        if (stop) return;
        if (r.status === "done" && r.account) {
          setSignin(null);
          setCfg(r.account);
          setFolders((await api.post<{ folders: Folder[] }>(`/settings/mailboxes/${cfg.id}/folders`)).folders);
          return;
        }
        wait = r.interval ?? wait; // Microsoft may ask us to slow down
        timer = window.setTimeout(tick, wait * 1000);
      } catch (e) {
        if (!stop) { setSignin(null); setError(e); }
      }
    };
    timer = window.setTimeout(tick, wait * 1000);
    return () => { stop = true; window.clearTimeout(timer); };
  }, [signin, cfg.id]);
  const set = (patch: Partial<MailboxConfig>) => { setCfg({ ...cfg, ...patch }); setMsg(null); };
  const body = (over: Partial<MailboxConfig> = {}) => {
    const c = { ...cfg, ...over };
    return { enabled: c.enabled, provider: c.provider, label: c.label, ms_tenant: c.ms_tenant,
      host: c.host, port: c.port, security: c.security, username: c.username, password: password || null,
      folders: c.folders, since_days: c.since_days, auto_scan: c.auto_scan };
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null); setMsg(null);
    try { await fn(); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  /** Save the account (creating it the first time) and return its id. */
  const persist = async (over: Partial<MailboxConfig> = {}): Promise<MailboxConfig> => {
    const saved = cfg.id
      ? await api.put<MailboxConfig>(`/settings/mailboxes/${cfg.id}`, body(over))
      : await api.post<MailboxConfig>("/settings/mailboxes", body(over));
    setCfg(saved);
    setPassword("");
    return saved;
  };
  const connect = () => run(async () => {
    const saved = await persist({ enabled: false });
    setFolders((await api.post<{ folders: Folder[] }>(`/settings/mailboxes/${saved.id}/folders`)).folders);
  });
  const startSignIn = () => run(async () => {
    const saved = await persist({ enabled: false }); // keep edits made before signing in
    setCfg({ ...saved, ms_client_id: cfg.ms_client_id });
    setSignin(await api.post<SignIn>(`/settings/mailboxes/${saved.id}/microsoft/start`,
      { client_id: cfg.ms_client_id.trim(), tenant: cfg.ms_tenant }));
  });
  const reload = async () => {
    const list = await api.get<{ accounts: MailboxConfig[] }>("/settings/mailboxes");
    const me = list.accounts.find((a) => a.id === cfg.id);
    if (me) setCfg(me);
  };
  const signOut = () => run(async () => {
    await api.del(`${base}/microsoft`);
    await reload();
    setFolders(null);
  });
  const save = (enabled: boolean) => run(async () => {
    await persist({ enabled });
    setMsg(enabled ? t("mailbox.on") : t("common.saved"));
  });
  const scan = () => run(async () => {
    await persist();
    const r = await api.post<ScanResult>("/mailbox/scan");
    setMsg(scanSummary(t, tn, r));
    await reload();
  });
  const remove = async () => {
    if (cfg.id) {
      const name = cfg.label || cfg.username || cfg.host;
      const ok = await confirm({ title: t("trash.ask_mailbox", { name }), body: t("trash.ask_mailbox_body"), confirm: t("common.remove") });
      if (!ok) return;
    }
    await run(async () => {
      if (cfg.id) await api.del(base);
      onRemoved(cfg);
    });
  };
  const toggleFolder = (name: string, on: boolean) =>
    set({ folders: on ? [...cfg.folders, name] : cfg.folders.filter((f) => f !== name) });
  const shown: Folder[] = folders ?? cfg.folders.map((f) => ({ name: f, label: cfg.folder_labels[f] ?? f }));
  const lastErr = cfg.last_error && hasKey(`error.${cfg.last_error}`) ? t(`error.${cfg.last_error}` as MessageKey) : cfg.last_error;
  const copy = (text: string) => void navigator.clipboard?.writeText(text).catch(() => undefined);
  const kindName = KIND_LABEL[kind] ? t(KIND_LABEL[kind]!) : kind === "gmail" ? "Gmail" : "NHSmail";
  return (
    <>
      <button type="button" className="btn ghost" onClick={onBack} style={{ marginTop: "-0.5rem", paddingLeft: 0 }}>
        ‹ {t("mailbox.all_accounts")}
      </button>
      <h3 style={{ marginTop: "0.25rem" }}>{cfg.id ? cfg.label || cfg.username || kindName : t("mailbox.new_account", { kind: kindName })}</h3>
      <ErrorAlert error={error} />
      {msg && <div className="alert ok" role="status">{msg}</div>}
      {cfg.enabled && lastErr && <div className="alert warn" role="status">{t("mailbox.last_failed", { reason: lastErr })}</div>}
      <div className="form-list">
        <Row id="m-label" label={t("mailbox.label")} hint={t("mailbox.label_hint")}>
          <input id="m-label" type="text" value={cfg.label} maxLength={100} placeholder={cfg.username || kindName}
            onChange={(e) => set({ label: e.target.value })} />
        </Row>
        {kind === "other" && (
          <>
            <Row id="m-host" label={t("mailbox.host")} hint={t("mailbox.host_hint")}>
              <input id="m-host" type="text" autoCapitalize="none" spellCheck={false} value={cfg.host} placeholder="imap.example.com"
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
          </>
        )}
        {!microsoft && (
          <>
            <Row id="m-user" label={t("mailbox.username")}>
              <input id="m-user" type="email" autoCapitalize="none" value={cfg.username} onChange={(e) => set({ username: e.target.value.trim() })} />
            </Row>
            <Row id="m-pass" label={t("mailbox.password")} hint={t(kind === "gmail" ? "mailbox.gmail_hint" : "mailbox.password_hint")}>
              <input id="m-pass" type="password" autoComplete="new-password" placeholder={cfg.password_set ? "••••••••" : ""}
                value={password} onChange={(e) => setPassword(e.target.value)} />
            </Row>
          </>
        )}
        {microsoft && !cfg.ms_signed_in && (
          <Row id="m-app" label={t("mailbox.ms_app_id")} hint={t("mailbox.ms_app_id_hint")}>
            <input id="m-app" type="text" autoCapitalize="none" spellCheck={false} placeholder="00000000-0000-0000-0000-000000000000"
              value={cfg.ms_client_id} onChange={(e) => set({ ms_client_id: e.target.value.trim() })} />
          </Row>
        )}
      </div>
      {kind === "gmail" && (
        <p className="hint"><a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">{t("mailbox.gmail_link")}</a></p>
      )}
      {microsoft && (
        <p className="hint"><a href={GUIDE} target="_blank" rel="noreferrer">{t("mailbox.ms_guide")}</a></p>
      )}
      {kind === "nhsmail" && <div className="alert info" role="note">{t("mailbox.nhs_note")}</div>}

      {signin ? (
        <div className="card" role="status" style={{ marginTop: "0.5rem" }}>
          <p style={{ marginTop: 0 }}>{t("mailbox.ms_code_lead")}</p>
          <p style={{ fontSize: "1.6rem", fontWeight: 600, letterSpacing: "0.1em", margin: "0.25rem 0" }}>{signin.user_code}</p>
          <div className="actions">
            <a className="btn" href={signin.verification_uri} target="_blank" rel="noreferrer" onClick={() => copy(signin.user_code)}>{t("mailbox.ms_open")}</a>
            <button className="btn ghost" onClick={() => setSignin(null)}>{t("common.cancel")}</button>
          </div>
          <p className="form-foot">{t("mailbox.ms_waiting")}</p>
        </div>
      ) : (
        <div className="actions" style={{ marginTop: "0.5rem" }}>
          {microsoft && cfg.ms_signed_in ? (
            <>
              <span className="muted">{t("mailbox.ms_signed_in", { email: cfg.username })}</span>
              <button className="btn secondary" disabled={busy} onClick={() => run(async () => setFolders((await api.post<{ folders: Folder[] }>(`${base}/folders`)).folders))}>{t("mailbox.choose_folders")}</button>
              <button className="btn ghost" disabled={busy} onClick={signOut}>{t("mailbox.ms_sign_out")}</button>
            </>
          ) : microsoft ? (
            <button className="btn secondary" disabled={busy || !cfg.ms_client_id.trim()} onClick={startSignIn}>{t("mailbox.ms_sign_in")}</button>
          ) : (
            <button className="btn secondary" disabled={busy || (kind === "other" && !cfg.host) || !cfg.username || (!password && !cfg.password_set)} onClick={connect}>
              {busy && !folders ? t("mailbox.connecting") : t("mailbox.connect")}
            </button>
          )}
        </div>
      )}

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
      {cfg.id > 0 && (
        <div className="actions" style={{ marginTop: "1.5rem" }}>
          <button className="btn ghost" disabled={busy} onClick={remove} style={{ color: "var(--err)" }}>{t("mailbox.remove")}</button>
        </div>
      )}
    </>
  );
}

/** Household profiles (admin only): each person has their own, separate Locuvi. */
function ProfilesSection({ me }: { me: HouseholdProfile }) {
  const { t } = useT();
  const toast = useToast();
  const [list, setList] = useState<{ profiles: HouseholdProfile[]; removed: HouseholdProfile[] } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<HouseholdProfile | null>(null);
  const [removing, setRemoving] = useState<HouseholdProfile | null>(null);
  const load = () => api.get<{ profiles: HouseholdProfile[]; removed: HouseholdProfile[] }>("/profiles").then(setList, setError);
  useEffect(() => { void load(); }, []);
  if (!list) return <ErrorAlert error={error} />;
  const restore = async (p: HouseholdProfile) => {
    setError(null);
    try { await api.post(`/profiles/${p.id}/restore`); await load(); toast({ text: t("profiles.restored", { name: p.name }) }); }
    catch (e) { setError(e); }
  };
  const remove = async (p: HouseholdProfile) => {
    setError(null);
    try {
      await api.del(`/profiles/${p.id}`);
      setRemoving(null);
      await load();
      toast({ text: t("profiles.removed", { name: p.name }), undo: () => void restore(p) });
    } catch (e) { setError(e); }
  };
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("profiles.intro")}</p>
      {!me.password_set && <div className="alert info" role="note">{t("profiles.set_own_password")}</div>}
      <ErrorAlert error={error} />
      <div className="form-list">
        {list.profiles.map((p) => (
          <button key={p.id} type="button" className="list-row" onClick={() => setEditing(p)}>
            <span className="list-main">
              <span className="list-title">{p.name}{p.id === me.id ? ` (${t("profiles.you")})` : ""}</span>
              <span className="list-sub">{p.is_admin ? t("profiles.admin") : t("profiles.member")}</span>
            </span>
            <span className="chev"><Icon name="chevron" size={18} /></span>
          </button>
        ))}
        <button type="button" className="list-row" onClick={() => setAdding(true)} style={{ color: "var(--steel)", fontWeight: 600 }}>
          <Icon name="plus" size={18} /> {t("profiles.add")}
        </button>
      </div>
      {list.removed.length > 0 && (
        <>
          <h3>{t("profiles.removed_title")}</h3>
          <p className="muted" style={{ marginTop: 0 }}>{t("profiles.removed_hint")}</p>
          <div className="form-list">
            {list.removed.map((p) => (
              <div key={p.id} className="form-row" style={{ gridTemplateColumns: "1fr auto" }}>
                <span>{p.name}<span className="hint" style={{ display: "block" }}>{t("profiles.removed_on", { when: dateTime(p.deleted_at ?? "") })}</span></span>
                <button className="btn secondary small" onClick={() => void restore(p)}>{t("profiles.restore")}</button>
              </div>
            ))}
          </div>
        </>
      )}
      {adding && <ProfileSheet onClose={() => setAdding(false)} onSaved={async (p) => { setAdding(false); await load(); toast({ text: t("profiles.added", { name: p.name }) }); }} />}
      {editing && (
        <ProfileSheet profile={editing} canRemove={!editing.is_admin && editing.id !== me.id}
          onClose={() => setEditing(null)}
          onRemove={() => { setRemoving(editing); setEditing(null); }}
          onSaved={async () => { setEditing(null); await load(); toast({ text: t("common.saved") }); }} />
      )}
      {removing && (
        <Dialog open title={t("profiles.remove_title", { name: removing.name })} onClose={() => setRemoving(null)}
          footer={<>
            <button className="btn ghost" autoFocus onClick={() => setRemoving(null)}>{t("common.cancel")}</button>
            <button className="btn danger" onClick={() => void remove(removing)}>{t("profiles.remove_confirm")}</button>
          </>}>
          <p style={{ marginTop: 0 }}>{t("profiles.remove_body", { name: removing.name })}</p>
        </Dialog>
      )}
    </>
  );
}

function ProfileSheet({ profile, canRemove = false, onClose, onSaved, onRemove }: {
  profile?: HouseholdProfile; canRemove?: boolean; onClose: () => void; onSaved: (p: HouseholdProfile) => void | Promise<void>; onRemove?: () => void;
}) {
  const { t } = useT();
  const [name, setName] = useState(profile?.name ?? "");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const mismatch = again.length > 0 && password !== again;
  const passwordOk = profile ? (!password || (password.length >= 10 && password === again)) : (password.length >= 10 && password === again);
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const body: Record<string, string> = {};
      if (!profile || name.trim() !== profile.name) body.name = name.trim();
      if (password) body.password = password;
      const p = profile
        ? await api.patch<HouseholdProfile>(`/profiles/${profile.id}`, body)
        : await api.post<HouseholdProfile>("/profiles", body);
      await onSaved(p);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open title={profile ? profile.name : t("profiles.add")} onClose={onClose}
      footer={<>
        {canRemove && onRemove && <button className="btn ghost" style={{ color: "var(--err)", marginRight: "auto" }} onClick={onRemove}>{t("profiles.remove")}</button>}
        <button className="btn ghost" onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn" disabled={busy || !name.trim() || !passwordOk} onClick={() => void save()}>{profile ? t("common.save") : t("profiles.add_button")}</button>
      </>}>
      <ErrorAlert error={error} />
      <div className="form-list">
        <Row id="pf-name" label={t("profiles.name")} hint={t("profiles.name_hint")}>
          <input id="pf-name" type="text" maxLength={40} autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />
        </Row>
        <Row id="pf-pass" label={profile ? t("profiles.new_password") : t("profiles.password")} hint={t(profile ? "profiles.reset_hint" : "password.new_hint")}>
          <input id="pf-pass" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Row>
        <Row id="pf-again" label={t("password.again")}>
          <input id="pf-again" type="password" autoComplete="new-password" value={again} aria-invalid={mismatch} onChange={(e) => setAgain(e.target.value)} />
        </Row>
      </div>
      {mismatch && <p className="hint" style={{ color: "var(--err)" }}>{t("password.mismatch")}</p>}
    </Dialog>
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
  const [exportFees, setExportFees] = useState(false);
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
  // Google and Outlook on the web fetch the feed from their own servers (internet only).
  const google = `https://calendar.google.com/calendar/render?cid=${encodeURIComponent(webcal)}`;
  const outlook = `https://outlook.live.com/calendar/0/addfromweb?url=${encodeURIComponent(url)}&name=${encodeURIComponent(t("calendar.feed_name"))}`;
  const office = `https://outlook.office.com/calendar/0/addfromweb?url=${encodeURIComponent(url)}&name=${encodeURIComponent(t("calendar.feed_name"))}`;
  const download = async (fmt: "ics" | "csv") => {
    try {
      downloadBlob(await api.blob("GET", `/calendar/export.${fmt}?fees=${exportFees}`), `locum-sessions.${fmt}`);
    } catch (e) {
      setError(e);
    }
  };
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("calendar.intro")}</p>
      <ErrorAlert error={error} />
      {POCKET ? (
        <div className="alert info">{t("pocket.calendar_note")}</div>
      ) : (
      <>
      <h3>{t("calendar.live_title")}</h3>
      <p className="hint" style={{ marginTop: 0 }}>{t("calendar.live_hint")}</p>
      <div className="form-list">
        <SwitchRow label={t("calendar.toggle")} checked={cfg.enabled} onChange={(v) => void put({ enabled: v })} />
        {cfg.enabled && (
          <SwitchRow label={t("calendar.fees")} hint={t("calendar.fees_hint")} checked={cfg.include_fees}
            onChange={(v) => void put({ enabled: true, include_fees: v })} />
        )}
      </div>
      {cfg.enabled && url && (
        <>
          <div className="actions wrap" style={{ marginTop: "0.75rem" }}>
            <a className="btn" href={webcal}>{t("calendar.apple")}</a>
            <a className="btn secondary" href={google} target="_blank" rel="noreferrer noopener">{t("calendar.google")}</a>
            <a className="btn secondary" href={outlook} target="_blank" rel="noreferrer noopener">{t("calendar.outlook")}</a>
            <a className="btn secondary" href={office} target="_blank" rel="noreferrer noopener">{t("calendar.office")}</a>
          </div>
          <p className="hint">{t("calendar.apps_hint")}</p>
          <h3>{t("calendar.link")}</h3>
          <div className="form-list">
            <div className="form-row stacked"><code style={{ wordBreak: "break-all" }}>{url}</code></div>
          </div>
          <div className="actions" style={{ marginTop: "0.5rem" }}>
            <button className="btn secondary" onClick={() => {
              void navigator.clipboard?.writeText(url).then(() => setCopied(true), () => undefined);
            }}>{copied ? t("ask.copied") : t("calendar.copy")}</button>
            <button className="btn ghost" onClick={() => void put({ enabled: true, regenerate: true })}>{t("calendar.new_link")}</button>
          </div>
          <p className="form-foot">{t("calendar.private")}</p>
        </>
      )}
      </>
      )}
      <h3>{t("calendar.export_title")}</h3>
      <p className="hint" style={{ marginTop: 0 }}>{t("calendar.export_hint")}</p>
      <div className="form-list">
        <SwitchRow label={t("calendar.export_fees")} checked={exportFees} onChange={setExportFees} />
      </div>
      <div className="actions wrap" style={{ marginTop: "0.5rem" }}>
        <button className="btn secondary" onClick={() => void download("ics")}><Icon name="download" size={18} /> {t("calendar.export_ics")}</button>
        <button className="btn secondary" onClick={() => void download("csv")}><Icon name="download" size={18} /> {t("calendar.export_csv")}</button>
      </div>
    </>
  );
}

interface DesktopState { available: boolean; phone_access?: boolean; update_check?: boolean; keeps_running?: boolean; listening?: boolean; restart_needed?: boolean; own_password?: boolean; addresses?: string[] }

function AppsSection() {
  const { t } = useT();
  const [desk, setDesk] = useState<DesktopState | null>(null);
  const [quit, setQuit] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const native = nativeApp();
  useEffect(() => {
    api.get<DesktopState>("/desktop").then(setDesk, () => setDesk({ available: false }));
  }, []);
  const phones = async (on: boolean) => {
    try {
      setError(null);
      setDesk(await api.put<DesktopState>("/desktop", { phone_access: on }));
    } catch (e) {
      setError(e);
    }
  };
  if (quit) {
    return (
      <div className="pocket-opening" role="status">
        <p><strong>{t("apps.stopped")}</strong></p>
        <p className="muted">{t("apps.stopped_hint")}</p>
      </div>
    );
  }
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("apps.intro")}</p>
      <ErrorAlert error={error} />
      {POCKET && (
        <>
          <h3>{t("apps.this_app")}</h3>
          <p className="hint" style={{ marginTop: 0 }}>{t("pocket.on_this_phone")} <Link to="/settings/sync">{t("settings.s_sync")}</Link></p>
          {native && (
            <div className="actions" style={{ marginTop: "0.5rem" }}>
              <button className="btn secondary" onClick={() => native.changeServer()}>{t("pocket.use_computer")}</button>
            </div>
          )}
        </>
      )}
      {native && !POCKET && (
        <>
          <h3>{t("apps.this_app")}</h3>
          <div className="form-list">
            <div className="form-row stacked"><span>{t("apps.connected_to")}</span><code style={{ wordBreak: "break-all" }}>{native.serverUrl()}</code></div>
          </div>
          <div className="actions" style={{ marginTop: "0.5rem" }}>
            <button className="btn secondary" onClick={() => native.changeServer()}>{t("apps.change_server")}</button>
          </div>
        </>
      )}
      {desk?.available && (
        <>
          <h3>{t("apps.computer_title")}</h3>
          <div className="form-list">
            <SwitchRow label={t("apps.phone_access")} hint={t("apps.phone_access_hint")} checked={!!desk.phone_access}
              onChange={(v) => void phones(v)} />
          </div>
          {!desk.own_password && (
            <p className="form-foot">{t("apps.password_first")} <Link to="/settings/password">{t("settings.s_password")}</Link></p>
          )}
          {desk.restart_needed && <div className="alert info" style={{ marginTop: "0.5rem" }}>{t("apps.restart")}</div>}
          <div className="actions wrap" style={{ marginTop: "0.75rem" }}>
            <button className="btn secondary" onClick={() => void api.post("/desktop/open-folder").catch(setError)}>{t("apps.open_folder")}</button>
            <button className="btn ghost" onClick={() => void api.post("/desktop/quit").then(() => setQuit(true), setError)}>{t("apps.quit")}</button>
          </div>
          <p className="form-foot">{desk.keeps_running ? t("apps.keeps_running") : t("apps.stops_itself")}</p>
          {desk.listening && desk.addresses && desk.addresses.length > 0 && (
            <>
              <p className="hint">{t("apps.addresses")}</p>
              <div className="form-list">
                {desk.addresses.map((a) => <div key={a} className="form-row stacked"><code>{a}</code></div>)}
              </div>
            </>
          )}
        </>
      )}
      {(desk?.available || POCKET || native) && <UpdatesSection computer={desk?.available ? desk : null} />}
      {!desk?.available && !native && !POCKET && (
        <>
          <h3>{t("apps.address_title")}</h3>
          <div className="form-list">
            <div className="form-row stacked"><code style={{ wordBreak: "break-all" }}>{window.location.origin}</code></div>
          </div>
          <p className="form-foot">{t("apps.address_hint")}</p>
        </>
      )}
      <h3>{t("apps.get_title")}</h3>
      <div className="form-list">
        <a className="list-row" href={DOWNLOADS.android} target="_blank" rel="noreferrer noopener">
          <span className="list-main"><span className="list-title">{t("apps.android")}</span><span className="list-sub">{t("apps.android_sub")}</span></span>
          <span className="chev"><Icon name="download" size={18} /></span>
        </a>
        <a className="list-row" href={DOWNLOADS.iphone} target="_blank" rel="noreferrer noopener">
          <span className="list-main"><span className="list-title">{t("apps.iphone")}</span><span className="list-sub">{t("apps.iphone_sub")}</span></span>
          <span className="chev"><Icon name="chevron" size={18} /></span>
        </a>
        <a className="list-row" href={DOWNLOADS.windows} target="_blank" rel="noreferrer noopener">
          <span className="list-main"><span className="list-title">{t("apps.windows")}</span><span className="list-sub">{t("apps.windows_sub")}</span></span>
          <span className="chev"><Icon name="download" size={18} /></span>
        </a>
        <a className="list-row" href={DOWNLOADS.mac} target="_blank" rel="noreferrer noopener">
          <span className="list-main"><span className="list-title">{t("apps.mac")}</span><span className="list-sub">{t("apps.mac_sub")}</span></span>
          <span className="chev"><Icon name="download" size={18} /></span>
        </a>
      </div>
      <p className="form-foot"><a href={APPS_GUIDE} target="_blank" rel="noreferrer noopener">{t("apps.guide")}</a></p>
    </>
  );
}

function PasswordSection({ profile }: { profile: HouseholdProfile | null }) {
  const { t } = useT();
  const needCurrent = profile?.password_set ?? true;
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
        {needCurrent && (
          <Row id="pw-cur" label={t("password.current")}>
            <input id="pw-cur" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          </Row>
        )}
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
        <button className="btn" disabled={(needCurrent && !current) || next.length < 10 || next !== again} onClick={save}>{t("password.save")}</button>
      </div>
      <p className="form-foot">{t(profile && !profile.is_admin ? "password.forgot_member" : "password.forgot")}</p>
    </>
  );
}
