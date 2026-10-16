// Record up to 20 s and send it to the server's speech model (needs STT_PROVIDER=mms). Useful for languages the
// browser cannot recognise (Afaan Oromo, Tigrinya...). The audio is processed in memory and not stored.
import { $, apiRaw, banner } from "/static/js/core.js";
import { t } from "/static/js/i18n.js";

export function initServerVoice({ caps, onText }) {
  const btn = $("recServer");
  if (!caps.stt || !caps.ffmpeg || !window.MediaRecorder || !navigator.mediaDevices) return;
  btn.hidden = false;
  let rec = null, chunks = [], stream = null, timer = null;
  const label = btn.querySelector("[data-i18n]");
  const stop = () => { clearTimeout(timer); if (rec && rec.state !== "inactive") rec.stop(); };
  btn.onclick = async () => {
    if (rec) return stop();
    const lang = $("srcLang").value;
    if (lang === "auto") return banner(t("lang.from") + "?");
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
    catch (_) { return banner("Microphone permission was denied."); }
    chunks = []; rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      stream.getTracks().forEach((x) => x.stop()); rec = null; btn.classList.remove("live"); label.textContent = t("voice.server");
      const blob = new Blob(chunks, { type: "audio/webm" });
      if (blob.size < 1500) return;
      try {
        const r = await (await apiRaw(`/api/v1/transcribe?language=${encodeURIComponent(lang)}`,
          { method: "POST", body: blob, headers: { "Content-Type": "application/octet-stream" }, timeout: 120000, retries: 0 })).json();
        if (r.text) onText(r.text, lang); else banner("…");
      } catch (e) { banner(e.message); }
    };
    rec.start(); btn.classList.add("live"); label.textContent = t("voice.recording");
    timer = setTimeout(stop, 20000);
  };
}
