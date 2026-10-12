"""Paired real-planner comparison, same model/input; isolated state, no browser."""
import asyncio,json,time,sys,uuid,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sawt import v2_runtime as rt
from sawt.transactions import Transactions
from sawt.v2_provider import V2Provider

TEXT='أبي ثلاثة معصوب ملكي، حجم عادي وخبز أسمر، ومعها شاي كرك واحد كبير بدون ثلج وسكر وسط، استلام من فرع النرجس بالرياض.'

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--output',type=Path,default=rt.ROOT/'runtime/latency-compare.json');args=parser.parse_args()
    rt.tx=Transactions(rt.ROOT/'runtime'/('latency-'+uuid.uuid4().hex+'.sqlite3'),rt.engine)
    runs=[]
    for repeat in range(args.repeats):
        for batched in ([False,True] if repeat%2==0 else [True,False]):
            sid,_=rt.tx.create();provider=V2Provider(batch_tools=batched);calls=[]
            original=provider.chat
            async def chat(messages,tools):
                started=time.perf_counter();result=await original(messages,tools)
                calls.append({'ms':round((time.perf_counter()-started)*1000),'tools':[c['function']['name'] for c in result.get('tool_calls',[])]})
                return result
            provider.chat=chat;started=time.perf_counter()
            try:
                result=await rt.delegate(sid,TEXT,'benchmark',0,voice_provider=provider)
                state=result['state'];basket={x['item_id']:x for x in state['basket']}
                checks={'items':set(basket)=={'breakfast_06','beverages_09'},'quantities':basket.get('breakfast_06',{}).get('quantity')==3 and basket.get('beverages_09',{}).get('quantity')==1,
                    'pickup_branch':state['service']=='pickup' and state['branch_id']=='ruh_narjis','no_order':not state['order_id'],
                    'sugar_proposal':bool(state['pending_choice'] and state['pending_choice']['group_id']=='sweetness' and state['pending_choice']['option_id']=='half')}
                row={'batched':batched,'repeat':repeat,'ms':round((time.perf_counter()-started)*1000),'requests':calls,'checks':checks,'reply':result['reply'],'passed':all(checks.values())}
            except Exception as exc:row={'batched':batched,'repeat':repeat,'passed':False,'error':str(exc),'requests':calls}
            finally:await provider.aclose();rt.tx.interrupt(sid,close=True)
            runs.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps({'scope':'Planner only; same model, paired sequential development runs; no audio timing','runs':runs},ensure_ascii=False,indent=2),encoding='utf8')
    assert all(r['passed'] for r in runs)

if __name__=='__main__':asyncio.run(main())
