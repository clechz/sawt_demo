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
- `planner-latency-comparison.json`: three paired serial/batched planner runs
  using identical synthetic wording and the same model. This measures backend
  processing, not speech latency. The public smoke separately measures received
  audible output after saved-state completion.
- `open-model-pins.json`: research checkpoint references, not benchmark results.

Passing these cases is not a held-out reliability score, native accent rating or
production latency/load certification. Human testing exposed stalls despite
earlier passing synthetic runs; DESIGN.md explains the subsequent changes.

- `cloud-deployment.json`: 427 Python checks, 20 real-Postgres contract checks,
  synthetic cloud voice checkout and independent private-storage verification.
  Local servers were stopped; no Chrome used. Playback receipt is simulated.

- `voice-readiness.json`: expanded full cloud-call baseline, failed reruns and fixes. Read its outstanding gates; it does not claim submission readiness.
