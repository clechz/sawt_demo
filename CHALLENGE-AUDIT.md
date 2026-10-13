# SAWT challenge audit — 13 October 2026

See [the seven submission gates](SUBMISSION-READINESS.md). The merged candidate
passed 938 Python tests (one optional skip), 63 Node tests and the frontend build.
A fresh README dependency install and uvicorn/page smoke also passed.

## Human-call follow-up

The kabsa/laban call reached a prepared 117 SAR checkout but never confirmed.
Normal lifetime shutdown did not mark `ending` before closing the provider
session, allowing its own `session.closed` event to enter the fatal-error path.
The lifecycle now marks intentional shutdown first; the regression simulates the
provider close callback and verifies no fatal error is dispatched. This is a
confirmed code defect, not proof of the exact unrecorded browser error wording.
Thirty-three routing/provider tests passed. Exact speech instructions now request
connected, understated Saudi delivery while preserving all supplied facts. A
Cedar sample generated successfully; naturalness and full-call behavior remain
unverified. Historical failures and the hosted deployment blocker still apply.

## Continuing local voice verification

The user selected **Cedar** after the Ash run. Local real-audio testing found and
fixed native delegation dropping uncommitted caption prefixes, false quantity
disagreement for اثنين/اثنان, support approval without a ledger mutation, and
support replies never delegated by the voice model. Pending proposal replies now
have a bounded dispatch fallback; domain consent checks remain mandatory.
The new greeting identifies مطعم صوت; follow-ups ask one missing choice at a time.
New complaints must produce an actual supported resolution offer.

The full regression run passed 929 Python tests (one optional skip) and 63 Node
checks; subsequent support-offer guard changes passed 71 focused regressions.
Sixteen real-model persisted-state turns passed, including the recent pizza
issue. The earlier Ash local ordering call passed all four turns; its report is
[evidence/v3/local-order-voice.json](evidence/v3/local-order-voice.json). Cedar ordering passed all four turns and support passed all six turns on the
`ea64d61` local snapshot. See [ordering evidence](evidence/v3/cedar-local-order-voice.json)
and [support evidence](evidence/v3/cedar-local-support-voice.json). These runs precede
the merge of `b91b0ee`; they do not certify the merged or hosted release.
Ordering state results took 1.33–6.66 seconds; readback first-byte times reached
5.36 seconds. Latency remains an open release issue. Timings containing listening acknowledgements are labeled accordingly.

Hosted rollout and the final demonstration video are still pending. The hourly
thread follow-up checks quota recovery and coordinates matching API/worker
releases. Nothing here certifies all challenge scenarios or human accent quality.

The release section below describes the previously pushed candidate.

## Release decision

Candidate application commit: `f9f00ecb2cbe0f2267e1893cdf109b946c05c2df`.
[Application CI succeeded](https://github.com/clechz/sawt_demo/actions/runs/38392581865).
**Do not describe this candidate as deployed or submission-ready.**

Vercel rejected the deployment with `api-deployments-free-per-day` (more than
100). Production still serves deployment `dpl_C7ybuiR37xm2ZYHWYRi2Bmd5KTZg`.
The independently triggered LiveKit deployment completed, but was rolled back
to `TKcMfpvSprXd` because the web release could not advance. Worker deployment
is now an explicit workflow dispatch: a source push must not independently
replace production voice code while its API deployment is blocked.

OpenAI funding is usable: the real planner completed the scenarios below.
Historical recording retrieval returned HTTP 403. The recent human-call
diagnosis uses persisted transcripts/events; no claim is made that the saved
recording was heard again. Raw human transcripts and recordings remain private.

## What failed and what changed

- The recent call contained removal instructions that a secondary transcript
  reduced to “الطلب”. The recognizer now rejects losing a removal verb.
- A spoken claim that an item was removed did not match its saved basket.
  A narrow reply-evidence guard requests tool repair or clarification before
  speaking unsupported removal/edit claims. It does not mutate the order or
  replace the model with a general intent classifier.
- Delegation could keep only the last caption and lose earlier choices in a
  fragmented request. It now retains unconsumed fragments until successful work consumes them; native pending text is not trusted as
  a complete request boundary.
- A real-model hot-option correction initially produced confirmation wording
  without applying the edit. The repair gate requires mutations and a fresh
  checkout/readback before asking for confirmation. Explicit staff requests
  must also persist a support case rather than merely promise assistance.
- Blob archival failure could invalidate an otherwise generated readback.
  Duration/receipt validation now completes independently; archival runs in a
  bounded background task. This does not waive full playback or confirmation.
- The final receipt uses the saved order snapshot, including fulfillment,
  rather than the mutable basket. It persists through hangup until a new call.
- Start has a subtle animation; confirmation pulses once per new order ID.
  Hangup stops local/remote audio immediately, then shrinks/fades the orb.
  Reduced-motion preference and bounded cleanup are supported.
- Ash, `تحدي عبدالله`, explicit recording notice without a checkbox, and the
  simulation disclosure remain. Waiting instructions avoid unnecessary filler;
  when actually needed, a short “معك” replaces formal waiting language. Native
  pronunciation and subjective naturalness still need live listening.

## Original challenge coverage

This maps the supplied Notion challenge to implementation and regression
evidence. Passing offline tests is not equivalent to passing every live accent
or interruption scenario.

| Requirement | Implementation and state-based verification |
|---|---|
| Original menu, categories, branches, availability and prices | Unchanged CSV; `tests/test_domain.py`, `test_catalog_context.py` |
| Delivery, pickup, information-only, complaint | Domain + hospitality tools; `test_conversation_requirements.py`, `test_hospitality.py` |
| Address/branch changes, fees and availability recalculation | `test_fulfillment_evidence.py`, `test_challenge_edit_persistence.py` |
| Add, remove, quantity, options and notes, including after total | `test_challenge_edit_persistence.py` executes mutations against persisted state before/after quote; real-model nonlinear case below |
| Early details, fragmented speech and corrections | `test_hospitality_voice.py`, `test_recognition.py`, new fragment/removal regressions |
| Readback of items/options/fees/total; explicit confirmation | `test_transactions.py`, `test_v2_api.py`, `playback.test.mjs`; stale quote and early-playback rejection |
| One mock order ID; retry/duplicate safety | Transaction tests and repeated real-model confirmation; saved order count remains one |
| Refund, complaint, human request at any point | Hospitality/runtime tests; persisted case, proposal and ledger tests; real-model refund duplicate rejection and staff case |
| Invalid tools, stale writes, interruptions, timeouts | `test_tool_batches.py`, `test_audio_gate.py`, `test_hospitality_runtime.py`, worker binding and playback tests |
| Minimal call UI and final receipt | `completion.test.mjs`, `call-lifecycle.test.mjs`; in-app browser fixture checked start/confirmed/ended states |
| STT → agent/tools → speech → playable audio | Implementation present; latest hosted real-audio acceptance remains blocked by rollout |
| Open-model comparison, Arabic dialect metrics, versions/licenses/hardware | `EVALUATION.md` is the proposal; not a claim that proposed open models were trained or benchmarked here |
| Architecture, context, operational product changes/wireframe | `DESIGN.md`, `V3-IMPLEMENTATION.md`, `PRODUCT.md` |
| Reproducible setup and <10 minute demonstration | `README.md`, `DEMO.md`; final recording remains outstanding |

## Evidence and reproducible checks

Run from repository root after the README environment setup:

```sh
python -m pytest -q
node --experimental-default-type=module --test tests/*.test.mjs
npm ci --prefix frontend
npm run build --prefix frontend
```

The Python suite passed **923 tests**, with one optional Postgres integration
test skipped. The JavaScript suite passed **63 checks** and the frontend build
passed. The skipped integration test is not counted as passed.

Paid real-provider planner/state evaluation (synthetic text; isolated SQLite):

```sh
python scripts/eval_challenge_state.py
```

[Saved synthetic report](evidence/v3/challenge-planner.json): 13/13 turns passed
across nonlinear ordering, missing-item refund and unknown-order/staff support.
The order case removes beef after quote, changes chicken quantity to three,
switches delivery to Jeddah pickup, changes spice, requotes at 54 SAR, confirms,
and repeats confirmation without duplicating the order. Refund records 30 SAR
once; repeat refund does not duplicate the ledger entry. Early failed runs
remain in ignored local runtime evidence; the successful rerun does not erase
the failures that motivated the repairs.

These are real model calls with persisted state assertions. Their 0–3.27 second
planner timings are **not** end-to-end voice latency. Playback is simulated in
this evaluator. In-app browser QA used a labeled local UI fixture, not a real
customer call. Chrome was not used.

## Remaining release gates

1. Wait for Vercel's quota reset or have the account owner change its plan.
   Do not create alternate projects to circumvent the limit.
2. Deploy the candidate web/API using the existing project, then dispatch the
   LiveKit workflow from the same source. Verify both source contracts. Retain
   the prior deployment/version for rollback if either component fails.
3. Run `python scripts/verify_challenge_voice.py` only against the matched
   release. It sends actual PCM through LiveKit, checks edits and totals,
   downloads/transcribes readbacks and checks the committed order. It uses
   timed simulated browser playback receipts, so it does not prove speaker
   playback in a physical browser. Do not treat this prepared script as a pass.
4. Complete real microphone/listening QA in the in-app browser, including
   interruption during quote, late corrections, silence/reconnect and support.
   Measure end-of-user-speech to first audible response; report distributions,
   not only planner time. Subjective Saudi accent quality needs human judgment.
5. Restore recording storage access if archived audio review is needed; keep
   storage errors visible while ensuring they do not block valid checkout.
6. Record the final demonstration against that verified release. Repository
   access must be granted to reviewers because the repository is private; the
   challenge does not specify that it must be public.

No claim of zero recognition mistakes or production restaurant readiness is
made. Orders, payments, refunds and staff actions remain explicitly simulated.
