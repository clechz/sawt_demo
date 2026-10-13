import test from 'node:test';
import assert from 'node:assert/strict';
import {confirmedReceipt,renderFinalReceipt} from '../static/v2/final-receipt.js';

const state={order_id:'S-123',service:'pickup',branch:{name:'النرجس'},
 basket:[{name:'wrong draft',quantity:20}],total:999999,
 hospitality:{orders:{'S-123':{id:'S-123',source:'confirmed_simulation',
 items:[{name:'شكشوكة',quantity:2,option_names:['كبير','تميس'],notes:''}],total_halalas:6000}}}};
test('receipt uses only committed order items and total, never draft or quote',()=>{
 assert.equal(confirmedReceipt({quote:{presented:true}}),null);
 assert.equal(confirmedReceipt({order_id:'invented'}),null);
 const receipt=confirmedReceipt(state);
 assert.equal(receipt.total,6000);assert.equal(receipt.items[0].quantity,2);
 assert.equal(receipt.items[0].name,'شكشوكة');
});
test('minimal receipt remains visible on unchanged polls and only clears on a new call',()=>{
 const panel={hidden:true,dataset:{},nodes:[],replaceChildren(...nodes){this.nodes=nodes;}};
 const root={getElementById:()=>panel,createElement:tag=>({tag})};
 renderFinalReceipt(root,state);assert.equal(panel.hidden,false);
 assert.deepEqual(panel.nodes.map(n=>n.textContent),['طلبك S-123','2 × شكشوكة','كبير · تميس','60 ر.س','استلام · النرجس']);
 const nodes=panel.nodes;renderFinalReceipt(root,state);assert.equal(panel.nodes,nodes);
 // Hangup changes lifecycle outside the receipt, not the confirmed state.
 renderFinalReceipt(root,{...state,closed:true});assert.equal(panel.nodes,nodes);
 renderFinalReceipt(root,{});assert.equal(panel.hidden,true);assert.equal(panel.nodes.length,0);
});
