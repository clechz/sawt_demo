"""Paid model-led regression with durable state assertions; synthetic text, not voice."""
import asyncio, json, sys, tempfile, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sawt.domain import Engine, Menu
from sawt.transactions import Transactions
from sawt.experience import validate_experience
from sawt.hospitality_runtime import prepare_turn, commit_turn, mark_proposal_presented
from sawt.v2_provider import V2Provider

ROOT=Path(__file__).resolve().parents[1]
async def main():
    report={'scope':'real planner, synthetic text, persisted SQLite; playback simulated, not audio proof','cases':[],'passed':False}
    provider=V2Provider(voice='ash');engine=Engine(Menu(ROOT/'data/restaurant-menu-complex.csv'))
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            tx=Transactions(Path(directory)/'calls.db',engine)
            async def case(name,scenario,steps):
                sid,_=tx.create(experience=validate_experience('ash',scenario,conversation_mode='model_led'))
                result={'name':name,'turns':[],'passed':False};report['cases'].append(result)
                try:
                    for i,(text,check) in enumerate(steps):
                        row=tx.load(sid);start=time.monotonic()
                        p=await prepare_turn(engine,provider,row,text,conversation_mode='model_led')
                        await commit_turn(tx,sid,str(i),p)
                        s=tx.load(sid)['state'];view=engine.view(s)
                        result['turns'].append({'input':text,'reply':p.reply,'seconds':round(time.monotonic()-start,2),'tools':[x['tool'] for x in p.operations]})
                        assert check(s,view), 'Saved state did not match expected result at turn '+str(i+1)
                        # Explicitly simulated hearing for TEXT-only confirmation checks.
                        if s.get('quote'):
                            rid=tx.prepare_audio(sid,s['quote']['token'],.001)
                            tx.playback(sid,rid,'started');await asyncio.sleep(.01);tx.playback(sid,rid,'completed',.001)
                        pending=s.get('hospitality',{}).get('pending_resolution')
                        if pending:mark_proposal_presented(tx,sid,pending['id'],row['epoch'])
                    result['passed']=True
                except Exception as e:result['error']=str(e)[:300]
                print(json.dumps(result,ensure_ascii=False),flush=True)
            await case('nonlinear_order','new_order',[
                ('أبي ٢ شاورما دجاج ساندوتش بخبز صاج بدون حار وبدون ثوم، ومعها شاورما لحم ساندوتش صاج حار. توصيل للرياض حي النرجس شارع الملك خالد مبنى ١٥.',lambda s,v: len(s['basket'])==2 and s['basket'][0]['quantity']==2 and s['service']=='delivery' and s['branch']=='ruh_narjis'),
                ('هذا كل طلبي، اقرأ الملخص.',lambda s,v:bool(s['quote']) and v['total']==7300),
                ('لا احذف شاورما اللحم من الطلب وخلي الدجاج ثلاثة بدل اثنين.',lambda s,v:len(s['basket'])==1 and s['basket'][0]['quantity']==3 and s['basket'][0]['item_id']=='sandwiches_07' and not s['order_id'] and v['total']==6900),
                ('بدل التوصيل استلام من فرع الروضة بجدة.',lambda s,v:s['service']=='pickup' and s['location'] is None and s['branch']=='jed_rawdah' and v['delivery_fee']==0),
                ('خلي الدجاج حار والباقي نفسه. اقرأ الملخص من جديد.',lambda s,v:s['basket'][0]['options']['spice_level']==['hot'] and bool(s['quote']) and v['total']==5400),
                ('نعم اعتمد الطلب.',lambda s,v:bool(s['order_id']) and v['total']==5400),
                ('نعم اعتمد الطلب.',lambda s,v:bool(s['order_id']) and len(s['hospitality']['orders'])==1),
            ])
            await case('refund_missing_item','missing_item',[
                ('طلبي S-DEMO7001 وصل ناقص الشكشوكة، أبي استرجاع قيمتها.',lambda s,v:bool(s['hospitality']['cases']) and bool(s['hospitality']['pending_resolution']) and not s['hospitality']['ledger']),
                ('نعم',lambda s,v:len(s['hospitality']['ledger'])==1 and s['hospitality']['ledger'][0]['amount_halalas']==3000),
                ('رجع قيمة نفس الشكشوكة مرة ثانية.',lambda s,v:len(s['hospitality']['ledger'])==1),
            ])
            await case('unknown_and_staff','new_order',[
                ('وين طلبي S-UNKNOWN؟',lambda s,v:not s['hospitality']['orders'] and not s['basket']),
                ('عندي شكوى أبي أكلم مسؤول.',lambda s,v:bool(s['hospitality']['cases']) and bool(s['hospitality']['pending_resolution'])),
                ('لا شكراً',lambda s,v:not s['hospitality']['pending_resolution'] and not s['hospitality']['ledger']),
            ])
            report['passed']=all(c['passed'] for c in report['cases'])
    finally:
        await provider.aclose()
        (ROOT/'runtime/challenge-planner.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    assert report['passed'], 'Real-model scenario failed; retained in runtime/challenge-planner.json'
if __name__=='__main__':asyncio.run(main())
