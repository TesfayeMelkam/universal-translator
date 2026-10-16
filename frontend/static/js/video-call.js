// Group video call (WebRTC "mesh": every person has a direct link to every other person) with live
// translated captions. Video/audio go peer-to-peer. The server only creates rooms, relays small
// setup messages to ONE named peer, and translates caption text. Nothing is recorded.
// Mesh is simple but each person uploads one video per other person, so keep groups small.
import { joinLarge } from "/static/js/large-call.js";

export function initCall({ $, api, byCode, getLangs, banner, speak, lowData = () => false, caps = {} }) {
  let ws = null, stream = null, rtc = { iceServers: [] };
  let myId = null, myLang = "en", roomCode = "", maxPeople = 4, pingTimer = null;
  let rec = null, wantRec = false, recFails = 0, talking = false, ttsChain = Promise.resolve();
  let micOn = true, showCaps = true, sayCaps = false, sawMock = false, leaving = false;
  const peers = new Map();            // id -> { id, name, lang, pc, pending, tile, video, st }
  const transcript = [];
  let large = null, largeCount = 0, lastInterim = 0, sfuPending = false;
  const live = new Map();             // speaker id -> live (still being spoken) caption line
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const send = (obj) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); };
  const setWait = (t) => { $("waitMsg").hidden = !t; if (t) $("waitMsg").firstChild.textContent = t; };

  // ---------- lobby ----------
  function fillLangs() {
    const sel = $("callLang"); sel.innerHTML = "";
    getLangs().forEach((l) => sel.add(new Option(`${l.native_name} — ${l.english_name}`, l.code)));
    const pref = localStorage.ut_call_lang || (localStorage.ut_src && localStorage.ut_src !== "auto" ? localStorage.ut_src : "en");
    sel.value = byCode(pref) ? pref : "en";
  }
  async function getMedia(audioOnly) {
    const audio = { echoCancellation: true, noiseSuppression: true };
    const video = lowData() ? { width: { ideal: 640 }, height: { ideal: 360 }, frameRate: { ideal: 15 }, facingMode: "user" }
                            : { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" };
    try {
      return await navigator.mediaDevices.getUserMedia(audioOnly ? { audio } : { video, audio });
    } catch (e) {
      if (e.name === "NotAllowedError") { banner("Camera/microphone permission was denied. Allow them in the address bar and try again."); return null; }
      if (!audioOnly && (e.name === "NotFoundError" || e.name === "OverconstrainedError")) {
        try { const a = await navigator.mediaDevices.getUserMedia({ audio: true }); banner("No camera found: joining with audio only."); return a; }
        catch (_) { banner("No camera or microphone was found."); return null; }
      }
      banner("Could not start the camera/microphone: " + e.name); return null;
    }
  }
  async function join(code) {
    code = (code || "").trim().toUpperCase();
    if (!$("callConsent").checked) return banner("Please tick the box to confirm you understand how the call works.");
    if (!/^[A-HJ-NP-Z2-9]{6}$/.test(code)) return banner("Room codes have 6 letters/numbers.");
    if (!window.isSecureContext || !navigator.mediaDevices) { $("secureWarn").hidden = false; return; }
    if (!window.RTCPeerConnection) return banner("This browser does not support video calls. Use Chrome or Edge.");
    let info;
    try { info = await api(`/api/v1/rooms/${code}`); maxPeople = info.max || maxPeople;
      if (info.full) return banner(`That call is full (${info.max} people maximum).`); }
    catch (e) { return banner(e.message); }
    banner("");
    const audioOnly = $("callAudioOnly").checked, isLarge = info.mode === "sfu";
    sfuPending = isLarge;
    if (!isLarge) {
      stream = await getMedia(audioOnly); if (!stream) return;
      try { rtc = await api(`/api/v1/rtc-config?room=${code}`); } catch (_) { rtc = { iceServers: [] }; }
    }
    myLang = $("callLang").value; localStorage.ut_call_lang = myLang;
    roomCode = code; micOn = true;
    if (stream) $("localVideo").srcObject = stream;
    $("callLobby").hidden = true; $("callStage").hidden = false; $("callRoom").textContent = code;
    $("cCam").disabled = isLarge ? audioOnly : !stream.getVideoTracks().length;
    ["cMic", "cCam"].forEach((id) => $(id).classList.remove("off"));
    $("cCap").classList.toggle("on", showCaps); $("cSay").classList.toggle("on", sayCaps);
    layout(); connect(code);
    if (isLarge) {
      try {
        const tokenInfo = await api(`/api/v1/livekit/token?room=${code}&name=${encodeURIComponent($("callName").value.trim() || "Guest")}`);
        large = await joinLarge({ $, tokenInfo, audioOnly, onCount: (n) => { largeCount = n; layout(); } });
      } catch (e) { banner(e.message); leave(); }
    }
  }
  async function create(mode) {
    if (!$("callConsent").checked) return banner("Please tick the box to confirm you understand how the call works.");
    try { const { code } = await api("/api/v1/rooms" + (mode === "sfu" ? "?mode=sfu" : ""), { method: "POST" }); $("callCode").value = code; await join(code); }
    catch (e) { banner(e.message); }
  }

  // ---------- people / video tiles ----------
  function addPeer(p) {
    const old = peers.get(p.id);
    if (old) { old.name = p.name; old.lang = p.lang; return old; }
    const tile = document.createElement("div"); tile.className = "tile remote";
    const video = document.createElement("video"); video.autoplay = true; video.playsInline = true;
    const label = document.createElement("div"); label.className = "vlabel"; label.textContent = p.name;
    const st = document.createElement("div"); st.className = "tstatus"; st.textContent = "Connecting…";
    const badge = document.createElement("div"); badge.className = "tbadge";
    tile.append(video, label, badge, st); $("videoGrid").insertBefore(tile, $("localTile"));
    const peer = { id: p.id, name: p.name, lang: p.lang, pc: null, pending: [], tile, video, st, badge,
                   offerer: false, restarts: 0, statsTimer: null, downTimer: null };
    peers.set(p.id, peer); layout(); return peer;
  }
  function removePeer(id) {
    const p = peers.get(id); if (!p) return;
    closePc(p); p.tile.remove(); peers.delete(id); layout();
  }
  function layout() {
    const n = isSfuRoom() ? largeCount : peers.size;
    $("videoGrid").dataset.n = String(Math.min(n, 5));
    setWait(n ? null : "Waiting for others to join…");
    $("callStatus").textContent = n ? `${n + 1} of ${maxPeople} people in the call` : `Waiting for others (1 of ${maxPeople})`;
    adjustQuality();
  }
  function adjustQuality() {   // less video per link when there are many links (mesh uploads one copy per person)
    const t = stream && stream.getVideoTracks()[0]; if (!t || !t.applyConstraints) return;
    t.applyConstraints(lowData() || peers.size >= 2 ? { width: { ideal: 640 }, height: { ideal: 360 }, frameRate: { ideal: 24 } }
                                       : { width: { ideal: 1280 }, height: { ideal: 720 } }).catch(() => {});
  }

  // ---------- signalling ----------
  function connect(code) {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/rooms/${code}`);
    ws.onopen = () => {
      send({ type: "join", name: $("callName").value.trim() || "Guest", lang: myLang });
      pingTimer = setInterval(() => send({ type: "ping" }), 25000);
    };
    ws.onmessage = (e) => { let m; try { m = JSON.parse(e.data); } catch (_) { return; } onMessage(m); };
    ws.onerror = () => banner("Could not reach the call server.");
    ws.onclose = () => { if (!leaving) { $("callStatus").textContent = "Disconnected from server"; peers.forEach((p) => closePc(p)); setWait("Disconnected"); } };
  }
  async function onMessage(m) {
    try {
      if (m.type === "joined") {
        myId = m.id; maxPeople = m.max || maxPeople;
        if (!isSfuRoom()) m.peers.forEach(addPeer);   // existing members will send US their offers (mesh calls only)
        layout(); wantRec = true; startRec();
      } else if (m.type === "peer_joined") {
        if (isSfuRoom()) return;                // large call: media goes through the media server, no peer links
        const p = addPeer(m.peer); await makeOffer(p);   // we were here first, so we make the offer
      } else if (m.type === "peer_left") removePeer(m.id);
      else if (m.type === "peer_lang") { const p = peers.get(m.id); if (p) p.lang = m.lang; }
      else if (m.type === "signal") await onSignal(m.from, m.data);
      else if (m.type === "interim") onInterim(m);
      else if (m.type === "caption") onCaption(m);
      else if (m.type === "caption_self") addCaption({ mine: true, text: m.text, lang: m.lang });
      else if (m.type === "error") { banner(m.message); if (m.fatal) leave(); }
    } catch (e) { console.error(e); banner("Something went wrong with the call connection."); }
  }

  // ---------- one WebRTC link per other person ----------
  function ensurePc(p) {
    if (p.pc) return p.pc;
    const pc = new RTCPeerConnection({ iceServers: rtc.iceServers });
    p.pc = pc;
    stream.getTracks().forEach((t) => pc.addTrack(t, stream));
    pc.onicecandidate = (e) => { if (e.candidate) send({ type: "signal", to: p.id, data: { candidate: e.candidate.toJSON() } }); };
    pc.ontrack = (e) => { p.video.srcObject = e.streams[0]; p.st.hidden = true; };
    pc.onconnectionstatechange = () => {
      const state = pc.connectionState;
      clearTimeout(p.downTimer);
      if (state === "connected") {
        p.st.hidden = true; p.restarts = 0; pollStats(p);
        if (!p.statsTimer) p.statsTimer = setInterval(() => pollStats(p), 3000);
      } else if (state === "disconnected") {
        p.st.hidden = false; p.st.textContent = "Reconnecting…";
        p.downTimer = setTimeout(() => { if (p.pc === pc && pc.connectionState !== "connected") recover(p); }, 5000);
      } else if (state === "failed") recover(p);
    };
    return pc;
  }
  function closePc(p) {
    if (p.pc) { p.pc.onicecandidate = p.pc.ontrack = p.pc.onconnectionstatechange = null; p.pc.close(); p.pc = null; }
    clearInterval(p.statsTimer); clearTimeout(p.downTimer); p.statsTimer = p.downTimer = null; p.badge.textContent = "";
    p.pending = []; p.video.srcObject = null;
    if (!leaving) { p.st.hidden = false; p.st.textContent = "Connecting…"; }
  }
  async function makeOffer(p, opts) {
    if (!opts) closePc(p);
    p.offerer = true; const pc = ensurePc(p);
    const offer = await pc.createOffer(opts); await pc.setLocalDescription(offer);
    send({ type: "signal", to: p.id, data: { sdp: { type: pc.localDescription.type, sdp: pc.localDescription.sdp } } });
  }
  async function onSignal(fromId, d) {
    if (!d) return;
    const p = peers.get(fromId); if (!p) return;      // only people the server told us about
    if (d.sdp) {
      if (d.sdp.type === "offer") { p.offerer = false; ensurePc(p); } else if (!p.pc) return;   // an offer on a live link = ICE restart
      await p.pc.setRemoteDescription(d.sdp);
      if (d.sdp.type === "offer") {
        const ans = await p.pc.createAnswer(); await p.pc.setLocalDescription(ans);
        send({ type: "signal", to: p.id, data: { sdp: { type: p.pc.localDescription.type, sdp: p.pc.localDescription.sdp } } });
      }
      for (const c of p.pending.splice(0)) await p.pc.addIceCandidate(c).catch(() => {});
    } else if (d.candidate) {
      if (p.pc && p.pc.remoteDescription) await p.pc.addIceCandidate(d.candidate).catch(() => {});
      else p.pending.push(d.candidate);
    }
  }

  // ---------- staying connected across networks ----------
  async function recover(p) {
    // The person who made the original offer re-negotiates (an "ICE restart"); the other side just answers.
    p.st.hidden = false; p.st.textContent = "Reconnecting…";
    if (p.offerer && p.pc && p.restarts < 3) {
      p.restarts++;
      try { if (p.pc.restartIce) p.pc.restartIce(); await makeOffer(p, { iceRestart: true }); return; }
      catch (_) { /* fall through to the failure message */ }
    }
    if (p.offerer || p.restarts >= 3) {
      p.st.textContent = "Could not connect";
      banner(rtc.turn
        ? `Could not connect to ${p.name} even through the relay server. Check that the relay's ports are open in the host's firewall.`
        : `Could not connect to ${p.name}. You are probably on different networks and no relay (TURN) server is set up. See README → Calls across different networks.`);
    }
  }
  async function pollStats(p) {
    if (!p.pc || !p.pc.getStats) return;
    try {
      const stats = await p.pc.getStats(); let pair = null;
      stats.forEach((r) => { if (r.type === "candidate-pair" && r.nominated && r.state === "succeeded") pair = r; });
      if (!pair) return;
      const local = stats.get(pair.localCandidateId), remote = stats.get(pair.remoteCandidateId);
      const relayed = (local && local.candidateType === "relay") || (remote && remote.candidateType === "relay");
      const rtt = typeof pair.currentRoundTripTime === "number" ? Math.round(pair.currentRoundTripTime * 1000) : null;
      p.badge.textContent = `${relayed ? "🔁 relayed" : "⚡ direct"}${rtt !== null ? ` · ${rtt} ms` : ""}`;
    } catch (_) { /* stats are optional */ }
  }
  async function networkCheck() {
    const out = $("netResult"), btn = $("callNetCheck");
    if (!window.RTCPeerConnection) { out.textContent = "This browser does not support video calls."; return; }
    btn.disabled = true; out.textContent = "Checking…";
    try {
      const code = ($("callCode").value || "").trim().toUpperCase();
      const valid = /^[A-HJ-NP-Z2-9]{6}$/.test(code);
      const cfg = await api("/api/v1/rtc-config" + (valid ? `?room=${code}` : ""));
      const found = { host: false, srflx: false, relay: false };
      const pc = new RTCPeerConnection({ iceServers: cfg.iceServers });
      pc.createDataChannel("probe");
      const done = new Promise((resolve) => {
        pc.onicecandidate = (e) => {
          if (!e.candidate) return resolve();
          const t = /typ (\w+)/.exec(e.candidate.candidate); if (t) found[t[1]] = true;
        };
        setTimeout(resolve, 6000);
      });
      await pc.setLocalDescription(await pc.createOffer()); await done; pc.close();
      if (found.relay) out.textContent = "✅ Relay server reachable: calls should work even between strict networks.";
      else if (found.srflx && cfg.turnConfigured && !valid) out.textContent = "🟡 Direct connection works. Type a room code and check again to test the relay server.";
      else if (found.srflx && cfg.turnConfigured) out.textContent = "🟡 Direct connection works, but the relay server was not reachable. Some networks may fail.";
      else if (found.srflx) out.textContent = "🟡 Direct connection works. No relay server is set up, so calls between some networks may fail.";
      else if (found.host) out.textContent = "🟠 Only local-network connection found. Calls will work on the same Wi-Fi only. Check your internet and firewall.";
      else out.textContent = "🔴 No network routes found. Check your internet connection and firewall.";
    } catch (e) { out.textContent = "Could not run the check: " + (e.message || e); }
    finally { btn.disabled = false; }
  }

  // ---------- captions ----------
  function startRec() {
    if (!SR) { banner("Speech recognition isn't supported in this browser, so your own speech won't be captioned. Use Chrome or Edge. (You will still see other people's captions.)"); wantRec = false; return; }
    spawn();
  }
  function spawn() {
    if (!wantRec || !micOn || talking || rec || !ws || ws.readyState !== 1) return;
    const l = byCode(myLang); if (!l) return;
    const r = new SR(); r.lang = l.speech_tag; r.continuous = true; r.interimResults = true;
    r.onresult = (e) => {
      recFails = 0; let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i], txt = res[0].transcript.trim();
        if (res.isFinal) { if (txt) { send({ type: "caption", text: txt.slice(0, 1000) }); send({ type: "interim", text: "" }); } }
        else interim += " " + txt;
      }
      interim = interim.trim();
      if (interim && Date.now() - lastInterim > 400) { lastInterim = Date.now(); send({ type: "interim", text: interim.slice(0, 300) }); }
    };
    r.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") { wantRec = false; banner("Microphone permission for captions was denied."); }
      else if (e.error === "language-not-supported") { wantRec = false; banner(`${l.english_name} speech recognition isn't available in this browser, so your speech can't be captioned. Other people's captions still work.`); }
      else if (e.error === "network") { recFails++; banner("Captions need an internet connection for speech recognition."); }
    };
    r.onend = () => { rec = null; if (wantRec && recFails < 5) setTimeout(spawn, 400); };
    try { r.start(); rec = r; } catch (_) { rec = null; }
  }
  function stopRec() { wantRec = false; if (rec) { try { rec.stop(); } catch (_) {} } rec = null; }

  function isSfuRoom() { return !!large || sfuPending; }
  function onInterim(m) {
    let item = live.get(m.from);
    if (!m.text) { if (item) { clearTimeout(item.timer); item.el.remove(); live.delete(m.from); } return; }
    if (!showCaps) return;
    if (!item) { const el = document.createElement("div"); el.className = "cap live"; $("capOverlay").append(el); item = { el, timer: null }; live.set(m.from, item); }
    item.el.textContent = `… ${m.name || "Guest"}: ${m.text}`;
    clearTimeout(item.timer); item.timer = setTimeout(() => { item.el.remove(); live.delete(m.from); }, 6000);
  }
  function onCaption(m) {
    onInterim({ from: m.from, text: "" });
    if (m.is_mock && !sawMock) { sawMock = true; banner("Demo translation mode: only a few greetings are really translated. See the README to turn on the real model."); }
    addCaption({ who: m.name, text: m.translated ?? m.original, orig: m.original, failed: m.translation_failed, lang: m.target });
    if (sayCaps && m.translated) {
      ttsChain = ttsChain.then(async () => {
        talking = true; if (rec) { try { rec.stop(); } catch (_) {} }
        try { await Promise.race([speak(m.translated, myLang), new Promise((r) => setTimeout(r, 15000))]); } catch (_) {}
        talking = false; spawn();
      });
    }
  }
  function addCaption({ who, text, orig, mine, failed, lang }) {
    const label = mine ? "You" : (who || "Guest");
    transcript.push(`[${new Date().toLocaleTimeString()}] ${label}: ${text}${orig && orig !== text ? `  (original: ${orig})` : ""}${failed ? "  (not translated)" : ""}`);
    const l = byCode(lang), dir = l && l.rtl ? "rtl" : "ltr";
    const row = document.createElement("div"); row.className = "msg" + (mine ? "" : " b");
    const s = document.createElement("div"); s.className = "s"; s.textContent = label;
    const t = document.createElement("div"); t.className = "t"; t.textContent = text; t.dir = dir;
    row.append(s, t); $("callLog").prepend(row);
    if (!showCaps) return;
    const c = document.createElement("div"); c.className = "cap" + (mine ? " me" : ""); c.dir = dir;
    c.textContent = (mine ? "You: " : peers.size > 1 ? `${label}: ` : "") + text;
    if (failed) { const o = document.createElement("span"); o.className = "orig"; o.textContent = "(could not translate)"; c.append(o); }
    else if (orig && orig !== text) { const o = document.createElement("span"); o.className = "orig"; o.textContent = orig; c.append(o); }
    const ov = $("capOverlay"); ov.append(c); while (ov.children.length > 4) ov.firstChild.remove();
    setTimeout(() => c.remove(), 9000);
  }

  // ---------- controls ----------
  function leave() {
    leaving = true; stopRec(); clearInterval(pingTimer);
    if (large) { try { large.leave(); } catch (_) {} large = null; }
    largeCount = 0; sfuPending = false; live.forEach((i) => { clearTimeout(i.timer); i.el.remove(); }); live.clear();
    if (ws) { try { ws.close(); } catch (_) {} ws = null; }
    [...peers.values()].forEach((p) => { closePc(p); p.tile.remove(); }); peers.clear();
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    $("localVideo").srcObject = null; $("capOverlay").textContent = ""; $("videoGrid").dataset.n = "0";
    $("callStage").hidden = true; $("callLobby").hidden = false; $("callCode").value = "";
    myId = null; leaving = false; banner("");
  }
  $("callNetCheck").onclick = networkCheck;
  $("callCreate").onclick = () => create();
  if (caps.livekit) { $("callCreateLarge").hidden = false; $("callCreateLarge").onclick = () => create("sfu"); }
  $("callJoin").onclick = () => join($("callCode").value);
  $("callCode").addEventListener("keydown", (e) => { if (e.key === "Enter") join($("callCode").value); });
  $("cMic").onclick = () => {
    micOn = !micOn; if (stream) stream.getAudioTracks().forEach((t) => (t.enabled = micOn));
    if (large) large.setMic(micOn).catch(() => {});
    $("cMic").classList.toggle("off", !micOn);
    if (micOn) spawn(); else if (rec) { try { rec.stop(); } catch (_) {} }
  };
  $("cCam").onclick = () => {
    if (large) { const on = $("cCam").classList.contains("off"); $("cCam").classList.toggle("off", !on); large.setCam(on).catch(() => {}); return; }
    const tr = stream ? stream.getVideoTracks() : []; if (!tr.length) return;
    const on = !tr[0].enabled; tr.forEach((t) => (t.enabled = on)); $("cCam").classList.toggle("off", !on);
  };
  $("cCap").onclick = () => { showCaps = !showCaps; $("cCap").classList.toggle("on", showCaps); if (!showCaps) $("capOverlay").textContent = ""; };
  $("cSay").onclick = () => { sayCaps = !sayCaps; $("cSay").classList.toggle("on", sayCaps);
    if (sayCaps) banner("Reading captions aloud is on. Use headphones so the microphone doesn't hear it. In a busy group it can get crowded."); };
  $("cLeave").onclick = leave;
  $("callCopy").onclick = async () => {
    const link = `${location.origin}/?room=${roomCode}`;
    try { await navigator.clipboard.writeText(link); banner("Invite link copied. Send it to the people you want to invite."); }
    catch (_) { banner("Copy this link: " + link); }
  };
  $("callSave").onclick = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([transcript.join("\n")], { type: "text/plain" }));
    a.download = `transcript-${roomCode}.txt`; a.click(); URL.revokeObjectURL(a.href);
  };
  window.addEventListener("beforeunload", () => { if (ws) ws.close(); });

  fillLangs();
  if (!window.isSecureContext) $("secureWarn").hidden = false;
  return { leave };
}
