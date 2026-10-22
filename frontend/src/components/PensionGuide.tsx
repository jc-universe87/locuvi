import { Link } from "react-router-dom";
import { Dialog } from "./ui";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n/en";

// Official pages only. PCSE runs the NHS pension forms for GPs in England.
export const PCSE_LOCUM_URL = "https://pcse.england.nhs.uk/services/gp-pensions/locum-gps";
export const LINKS: { key: MessageKey; url: string }[] = [
  { key: "pguide.link_pcse", url: PCSE_LOCUM_URL },
  { key: "pguide.link_submit", url: "https://pcse.england.nhs.uk/services/gp-pensions/locum-gps/submit-locum-b-forms" },
  { key: "pguide.link_pay", url: "https://pcse.england.nhs.uk/services/gp-pensions/locum-gps/paying-pension-contributions-nhs-england" },
  { key: "pguide.link_help", url: "https://pcse.england.nhs.uk/help/gp-pensions/pension-contributions-locum-b" },
  { key: "pguide.link_access", url: "https://pcse.england.nhs.uk/contact-us/pcse-online-access" },
  { key: "pguide.link_contact", url: "https://pcse.england.nhs.uk/contact-us/gp-pensions-enquiries" },
  { key: "pguide.link_bma", url: "https://www.bma.org.uk/pay-and-contracts/pensions/being-a-member-of-a-pension-scheme/the-nhs-pension-scheme-as-a-locum-gp" },
];

// Each section: a heading and its steps, in the order a locum does them.
export const SECTIONS: { title: MessageKey; steps: MessageKey[]; ordered?: boolean }[] = [
  { title: "pguide.once_title", steps: ["pguide.once_1", "pguide.once_2", "pguide.once_3"] },
  { title: "pguide.a_title", ordered: true, steps: ["pguide.a_1", "pguide.a_2", "pguide.a_3", "pguide.a_4", "pguide.a_5"] },
  { title: "pguide.b_title", ordered: true, steps: ["pguide.b_1", "pguide.b_2", "pguide.b_3", "pguide.b_4"] },
  { title: "pguide.pay_title", steps: ["pguide.pay_1", "pguide.pay_2", "pguide.pay_3"] },
  { title: "pguide.rules_title", steps: ["pguide.rules_1", "pguide.rules_2", "pguide.rules_3", "pguide.rules_4"] },
  { title: "pguide.stuck_title", steps: ["pguide.stuck_1", "pguide.stuck_2", "pguide.stuck_3"] },
  { title: "pguide.nations_title", steps: ["pguide.nations_1", "pguide.nations_2", "pguide.nations_3"] },
];

export function PensionGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useT();
  return (
    <Dialog open={open} title={t("pguide.title")} onClose={onClose}
      footer={<button className="btn" onClick={onClose}>{t("common.close")}</button>}>
      <p style={{ marginTop: 0 }}>{t("pguide.intro")}</p>
      <p>
        <a className="btn secondary small" href={PCSE_LOCUM_URL} target="_blank" rel="noreferrer noopener">
          {t("pguide.open_pcse")}
        </a>
      </p>
      {SECTIONS.map((s) => {
        const List = s.ordered ? "ol" : "ul";
        return (
          <section key={s.title}>
            <h3>{t(s.title)}</h3>
            <List style={{ paddingLeft: "1.25rem", margin: "0.25rem 0 0.75rem" }}>
              {s.steps.map((k) => <li key={k} style={{ marginBottom: "0.35rem" }}>{t(k)}</li>)}
            </List>
            {s.title === "pguide.once_title" && (
              <p className="hint" style={{ marginTop: 0 }}>
                <Link to="/settings/pension" onClick={onClose}>{t("pension.set_tier_link")}</Link>
              </p>
            )}
          </section>
        );
      })}
      <h3>{t("pguide.links_title")}</h3>
      <ul style={{ paddingLeft: "1.25rem", margin: "0.25rem 0 0.75rem" }}>
        {LINKS.map((l) => (
          <li key={l.key} style={{ marginBottom: "0.35rem" }}>
            <a href={l.url} target="_blank" rel="noreferrer noopener">{t(l.key)}</a>
          </li>
        ))}
      </ul>
      <p className="hint">{t("pguide.checked")}</p>
    </Dialog>
  );
}
