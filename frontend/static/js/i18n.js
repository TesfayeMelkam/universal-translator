// Tiny translation layer: static text uses data-i18n attributes, dynamic text uses t("key", {vars}).
// Missing keys fall back to English, so partly translated (draft) languages still work.
let en = {}, dict = {}, current = "en", index = [];

async function load(code) {
  const res = await fetch(`/static/i18n/${code}.json`, { cache: "no-cache" });
  if (!res.ok) throw new Error("locale " + code);
  return res.json();
}
export function t(key, vars) {
  let s = dict[key] ?? en[key] ?? key;
  if (vars) s = s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ""));
  return s;
}
export function errorMessage(code, fallback) { return dict["err." + code] ?? en["err." + code] ?? fallback; }
export function getLocale() { return current; }
export async function listLocales() {
  if (!index.length) { try { index = await (await fetch("/static/i18n/index.json")).json(); } catch (_) { index = [{ code: "en", name: "English", draft: false }]; } }
  return index;
}
export function applyI18n(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
  root.querySelectorAll("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
  root.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
  document.documentElement.lang = current;
  document.title = t("app.title");
}
export async function setLocale(code) {
  try { if (!Object.keys(en).length) en = await load("en"); dict = code === "en" ? {} : await load(code); current = code; }
  catch (_) { dict = {}; current = "en"; }
  try { localStorage.ut_ui = current; } catch (_) {}
  applyI18n();
  document.dispatchEvent(new CustomEvent("localechange", { detail: current }));
}
export async function initI18n() {
  const locales = await listLocales();
  const want = (localStorage.ut_ui || (navigator.language || "en").slice(0, 2)).toLowerCase();
  await setLocale(locales.some((l) => l.code === want) ? want : "en");
}
