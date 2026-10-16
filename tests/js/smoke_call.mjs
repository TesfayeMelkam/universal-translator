// Node smoke test for frontend/static/js/video-call.js using fake DOM/WebSocket/WebRTC.
// Run:  node tests/js/smoke_call.mjs     (needs Node 18+; no packages)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import assert from "node:assert/strict";

class El {
  constructor() { this.children = []; this.dataset = {}; this.value = ""; this.checked = false; this.hidden = false;
    this.disabled = false; this._text = ""; this.parent = null; this.srcObject = null; this.style = {};
    const set = new Set(); this.classList = { add: (c) => set.add(c), remove: (c) => set.delete(c),
      toggle: (c, f) => (f === undefined ? (set.has(c) ? set.delete(c) : set.add(c)) : f ? set.add(c) : set.delete(c)), has: (c) => set.has(c) }; }
  append(...n) { n.forEach((c) => { if (c && typeof c === "object") { c.parent = this; this.children.push(c); } }); }
  prepend(c) { c.parent = this; this.children.unshift(c); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((x) => x !== this); }
  add() {}
  insertBefore(c) { c.parent = this; this.children.push(c); }
  addEventListener() {}
  get firstChild() { return this.children[0]; }
  set innerHTML(_) { this.children = []; }
  set textContent(v) { this._text = v; if (v === "") this.children = []; }
  get textContent() { return this._text; }
}
const els = {};
const $ = (id) => (els[id] ||= new El());
els.waitMsg = new El(); els.waitMsg.children = [{ textContent: "" }];

let ws, pcs = [];
globalThis.Option = class { constructor(t, v) { this.text = t; this.value = v; } };
globalThis.document = { createElement: () => new El() };
globalThis.localStorage = {};
globalThis.location = { protocol: "http:", host: "x", origin: "http://x" };
globalThis.URL = { createObjectURL: () => "blob:x", revokeObjectURL() {} };
globalThis.WebSocket = class { constructor(u) { ws = this; this.url = u; this.readyState = 1; this.sent = []; }
  send(m) { this.sent.push(JSON.parse(m)); } close() { this.readyState = 3; } };
globalThis.window = { isSecureContext: true, addEventListener() {}, SpeechRecognition: undefined,
  RTCPeerConnection: class { constructor() { pcs.push(this); this.added = 0; this.offers = []; this.connectionState = "new"; }
    addTrack() { this.added++; } createDataChannel() { this.probe = true; }
    async createOffer(o) { this.offers.push(o); return { type: "offer", sdp: "o" }; }
    async createAnswer() { return { type: "answer", sdp: "a" }; }
    restartIce() { this.restarted = true; }
    async setLocalDescription(d) { this.localDescription = d;
      if (this.probe && globalThis.__cands) setTimeout(() => globalThis.__cands.forEach((c) =>
        this.onicecandidate && this.onicecandidate({ candidate: c ? { candidate: c } : null })), 0); }
    async setRemoteDescription(d) { this.remoteDescription = d; }
    async getStats() { return new Map(Object.entries({ pair: { type: "candidate-pair", nominated: true, state: "succeeded",
      localCandidateId: "l", remoteCandidateId: "r", currentRoundTripTime: 0.042 },
      l: { candidateType: "relay" }, r: { candidateType: "host" } })); }
    async addIceCandidate() {} close() { this.closed = true; } } };
globalThis.RTCPeerConnection = window.RTCPeerConnection;
const track = { enabled: true, stop() {} };
Object.defineProperty(globalThis, "navigator", { configurable: true, value: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [track], getAudioTracks: () => [track], getVideoTracks: () => [track] }) } } });

const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../frontend/static/js/video-call.js");
// the page imports its sibling by web path ("/static/js/large-call.js"): point that at a temp copy for Node
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "vc-smoke-"));
for (const f of ["video-call.js", "large-call.js"]) {
  fs.writeFileSync(path.join(dir, f), fs.readFileSync(path.join(path.dirname(src), f), "utf8").replaceAll('"/static/js/', '"./'));
}
const tmp = path.join(dir, "video-call.js");
const { initCall } = await import(pathToFileURL(tmp).href);

const langs = [{ code: "en", english_name: "English", native_name: "English", speech_tag: "en-US", rtl: false },
               { code: "am", english_name: "Amharic", native_name: "አማርኛ", speech_tag: "am-ET", rtl: false }];
const api = async (p, o = {}) => p === "/api/v1/rooms" ? { code: "ABCDEF" }
  : p.startsWith("/api/v1/rooms/") ? { full: false, max: 4 } : { iceServers: [], turn: false, turnConfigured: false, maxParticipants: 4 };
const banners = [];
const call = initCall({ $, api, byCode: (c) => langs.find((l) => l.code === c), getLangs: () => langs,
  banner: (m) => banners.push(m), speak: async () => {} });

$("callConsent").checked = true; $("callLang").value = "en";
await $("callCreate").onclick();
assert.equal($("callStage").hidden, false, "stage shown");
assert.match(ws.url, /ws:\/\/x\/ws\/rooms\/ABCDEF/);
ws.onopen(); assert.deepEqual(ws.sent[0], { type: "join", name: "Guest", lang: "en" });

const recv = async (m) => { ws.onmessage({ data: JSON.stringify(m) }); await new Promise((r) => setTimeout(r, 5)); };
await recv({ type: "joined", id: "me", room: "ABCDEF", you: {}, peers: [{ id: "p1", name: "Abel", lang: "am" }] });
assert.equal($("videoGrid").dataset.n, "1");
assert.equal($("waitMsg").hidden, true, "waiting overlay hidden once someone is there");

await recv({ type: "peer_joined", peer: { id: "p2", name: "Sara", lang: "en" } });
assert.equal($("videoGrid").dataset.n, "2");
const offer = ws.sent.find((m) => m.type === "signal" && m.to === "p2");
assert.equal(offer.data.sdp.type, "offer", "existing member offers to the newcomer only");
assert.equal(ws.sent.filter((m) => m.type === "signal" && m.to === "p1").length, 0, "no offer to the person who already offered");

await recv({ type: "signal", from: "p1", data: { sdp: { type: "offer", sdp: "x" } } });
const answer = ws.sent.find((m) => m.type === "signal" && m.to === "p1");
assert.equal(answer.data.sdp.type, "answer");
assert.equal(pcs.length, 2, "one connection per other person");
assert.ok(pcs.every((p) => p.added === 1), "local tracks added to each connection");


// ---- staying connected across networks ----
const tick = () => new Promise((r) => setTimeout(r, 5));
const offersTo = (id) => ws.sent.filter((m) => m.type === "signal" && m.to === id && m.data.sdp && m.data.sdp.type === "offer");
const [pcSara, pcAbel] = [pcs[0], pcs[1]];            // p2 (we offered) and p1 (they offered)
pcAbel.connectionState = "failed"; pcAbel.onconnectionstatechange(); await tick();
assert.equal(offersTo("p1").length, 0, "the side that did NOT make the offer never re-offers");
for (let i = 1; i <= 3; i++) {
  pcSara.connectionState = "failed"; pcSara.onconnectionstatechange(); await tick();
  assert.equal(offersTo("p2").length, 1 + i, `ICE restart #${i} sent`);
}
assert.equal(pcSara.restarted, true);
assert.equal(pcSara.offers.filter((o) => o && o.iceRestart).length, 3, "restart offers use iceRestart");
const before = banners.length;
pcSara.connectionState = "failed"; pcSara.onconnectionstatechange(); await tick();
assert.equal(offersTo("p2").length, 4, "gives up after 3 restarts");
assert.match(banners.slice(before).join(" "), /different networks.*TURN|relay/i, "tells the user what to do");

await recv({ type: "signal", from: "p1", data: { sdp: { type: "offer", sdp: "again" } } });   // ICE restart from the other side
assert.equal(pcs.length, 2, "an offer on a live link reuses the connection");

pcSara.connectionState = "connected"; pcSara.onconnectionstatechange(); await tick();
const badges = els.videoGrid.children.flatMap((tl) => tl.children).filter((c) => c.className === "tbadge");
assert.ok(badges.some((b) => /relayed · 42 ms/.test(b.textContent)), "shows relayed + round-trip time");
pcSara.connectionState = "closed";

// ---- live (interim) captions ----
await recv({ type: "interim", from: "p1", name: "Abel", text: "hel" });
const liveLines = () => els.capOverlay.children.filter((c) => /^…/.test(c.textContent));
assert.equal(liveLines().length, 1, "interim line shown");
assert.match(liveLines()[0].textContent, /^… Abel: hel/);
await recv({ type: "interim", from: "p1", name: "Abel", text: "hello th" });
assert.equal(liveLines().length, 1, "same speaker updates the same line");
assert.match(liveLines()[0].textContent, /hello th/);
await recv({ type: "interim", from: "p1", name: "Abel", text: "" });
assert.equal(liveLines().length, 0, "empty interim clears it");
await recv({ type: "interim", from: "p1", name: "Abel", text: "again" });
await recv({ type: "caption", from: "p1", name: "Abel", original: "Hello", translated: "ሰላም", source: "en", target: "am" });
assert.equal(liveLines().length, 0, "the final caption replaces the live line");
$("capOverlay").textContent = "";
await recv({ type: "caption", from: "p1", name: "Abel", original: "ሰላም", translated: "Hello", source: "am", target: "en", is_mock: false });
assert.match($("capOverlay").children[0].textContent, /^Abel: Hello/, "group captions are labelled with the speaker");

await recv({ type: "peer_left", id: "p1" });
assert.equal($("videoGrid").dataset.n, "1");
await recv({ type: "signal", from: "ghost", data: { candidate: { candidate: "c" } } });   // must not throw

$("cLeave").onclick();
assert.equal($("callStage").hidden, true);
assert.equal(pcs.filter((p) => p.closed).length >= 2, true, "all connections closed on leave");

// ---- "Check my connection" ----
const runCheck = async (cands) => { globalThis.__cands = cands; $("netResult").textContent = ""; await $("callNetCheck").onclick(); return $("netResult").textContent; };
assert.match(await runCheck(["candidate:1 1 udp 1 10.0.0.2 1 typ host", "candidate:2 1 udp 1 1.2.3.4 1 typ srflx", null]), /No relay server is set up/);
assert.match(await runCheck(["candidate:1 1 udp 1 10.0.0.2 1 typ host", "candidate:3 1 udp 1 5.6.7.8 1 typ relay", null]), /Relay server reachable/);
assert.match(await runCheck(["candidate:1 1 udp 1 10.0.0.2 1 typ host", null]), /Only local-network/);
assert.match(await runCheck([null]), /No network routes/);
assert.equal($("callNetCheck").disabled, false, "button usable again");
console.log("video-call smoke test: OK");
process.exit(0);   // the app code has 9-second caption timers; do not wait for them
