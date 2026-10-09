import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import en, { type MessageKey } from "./en";
import de from "./de";
import es from "./es";
import fr from "./fr";
import ko from "./ko";
import pt from "./pt";

export type Locale = "en" | "de" | "ko" | "fr" | "es" | "pt";
export type Catalogue = Partial<Record<MessageKey, string>>;

// English is complete; other catalogues are partial and fall back to English per key.
export const catalogues: Record<Locale, Catalogue> = { en, de, ko, fr, es, pt };
export const localeNames: Record<Locale, string> = {
  en: "English",
  de: "Deutsch",
  ko: "한국어",
  fr: "Français",
  es: "Español",
  pt: "Português",
};

export type Params = Record<string, string | number>;

export function translate(locale: Locale, key: string, params?: Params): string {
  const text = (catalogues[locale] as Record<string, string>)[key] ?? (en as Record<string, string>)[key] ?? key;
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (m, name: string) =>
    params[name] !== undefined ? String(params[name]) : m,
  );
}

export function hasKey(key: string): boolean {
  return key in en;
}

function initialLocale(): Locale {
  try {
    const saved = localStorage.getItem("locuvi.locale");
    if (saved && saved in catalogues) return saved as Locale;
  } catch {
    /* storage unavailable */
  }
  return "en";
}

interface I18n {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: MessageKey, params?: Params) => string;
  /** Count-aware: uses `${key}_one` when n === 1 and that key exists. */
  tn: (key: MessageKey, n: number, params?: Params) => string;
}

const Ctx = createContext<I18n>({
  locale: "en",
  setLocale: () => undefined,
  t: (key, params) => translate("en", key, params),
  tn: (key, n, params) => translate("en", n === 1 && hasKey(`${key}_one`) ? `${key}_one` : key, { n, ...params }),
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  useEffect(() => {
    document.documentElement.lang = locale === "en" ? "en-GB" : locale;
  }, [locale]);
  const setLocale = useCallback((l: Locale) => {
    document.documentElement.lang = l === "en" ? "en-GB" : l;
    setLocaleState(l);
    try {
      localStorage.setItem("locuvi.locale", l);
    } catch {
      /* ignore */
    }
  }, []);
  const value = useMemo<I18n>(
    () => ({
      locale,
      setLocale,
      t: (key, params) => translate(locale, key, params),
      tn: (key, n, params) =>
        translate(locale, n === 1 && hasKey(`${key}_one`) ? `${key}_one` : key, { n, ...params }),
    }),
    [locale, setLocale],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useT() {
  return useContext(Ctx);
}
