// Receipt data comes only from authenticated saved order state, never speech.
const money=new Intl.NumberFormat('en-US',{maximumFractionDigits:2});
const price=value=>`${money.format(value/100)} ر.س`;
export function receiptModel(state){
 if(!state?.order_id)return null;
 const saved=state.hospitality?.orders?.[state.order_id];
 const order=saved?.id===state.order_id?saved:null;
 const fulfillment=order?.fulfillment||state;
 return {id:state.order_id,cancelled:order?.status==='cancelled',
  items:order?.items||state.basket||[],total:order?.total_halalas??state.total,
  service:fulfillment.service,branch:fulfillment.branch?.name||'',address:fulfillment.location?.address||'',
  deliveryFee:fulfillment.service==='delivery'?fulfillment.delivery_fee:0,
  refunded:order?.refunded_halalas||0};
}
export function createCompletionView(root=document){
 const panel=root.getElementById('completion');let signature='',orderId=null;
 const el=(tag,cls,text)=>{const n=root.createElement(tag);n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 return {
  reset(){signature='';orderId=null;panel.replaceChildren();panel.hidden=true;root.body.classList.remove('has-completion');},
  render(state){
   const receipt=receiptModel(state);if(!receipt)return false;
   const key=JSON.stringify(receipt);if(key===signature)return true;signature=key;
   if(orderId!==receipt.id&&!globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches){
    root.querySelector?.('.orb-control')?.animate?.([{transform:'scale(1)'},{transform:'scale(1.045)'},{transform:'scale(1)'}],{duration:650,easing:'ease-out'});
   }
   orderId=receipt.id;
   const heading=el('header','receipt-heading');
   const mark=el('span','receipt-mark',receipt.cancelled?'—':'✓');mark.setAttribute('aria-hidden','true');
   const title=el('h2','',receipt.cancelled?'الطلب ملغي':`طلبك ${receipt.id}`);title.id='completion-title';
   const identity=el('p','receipt-number');identity.append('رقم الطلب ',el('bdi','',receipt.id));
   const intro=el('div','');intro.append(title);heading.append(intro);
   const items=el('div','receipt-items');
   for(const line of receipt.items){
    const row=el('article','receipt-line');const description=el('div','');
    description.append(el('p','receipt-item-name',`${line.quantity} × ${line.name}`));
    const options=[...(line.option_names||[]),line.notes].filter(Boolean).join(' · ');
    if(options)description.append(el('p','receipt-options',options));
    row.append(description);items.append(row);
   }
   const fulfillment=el('div','receipt-fulfillment');
   const service=receipt.service==='pickup'?'استلام من الفرع':receipt.service==='delivery'?'توصيل':'';
   fulfillment.append(el('p','',[service,receipt.branch].filter(Boolean).join(' · ')));
   if(receipt.service==='delivery'&&receipt.address)fulfillment.append(el('p','receipt-address',receipt.address));
   const total=el('div','receipt-total');total.append(el('span','','الإجمالي'),el('bdi','',price(receipt.total)));
   const nodes=[heading,items,fulfillment];
   nodes.push(total);
   panel.replaceChildren(...nodes);panel.dataset.cancelled=String(receipt.cancelled);panel.hidden=false;
   root.body.classList.add('has-completion');return true;
  }
 };
}
