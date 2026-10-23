import { useCallback, useEffect, useState } from "react";
import { BrowserRouter, HashRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ConfirmProvider, Icon, Logo, ToastProvider } from "./components/ui";
import { useT } from "./i18n";
import type { MessageKey } from "./i18n/en";
import { api, setCsrf, setUnauthorizedHandler } from "./lib/api";
import { POCKET, onPocketProgress } from "./lib/pocket";
import { useDesktopHeartbeat } from "./lib/desktop";
import type { HouseholdProfile } from "./lib/types";
import DiaryPage from "./pages/Diary";
import AskPage from "./pages/Ask";
import BankPage from "./pages/Bank";
import InboxPage from "./pages/Inbox";
import InvoiceDetailPage from "./pages/InvoiceDetail";
import InvoiceEditor from "./pages/InvoiceEditor";
import InvoicesPage from "./pages/Invoices";
import LoginPage from "./pages/Login";
import PensionPage from "./pages/Pension";
import ReportsPage from "./pages/Reports";
import SettingsPage from "./pages/Settings";
import TodayPage from "./pages/Today";
import WelcomePage from "./pages/Welcome";

interface SessionInfo {
  authenticated: boolean;
  auth_mode: "password" | "gateway";
  login_required?: boolean;
  multi?: boolean;
  csrf_token: string | null;
  profile?: HouseholdProfile | null;
}

const TABS: { to: string; icon: string; label: MessageKey; end?: boolean }[] = [
  { to: "/", icon: "today", label: "nav.today", end: true },
  { to: "/diary", icon: "diary", label: "nav.diary" },
  { to: "/invoices", icon: "invoices", label: "nav.invoices" },
  { to: "/pension", icon: "pension", label: "nav.pension" },
  { to: "/reports", icon: "reports", label: "nav.reports" },
];

// The phone app is served from files (Android) or a sub-folder (iPhone), so it uses #/ links.
const Router = POCKET ? HashRouter : BrowserRouter;

/** Phone app: the first start sets Locuvi up on the phone, which takes a few seconds. */
function PocketOpening() {
  const { t } = useT();
  const [step, setStep] = useState("runtime");
  useEffect(() => onPocketProgress(setStep), []);
  return (
    <main className="pocket-opening" aria-busy="true">
      <Logo />
      {step === "failed" ? (
        <p role="alert">{t("pocket.step_failed")}</p>
      ) : (
        <>
          <p>{t("pocket.opening")}</p>
          <p className="muted">{t(`pocket.step_${step}` as MessageKey)}</p>
        </>
      )}
    </main>
  );
}

/** Phone app: sync with the other devices now and then, and when it comes back on screen. */
function usePocketSync(on: boolean) {
  useEffect(() => {
    if (!POCKET || !on) return;
    const run = () =>
      api.get<{ enabled: boolean }>("/sync").then((s) => (s.enabled ? api.post("/sync/now") : null)).catch(() => undefined);
    const every = window.setInterval(run, 5 * 60 * 1000);
    const back = () => document.visibilityState === "visible" && void run();
    document.addEventListener("visibilitychange", back);
    void run();
    return () => {
      window.clearInterval(every);
      document.removeEventListener("visibilitychange", back);
    };
  }, [on]);
}

export default function App() {
  const { t } = useT();
  const [session, setSession] = useState<SessionInfo | null>(null);
  usePocketSync(!!session?.authenticated);
  useDesktopHeartbeat(!POCKET && !!session?.authenticated);

  const refresh = useCallback(async () => {
    try {
      const s = await api.get<SessionInfo>("/auth/session");
      setCsrf(s.csrf_token);
      setSession(s);
    } catch {
      // Phone app: the opening screen stays and explains (no sign-in page on a phone)
      if (!POCKET) setSession({ authenticated: false, auth_mode: "password", csrf_token: null });
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setSession((s) => (s ? { ...s, authenticated: false } : s)));
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onScroll = () => document.querySelector(".topbar")?.classList.toggle("scrolled", window.scrollY > 4);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  if (!session) return POCKET ? <PocketOpening /> : null;
  if (!session.authenticated) return <LoginPage multi={!!session.multi} onSignedIn={refresh} />;

  const signOut = async () => {
    await api.post("/auth/logout");
    // Start the next person (another household profile) on the start page, not here.
    window.history.replaceState(null, "", "/");
    await refresh();
  };

  return (
    <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ToastProvider>
      <ConfirmProvider>
        <a className="skip" href="#main">
          {t("app.skip")}
        </a>
        <header className="topbar">
          <div className="topbar-inner">
            <NavLink to="/" className="brand" aria-label={`${t("app.name")} — ${t("nav.today")}`}>
              <Logo />
              <span className="brand-word">locuvi</span>
            </NavLink>
            <nav className="topnav" aria-label={t("nav.main")}>
              {TABS.map((tab) => (
                <NavLink key={tab.to} to={tab.to} end={tab.end}>
                  {t(tab.label)}
                </NavLink>
              ))}
            </nav>
            <span className="spacer" />
            <AskLink />
            <InboxLink />
            <NavLink to="/settings" className="icon-btn" aria-label={t("nav.settings")} title={t("nav.settings")}>
              <Icon name="settings" />
            </NavLink>
          </div>
        </header>
        <main id="main">
          <Routes>
            <Route path="/" element={<TodayPage />} />
            <Route path="/welcome" element={<WelcomePage />} />
            <Route path="/diary" element={<DiaryPage />} />
            <Route path="/invoices" element={<InvoicesPage />} />
            <Route path="/invoices/new" element={<InvoiceEditor />} />
            <Route path="/invoices/:id/edit" element={<InvoiceEditor />} />
            <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
            <Route path="/inbox" element={<InboxPage />} />
            <Route path="/bank" element={<BankPage />} />
            <Route path="/ask" element={<AskPage />} />
            <Route path="/pension" element={<PensionPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/settings" element={<SettingsPage profile={session.profile ?? null} onSignOut={session.login_required ?? session.auth_mode === "password" ? signOut : undefined} />} />
            <Route path="/settings/:section" element={<SettingsPage profile={session.profile ?? null} onSignOut={session.login_required ?? session.auth_mode === "password" ? signOut : undefined} />} />
            <Route path="/practices" element={<Navigate to="/settings/practices" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <nav className="tabbar" aria-label={t("nav.main")}>
          {TABS.map((tab) => (
            <NavLink key={tab.to} to={tab.to} end={tab.end}>
              <Icon name={tab.icon} />
              {t(tab.label)}
            </NavLink>
          ))}
        </nav>
      </ConfirmProvider>
      </ToastProvider>
    </Router>
  );
}

/** Inbox tray in the top bar; the badge counts documents not yet dealt with. */
function InboxLink() {
  const { t } = useT();
  const location = useLocation();
  const [count, setCount] = useState(0);
  useEffect(() => {
    api.get<{ new: number }>("/documents?status=new").then((r) => setCount(r.new), () => undefined);
  }, [location.pathname]);
  const label = count ? `${t("inbox.title")} — ${t("inbox.badge", { n: count })}` : t("inbox.title");
  return (
    <NavLink to="/inbox" className="icon-btn badge-host" aria-label={label} title={label}>
      <Icon name="inbox" />
      {count > 0 && <span className="badge" aria-hidden="true">{count > 9 ? "9+" : count}</span>}
    </NavLink>
  );
}

/** Sparkle in the top bar, only when the optional assistant is switched on. */
function AskLink() {
  const { t } = useT();
  const [on, setOn] = useState(false);
  useEffect(() => {
    api.get<{ ready: boolean }>("/settings/assistant").then((r) => setOn(r.ready), () => undefined);
  }, []);
  if (!on) return null;
  return (
    <NavLink to="/ask" className="icon-btn" aria-label={t("ask.title")} title={t("ask.title")}>
      <Icon name="sparkle" />
    </NavLink>
  );
}
