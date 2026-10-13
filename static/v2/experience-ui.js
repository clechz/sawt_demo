// No environment mutation, provider key, free-text prompt, or voice-changing call restart.
const VOICES = new Set(['cedar', 'ash', 'marin']);
const BRIEFS = {
 new_order:'اطلب أو اسأل بطريقتك.',
 late_delivery:'طلبك S-DEMO7001 تأخر. اسأل عنه أو قدم شكوى.',
 missing_item:'طلبك S-DEMO7001 وصل، لكن الشكشوكة ناقصة.',
 wrong_item:'طلبك S-DEMO7001 وصل، لكن الصنف غير المطلوب.'
};
export function selectedExperience(voice,scenario,consent){
 if(!VOICES.has(voice)||!Object.hasOwn(BRIEFS,scenario))throw new Error('اختيار غير متاح.');
 return {voice,scenario,recording_consent:consent===true,experience_version:'v3',conversation_mode:'model_led'};
}
export function createExperienceControls(root){
 const voice=root.getElementById('voice-choice'),scenario=root.getElementById('scenario-choice');
 const consent=root.getElementById('experience-consent');
 try{const saved=localStorage.getItem('sawt-preferred-voice');if(VOICES.has(saved))voice.value=saved;}catch{}
 const update=()=>{
  root.getElementById('voice-current').textContent=voice.value[0].toUpperCase()+voice.value.slice(1);
  root.getElementById('scenario-brief').textContent=BRIEFS[scenario.value];
  try{localStorage.setItem('sawt-preferred-voice',voice.value);}catch{}
 };
 voice.addEventListener('change',update);scenario.addEventListener('change',update);update();
 return {
  value:()=>selectedExperience(voice.value,scenario.value,consent.checked),
  setBusy:busy=>{voice.disabled=scenario.disabled=consent.disabled=busy;
   root.getElementById('voice-change-note').textContent=busy?'الصوت ثابت للمكالمة الحالية. غيّره بعد ما تنهيها.':'اختر الصوت قبل المكالمة. تقدر تغيّره بعد ما تنهيها.';}
 };
}
const statusText={accepted:'تم استلام الطلب',out_for_delivery:'الطلب مع المندوب',delivered:'تم التوصيل',cancelled:'الطلب ملغي',open:'البلاغ مفتوح',resolved:'تم حل البلاغ',review_requested:'بانتظار المراجعة'};
const money=value=>new Intl.NumberFormat('ar-SA',{style:'currency',currency:'SAR'}).format(value/100);
export function renderSupport(root,h){
 const panel=root.getElementById('support-result');
 if(!panel)return;
 if(!h){panel.hidden=true;panel.replaceChildren();delete panel.dataset.signature;return;}
 const signature=JSON.stringify(h);if(panel.dataset.signature===signature)return;panel.dataset.signature=signature;
 const nodes=[];const line=text=>{const el=root.createElement('p');el.textContent=text;nodes.push(el);};
 for(const order of Object.values(h.orders||{})){
  line(`${order.id} · ${statusText[order.status]||order.status}`);
  if(order.status==='out_for_delivery')line(`الوصول المتوقع خلال ${order.eta_minutes} دقائق`);
  if(order.refunded_halalas)line(`المبلغ المسترجع: ${money(order.refunded_halalas)}`);
 }
 for(const item of h.cases||[]){line(`${item.id} · ${statusText[item.status]||item.status}`);if(item.resolution)line(item.resolution.reply);}
 panel.replaceChildren(...nodes);panel.hidden=nodes.length===0;
}
