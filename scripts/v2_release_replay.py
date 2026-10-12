"""Paid planner acceptance tests using real-call wording. Isolated DB; simulated playback."""
import asyncio
import argparse
import json
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sawt import v2_runtime as runtime
from sawt.transactions import Transactions


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=runtime.ROOT/'evidence/v2/release-live-replay.json')
    parser.add_argument('--only-address',action='store_true')
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    runtime.tx=Transactions(runtime.ROOT/'runtime'/f'release-replay-{uuid.uuid4().hex}.sqlite3',runtime.engine)
    report={'kind':'live_planner_acceptance','playback':'SIMULATED; browser audio tested separately','scenarios':[]}
    async def scenario(name, fn):
        sid,_=runtime.tx.create();record={'name':name,'turns':[]};report['scenarios'].append(record)
        async def turn(text):
            epoch=runtime.tx.interrupt(sid,invalidate_quote=False)
            start=time.perf_counter()
            reply=await runtime.delegate(sid,text,uuid.uuid4().hex,epoch)
            record['turns'].append({'input':text,'ms':round((time.perf_counter()-start)*1000),**reply})
            print(json.dumps({'scenario':name,'turn':len(record['turns']),'input':text,'reply':reply['reply'],'basket':[(x['item_id'],x['quantity'],x['options']) for x in reply['state']['basket']]},ensure_ascii=False),flush=True)
            return reply['state']
        try:
            await fn(sid,turn)
            record['passed']=True
        except Exception as exc:
            record['passed']=False;record['error']=repr(exc)
            print(name+' FAIL '+repr(exc),flush=True)
        finally:
            runtime.tx.interrupt(sid,close=True)

    def line(state,item):
        matches=[x for x in state['basket'] if x['item_id']==item]
        assert len(matches)==1, f'Expected one line for {item}: {matches}'
        return matches[0]

    async def karak(sid,turn):
        s=await turn('وش أقسام المنيو عندكم؟')
        assert not s['basket'] and s['service'] is None
        s=await turn('أبغى ثلاثة معصوب ملكي خبز أسمر حجم عادي، وتوصيل.')
        assert line(s,'breakfast_06')['options']=={'portion':['regular'],'bread':['brown']}
        s=await turn('ومعها ثلاثة شاي عدني.')
        assert len(s['basket'])==1, 'Unavailable Adani must not silently become karak'
        s=await turn('ماشي كرك، عطني كرك بدال العدني.')
        assert line(s,'beverages_09')['quantity']==3
        s=await turn('وشو كرك ثلج؟ تستهبل انت، الكرك حار.')
        assert not s['order_id']
        assert s['pending_choice'] and s['pending_choice']['group_id']=='ice' and s['pending_choice']['option_id']=='none', 'The ice proposal must be stored before asking yes/no'
        s=await turn('أيوه')
        assert line(s,'beverages_09')['options'].get('ice')==['none'], 'Yes must resolve the exact ice proposal'
        s=await turn('بدون ثلج، الحجم كبير وخلي سكر وسط.')
        assert line(s,'beverages_09')['options'].get('size')==['large'], 'Save size before clarifying sugar'
        assert line(s,'beverages_09')['options'].get('ice')==['none']
        assert s['pending_choice'] and s['pending_choice']['group_id']=='sweetness' and s['pending_choice']['option_id']=='half', 'Medium sugar must be clarified once'
        s=await turn('أيوه')
        assert line(s,'beverages_09')['options']['sweetness']==['half']
        assert s['order_id'] is None
        s=await turn('لا الشاي واحد بس، المعصوب خله ثلاثة.')
        assert line(s,'beverages_09')['quantity']==1 and line(s,'breakfast_06')['quantity']==3
        s=await turn('يا بويا المرة المليار تعيد لي، بدون ثلج و سكر نص، كمل.')
        assert line(s,'beverages_09')['options']=={'size':['large'],'ice':['none'],'sweetness':['half']}
        s=await turn('الرياض حي النرجس شارع الاختبار مبنى ١٢، العنوان تجريبي.')
        assert s['location'] and not s['issues']
        s=await turn('خلص هذا طلبي، اقرأ الملخص.')
        assert s['quote'] and not s['quote']['presented'] and not s['order_id']
        # A pre-playback yes cannot submit even when the planner tries to confirm.
        s=await turn('نعم')
        assert not s['order_id']
        s=await turn('اقرأ لي ملخص الطلب من جديد.')
        assert s['quote']
        receipt=runtime.tx.prepare_audio(sid,s['quote']['token'],.1)
        runtime.tx.playback(sid,receipt,'started');runtime.tx.playback(sid,receipt,'completed',.1)
        s=await turn('نعم')
        assert s['order_id']
        order=s['order_id']
        s=await turn('نعم')
        assert s['order_id']==order
        with runtime.tx.connect() as db:
            assert db.execute('SELECT count(*) FROM placed_orders WHERE session_id=?',(sid,)).fetchone()[0]==1

    async def information(sid,turn):
        s=await turn('هل مضغوط اللحم متوفر بفرع النرجس بالرياض؟ بس أسأل ما أبي أطلب للحين.')
        assert not s['basket'] and s['service'] is None and s['location'] is None, 'Information question cannot choose service'
        s=await turn('عندي حساسية مكسرات، هل تضمن المعصوب آمن؟')
        assert not s['basket'] and not s['order_id']
        response=runtime.tx.load(sid)['state']['history'][-1]['content']
        assert any(x in response for x in ['معلومات','أضمن','بيانات','موظف','سلام']), response

    async def corrections(sid,turn):
        s=await turn('أبي معصوب ملكي صغير بخبز أسمر، استلام فرع العليا بالرياض.')
        item=line(s,'breakfast_06')
        assert not item['options'].get('portion'), 'Small is unavailable; do not map it to regular'
        assert item['options'].get('bread')==['brown']
        s=await turn('حجم عادي عادي')
        assert line(s,'breakfast_06')['options']['portion']==['regular']
        s=await turn('خلها اثنين واقرأ الطلب.')
        assert line(s,'breakfast_06')['quantity']==2 and s['quote']
        s=await turn('نعم بس خله واحد بدل اثنين')
        assert not s['order_id'] and line(s,'breakfast_06')['quantity']==1
        s=await turn('غيرها توصيل للطائف حي الحلقة شارع تجريبي واحد')
        assert not s['location'] and s['issues'] and not s['order_id']
        s=await turn('طيب رجعها استلام من فرع العليا بالرياض واقرأ ملخص الطلب')
        assert s['service']=='pickup' and s['delivery_fee']==0 and s['quote']

    async def partial_address(sid,turn):
        s=await turn('أبي شكشوكة عادي خبز صاج، توصيل.')
        assert line(s,'breakfast_01')['options']=={'portion':['regular'],'bread':['saj']}
        s=await turn('الرياض')
        assert s['delivery_details']['city']=='الرياض' and not s['location']
        assert runtime.tx.load(sid)['state']['history'][-1]['content']=='بأي حي؟'
        s=await turn('النرجس')
        assert s['delivery_details']['zone']=='النرجس' and not s['location']
        assert runtime.tx.load(sid)['state']['history'][-1]['content']=='واسم الشارع ورقم المبنى؟'
        s=await turn('شارع الاختبار')
        assert s['delivery_details']['street'] and not s['location']
        assert runtime.tx.load(sid)['state']['history'][-1]['content']=='ورقم المبنى؟'
        s=await turn('مبنى اثنا عشر')
        assert s['location'] and not s['issues'] and not s['order_id']
        s=await turn('خلاص')
        assert s['quote'] and not s['order_id']

    try:
        if not args.only_address:
            await scenario('human_karak_loop',karak)
            await scenario('information_and_allergens',information)
            await scenario('unavailable_size_and_corrections',corrections)
        await scenario('incremental_address',partial_address)
    finally:
        await runtime.provider.aclose()
        report['passed']=all(x.get('passed') for x in report['scenarios'])
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    raise SystemExit(0 if report['passed'] else 1)

asyncio.run(main())
