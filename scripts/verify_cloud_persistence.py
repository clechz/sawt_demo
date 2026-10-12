"""Independently verify completed synthetic order and private recording storage."""
import json
import os
from pathlib import Path
import psycopg
from dotenv import dotenv_values
from vercel.blob import list_objects, get
import httpx

ROOT=Path(__file__).resolve().parents[1]
report=json.loads((ROOT/'runtime/cloud-acceptance.json').read_text(encoding='utf8'))
assert report['passed'], 'Complete the cloud acceptance call first'
cfg=dotenv_values(ROOT/'runtime/cloud.env')
os.environ['BLOB_READ_WRITE_TOKEN']=cfg['BLOB_READ_WRITE_TOKEN']
sid=report['call_id'];checks={}
with psycopg.connect(cfg['DATABASE_URL']) as db:
    closed,state=db.execute('SELECT closed,state FROM calls WHERE id=%s',(sid,)).fetchone()
    state=json.loads(state)
    count=db.execute('SELECT count(*) FROM placed_orders WHERE session_id=%s',(sid,)).fetchone()[0]
    checks['closed_call_persisted']=bool(closed)
    checks['exactly_one_durable_order']=count==1 and bool(state['order_id'])
    checks['corrected_order_persisted']=len(state['basket'])==1 and state['basket'][0]['quantity']==1
objects=list_objects(prefix='calls/'+sid+'/').blobs
names={b.pathname.rsplit('/',1)[-1] for b in objects}
checks['caller_and_assistant_archived']={'caller.wav','generated-assistant.wav','capture.json'}<=names
checks['readback_archived']=any(n.endswith('.mp3') for n in names)
sample=next((b for b in objects if b.pathname.endswith('/caller.wav')),None)
if sample:
    checks['archive_private']=httpx.get(sample.url).status_code in (401,403,404)
    checks['authorized_download_valid']=get(sample.pathname,access='private').content.startswith(b'RIFF')
result={'passed':all(checks.values()),'checks':checks,'call_id':sid}
(ROOT/'runtime/cloud-persistence.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
assert result['passed'],checks
