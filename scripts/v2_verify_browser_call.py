"""Verify a completed browser test from durable state; does not synthesize playback.

Use with synthetic Shakshuka fixtures after driving /lab in Chrome. This checks
the actual browser receipts and saved order, not an LLM's assessment of success.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sawt.domain import Engine, Menu

ROOT=Path(__file__).resolve().parents[1]


def verify(sid, quantity, total, interrupted=False):
    with sqlite3.connect((ROOT/'runtime/v2.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        orders=db.execute('SELECT snapshot FROM placed_orders WHERE session_id=?',(sid,)).fetchall()
        assert len(orders)==1, 'Exactly one order must be saved'
        snapshot=json.loads(orders[0]['snapshot'])
        receipts=[dict(r) for r in db.execute('SELECT revision,duration,started,completed,id FROM receipts WHERE session_id=? ORDER BY rowid',(sid,))]
    view=Engine(Menu(ROOT/'data/restaurant-menu-complex.csv')).view(snapshot)
    assert len(view['basket'])==1 and view['basket'][0]['quantity']==quantity
    assert view['basket'][0]['item_id']=='breakfast_01'
    assert view['basket'][0]['options']['portion']==['large']
    assert view['basket'][0]['options']['bread']==['tamees']
    assert view['total']==total, 'Final price must be recomputed from the menu'
    assert sum(bool(r['completed']) for r in receipts)==1
    assert snapshot['quote']['presented'] and snapshot['quote']['receipt_id']==receipts[-1]['id']
    if interrupted:
        assert len(receipts)==2 and receipts[0]['completed'] is None
        assert receipts[-1]['revision']>receipts[0]['revision']
    return {'call_id':sid,'passed':True,'quantity':quantity,'total_halalas':view['total'],
            'order_id':view['order_id'],'placed_order_count':1,'receipts':receipts}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('call_id');parser.add_argument('--quantity',type=int,required=True)
    parser.add_argument('--total-halalas',type=int,required=True);parser.add_argument('--interrupted',action='store_true')
    args=parser.parse_args()
    print(json.dumps(verify(args.call_id,args.quantity,args.total_halalas,args.interrupted),indent=2))
