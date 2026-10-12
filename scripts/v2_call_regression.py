"""Live planner replay of observed caller failures. Playback is simulated here."""
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
    parser.add_argument('--output', type=Path, default=runtime.ROOT/'evidence/v2/call-regression.json')
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    runtime.tx=Transactions(runtime.ROOT/'runtime'/f'call-regression-{uuid.uuid4().hex}.sqlite3',runtime.engine)
    sid,_=runtime.tx.create();turns=[];stages=[]
    async def turn(text):
        epoch=runtime.tx.interrupt(sid,invalidate_quote=False)
        async def progress(stage,epoch):stages.append({'stage':stage,'epoch':epoch})
        start=time.perf_counter()
        result=await runtime.delegate(sid,text,f'replay-{len(turns)}',epoch,progress=progress)
        turns.append({'input':text,'ms':round((time.perf_counter()-start)*1000),**result})
        print(json.dumps({'turn':len(turns),'reply':result['reply'],'items':[(x['item_id'],x['options']) for x in result['state']['basket']]},ensure_ascii=False),flush=True)
        return result['state']
    report={'kind':'live_gpt_4.1_call_regression','playback':'simulated receipt, not acoustic evidence','turns':turns,'stages':stages}
    try:
        view=await turn('وش أقسام المنيو عندكم؟ اذكر لي الأقسام كلها.')
        assert not view['basket']
        assert any(e['tool']=='list_categories' for e in turns[-1]['events']), 'overview must use the full category catalog'
        view=await turn('أبغى فول وتميس وقلابة، وكثر لي فلفل على القلابة.')
        assert {x['item_id'] for x in view['basket']}=={'breakfast_03'}, 'save the explicit qalaba; ask about ambiguous fool and tamees instead of silently choosing variants'
        assert 'فلفل' in next(x for x in view['basket'] if x['item_id']=='breakfast_03')['notes']
        view=await turn('الفول حجازي والتميس بالعسل. الثلاثة كلهم حجم عادي وخبز أسمر. وأبغى استلام من فرع النرجس بالرياض.')
        assert {x['item_id'] for x in view['basket']}=={'breakfast_02','breakfast_03','breakfast_05'}
        assert view['service']=='pickup' and view['branch_id']=='ruh_narjis'
        assert all(x['options'].get('portion')==['regular'] and x['options'].get('bread')==['brown'] for x in view['basket'])
        line=next(x for x in view['basket'] if x['item_id']=='breakfast_05');line_id=line['line_id']
        view=await turn('بدل التميس بالعسل خله تميس بالجبن، والباقي مثل ما هو.')
        line=next(x for x in view['basket'] if x['item_id']=='breakfast_04')
        assert line['line_id']==line_id and line['options']=={'portion':['regular'],'bread':['brown']}, 'replacement must keep known choices and identity'
        view=await turn('لا رجع التميس بالعسل خبز اسمري، والباقي نفسه.')
        line=next(x for x in view['basket'] if x['item_id']=='breakfast_05')
        assert line['line_id']==line_id and line['options']=={'portion':['regular'],'bread':['brown']}
        assert len(view['basket'])==3 and not view['order_id']
        view=await turn('خلص هذا كل طلبي، اقرأ لي ملخص الطلب.')
        assert view['quote'] and not view['quote']['presented'] and not view['order_id']
        receipt=runtime.tx.prepare_audio(sid,view['quote']['token'],.1)
        runtime.tx.playback(sid,receipt,'started');runtime.tx.playback(sid,receipt,'completed',.1)
        view=await turn('نعم')
        assert view['order_id']
        with runtime.tx.connect() as db:
            assert db.execute('SELECT count(*) FROM placed_orders WHERE session_id=?',(sid,)).fetchone()[0]==1
        report['passed']=True
    except Exception as exc:
        report['passed']=False;report['error']=str(exc)
        raise
    finally:
        await runtime.provider.aclose()
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('Observed-call planner regression PASS')

asyncio.run(main())
