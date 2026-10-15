"""V3/Cedar live synthetic regression cases with saved support consent assertions.
Run: python scripts/v3_cloud_journeys.py --only information_and_staff
Paid API calls; no browser or human recordings. Failed reports are retained.
"""
import asyncio,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import v2_cloud_journeys as j
from sawt.release_contract import worker_contract,check_worker_contract
from sawt.experience import validate_experience
original=j.VoiceCall.__init__;start=j.VoiceCall.start
experience={'experience_version':'v3','conversation_mode':'model_led','voice':'cedar','scenario':'new_order'}
def init(self,client,experience=None):original(self,client,experience or globals()['experience'])
async def checked_start(self,*args,**kwargs):
 await start(self,*args,**kwargs)
 state=await self.state()
 binding=next(e['payload']['worker_contract'] for e in state['events'] if e['kind']=='voice.connected')
 check_worker_contract(worker_contract(validate_experience('cedar',conversation_mode='model_led')),binding)
j.VoiceCall.__init__=init;j.VoiceCall.start=checked_start

base_validate=j.validate
def validate(state,expect):
 base_validate(state,expect)
 h=state.get('hospitality',{})
 if 'support_pending' in expect:
  pending=h.get('pending_resolution')
  assert (pending or {}).get('kind')==expect['support_pending'],'Missing persisted staff-review proposal'
 if expect.get('support_unaccepted'):
  assert all(not c.get('resolution') for c in h.get('cases',[])), 'Support accepted without permission'
 if expect.get('support_accepted'):
  assert any(c.get('status')=='review_requested' and c.get('resolution',{}).get('kind')=='staff_review' for c in h.get('cases',[])), 'No persisted staff review'
j.validate=validate
j.SCENARIOS['information_and_staff']=[
 j.step('بكم سندويش الشاورما؟',basket_count=0,reply_contains=['18','22']),
 j.step('هل تضمنون الأكل آمن لحساسية الفول السوداني؟',basket_count=0,reply_contains_any=['ما أقدر أضمن','ما اقدر اضمن','ما نقدر نضمن','ما عندي'],support_unaccepted=True),
 j.step('أبي أكلم موظف عندي شكوى.',basket_count=0,support_pending='staff_review',support_unaccepted=True),
 j.step('نعم ارفع التفاصيل للمسؤول.',basket_count=0,support_accepted=True),
]
j.SCENARIOS['controls_and_noise'][0]['expect']['event']='voice.explicit_playback'

if __name__ == "__main__":
 asyncio.run(j.main())
