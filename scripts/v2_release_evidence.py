"""Read-only assertions for the completed synthetic browser release calls."""
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sawt.domain import Engine,Menu
ROOT=Path(__file__).resolve().parents[1]
sid='3ffb9340307e4665bc48f029a7bb2bba'
complaint='16d13e46d4094cb8adba157dc7245101'
with sqlite3.connect((ROOT/'runtime/v2.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    row=db.execute('SELECT * FROM calls WHERE id=?',(sid,)).fetchone()
    orders=db.execute('SELECT snapshot FROM placed_orders WHERE session_id=?',(sid,)).fetchall()
    assert row['closed'] and len(orders)==1
    saved=json.loads(orders[0]['snapshot'])
    view=Engine(Menu(ROOT/'data/restaurant-menu-complex.csv')).view(saved)
    assert view['total']==4600 and len(view['basket'])==2
    maasoub,karak=view['basket']
    assert maasoub['item_id']=='breakfast_06' and maasoub['quantity']==1
    assert maasoub['options']=={'portion':['regular'],'bread':['brown']}
    assert karak['item_id']=='beverages_09' and karak['quantity']==1
    assert karak['options']=={'size':['large'],'ice':['none'],'sweetness':['half']}
    receipts=[dict(r) for r in db.execute('SELECT id,revision,duration,started,completed FROM receipts WHERE session_id=? ORDER BY rowid',(sid,))]
    assert len(receipts)==3 and receipts[0]['completed'] and not receipts[1]['completed'] and receipts[2]['completed']
    assert saved['quote']['presented'] and saved['quote']['receipt_id']==receipts[2]['id']
    audit=[{'at':r['at'],'kind':r['kind'],'payload':json.loads(r['payload'])} for r in db.execute('SELECT at,kind,payload FROM audit WHERE session_id=? ORDER BY sequence',(sid,))]
    commits=[e for e in audit if e['kind']=='tool.committed' and e['payload']['tool']=='confirm']
    assert len(commits)==1 and commits[0]['at']>receipts[2]['completed']
    assert any(e['kind']=='call.end_requested' and e['payload']['source']=='explicit_caller_command' for e in audit)
    complaint_row=db.execute('SELECT state,closed FROM calls WHERE id=?',(complaint,)).fetchone()
    complaint_state=json.loads(complaint_row['state'])
    assert complaint_row['closed'] and complaint_state['handoff'] and not complaint_state['order_id']
    assert db.execute('SELECT count(*) FROM placed_orders WHERE session_id=?',(complaint,)).fetchone()[0]==0
    result={'kind':'durable_actual_browser_evidence','passed':True,'call_id':sid,'order_id':view['order_id'],
            'total_halalas':view['total'],'order_count':len(orders),'receipts':[{k:v for k,v in r.items() if k!='id'} for r in receipts],
            'interrupted_readback_not_completed':True,'confirmation_only_after_final_readback':True,'spoken_hangup':True,
            'complaint_call':complaint,'complaint_handoff_without_order':True}
(ROOT/'evidence/v2/release-browser-evidence.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps(result,indent=2))
