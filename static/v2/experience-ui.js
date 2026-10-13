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
// Ash remains fixed; no previous voice preference can override it.
// A deliberate start acknowledges the recording notice beside the button.
// Merely loading the page or reading its settings grants nothing.
export function createExperienceControls(root){
 const notice=root.getElementById('recording-notice');
 if(!notice?.textContent?.trim())throw new Error('Recording notice is missing');
 let busy=false;
 return {
  value:({startRequested=false}={})=>selectedExperience('ash','new_order',startRequested===true&&!busy),
  setBusy:value=>{busy=value===true;}
 };
}

const statusText={accepted:'تم استلام الطلب',out_for_delivery:'الطلب مع المندوب',delivered:'تم التوصيل',cancelled:'الطلب ملغي',open:'البلاغ مفتوح',resolved:'تم حل البلاغ',review_requested:'بانتظار المراجعة'};
const money=value=>new Intl.NumberFormat('ar-SA',{style:'currency',currency:'SAR'}).format(value/100);
export function renderSupport(root,h,currentOrderId){
 const panel=root.getElementById('support-result');
 if(!panel)return;
 if(!h){panel.hidden=true;panel.replaceChildren();delete panel.dataset.signature;return;}
 const signature=JSON.stringify(h);if(panel.dataset.signature===signature)return;panel.dataset.signature=signature;
 const nodes=[];const line=text=>{const el=root.createElement('p');el.textContent=text;nodes.push(el);};
 for(const order of Object.values(h.orders||{})){
  if(order.id===currentOrderId)continue; // Its saved receipt already shows this order.
  line(`${order.id} · ${statusText[order.status]||order.status}`);
  if(order.status==='out_for_delivery')line(`الوصول المتوقع خلال ${order.eta_minutes} دقائق`);
  if(order.refunded_halalas)line(`المبلغ المسترجع: ${money(order.refunded_halalas)}`);
 }
 for(const item of h.cases||[]){line(`${item.id} · ${statusText[item.status]||item.status}`);if(item.resolution)line(item.resolution.reply);}
 panel.replaceChildren(...nodes);panel.hidden=nodes.length===0;
}
