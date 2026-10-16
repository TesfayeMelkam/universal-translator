// Works on Wi-Fi, mobile data and flaky links: online/offline badge, low-data switch, install button,
// "share to this app" (Android share sheet) and tab shortcuts.
import { $, banner, lowData, setLowData } from "/static/js/core.js";
import { t } from "/static/js/i18n.js";

export function initPwa({ showTab }) {
  const badge = $("netBadge");
  const paint = () => {
    const on = navigator.onLine;
    badge.textContent = on ? t("net.online") : t("net.offline");
    badge.classList.toggle("on", on); badge.classList.toggle("off", !on);
  };
  window.addEventListener("online", () => { paint(); banner(""); });
  window.addEventListener("offline", () => { paint(); banner(t("net.offline_msg")); });
  document.addEventListener("localechange", paint);
  paint();

  const lb = $("lowDataBtn");
  const paintLow = () => { lb.setAttribute("aria-pressed", String(lowData())); lb.classList.toggle("on", lowData()); };
  lb.onclick = () => { setLowData(!lowData()); paintLow(); banner(lowData() ? "🐢 " + t("net.low") : ""); };
  paintLow();
  const c = navigator.connection;
  if (c && /(^|-)2g$/.test(c.effectiveType || "") && localStorage.getItem("ut_lowdata") === null) banner(t("net.slow"));

  let deferred = null;
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferred = e; $("installBtn").hidden = false; });
  $("installBtn").onclick = async () => { if (!deferred) return; deferred.prompt(); await deferred.userChoice; deferred = null; $("installBtn").hidden = true; };

  const q = new URLSearchParams(location.search);
  const shared = [q.get("title"), q.get("text"), q.get("url")].filter(Boolean).join("\n");
  if (shared) { $("inputText").value = shared.slice(0, 2000); $("inputText").dispatchEvent(new Event("input")); showTab("text"); }
  const tab = q.get("tab");
  if (tab && document.querySelector(`[data-tab="${tab.replace(/[^a-z]/g, "")}"]`)) showTab(tab.replace(/[^a-z]/g, ""));
}
