"""Browser/UI regression only. Call transport is mocked; not a voice quality test."""
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from threading import Thread
from playwright.sync_api import sync_playwright
import json
ROOT=Path(__file__).resolve().parents[1]
root=ROOT/'static/v2'
OUT=Path('/tmp/sawt-ash-ui-evidence');OUT.mkdir(exist_ok=True)
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(root),**kw)
 def do_GET(self):
  if self.path.startswith('/assets/'):self.path=self.path[len('/assets'):]
  super().do_GET()
 def log_message(self,*a):pass
server=ThreadingHTTPServer(('127.0.0.1',8767),Handler)
Thread(target=server.serve_forever,daemon=True).start()
contract={'protocol':1,'source_fingerprint':'a'*64,'experience_version':'v3','conversation_mode':'model_led','voice':'ash','planner_model':'test-model','voice_model':'gpt-live-1'}
fake=r'''window.LivekitClient={RoomEvent:Object.fromEntries(['LocalTrackPublished','LocalTrackUnpublished','TrackSubscribed','TrackUnsubscribed','DataReceived','Reconnecting','Reconnected','Disconnected'].map(x=>[x,x])),Room:class{
 constructor(){this.events={};this.remoteParticipants=new Map();window.testRoom=this;window.testMic={enabled:true};this.localParticipant={audioLevel:0,identity:'caller-test',audioTrackPublications:new Map([['mic',{source:'microphone',track:{mediaStreamTrack:window.testMic}}]]),publishData:async(data,opts)=>{window.lastMicMessage={body:JSON.parse(new TextDecoder().decode(data)),opts};},setMicrophoneEnabled:async()=>{setTimeout(()=>{this.events.DataReceived(new TextEncoder().encode(JSON.stringify({type:'ready',call_id:'test',worker_contract:CONTRACT})),{identity:'worker'},null,'sawt');},40);}};}
 on(k,v){this.events[k]=v;return this;}async startAudio(){}async connect(){}async disconnect(){}
 }};'''.replace('CONTRACT',json.dumps(contract))
results={'scope':'real browser/UI; mocked call transport, not a live voice test','checks':[]}
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
  for label,width,height in [('desktop',1280,800),('mobile',390,844)]:
   page=browser.new_page(viewport={'width':width,'height':height},device_scale_factor=1)
   errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/assets/livekit-client.js',lambda route:route.fulfill(status=200,content_type='application/javascript',body=fake))
   def api(route):
    path=route.request.url.split('8767')[-1]
    body={'id':'test','token':'test-only','url':'mock','room_token':'mock','max_seconds':600,'required_worker':contract} if path=='/api/calls' else {'state':{'basket':[],'issues':[],'total':0,'subtotal':0,'delivery_fee':0},'closed':False}
    route.fulfill(status=200,content_type='application/json',body=json.dumps(body))
   page.route('**/api/**',api)
   page.goto('http://127.0.0.1:8767/');page.wait_for_timeout(1000)
   assert page.locator('select').count()==0
   assert not page.locator('#experience-consent').is_checked()
   page.screenshot(path=str(OUT/f'{label}-idle.png'))
   page.locator('#experience-consent').check();page.locator('#start').click();page.wait_for_timeout(200)
   assert page.locator('body').get_attribute('data-voice')=='ash'
   orb=page.locator('.orb-control').bounding_box();phase=page.locator('.call-state').bounding_box()
   assert phase['y']>=orb['y']+orb['height'],(orb,phase)
   page.locator('#mute').click();page.wait_for_timeout(50)
   assert page.evaluate('testMic.enabled') is False
   assert page.evaluate('lastMicMessage.body.muted') is True
   assert page.evaluate('lastMicMessage.opts.topic')=='sawt-mic'
   assert page.locator('#controls').is_visible()
   page.screenshot(path=str(OUT/f'{label}-call.png'))
   page.locator('#mute').click();assert page.evaluate('testMic.enabled') is True
   page.locator('#end').click();page.wait_for_timeout(100)
   assert page.locator('#start').is_visible()
   assert not errors,errors
   results['checks'].append({'viewport':label,'ash':True,'no_selectors':True,'status_below_orb':True,'mute_unmute_controls':True,'console_errors':errors})
   page.close()
  browser.close()
finally:
 server.shutdown()
 (OUT/'browser-results.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
