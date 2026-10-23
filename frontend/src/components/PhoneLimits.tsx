import { useState } from "react";
import { useT } from "../i18n";
import { POCKET } from "../lib/pocket";

const ITEMS = ["assistant", "email", "agents", "nextcloud", "calendar", "sync"] as const;
const DISMISSED = "locuvi.phone-limits-seen";

/**
 * The phone app (iPhone, iPad, Android) has everything except what needs a connection a
 * phone app can't make. Said plainly, with what to use instead. Shown in Settings always and
 * on Today until dismissed. Nothing at all outside the phone app.
 */
export function PhoneLimits({ dismissible = false }: { dismissible?: boolean }) {
  const { t } = useT();
  const [hidden, setHidden] = useState(() => {
    try {
      return dismissible && localStorage.getItem(DISMISSED) === "1";
    } catch {
      return false;
    }
  });
  if (!POCKET || hidden) return null;
  const dismiss = () => {
    try {
      localStorage.setItem(DISMISSED, "1");
    } catch {
      /* private browsing: it shows again next time */
    }
    setHidden(true);
  };
  return (
    <section className="alert info" aria-labelledby="phone-limits" style={{ marginBottom: "1rem" }}>
      <strong id="phone-limits">{t("phone.limits_title")}</strong>
      <ul style={{ margin: "0.4rem 0", paddingLeft: "1.2rem" }}>
        {ITEMS.map((k) => (
          <li key={k}>{t(`phone.limit_${k}`)}</li>
        ))}
      </ul>
      <span>{t("phone.limits_future")}</span>
      {dismissible && (
        <div style={{ marginTop: "0.5rem" }}>
          <button className="btn ghost small" onClick={dismiss}>{t("phone.limits_ok")}</button>
        </div>
      )}
    </section>
  );
}
