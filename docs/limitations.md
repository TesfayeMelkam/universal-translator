# What is verified, what is not (v0.5)

"Verified" below means checked in the build sandbox, which had **no internet, no AI models, no Windows, no phone and no
real second network**. Nothing here guarantees perfect translation: machine translation is imperfect, especially for
low-resource languages. Have a fluent speaker review anything important.

## Your 11 recommendations

| # | Item | Status | How it was checked |
|---|---|---|---|
| 1 | Real translation + quality check | **Tooling done; the model itself is NOT installed here.** `Setup` tab, `/api/v1/translation/status`, `scripts/check_translation.py` (round-trip score; flags engines that just echo English), and a guard that refuses model language codes the tokenizer does not know. Default is still a **mock** (a few greetings). | Unit tests with mock/echo/failing engines. NLLB itself: unverified. |
| 2 | Real test | **Done for the web page.** 17 tests drive a real Chromium with fake camera/microphone, including 2- and 3-person WebRTC calls, captions, documents, OCR, offline badge, mobile layout. Not tested: real phones, real networks, real speech engines. | `python -m unittest tests.e2e.test_browser` |
| 3 | Amharic interface | **Done** (every string). Afaan Oromo and Tigrinya are **drafts with only ~19 common strings**, not reviewed by native speakers (marked "draft"; the rest falls back to English). Some dynamic status messages are still English. | Key-parity tests; real-browser test switches language; screenshot checked |
| 4 | Live captions while speaking | **Done.** Words appear (in the speaker's own language, greyed) while someone talks; the translated caption replaces them at the end of the sentence. Translating partial sentences is deliberately not done (slow, inaccurate). | Unit, simulated-browser and real-browser tests (with a fake speech engine; real speech engines not tested) |
| 5 | Better speech for Amharic/Oromo/Tigrinya | **Code written, NOT verified.** Server speech recognition (Meta MMS) and server voices (MMS-TTS), a "record on server" button, FFmpeg audio decoding (**this part is tested with real FFmpeg**). No models were available. Quality for these languages is unknown until you try it. | FFmpeg decoding: real; models: unverified |
| 6 | Accounts / login | **Built in (not Django):** username + password (scrypt), cookie sessions, per-user history, lockout, CSRF origin check. No e-mail, so **no password reset**; no admin screen. | Unit tests + real route functions via a FastAPI stand-in |
| 7 | Translation drawn over the photo | **Done.** | Real Chromium + real Tesseract (English): original covered, translation drawn |
| 8 | Bigger group calls | **Partly.** Mesh calls up to 4 (configurable to 6). Larger calls via LiveKit are **written but unverified** (server tokens are tested; the LiveKit browser SDK code and the Docker files never ran). Needs a rented server + a second domain. | Token/JWT and room logic tested; the rest unverified |
| 9 | Subtitles | **Done for .srt/.vtt translation** (timings preserved). Audio/video -> subtitles: pipeline **tested with real FFmpeg and a fake recogniser** (15-second blocks, approximate timing, silence skipped); with a real recogniser it is unverified and slow on CPU. | Unit + end-to-end job tests |
| 10 | Documents + Android | **Documents done:** .txt .md .srt .vtt .docx (formatting kept; python-docx opens the result) and .pdf (text only, saved as .txt). **Android:** installable app (PWA) with Share-to-app and shortcuts; **no native Play Store app** (see docs/ANDROID.md). | Real-browser upload/download tests; docx built and re-read |
| 11 | Integrations | **Telegram bot written** and tested with a fake Telegram; never run against real Telegram. Other apps can call the REST API with the access code. **Not built:** SMS, WhatsApp, e-mail, Slack. | Unit tests + webhook route tests |

## Other things you asked for

* **150+ languages:** 153 in the catalog, including Amharic, Afaan Oromo, Tigrinya, Somali and Nuer. Wolaytta, Sidama, Gurage, Afar and Kambaata are **not** included: the translation model does not cover them, and I will not pretend it does.
* **Works on Wi-Fi and mobile data:** 🐢 low-data mode (smaller photos, 360p video, audio-only calls), request retries/timeouts, offline badge, installable shell. Offline translation is **not** possible (needs the server/model). Calls across different networks need a TURN relay (see deploy/README.md); not tested on real networks.
* **Modern, smarter front end:** 10 tabs, interface languages, recent languages, language hint while typing, drag-and-drop files, dark mode, phone bottom tab bar, keyboard focus outlines, reduced-motion support. Screenshot-reviewed.
* **Honest unknowns:** browser speech recognition quality for Amharic/Oromo/Tigrinya depends on your browser and often does not exist (the app says so); NLLB quality for each language varies.

## Known limits
* Calls: no recording, no screen sharing, mesh uses lots of upload bandwidth, anyone with a room code can join that room.
* Accounts have no e-mail verification or reset. The access code is one shared secret.
* History is stored in a SQLite file on the host.
* PDF output is plain text; scanned PDFs need the Camera/OCR tab.

## v0.6 additions: what is and is not verified
* **Verified by automated tests (with a simulated network):** request/response handling for Google, Azure, LibreTranslate and MyMemory,
  fall-back between engines, pausing a failing engine, text splitting, phrasebook import/sync, the new API routes, the redesigned UI in a real browser.
* **NOT verified here:** calls to the real Google/Azure/MyMemory/LibreTranslate services (the build environment had no internet, no keys). The
  request formats follow each service's public documentation; if one engine fails, Setup shows its last error and the next engine is used.
* **Translation quality is not measured or guaranteed.** MyMemory in particular is uneven for Amharic/Oromo/Tigrinya. Prefer Google or Azure for those, and have a fluent speaker review important text.
* **Language coverage is asked from each engine** where it offers a list; MyMemory has none, so for it 2-letter languages are assumed (an unchanged echo is treated as a failure).
* **Afar, Wolaytta, Sidama, Kambaata, Hadiyya, Gamo, Gurage, Harari, Anuak, Ge'ez are phrasebook-only.** No data is bundled for them: the app cannot translate them until you add phrases.
* **Auto-detect** now separates several Latin-script languages and Amharic/Tigrinya using common-word lists. It can be wrong on short or mixed text.
* The Amharic text of the new interface labels was written without a native-speaker review.
