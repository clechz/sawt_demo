# Voice regression and release gate

Run from the repository root with `requirements-cloud.txt` installed. These commands use paid provider APIs and the password-protected cloud demo; no Chrome is used.

The full sequential cloud command is `python scripts/v2_cloud_suite.py --release conversation-v31`.
It checks planner access, then runs received-speech review, six order/information
journeys, three interruption offsets, checkout and private-storage checks.
It stops at the first failure and preserves logs in a timestamped ignored
`runtime/cloud-suite/` directory. Restore API credit first if preflight reports
`credit_balance_exhausted`; it does not retry billing failures. The expected
release is checked so results from an old worker cannot certify a new deploy.
Use `--continue-on-failure` for a complete inventory of independent failures;
the overall status remains failed. Storage verification is skipped if checkout
failed, so an older successful order cannot be reused as current evidence.

```sh
python -m pytest -q
node --test tests/audio-meter.test.mjs tests/call-start.test.mjs tests/call-status.test.mjs tests/playback.test.mjs
python scripts/v2_cloud_journeys.py
python scripts/v2_cloud_journeys.py --only pizza_options --repeat 3
python scripts/v2_cloud_journeys.py --only pizza_options information_and_staff --wait-for-capacity-seconds 900
python scripts/v2_cloud_acceptance.py
python scripts/verify_cloud_persistence.py
python scripts/v2_cloud_interruptions.py
python scripts/v2_conversation_review.py
```

Set `SAWT_DEMO_PASSWORD` in the process environment, or use the ignored local `runtime/private-demo.json`. Cloud journeys save timestamped JSON under `runtime/`. Never commit those raw files: they contain call identifiers, state and transient quote tokens. Caller fixtures are synthetic and cached by a hash of their wording. Historical human recordings are not uploaded by this runner.

The next test target is `conversation-v31`, after funding and deployment. The hosted worker remains V30. `submission-final.json` records
its actual completion status, deployed source commits and previous failures.
V24 passed state/media checks but one audio-check reply took 9.69 seconds.
V25 removed redundant transcription for that bounded nontransactional phrase;
three repeated audio checks took 1.51–1.66 seconds, but one goodbye stalled.
V26 added five independently transcribed fixed control/goodbye PCM assets. Its
repeated run exposed a split pause: “لو سمحت” arrived after “انتظر شوي” and
incorrectly resumed conversation. V27 holds those exact polite suffixes silent
only while already waiting. Mixed/new requests still resume normal processing.
V27 passed all 28 journey turns, three interruption timings, checkout and
private storage, but a readback provider stream failed in the separate speech
review. V28 bounds speech idle time and gives incomplete playback a retry
message, without allowing a partial or stale readback to confirm an order.
V28 still failed upstream streaming; the same stall reproduced outside Vercel.
V29 buffers initial PCM and retries once only before any audio has escaped,
uses compact speech instructions, preserves explicit single-drink modifiers
and records reversed-wording staff offers. Its planner replay exposed ambiguous
medium sugar; V30 stores one scoped proposal instead of repeating all choices.
The direct speech comparison uses one fixture and is reported separately from
the full hosted call suite; it does not certify native accent or broad latency.


Each full run checks the exact deployed worker. During a rolling deployment,
old workers can still answer; a release mismatch fails the test and stops the
suite even with `--continue-on-failure`. Billing failure also stops the suite.
Other failed checks remain failures while independent stages can continue.
An unchanged old checkout file is never copied as evidence for a new run.

To repeat the controls and staff cases against the actual current worker:

```powershell
$env:SAWT_EXPECT_WORKER_RELEASE = 'conversation-v31'
python scripts/v2_cloud_journeys.py --only controls_and_noise information_and_staff --repeat 3
```

On Bash, prefix the Python command with `SAWT_EXPECT_WORKER_RELEASE=conversation-v31`.
Consult `submission-final.json` for the current run's actual result and timing;
earlier passing results never substitute for a failing current release.

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

Cancellation and the unsupported-bread correction each allow one explicit
repeat after recognition disagreement. The uncertain turn must leave the
basket, price, order and handoff unchanged. Reports include the repeat and its
total elapsed time. A completion after clarification is not a first-pass
recognition success; there is no automatic retry of a failed order assertion.

## Reproduced failures, 2026-10-12

The first expanded run passed only one of six complete journeys. It exposed failures that earlier smoke tests missed: natural pizza options looping, a cancellation misheard by secondary STT, a price spelling variant rejected, Adani silently substituted with red tea, an audio-check handler producing no audible response, and merged words losing the negation boundary. The baseline remains in the local run archive. Fixes and rerun results must be reported separately; unit-test counts are not a call-success percentage.

The controlled barge-in sweep below adds measured interruption offsets. Packet loss/reconnect and a held-out human Saudi accent set remain unmeasured. The scripted wait/resume case is not a comprehensive interruption benchmark.

`v2_conversation_review.py` reproduces an ambiguous shawarma request, its protein/modifier answer, pickup/repeated pickup, branch selection and quantity correction. It records received LiveKit audio and independently transcribes the assistant's actual response. Exact readbacks are downloaded, decoded and given timed simulated playback receipts. These are separate speech sources in the report. Assertions reject repeated service questions after pickup, missing audible responses and selected unwanted filler. This is not an accent rating or proof that every paraphrase is correct.

`v2_cloud_interruptions.py` covers explicit wait requests during measured assistant output at 0.2, 0.8 and 1.5 seconds, subsequent option selection, and terminal transport-disconnect cleanup. An explicit participant disconnect ends this demo's call; automatic recovery from packet loss is a separate, unmeasured LiveKit behavior. This script does not certify arbitrary mid-word corrections or network recovery.

## Why the extra call tests matter

A correct tool trace is insufficient. In V30, saved saj was followed by a
spoken brown-bread question. The received-speech test now requires the actual
delivery/pickup question at that point. The original runner passed but the
manual review of its transcription failed; the report records both.

The V31 candidate speaks the validated backend text directly, instead of asking
the live model to paraphrase a commentary injection. A task-local playback
permit lets explicit PCM through while model-generated business audio stays
muted. New input revokes the permit; an older playback cannot clear a newer
permit. Tests exercise the installed SDK's resampling path, stale epochs,
parallel model audio, interrupted output and missing speech. Hosted audio and
latency are still pending because provider credit exhausted again.

Earlier versions used an acknowledgment and a 1.5-second missing-reply fallback.
V31 removes both waits and the obsolete fallback path. It still pays recognition,
planning and initial TTS latency. This is a design change to test, not a claim
that the hosted delay is already solved. The independent received-speech and
interruption suites must pass before the candidate is ready for a demo.
