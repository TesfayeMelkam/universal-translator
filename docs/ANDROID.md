# Using this on an Android phone

**Easiest: install it as an app (a "PWA"). Nothing to build.**
1. Open the site in Chrome on the phone (it must be `https://` or `http://localhost`; see README → Calls across networks).
2. Menu ⋮ → **Install app** (or press the ⬇️ button in the app header).
3. It now has its own icon, opens full-screen, and appears in Android's **Share** menu: share text from any app to
   "Translator" and it opens ready to translate. Long-press the icon for shortcuts (Voice, Camera, Video call, Documents).

What works on a phone: everything that works in the browser (text, voice, camera, documents, calls, history), with the
interface in Amharic if you choose it. The app shell opens offline, but translation needs the internet.
Tip: switch on **🐢 low-data mode** on mobile data.

**A native Play Store app is NOT built.** If you want one later, the usual route is a "Trusted Web Activity" generated
by Google's Bubblewrap tool from your HTTPS site (`npm i -g @bubblewrap/cli`, `bubblewrap init --manifest https://YOUR/static/manifest.json`).
That needs your own domain with HTTPS and a Google Play developer account. Not tested here.
