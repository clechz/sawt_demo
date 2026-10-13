// Display server-calculated amounts; order changes still happen through voice.
const money=new Intl.NumberFormat('en-US',{maximumFractionDigits:2});
const price=value=>`${money.format(value/100)} ر.س`;
const node=(tag,className,text)=>{const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=text;return el;};

export function createOrderView(root=document){
 const $=id=>root.getElementById(id);
 let previous='';
 return state=>{
  // Polling an unchanged basket should not replace focused or scrolling content.
  const signature=JSON.stringify([state.basket,state.service,state.branch,state.location,state.subtotal,state.delivery_fee,state.total,state.order_id,state.handoff,state.hospitality?.orders?.[state.order_id]?.status,state.issues,!!state.quote?.presented]);
  if(signature===previous)return;previous=signature;
  const count=state.basket.reduce((sum,line)=>sum+line.quantity,0);
  const missing=state.basket.some(line=>line.missing.length);
  const confirmed=!!state.order_id;
  const reviewed=!!state.quote?.presented;
  const cancelled=state.hospitality?.orders?.[state.order_id]?.status==='cancelled';
  const badge=cancelled?'تم الإلغاء':confirmed?'تم التأكيد':missing?'باقي تفاصيل':reviewed?'بانتظار تأكيدك':'مسودة';
  $('order-button').hidden=!count&&!confirmed;
  $('total').textContent=price(state.total);
  $('order-button').dataset.confirmed=String(confirmed);
  $('order-badge').textContent=badge;
  $('order-badge').dataset.state=confirmed?'confirmed':missing?'incomplete':reviewed?'reviewed':'draft';
  const lines=[];
  for(const line of state.basket){
   const row=node('article','order-line');
   const quantity=node('span','line-quantity',`${line.quantity} ×`);
   quantity.dir='ltr';
   quantity.setAttribute('aria-label',`الكمية ${line.quantity}`);
   const content=node('div','line-content');
   content.append(node('h3','',line.name));
   const options=[...line.option_names,line.notes].filter(Boolean);
   if(options.length)content.append(node('p','line-options',options.join(' · ')));
   if(line.missing.length)content.append(node('p','line-missing','باقي نختار: '+line.missing.join('، ')));
   row.append(quantity,content,node('bdi','line-price',price(line.line_total)));
   lines.push(row);
  }
  $('basket').replaceChildren(...lines);
  const details=[];
  const detail=(label,value)=>{if(!value)return;const row=node('div','detail-row');row.append(node('dt','',label),node('dd','',value));details.push(row);};
  const service=state.service==='pickup'?'استلام من الفرع':state.service==='delivery'?'توصيل':null;
  detail('نوع الطلب والفرع',[service,state.branch?.name].filter(Boolean).join(' · '));
  if(state.service==='delivery')detail('العنوان',state.location?.address);
  $('order-meta').replaceChildren(...details);
  $('order-meta').hidden=!details.length;
  $('order-delivery').textContent=price(state.delivery_fee);
  $('delivery-row').hidden=state.service!=='delivery';
  $('order-total').textContent=price(state.total);
  $('order-status').textContent=confirmed?`${cancelled?'الطلب ملغي · ':''}${state.experience?.version==='v3'?'رقم الطلب':'رقم الطلب التجريبي'} ${state.order_id}`:state.handoff?'سُجّل طلب التواصل مع موظف كتذكرة تجريبية.':state.issues.join(' ');
  $('order-status').dataset.confirmed=String(confirmed);
  $('order-note').textContent=cancelled?'تم إلغاء طلبك':confirmed?'طلبك محفوظ':missing?'طلبك مسودة · باقي نختار بعض التفاصيل':count?'تقدر تشوف طلبك وتراجعه بأي وقت':'';
 };
}
