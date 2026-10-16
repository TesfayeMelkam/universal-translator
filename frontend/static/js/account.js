// Sign in / create account (only shown when the server has AUTH_MODE on). Cookie session, HttpOnly.
import { $, api, banner, setAuthHandler } from "/static/js/core.js";
import { t } from "/static/js/i18n.js";

export async function initAccount() {
  let user = null, mode = "off", resolver = null;
  const dlg = $("loginDialog");

  const render = () => {
    const b = $("accountBtn");
    b.hidden = mode === "off";
    b.textContent = user ? `👤 ${user.username}` : t("account.sign_in");
    b.title = user ? t("account.sign_out") : "";
  };
  async function refresh() {
    try { const me = await api("/api/v1/auth/me"); mode = me.auth_mode; user = me.user; } catch (_) { /* offline */ }
    render();
  }
  function promptLogin() {
    if (!dlg || !dlg.showModal) return Promise.resolve(false);
    $("loginMsg").textContent = ""; $("loginPass").value = "";
    if (!dlg.open) dlg.showModal();
    return new Promise((res) => { resolver = res; });
  }
  function finish(ok) { if (dlg.open) dlg.close(); if (resolver) { resolver(ok); resolver = null; } }
  async function submit(kind) {
    const username = $("loginUser").value.trim(), password = $("loginPass").value;
    $("loginMsg").textContent = "";
    try {
      const r = await api(`/api/v1/auth/${kind}`, { method: "POST", body: JSON.stringify({ username, password }) });
      user = r.user; render(); finish(true);
      document.dispatchEvent(new CustomEvent("authchange"));
    } catch (e) { $("loginMsg").textContent = e.message; }
  }
  setAuthHandler(async (code) => {
    if (code === "login_required") return promptLogin();
    if (code === "access_required") {
      const c = window.prompt(t("err.access_required"));
      if (c) { try { sessionStorage.ut_access = c.trim(); } catch (_) {} return true; }
    }
    return false;
  });
  $("loginSubmit").onclick = () => submit("login");
  $("loginRegister").onclick = () => submit("register");
  $("loginCancel").onclick = () => finish(false);
  dlg.addEventListener("cancel", () => finish(false));
  $("loginPass").addEventListener("keydown", (e) => { if (e.key === "Enter") submit("login"); });
  $("accountBtn").onclick = async () => {
    if (!user) return promptLogin();
    if (window.confirm(t("account.sign_out") + "?")) {
      try { await api("/api/v1/auth/logout", { method: "POST" }); } catch (_) {}
      user = null; render(); banner(""); document.dispatchEvent(new CustomEvent("authchange"));
    }
  };
  document.addEventListener("localechange", render);
  await refresh();
  return { refresh };
}
