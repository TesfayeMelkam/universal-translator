# Connecting other systems

Base URL: `http://127.0.0.1:8000` (or your server). Interactive docs: `/docs`.
If `ACCESS_CODE` is set add `-H "X-Access-Code: YOUR_CODE"` to every call.

## Translate one text
```bash
curl -X POST http://127.0.0.1:8000/api/v1/translate -H "Content-Type: application/json" \
  -d '{"text":"Good morning","source":"en","target":"am","save_history":false}'
# -> {"translation": "...", "provider": "google" | "mymemory" | "phrasebook" | ..., "is_mock": false, "detected": {...}}
```
`source` may be `"auto"` (a guess; pick the language yourself when it matters).

## Batch (up to 50 texts, one bad item does not fail the others)
```bash
curl -X POST http://127.0.0.1:8000/api/v1/translate/batch -H "Content-Type: application/json" \
  -d '{"texts":["Hello","Thank you"],"source":"en","target":"om"}'
# -> {"results":[{"ok":true,"translation":"..."},{"ok":false,"error":{"code":"...","message":"..."}}]}
```

## LibreTranslate-compatible
Tools that support LibreTranslate can use this server as is: URL = `http://HOST:8000`, endpoints `POST /translate`
(`{"q","source","target"}` -> `{"translatedText"}`) and `GET /languages` (only languages that currently have an engine or data).

## Python
```python
import requests
r = requests.post("http://127.0.0.1:8000/api/v1/translate",
                  json={"text": "Hello", "source": "en", "target": "ti", "save_history": False},
                  headers={"X-Access-Code": "..."}, timeout=30)
r.raise_for_status(); print(r.json()["translation"])
```

## JavaScript
```js
const r = await fetch("/api/v1/translate", {method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({text: "Hello", source: "en", target: "so", save_history: false})});
console.log((await r.json()).translation);
```

## Feeding data in
| Call | What |
|---|---|
| `POST /api/v1/glossary` `{"source":"en","target":"wal","source_text":"Hello","translation":"..."}` | add / correct one phrase |
| `POST /api/v1/glossary/import?name=file.csv` (body = CSV or JSON file) | bulk import (replaces the earlier import with the same name) |
| `GET /api/v1/glossary/export` | download everything as CSV |
| `POST /api/v1/data/sync` | re-read `data/glossary/` and every `DATA_SOURCE_URLS` link |
| `GET /api/v1/data/status` | counts, sources, last sync result |

## Errors
JSON `{"error": {"code", "message"}}`. Useful codes: `translation_unavailable` (503: no engine reachable, retry later),
`unsupported_pair` (422: no engine/data for that language, add phrases), `rate_limited` (429), `bad_glossary_entry` (422).

## Operating notes
* Online engines receive the text. For sensitive text use the phrasebook, a self-hosted LibreTranslate or the offline `nllb` model.
* Put the app behind HTTPS (nginx/Caddy) and set `TRUST_PROXY=1`, `ACCESS_CODE` or accounts before exposing it to the internet.
* Cloud data links are configured only by the server owner (`.env`); web users cannot make the server fetch addresses.
