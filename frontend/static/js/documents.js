// Documents (.txt .md .srt .vtt .docx .pdf) and subtitles-from-audio/video. Files are sent raw (no multipart).
import { $, apiRaw, api, banner, download } from "/static/js/core.js";
import { t } from "/static/js/i18n.js";

const enc = encodeURIComponent;
function dropZone(zone, input, onFile) {
  input.onchange = (e) => onFile(e.target.files[0] || null);
  ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
  zone.addEventListener("drop", (e) => onFile(e.dataTransfer.files[0] || null));
}
const size = (f) => (f.size > 1e6 ? (f.size / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round(f.size / 1024)) + " KB");

export function initDocs({ caps }) {
  // ---------------- documents ----------------
  let doc = null;
  const pickDoc = (f) => { doc = f; $("docName").textContent = f ? `${f.name} · ${size(f)}` : ""; $("docTranslate").disabled = !f; $("docStatus").textContent = ""; };
  dropZone($("docDrop"), $("docFile"), pickDoc);
  $("docTranslate").onclick = async () => {
    if (!doc) return;
    const src = $("srcLang").value, tgt = $("tgtLang").value, btn = $("docTranslate"), st = $("docStatus");
    btn.disabled = true; st.classList.remove("err"); st.textContent = t("docs.working");
    try {
      const res = await apiRaw(`/api/v1/documents/translate?source=${enc(src)}&target=${enc(tgt)}&filename=${enc(doc.name)}`,
        { method: "POST", body: doc, headers: { "Content-Type": "application/octet-stream" }, timeout: 600000, retries: 0 });
      const blob = await res.blob();
      let stats = {}; try { stats = JSON.parse(res.headers.get("X-Doc-Stats") || "{}"); } catch (_) {}
      const cd = res.headers.get("Content-Disposition") || "";
      const name = decodeURIComponent((/filename\*=UTF-8''([^;]+)/.exec(cd) || [])[1] || "translated.txt");
      download(blob, name);
      st.textContent = t("docs.done", { name }) + (stats.mock ? " ⚠ " + t("docs.mock") : "");
    } catch (e) { st.textContent = e.message; st.classList.add("err"); }
    finally { btn.disabled = false; }
  };

  // ---------------- subtitles ----------------
  let media = null, job = null, timer = null;
  const pickMedia = (f) => { media = f; $("subName").textContent = f ? `${f.name} · ${size(f)}` : ""; $("subStart").disabled = !f; };
  dropZone($("subDrop"), $("subFile"), pickMedia);
  const stop = () => { clearInterval(timer); timer = null; $("subStart").disabled = !media; };
  $("subStart").onclick = async () => {
    const src = $("srcLang").value, tgt = $("tgtLang").value, st = $("subStatus");
    $("subDownload").hidden = $("subDownloadSrc").hidden = true; st.classList.remove("err");
    if (src === "auto") { st.textContent = t("lang.from") + "?"; st.classList.add("err"); return; }
    if (!caps.stt || !caps.ffmpeg) { st.textContent = t("subs.hint"); st.classList.add("err"); return; }
    $("subStart").disabled = true; $("subProgress").hidden = false; $("subProgress").value = 0;
    try {
      const r = await (await apiRaw(`/api/v1/subtitles?source=${enc(src)}&target=${enc(tgt === src ? "" : tgt)}&filename=${enc(media.name)}`,
        { method: "POST", body: media, headers: { "Content-Type": "application/octet-stream" }, timeout: 600000, retries: 0 })).json();
      job = r.job;
      timer = setInterval(async () => {
        try {
          const s = await api(`/api/v1/jobs/${job}`);
          $("subProgress").value = Math.round(s.progress * 100);
          st.textContent = s.status === "error" ? s.error.message : t("subs.working", { pct: Math.round(s.progress * 100) }) + (s.note ? " · " + s.note : "");
          if (s.status === "error") { st.classList.add("err"); stop(); $("subProgress").hidden = true; }
          if (s.status === "done") { stop(); $("subProgress").hidden = true; st.textContent = "✓ " + (s.segments || 0) + " ▸ .srt";
            $("subDownload").hidden = false; $("subDownloadSrc").hidden = !s.translated; }
        } catch (e) { st.textContent = e.message; st.classList.add("err"); stop(); }
      }, 1500);
    } catch (e) { st.textContent = e.message; st.classList.add("err"); $("subProgress").hidden = true; $("subStart").disabled = false; }
  };
  const save = (which) => async () => {
    try { download(await (await apiRaw(`/api/v1/jobs/${job}/download?which=${which}`)).blob(), "subtitles.srt"); }
    catch (e) { banner(e.message); }
  };
  $("subDownload").onclick = save("final");
  $("subDownloadSrc").onclick = save("source");
}
