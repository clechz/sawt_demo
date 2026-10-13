# Implementation order: close the research-to-experience gap

Work branch: `feat/v3-hospitality-voice`; review: PR #3. Main and the existing hosted demo are not changed by this execution order. The supplied menu stays byte-for-byte unchanged.

## Current starting point

The earlier audit describes an older branch state. V3 application code now exists (application commit e347576, evidence/cleanup commit 9c932e7). It contains per-call Cedar/Ash/Marin selection, native GPT-Live delegation, selective verification, and isolated simulated order/support records. Those are implementation candidates, not live speech acceptance evidence.

This first integration batch brings in all seven files from PR #1 (4e325ba) without discarding their tests; adds explicit outcome ownership; repairs stale rejected planner replies and the choice-guard group-key mismatch; and tests complete V3 preparation/publication paths. PR #2's older case logger is not merged on top of V3's replacement support engine: doing so would reintroduce conflicting state and demo-only refusal copy.

## Order of work and completion gates

| Sequence | Deliverable | Current evidence / gate |
|---|---|---|
| 1 | One coherent V3 source and explicit response ownership | Implemented in this batch; full pinned CI still must be checked on the final commit |
| 2 | Receiver-verified support proposals and consequential speech | Next implementation; current server-side playout marker is weaker than checkout receipts |
| 3 | Complete support lifecycle and repeat/reconnect behavior | Seeded refund/replacement/cancellation implemented; transitions, authenticated resume, and mixed tasks need additional integration coverage |
| 4 | Voice controls across the whole call | Pre-call Cedar/Ash/Marin implemented; audition and preview remain; mid-call replacement is not implemented |
| 5 | Natural conversational timing and recovery | Native delegation implemented; real audio, latency, interruptions and false business claims remain unverified |
| 6 | Matching preview, held-out Saudi calls, and release | Not deployed or certified by unit tests |

### 1. Response ownership and integration

Completed here:
- Preserve PR #1's exact Saudi spice labels, explicit single-shawarma choices, and regression tests.
- Publish an explicit `outcome` envelope: `task_id`, `kind`, `changed_domains`, `revision`, `pending_question`, and `speech_mode`.
- Determine changed domains from before/after domain state, not a global revision bump or a model success statement.
- Preserve support responses with empty, incomplete, complete-unconfirmed, and confirmed baskets.
- Never publish wording rejected by a clarification/confirmation guard while repair calls are still running; reject on repair-budget exhaustion.
- Use the actual choice-guard schema (`group`, not `group_id`) when rendering acknowledgments.
- Exercise prepare -> commit -> reload -> replay with a scripted model and real SQLite. Label the model as scripted, not live understanding.

### 2. Close the receiver acknowledgment gap

Reuse or generalize the existing checkout playback machinery for support proposals. Persist a receipt bound to call, proposal ID, revision, audio generation and voice. A completed provider stream or worker playout alone must not authorize a resolution. The browser acknowledges completed current playback; interruption, stale callbacks, partial audio, rejected autoplay and receiver timeout leave the offer unaccepted. Keep a bounded replay of the same proposal without executing it.

Required tests: no receipt; wrong call/token; stale proposal; interrupted first packet; started but not ended; early user yes; delayed completion from an old player; repeated acceptance; expired offer after a topic change. Both SQLite and isolated Postgres must preserve the same contract. No customer assertion or model tool argument may set `presented=true`.

### 3. Finish the simulated service, not a refusal script

Keep the fictional operating profile separate from menu data. The existing seeded missing/wrong-item order has a 30 SAR line and 15 SAR delivery charge; a line refund must not silently refund the whole 45 SAR order.

Build scenario-controlled status transitions with an injected test clock: accepted -> preparing -> ready -> dispatched/collected -> completed. Gate amendments/cancellation on actual mock status; preserve order snapshots and operation IDs. A replacement request becomes a persistent replacement journey; staff review remains pending until an explicit simulated event advances it. All events remain isolated and carry `simulated=true`.

Add authorized logical-call resume before claiming reconnect continuity. Never expose another caller's seeded or new orders. Unknown IDs stay unknown. Offer changes require fresh acceptance. Preserve unrelated saved basket fields while support is active, then resume the existing order without a new intake interview. Test paraphrased repeat complaints and cross-category attempts at duplicate compensation. Do not contact real staff, couriers, restaurants or payment systems.

### 4. Voice and restaurant identity

Use the existing session-local selection, never process-global environment mutation. Validate all UI voices against the funded Live and TTS providers, including business speech, checkout, recovery and goodbye. Cedar is provisional, not a proven Spruce equivalent. Do not expose or relabel Spruce without a documented supported identifier.

Add short cached previews, keyed by voice/model/text/style version, with authenticated and budgeted generation. Keep pre-call choice usable while mid-call support is built. Mid-call switching requires a new provider session and media generation, not a dropdown pretending to mutate an immutable voice. Preserve logical state and prevent old cleanup callbacks from closing the replacement; defer during sensitive playback/commit phases. A switch must not place or duplicate an order.

The Saudi host should greet once, use consistent ordinary language, ask only missing details and acknowledge a specific complaint without repeated apologies or sales prompts. Apply phrasing to both live persona and backend speech. Maintain visible AI/simulation disclosure and explicit recording consent, not repeated demo disclaimers in every reply. Missing allergen data stays unknown.

### 5. Natural conversation and latency

Keep one conversational model, one bounded business interpreter and deterministic tools. Do not add a general intent-classifier service or a list of random fillers. Brief listening cues are not business confirmations. One optional progress statement must describe work actually underway and become obsolete immediately when the result arrives or the caller corrects it.

Use native GPT-Live timing; do not apply turn-based Realtime VAD settings as though they control this integration. Treat caption coalescing, acoustic verification, planner loops, database work, TTS startup and receiver playout as separate latency sources. Preserve existing batching. Speculate on read-only preparation only; publish actions after validation and current revision/epoch checks.

Test interrupted native speech, exact speech, checkout and support proposals. Replaying an already committed result must never rerun its mutation, and must not disappear into silent return. Keep the model's context aware of what actually played; a generated transcript is not proof of received speech. Free-form live business speech needs explicit received-audio checks for fabricated prices, option changes or success claims.

### 6. Preview and acceptance evidence

Provision a private preview with isolated database and matching API/worker build. Record API SHA, worker SHA, profile/policy versions, voice, model and unchanged menu checksum per run. Environment-variable presence is not provider entitlement or microphone readiness.

Run the full pinned Python suite, all 24+ JavaScript tests, frontend build and Postgres contract first. Then funded end-to-end tests with actual received audio on reviewer devices, followed by spontaneous Saudi calls by people who did not author the prompt. Evaluate ordinary orders, price-only questions, long pauses, asides, Arabic/English mixing, corrections, complaints, unknown requests, reconnects and concurrent voices.

Record first acknowledgment separately from first useful answer and task completion. Targets to validate, not current results: simple useful reply median <=1.5s and p95 <=3s; explicit interruption stop p95 <=300ms. Count silence/missing output/timeouts as failures. A filler does not satisfy a useful-answer gate. Human listening must rate accent, pacing, clarity and usefulness; ASR alone cannot rate Saudi naturalness.

Promote only after this exact preview release passes. Preserve V2 rollback and all earlier failed evidence. No merge/deploy, API credit spending or human evaluation is claimed by this document.

## Primary implementation references

- https://developers.openai.com/api/docs/guides/live-delegation
- https://developers.openai.com/api/docs/guides/live-prompting
- https://docs.livekit.io/agents/models/realtime/plugins/gpt-live/
- https://developers.openai.com/api/docs/guides/text-to-speech

## Evidence for this batch

Before fixes: the new suite exposed rejected-wording leakage and repair-budget fallthrough; new outcome-contract assertions were not yet satisfied. Choice-guard schema correction is exercised by an unavailable-bread journey. After fixes: 379 selected Python regressions and 24 Node tests passed locally. The container cannot resolve dependency hosts, so pinned media dependency installation failed; full pinned CI is separate evidence and must be inspected, not inferred. No paid call or real Saudi-listener test ran locally.
