// LARGE calls (more people than a peer-to-peer mesh can handle) through a LiveKit media server (SFU).
// UNVERIFIED: written without the LiveKit SDK or a LiveKit server available. It only runs when the host
// configured LIVEKIT_* and the room was created as a "large call". Captions still use this app's own channel.
async function loadSdk(url) {
  if (window.LivekitClient) return window.LivekitClient;
  await new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = url; s.onload = resolve; s.onerror = () => reject(new Error("Could not load the large-call library."));
    document.head.append(s);
  });
  if (!window.LivekitClient) throw new Error("The large-call library did not start.");
  return window.LivekitClient;
}

export async function joinLarge({ $, tokenInfo, audioOnly, onCount }) {
  const LK = await loadSdk(tokenInfo.sdk);
  const room = new LK.Room({ adaptiveStream: true, dynacast: true });
  const tiles = new Map(), grid = $("videoGrid"), localTile = $("localTile");
  const tileFor = (p) => {
    let el = tiles.get(p.identity); if (el) return el;
    el = document.createElement("div"); el.className = "tile remote";
    const label = document.createElement("div"); label.className = "vlabel"; label.textContent = p.name || "Guest";
    el.append(label); grid.insertBefore(el, localTile); tiles.set(p.identity, el); onCount(tiles.size); return el;
  };
  room.on(LK.RoomEvent.TrackSubscribed, (track, _pub, p) => {
    const el = track.attach(); if (track.kind === "video") { el.autoplay = true; el.playsInline = true; }
    tileFor(p).prepend(el);
  });
  room.on(LK.RoomEvent.TrackUnsubscribed, (track) => track.detach().forEach((e) => e.remove()));
  room.on(LK.RoomEvent.ParticipantConnected, tileFor);
  room.on(LK.RoomEvent.ParticipantDisconnected, (p) => {
    const el = tiles.get(p.identity); if (el) { el.remove(); tiles.delete(p.identity); onCount(tiles.size); }
  });
  await room.connect(tokenInfo.url, tokenInfo.token);
  room.remoteParticipants.forEach(tileFor);
  await room.localParticipant.setMicrophoneEnabled(true);
  if (!audioOnly) {
    await room.localParticipant.setCameraEnabled(true);
    const pub = room.localParticipant.getTrackPublication(LK.Track.Source.Camera);
    if (pub && pub.track) pub.track.attach($("localVideo"));
  }
  return {
    setMic: (on) => room.localParticipant.setMicrophoneEnabled(on),
    setCam: (on) => room.localParticipant.setCameraEnabled(on),
    leave: () => { room.disconnect(); tiles.forEach((el) => el.remove()); tiles.clear(); },
  };
}
