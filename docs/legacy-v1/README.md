# Sawt — Arabic restaurant voice agent

**V2 is the current voice-first application.** It uses LiveKit + GPT-Live for continuous conversation, bounded GPT-Transcribe audio verification before business/call-control actions, a validated GPT-4.1 planner, SQLite transactions, and streamed exact checkout speech. Run `python -m pip install -r requirements-v2.txt`, configure the OpenAI and LiveKit values in `.env`, then run `python -m uvicorn app_v2:app --host 127.0.0.1 --port 8766` and `python voice_worker.py start` in separate terminals. Open http://127.0.0.1:8766 in Chrome or Edge. The in-app browser's WebRTC implementation is not supported for live calls.

Run `python scripts/v2_quality_check.py` (Python 3.12 and Node 22+) for offline tests and a local call audit; add `--live` for paid provider regression tests. See [V2 improvement notes](V2-IMPROVEMENTS.txt) for the tested changes, browser evidence, and remaining limitations. Calls and diagnostic recordings can be reviewed on the host at `/recordings`. Orders and human handoffs remain simulated.

The setup and push-to-talk documentation below describe the preserved **V1 baseline** (`app:app`, port 8765).

Current call wording and request coverage: [CALL-EXPERIENCE.txt](CALL-EXPERIENCE.txt). Edit reusable spoken templates in `data/conversation-copy.json`; regenerate the review with `python scripts/export_conversation_playbook.py`. The introduction invites any customer need, draft cancellation keeps the call open, staff offers have explicit yes/no state, and spoken hang-up plays a bounded state-aware goodbye. No separate intent classifier is required. [RECOGNITION-REPORT.txt](RECOGNITION-REPORT.txt) records the real-call diagnosis and its limits.

Paid checks without a browser: `python scripts/v2_interaction_eval.py` tests planner interactions; `python scripts/v2_recognition_replay.py --edges` tests real LiveKit media using synthetic caller speech; `python scripts/v2_recognition_replay.py --only farewell --output evidence/v2/recognition-farewell.json` checks closing audio and disconnect. The media tests need the API and worker running locally. Recorded human audio is optional and must only be replayed with the caller's authorization.

A local Arabic voice ordering demo with a deterministic basket engine, the supplied 144-item menu, four branches, and a visible tool/state trace. The application records or accepts Arabic audio, transcribes it, uses validated tools to build an order, and generates playable Arabic speech.

## Setup (Python 3.12)

Windows PowerShell:

```powershell
git clone https://github.com/clechz/sawt_demo.git
cd sawt_demo
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env: set OPENAI_API_KEY to your funded API key.
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8765
```

macOS/Linux:

```bash
git clone https://github.com/clechz/sawt_demo.git
cd sawt_demo
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env to set OPENAI_API_KEY.
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8765
```

Open http://127.0.0.1:8765 in Chrome or Edge. Allow microphone access, press **تحدث بالعربي**, speak, then press the same button to finish and send. An audio-file upload and text diagnostic path are also available. API keys stay on the server and are excluded from Git. One OpenAI API key is needed; no Twilio, paid database, or GPU is required. `.env` changes are reloaded on the next provider call.

Default models: `gpt-4o-transcribe` → `gpt-4.1` with tools → `gpt-4o-mini-tts` (coral). These are configurable in `.env`. They are separate from the open-weight research recommendations in [EVALUATION.md](EVALUATION.md). See the official [STT](https://developers.openai.com/api/docs/guides/speech-to-text), [TTS](https://developers.openai.com/api/docs/guides/text-to-speech), and [LLM](https://developers.openai.com/api/docs/models/gpt-4.1) documentation. Account access and credit must be checked with live tests.

## Demonstration

Say: «أبي توصيل للرياض حي النرجس شارع التجربة مبنى ١٢. أبي شكشوكة كبير مع تميس بدون إضافات، عدد ٢.»

Then switch to pickup, change quantity, request the final summary, wait for the complete audio readback, and say «اعتمد الطلب». The summary includes all options/notes, branch, fee, total and ETA. A mock `S-######` order is created only after explicit acceptance of the unchanged readback. Use «أبي موظف عندي شكوى» at any point for a mock handoff ticket.

**مقاطعة / إيقاف** stops output, cancels speculative work, and invalidates a checkout readback. Starting a recording while the assistant speaks also interrupts. This is explicit push-to-talk barge-in, not continuous full-duplex voice activity detection. Audio failure leaves the response text available. The text-test acknowledgement button is labelled as such and is not proof of the voice path.

## Mock restaurant assumptions

Menu: the supplied, unmodified `data/restaurant-menu-complex.csv` (144 items / 12 categories / 1,728 option rows / 20 columns). Price = base price + selected option deltas, multiplied by quantity; never sum repeated CSV base prices. Integer halalas avoid floating-point errors. Fixture prices are treated as final customer prices; no additional tax is invented.

Mock zones/fees/ETA: Riyadh Olaya/Sulaymaniyah → Olaya (12 SAR / 35 min); Narjis/Yasmin → Narjis (15 / 40); Malqa/Hittin → Malqa (10 / 30); Jeddah Rawdah/Salamah → Rawdah (14 / 40). Pickup fee is zero; pickup ETA 20 min. Zone boundaries are a fixed lookup, not geocoding. Addresses are free text after city/neighborhood validation. No real payment, dispatch, stock reservation or human telephony connection occurs. Human requests create a local ticket.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=test-results.xml
# Paid real-provider conversational regression tests:
.\.venv\Scripts\python.exe scripts/live_eval.py
# Paid audio smoke journey: synthetic Arabic customer → STT → agent → TTS
.\.venv\Scripts\python.exe scripts/live_eval.py --audio --case delivery_complete
```

Replace the executable with `.venv/bin/python` on macOS/Linux. Automated tests use controlled provider outputs. Live reports are written to ignored `runtime/live-text-report.json` and `runtime/live-audio-report.json`; audio-mode MP3 files are also saved there. Synthetic audio is a plumbing check, not a Saudi-speaker quality study. [TESTING.md](TESTING.md) maps the requirements to checks and records remaining manual gates.

## Files to review

- [DESIGN.md](DESIGN.md): architecture, state, reliability, context and production gaps.
- [EVALUATION.md](EVALUATION.md): open Arabic model choices, evidence and evaluation design.
- [PRODUCT.md](PRODUCT.md): safe-change workflow and wireframe.
- [DEMO.md](DEMO.md): timed recording script and submission checklist.
- `sawt/domain.py`: business rules; `sawt/agent.py`: bounded tool loop; `sawt/store.py`: durable order/request deduplication.

Local storage is `runtime/orders.sqlite3`; exported traces include the customer-supplied address and conversation. Use fictional data for the demo. Run one server worker: per-session concurrency and cancellation use in-process locks/epochs. This unauthenticated demo is intended for localhost, not public hosting.
