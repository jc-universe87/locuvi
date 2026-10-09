import { useState, type FormEvent } from "react";
import { ErrorAlert, Logo } from "../components/ui";
import { useT } from "../i18n";
import { api } from "../lib/api";

export default function LoginPage({ onSignedIn }: { onSignedIn: () => Promise<void> }) {
  const { t } = useT();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/login", { password });
      await onSignedIn();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <div className="card">
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.25rem" }}>
          <Logo size={32} />
          <span className="brand-word" style={{ fontFamily: "var(--font-head)", fontWeight: 600, fontSize: "1.4rem" }}>
            locuvi
          </span>
        </div>
        <p className="muted" style={{ marginTop: 0 }}>{t("app.tagline")}</p>
        <h1>{t("auth.title")}</h1>
        <ErrorAlert error={error} />
        <form onSubmit={submit} className="grid">
          <div className="field">
            <label htmlFor="pw">{t("auth.password")}</label>
            <input id="pw" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} required autoFocus />
          </div>
          <button className="btn" disabled={busy || !password}>
            {t("auth.submit")}
          </button>
        </form>
      </div>
    </main>
  );
}
