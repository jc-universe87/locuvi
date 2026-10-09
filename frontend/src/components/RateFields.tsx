import { useT } from "../i18n";
import { Field, Segmented } from "./ui";

/** How a practice pays: per session or per hour, and whether NHS pension is on top or inside. */
export interface RateValue {
  default_unit: string;
  default_rate: string;
  hourly_rate: string;
  default_hours: string;
  rate_includes_pension: boolean;
}

const DEC = /^\d{1,7}(\.\d{1,2})?$/;

export function rateFieldsValid(v: RateValue): boolean {
  const ok = (s: string) => !s.trim() || DEC.test(s.trim());
  return ok(v.default_rate) && ok(v.hourly_rate) && ok(v.default_hours);
}

export function RateFields({ value, onChange, pensionable = true, idPrefix }: {
  value: RateValue; onChange: (v: RateValue) => void; pensionable?: boolean; idPrefix: string;
}) {
  const { t } = useT();
  const hourly = value.default_unit === "hours";
  const set = (patch: Partial<RateValue>) => onChange({ ...value, ...patch });
  return (
    <div className="grid rate-fields">
      <div className="toggle-row">
        <span className="text">{t("rates.paid_per")}</span>
        <Segmented value={hourly ? "hours" : "session"} label={t("rates.paid_per")}
          onChange={(v) => set({ default_unit: v === "hours" ? "hours" : "am" })}
          options={[{ value: "session", label: t("rates.per_session") }, { value: "hours", label: t("rates.per_hour") }]} />
      </div>
      {hourly ? (
        <div className="grid grid-2">
          <Field id={`${idPrefix}-hrate`} label={t("rates.hourly_rate")}>
            <input id={`${idPrefix}-hrate`} type="text" inputMode="decimal" placeholder="£" value={value.hourly_rate}
              aria-invalid={!!value.hourly_rate.trim() && !DEC.test(value.hourly_rate.trim())}
              onChange={(e) => set({ hourly_rate: e.target.value })} />
          </Field>
          <Field id={`${idPrefix}-hours`} label={t("rates.usual_hours")} optional>
            <input id={`${idPrefix}-hours`} type="text" inputMode="decimal" placeholder="4" value={value.default_hours}
              aria-invalid={!!value.default_hours.trim() && !DEC.test(value.default_hours.trim())}
              onChange={(e) => set({ default_hours: e.target.value })} />
          </Field>
        </div>
      ) : (
        <Field id={`${idPrefix}-srate`} label={t("rates.session_rate")}>
          <input id={`${idPrefix}-srate`} type="text" inputMode="decimal" placeholder="£" value={value.default_rate}
            aria-invalid={!!value.default_rate.trim() && !DEC.test(value.default_rate.trim())}
            onChange={(e) => set({ default_rate: e.target.value })} />
        </Field>
      )}
      {pensionable && (
        <>
          <div className="toggle-row">
            <span className="text">{t("rates.nhs_pension")}</span>
            <Segmented value={value.rate_includes_pension ? "included" : "on_top"} label={t("rates.nhs_pension")}
              onChange={(v) => set({ rate_includes_pension: v === "included" })}
              options={[{ value: "on_top", label: t("rates.pension_on_top") }, { value: "included", label: t("rates.pension_included") }]} />
          </div>
          <p className="hint" style={{ margin: 0 }}>
            {value.rate_includes_pension ? t("rates.included_help") : t("rates.on_top_help")}
          </p>
        </>
      )}
    </div>
  );
}

/** API body fields for a practice from the rate block (empty strings become null). */
export function rateBody(v: RateValue) {
  const n = (s: string) => s.trim() || null;
  return {
    default_unit: v.default_unit === "hours" ? "hours" : "am",
    default_rate: n(v.default_rate),
    hourly_rate: n(v.hourly_rate),
    default_hours: n(v.default_hours),
    rate_includes_pension: v.rate_includes_pension,
  };
}
