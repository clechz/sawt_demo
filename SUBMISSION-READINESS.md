# Submission gates — 13 October 2026

> Current release note — 16 October: see the [README release audit](README.md#release-audit--2026-10-16) for the deployed revision and remaining actual-browser verification. The dated runs below are historical evidence, not a blanket certification of today's version. Private new call evidence is deliberately excluded from this public repository.

This is an evidence checklist, not a declaration that the hosted release is ready.

## Hosted verification update — 13 October

The live API and worker now pass the source compatibility check. A real synthetic
Arabic call passed naming, priced readback, removal/quantity and branch/spice
corrections, confirmation, and received success speech in 1.98 seconds. An
independent Postgres read verified one durable order after closure.
See [hosted order evidence](evidence/v3/cedar-hosted-order-ending.json).

The support run passed refund confirmation and duplicate-refund protection but
failed during speech generation for a staff-offer question. The worker now has
an independently transcribed Cedar asset for that fixed question. Its no-network
regressions passed, and the [complaint retest](evidence/v3/cedar-hosted-complaint-retest.json)
passed all three turns. The [initial failed run](evidence/v3/cedar-hosted-support-failed.json)
is retained. These are synthetic media tests, not native-speaker certification;
order readback completion acknowledgments are timed simulations.

Production Vercel deployment: `dpl_AyVmTSgRYguLrex4z772uGwEXo3Z`.
Worker: `EgnxPJY9d9rM`. The worker's additional fixed-speech asset is not yet in
the production web bundle; runtime contracts match and the hosted tests pass.
An explicit Vercel production deploy still returned `api-deployments-free-per-day`
with a 24-hour retry instruction. No quota workaround was attempted. Cloud Blob
recording archival still fails, and not every challenge scenario has been retested
on this hosted revision. No full submission-readiness claim is made.

Publication update: the repository is public and access was checked without
authentication. The user's 4 min 7 sec recording is being prepared as a separate
email attachment at the user's request; the public video release was removed. Video content has
not been fully reviewed against the architecture, model-research and product
explanation requirements; earlier references to a missing video are historical.

## Latest local order-ending retest: passed; hosted release pending

[Recorded test evidence](evidence/v3/cedar-order-ending.json): a synthetic Arabic
caller used real LiveKit/OpenAI audio over trusted LAN HTTPS, without Chrome.
The agent asked whose name the order was under, saved Abdullah, read the priced
summary, applied removal/quantity and branch/spice corrections, waited for explicit
confirmation, saved the 54 SAR order, and delivered the complete Cedar success
phrase. Receiver audio was independently transcribed as “تأكد طلبك، يعطيك العافية.”
First received success audio was 1.84 seconds after the approval input was sent.
The actual saved order also passed receipt rendering/persistence checks in Node.
950 Python tests passed (one optional Postgres skip), 65 Node tests passed, and
the frontend production build passed.

Limits: readback completion receipts were timed simulations; receipt rendering
used a DOM fixture, not a physical browser/device check. This is one successful
synthetic order journey, not proof of all accents/scenarios or hosted readiness.
The harness emitted LiveKit FFI cleanup warnings after completing and closing
the call; its process exited successfully. Matched cloud deployment remains
blocked by the Vercel deployment quota; the submission video is still outstanding.

## Earlier failures (retained for traceability)

The newer integrated local call failed after treating a bread option as an extra
dish and describing an unsaved basket. A following run exhausted three private
replans while the caller continued speaking and timed out. The resulting fixes
add an empty-basket claim guard, clarify option attachment, and resume already
delegated unfinished work. **940 Python tests pass (one optional skip), but these
last fixes still need a successful full real-voice retest.** Earlier audio passes
below remain historical evidence, not a pass for this revision.

The existing Vercel release accepted login and a Cedar call, but answered an
Arabic price question by falsely claiming there were no sandwiches. Deployment
of the fixes is still rejected by `api-deployments-free-per-day`.
The user approved code-free access for exactly `10.207.119.67/32`; that local
allowlist update is applied. The trusted LAN HTTPS retest passed initial ordering,
removal/quantity correction and branch/spice changes. Final confirmation saved the
correct 54 SAR order, but no confirmation audio arrived within five seconds after
the saved state was observed. **The full voice gate remains failed.** See the
[LAN retest](evidence/v3/cedar-lan-retest.json). Testing from this PC through its LAN
address does not prove reachability from another computer. No firewall or
certificate trust changes were made.


| Required gate | Status and evidence |
|---|---|
| Repository runs from README | **Verified on Windows / Python 3.12.** Fresh virtual environment installed `requirements-v2.txt`; both entry points imported. A clean tracked-source copy launched with the documented uvicorn command; health and call page returned HTTP 200. Credentials are still required for voice. macOS/Linux commands were not executed. |
| Arabic audio input → Arabic audio output | **Verified locally on the ea64d61 snapshot; hosted merged release pending.** Four Cedar ordering turns and six support turns used synthetic Arabic PCM through real LiveKit/OpenAI. [Ordering](evidence/v3/cedar-local-order-voice.json), [support](evidence/v3/cedar-local-support-voice.json). Readback receipts were timed simulations, not physical speaker testing. Latency remains unsatisfactory on some turns. |
| At least 100 items, accessed by tools/retrieval | **Verified.** 144 distinct items / 1,728 CSV rows; catalog tools retrieve menu definitions. `tests/test_domain.py` checks the count and every item's option pricing. See [architecture](DESIGN.md). |
| Non-linear journey recalculates state | **Verified locally.** Real ordering: chicken + beef = 58 SAR; remove beef and change chicken quantity = 54 SAR; change branch/spice; fresh readback; explicit confirmation. State tests additionally cover fulfillment, address, availability, fees, stale quotes and duplicate protection. Hosted verification is pending. |
| Arabic STT, LLM and TTS evidence | **Included.** [EVALUATION.md](EVALUATION.md) provides sourced candidate research, licensing, alternatives and an evaluation plan. The live evidence above separately measures the implemented hosted-provider path. Open-weight candidates were not run locally; published scores are labeled. |
| Product proposal with flow/wireframe | **Included.** [PRODUCT.md](PRODUCT.md) includes the policy-change workflow, text wireframe, acceptance examples and rollout/rollback plan. It is a proposal, not a shipped operations console. |
| Working video link with live demonstration | **Missing.** No finished video or accessible video URL has been supplied. [DEMO.md](DEMO.md) is the under-10-minute recording script, not a video. Record actual interaction with microphone + system audio and verify reviewer access to the uploaded link. |

## Current integration validation

After merging the Cedar fixes with b91b0ee: **938 Python tests passed, one optional
Postgres test skipped; 63 Node tests passed; frontend typecheck/build passed.**
These counts are local results, not a claim of CI or deployed acceptance success.
The four legacy complaint fixtures now check a persisted resolution proposal and
an empty refund ledger before approval instead of stopping at complaint logging.

## Still open before final submission

- Deploy matching Vercel and LiveKit components once Vercel's deployment quota
  allows it, then verify their source fingerprints and rerun voice acceptance.
- Address slow meaningful replies: the Cedar ordering run reached 6.66 seconds
  to saved state and 5.36 seconds TTS first byte. Those suites overlapped; this is
  not a clean-load latency benchmark and backchannels do not count as answers.
- Verify current browser playback, interruptions and final receipt on the exact
  deployed revision. Local scripted receipts cannot certify device playback.
- Record/upload the demonstration and check the link from a reviewer-accessible
  session. The repository is private; grant the reviewers access or explicitly
  choose to publish it before submitting.

Do not mark the video or hosted-release gates complete from source tests alone.
