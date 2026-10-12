"""Paid backend intent checks. No browser, microphone or playback acknowledgement."""
import asyncio,json,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sawt import v2_runtime as rt
from sawt.transactions import Transactions
from sawt.v2_provider import V2Provider

CASES=[
 ('price_information','بكم سندويش شاورما الدجاج واللحم؟'),
 ('menu_discovery','وش فئات الأكل اللي عندكم؟'),
 ('branch_information','عندكم فرع في جدة؟ أنا بس أسأل، ما أبي أطلب.'),
 ('opening_hours','متى يقفل فرع النرجس اليوم؟'),
 ('allergen_unknown','عندي حساسية سمسم. هل الشكشوكة مضمونة خالية من السمسم؟'),
 ('external_order_tracking','طلبي من أمس رقمه 123، وين وصل المندوب؟'),
 ('complaint','عندي شكوى، أبي أكلم موظف.'),
 ('negated_complaint','ما أبي موظف ولا عندي شكوى، بس بكم سندويش الشاورما؟'),
 ('cancel_draft','الغ طلبي'),
 ('cancel_confirmed','الغ طلبي'),
]

async def main():
    rt.tx=Transactions(rt.ROOT/'runtime'/('interaction-eval-'+uuid.uuid4().hex+'.sqlite3'),rt.engine)
    gate=asyncio.Semaphore(3)
    async def run(name,text):
        async with gate:
            sid,_=rt.tx.create();provider=V2Provider()
            try:
                if name.startswith('cancel'):
                    state=rt.tx.load(sid)['state']
                    rt.engine.act(state,'set_service',{'service':'pickup'})
                    rt.engine.act(state,'set_branch',{'branch_id':'ruh_narjis'})
                    rt.engine.act(state,'add_item',{'item_id':'breakfast_05','quantity':1,'options':{'portion':['regular'],'bread':['brown']}})
                    if name=='cancel_confirmed':state['order_id']='S-SEEDED-TEST'
                    rt.tx.commit_bundle(sid,'seed',0,0,state,[],response={})
                reply=await rt.delegate(sid,text,'turn',0,voice_provider=provider)
                state=rt.tx.load(sid)['state'];tools=[e['tool'] for e in reply['events']]
                if name=='cancel_draft':
                    assert not state['basket'] and not state['service'] and not rt.tx.load(sid)['closed']
                    assert tools==['cancel_draft']
                elif name=='cancel_confirmed':
                    assert state['order_id']=='S-SEEDED-TEST' and len(state['basket'])==1 and not tools
                elif name=='complaint':
                    assert state['handoff'] and not state['order_id'] and tools==['handoff']
                else:
                    assert not state['basket'] and state['service'] is None and state['branch'] is None and not state['order_id'] and not state['handoff']
                    assert all(t in ('search_menu','get_item','list_categories','list_branches','get_state','offer_handoff') for t in tools)
                if name=='price_information':assert '18' in reply['reply'] and '22' in reply['reply'] and 'بيتزا' not in reply['reply']
                if name=='menu_discovery':assert 'list_categories' in tools
                if name=='branch_information':assert 'list_branches' in tools and 'جدة' in reply['reply']
                if name in ('opening_hours','allergen_unknown','external_order_tracking'):
                    assert state['pending_handoff'] and 'مو مفعّل' in reply['reply']
                result={'name':name,'passed':True,'text':text,'reply':reply['reply'],'tools':tools,'state':reply['state']}
                if name in ('opening_hours','allergen_unknown'):
                    answer='نعم' if name=='opening_hours' else 'لا شكرا'
                    follow=await rt.delegate(sid,answer,'followup',rt.tx.load(sid)['epoch'],voice_provider=provider)
                    assert bool(follow['state']['handoff'])==(answer=='نعم') and not follow['state']['order_id']
                    assert follow['state']['pending_handoff'] is None
                    result['followup']={'text':answer,'reply':follow['reply'],'tools':[e['tool'] for e in follow['events']]}
            except Exception as exc:result={'name':name,'passed':False,'error':str(exc)}
            finally:await provider.aclose()
            print(json.dumps({k:v for k,v in result.items() if k!='state'},ensure_ascii=False),flush=True)
            return result
    results=await asyncio.gather(*(run(*case) for case in CASES))
    report={'passed':all(x['passed'] for x in results),'scope':'Real planner and transactions, seeded cancellation states; no audio or browser. Unknown-fact wording requires manual inspection of saved replies.','cases':results}
    (rt.ROOT/'evidence/v2/interaction-eval.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    assert report['passed'], 'Interaction check failed'

if __name__=='__main__':asyncio.run(main())
