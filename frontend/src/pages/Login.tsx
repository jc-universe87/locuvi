import { useState, type FormEvent } from "react";
import { ErrorAlert, Logo } from "../components/ui";
import { useT } from "../i18n";
import { api } from "../lib/api";

const LAST_NAME = "locuvi.lastProfile";

function lastName(): string {
  try { return localStorage.getItem(LAST_NAME) ?? ""; } catch { return ""; }
}

export default function LoginPage({ onSignedIn, multi = false }: { onSignedIn: () => Promise<void>; multi?: boolean }) {
  const { t } = useT();
  const [name, setName] = useState(lastName);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/login", multi ? { name: name.trim(), password } : { password });
      if (multi) {
        try { localStorage.setItem(LAST_NAME, name.trim()); } catch { /* private mode */ }
      }
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
          {multi && (
            <div className="field">
              <label htmlFor="who">{t("auth.name")}</label>
              <input id="who" type="text" autoComplete="username" autoCapitalize="words" value={name}
                onChange={(e) => setName(e.target.value)} required autoFocus={!name} />
            </div>
          )}
          <div className="field">
            <label htmlFor="pw">{t("auth.password")}</label>
            <input id="pw" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} required autoFocus={!multi || !!name} />
          </div>
          <button className="btn" disabled={busy || !password || (multi && !name.trim())}>
            {t("auth.submit")}
          </button>
        </form>
      </div>
    </main>
  );
}
