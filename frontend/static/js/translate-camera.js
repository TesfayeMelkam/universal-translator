// Camera / photo translation. The photo is re-encoded as JPEG in the browser (smaller in low-data mode), sent to the
// server for OCR + translation, then the translated text is drawn back over the photo where the original text was.
export function initCamera({ $, api, speak, setDir, banner, lowData, t }) {
  const video = $("camVideo"), canvas = $("camCanvas"), preview = $("camPreview"), result = $("camResult");
  let stream = null, imageData = null, resultName = "translated.png";

  function stopCamera() {
    if (stream) stream.getTracks().forEach((x) => x.stop());
    stream = null; video.srcObject = null; video.hidden = true;
    $("camCapture").hidden = true; $("camStart").hidden = false;
  }
  async function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { banner("This browser can't open the camera. Use 'Upload photo' instead."); return; }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      video.srcObject = stream; video.hidden = false; $("camCapture").hidden = false; $("camStart").hidden = true; banner("");
    } catch (e) {
      banner(e.name === "NotAllowedError" ? "Camera permission was denied. Allow the camera in the address bar, or use 'Upload photo'."
        : "Could not open the camera. Use 'Upload photo' instead.");
    }
  }
  function drawScaled(source, w, h) {
    const low = lowData(), max = low ? 1024 : 1600, k = Math.min(1, max / Math.max(w, h));
    canvas.width = Math.round(w * k); canvas.height = Math.round(h * k);
    canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
    setImage(canvas.toDataURL("image/jpeg", low ? 0.6 : 0.85));
  }
  function setImage(dataUrl) {
    imageData = dataUrl; preview.src = dataUrl; preview.hidden = false; result.hidden = true; $("camDownload").hidden = true;
    $("camTranslate").disabled = false; $("camOriginal").textContent = ""; $("camTranslation").textContent = "";
  }
  function capture() {
    if (!video.videoWidth) { banner("Camera is not ready yet."); return; }
    drawScaled(video, video.videoWidth, video.videoHeight); stopCamera();
  }
  function onFile(e) {
    const f = e.target.files[0]; if (!f) return;
    if (!/^image\/(png|jpeg|webp)$/.test(f.type)) { banner("Please choose a PNG, JPEG or WebP image."); return; }
    resultName = f.name.replace(/\.[^.]+$/, "") + ".translated.png";
    const img = new Image();
    img.onload = () => { drawScaled(img, img.naturalWidth, img.naturalHeight); URL.revokeObjectURL(img.src); };
    img.onerror = () => banner("That image could not be opened.");
    img.src = URL.createObjectURL(f);
  }

  // Draw each translated line on top of the original line. Boxes come from OCR in the pixel space of the sent image.
  function drawOverlay(regions, rtl) {
    const img = new Image();
    img.onload = () => {
      result.width = img.naturalWidth; result.height = img.naturalHeight;
      const g = result.getContext("2d"); g.drawImage(img, 0, 0);
      for (const r of regions) {
        // paint over the original with the colour found just outside its box, then pick a readable text colour
        const sx = Math.max(0, Math.min(result.width - 1, Math.round(r.x - 3))), sy = Math.max(0, Math.min(result.height - 1, Math.round(r.y - 3)));
        const c = g.getImageData(sx, sy, 1, 1).data, lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2];
        g.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`; g.fillRect(r.x - 2, r.y - 2, r.w + 4, r.h + 4);
        let size = Math.max(9, Math.round(r.h * 0.82));
        const family = '"Noto Sans Ethiopic","Nyala","Segoe UI","Noto Sans Arabic",sans-serif';
        g.font = `${size}px ${family}`;
        while (size > 9 && g.measureText(r.translation).width > r.w) { size -= 1; g.font = `${size}px ${family}`; }
        g.fillStyle = lum > 140 ? "#111" : "#fff"; g.textBaseline = "middle"; g.direction = rtl ? "rtl" : "ltr"; g.textAlign = rtl ? "right" : "left";
        g.fillText(r.translation, rtl ? r.x + r.w : r.x, r.y + r.h / 2, Math.max(r.w, 40));
      }
      result.hidden = false; preview.hidden = true; $("camDownload").hidden = false;
    };
    img.src = imageData;
  }

  async function run() {
    const src = $("srcLang").value, tgt = $("tgtLang").value;
    if (src === "auto") { banner(t("lang.from") + "?"); return; }
    const btn = $("camTranslate"); btn.disabled = true; btn.textContent = t("camera.reading");
    const o = $("camOriginal"), tr = $("camTranslation"); tr.classList.remove("err");
    try {
      const r = await api("/api/v1/vision/translate", { method: "POST", body: JSON.stringify({ image: imageData, source: src, target: tgt }), timeout: 120000 });
      o.textContent = r.source_text; setDir(o, r.source);
      tr.textContent = r.translation; setDir(tr, r.target);
      const bits = [];
      if (r.ocr.is_mock) bits.push("OCR is a MOCK: it did not really read your picture. Install Tesseract (see README).");
      else if (r.ocr.confidence != null) bits.push(`OCR confidence ${r.ocr.confidence}% (engine's own estimate; check important text).`);
      if (r.ocr.truncated) bits.push("Text was cut to the length limit.");
      banner(bits.join(" "));
      if (r.overlay && r.overlay.length) drawOverlay(r.overlay, !!r.rtl);
      speak(r.translation, r.target);
    } catch (e) { o.textContent = ""; tr.textContent = e.message; tr.classList.add("err"); }
    finally { btn.disabled = false; btn.textContent = t("camera.read"); }
  }
  $("camStart").onclick = startCamera; $("camCapture").onclick = capture;
  $("camFile").onchange = onFile; $("camTranslate").onclick = run;
  $("camSpeak").onclick = () => speak($("camTranslation").textContent, $("tgtLang").value);
  $("camDownload").onclick = () => result.toBlob((b) => {
    const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = resultName; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 3000);
  }, "image/png");
  return { stopCamera };
}
