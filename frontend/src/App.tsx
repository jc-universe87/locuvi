import { useCallback, useEffect, useState } from "react";
import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { Logo } from "./components/ui";
import { localeNames, useT, type Locale } from "./i18n";
import { api, setCsrf, setUnauthorizedHandler } from "./lib/api";
import InvoiceDetailPage from "./pages/InvoiceDetail";
import InvoiceEditor from "./pages/InvoiceEditor";
import InvoicesPage from "./pages/Invoices";
import LoginPage from "./pages/Login";
import PracticesPage from "./pages/Practices";
import SettingsPage from "./pages/Settings";

interface SessionInfo {
  authenticated: boolean;
  auth_mode: "password" | "gateway";
  csrf_token: string | null;
}

export default function App() {
  const { t, locale, setLocale } = useT();
  const [session, setSession] = useState<SessionInfo | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await api.get<SessionInfo>("/auth/session");
      setCsrf(s.csrf_token);
      setSession(s);
    } catch {
      setSession({ authenticated: false, auth_mode: "password", csrf_token: null });
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setSession((s) => (s ? { ...s, authenticated: false } : s)));
    void refresh();
  }, [refresh]);

  if (!session) return <p className="muted" style={{ padding: "2rem" }}>{t("app.loading")}</p>;
  if (!session.authenticated) return <LoginPage onSignedIn={refresh} />;

  const signOut = async () => {
    await api.post("/auth/logout");
    await refresh();
  };

  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <a className="skip" href="#main">
        {t("app.skip")}
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/invoices" className="brand" aria-label={`${t("app.name")} — ${t("app.descriptor")}`}>
            <Logo />
            <span className="brand-word">locuvi</span>
            <span className="brand-desc">{t("app.descriptor")}</span>
          </NavLink>
          <nav className="nav" aria-label={t("nav.main")}>
            <NavLink to="/invoices">{t("nav.invoices")}</NavLink>
            <NavLink to="/practices">{t("nav.practices")}</NavLink>
            <NavLink to="/settings">{t("nav.settings")}</NavLink>
          </nav>
          <div className="topbar-tools">
            <label className="sr-only" htmlFor="lang">
              {t("app.language")}
            </label>
            <select id="lang" className="lang" value={locale} onChange={(e) => setLocale(e.target.value as Locale)}>
              {(Object.keys(localeNames) as Locale[]).map((l) => (
                <option key={l} value={l}>
                  {localeNames[l]}
                </option>
              ))}
            </select>
            {session.auth_mode === "password" && (
              <button className="btn ghost small" onClick={signOut}>
                {t("nav.signout")}
              </button>
            )}
          </div>
        </div>
      </header>
      <main id="main">
        <Routes>
          <Route path="/" element={<Navigate to="/invoices" replace />} />
          <Route path="/invoices" element={<InvoicesPage />} />
          <Route path="/invoices/new" element={<InvoiceEditor />} />
          <Route path="/invoices/:id/edit" element={<InvoiceEditor />} />
          <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
          <Route path="/practices" element={<PracticesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/invoices" replace />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
