"""Verify actual browser playback, short-answer routing, and spoken hangup."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sawt.v2_runtime import tx,engine,ROOT

sid=sys.argv[1]
row=tx.load(sid);state=engine.view(row['state'])
def read_events(call_id):
    events=[];after=0
    while True:
        page=tx.events(call_id,after);events.extend(page)
        if len(page)<500:return events
        after=page[-1]['sequence']
events=read_events(sid)
end_sid=sys.argv[2] if len(sys.argv)>2 else sid
end_row=tx.load(end_sid);end_events=read_events(end_sid)
with tx.connect() as db:
    receipts=[dict(r) for r in db.execute('SELECT duration,started,completed FROM receipts WHERE session_id=?',(sid,))]
    count=db.execute('SELECT count(*) FROM placed_orders WHERE session_id=?',(sid,)).fetchone()[0]
assert row['closed'], 'main test call must be closed'
assert end_row['closed'], 'spoken end command must close the hangup test call'
assert any(e['kind']=='call.end_requested' for e in end_events), 'must close through the voice command, not a manual end button'
assert count==1 and state['order_id'], 'exactly one durable order'
assert len(state['basket'])==1 and state['basket'][0]['item_id']=='breakfast_05'
assert state['basket'][0]['options']=={'bread':['brown'],'portion':['regular']}
assert state['total']==1500 and state['branch_id']=='ruh_narjis'
assert any(r['completed'] and r['duration']>10 and r['completed']-r['started']>=r['duration']-.5 for r in receipts), 'actual browser playback must finish'
shorts=[e for e in events if e['kind']=='delegation.started' and 'حجم عادي عادي' in e['payload']['text']]
assert shorts and shorts[-1]['payload']['delegation_id'].startswith('transcript-'), 'short answer must exercise the fallback route'
stages={e['payload']['stage'] for e in events if e['kind']=='delegation.progress'}
assert {'understanding','add_item','update_item','checkout','confirm','saving'}<=stages
assert not any(e['kind']=='delegation.failed' for e in events)
report={'passed':True,'kind':'real_chrome_synthetic_voice','session_id':sid,'state':state,'receipts':receipts,'order_count':count,'events':events,'hangup_retest':{'session_id':end_sid,'closed':bool(end_row['closed']),'events':end_events},'note':'The first call exposed segmented hangup recognition; the separate hangup call verifies the subsequent fix.' if end_sid!=sid else ''}
(ROOT/'evidence/v2/browser-call-improvements.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'passed':True,'session_id':sid,'order_count':count,'receipt_seconds':[r['duration'] for r in receipts],'stages':sorted(stages),'spoken_hangup':True},ensure_ascii=False))
