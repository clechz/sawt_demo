import copy
from pathlib import Path
import pytest
from sawt.release_contract import SOURCE_FILES, source_fingerprint, worker_contract, check_worker_contract
from sawt.experience import validate_experience, call_experience
from sawt.domain import Engine, Menu
from sawt.transactions import Transactions


def test_source_fingerprint_changes_on_worker_change_and_requires_complete_package(tmp_path):
    for name in SOURCE_FILES:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
    before=source_fingerprint(tmp_path)
    (tmp_path/'voice_worker.py').write_text('updated worker')
    assert source_fingerprint(tmp_path)!=before
    (tmp_path/'voice_worker.py').unlink()
    with pytest.raises(RuntimeError):source_fingerprint(tmp_path)

@pytest.mark.parametrize('field,value',[
 ('source_fingerprint','0'*64),('voice','ash'),('conversation_mode','legacy'),
 ('planner_model','different-model'),('experience_version','v2'),('protocol',2),('voice_model','other')])
def test_contract_rejects_code_voice_mode_and_model_drift(field,value):
    settings=validate_experience('cedar',conversation_mode='model_led')
    required=worker_contract(settings);actual=copy.deepcopy(required);actual[field]=value
    with pytest.raises(ValueError):check_worker_contract(required,actual)

@pytest.mark.parametrize('bad',[None,{},'v3',{'protocol':1}])
def test_missing_worker_information_is_not_success(bad):
    with pytest.raises(ValueError):check_worker_contract(worker_contract(validate_experience()),bad)

def test_matching_contract_passes():
    c=worker_contract(validate_experience('cedar',conversation_mode='model_led'))
    check_worker_contract(c,copy.deepcopy(c))

def test_call_mode_is_saved_not_changed_by_worker_environment(tmp_path,monkeypatch):
    e=Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))
    tx=Transactions(tmp_path/'calls.db',e)
    a,_=tx.create(experience=validate_experience('cedar',conversation_mode='model_led'))
    b,_=tx.create(experience=validate_experience('ash',conversation_mode='legacy'))
    monkeypatch.setenv('SAWT_CONVERSATION_MODE','legacy')
    one=call_experience(tx.load(a)['state']);two=call_experience(tx.load(b)['state'])
    assert one['conversation_mode']=='model_led' and two['conversation_mode']=='legacy'
    assert one['voice']=='cedar' and two['voice']=='ash'
    check_worker_contract(one['worker_contract'],worker_contract(one))
    one['worker_contract']['voice']='ash'
    assert tx.load(a)['state']['experience']['worker_contract']['voice']=='cedar'

def test_caller_cannot_supply_fake_worker_contract(tmp_path):
    e=Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))
    tx=Transactions(tmp_path/'calls.db',e)
    settings=validate_experience('cedar',conversation_mode='model_led')
    settings['worker_contract']={'source_fingerprint':'forged'}
    sid,_=tx.create(experience=settings)
    assert tx.load(sid)['state']['experience']['worker_contract']['source_fingerprint']!='forged'

def test_v2_cannot_request_model_led():
    with pytest.raises(ValueError):validate_experience('marin',version='v2',conversation_mode='model_led')
