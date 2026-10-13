// Only committed orders qualify; quotes and spoken claims never create receipts.
export function confirmedReceipt(state){
 const order=state.hospitality?.orders?.[state.order_id];
 if(!state.order_id||!order||order.source!=='confirmed_simulation')return null;
 const fulfillment=order.fulfillment||state;
 return {id:order.id,items:order.items,total:order.total_halalas,
  service:fulfillment.service,branch:fulfillment.branch?.name,address:fulfillment.location?.address};
}
export function renderFinalReceipt(root,state){
 const panel=root.getElementById('final-receipt');
 if(!panel)return;
 const receipt=confirmedReceipt(state);
 if(!receipt){panel.hidden=true;panel.replaceChildren();delete panel.dataset.signature;return;}
 const signature=JSON.stringify(receipt);
 if(panel.dataset.signature===signature)return;
 panel.dataset.signature=signature;
 const line=(tag,text)=>{const el=root.createElement(tag);el.textContent=text;return el;};
 const nodes=[line('h2',`طلبك ${receipt.id}`)];
 for(const item of receipt.items){
  nodes.push(line('p',`${item.quantity} × ${item.name}`));
  const options=[...(item.option_names||[]),item.notes].filter(Boolean);
  if(options.length){const el=line('p',options.join(' · '));el.className='receipt-options';nodes.push(el);}
 }
 nodes.push(line('strong',`${new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(receipt.total/100)} ر.س`));
 nodes.push(line('p',[receipt.service==='pickup'?'استلام':'توصيل',receipt.branch,receipt.service==='delivery'?receipt.address:null].filter(Boolean).join(' · ')));
 panel.replaceChildren(...nodes);panel.hidden=false;
}
