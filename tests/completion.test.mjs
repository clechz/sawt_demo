import test from 'node:test';
import assert from 'node:assert/strict';
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
