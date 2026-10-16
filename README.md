# Universal Translator

Text, voice, photos, documents, subtitles and group video calls with live translated captions, in **150+ languages**
(including Amharic, Afaan Oromo, Tigrinya, Somali), with an Amharic interface. One Python app: API + website + installable
phone app. **Read `docs/limitations.md` first: it says exactly what is verified and what is not.**
**v0.6: translation now works out of the box** through online engines (free MyMemory with no key; Google / Azure / LibreTranslate with a key),
with automatic fall-back, your own phrasebook (files or cloud sheets), and 10 more Ethiopian languages (phrasebook-only, see below).
**If it still shows only greetings:** your old `.env` says `TRANSLATION_PROVIDER=mock`. `run.py` offers to fix it, or change it to `auto`.

## Quickest start (PyCharm, no terminal)
1. Unzip, then **File → Open** → choose the `universal_translator` folder (trust the project).
2. **File → Settings → Project → Python Interpreter → Add Interpreter → Virtualenv** (OK).
3. Open `run.py` and click the green **▶**. If packages are missing it asks to install them: type `y` in the Run window.
4. Your browser opens http://127.0.0.1:8000 (use **Chrome or Edge**). Red ■ stops it.

PowerShell alternative: `.\scripts\setup_windows.ps1` then `.\scripts\run_dev.ps1`.

## What is in it
| Tab | What it does |
|---|---|
| ✍️ Text | Translate; detects the language of what you type; dictate by voice; listen; copy/share |
| 🎙️ Voice / 💬 Talk | Speak → translated → read aloud; two people on one device |
| 📷 Camera | Photo or camera → reads text (OCR) → translation drawn over the photo |
| 📹 Video call | Group call (up to 4 by default), each person reads captions in their language, live words while speaking |
| 📄 Documents | .txt .md .srt .vtt .docx (layout kept), .pdf (→ text) |
| 🎞️ Subtitles | Audio/video → .srt (needs speech model + FFmpeg) |
| 🕘 History | Per person when accounts are on |
| 🛠️ Setup | Engines, your phrasebook / cloud data, how to connect other systems, quality check |

Interface languages: English, **Amharic (complete)**, Afaan Oromo and Tigrinya (drafts, few strings; need native review).
🐢 = low-data mode. ⬇️ installs it as an app. Android: see `docs/ANDROID.md`.

## Real translation (v0.6)
Set in `.env` (see `.env.example`, restart `run.py` after changes). Default `TRANSLATION_PROVIDER=auto`:

| Engine | Needs | Notes |
|---|---|---|
| `google` | `GOOGLE_TRANSLATE_API_KEY` | Best coverage of Amharic, Afaan Oromo, Tigrinya, Somali (free quota, then paid) |
| `azure` | `AZURE_TRANSLATOR_KEY`, `AZURE_TRANSLATOR_REGION` | Microsoft Translator (free tier) |
| `libretranslate` | `LIBRETRANSLATE_URL` (+ key) | Open source; self-host for privacy |
| `mymemory` | nothing | Free, small daily quota, uneven quality for low-resource languages |
| `nllb` | model download | Offline; `pip install transformers torch sentencepiece`, `scripts/download_models.py` (~3 GB, non-commercial licence) |

`auto` = every engine that has a key, then MyMemory. You can force an order, e.g. `TRANSLATION_PROVIDER=google,mymemory,nllb`.
If an engine is unreachable, out of quota or refused, the next one is tried automatically; a dead engine is paused for a while.
The **Setup** tab shows each engine, whether it is paused and *who receives your text*.
**Privacy:** online engines receive what you translate. Use the phrasebook or `nllb` for private text.
Measure quality with `scripts/check_translation.py --langs am om ti so` or Setup → "Run quality check" (round-trip consistency only;
a fluent speaker must review anything important).

## Your own data: phrasebook, files, cloud
* Checked **before** any engine, works offline, and fixes engine mistakes (an entry always wins).
* Add phrases in **Setup → Your data**, import a CSV/JSON file there, or drop files into `data/glossary/` (see `data/glossary/README.txt`).
* **Cloud:** `DATA_SOURCE_URLS=https://docs.google.com/spreadsheets/d/e/.../pub?output=csv` (Google Sheets "Publish to web → CSV"; GitHub raw,
  S3, Azure Blob links also work). Press **Sync cloud data now**, or set `DATA_SYNC_MINUTES=30`. Removing a row in the sheet removes it here on the next sync.
* A sheet can have one column per language (`en,am,om,wal,...`); phrases also work between two non-English languages through the English column.

## Ethiopian languages
Machine translation (via the engines above): Amharic, Afaan Oromo, Tigrinya, Somali (engine coverage varies; Setup shows what each engine reports).
**Phrasebook only** (no engine supports them; the app says so next to the language): Afar, Wolaytta, Sidama, Kambaata, Hadiyya, Gamo,
Gurage (Sebat Bet), Harari, Anuak, Ge'ez. For these, translation works **only for phrases you provide**. The app does not guess.

## Other systems and other networks
* REST API with docs at `/docs`: `POST /api/v1/translate`, `POST /api/v1/translate/batch` (50 texts), glossary + data endpoints.
  A **LibreTranslate-compatible** `POST /translate` and `GET /languages` let tools that already speak that API point at this server.
  Examples: `docs/INTEGRATION.md`. With `ACCESS_CODE` set, send header `X-Access-Code`.
* Other devices: `LAN_MODE=1` (or `APP_HOST=0.0.0.0`, `APP_PORT=...`). Behind nginx/Caddy/a tunnel set `TRUST_PROXY=1`.
* Slow or unstable network: online engines have timeouts, retries and fall-back; the browser retries when the connection returns; 🐢 low-data mode.

## Voice
Default: your browser's speech recognition and voices (Chrome/Edge). Many languages have none (Afaan Oromo and Tigrinya often don't); the app says so.
Better coverage (unverified, large): `STT_PROVIDER=mms` and `TTS_PROVIDER=mms`, models via `scripts/download_models.py --model mms-asr --tts amh orm tir`, and FFmpeg installed. Windows system voices: `TTS_PROVIDER=pyttsx3`.

## Camera / OCR
`pip install pytesseract pillow` + install the **Tesseract** program (https://github.com/UB-Mannheim/tesseract/wiki) ticking the languages you need (Amharic = `amh`). Without it the camera tab uses a mock that does not read pictures (the app tells you).

## Documents and subtitles
Documents need nothing extra (`pip install pypdf` for PDF). Subtitles from audio/video need **FFmpeg** on PATH and `STT_PROVIDER=mms`. Timing is approximate (15-second blocks).

## Video calls
Quick try on one PC: start a call, copy the invite link, open it in a second browser window, **Join**. For 3+ people use separate devices.
* Same Wi-Fi from a phone: browsers block cameras on plain `http`, so use HTTPS: `pip install cryptography`, `python scripts/make_dev_cert.py`, `LAN_MODE=1` in `.env`.
* Across the internet: `scripts\share_online.ps1` (free tunnel; set `ACCESS_CODE` first) or the `deploy/` server pack with a TURN relay (`deploy/README.md`). Press **🌐 Check my connection** to see what will work.
* More than 4–6 people: LiveKit (`deploy/docker-compose.livekit.yml`), unverified.
* Mesh calls send one video per person to everyone else, so keep groups small.

## Accounts, access code, Telegram
* `ACCESS_CODE=...` : one shared secret for host features (guests joining a call don't need it).
* `AUTH_MODE=optional|required` : sign-up/login (scrypt passwords, HttpOnly cookie sessions, private history). No e-mail, so no password reset.
* Telegram bot: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, then `python scripts/telegram_set_webhook.py https://your-address`. Private chats only for plain text; `/lang am`, `/from auto`.
* Other apps: call the REST API (`/docs` lists it) with header `X-Access-Code`.

## Tests
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests          # 158 tests run in the build sandbox (13 more in tests/test_api.py need real FastAPI)
.\.venv\Scripts\python.exe -m playwright install chromium         # once, for the real-browser tests
node tests/js/smoke_call.mjs                                      # simulated call (needs Node 18+)
```
The real-browser tests use a stand-in server (`tests/e2e/harness.py`) so they also run without FastAPI; when FastAPI is installed
`tests/test_api.py` tests the real server, and without it `tests/test_glue.py` runs the real route functions through a small stand-in.

## Layout
```
shared/languages.py      153 languages (single catalog)         frontend/            page, scripts, translations (static/i18n)
ai_services/main.py      FastAPI app (thin)                     ai_services/rooms.py call rooms, captions, signalling
ai_services/services/    pipeline, documents, subtitles, quality ai_services/auth.py  accounts       turn.py  relay logins
ai_services/providers/   mock + NLLB, Tesseract, MMS speech      integrations/        Telegram        jobs.py  background jobs
deploy/                  Docker, HTTPS, TURN relay, LiveKit      scripts/             setup, models, checks, tunnel, cert
tests/                   unit, glue, real-browser (e2e), js
```
