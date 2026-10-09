import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { RateFields, rateBody, rateFieldsValid } from "../components/RateFields";
import { ErrorAlert, Logo } from "../components/ui";
import { useT } from "../i18n";
import { api } from "../lib/api";
import type { Practice, Profile } from "../lib/types";

type Step = 0 | 1 | 2;

export default function WelcomePage() {
  const { t } = useT();
  const nav = useNavigate();
  const [step, setStep] = useState<Step>(0);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [me, setMe] = useState({ legal_name: "", address_lines: "", postcode: "", email: "" });
  const [bank, setBank] = useState({ bank_account_holder: "", bank_sort_code: "", bank_account_number: "" });
  const [hasAccount, setHasAccount] = useState(false);
  const [practice, setPractice] = useState({
    name: "", billing_address: "", default_rate: "", default_unit: "am", hourly_rate: "", default_hours: "",
    rate_includes_pension: false,
  });
  const [hasPractice, setHasPractice] = useState(false);

  useEffect(() => {
    api.get<Profile>("/settings/profile").then((p) => {
      setMe({ legal_name: p.legal_name, address_lines: p.address_lines, postcode: p.postcode, email: p.email });
      setBank({ bank_account_holder: p.bank_account_holder, bank_sort_code: p.bank_sort_code, bank_account_number: "" });
      setHasAccount(p.bank_account_number_set);
    }, setError);
    api.get<Practice[]>("/practices").then((ps) => setHasPractice(ps.length > 0), () => undefined);
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

  const finish = async () => {
    await api.patch("/settings/profile", { setup_completed: true });
    nav("/", { replace: true });
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      if (step === 0) {
        await api.patch("/settings/profile", me);
        if (!bank.bank_account_holder) setBank((b) => ({ ...b, bank_account_holder: me.legal_name }));
        setStep(1);
      } else if (step === 1) {
        await api.patch("/settings/profile", {
          bank_account_holder: bank.bank_account_holder,
          bank_sort_code: bank.bank_sort_code,
          ...(bank.bank_account_number ? { bank_account_number: bank.bank_account_number } : {}),
        });
        setStep(2);
      } else {
        if (practice.name.trim()) {
          await api.post("/practices", { name: practice.name, billing_address: practice.billing_address, ...rateBody(practice) });
        }
        await finish();
      }
    });
  };

  const skip = () => {
    try {
      sessionStorage.setItem("locuvi.setup.skip", "1");
    } catch {
      /* ignore */
    }
    nav("/", { replace: true });
  };

  const titles = [t("welcome.you_title"), t("welcome.bank_title"), t("welcome.practice_title")];
  const leads = [t("welcome.you_lead"), t("welcome.bank_lead"), t("welcome.practice_lead")];
  const canNext =
    step === 0
      ? me.legal_name.trim() && me.address_lines.trim()
      : step === 1
        ? bank.bank_account_holder.trim() && bank.bank_sort_code.replace(/\D/g, "").length === 6 &&
          (hasAccount || bank.bank_account_number.replace(/\D/g, "").length === 8)
        : rateFieldsValid(practice);

  return (
    <div className="wizard">
      <div style={{ textAlign: "center", marginTop: "1.5rem" }}><Logo size={44} /></div>
      <div className="steps" aria-hidden="true">
        {[0, 1, 2].map((i) => <span key={i} className={i <= step ? "on" : ""} />)}
      </div>
      <p className="sr-only">{t("welcome.step", { n: step + 1 })}</p>
      <h1>{titles[step]}</h1>
      <p className="lead">{leads[step]}</p>
      <ErrorAlert error={error} />
      <form onSubmit={submit}>
        <div className="form-list">
          {step === 0 && (
            <>
              <Row id="w-name" label={t("settings.legal_name")}>
                <input id="w-name" type="text" autoComplete="name" autoFocus placeholder={t("welcome.name_ph")}
                  value={me.legal_name} onChange={(e) => setMe({ ...me, legal_name: e.target.value })} />
              </Row>
              <Row id="w-addr" label={t("settings.address")} stacked>
                <textarea id="w-addr" autoComplete="street-address" rows={2} placeholder={t("welcome.address_ph")}
                  value={me.address_lines} onChange={(e) => setMe({ ...me, address_lines: e.target.value })} />
              </Row>
              <Row id="w-pc" label={t("settings.postcode")}>
                <input id="w-pc" type="text" autoComplete="postal-code" value={me.postcode}
                  onChange={(e) => setMe({ ...me, postcode: e.target.value.toUpperCase() })} />
              </Row>
              <Row id="w-email" label={t("settings.email")}>
                <input id="w-email" type="email" autoComplete="email" value={me.email}
                  onChange={(e) => setMe({ ...me, email: e.target.value })} />
              </Row>
            </>
          )}
          {step === 1 && (
            <>
              <Row id="w-holder" label={t("settings.bank_holder")}>
                <input id="w-holder" type="text" autoFocus value={bank.bank_account_holder}
                  onChange={(e) => setBank({ ...bank, bank_account_holder: e.target.value })} />
              </Row>
              <Row id="w-sort" label={t("settings.sort_code")}>
                <input id="w-sort" type="text" inputMode="numeric" autoComplete="off" placeholder="00-00-00"
                  value={bank.bank_sort_code} onChange={(e) => setBank({ ...bank, bank_sort_code: e.target.value })} />
              </Row>
              <Row id="w-acct" label={t("settings.account_number")}>
                <input id="w-acct" type="text" inputMode="numeric" autoComplete="off" maxLength={8}
                  placeholder={hasAccount ? t("welcome.account_saved") : t("welcome.account_ph")}
                  value={bank.bank_account_number} onChange={(e) => setBank({ ...bank, bank_account_number: e.target.value })} />
              </Row>
            </>
          )}
          {step === 2 && !hasPractice && (
            <>
              <Row id="w-pname" label={t("practices.name")}>
                <input id="w-pname" type="text" autoFocus placeholder={t("welcome.practice_ph")}
                  value={practice.name} onChange={(e) => setPractice({ ...practice, name: e.target.value })} />
              </Row>
              <Row id="w-paddr" label={t("practices.billing_address")} stacked>
                <textarea id="w-paddr" rows={2} value={practice.billing_address}
                  onChange={(e) => setPractice({ ...practice, billing_address: e.target.value })} />
              </Row>
              <div className="welcome-rates">
                <RateFields idPrefix="w" value={practice} onChange={(v) => setPractice({ ...practice, ...v })} />
              </div>
            </>
          )}
          {step === 2 && hasPractice && <p style={{ padding: "1rem 1.15rem", margin: 0 }}>{t("welcome.practice_exists")}</p>}
        </div>
        <p className="form-foot">{step === 1 ? t("welcome.bank_foot") : step === 2 ? t("welcome.practice_foot") : t("welcome.you_foot")}</p>
        <button className="btn big block" disabled={busy || !canNext}>
          {step < 2 ? t("common.continue") : t("welcome.done")}
        </button>
        <div className="row" style={{ justifyContent: "center", marginTop: "0.75rem" }}>
          {step > 0 && <button type="button" className="btn ghost small" onClick={() => setStep((step - 1) as Step)}>{t("common.back")}</button>}
          <button type="button" className="btn ghost small" onClick={skip}>{t("welcome.later")}</button>
        </div>
      </form>
    </div>
  );
}

function Row({ id, label, children, stacked }: { id: string; label: string; children: React.ReactNode; stacked?: boolean }) {
  return (
    <div className={`form-row ${stacked ? "stacked" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children}
    </div>
  );
}
