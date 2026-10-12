# Requirement coverage and honest execution record

**Current submission:** V2 setup is in README.md; curated synthetic evidence is in [evidence/v2](evidence/v2/README.md). The latest audio-clock, background-diagnostic and microphone-meter changes are explained in DESIGN.md. A passing synthetic run does not override a human report of poor latency.

**Current V2 evidence:** see `RELEASE-TEST-REPORT.txt`, `RECOGNITION-REPORT.txt`, and `CALL-EXPERIENCE.txt`. Current tests add bounded audio verification, correction/negation checks, stateful staff offers, whole-draft cancellation and audible closing. Run `python scripts/v2_quality_check.py` for the offline suite. The counts, batch STT/TTS timings and push-to-talk limitations below are preserved **V1 historical results**, not current V2 results.

Local execution: **232 automated tests passed** on Python 3.12.14. `test-results.xml` is the machine-readable output. Includes 144 parametrized menu-item tests that iterate all selectable option rows and validate independent price expectations. Tests using a scripted provider establish application behavior, not real-model Arabic understanding. Concurrent confirmations, in-flight interruption, malformed provider envelopes, stale readback acknowledgement, neighborhood prefixes, incomplete address corrections, size aliases and negated handoff phrases are covered.

Hosted execution on 2026-10-11: **14/14 text scenarios passed** with GPT-4.1; **one three-turn synthetic Arabic audio journey passed** with GPT-4o Transcribe, GPT-4.1 and GPT-4o mini TTS. The saved reports in `evidence/` contain observed transcripts, states, tools and timings. These are a single final run of a development suite, not a held-out reliability estimate. Earlier runs exposed failures described below; the suite was used to improve the implementation.

Real browser verification: uploaded synthetic Arabic audio produced a priced delivery basket; a subsequent readback played to completion and set its token's `presented` flag; uploaded spoken «نعم» created mock order `S-967539`, and its reply played. This browser session spans development configurations and is separate from the final-configuration audio report. Screenshot: `demo-preview.png`. No human microphone or native-listener pronunciation assessment is claimed.

## Coverage map

| Requirement | Implementation | Evidence / gate |
|---|---|---|
| Supplied 100+ item menu | CSV parser, 144 items, all 1,728 option rows | `test_fixture`, all-item price/constraint checks |
| Menu outside main prompt | Search/get-item tools, at most 5 candidates | Context bounded test; browser menu search |
| Service/location/branch/fees | Fixed mock zones, deterministic lookup | Domain routing, branch override and unsupported-zone tests |
| Quantities/options/notes | Stable basket lines and required group validation | Invalid quantity, invalid modifier, required choice tests |
| Delivery → pickup | Address cleared, zero fee, quote invalidated | Dedicated transition test |
| Location after items | Revalidation, retained unavailable lines, ETA/fee update | Dedicated unavailable-branch test |
| Edit/remove after total | Revision increment, new readback required | Update/remove and confirmation tests |
| Information early | Draft basket before fulfillment | Early-item test and live scenario |
| Corrections/short answers | LLM interprets, tool engine validates | Live short-answer and correction scenarios passed; human Arabic check still required |
| Arabic/Western digits/spelling | Normalizer plus model extraction | Normalizer tests; live quantity scenario |
| Code switching | Bilingual retrieval plus model extraction | `code_switch` and `sauce_correction` real-model scenarios passed |
| Complaint/human anytime | Deterministic common phrases + handoff tool | Four journey-phase tests; real browser handoff verified |
| Full readback | Server-generated exact summary and confirmation-language guard | Summary tests; browser playback/ack verified; native listening pending |
| Explicit consent | Current token/revision + completed playback + exact acceptance | Confirmation gates and false-consent tests |
| No duplicate order/tools | Turn replay, per-turn tool dedup, unique DB order/session | HTTP replay, tool replay, persisted single-order tests |
| Invalid output / timeout | Argument validation, bounded retries, speculative copy | Malformed JSON and rollback tests |
| Interruption | Stop audio, abort client, server epochs, invalidate quote | Stale-epoch/ack test; human audio interruption pending |
| Voice pipeline | Browser recorder/upload → STT → agent/tools → TTS/player | Real-provider synthetic audio and browser upload/playback passed; human microphone pending |
| Model research | Exact named models, licenses, source links, evaluation plans | `EVALUATION.md`; researched, not locally benchmarked |
| Safe-change product | Version/replay/review/canary/rollback design | `PRODUCT.md` wireframe and explicit gates |
| README reproducibility | Pinned packages, exact Windows/Unix commands | Fresh GitHub clone + new Python 3.12 environment: install succeeded, all 211 tests passed on Windows; Unix commands not locally executed |
| ≤10-minute video | Timed walkthrough script | Recording and link verification pending |

## Live automated scenarios

`python scripts/live_eval.py` covers delivery completion; pickup switch; location causing unavailability; quantity edit after total; mixed-language request; early items; human handoff; unsupported zone; required choices; removal after total; yes-with-correction; information-only call; short answers; sauce removal with an English size correction. It exits nonzero on any failed assertion. A missing key exits with BLOCKED, not PASS.

`python scripts/live_eval.py --audio --case delivery_complete` exercises real hosted APIs with synthetic Arabic input and generated output files. It is a useful integration test, but cannot establish human accent/noise robustness. The script simulates full reply consumption; browser playback acknowledgement is a separate test.

## Manual release/demo gate

Record actual outcomes, not just checkmarks:

1. Use a microphone and complete one Arabic order through an audible final order ID.
2. Speak «أبي large meal بدون صوص» with a specific menu item; verify correct option mapping and sauce removal.
3. Use both «٢»/spoken اثنين and typed `2`; verify quantities match.
4. Correct the address after adding items; show changed branch/fee/ETA and any unavailable item.
5. Switch to pickup; show zero delivery fee and appropriate branch.
6. Remove/change an item after readback, then say yes before a new summary; verify no premature order.
7. Interrupt halfway through the summary; verify immediate stop and new readback requirement.
8. Ask for staff at checkout; verify handoff and no order creation.
9. Ask an ingredient/allergy question absent from the fixture; verify no invented guarantee.
10. Listen to menu names, prices, quantity, address and order ID. Record mispronunciations verbatim.
11. Retry a confirmed request; verify same order ID and one stored order.
12. Open the repository using reviewer access and open/play the video link in a separate browser session.

## Observed failures and remaining limits

Development failures included `حي النرجس` not matching `النرجس`, incomplete address corrections retaining an older location, invented `large_meal` option IDs, model-authored confirmation questions missing checkout tokens, intermittent missing draft writes with GPT-4.1 mini, and STT confusing `تميس` with `تمييز`. Fixes added canonical location/size handling, invalidation on partial corrections, menu definitions in tool-repair responses, a readback guard, GPT-4.1, and menu vocabulary hints with GPT-4o Transcribe. These changes improve the tested cases; they do not prove all paraphrases work.

Final synthetic voice run, three utterances (milliseconds; batch generation, not streaming):

| Turn | STT | Agent/tools | TTS generation | Sum before reply audio is ready |
|---|---:|---:|---:|---:|
| Full order | 1272 | 3109 | 4513 | 8894 |
| Request readback | 840 | 605 | 3585 | 5030 |
| Confirm | 499 | 1 | 2413 | 2913 |

This tiny sample cannot establish p95 or real-world voice quality. It excludes recording time, audio playback, and browser/network overhead. Customer-speech synthesis used to create the test input is excluded from these stage sums.

Known prototype limits: text-only initial greeting, push-to-talk rather than continuous VAD, batch audio generation, mock handoff/dispatch, fixed delivery zones, one server worker, narrow confirmation phrase list, no measured native-speaker WER/MOS, no held-out conversational evaluation. The UI creates a new request ID on every submission, so a manual retry after a lost response is not the same idempotent operation; end-to-end retry recovery needs improvement. These must remain visible in the submission. Never present 232 application checks as 232 live Arabic conversations.
