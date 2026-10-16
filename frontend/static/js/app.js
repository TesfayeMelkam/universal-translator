// Universal Translator web client. Languages and server abilities come from the API.
import { $, api, banner, lowData } from "/static/js/core.js";
import { initI18n, listLocales, setLocale, getLocale, t } from "/static/js/i18n.js";
import { initAccount } from "/static/js/account.js";
import { initPwa } from "/static/js/pwa.js";
import { initCamera } from "/static/js/translate-camera.js";
import { initCall } from "/static/js/video-call.js";
import { initDocs } from "/static/js/documents.js";
import { initSetup } from "/static/js/setup.js";
import { initServerVoice } from "/static/js/server-voice.js";

let LANGS = [], caps = null, camera = null, setup = null;
let lastTranslation = { text: "", lang: "en" };
const byCode = (c) => LANGS.find((l) => l.code === c);
const langName = (c) => (byCode(c) ? byCode(c).native_name : c);
function setDir(el, code) { const l = byCode(code); el.dir = l && l.rtl ? "rtl" : "ltr"; }

// ---------- languages (150+, searchable, with recent ones on top) ----------
const recent = () => { try { return JSON.parse(localStorage.ut_recent || "[]"); } catch (_) { return []; } };
function pushRecent(...codes) {
  const r = recent().filter((c) => !codes.includes(c));
  try { localStorage.ut_recent = JSON.stringify([...codes.filter((c) => c && c !== "auto"), ...r].slice(0, 6)); } catch (_) {}
}
function fillSelect(sel, withAuto, keep) {
  const q = $("langSearch").value.trim().toLowerCase();
  const list = LANGS.filter((l) => !q || l.code.includes(q) || l.english_name.toLowerCase().includes(q) ||
    l.native_name.toLowerCase().includes(q) || l.code === keep);
  const tag = (l) => (l.data_only ? ` (${t("lang.phrasebook_only")})` : l.available === false ? ` (${t("lang.no_engine")})` : "");
  const label = (l) => `${l.native_name} — ${l.english_name}${tag(l)}`;
  sel.innerHTML = "";
  if (withAuto) sel.add(new Option(t("lang.detect"), "auto"));
  const rec = recent().map(byCode).filter((l) => l && list.includes(l));
  if (rec.length && !q) {
    const og = document.createElement("optgroup"); og.label = t("group.recent");
    rec.forEach((l) => og.appendChild(new Option(label(l), l.code))); sel.appendChild(og);
  }
  for (const g of ["ethiopian", "african", "world"]) {
    const og = document.createElement("optgroup"); og.label = t("group." + g);
    list.filter((l) => l.group === g).forEach((l) => og.appendChild(new Option(label(l), l.code)));
    if (og.children.length) sel.appendChild(og);
  }
  sel.value = keep;
  if (sel.value !== keep) sel.selectedIndex = 0;
}
function refillLanguages() {
  const s = $("srcLang").value || localStorage.ut_src || "en", tg = $("tgtLang").value || localStorage.ut_tgt || "am";
  fillSelect($("srcLang"), true, s); fillSelect($("tgtLang"), false, tg); updateTalkLabels();
}
function updateTalkLabels() { $("talkALabel").textContent = langName($("srcLang").value); $("talkBLabel").textContent = langName($("tgtLang").value); }

// ---------- script-based language hint while typing (the server has the same rules) ----------
const RANGES = [["am", 0x1200, 0x139f, true], ["ar", 0x600, 0x6ff, true], ["hi", 0x900, 0x97f, true], ["bn", 0x980, 0x9ff, false],
  ["ta", 0xb80, 0xbff, false], ["th", 0xe00, 0xe7f, false], ["he", 0x590, 0x5ff, false], ["el", 0x370, 0x3ff, false],
  ["ko", 0xac00, 0xd7af, false], ["ja", 0x3040, 0x30ff, false], ["zh", 0x4e00, 0x9fff, true], ["ru", 0x400, 0x4ff, true]];
function guessLanguage(text) {
  const n = {};
  for (const ch of text) {
    const cp = ch.codePointAt(0); const r = RANGES.find(([, lo, hi]) => cp >= lo && cp <= hi);
    if (r) n[r[0]] = (n[r[0]] || 0) + 1; else if (/\p{L}/u.test(ch) && cp < 0x250) n.en = (n.en || 0) + 1;
  }
  const best = Object.keys(n).sort((a, b) => n[b] - n[a])[0];
  return best ? { code: best, ambiguous: best === "en" || RANGES.some((r) => r[0] === best && r[3]) } : null;
}
function updateDetectChip() {
  const chip = $("detectChip"), g = $("srcLang").value === "auto" ? guessLanguage($("inputText").value) : null;
  if (!g) { chip.hidden = true; return; }
  chip.hidden = false; chip.textContent = t("text.detected", { lang: langName(g.code) + (g.ambiguous ? " ?" : "") });
  chip.onclick = () => { $("srcLang").value = g.code; localStorage.ut_src = g.code; updateTalkLabels(); chip.hidden = true; };
}

// ---------- text to speech ----------
let serverTts = false;
const rate = () => parseFloat(localStorage.ut_rate || "1");
function voicesFor(tag) {
  if (!("speechSynthesis" in window)) return [];
  const all = speechSynthesis.getVoices(), p = tag.slice(0, 2).toLowerCase();
  const exact = all.filter((v) => v.lang.toLowerCase().replace("_", "-") === tag.toLowerCase());
  return [...exact, ...all.filter((v) => v.lang.toLowerCase().startsWith(p) && !exact.includes(v))];
}
function pickVoice(code) {
  const l = byCode(code); if (!l) return null;
  const list = voicesFor(l.speech_tag), saved = localStorage["ut_voice_" + code];
  return list.find((v) => v.name === saved) || list[0] || null;
}
async function speakServer(text, code) {
  const res = await fetch("/api/v1/synthesize", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: text.slice(0, 1000), language: code }) });
  if (!res.ok) throw new Error("server voice unavailable");
  const url = URL.createObjectURL(await res.blob());
  const audio = new Audio(url); audio.onended = () => URL.revokeObjectURL(url); await audio.play();
}
async function speak(text, code) {
  const l = byCode(code); if (!l || !text) return;
  const voice = pickVoice(code);
  if (voice) {
    banner(""); speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.voice = voice; u.lang = voice.lang; u.rate = rate();
    return new Promise((res) => { u.onend = res; u.onerror = res; speechSynthesis.speak(u); });
  }
  if (serverTts) { try { await speakServer(text, code); banner(""); return; } catch (_) { /* fall through */ } }
  banner(`No ${l.english_name} voice is available on this computer/browser, so it can't be read aloud. Tip: try Microsoft Edge, or ask the host to enable server voices (TTS_PROVIDER=mms).`);
}
function refreshVoiceList() {
  const sel = $("voiceSel"); if (!sel) return;
  const code = $("tgtLang").value, l = byCode(code); sel.innerHTML = "";
  const list = l ? voicesFor(l.speech_tag) : [];
  if (!list.length) sel.add(new Option(`No ${l ? l.english_name : ""} voice found`, ""));
  list.forEach((v) => sel.add(new Option(`${v.name} (${v.lang})`, v.name)));
  const saved = localStorage["ut_voice_" + code]; if (saved) sel.value = saved;
}
const SAMPLE = { en: "Hello", am: "ሰላም", ar: "مرحبا", fr: "Bonjour", es: "Hola", de: "Hallo", sw: "Habari", it: "Ciao" };
function voiceCheck() {
  const box = $("voiceReport"); box.textContent = "";
  for (const l of LANGS) {
    const v = pickVoice(l.code), d = document.createElement("div"); d.className = "vrow";
    d.textContent = `${l.native_name} — ${l.english_name}: ` + (v ? `✅ ${v.name}` : (serverTts ? "☁ server voice may work" : "❌"));
    box.append(d);
  }
}

// ---------- speech recognition (browser) ----------
function listen(code, { onStart, onText, onEnd, onError }) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { onError("Speech recognition isn't supported in this browser. Use Chrome or Edge" + (caps && caps.stt ? ", or the server recording button." : ".")); return null; }
  const l = byCode(code);
  if (!l) { onError("Please choose a specific language first."); return null; }
  const rec = new SR();
  rec.lang = l.speech_tag; rec.interimResults = false; rec.maxAlternatives = 1;
  rec.onstart = onStart;
  rec.onresult = (e) => onText(e.results[0][0].transcript);
  rec.onerror = (e) => onError({
    "not-allowed": "Microphone permission was denied. Allow the mic in the address bar and try again.",
    "no-speech": "I didn't hear anything. Try again.",
    "language-not-supported": `${l.english_name} speech recognition isn't available in this browser.` + (caps && caps.stt ? " Try the server recording button." : ""),
    "network": "Speech recognition needs an internet connection in this browser.",
  }[e.error] || `Speech recognition error: ${e.error}`);
  rec.onend = onEnd;
  try { rec.start(); } catch (_) { onError("Could not start the microphone."); return null; }
  return rec;
}

// ---------- translate ----------
const translate = (text, source, target, save = true) =>
  api("/api/v1/translate", { method: "POST", body: JSON.stringify({ text, source, target, save_history: save }) });
let liveSeq = 0, retryPending = false;
function showEngine(r) {
  const n = $("engineNote");
  if (r.provider === "phrasebook") { n.textContent = t("text.via_phrasebook"); n.hidden = false; }
  else if (!r.is_mock && r.provider) { n.textContent = t("text.via", { engine: r.provider }); n.hidden = false; }
  else n.hidden = true;
}
function showDetected(r) {
  if ($("srcLang").value !== "auto" || !r.detected || !r.detected.language) return;
  const chip = $("detectChip"), code = r.detected.language;
  chip.hidden = false; chip.textContent = t("text.detected", { lang: langName(code) + (r.detected.ambiguous ? " ?" : "") });
  chip.onclick = () => { $("srcLang").value = code; localStorage.ut_src = code; updateTalkLabels(); chip.hidden = true; };
}
async function runTextTranslate(live = false) {
  const btn = $("translateBtn"), out = $("outputBox"), mine = ++liveSeq;
  if (live !== true) { btn.disabled = true; btn.textContent = t("text.translating"); }
  out.classList.remove("err");
  try {
    const r = await translate($("inputText").value, $("srcLang").value, $("tgtLang").value, live !== true);
    if (mine !== liveSeq) return;                                  // a newer request replaced this one
    out.textContent = r.translation; setDir(out, r.target);
    lastTranslation = { text: r.translation, lang: r.target };
    pushRecent(r.target, r.source); showEngine(r); showDetected(r); retryPending = false;
    if (r.is_mock && r.translation.startsWith("[MOCK")) banner(t("about.mock")); else banner("");
    if (live !== true && $("autoSpeak").checked) speak(r.translation, r.target);
  } catch (e) {
    if (mine !== liveSeq) return;
    if (e.code === "network") { retryPending = true; banner(t("net.retrying")); out.textContent = ""; }
    else { out.textContent = e.message; out.classList.add("err"); $("engineNote").hidden = true; }
  } finally { if (live !== true) { btn.disabled = false; btn.textContent = t("text.translate"); } }
}
function dictate() {
  if (dictRec) { dictRec.stop(); return; }
  const src = $("srcLang").value, b = $("dictBtn");
  if (src === "auto") { banner(t("lang.from") + "?"); return; }
  dictRec = listen(src, {
    onStart: () => { b.classList.add("live"); banner(""); },
    onText: (x) => { const i = $("inputText"); i.value = (i.value + " " + x).trim(); i.dispatchEvent(new Event("input")); runTextTranslate(); },
    onEnd: () => { b.classList.remove("live"); dictRec = null; },
    onError: banner,
  });
}
let dictRec = null, rec = null, talkRec = null;

// ---------- voice tab ----------
async function handleSpoken(text, src) {
  $("heard").textContent = text; setDir($("heard"), src); $("micStatus").textContent = t("text.translating");
  try {
    const r = await translate(text, src, $("tgtLang").value);
    $("voiceOut").textContent = r.translation; setDir($("voiceOut"), r.target);
    lastTranslation = { text: r.translation, lang: r.target };
    $("micStatus").textContent = t("voice.ready"); speak(r.translation, r.target);
  } catch (e) { $("micStatus").textContent = e.message; }
}
function micToggle() {
  if (rec) { rec.stop(); return; }
  const src = $("srcLang").value;
  if (src === "auto") { banner(t("lang.from") + "?"); return; }
  const mic = $("micBtn"), status = $("micStatus");
  rec = listen(src, {
    onStart: () => { mic.classList.add("live"); status.textContent = t("text.listening"); },
    onText: (x) => handleSpoken(x, src),
    onEnd: () => { mic.classList.remove("live"); rec = null; if (status.textContent === t("text.listening")) status.textContent = t("voice.ready"); },
    onError: (m) => { status.textContent = m; },
  });
}

// ---------- talk (two people) ----------
function talk(side) {
  if (talkRec) { talkRec.stop(); return; }
  const from = side === "a" ? $("srcLang").value : $("tgtLang").value, to = side === "a" ? $("tgtLang").value : $("srcLang").value;
  if (from === "auto" || to === "auto") { banner(t("lang.from") + "?"); return; }
  const btn = $(side === "a" ? "talkA" : "talkB");
  talkRec = listen(from, {
    onStart: () => btn.classList.add("live"),
    onText: async (x) => {
      try {
        const r = await translate(x, from, to);
        const div = document.createElement("div"); div.className = `msg ${side}`;
        const a = document.createElement("div"); a.className = "s"; a.textContent = x;
        const b = document.createElement("div"); b.className = "t"; b.textContent = r.translation; setDir(b, to);
        div.append(a, b); $("talkLog").prepend(div); speak(r.translation, to);
      } catch (e) { banner(e.message); }
    },
    onEnd: () => { btn.classList.remove("live"); talkRec = null; },
    onError: banner,
  });
}

// ---------- history ----------
async function loadHistory() {
  const box = $("historyList"); box.textContent = "…";
  try {
    const { items } = await api("/api/v1/history");
    box.textContent = items.length ? "" : t("history.none");
    for (const it of items) {
      const d = document.createElement("div"); d.className = "msg";
      const s = document.createElement("div"); s.className = "s"; s.textContent = `${it.source} → ${it.target} · ${it.created_at}`;
      const x = document.createElement("div"); x.className = "t"; x.textContent = `${it.source_text}  ⟶  ${it.translated_text}`;
      const row = document.createElement("div"); row.className = "row";
      const fav = document.createElement("button"); fav.className = "btn ghost"; fav.textContent = it.favorite ? "★" : "☆";
      fav.onclick = async () => { await api(`/api/v1/history/${it.id}/favorite`, { method: "POST" }); loadHistory(); };
      const sp = document.createElement("button"); sp.className = "btn ghost"; sp.textContent = "🔊"; sp.onclick = () => speak(it.translated_text, it.target);
      row.append(fav, sp); d.append(s, x, row); box.append(d);
    }
  } catch (e) { box.textContent = e.message; }
}

// ---------- tabs ----------
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll(".tabpanel").forEach((p) => (p.hidden = p.id !== `tab-${name}`));
  if (name !== "camera" && camera) camera.stopCamera();
  $("tab-text").parentElement.querySelector(".langbar").hidden = ["call", "history", "setup", "about"].includes(name);
  if (name === "history") loadHistory();
  if (name === "setup" && setup) setup.render();
  banner("");
}

async function init() {
  await initI18n();
  const sel = $("uiLang");
  const paintLocales = async () => {
    sel.innerHTML = "";
    (await listLocales()).forEach((l) => sel.add(new Option(l.name + (l.draft ? ` (${t("ui.draft")})` : ""), l.code)));
    sel.value = getLocale();
  };
  await paintLocales();
  sel.onchange = () => setLocale(sel.value);
  await initAccount();
  try { LANGS = (await api("/api/v1/languages")).languages; }
  catch (e) { banner(e.message); return; }
  try { caps = await api("/api/v1/capabilities"); } catch (_) { caps = { stt: false, ffmpeg: false, tts: false, livekit: false, languages: LANGS.length, ocr: { provider: "?", mock: true }, limits: { max_participants: 4, max_large: 12 }, auth_mode: "off" }; }
  serverTts = !!caps.tts;
  refillLanguages();
  const ctx = { $, api, byCode, getLangs: () => LANGS, banner, speak, setDir, lowData, t, caps };
  camera = initCamera(ctx);
  initCall(ctx);
  initDocs(ctx);
  setup = initSetup({ caps, byCode, getTarget: () => $("tgtLang").value, getLangs: () => LANGS });
  document.addEventListener("phrasebookchange", async () => { try { LANGS = (await api("/api/v1/languages")).languages; refillLanguages(); } catch (_) {} });
  initServerVoice({ caps, onText: handleSpoken });

  ["srcLang", "tgtLang"].forEach((id) => $(id).addEventListener("change", () => {
    localStorage.ut_src = $("srcLang").value; localStorage.ut_tgt = $("tgtLang").value; updateTalkLabels(); updateDetectChip();
  }));
  document.addEventListener("localechange", () => { refillLanguages(); paintLocales(); updateDetectChip(); });
  document.addEventListener("authchange", () => { if (!$("tab-history").hidden) loadHistory(); });
  $("langSearch").addEventListener("input", refillLanguages);
  $("swapBtn").onclick = () => {
    const s = $("srcLang").value, tg = $("tgtLang").value; if (s === "auto") return banner(t("lang.from") + "?");
    fillSelect($("srcLang"), true, tg); fillSelect($("tgtLang"), false, s);
    const i = $("inputText"), o = $("outputBox"); [i.value, o.textContent] = [o.textContent, i.value]; updateTalkLabels();
  };
  let hintTimer = null, liveTimer = null;
  $("inputText").addEventListener("input", () => {
    $("counter").textContent = `${$("inputText").value.length} / 2000`;
    clearTimeout(hintTimer); hintTimer = setTimeout(updateDetectChip, 300);
    clearTimeout(liveTimer);                                       // "Live": translate shortly after typing stops
    if ($("liveTranslate").checked && $("inputText").value.trim().length >= 3) liveTimer = setTimeout(() => runTextTranslate(true), 900);
  });
  try { $("liveTranslate").checked = localStorage.ut_live === "1"; } catch (_) {}
  $("liveTranslate").onchange = (e) => { try { localStorage.ut_live = e.target.checked ? "1" : "0"; } catch (_) {} };
  window.addEventListener("online", () => { if (retryPending && $("inputText").value.trim()) runTextTranslate(); });
  const paintEmpty = () => { $("outputBox").dataset.empty = t("text.empty"); };
  paintEmpty(); document.addEventListener("localechange", paintEmpty);
  $("inputText").addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runTextTranslate(); });
  $("translateBtn").onclick = () => runTextTranslate();
  $("clearBtn").onclick = () => { liveSeq++; $("engineNote").hidden = true; $("inputText").value = ""; $("outputBox").textContent = ""; $("counter").textContent = "0 / 2000"; $("detectChip").hidden = true; };
  $("speakBtn").onclick = () => speak(lastTranslation.text, lastTranslation.lang);
  $("voiceReplay").onclick = () => speak(lastTranslation.text, lastTranslation.lang);
  $("copyBtn").onclick = async () => { try { await navigator.clipboard.writeText($("outputBox").textContent); banner(t("text.copied")); } catch (_) { banner("Copy failed."); } };
  $("shareBtn").onclick = async () => { const x = $("outputBox").textContent; if (navigator.share) { try { await navigator.share({ text: x }); } catch (_) {} } else banner("Sharing isn't supported here: use Copy."); };
  $("micBtn").onclick = micToggle; $("dictBtn").onclick = dictate;
  $("rateRange").value = rate(); $("rateVal").textContent = rate().toFixed(1) + "×";
  $("rateRange").oninput = (e) => { localStorage.ut_rate = e.target.value; $("rateVal").textContent = parseFloat(e.target.value).toFixed(1) + "×"; };
  $("voiceSel").onchange = (e) => { localStorage["ut_voice_" + $("tgtLang").value] = e.target.value; };
  $("voiceTest").onclick = () => {
    const code = $("tgtLang").value, text = lastTranslation.lang === code && lastTranslation.text ? lastTranslation.text : SAMPLE[code];
    if (!text) { banner("Translate something into this language first, then press Test voice."); return; }
    speak(text, code);
  };
  $("voiceCheck").onclick = voiceCheck;
  $("tgtLang").addEventListener("change", refreshVoiceList); refreshVoiceList();
  $("talkA").onclick = () => talk("a"); $("talkB").onclick = () => talk("b");
  $("clearHistory").onclick = async () => { if (confirm(t("history.confirm"))) { await api("/api/v1/history", { method: "DELETE" }); loadHistory(); } };
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  $("themeBtn").onclick = () => { const h = document.documentElement; h.dataset.theme = h.dataset.theme === "dark" ? "light" : "dark"; };
  if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = refreshVoiceList;
  try { const h = await api("/health"); $("aboutInfo").textContent = `${h.translation_provider}${h.mock ? " (MOCK)" : ""} · OCR: ${h.ocr_provider}${h.ocr_mock ? " (MOCK)" : ""} · ${LANGS.length}`; } catch (_) {}

  const invite = (new URLSearchParams(location.search).get("room") || "").toUpperCase();
  if (/^[A-HJ-NP-Z2-9]{6}$/.test(invite)) { showTab("call"); $("callCode").value = invite; }
  initPwa({ showTab });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js").catch(() => {});
  const fit = () => document.documentElement.style.setProperty("--topbar-h", document.querySelector(".topbar").offsetHeight + "px");
  fit(); window.addEventListener("resize", fit); document.addEventListener("localechange", fit);
  window.__ready = true;
}
init();
