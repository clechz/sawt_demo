"""Initialize demo-only credentials, never log them. Run after tunnel startup."""
import json
import re
import secrets
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
log=(ROOT/'runtime/private-tunnel.err.log').read_text(encoding='utf8',errors='replace')
urls=re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com',log)
if not urls:raise SystemExit('Tunnel URL is not ready.')
path=ROOT/'runtime/private-demo.json'
settings=json.loads(path.read_text(encoding='utf8')) if path.exists() else {'password':secrets.token_urlsafe(18),'secret':secrets.token_urlsafe(40)}
settings['url']=urls[-1]
path.write_text(json.dumps(settings,indent=2),encoding='utf8')
(ROOT/'runtime/PRIVATE-DEMO-ACCESS.txt').write_text('PRIVATE SAWT DEMO\n\nURL: '+settings['url']+'\nPassword: '+settings['password']+'\n\nShare these only with invited testers. The URL works while this computer, the API, voice worker, gateway and tunnel are running. It changes when the tunnel restarts. No real restaurant orders or human dispatch.\n',encoding='utf8')
print(settings['url'])
print('Private access details saved to ignored runtime/PRIVATE-DEMO-ACCESS.txt')
