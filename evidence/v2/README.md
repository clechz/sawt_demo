# Reviewer evidence

Only synthetic test traces and test results are included here. Human recordings,
private call histories, credentials and local databases are excluded.

- `submission-copy-tests.xml`: complete offline Python result.
- `submission-live-replay.json`: four real-planner journeys; playback receipts
  are simulated by this backend harness.
- `interaction-eval.json`: information, complaints, cancellation and staff-offer
  acceptance/decline with the real planner.
- `submission-voice-edges.json`: earlier real-media synthetic recognition run.
- `latency-fix-edges.json`: real-media synthetic rerun after audio-clock anchoring,
  queued diagnostics, burst invalidation and shorter settlement.
- `private-demo-smoke.json`: HTTPS gateway and real-media synthetic smoke test;
  the temporary URL depends on the development host staying online.
- `open-model-pins.json`: research checkpoint references, not benchmark results.

Passing these cases is not a held-out reliability score, native accent rating or
production latency/load certification. Human testing exposed stalls despite
earlier passing synthetic runs; DESIGN.md explains the subsequent changes.
