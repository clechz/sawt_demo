# Submission gates — 13 October 2026

This is an evidence checklist, not a declaration that the hosted release is ready.

## Latest retest: release gate failed

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
Local HTTPS serves the page, but calling through the LAN address returns 403:
the code-free allowlist contains an old device IP. Changing it awaits explicit
approval after automatic approval review rejected the update. Localhost remains
available. No firewall or certificate trust changes were made in this retest.


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
