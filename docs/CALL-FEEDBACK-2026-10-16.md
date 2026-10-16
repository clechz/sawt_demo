# Call feedback regression — 16 October 2026

Reviewed two substantive calls using saved captions, tool events and persisted state.
Archived recordings were unavailable (Blob storage suspended); generated captions do not prove audible output.

Findings and changes:
- Manakish retrieval was paginated behind eight pizzas sharing its category. Normalize the Arabic plural/singular and prioritize dish-name matches.
- The assistant falsely denied that a CSV/backend existed. Supply explicit implementation facts to both planner and voice instructions; fulfillment remains clearly simulated.
- Routine draft edits unnecessarily switched from the live voice to synthesized exact speech. Keep routine validated draft acknowledgments in the live voice. Exact quote, confirmation, consequential support and sensitive corrections remain guarded.
- Menu responses overloaded the caller with choices/modifiers. Limit recommendations to two and ask only the next missing choice; allow more items before fulfillment.
- Checkout produced a 62 SAR pickup quote, but no browser playback-start event or confirmed order. A second audio stream completed generation without a playback receipt. This is not proof of successful playback. Reuse an audio element unlocked by the start gesture, label autoplay failures as unconfirmed, and record bounded browser failure codes. Autoplay is a suspected cause, not proven from the old logs.

Validation:
- Full Python regression before final diagnostic additions: 1011 passed, 1 skipped.
- JavaScript suite after changes: 67 passed.
- In-app browser (no Chrome): synthetic audio actually reached playing/ended, and only then emitted the completion receipt.
- Existing transaction tests retain incomplete/stale-readback rejection and separate confirmation.
- New regressions cover manakish retrieval, persistent pizza-size correction with live speech, media reuse, autoplay rejection, and diagnostic authorization/state isolation.

Production deployment and real voice acceptance must be verified separately. Browser synthetic-tone playback is not evidence of Saudi pronunciation or full live order completion.
