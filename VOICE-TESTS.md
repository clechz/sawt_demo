# Voice regression and release gate

Run from the repository root with `requirements-cloud.txt` installed. These commands use paid provider APIs and the password-protected cloud demo; no Chrome is used.

```sh
python -m pytest -q
node --test tests/audio-meter.test.mjs tests/call-start.test.mjs tests/call-status.test.mjs tests/playback.test.mjs
python scripts/v2_cloud_journeys.py
python scripts/v2_cloud_journeys.py --only pizza_options --repeat 3
python scripts/v2_cloud_journeys.py --only pizza_options information_and_staff --wait-for-capacity-seconds 900
python scripts/v2_cloud_acceptance.py
python scripts/verify_cloud_persistence.py
python scripts/v2_cloud_interruptions.py
```

Set `SAWT_DEMO_PASSWORD` in the process environment, or use the ignored local `runtime/private-demo.json`. Cloud journeys save timestamped JSON under `runtime/`. Never commit those raw files: they contain call identifiers, state and transient quote tokens. Caller fixtures are synthetic and cached by a hash of their wording. Historical human recordings are not uploaded by this runner.

## What a full-call test checks

The runner logs in, creates an isolated call, connects a real LiveKit microphone track, streams spoken audio with continuous silence between turns, observes received assistant PCM, checks persisted basket state, and ends the call. Each failed attempt remains a failed case; repeating a test does not erase it. Exact order assertions use code, not an LLM judge. A requested recognition clarification may have one explicitly scripted repeat, with an assertion that the uncertain turn changed no basket, total, order or handoff.

| Challenge behavior | Automated coverage |
|---|---|
| Natural Saudi options and short answers | Pizza size/crust sequence and repeated saved choice |
| Quantities, modifiers, corrections, code switching | Three-to-two quantity correction; English karak request; negated item |
| Information and complaints | Price-only basket unchanged, unknown allergen information, staff-offer decline and direct complaint |
| Delivery, branch and unavailable request | Unavailable Adani tea cannot become another item; unsupported zone; pickup change |
| Silence and call controls | Continuous audio, wait/noise/resume, negated hangup, explicit audible goodbye |
| Unsafe substitution and confirmation | Unsupported brown bread cannot become brioche; price manipulation cannot confirm |
| Readback and durable confirmation | `v2_cloud_acceptance.py`: actual speech download/decode, edit after the first readback, stale receipt rejected, fresh readback, explicit confirmation, no duplicate order |
| Cross-process storage | Independent Postgres and private Blob inspection after the call |
| Browser audio state | JavaScript tests: autoplay rejection does not abort microphone; caller/AI samples move orb; stale playback cannot confirm |
| Other state invariants | Python suite: branch availability/fees, edit/remove after quote, concurrent confirmation, stale operations, required options, all 144 items |

## Honest limits

The state-completion hard ceiling defaults to eight seconds; that is a stall detector, not a claim that eight seconds feels conversational. First received audio is measured separately. RMS proves audible energy, not correct spoken meaning. This runner does not certify native Saudi pronunciation, real microphone permissions, Bluetooth behavior, a real telephone network, or every possible wording. Human-call failures take precedence over a passing synthetic test.

A release needs all intended cases executed, zero incorrect or unconfirmed orders, no silent substitution, and no unresolved missing-reply failures. Do not describe a run as passing when cases were skipped, rate-limited or failed. The demo has a shared 120-start/hour and four-active-call budget; schedule test runs accordingly and leave room for human testing. The optional `--wait-for-capacity-seconds` flag retries only the existing call-budget response until its deadline; it never changes limits or exempts synthetic calls. Other errors remain failures. The checkout runner accepts the same flag.

## Reproduced failures, 2026-10-12

The first expanded run passed only one of six complete journeys. It exposed failures that earlier smoke tests missed: natural pizza options looping, a cancellation misheard by secondary STT, a price spelling variant rejected, Adani silently substituted with red tea, an audio-check handler producing no audible response, and merged words losing the negation boundary. The baseline remains in the local run archive. Fixes and rerun results must be reported separately; unit-test counts are not a call-success percentage.

A controlled barge-in sweep (speaking at several offsets during assistant audio), packet loss/reconnect, and a held-out human Saudi accent set are still required before any broad reliability claim. The scripted wait/resume case is not a comprehensive interruption benchmark.

`v2_cloud_interruptions.py` covers explicit wait requests during measured assistant output at 0.2, 0.8 and 1.5 seconds, subsequent option selection, and terminal transport-disconnect cleanup. An explicit participant disconnect ends this demo's call; automatic recovery from packet loss is a separate, unmeasured LiveKit behavior. This script does not certify arbitrary mid-word corrections or network recovery.

## Why the extra call tests matter

A tool trace can be correct while the caller hears nothing. Each real-media journey therefore checks order state separately from received assistant audio. The cloud worker now has a guarded missing-reply fallback: after 1.5 seconds without audible output sent to the LiveKit sink, synthesize the verified backend reply; recheck the call epoch, new input, waiting/checkout state and intervening audio before playback. This recovers missing speech, not slow planning. A fallback event is recorded for diagnosis.

Menu search also labels partial-only matches. The planner's draft-saving reminder no longer forces an extra add-item round for an unavailable request. Repeated complete option answers use the same narrow deterministic path even after the next question begins. Neither change supplies unstated choices or authorizes confirmation.

The generated-but-inaudible reply regression was traced to disabling the SDK output while a realtime speech task began. That task snapshots its audio destination, so re-enabling output later can leave the same task without a destination. `SpeechGate` keeps the destination attached and sends zeroed samples during validation/wait/readback instead. It preserves frame timing and flush/playout events, clears queued speech when muted, and reports audible samples only after forwarding to the sink. A unit test exercises mute/resume on the same destination; real cloud reception remains the acceptance check.
