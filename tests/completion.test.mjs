import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {receiptModel,createCompletionView} from '../static/v2/completion.js';
const line={name:'مضغوط لحم',quantity:3,line_total:13500,option_names:['فردي','رز بسمتي'],notes:'بدون صوص'};
const state=()=>({order_id:'S-123',basket:[line],service:'pickup',branch:{name:'النرجس'},location:null,total:13500,delivery_fee:0});
function rootFixture(){
 const classes=new Set();const element=tag=>({tag,hidden:true,dataset:{},children:[],setAttribute(k,v){this[k]=v;},append(...n){this.children.push(...n);},replaceChildren(...n){this.children=n;this.renders=(this.renders||0)+1;}});
 const panel=element('section');return {panel,classes,createElement:element,getElementById:()=>panel,body:{classList:{add:c=>classes.add(c),remove:c=>classes.delete(c)}}};
}
test('a draft, a played quote and a spoken claim cannot show success without a saved order ID',()=>{
 for(const input of [null,{}, {...state(),order_id:null,quote:{presented:true}}, {reply:'تم تأكيد طلبك'}])assert.equal(receiptModel(input),null);
});
test('receipt shows saved order number, exact quantities, options and server-calculated total',()=>{
 const v=receiptModel(state());assert.equal(v.id,'S-123');assert.equal(v.items[0].quantity,3);assert.equal(v.total,13500);assert.deepEqual(v.items[0].option_names,['فردي','رز بسمتي']);
});
test('confirmed snapshot wins over changed draft and includes actual cancellation/refund state',()=>{
 const s=state();s.hospitality={orders:{'S-123':{id:'S-123',items:[line],total_halalas:13500,status:'cancelled',refunded_halalas:13500}}};s.basket=[];s.total=0;
 const v=receiptModel(s);assert.equal(v.total,13500);assert.equal(v.items.length,1);assert.equal(v.cancelled,true);assert.equal(v.refunded,13500);
});
test('another order record cannot replace the current receipt',()=>{
 const s=state();s.hospitality={orders:{'S-123':{id:'different',total_halalas:1}}};assert.equal(receiptModel(s).total,13500);
});
test('confirmed fulfillment snapshot cannot change with later draft fields',()=>{
 const s=state();s.hospitality={orders:{'S-123':{id:'S-123',items:[line],total_halalas:13500,fulfillment:{service:'pickup',branch:{name:'النرجس'},location:null,delivery_fee:0}}}};
 s.service='delivery';s.branch={name:'الروضة'};s.location={address:'different'};
 assert.equal(receiptModel(s).service,'pickup');assert.equal(receiptModel(s).branch,'النرجس');assert.equal(receiptModel(s).address,'');
});
test('delivery includes the actual saved address and fee; pickup does not reuse it',()=>{
 const s={...state(),service:'delivery',location:{address:'شارع الملك، مبنى ٣'},delivery_fee:1500,total:15000};
 assert.equal(receiptModel(s).address,'شارع الملك، مبنى ٣');assert.equal(receiptModel(s).deliveryFee,1500);
 s.service='pickup';assert.equal(receiptModel(s).deliveryFee,0);
});
test('unchanged polls do not rebuild the receipt; hangup does not erase it; explicit reset clears it',()=>{
 const root=rootFixture(),view=createCompletionView(root);assert.equal(view.render(state()),true);
 assert.equal(root.panel.renders,1);view.render(state());assert.equal(root.panel.renders,1);
 assert.equal(root.panel.hidden,false);view.render(null);assert.equal(root.panel.hidden,false);
 view.reset();assert.equal(root.panel.hidden,true);assert.equal(root.classes.has('has-completion'),false);
});
test('caller-controlled receipt strings remain text nodes, not injected HTML',()=>{
 const root=rootFixture(),view=createCompletionView(root);const s=state();s.basket=[{...line,name:'<img src=x onerror=alert(1)>'}];
 view.render(s);const text=[];function walk(n){if(n.textContent)text.push(n.textContent);assert.equal(n.innerHTML,undefined);for(const c of n.children||[])if(typeof c==='object')walk(c);}
 walk(root.panel);assert.ok(text.includes('3 × <img src=x onerror=alert(1)>'));
});

test('saved customer name appears in receipt and survives changed draft and hangup',()=>{
 const root=rootFixture(),view=createCompletionView(root),s=state();
 s.customer_name='محمد';s.hospitality={orders:{'S-123':{id:'S-123',customer_name:'عبدالله',items:[line],total_halalas:13500}}};
 assert.equal(receiptModel(s).customerName,'عبدالله');
 view.render(s);view.render(null);
 const text=[];function walk(n){if(n.textContent)text.push(n.textContent);for(const c of n.children||[])walk(c);}
 walk(root.panel);assert.ok(text.includes('باسم عبدالله'));assert.equal(root.panel.hidden,false);
});

test('real Arabic call final state renders the confirmed receipt and keeps it after hangup',()=>{
 const evidence=JSON.parse(readFileSync(new URL('../evidence/v3/cedar-order-ending.json',import.meta.url),'utf8'));
 assert.equal(evidence.passed,true);
 const s=evidence.final_state,receipt=receiptModel(s),root=rootFixture(),view=createCompletionView(root);
 assert.equal(receipt.id,evidence.order_id);assert.equal(receipt.customerName,'عبدالله');
 assert.equal(receipt.total,5400);assert.equal(receipt.items.length,1);assert.equal(receipt.items[0].quantity,3);
 assert.equal(receipt.items[0].item_id,'sandwiches_07');assert.equal(receipt.service,'pickup');
 assert.match(receipt.branch,/الروضة/);assert.deepEqual(receipt.items[0].options.spice_level,['hot']);
 view.render(s);view.render(null);
 const text=[];function walk(n){if(n.textContent)text.push(n.textContent);for(const c of n.children||[])walk(c);}
 walk(root.panel);assert.ok(text.includes('باسم عبدالله'));assert.ok(text.includes('54 ر.س'));
 assert.ok(text.some(x=>x.includes(evidence.order_id)));assert.equal(root.panel.hidden,false);
});


test('confirmed title and saved ETA are minimal and survive draft changes',()=>{
 const s=state(),root=rootFixture(),view=createCompletionView(root);
 s.eta_minutes=999;s.hospitality={orders:{'S-123':{id:'S-123',items:[line],total_halalas:13500,eta_minutes:20,fulfillment:{service:'pickup',branch:{name:'النرجس'}}}}};
 view.render(s);const text=[];function walk(n){if(n.textContent)text.push(n.textContent);for(const c of n.children||[])walk(c);}walk(root.panel);
 assert.ok(text.includes('تم تأكيد طلبك'));assert.ok(text.includes('S-123'));
 assert.ok(text.some(t=>t.includes('20 دقيقة')));assert.ok(!text.some(t=>t.includes('999')));
});
