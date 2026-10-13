"""Real Chromium UI/media controls with synthetic tracks and mocked backend.
This proves browser lifecycle behavior, not deployed speech or model competence.
"""
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from threading import Thread
from playwright.sync_api import sync_playwright
import json
ROOT=Path(__file__).resolve().parents[1]
OUT=Path('/tmp/sawt-completion-evidence');OUT.mkdir(exist_ok=True)
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'static/v2'),**kw)
 def do_GET(self):
  if self.path.startswith('/assets/'):self.path=self.path[len('/assets'):]
  super().do_GET()
 def log_message(self,*a):pass
server=ThreadingHTTPServer(('127.0.0.1',8767),Handler)
Thread(target=server.serve_forever,daemon=True).start()
contract={'protocol':1,'source_fingerprint':'a'*64,'experience_version':'v3','conversation_mode':'model_led','voice':'ash','planner_model':'test-model','voice_model':'gpt-live-1'}
line={'line_id':'one','item_id':'rice_06','name':'مضغوط لحم','quantity':3,'option_names':['فردي','بسمتي'],'notes':'بدون صوص','missing':[],'line_total':13500}
base={'basket':[line],'issues':[],'total':13500,'subtotal':13500,'delivery_fee':0,'service':'pickup','branch':{'name':'فرع النرجس'},'order_id':None,'quote':None}
fake=r'''window.LivekitClient={RoomEvent:Object.fromEntries(['LocalTrackPublished','LocalTrackUnpublished','TrackSubscribed','TrackUnsubscribed','DataReceived','Reconnecting','Reconnected','Disconnected'].map(x=>[x,x])),Room:class{
 constructor(){this.events={};this.remoteParticipants=new Map();window.testRoom=this;this.context=new AudioContext();this.input=this.context.createMediaStreamDestination();window.testMic=this.input.stream.getAudioTracks()[0];this.localParticipant={identity:'caller-test',audioLevel:0,audioTrackPublications:new Map([['mic',{source:'microphone',track:{mediaStreamTrack:window.testMic}}]]),publishData:async(data,opts)=>{window.lastMicMessage={body:JSON.parse(new TextDecoder().decode(data)),opts};},setMicrophoneEnabled:async()=>{
 const dest=this.context.createMediaStreamDestination(),osc=this.context.createOscillator(),gain=this.context.createGain();gain.gain.value=.005;osc.connect(gain);gain.connect(dest);osc.start();this.osc=osc;window.testSpeaker=document.createElement('audio');testSpeaker.srcObject=dest.stream;
 this.events.TrackSubscribed({kind:'audio',mediaStreamTrack:dest.stream.getAudioTracks()[0],attach:()=>testSpeaker,detach:()=>[testSpeaker]});
 setTimeout(()=>this.events.DataReceived(new TextEncoder().encode(JSON.stringify({type:'ready',call_id:'test',worker_contract:CONTRACT})),{identity:'worker'},null,'sawt'),40);
 }};}
 on(k,v){this.events[k]=v;return this;}async startAudio(){await this.context.resume();}async connect(){}async disconnect(){window.testDisconnected=true;this.osc?.stop();await this.context.close();}
 }};'''.replace('CONTRACT',json.dumps(contract))
report={'scope':'Chromium browser, synthetic audio tracks and mocked backend; NOT a live model conversation','checks':[]}
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox','--autoplay-policy=no-user-gesture-required','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
  for label,width,height,motion in [('desktop',1280,900,'no-preference'),('mobile',390,844,'no-preference'),('reduced-motion',390,844,'reduce')]:
   page=browser.new_page(viewport={'width':width,'height':height});page.emulate_media(reduced_motion=motion)
   errors=[];state=dict(base);requests=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/assets/livekit-client.js',lambda route:route.fulfill(status=200,content_type='application/javascript',body=fake))
   def api(route):
    path=route.request.url.split('8767')[-1];requests.append(path)
    if path=='/api/calls':
     assert json.loads(route.request.post_data)['voice']=='ash'
     payload={'id':'test','token':'test-only','url':'mock','room_token':'mock','max_seconds':600,'required_worker':contract}
    elif path.endswith('/end'):payload={'closed':True}
    else:payload={'state':state,'closed':False}
    route.fulfill(status=200,content_type='application/json',body=json.dumps(payload))
   page.route('**/api/**',api)
   try:
    page.goto('http://127.0.0.1:8767/');page.wait_for_timeout(500)
    assert page.locator('select').count()==0 and page.locator('input[type=checkbox]').count()==0
    page.locator('#start').click();page.wait_for_function("document.body.dataset.voice==='ash'",timeout=5000)
    assert not page.locator('#completion').is_visible()
    page.locator('#mute').click();page.wait_for_function('window.lastMicMessage?.body.muted===true')
    assert page.evaluate('testMic.enabled') is False and page.evaluate('testMic.readyState')=='live'
    assert page.evaluate('testSpeaker.paused') is False and page.evaluate('testSpeaker.muted') is False
    page.locator('#mute').click();page.wait_for_function('window.lastMicMessage?.body.muted===false')
    assert page.evaluate('testMic.enabled') is True
    state['order_id']='S-123';page.wait_for_selector('#completion',state='visible',timeout=4000)
    text=page.locator('#completion').inner_text()
    assert 'تم تأكيد طلبك' in text and 'S-123' in text and 'مضغوط لحم' in text and '135' in text
    page.screenshot(path=str(OUT/f'{label}-confirmed.png'),full_page=True)
    flags=page.evaluate("""()=>{document.querySelector('#end').click();return {micStopped:testMic.readyState==='ended',speakerPaused:testSpeaker.paused,disconnectStarted:window.testDisconnected===true};}""")
    assert all(flags.values()),flags
    page.wait_for_function("document.body.dataset.phase==='ended'",timeout=2500)
    assert page.locator('#completion').is_visible() and page.locator('#new-call').is_visible()
    assert not page.locator('#controls').is_visible()
    page.screenshot(path=str(OUT/f'{label}-ended.png'),full_page=True)
    assert not errors,errors
    report['checks'].append({'viewport':label,'ash':True,'mic_mute_keeps_synthetic_speaker_playing':True,'no_draft_success':True,'saved_receipt':True,'immediate_hangup':flags,'receipt_survives_hangup':True,'new_call_button':True,'console_errors':errors})
   except Exception:
    report['failure']={'viewport':label,'console_errors':errors,'requests':requests,'body':page.locator('body').inner_text()}
    page.screenshot(path=str(OUT/f'{label}-failure.png'),full_page=True)
    print(json.dumps(report['failure'],ensure_ascii=False));raise
   finally:page.close()
  browser.close()
finally:
 server.shutdown();(OUT/'browser-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
