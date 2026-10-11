"""Paid live-model regression checks; generates an honest JSON report, exits nonzero on failure.
Run from the repo root: python scripts/live_eval.py [--audio]
Audio mode uses clearly labelled synthetic customer speech, not human recordings.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sawt.agent import Agent
from sawt.domain import Engine, Menu, new_state
from sawt.provider import OpenAIProvider, config

ROOT=Path(__file__).resolve().parents[1]
CASES=[
 ('delivery_complete', ['أبي توصيل للرياض حي النرجس شارع التجربة مبنى ١٢. أبي شكشوكة حجم كبير مع تميس بدون إضافات، الكمية ٢. هذا كل طلبي.', 'خلصت، عطيني ملخص الطلب', 'نعم'], {'service':'delivery','branch_id':'ruh_narjis','quantity':2,'item':'breakfast_01','option':('portion','large'),'order':True}),
 ('pickup_switch', ['أبي توصيل للرياض حي النرجس شارع ١٢. أبي شكشوكة عادي مع تميس بدون إضافات عدد 1.', 'غيرت رأيي، أبي استلام من فرع النرجس. هذا كل الطلب.', 'عطني ملخص الطلب', 'نعم'], {'service':'pickup','branch_id':'ruh_narjis','quantity':1,'fee':0,'order':True}),
 ('location_unavailable', ['أبي توصيل للرياض حي النرجس شارع ١٢. أبي شكشوكة عادي مع تميس بدون إضافات عدد 1.', 'لا غير العنوان إلى الرياض حي العليا شارع ٢٠. خلصت.'], {'branch_id':'ruh_olaya','unavailable':True,'order':False}),
 ('edit_after_total', ['أبي استلام من فرع النرجس بالرياض، شكشوكة عدد ٢، كبير مع تميس بدون إضافات. هذا كل طلبي.', 'عطني ملخص الطلب', 'لا، خلها وحدة بس.', 'عطني ملخص الطلب', 'اعتمد الطلب'], {'service':'pickup','quantity':1,'order':True}),
 ('code_switch', ['أبي استلام من فرع النرجس. Shakshuka large مع تميس، عدد 2، بدون إضافات.'], {'service':'pickup','quantity':2,'item':'breakfast_01','option':('portion','large')}),
 ('early_item', ['أبي شكشوكة كبير مع تميس بدون إضافات عدد ١.', 'توصيل للرياض حي النرجس شارع ٣ مبنى ٤.'], {'quantity':1,'item':'breakfast_01','branch_id':'ruh_narjis'}),
 ('human_anytime', ['أبي استلام من فرع النرجس.', 'أبي موظف عندي شكوى'], {'handoff':True,'order':False}),
 ('unknown_zone', ['أبي توصيل للرياض حي النرجس شارع ١٢.', 'لا، غير العنوان إلى حي خارج النطاق بمدينة أبها.'], {'no_location':True,'order':False}),
 ('required_choices', ['أبي شكشوكة عدد ١ واستلام من فرع النرجس.'], {'order':False,'missing':True}),
 ('remove_after_total', ['أبي استلام من فرع النرجس، شكشوكة عادي مع تميس بدون إضافات. هذا كل طلبي.', 'عطني ملخص الطلب', 'احذف الشكشوكة من الطلب.'], {'empty':True,'order':False}),
 ('no_false_confirmation', ['أبي استلام من فرع النرجس، شكشوكة عادي مع تميس بدون إضافات. هذا كل طلبي.', 'عطني ملخص الطلب', 'نعم بس خلها وجبتين'], {'quantity':2,'order':False}),
 ('information_only', ['وش عندكم فطور؟'], {'empty':True,'order':False}),
]

def verify(view, expected):
    failures=[]
    for key in ['service','branch_id']:
        if key in expected and view[key]!=expected[key]:failures.append(f'{key}: {view[key]} != {expected[key]}')
    if 'order' in expected and bool(view['order_id'])!=expected['order']:failures.append('order creation expectation')
    if expected.get('handoff') and not view['handoff']:failures.append('missing handoff')
    if expected.get('no_location') and view['location']:failures.append('old address retained')
    if expected.get('empty') and view['basket']:failures.append('basket should be empty')
    if 'fee' in expected and view['delivery_fee']!=expected['fee']:failures.append('wrong delivery fee')
    if 'quantity' in expected and (len(view['basket'])!=1 or view['basket'][0]['quantity']!=expected['quantity']):failures.append('wrong quantity or duplicate lines')
    if 'item' in expected and (not view['basket'] or view['basket'][0]['item_id']!=expected['item']):failures.append('wrong item')
    if 'option' in expected:
        group,opt=expected['option']
        if not view['basket'] or opt not in view['basket'][0]['options'].get(group,[]):failures.append('wrong option')
    if expected.get('unavailable') and not any(x['available'] is False for x in view['basket']):failures.append('availability not flagged')
    if expected.get('missing') and not any(x['missing'] for x in view['basket']):failures.append('required choices silently filled')
    return failures

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--audio',action='store_true');parser.add_argument('--case');args=parser.parse_args()
    if not config()['key']:raise SystemExit('BLOCKED: OPENAI_API_KEY is missing. No live tests were run.')
    provider=OpenAIProvider();engine=Engine(Menu(ROOT/'data/restaurant-menu-complex.csv'));agent=Agent(engine,provider)
    report={'models':{k:v for k,v in config().items() if k!='key'},'audio_source':'synthetic TTS customer, not human' if args.audio else 'text','cases':[]}
    output=ROOT/'runtime';output.mkdir(exist_ok=True)
    for name,turns,expected in CASES:
        if args.case and name!=args.case:continue
        state=new_state();record={'name':name,'turns':[]};started=time.perf_counter()
        try:
            for i,text in enumerate(turns):
                transcript=text
                if args.audio:
                    audio=await provider.speak(text);(output/f'{name}-{i}-customer.mp3').write_bytes(audio)
                    transcript=await provider.transcribe(audio,'customer.mp3')
                state,result=await agent.turn(state,transcript)
                record['turns'].append({'input':text,'transcript':transcript,**result})
                if args.audio:
                    audio=await provider.speak(result['reply']);(output/f'{name}-{i}-assistant.mp3').write_bytes(audio)
                # Simulated listener consumes the full generated reply before next turn.
                # Browser tests separately verify real audio-ended acknowledgement.
                if state['quote']:state['quote']['presented']=True
            record['failures']=verify(engine.view(state),expected)
        except Exception as exc:record['failures']=[str(exc)]
        record['passed']=not record['failures'];record['duration_s']=round(time.perf_counter()-started,2);report['cases'].append(record)
        print(name, 'PASS' if record['passed'] else 'FAIL', record['failures'],flush=True)
        (output/('live-audio-report.json' if args.audio else 'live-text-report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if report['cases'] and all(x['passed'] for x in report['cases']) else 1)

if __name__=='__main__':asyncio.run(main())
