"""Live GPT-4.1 regression over V2 transactions. Playback is SIMULATED here."""
import asyncio
import json
import sys
import time
import uuid
import argparse
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.live_eval import CASES, verify
from sawt import v2_runtime as runtime
from sawt.transactions import Transactions

EXTRA=[
 ('unavailable_bread_no_defaults',[
  'أبي استلام من فرع النرجس بالرياض. وجبة شاورما لحم واحدة، خلي الخبز بيتا. لا لا معليش، خله خبز بر.'
 ],{'quantity':1,'item':'sandwiches_08','order':False}),
 ('critical_nonlinear',[
  'أبي توصيل للرياض حي النرجس شارع التجربة مبنى ١٢. دجاج مسحب وجبتين حجم عادي مع بطاطس وبدون حار وصوص ثوم.',
  'الملقا مو النرجس، شارع التجربة مبنى ١٢.',
  'بدل التوصيل استلام من فرع الملقا.',
  'خل الوجبة الثانية بدون صوص، والأولى مثل ما هي. هذا كل طلبي.',
  'عطني ملخص الطلب.',
  'تمام اعتمد، لا لحظة أبي أضيف مشروب. لا تعتمد الحين.',
 ],{'service':'pickup','branch_id':'ruh_malqa','order':False,'fee':0}),
 ('two_distinct_meals',[
  'أبي استلام من فرع النرجس. دجاج مسحب وجبتين، الأولى كبير والثانية عادي. الاثنين مع بطاطس بدون حار. الأولى صوص ثوم والثانية بدون صوص.',
  'شيل الثانية وخلي الأولى.'
 ],{'quantity':1,'item':'chicken_01','option':('portion','large'),'order':False}),
 ('note_correction',[
  'أبي استلام من النرجس بالرياض. شكشوكة عادي وتميس عدد واحد بدون صوص.',
  'بدون بصل، مو بدون صوص.'
 ],{'quantity':1,'item':'breakfast_01','order':False}),
 ('unknown_allergens',['عندي حساسية شديدة من السمسم، تضمن لي الشكشوكة آمنة؟'],{'empty':True,'order':False})
]

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', help='Run one named case only')
    parser.add_argument('--output',type=Path,default=runtime.ROOT/'evidence/v2/backend-eval.json')
    args=parser.parse_args()
    cases=[case for case in CASES+EXTRA if not args.case or case[0]==args.case]
    if not cases:parser.error('Unknown case name')
    runtime.tx=Transactions(runtime.ROOT/'runtime'/f'v2-eval-{uuid.uuid4().hex}.sqlite3',runtime.engine)
    report={'at':datetime.now(timezone.utc).isoformat(),'model':'gpt-4.1','playback':'simulated receipt; not acoustic evidence','cases':[]}
    gate=asyncio.Semaphore(3)
    async def run(case):
        async with gate:
            name,turns,expected=case;sid,_=runtime.tx.create();record={'name':name,'turns':[]}
            try:
                for index,text in enumerate(turns):
                    row=runtime.tx.load(sid);q=row['state']['quote']
                    if q and not q['presented']:
                        rid=runtime.tx.prepare_audio(sid,q['token'],.1);runtime.tx.playback(sid,rid,'started');runtime.tx.playback(sid,rid,'completed',.1)
                    epoch=runtime.tx.interrupt(sid,invalidate_quote=False)
                    start=time.perf_counter();reply=await runtime.delegate(sid,text,f'{name}-{index}',epoch)
                    record['turns'].append({'input':text,'ms':round((time.perf_counter()-start)*1000),**reply})
                view=runtime.engine.view(runtime.tx.load(sid)['state']);failures=verify(view,expected)
                if name=='critical_nonlinear':
                    assert len(view['basket'])==2 and sum(x['quantity'] for x in view['basket'])==2,'distinct modifiers need two lines'
                    assert sum(bool(x['options'].get('sauce')) for x in view['basket'])==1,'exactly one meal without sauce'
                if name=='note_correction':
                    notes=view['basket'][0]['notes'];assert 'بصل' in notes and 'بدون صوص' not in notes,'correction must replace old note'
                if name=='unavailable_bread_no_defaults':
                    assert len(view['basket'])==1,'save the known item as an incomplete draft'
                    options=view['basket'][0]['options']
                    assert not options.get('bread'),'unavailable bread must not silently become saj or another bread'
                    assert not options.get('spice_level'),'unstated heat preference must remain unresolved'
                    assert view['quote'] is None,'incomplete required choices must block checkout'
                if name=='unknown_allergens':
                    assert any(word in record['turns'][-1]['reply'] for word in ['موظف','معلومات','متوفر','مضم','حساسية']), 'must communicate uncertainty'
                record['failures']=failures;record['passed']=not failures
            except Exception as exc:
                record['passed']=False;record['failures']=[type(exc).__name__+': '+str(exc)]
            report['cases'].append(record);print(name, 'PASS' if record['passed'] else record['failures'],flush=True)
    await asyncio.gather(*(run(case) for case in cases))
    await runtime.provider.aclose()
    report['passed']=sum(c['passed'] for c in report['cases']);report['total']=len(report['cases'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(f"{report['passed']}/{report['total']} passed")
    if report['passed']!=report['total']:raise SystemExit(1)

asyncio.run(main())
