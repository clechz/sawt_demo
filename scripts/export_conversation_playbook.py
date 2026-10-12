"""Export the exact editable call copy with its behavioral contract."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sawt.conversation import COPY
ROOT=Path(__file__).resolve().parents[1]
WHEN={
 'greeting':'Once on connection. Invite ordering, information or a complaint; do not assume an order.',
 'unclear':'Audio could not be verified. Ask once; never act on the uncertain words.',
 'audio_check':'The caller says they cannot hear the bot. Resume output; do not interpret it as a request to be quiet.',
 'service_question':'An ordering caller has not yet chosen delivery or pickup.',
 'address_question':'Delivery is selected but a usable supported address is still missing. Rephrase to ask only missing parts.',
 'branch_question':'Pickup is selected and its branch is missing.',
 'choice_saved':'Only after committing the choice; next question covers an actually missing field.',
 'change_saved':'Only after committing a change. Do not use this for a failed tool.',
 'next_item':'Complete draft after a saved change; no automatic sales/add-on offer.',
 'empty_basket':'Ordering conversation has no remaining items. Not appended to an explicit cancellation.',
 'unavailable_item':'Saved item is unavailable at the selected branch. Keep it visible and ask the caller to decide.',
 'small_unavailable':'The requested small size is absent from the supplied options.',
 'karak_ice':'The unmodified fixture requires an ice choice for karak. Propose no ice explicitly; do not silently default.',
 'choice_proposal':'Persist a specific line/group/option proposal. Yes applies to this option only.',
 'choice_question':'Ask from the current item options; never ask again for a choice already saved.',
 'handoff':'A mock staff-request ticket has actually been saved. No live human transfer or callback promise.',
 'offer_handoff':'Persist a staff-ticket proposal. Yes creates the ticket; no clears the offer and preserves the basket.',
 'handoff_declined':'The caller declined the current staff-ticket proposal. Do not repeat the same offer immediately.',
 'missing_other':'An unsupported fact/capability was requested. Combine with offer_handoff only when offering staff help.',
 'missing_hours':'No opening-hours data is supplied.',
 'missing_allergens':'No verified ingredients/allergen data is supplied. Never infer safety from dish names or notes.',
 'missing_tracking':'No delivery tracking or courier connection exists.',
 'missing_payments':'No payment, refund or real order settlement exists.',
 'missing_scheduling':'No booking or scheduled-order integration exists.',
 'confirmed':'Exactly one saved mock order after completed current readback and explicit acceptance.',
 'already_confirmed':'Repeat acceptance returns the same order ID, never another order.',
 'draft_canceled':'Explicit whole-draft cancellation. Clear basket, service, address, branch, quote and pending choices; keep call open.',
 'nothing_to_cancel':'Explicit cancellation when no draft/fulfillment details remain.',
 'confirmed_change':'Confirmed order remains unchanged; real cancellation/amendment requires staff integration.',
 'goodbye_empty':'Explicit hang-up with no draft/order. Thank-you alone does not disconnect.',
 'goodbye_draft':'Explicit hang-up with an unconfirmed basket. Make clear no order was confirmed.',
 'goodbye_confirmed':'Explicit hang-up after confirmation. Preserve the confirmed order.',
 'goodbye_handoff':'Explicit hang-up after a mock ticket. Do not pretend a staff member joined.',
 'backend_error':'The step failed. Preserve committed state; avoid claiming whether an unobserved network response succeeded.',
 'voice_error':'Fatal media/provider failure; saved details remain accessible.',
 'storage_error':'Stop the call if durable state cannot be read safely.',
 'summary':'Server-filled items, all quantities/options/notes, service, branch, delivery fee, total and ETA; explicit confirmation question.'
}

INTRO='''SAWT — CALL EXPERIENCE AND REUSABLE WORDING
Reviewed against the actual challenge on 2026-10-12.

DECISION
Keep one conversational model/planner and validated tools. No separate intent
classification model. Natural-language understanding stays flexible; code owns
state changes, pricing, confirmation, cancellation and call lifecycle.

The source of recurring spoken wording is data/conversation-copy.json.
Edit that file, then restart the voice worker for new calls. Regenerate this
review with python scripts/export_conversation_playbook.py. A wording edit must
not silently change the behavior/conditions described beside it.

The introduction no longer announces recording or data collection. Existing
local diagnostics/recording continue, as requested. If asked directly, the
assistant should answer truthfully. Nothing here changes the retention policy.

HOW TO READ THE SCRIPT
These are reusable building blocks, not a list of sentences to recite on every
call. Most calls need the greeting, a few contextual questions, readback and
confirmation. Waiting is SILENCE. Routine processing is shown in the orb; it
does not need constant spoken filler. A direct End button disconnects promptly;
an explicit spoken hang-up uses a brief state-aware goodbye, bounded to 8 seconds
including synthesis/playback, then disconnects even if speech fails.

Control wording is fixed. Menu answers/recommendations remain model-generated
from retrieved data. The complete checkout summary is generated by the server
and is never paraphrased by the voice model. Prices are calculated, not guessed.
The greeting/recovery wording is supplied to the conversational voice model;
exact word-for-word acoustic delivery is not guaranteed for those turns.

REUSABLE PHRASES — LIVE SOURCE
'''

COVERAGE='''
CUSTOMER REQUEST COVERAGE

Each row says what should happen, what guards it, and where evidence is found.
"Tested" below is scoped to the named tests, not a promise about every Arabic
paraphrase, microphone, accent or production integration.

1. Greeting / purpose: open invitation; once per call. New prompt/copy is loaded.
   Information and complaint paths do not force a delivery/pickup interview.
2. Price-only question: retrieve relevant variants; answer prices; empty basket.
   Live interaction-eval and original human-audio replay passed. Extra filler can
   still vary; prompt adherence alone does not prove every answer stays minimal.
3. Broad menu/categories: list_categories returns all 12 real categories.
   Live interaction-eval passed; no arbitrary search for the word "menu".
4. Dish search / recommendations: bounded retrieval, real IDs/options/prices.
   Preference/budget dialogue is supported by planner; no separate exhaustive
   recommendation quality benchmark was performed this revision.
5. Branch information only: list branches without selecting service/branch.
   Jeddah-only information case passed against the real planner.
6. Delivery: supported city/neighborhood/address selects branch, fee and ETA.
   Fixed mock zones, not GPS/distance. Domain and prior nonlinear tests cover it.
7. Pickup: explicit branch, zero delivery fee; don't call a branch "nearest".
   Domain and prior live tests; no real geolocation integration.
8. Items before address: preserve draft. Ask only remaining required fields.
   Existing early-item and draft-first regressions.
9. Complete order in one sentence: save clear service/location/items/options.
   Existing live order tests and synthetic recognition replay.
10. Multiple quantities/modifiers: distinct lines when choices differ.
    Existing two-distinct-meals checks; quantity 3 -> 2 audio replay passed.
11. Arabic/Western digits and English words: normalize known values, preserve
    meaning. Real media test accepted "two karak, large, no ice, half sugar".
12. Short yes/no/normal/brown/without: bind to the current stored question.
    clarification tests and earlier human-call regression, not a global default.
13. Ambiguous dish (plain tamees/generic shawarma): clarify before picking a
    variant. Guards reject an unstated chicken/beef or honey/cheese substitution.
14. Unavailable size/bread/modifier: explain actual alternatives; no fake success.
    Choice guards, unavailable-option checks and saved human-call regressions.
15. Add vs replace vs change quantity: use stable lines; preserve untouched choices.
    Domain/choice tests; corrections never become duplicate additions.
16. Remove one item: remove_item; recalculate total and invalidate old quote.
    Existing domain, live and replay tests.
17. Cancel whole unconfirmed order: cancel_draft; clear draft and fulfillment;
    keep call open. New unit and live backend tests. Conditional/negated/quoted
    cancellations cannot take the deterministic cancellation shortcut.
18. Delivery -> pickup: discard old delivery address/fee, revalidate branch.
    Existing required challenge transition tests.
19. Location/branch correction after items: reprice/revalidate availability/ETA;
    keep unavailable lines visible until the caller chooses replacement/removal.
    Existing required challenge transition tests.
20. Incomplete/unsupported address correction: never reuse the old address.
    Existing domain and live unsupported-zone tests.
21. "What is in my order?" / running total: read authoritative draft state.
    Distinct from a final checkout; incomplete drafts cannot be confirmed.
22. Final readback: all items/options/notes, fulfillment, branch, fee, total, ETA.
    Exact server text + real playback receipt. Existing release browser evidence
    predates this revision; final new browser checkout was not completed.
23. Yes to the current finished readback: create one mock order. Yes to a size,
    staff offer, unheard readback or changed quote cannot create an order.
    Transaction tests; real media unheard-yes negative check passed.
24. Edit after total / "yes, but...": expire quote, apply correction, new readback.
    Existing revision/epoch, live and readback-interruption tests.
25. Repeated confirm/retry: same stored order, no duplicate creation.
    Idempotency and concurrent-confirmation tests.
26. Confirmed-order change/cancellation: don't change the saved order or promise
    a real refund. New cancellation test preserves the seeded confirmed order.
27. Complaint/human at any point: stop ordering and save mock handoff ticket.
    Existing phase tests and new live complaint test; no actual phone transfer.
28. Offering staff help: record exact proposal. Yes -> ticket; no -> no ticket;
    an intervening topic expires it. New unit and real-model follow-up tests.
29. Allergy/ingredients: no safety guarantees. Honest missing-data + optional
    demo ticket. Real-model case and decline follow-up passed.
30. Hours, payment/refund, tracking, scheduled order/reservation: acknowledge
    missing integration/data. Hours/tracking tested live. Payments/scheduling
    templates are available; not separate new live scenarios in this revision.
31. Interrupt/correct: cancel obsolete work/output; newer epoch wins.
    Existing interruption tests + new recognition-in-flight invalidation test.
32. "Wait / let me finish": quiet, no repeated questions; resume on speech.
    Original-audio regression plus synthetic wait/resume media evidence.
33. "You aren't speaking / I can't hear you": audio check, not mute.
    User-confirmed meaning and approved original-audio replay passed.
34. Noise/empty/unclear speech: no order/control action from failed verification.
    Disagreement guards preserve quantity, negation and price-question evidence;
    ask to repeat when needed. Noise test left the basket unchanged.
35. Repeat an answer / ambiguous "the second one": use current context and clarify
    ambiguous scope; do not reset all fields. Some variants still depend on the
    planner; not an exhaustive paraphrase test.
36. End call: whole explicit command/goodbye, never bare "thanks" or "done".
    State-aware closing, media playout then actual disconnect; headless media
    check passed. Direct End button remains immediate.
37. Model/network/TTS/storage failures: preserve committed state, no fake success,
    no confirmation without playback, bounded goodbye fallback. Unit tests cover
    failures; no sustained network/soak test was performed.
38. Privacy/capability questions: truthful answers. Greeting stays brief and has
    no unsolicited collection announcement. No new legal/compliance claim.

CHALLENGE REQUIREMENTS BEYOND THE CALL
Source: https://app.notion.com/p/Sawt-Challenge-Technical-fe21da866603833d90a1011db9239f2d

The rubric is four equal parts: journey/state design, working implementation,
Arabic model judgment, and safe-change product design. UI polish is not scored.
The supplied unmodified CSV is 144 dishes, 12 categories, 4 branches, 1,728 option
rows. Research in EVALUATION.md and the release-workbench proposal in PRODUCT.md
remain separate deliverables, not implemented production services.
The family-meal add-on scenario is the product-design question; it does not mean
the live demo should start upselling every caller. A <=10-minute demo video and
verification of reviewer access are still submission work, not completed by tests.

REAL RESTAURANT LIMITS
No real POS, payment/refund, dispatch, stock reservation, courier tracking, human
telephone transfer, business hours/allergen feed, reservation or scheduled-order
integration. Hosted demo depends on this computer and its temporary tunnel.
Native Saudi pronunciation, broad microphone/noise conditions, sustained load,
and a fresh full browser checkout remain additional release evidence.
Do not describe this as production-ready or 100% recognition accuracy.

TEST FILES AND REPORTS
tests/test_conversation.py — cancellation, staff-offer semantics, closing failures.
tests/test_recognition.py — audio windows, disagreement, stale verification.
tests/test_voice_routing.py — exact vs negated/mixed call controls.
tests/test_transactions.py — confirmation, revisions, duplicates and playback.
evidence/v2/interaction-eval.json — real planner, 10 scenarios and 2 follow-ups.
evidence/v2/recognition-live-replay.json — approved original price/complaint audio.
evidence/v2/recognition-edge-replay.json — quantities, mixed language, noise.
evidence/v2/recognition-farewell.json — actual received goodbye and disconnect.
RECOGNITION-REPORT.txt — investigation, fixes, evidence and remaining limits.
'''

assert set(WHEN)==set(COPY), 'Every live template must have a reviewable trigger'
parts=[INTRO]
for index,(key,text) in enumerate(COPY.items(),1):
    parts.append(f'{index:02d}. {key}\n    {text}\n    When: {WHEN[key]}\n')
parts.append(COVERAGE)
(ROOT/'CALL-EXPERIENCE.txt').write_text('\n'.join(parts),encoding='utf8')
print(f'Exported {len(COPY)} live templates and 38 request/edge-case entries.')
