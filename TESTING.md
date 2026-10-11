# Requirement coverage and honest execution record

Local execution: **211 automated tests passed** on Python 3.12.14. `test-results.xml` is the machine-readable output. Includes 144 parametrized menu-item tests that iterate all selectable option rows and validate independent price expectations. Tests using a scripted provider establish application behavior, not real-model Arabic understanding. Concurrent confirmations, in-flight interruption, malformed provider envelopes and stale readback acknowledgement are covered.

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
| Corrections/short answers | LLM interprets, tool engine validates | Live scenarios, manual Arabic check still required |
| Arabic/Western digits/spelling | Normalizer plus model extraction | Normalizer tests; live quantity scenario |
| Code switching | Bilingual retrieval plus model extraction | `code_switch` live scenario, pending execution |
| Complaint/human anytime | Deterministic common phrases + handoff tool | Four journey-phase tests; real browser handoff verified |
| Full readback | Server-generated exact summary | Summary content test, live listening pending |
| Explicit consent | Current token/revision + completed playback + exact acceptance | Confirmation gates and false-consent tests |
| No duplicate order/tools | Turn replay, per-turn tool dedup, unique DB order/session | HTTP replay, tool replay, persisted single-order tests |
| Invalid output / timeout | Argument validation, bounded retries, speculative copy | Malformed JSON and rollback tests |
| Interruption | Stop audio, abort client, server epochs, invalidate quote | Stale-epoch/ack test; human audio interruption pending |
| Voice pipeline | Browser recorder/upload → STT → agent/tools → TTS/player | Mock API pipeline tested; real-provider audio test pending |
| Model research | Exact named models, licenses, source links, evaluation plans | `EVALUATION.md`; researched, not locally benchmarked |
| Safe-change product | Version/replay/review/canary/rollback design | `PRODUCT.md` wireframe and explicit gates |
| README reproducibility | Pinned packages, exact Windows/Unix commands | Fresh-install verification to be recorded |
| ≤10-minute video | Timed walkthrough script | Recording and link verification pending |

## Live automated scenarios

`python scripts/live_eval.py` covers delivery completion; pickup switch; location causing unavailability; quantity edit after total; mixed-language request; early items; human handoff; unsupported zone; required choices; removal after total; yes-with-correction; information-only call. It exits nonzero on any failed assertion. A missing key exits with BLOCKED, not PASS. Record counts from the generated report only after execution.

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

Known prototype limits: push-to-talk rather than continuous VAD, mock handoff/dispatch, fixed delivery zones, one server worker, narrow confirmation phrase list, no measured native-speaker WER/MOS. These must remain visible in the submission. Never present the 211 application checks as 211 live Arabic conversations.
