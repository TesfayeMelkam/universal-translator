// Setup tab: server abilities, translation engines (+ who receives your text), your phrasebook / cloud data,
// how other systems connect, and a translation quality check (round-trip consistency, not proof of correctness).
import { $, api, apiRaw, banner, download } from "/static/js/core.js";
import { t } from "/static/js/i18n.js";

const line = (text, cls) => { const d = document.createElement("div"); d.className = "msg " + (cls || ""); d.textContent = text; return d; };
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };

export function initSetup({ caps, byCode, getTarget, getLangs }) {
  function engineCard(e) {
    const d = el("div", "engine" + (e.state === "paused" ? " paused" : ""));
    const b = el("b", "", e.label || e.name);
    b.append(el("span", "badge" + (e.state === "paused" ? " warn" : ""), e.state === "paused" ? t("setup.engine_paused") : t("setup.engine_ready")));
    d.append(b);
    d.append(el("small", "", e.sends_text_off_device ? t("setup.sends", { where: e.where || "?" }) : t("setup.local")));
    if (e.last_error) d.append(el("small", "", t("setup.last_problem", { msg: e.last_error })));
    return d;
  }
  async function renderData() {
    const box = $("dataStatus"); box.textContent = "";
    try {
      const d = await api("/api/v1/data/status");
      box.append(line(t("data.entries", { n: d.entries })));
      (d.last.results || []).forEach((r) => box.append(line(`${r.ok ? "✅" : "⚠"} ${r.source}: ${r.ok ? r.added : r.errors[0]}`, r.ok ? "ok" : "warn")));
      if (!d.sources.urls.length) box.append(line(t("data.cloud_none")));
    } catch (e) { box.append(line(e.message, "warn")); }
  }
  function fillPick(sel, keep) {
    sel.textContent = "";
    getLangs().forEach((l) => sel.add(new Option(`${l.native_name} — ${l.english_name}`, l.code)));
    sel.value = keep;
  }
  async function render() {
    const box = $("setupInfo"); box.textContent = "";
    let st = null; try { st = await api("/api/v1/translation/status"); } catch (e) { box.append(line(e.message, "bad")); return; }
    box.append(line(`${t("setup.provider")}: ${st.provider}${st.mock ? " — " + t("setup.mock") : ""}`, st.mock ? "warn" : ""));
    box.append(line(st.ready ? "✅ " + t("setup.ready") : "⚠ " + t("setup.not_ready") + (st.detail ? ` (${st.detail})` : ""), st.ready ? "" : "warn"));
    box.append(line(`🌍 ${caps.languages}`));
    box.append(line(`🔊 server voice: ${caps.tts ? (caps.tts_provider || "yes") : "no"} · 🎙️ server speech recognition: ${caps.stt ? "yes" : "no"} · FFmpeg: ${caps.ffmpeg ? "yes" : "no"}`));
    box.append(line(`📷 OCR: ${caps.ocr.provider}${caps.ocr.mock ? " (mock: does not read pictures)" : ""}`, caps.ocr.mock ? "warn" : ""));
    box.append(line(`👥 calls: ${caps.limits.max_participants} people (mesh)${caps.livekit ? `, up to ${caps.limits.max_large} (large)` : ""} · Telegram: ${caps.telegram ? "on" : "off"} · login: ${caps.auth_mode}`));
    if (st.unsupported_codes && st.unsupported_codes.length) box.append(line("Languages the loaded model does not know: " + st.unsupported_codes.join(", "), "warn"));
    (st.warnings || []).forEach((w) => box.append(line("⚠ " + w, "warn")));

    const eng = $("engineList"); eng.textContent = "";
    if (st.engines) { if (!st.engines.length) eng.append(line(t("setup.no_engine"), "warn")); st.engines.forEach((e) => eng.append(engineCard(e))); }
    renderData();
    fillPick($("pbSrc"), "en"); fillPick($("pbTgt"), getTarget() === "en" ? "am" : getTarget());
    $("apiExample").textContent = `curl -X POST ${location.origin}/api/v1/translate \\\n  -H "Content-Type: application/json" \\\n  -d '{"text":"Hello","source":"en","target":"am","save_history":false}'\n\n# LibreTranslate-compatible:  POST ${location.origin}/translate   {"q":"Hello","source":"en","target":"am"}\n# Batch (50 texts):          POST ${location.origin}/api/v1/translate/batch   {"texts":[...],"source":"en","target":"am"}` + (caps.access_code ? '\n# add header:  X-Access-Code: <your code>' : "");
    const pick = $("selfTestLangs"); pick.textContent = "";
    ["am", "om", "ti", "so", getTarget()].filter((c, i, a) => c !== "en" && a.indexOf(c) === i).forEach((c) => {
      const l = document.createElement("label"); l.className = "check";
      const cb = document.createElement("input"); cb.type = "checkbox"; cb.value = c; cb.checked = ["am", "om", "ti"].includes(c);
      l.append(cb, " " + (byCode(c) ? byCode(c).english_name : c)); pick.append(l);
    });
  }
  $("pbAdd").onclick = async () => {
    const body = { source: $("pbSrc").value, target: $("pbTgt").value, source_text: $("pbText").value, translation: $("pbTr").value };
    try { await api("/api/v1/glossary", { method: "POST", body: JSON.stringify(body) }); $("pbText").value = ""; $("pbTr").value = ""; banner(t("data.saved")); renderData(); document.dispatchEvent(new CustomEvent("phrasebookchange")); }
    catch (e) { banner(e.message); }
  };
  $("pbFile").onchange = async (ev) => {
    const f = ev.target.files[0]; if (!f) return;
    try {
      const r = await (await apiRaw(`/api/v1/glossary/import?name=${encodeURIComponent(f.name)}`, { method: "POST", body: f, headers: { "Content-Type": "application/octet-stream" }, retries: 0 })).json();
      banner(t("data.imported", { n: r.added, skipped: r.skipped }) + (r.errors && r.errors[0] ? " · " + r.errors[0] : "")); renderData(); document.dispatchEvent(new CustomEvent("phrasebookchange"));
    } catch (e) { banner(e.message); }
    ev.target.value = "";
  };
  $("pbExport").onclick = async () => { try { download(await (await apiRaw("/api/v1/glossary/export")).blob(), "phrasebook.csv"); } catch (e) { banner(e.message); } };
  $("pbSync").onclick = async () => { try { await api("/api/v1/data/sync", { method: "POST", body: "{}", timeout: 120000, retries: 0 }); banner(t("data.synced")); renderData(); document.dispatchEvent(new CustomEvent("phrasebookchange")); } catch (e) { banner(e.message); } };
  $("runSelfTest").onclick = async () => {
    const langs = [...$("selfTestLangs").querySelectorAll("input:checked")].map((i) => i.value).slice(0, 8);
    const out = $("selfTestResult"); out.textContent = ""; out.append(line(t("setup.running")));
    try {
      const r = await api("/api/v1/translation/selftest", { method: "POST", body: JSON.stringify({ languages: langs, phrases: 5 }), timeout: 600000, retries: 0 });
      out.textContent = "";
      if (r.is_mock) out.append(line("⚠ " + t("setup.mock"), "warn"));
      r.languages.forEach((e) => out.append(line(`${e.name}: ${e.score === null ? "—" : Math.round(e.score * 100) + "%"} · ${e.grade}` +
        (e.unchanged ? ` · ${e.unchanged} echoed unchanged` : ""), e.grade === "good" ? "" : "warn")));
      out.append(line(r.disclaimer));
    } catch (e) { out.textContent = ""; out.append(line(e.message, "bad")); }
  };
  return { render };
}
