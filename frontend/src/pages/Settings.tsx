import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ErrorAlert, Field } from "../components/ui";
import { hasKey, useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api } from "../lib/api";
import { pct, todayLondon, ukDate } from "../lib/format";
import { suggestYearPrefix } from "../lib/numbering";
import type { Numbering, Policy, Profile, WebDavConfig } from "../lib/types";

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="card" id={id} aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`}>{title}</h2>
      {children}
    </section>
  );
}

function useSaveState() {
  const [error, setError] = useState<unknown>(null);
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setOk(false);
    try {
      await fn();
      setOk(true);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return { error, ok, busy, run };
}

export default function SettingsPage() {
  const { t } = useT();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.get<Profile>("/settings/profile").then(setProfile, setError);
  }, []);

  return (
    <>
      <h1>{t("settings.title")}</h1>
      <nav className="section-nav" aria-label={t("settings.title")}>
        <a href="#sender">{t("settings.sender")}</a>
        <a href="#numbering">{t("settings.numbering")}</a>
        <a href="#pension">{t("settings.pension")}</a>
        <a href="#storage">{t("settings.storage")}</a>
      </nav>
      <ErrorAlert error={error} />
      {profile && (
        <>
          <SenderSection profile={profile} onSaved={setProfile} />
          <NumberingSection profile={profile} onSaved={setProfile} />
          <PensionSection profile={profile} onSaved={setProfile} />
        </>
      )}
      <StorageSection />
    </>
  );
}

function profileBody(p: Profile, accountNumber: string | null) {
  const { bank_account_number_masked: _m, bank_account_number_set: _s, ...rest } = p;
  return { ...rest, bank_account_number: accountNumber };
}

function SenderSection({ profile, onSaved }: { profile: Profile; onSaved: (p: Profile) => void }) {
  const { t } = useT();
  const [p, setP] = useState(profile);
  const [acct, setAcct] = useState("");
  const st = useSaveState();
  const set = (patch: Partial<Profile>) => setP({ ...p, ...patch });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void st.run(async () => {
      const saved = await api.put<Profile>("/settings/profile", profileBody({ ...profile, ...pick(p) }, acct.trim() || null));
      setAcct("");
      setP(saved);
      onSaved(saved);
    });
  };
  const pick = (x: Profile) => ({
    legal_name: x.legal_name, trading_name: x.trading_name, designation: x.designation, address_lines: x.address_lines,
    postcode: x.postcode, email: x.email, phone: x.phone, bank_account_holder: x.bank_account_holder, bank_sort_code: x.bank_sort_code,
  });
  return (
    <Section id="sender" title={t("settings.sender")}>
      <p className="hint" style={{ marginTop: 0 }}>{t("settings.sender_help")}</p>
      <form onSubmit={submit} className="grid grid-2">
        <Field id="s-legal" label={t("settings.legal_name")}>
          <input id="s-legal" type="text" autoComplete="name" value={p.legal_name} onChange={(e) => set({ legal_name: e.target.value })} />
        </Field>
        <Field id="s-trading" label={t("settings.trading_name")} optional>
          <input id="s-trading" type="text" value={p.trading_name ?? ""} onChange={(e) => set({ trading_name: e.target.value })} />
        </Field>
        <Field id="s-desig" label={t("settings.designation")} optional className="span-2">
          <input id="s-desig" type="text" value={p.designation} onChange={(e) => set({ designation: e.target.value })} />
        </Field>
        <Field id="s-addr" label={t("settings.address")} className="span-2">
          <textarea id="s-addr" autoComplete="street-address" value={p.address_lines} onChange={(e) => set({ address_lines: e.target.value })} />
        </Field>
        <Field id="s-pc" label={t("settings.postcode")}>
          <input id="s-pc" type="text" autoComplete="postal-code" value={p.postcode} onChange={(e) => set({ postcode: e.target.value })} />
        </Field>
        <Field id="s-email" label={t("settings.email")}>
          <input id="s-email" type="email" autoComplete="email" value={p.email} onChange={(e) => set({ email: e.target.value })} />
        </Field>
        <Field id="s-phone" label={t("settings.phone")} optional>
          <input id="s-phone" type="tel" autoComplete="tel" value={p.phone ?? ""} onChange={(e) => set({ phone: e.target.value })} />
        </Field>
        <Field id="s-holder" label={t("settings.bank_holder")}>
          <input id="s-holder" type="text" value={p.bank_account_holder} onChange={(e) => set({ bank_account_holder: e.target.value })} />
        </Field>
        <Field id="s-sort" label={t("settings.sort_code")}>
          <input id="s-sort" type="text" inputMode="numeric" autoComplete="off" placeholder="00-00-00" value={p.bank_sort_code}
            onChange={(e) => set({ bank_sort_code: e.target.value })} />
        </Field>
        <Field id="s-acct" label={t("settings.account_number")}
          hint={profile.bank_account_number_set ? t("settings.account_saved", { masked: profile.bank_account_number_masked }) : undefined}>
          <input id="s-acct" type="text" inputMode="numeric" autoComplete="off" maxLength={8} value={acct} onChange={(e) => setAcct(e.target.value)} />
        </Field>
        <div className="span-2">
          <ErrorAlert error={st.error} />
          <div className="actions">
            <button className="btn" disabled={st.busy}>{t("common.save")}</button>
            {st.ok && <span className="tick" role="status">✓ {t("common.saved")}</span>}
          </div>
        </div>
      </form>
    </Section>
  );
}

function NumberingSection({ profile, onSaved }: { profile: Profile; onSaved: (p: Profile) => void }) {
  const { t } = useT();
  const [n, setN] = useState<Numbering | null>(null);
  const [terms, setTerms] = useState(String(profile.payment_terms_days));
  const [vat, setVat] = useState(profile.vat_status);
  const st = useSaveState();
  useEffect(() => {
    api.get<Numbering>("/settings/numbering").then(setN, () => undefined);
  }, []);
  if (!n) return null;
  const preview = `${n.prefix}${String(n.next_number).padStart(n.padding, "0")}`;
  const suggested = suggestYearPrefix(n.prefix, Number(todayLondon().slice(0, 4)));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void st.run(async () => {
      setN(await api.put<Numbering>("/settings/numbering", { prefix: n.prefix, next_number: n.next_number, padding: n.padding }));
      const saved = await api.put<Profile>("/settings/profile",
        profileBody({ ...profile, payment_terms_days: Number(terms), vat_status: vat }, null));
      onSaved(saved);
    });
  };
  return (
    <Section id="numbering" title={t("settings.numbering")}>
      <p className="hint" style={{ marginTop: 0 }}>{t("settings.numbering_help")}</p>
      <form onSubmit={submit} className="grid grid-3">
        <Field id="n-prefix" label={t("settings.prefix")}>
          <input id="n-prefix" type="text" value={n.prefix} onChange={(e) => setN({ ...n, prefix: e.target.value })} />
        </Field>
        <Field id="n-next" label={t("settings.next_number")}>
          <input id="n-next" type="number" min={1} value={n.next_number} onChange={(e) => setN({ ...n, next_number: Number(e.target.value) })} />
        </Field>
        <Field id="n-pad" label={t("settings.padding")}>
          <input id="n-pad" type="number" min={1} max={8} value={n.padding} onChange={(e) => setN({ ...n, padding: Number(e.target.value) })} />
        </Field>
        <p className="span-2" style={{ margin: 0 }}><strong>{t("settings.number_preview", { number: preview })}</strong></p>
        <div />
        {suggested && (
          <div className="alert info span-2" role="status" style={{ margin: 0 }}>
            {t("settings.year_prefix_hint", { prefix: suggested })}{" "}
            <button type="button" className="btn secondary small"
              onClick={() => setN({ ...n, prefix: suggested, next_number: 1 })}>
              {t("settings.year_prefix_apply", { number: `${suggested}${"1".padStart(n.padding, "0")}` })}
            </button>
          </div>
        )}
        <Field id="n-terms" label={t("settings.terms")}>
          <input id="n-terms" type="number" min={0} max={365} value={terms} onChange={(e) => setTerms(e.target.value)} />
        </Field>
        <Field id="n-vat" label={t("settings.vat_status")} hint={t("settings.vat_help")} className="span-2">
          <select id="n-vat" value={vat} onChange={(e) => setVat(e.target.value as Profile["vat_status"])}>
            <option value="not_vat_registered">{t("settings.vat_not_registered")}</option>
            <option value="vat_registered">{t("settings.vat_registered")}</option>
          </select>
        </Field>
        <div className="span-2">
          <ErrorAlert error={st.error} />
          <div className="actions">
            <button className="btn" disabled={st.busy}>{t("common.save")}</button>
            {st.ok && <span className="tick" role="status">✓ {t("common.saved")}</span>}
          </div>
        </div>
      </form>
    </Section>
  );
}

function PensionSection({ profile, onSaved }: { profile: Profile; onSaved: (p: Profile) => void }) {
  const { t } = useT();
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [def, setDef] = useState(profile.pension_default_enabled);
  const [np, setNp] = useState({ effective_from: "", employer_rate: "", pensionable_fraction: "0.90", label: "" });
  const st = useSaveState();
  const add = useSaveState();
  const load = () => api.get<Policy[]>("/settings/pension-policies").then(setPolicies, () => undefined);
  useEffect(() => {
    void load();
  }, []);
  return (
    <Section id="pension" title={t("settings.pension")}>
      <p className="hint" style={{ marginTop: 0 }}>{t("settings.pension_help")}</p>
      <label className="check">
        <input type="checkbox" checked={def} onChange={(e) => {
          const v = e.target.checked;
          setDef(v);
          void st.run(async () => onSaved(await api.put<Profile>("/settings/profile",
            profileBody({ ...profile, pension_default_enabled: v }, null))));
        }} />
        <span>{t("settings.pension_default")}</span>
      </label>
      <ErrorAlert error={st.error} />
      <h3 style={{ marginTop: "1rem" }}>{t("settings.policies")}</h3>
      <div className="table-wrap">
        <table className="list">
          <thead>
            <tr>
              <th>{t("settings.policy_from")}</th>
              <th>{t("settings.policy_rate")}</th>
              <th>{t("settings.policy_fraction")}</th>
              <th>{t("settings.policy_label")}</th>
            </tr>
          </thead>
          <tbody>
            {policies.map((p) => (
              <tr key={p.id}>
                <td>{ukDate(p.effective_from)}</td>
                <td>{pct(p.employer_rate)}</td>
                <td>{pct(p.pensionable_fraction)}</td>
                <td>{p.label}{p.in_use && <div className="hint">{t("settings.policy_in_use")}</div>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="grid grid-3" style={{ marginTop: "1rem" }} onSubmit={(e) => {
        e.preventDefault();
        void add.run(async () => {
          await api.post("/settings/pension-policies", np);
          setNp({ effective_from: "", employer_rate: "", pensionable_fraction: "0.90", label: "" });
          await load();
        });
      }}>
        <Field id="pp-from" label={t("settings.policy_from")}>
          <input id="pp-from" type="date" required value={np.effective_from} onChange={(e) => setNp({ ...np, effective_from: e.target.value })} />
        </Field>
        <Field id="pp-rate" label={t("settings.policy_rate")} hint={t("settings.policy_rate_hint")}>
          <input id="pp-rate" type="text" inputMode="decimal" required value={np.employer_rate} onChange={(e) => setNp({ ...np, employer_rate: e.target.value })} />
        </Field>
        <Field id="pp-frac" label={t("settings.policy_fraction")}>
          <input id="pp-frac" type="text" inputMode="decimal" required value={np.pensionable_fraction} onChange={(e) => setNp({ ...np, pensionable_fraction: e.target.value })} />
        </Field>
        <Field id="pp-label" label={t("settings.policy_label")} optional className="span-2">
          <input id="pp-label" type="text" value={np.label} onChange={(e) => setNp({ ...np, label: e.target.value })} />
        </Field>
        <div style={{ alignSelf: "end" }}>
          <button className="btn secondary" disabled={add.busy}>{t("settings.policy_add")}</button>
        </div>
      </form>
      <ErrorAlert error={add.error} />
    </Section>
  );
}

function StorageSection() {
  const { t } = useT();
  const [cfg, setCfg] = useState<WebDavConfig | null>(null);
  const [password, setPassword] = useState("");
  const [test, setTest] = useState<{ ok: boolean; error_class?: string; folder_exists?: boolean } | null>(null);
  const [testing, setTesting] = useState(false);
  const st = useSaveState();
  useEffect(() => {
    api.get<WebDavConfig>("/storage/webdav").then(setCfg, () => undefined);
  }, []);
  if (!cfg) return null;
  const set = (patch: Partial<WebDavConfig>) => {
    setCfg({ ...cfg, ...patch });
    setTest(null);
  };
  const body = () => ({
    enabled: cfg.enabled,
    target_url: cfg.target_url,
    username: cfg.username,
    base_path: cfg.base_path,
    auto_upload: cfg.auto_upload,
    password: password ? password : null,
  });
  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      const { enabled: _e, auto_upload: _a, ...rest } = body();
      setTest(await api.post("/storage/webdav/test", rest));
    } catch (e) {
      st.run(async () => { throw e; });
    } finally {
      setTesting(false);
    }
  };
  const save = (e: FormEvent) => {
    e.preventDefault();
    void st.run(async () => {
      setCfg(await api.put<WebDavConfig>("/storage/webdav", body()));
      setPassword("");
    });
  };
  const reason = (cls?: string) => (cls && hasKey(`archive_error.${cls}`) ? t(`archive_error.${cls}` as MessageKey) : cls ?? "");
  return (
    <Section id="storage" title={t("settings.storage")}>
      <h3>{t("settings.local")}</h3>
      <p className="hint" style={{ marginTop: 0 }}>{t("settings.local_help")}</p>
      <h3 style={{ marginTop: "1rem" }}>{t("settings.webdav")}</h3>
      <form onSubmit={save} className="grid grid-2">
        <label className="check span-2">
          <input type="checkbox" checked={cfg.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
          <span>{t("settings.webdav_enabled")}</span>
        </label>
        <Field id="w-url" label={t("settings.webdav_url")} hint={t("settings.webdav_url_hint")} className="span-2">
          <input id="w-url" type="url" autoComplete="off" spellCheck={false} value={cfg.target_url} onChange={(e) => set({ target_url: e.target.value })} />
        </Field>
        <Field id="w-user" label={t("settings.webdav_user")}>
          <input id="w-user" type="text" autoComplete="off" value={cfg.username} onChange={(e) => set({ username: e.target.value })} />
        </Field>
        <Field id="w-pass" label={t("settings.webdav_password")}
          hint={cfg.password_source === "secret_file" ? t("settings.webdav_password_file")
            : cfg.password_set ? t("settings.webdav_password_saved") : t("settings.webdav_password_hint")}>
          <input id="w-pass" type="password" autoComplete="new-password" value={password}
            disabled={cfg.password_source === "secret_file"} onChange={(e) => { setPassword(e.target.value); setTest(null); }} />
        </Field>
        <Field id="w-folder" label={t("settings.webdav_folder")}
          hint={t("settings.webdav_privacy", { example: `${cfg.base_path || "Locuvi/Invoices"}/2026/10/LOC-2026-0001.pdf` })} className="span-2">
          <input id="w-folder" type="text" value={cfg.base_path} onChange={(e) => set({ base_path: e.target.value })} />
        </Field>
        <label className="check span-2">
          <input type="checkbox" checked={cfg.auto_upload} onChange={(e) => set({ auto_upload: e.target.checked })} />
          <span>{t("settings.webdav_auto")}</span>
        </label>
        <div className="span-2">
          {test && (
            <div className={`alert ${test.ok ? "ok" : "error"}`} role="status">
              {test.ok
                ? t("settings.webdav_test_ok", { folder: test.folder_exists ? t("settings.webdav_folder_exists") : t("settings.webdav_folder_missing") })
                : t("settings.webdav_test_failed", { reason: reason(test.error_class) })}
            </div>
          )}
          <ErrorAlert error={st.error} />
          <div className="actions">
            <button type="button" className="btn secondary" onClick={runTest} disabled={testing || !cfg.target_url}>
              {testing ? t("settings.webdav_testing") : t("settings.webdav_test")}
            </button>
            <button className="btn" disabled={st.busy}>{t("common.save")}</button>
            {st.ok && <span className="tick" role="status">✓ {t("common.saved")}</span>}
          </div>
        </div>
      </form>
      {cfg.enabled && cfg.password_set && <ArchiveBacklog />}
    </Section>
  );
}

interface Backlog {
  not_archived: number;
  pending: number;
  synced: number;
  failed: number;
  conflict: number;
}

function ArchiveBacklog() {
  const { t } = useT();
  const [b, setB] = useState<Backlog | null>(null);
  const [queued, setQueued] = useState<number | null>(null);
  const st = useSaveState();
  useEffect(() => {
    api.get<Backlog>("/storage/webdav/backlog").then(setB, () => undefined);
  }, []);
  if (!b) return null;
  const todo = b.not_archived + b.failed;
  const run = () =>
    void st.run(async () => {
      const res = await api.post<{ queued: number; backlog: Backlog }>("/storage/webdav/archive-all");
      setQueued(res.queued);
      setB(res.backlog);
    });
  return (
    <div style={{ marginTop: "1.25rem" }}>
      <h3>{t("settings.archive_all_title")}</h3>
      <p className="hint" style={{ marginTop: 0 }}>
        {t("settings.archive_all_counts", { synced: b.synced, pending: b.pending, todo, conflict: b.conflict })}
      </p>
      {queued !== null && <div className="alert ok" role="status">{t("settings.archive_all_queued", { n: queued })}</div>}
      <ErrorAlert error={st.error} />
      <button type="button" className="btn secondary" onClick={run} disabled={st.busy || todo === 0}>
        {t("settings.archive_all_button", { n: todo })}
      </button>
    </div>
  );
}
