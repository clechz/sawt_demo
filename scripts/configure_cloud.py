"""Copy existing credentials to the requested cloud services without logging values."""
import json
import subprocess
import shutil
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
local = dotenv_values(ROOT/'.env')
cloud = dotenv_values(ROOT/'runtime/cloud.env')
private = json.loads((ROOT/'runtime/private-demo.json').read_text())
values = {key: local[key] for key in ('OPENAI_API_KEY','LIVEKIT_URL','LIVEKIT_API_KEY','LIVEKIT_API_SECRET')}
values.update(SAWT_DEMO_PASSWORD=private['password'], SAWT_DEMO_SECRET=private['secret'],
              SAWT_PUBLIC_URL='https://sawt-demo.vercel.app',
              SAWT_AGENT_NAME='sawt-cloud', SAWT_RUNTIME_DIR='/tmp/sawt')
cli = shutil.which('vercel.cmd') or shutil.which('vercel')
for name, value in values.items():
    result = subprocess.run([cli,'env','add',name,'production','--force','--yes'],
                            input=value, text=True, capture_output=True, cwd=ROOT)
    if result.returncode:
        raise SystemExit('Unable to configure '+name+'; CLI exit '+str(result.returncode))
    print('Configured '+name, flush=True)
worker = {key: values[key] for key in ('OPENAI_API_KEY','SAWT_AGENT_NAME','SAWT_RUNTIME_DIR')}
worker.update({key: cloud[key] for key in ('DATABASE_URL','BLOB_READ_WRITE_TOKEN')})
(ROOT/'runtime/livekit-cloud.env').write_text('\n'.join(k+'='+json.dumps(v) for k,v in worker.items())+'\n')
print('Worker secrets saved in ignored runtime/livekit-cloud.env')
