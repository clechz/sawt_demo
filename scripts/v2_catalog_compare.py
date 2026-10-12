"""Paired paid menu-retrieval benchmark on identical requests and model."""
import argparse,asyncio,importlib.util,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sawt.agent import Agent
from sawt.domain import Engine,Menu,new_state
from sawt.transactions import StagedEngine
from sawt.v2_provider import V2Provider
ROOT=Path(__file__).resolve().parents[1]

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline-source',type=Path,required=True)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('sawt._catalog_baseline',args.baseline_source)
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    engine=Engine(Menu(ROOT/'data/restaurant-menu-complex.csv'));runs=[]
    for repeat in range(2):
        for text in ['طال عمرك أبغى شاورما.','أبي شكشوكة كبير خبز تميس وتوصيل.','بكم سندويش الشاورما؟']:
            for name,cls in ([('before',baseline.Agent),('after',Agent)] if repeat==0 else [('after',Agent),('before',baseline.Agent)]):
                p=V2Provider();chat=p.chat;requests=[];start=time.perf_counter()
                async def measured(messages,tools):
                    result=await chat(messages,tools);requests.append([c['function']['name'] for c in result.get('tool_calls',[])])
                    return result
                p.chat=measured
                try:
                    state,result=await cls(StagedEngine(engine,check_choices=True),p).turn(new_state(),text)
                    if 'شكشوكة' in text:
                        assert len(state['basket'])==1
                        line=state['basket'][0]
                        assert line['item_id']=='breakfast_01' and line['quantity']==1
                        assert line['options']=={'portion':['large'],'bread':['tamees']} and state['service']=='delivery'
                    else:
                        assert not state['basket'] and not state['service']
                        for word in (['18','22'] if text.startswith('بكم') else ['دجاج','لحم']):assert word in result['reply']
                    assert not state['order_id']
                    row={'version':name,'repeat':repeat,'input':text,'ms':round((time.perf_counter()-start)*1000),'requests':requests,'reply':result['reply'],'passed':True}
                except Exception as exc:row={'version':name,'repeat':repeat,'input':text,'requests':requests,'passed':False,'error':str(exc)}
                finally:await p.aclose()
                runs.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    (ROOT/'runtime/catalog-compare-v11.json').write_text(json.dumps({'runs':runs},ensure_ascii=False,indent=2),encoding='utf8')
    assert all(r['passed'] for r in runs if r['version']=='after')

if __name__=='__main__':asyncio.run(main())
