# V3: a Saudi restaurant experience, not a voice-enabled form

Status: implementation candidate on `feat/v3-hospitality-voice`. The live deployment and `main` are not changed by this work. The menu CSV, prices, option IDs, branch fixtures and existing final-order confirmation contract remain intact. Real-provider speech quality is a release gate, not established by offline tests.

## 1. Product contract

The tester should be able to call, ask a question without ordering, order in their own sequence, pause, correct themselves, switch languages, raise a complaint, obtain a simulated resolution, and inspect what actually happened. The agent should not repeatedly announce that it is a demo or use the word “simulation” as an excuse to stop helping.

The boundary is simple: the interface clearly discloses synthetic AI speech and simulated orders, payment/refund records, couriers and staff. Recording requires an explicit checkbox. Within that disclosed world, supported actions operate normally and persist. “رجعت لك ثلاثين ريال” is appropriate only after the simulated ledger contains that refund. A request for review is not an approved refund. Nothing contacts a real restaurant, payment system, courier or employee. If directly asked, the agent explains that truthfully.

Natural does not mean pretending to be human. It means appropriate timing, consistent language, relevant questions, good memory of saved choices, competent repairs and useful outcomes.

## 2. What this implementation changes

### Per-call voice selection

The UI offers Cedar, Ash and Marin before the call and remembers the preferred voice locally. Cedar is the initial candidate, not a proven acoustic equivalent of Spruce. Invalid voice IDs are rejected server-side. Spruce is not exposed as an API voice because no supported identifier or official mapping was found in the reviewed API documentation.

The selected voice is saved in the call's durable `experience` settings. It travels to the live worker, business-response TTS, recovery speech and checkout readback. No request mutates `os.environ` to switch a voice, so simultaneous callers cannot change one another's voices. The selector is disabled during a call; changing it afterward applies to the next call. The current Live voice is startup-only, so a mid-call selector must not secretly restart the model or discard the basket.

Voice-specific cache keys are retained. Non-Marin calls do not reuse the Marin confirmation asset. UI preferences never constitute provider entitlement checks.

### Separate V3 conversation handling

V2 remains available through `experience_version: "v2"`. V3 has a separate voice subclass and planner/runtime adapter, rather than an unconditional rewrite of the rollback path. The current UI starts V3 calls explicitly; API callers that omit the version retain V2 behavior.

V3 uses native GPT-Live delegation to start backend work. A final caption is no longer treated as proof of a restaurant request, and a short exact social-phrase whitelist no longer decides whether the agent is allowed to speak. The live prompt explicitly permits moderate listening acknowledgments and conversation while real work is underway. It forbids claiming a business outcome before a saved tool result exists.

This removes blanket business-turn muting while work is in progress. It does NOT remove exact output control for consequential results. Draft edits, questions that bind a later yes, prices and consequential status statements still use the exact speech path. Appropriate lower-risk replies can use Live commentary. A spoken reply generated from commentary is not guaranteed to reproduce the supplied words; that path requires received-audio regression tests.

The 250 ms caption-coalescing candidate runs after native delegation rather than making every finalized caption a new task. It is not a semantic-VAD setting, and it is not a claim that the user receives a response in 250 ms. Native current-turn hints are aligned against captured caption fragments to avoid unnecessarily reprocessing older small talk. If alignment is unavailable, the unconsumed input is retained rather than guessed.

### Selective recognition and staged work

Ordinary informational requests and simple catalog answers avoid a second transcription request. Verification is tied to actual staged actions: final order creation, draft cancellation, accepted support resolutions, removal/replacement, addresses, and quantity/negation-sensitive edits. This is a testable engineering policy, not a fabricated recognition confidence score.

Planning occurs against a private copy. The verified transcript is checked in both directions for critical disagreement. Explicit acceptance must remain explicit in both transcripts. If verification changes the words, the previous plan is discarded and a new plan is prepared from the verified words. A recognizer approving some audio cannot authorize an unrelated caption-based plan.

Only after verification, revision and input-epoch checks does a transaction publish the bundle. Slow, superseded preparations cannot overwrite newer input. Already committed changes are preserved and can be corrected by the next request; interruption never implies rollback of a transaction that already committed.

### Stateful simulated support

The simulation has current/seeded orders, cases, pending resolutions, a refund ledger and replacement records. The restaurant profile is separate from the menu. Opening hours and payment descriptions are explicitly fictional operating fixtures; ingredient and allergen information is NOT invented.

A new confirmed order creates a simulated accepted/paid record. A missing/wrong-item scenario seeds an order with a real catalog item and option set: one large shakshuka with tamees at 30 SAR, plus the existing Narjis delivery fee of 15 SAR. A line refund is therefore 30 SAR, not an invented whole-order refund. A late-delivery scenario has an explicit simulated status and ETA, not real courier tracking.

Supported workflows:

- Look up the current or seeded order and its actual saved status. Unknown IDs remain unknown.
- Open a missing-item, wrong-item, late-order, cancellation, general or allergy case without freezing the order conversation.
- Offer a policy-eligible item refund, no-charge replacement, pre-preparation cancellation or staff review.
- Require a separate explicit acceptance of a presented, unchanged proposal.
- Record the resolution and make its result visible to the tester.
- Reuse existing cases/resolutions and prevent duplicate compensation of the same line, even under a different complaint category.

Offers do not execute actions. Amounts are computed from records, never supplied by a model argument. A case needing staff review remains `review_requested`; it does not impersonate a completed human intervention. A replacement remains a requested replacement, not a claim that the kitchen already delivered it. Current scenarios are seeded states, not a live GPS system or a continuously advancing courier simulator.

Order checkout retains the original browser receipt and separate spoken acceptance. Support proposals currently use the worker's completed guarded playout marker. That is weaker than a receiver acknowledgment and is NOT proof that a caller heard audio from their speakers. The support receiver-acknowledgment test listed below remains a release-hardening task; do not describe those two receipt mechanisms as equivalent.

### Restaurant manner

`data/hospitality-profile.json` owns the new live persona and the simulated operating facts. The opening is “يا هلا، حياك الله، تفضل.” There is no repeated “أنا مساعد المطعم الذكي.” The profile calls for an unhurried, competent Saudi host: concise, attentive, consistent dialect, no habitual upsell, and one focused follow-up rather than a form.

A complaint is acknowledged briefly and moves toward a resolution. A price question is answered without starting an order. Existing catalog rules continue to distinguish an ambiguous dish from a clear dish with missing options. Clear facts can be saved as a draft while one uncertainty is clarified. Required choices are never silently defaulted to make the demo appear smoother.

Use “شطة” only when it correctly describes the existing heat option. It must not create a new sauce or ingredient. No claims of popularity, dietary suitability, allergy safety or stock beyond supplied sources.

## 3. File-level map

| File | Responsibility |
|---|---|
| `sawt/experience.py` | Validated immutable voice/scenario configuration and experience catalog |
| `data/hospitality-profile.json` | Saudi persona, approved simulated facts and resolution policy |
| `sawt/hospitality.py` | Stateful simulation tools and policy-enforced resolutions |
| `sawt/hospitality_runtime.py` | Bounded planner, staged turns, selective verification and atomic publication |
| `sawt/hospitality_voice.py` | Native delegation, conversational output, interruptions and result delivery |
| `voice_worker.py` | Select V2/V3 per call while retaining the original media lifecycle |
| `sawt/transactions.py` | Persist experience and isolated scenario state in existing call storage |
| `sawt/v2_provider.py` | Session-scoped voice across synthesis/cache paths |
| `app_v2.py` | Experience catalog, validated call creation and voice-correct checkout |
| `static/v2/experience-ui.js`, `experience.css`, `index.html` | Voice/scenario controls, consent, persistent simulation badge and case results |
| `static/v2/app.js`, `order-view.js` | Wire settings into call startup and display current outcomes |
| `tests/test_hospitality*.py`, `tests/experience.test.mjs` | New domain/runtime/voice-policy and browser-logic regression tests |

## 4. Why this architecture

The main separation is conversation versus authoritative state, not a chain of multiple specialized chatbots. Live handles conversational timing. One backend planner reasons over bounded current state and retrieved menu definitions. Deterministic tools own the outcomes. No extra general intent-classifier service is introduced.

Do not blindly switch the backend model because a newer name exists. Keep the currently configured model as the measured baseline, then benchmark supported alternatives against the same held-out calls. Select on task accuracy, natural latency, repair quality, tool correctness and cost—not one synthetic successful request. `LLM_MODEL` still controls the planner, not the live voice model.

Preserve stable prompt/tool prefixes for caching. Batch independent known edits and the state-derived follow-up in one request. Do not ask the model to invent a generated line/case ID before its creating tool returns. Read-only retrieval does not itself save a selection. Never hold a database transaction across model, recognition or speech network calls.

## 5. Completion plan and release gates

### Gate A: deterministic correctness

Run all original Python tests, the new Python tests, all JavaScript playback/startup/experience tests, and the locked frontend build. Compare the menu blob/hash to the branch base. Verify simultaneous callers with different voices, incorrect voice IDs, missing consent, cross-call authorization, refunds after wrong/missing-item complaints, declined/unheard offers, repeated acceptance, interruption before commit, and persistence after reopening the database.

Check planner failures with scripted tool envelopes: malformed JSON, invalid IDs, partial option errors, failed mutations before checkout, insufficient context and exhausted budgets. The visible reply must not claim a rejected change succeeded. Domain tests and scripted planners are not measurements of actual model understanding.

### Gate B: real provider compatibility and voice audition

Using funded credentials in the existing secret environment, verify GPT-Live and TTS for every UI voice. Do not paste keys into chat or commit them. Compare the same Arabic utterances through both live speech and exact TTS: greetings, corrections, numbers, money, unfamiliar streets, bread names and an upset-customer exchange. Cedar is provisional until this listening test.

Verify that checkout/recovery never switches back to Marin in Cedar/Ash calls. Test stream failure after the first packet, interrupted synthesis, missing final confirmation words and browser autoplay refusal. No receipt may become valid merely because synthesis returned bytes.

### Gate C: full conversational journeys

Run these on an isolated preview API + matching V3 worker; do not point a V3 browser at an old worker:

1. Order in one utterance, missing options, later additions, pickup/delivery change, recap and explicit final confirmation.
2. Unscripted Saudi hesitation and mid-utterance correction; do not seize a pause as an order submission.
3. Ten-plus-turn call with small talk followed by a real request; no expired PCM window caused by old greetings.
4. Interruption during native speech, exact business speech, checkout, planner processing and support proposals.
5. “Wait,” an aside to a friend, a return to the agent, and “stop talking” without canceling a draft.
6. Price/menu/branch-only questions with no basket mutation or unsolicited sales question.
7. Missing/wrong-item complaint, refund or replacement, explicit acceptance, repeat question and no double compensation.
8. Late delivery followed by staff review; a pending review must remain pending.
9. Unknown order, request outside policy, allergen question, negative answer and refusal of proposed resolution.
10. Switch languages, change the UI voice between calls, close/reopen the UI and run two simultaneous voices.

Use real Saudi speakers who did not author the prompt, not only synthetic fixtures. Compare V2 versus V3 with the same speaker/device and representative task. No automatic ASR transcript can establish that a voice sounds authentically Saudi.

### Gate D: latency and naturalness

Keep five measurements separate: end of customer speech, first acknowledgment, first useful answer, durable action completion, and audible stop after interruption. Record medians and tail percentiles, not only a fastest call. Report unexplained silence, repeated questions, false progress statements, wrong saved state, false success claims, misunderstood corrections, and task completion.

Initial engineering targets, not observed results: straightforward requests should usually reach the first useful reply within 1–2 seconds, with a reviewed p95 target of 3 seconds; complex support/checkout can have a different budget. Target an audible stop within approximately 300 ms after a clear interruption. An acknowledgment does not count as the useful answer. A “checking” phrase every turn must not inflate the score.

Let native backchannels carry ordinary attentiveness. Add at most one progress update only when genuine work remains slow, and cancel it if the result arrives or the caller interrupts. Do not add fake keyboard sounds, background restaurant noise or random filler to hide unresolved backend latency.

Specific hardening before promoting the native-speech path: validate that free-form business speech never invents a price, changed option or transaction status; inspect rendered audio, not only provider output text. Support proposals need a receiver-side completion acknowledgment before they can be treated as having the same strictness as order checkout. Verify stale-output cleanup against new speech and the append-only live context.

### Gate E: deployment and rollback

Keep `main` and the current hosted worker unchanged until the above gates pass. Create a private preview with the same code revision on API and worker; use an isolated database/room namespace. Publish the exact commit SHA and `hospitality-v3-candidate` release marker in test evidence. The frontend must retain visible disclosure and explicit consent.

Record the actual hosted API and worker version before evaluating. Stop on missing credit, unavailable model/voice, no microphone publication or no returned audio. A budget increase is not a provider-credit fix. Roll back by selecting V2 and redeploying the known baseline; do not overwrite the original evidence with synthetic claims that V3 passed.

## 6. Running and validating

The existing Python 3.12 setup remains. Start the API and worker from this branch using the README's V2 commands; per-call settings select the new implementation. The UI sends `experience_version: "v3"`, `voice` and `scenario` with explicit `recording_consent`. For a rollback comparison, an API client may send `experience_version: "v2"` with `scenario: "new_order"`.

Local quick checks:

```bash
python -m pytest -q tests/test_hospitality.py tests/test_hospitality_runtime.py tests/test_hospitality_voice.py
node --experimental-default-type=module --test tests/experience.test.mjs tests/call-start.test.mjs tests/playback.test.mjs tests/audio-meter.test.mjs tests/call-status.test.mjs
python -m pytest -q
npm ci --prefix frontend
npm run build --prefix frontend
```

The old `v2_cloud_suite.py` starts baseline calls unless explicitly adapted. Its passing report must NOT be mislabeled V3 evidence. Paid V3 end-to-end evaluation and a native Saudi listener comparison remain to be run in the funded preview environment.

## 7. Evidence recorded for this candidate

The implementation session ran 53 new Python tests, the 587-test locally importable regression subset (one skip), and 24 JavaScript tests successfully before packaging. The full pinned Python 3.12/LiveKit/AV suite and frontend build run on GitHub Actions. The local container lacks the project's pinned media dependencies; the excluded local test modules are documented in the validation report. Treat CI results as separate evidence and inspect the final run, not the earlier baseline run.

No new paid call, Spruce-equivalence audition, real courier integration, actual refund, production deployment or human-rated naturalness benchmark is claimed.

## 8. Primary research used

Reviewed 2026-10-12/13:

- OpenAI, Prompting GPT-Live: https://developers.openai.com/api/docs/guides/live-prompting
- OpenAI, Delegation and tools: https://developers.openai.com/api/docs/guides/live-delegation
- OpenAI, Live session creation and startup-only voices: https://developers.openai.com/api/reference/resources/live/methods/create
- OpenAI, Text to speech, voice choices and disclosure: https://developers.openai.com/api/docs/guides/text-to-speech
- LiveKit, GPT-Live plugin, client delegation/current turn, append-only context and interruption limits: https://docs.livekit.io/agents/models/realtime/plugins/gpt-live/

The design deliberately distinguishes documented capabilities, measured test results and proposed performance goals.
