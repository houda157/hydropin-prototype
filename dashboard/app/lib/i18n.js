import { STRINGS } from "./strings.js";

const LANGS = ["fr", "ar", "en"];
const KEY = "hydropin.lang";

/** The saved choice wins, then the phone's language, then French. */
export function detectLang(navLang, stored) {
  if (LANGS.includes(stored)) return stored;
  const p = String(navLang || "").slice(0, 2).toLowerCase();
  return LANGS.includes(p) ? p : "fr";
}

export function t(lang, key, vars = {}) {
  const s = (STRINGS[lang] && STRINGS[lang][key]) ?? STRINGS.fr[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

export const isRtl = (lang) => lang === "ar";

export function locale(lang) {
  return lang === "ar" ? "ar-TN" : lang === "fr" ? "fr-TN" : "en";
}

export function fmt(lang, n, digits = 0) {
  return new Intl.NumberFormat(locale(lang), { maximumFractionDigits: digits, numberingSystem: "latn" }).format(n);
}

// Browser storage can be missing or blocked (private window): the app still works, it just forgets.
export function loadLang(storage = globalThis.localStorage) {
  try { return storage ? storage.getItem(KEY) : null; } catch { return null; }
}

export function saveLang(lang, storage = globalThis.localStorage) {
  try { if (storage) storage.setItem(KEY, lang); } catch { /* not remembered; fine */ }
}
