# Exact recording script — target 9 minutes

Record your microphone **and system audio**. Use fictional details. Have the running app, README, DESIGN, EVALUATION and PRODUCT tabs ready. Do not show credentials or private recordings. Keep the live interaction at normal speed; wait for actual responses. This is a guide, not a claim that a video has already been recorded.

## 0:00–0:25 — introduction

Show the minimal call screen. Say:

> أنا عبدالله، وهذا تطبيقي لتحدي صوت. الفكرة تجربة بسيطة للعميل، لكن حالة الطلب والحسابات والتأكيد مضبوطة في الخلفية. المنيو هو الملف المعطى: ١٤٤ صنف وأربعة فروع. الطلبات والتحويل للموظف في هذا العرض تجريبية.

## 0:25–3:20 — a real non-linear order

Start the call. Wait for the greeting. Say each line, then let the assistant respond:

1. **«أبي شكشوكة، حجم كبير، مع تميس، عدد اثنين. أبيها توصيل.»**
2. If asked city/neighborhood: **«الرياض، حي النرجس.»**
3. When asked the remaining address: **«شارع التجربة، مبنى اثنا عشر.»**
4. If no readback starts: **«هذا كل الطلب، اقرأ الملخص.»** Let it finish. Expected delivery total: **75 ريال**.
5. **«غيرت رأيي، أبي استلام من فرع النرجس.»** Expected total: **60 ريال**.
6. **«خلها وحدة بس.»** Expected total: **30 ريال**.
7. If needed: **«خلاص، اقرأ الطلب.»** Wait for the whole revised readback, including the confirmation question.
8. **«اعتمد الطلب.»** Open the receipt and show one large Shakshuka with tamees, Narjis pickup, **30 SAR**, and one mock order ID.
9. **«مع السلامة.»** Let the call close.

If a required clarification is asked, answer it naturally; do not talk over the readback. If a price/state is wrong, do not narrate the expected result as if it happened. Stop, preserve the failed call and fix it before recording the final submission.

Narrate after the call:

> غيرت نوع الخدمة والكمية بعد ما سمعنا المجموع. الأصناف والخيارات المحفوظة بقيت، وتغيرت الرسوم والحسابات. التأكيد ما يصير من كلمة نعم لحالها؛ لازم تكون على ملخص الطلب الحالي وبعد اكتمال قراءته.

## 3:20–4:00 — information and escalation

New call:

1. **«بكم سندويش شاورما الدجاج واللحم؟ بس أسأل، ما أبي أطلب.»** Expected starting prices: **18 / 22 SAR**, with no basket created.
2. **«عندي شكوى، أبي أكلم موظف.»** Show the saved mock staff ticket and the honest limitation: no real live transfer.
3. **«مع السلامة.»**

Say:

> مو كل اتصال لازم يتحول لطلب. سؤال السعر ما يضيف صنف، والشكوى تقدر توقف مسار الطلب وتروح لطلب تواصل تجريبي.

## 4:00–5:25 — architecture and context

Show DESIGN.md and its diagram. Say:

> فصلت المحادثة عن صلاحية تغيير الطلب. LiveKit ينقل الصوت، وGPT-Live يدير توقيت المحادثة. طلبات المطعم تمر على تخطيط بأدوات، لكن كود Python هو اللي يتحقق من الخيارات والأسعار والتوفر.
>
> ما بنيت شبكة وكلاء ولا مصنف نوايا إضافي. عندنا مسؤوليتان للنماذج: الصوت، وفهم الطلب واختيار الأدوات. حالة الطلب في النسخة المستضافة محفوظة في Neon Postgres، ومحليًا نستخدم SQLite. الحالة هي المرجع؛ سجل المحادثة يساعد على الفهم فقط.
>
> السياق يحتوي الحالة الحالية وآخر ١٢ رسالة، ونسترجع حتى خمسة أصناف في البحث بدل إرسال المنيو كاملًا. ونرفق خيارات الأصناف الموجودة في السلة عشان التعديل ما يحتاج بحثًا مكررًا. أي تغيير يحدّث رقم نسخة الطلب ويلغي الملخص القديم. وإذا وصل كلام أحدث، نتيجة الشغل القديم ما تقدر تكتب فوقه.
>
> واجهة العميل بسيطة، لكن التأكيد له شروط واضحة: ملخص حالي، اكتمال تشغيله، ثم موافقة صريحة. وقيد في قاعدة البيانات يمنع تكرار نفس الطلب.

Show `data/conversation-copy.json` briefly:

> فصلت العبارات المتكررة عن قواعد العمل. ونقول للعميل التغيير اللي انحفظ فعليًا، ونسأله عن الناقص فقط.

## 5:25–6:50 — model research and evaluation

Show EVALUATION.md. Say:

> النماذج المفتوحة هنا مقترحات بحثية، مو النماذج اللي شغلت العرض عليها، وما أدعي أني قست سرعتها محليًا.
>
> للتعرف على الكلام درست Cohere Transcribe Arabic إصدار يوليو ٢٠٢٦، مع Whisper large-v3 كخط أساس. المهم عندي اللهجة السعودية والكلام المختلط، ودقة الأرقام والنفي، مو WER عام لحاله.
>
> للتخطيط اخترت Qwen3-30B-A3B-Instruct-2507 كمرشح اختبار، وقارنته مع ALLaM. التوازن المطلوب بين العربية، استدعاء الأدوات، الذاكرة والسرعة. أرقام البنشمارك المنشورة ما تعني نجاح طلبات المطاعم.
>
> للصوت، اخترت Chatterbox Multilingual V3 كمرشح اختبار، وقارنته مع XTTS-v2 مع الانتباه لاختلاف الترخيص. التقييم يحتاج سعوديين يقيمون الوضوح والطبيعية وصحة نطق الأصناف، إلى جانب زمن أول صوت مفيد.
>
> خطة الاختبار تفصل جودة الكلام عن صحة الطلب: كميات، نفي، تصحيحات، ضوضاء، تغيير فرع، ومقاطعة الملخص. نجاح الحالات الحالية دليل محدود؛ مو ادعاء أن التعرف مثالي.

Read the exact TTS candidate from EVALUATION.md on screen rather than substituting a model from memory.

## 6:50–8:10 — safe product changes

Show PRODUCT.md workflow and wireframe. Say:

> الجزء المنتجّي هو كيف نخلي فريق العمليات يغير السلوك بأمان. مثلًا: عرض إضافة واحدة مع وجبة عائلية، وعدم تكرار العرض بعد الرفض.
>
> التغيير يصير سياسة لها نسخة وشروط واضحة، مو تعديل مبهم على البرومبت. نحدد وقت العرض، الصنف المناسب والمتوفر، وحالة قبول أو رفض مستقلة عن تعديلات السلة.
>
> نقارن النسخة الجديدة بالحالية على نفس المكالمات والاختبارات. نراجع السعر والتوفر وعدم تكرار العرض، ثم إطلاق محدود ومراقبة وتراجع إذا تدهورت النتائج. لو العميل قبل الإضافة، هذا تعديل للسلة ويحتاج مجموعًا وملخصًا جديدين؛ مو تأكيدًا نهائيًا.
>
> هذا الجزء تصميم مقترح مو خدمة إطلاق مكتملة، والتمييز موضح في المستودع.

## 8:10–9:00 — evidence and close

Show latest test report and README setup. Say:

> المستودع فيه أوامر التشغيل للويندوز ولينكس وماك، مفاتيح الخدمات المطلوبة، الاختبارات، وتصميم النظام. الاختبارات الآلية منفصلة عن اختبارات المزود والصوت الحقيقي؛ وبعض اختبارات الخلفية تحاكي إيصال التشغيل وهذا مو اختبار سماعة المستخدم.
>
> التجارب البشرية كشفت مشكلة توقيت بين النص والصوت، وكتابات تشخيص كانت تعطل حلقة الصوت. وثقت السبب والتعديلات بدل الاكتفاء بأن اختبار الطلب نجح. ما غيرت نموذج الصوت لمجرد ظهور المشكلة.
>
> هذا نموذج تحدي، مو نظام مطعم منشور للإنتاج: ما فيه دفع أو إرسال للمطبخ أو تحويل حقيقي لموظف. الخطوة التالية قياس لهجات وضوضاء وزمن استجابة على مجموعة مستقلة وربط أنظمة المطعم. شكرًا لكم.

Only quote the current test count from the report shown on screen. Do not describe a failed or pending live test as passed. Keep total duration below ten minutes; trim narration rather than speeding up or hiding the real call.

## Submission

- Repository URL with reviewer access and the final commit.
- Video link, tested with intended reviewer permissions, under ten minutes.
- Demo URL: https://sawt-demo.vercel.app. It runs on cloud services independently of the development PC. Share its password privately, not in the public repository.
- The brief lists `basim@sawt.sa`, cc `careers@sawt.sa`, subject `Sawt Challenge — Abdullah`. Confirm the spelling of your full name before sending. No email is sent by this guide.
