"""Paired paid planner benchmark against a saved previous agent.py; no voice/browser."""
import argparse,asyncio,copy,importlib.util,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sawt.agent import Agent
from sawt.domain import Engine,Menu,new_state
from sawt.transactions import StagedEngine
from sawt.v2_provider import V2Provider
ROOT=Path(__file__).resolve().parents[1]

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-source',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--output',type=Path,default=ROOT/'runtime/planner-roundtrips.json')
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('sawt._benchmark_baseline',args.baseline_source)
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    engine=Engine(Menu(ROOT/'data/restaurant-menu-complex.csv'))
    original=new_state()
    engine.act(original,'set_service',{'service':'pickup'})
    engine.act(original,'set_branch',{'branch_id':'ruh_narjis'})
    engine.act(original,'add_item',{'item_id':'breakfast_01','quantity':1,'options':{'portion':['regular'],'bread':['saj']},'notes':''})
    runs=[]
    for repeat in range(args.repeats):
        for name,cls in ([('before',baseline.Agent),('after',Agent)] if repeat%2==0 else [('after',Agent),('before',baseline.Agent)]):
            p=V2Provider();chat=p.chat;requests=[]
            async def measured(messages,tools):
                result=await chat(messages,tools)
                requests.append([c['function']['name'] for c in result.get('tool_calls',[])])
                return result
            p.chat=measured;start=time.perf_counter()
            try:
                state,result=await cls(StagedEngine(engine,check_choices=True),p).turn(copy.deepcopy(original),'خلها اثنين واقرأ الطلب.')
                view=engine.view(state)
                checks={'quantity':len(state['basket'])==1 and state['basket'][0]['quantity']==2,
                        'options':state['basket'][0]['options']==original['basket'][0]['options'],
                        'total':view['total']==4400,'readback':bool(state['quote']),
                        'not_confirmed':not state['order_id'] and not state['quote']['presented']}
                row={'version':name,'repeat':repeat,'ms':round((time.perf_counter()-start)*1000),'requests':requests,'checks':checks,'passed':all(checks.values())}
            except Exception as exc:row={'version':name,'repeat':repeat,'requests':requests,'passed':False,'error':str(exc)}
            finally:await p.aclose()
            runs.append(row);print(json.dumps(row),flush=True)
    args.output.write_text(json.dumps({'scope':'Same model and correction request; planner only, not end-to-end voice latency','runs':runs},indent=2),encoding='utf8')
    assert all(r['passed'] for r in runs)

if __name__=='__main__':asyncio.run(main())
