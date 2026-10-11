# Recording guide — target 9 minutes 30 seconds

Use fictional addresses. Keep the state/tool panel visible. Check the microphone and assistant audio are included in the recording before starting. Do not show `.env` or provider dashboards with credentials.

| Time | Show / explain |
|---|---|
| 0:00–0:25 | Local app, AI voice disclosure, 144 menu items / 4 branches, mock order scope |
| 0:25–2:40 | Real Arabic microphone order; options; delivery address; change to pickup; edit quantity after total; fresh readback; explicit confirmation; audible order ID |
| 2:40–3:30 | New conversation: location change to unavailable branch or complaint/handoff; show correct state |
| 3:30–4:40 | Architecture diagram; deterministic prices, revision invalidation, readback acknowledgment, atomic writes/idempotency, menu retrieval and bounded history |
| 4:40–6:50 | STT, LLM, TTS open-weight choices; exact release/license; source evidence; hardware and latency estimates labelled unmeasured; proposed metrics and pass criteria |
| 6:50–8:50 | Product request: one family-meal add-on; versioned policy, regression comparison, review, canary, monitoring and rollback; show wireframe |
| 8:50–9:30 | Actual test results and limitations; where to run and read documentation |

Suggested Arabic journey (answer any required clarifications naturally):

1. «السلام عليكم، أبي توصيل للرياض حي النرجس شارع التجربة مبنى ١٢.»
2. «أبي شكشوكة، حجم كبير، مع تميس، بدون إضافات، عدد ٢.»
3. «هذا كل الطلب، عطني الملخص.»
4. After hearing the total: «غيرت رأيي، أبي استلام من فرع النرجس.»
5. «خلها وحدة بس.»
6. «خلصت، عطني ملخص الطلب.»
7. Let the full readback finish, then: «اعتمد الطلب.»

For availability: Shakshuka (`breakfast_01`) is unavailable in Olaya and available in Narjis in the supplied fixture. Start delivery to Narjis, add it, then change to Olaya. Show the unavailable line and blocked checkout. Resolve with pickup at Narjis or remove/replace it.

For the research explanation, say: "These are published model results and proposed test gates. I have not benchmarked these open weights locally. The running demo uses hosted models." Quote the actual live-test count only after running it.

## Submission checklist

- [ ] GitHub repository is accessible to the reviewer.
- [ ] README setup runs in a fresh environment.
- [ ] A microphone-driven Arabic order has been completed and heard.
- [ ] Non-linear journey and recalculation shown.
- [ ] Automated and live test results reported separately.
- [ ] EVALUATION.md sources/versions/licenses reviewed.
- [ ] PRODUCT.md flow/wireframe included.
- [ ] Video ≤10 minutes, with intelligible input/output audio.
- [ ] Video link tested with intended reviewer access.

The brief's delivery destination is `basim@sawt.sa`, cc `careers@sawt.sa`, subject `Sawt Challenge — {Your Name}`. Include repository link, video link and the completed checklist. This file is a preparation aid; no email has been sent and no video link is claimed.
