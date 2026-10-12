import concurrent.futures
import json
from pathlib import Path
import pytest
from sawt.domain import Engine, Menu, RuleError
from sawt.transactions import Transactions, Conflict
from sawt.transactions import StagedEngine
import copy

@pytest.fixture
def tx(tmp_path):
    return Transactions(tmp_path/'calls.sqlite3', Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv')))

def command(tx, sid, name, args=None, op=None, utterance=''):
    row=tx.load(sid)
    return tx.execute(sid,op or str(len(tx.events(sid))),row['state']['revision'],row['epoch'],name,args or {},utterance=utterance)

def ready(tx):
    sid,token=tx.create()
    command(tx,sid,'set_service',{'service':'pickup'})
    command(tx,sid,'set_branch',{'branch_id':'ruh_narjis'})
    item=next(x for x in tx.engine.menu.items.values() if 'ruh_narjis' in x['available'])
    options={gid:list(g['options'])[:g['min']] for gid,g in item['groups'].items() if g['min']}
    command(tx,sid,'add_item',{'item_id':item['id'],'quantity':1,'options':options,'notes':''})
    command(tx,sid,'checkout')
    return sid,token

def heard(tx,sid,monkeypatch):
    row=tx.load(sid)
    receipt=tx.prepare_audio(sid,row['state']['quote']['token'],5)
    monkeypatch.setattr('sawt.transactions.time.time',lambda:1000)
    tx.playback(sid,receipt,'started')
    monkeypatch.setattr('sawt.transactions.time.time',lambda:1006)
    tx.playback(sid,receipt,'completed',5)
    return receipt

def test_restart_replay_and_payload_collision(tx):
    sid,_=tx.create()
    args={'service':'pickup'}
    first=tx.execute(sid,'op',0,0,'set_service',args)
    reopened=Transactions(tx.path,tx.engine)
    assert reopened.execute(sid,'op',0,0,'set_service',args)==first
    with pytest.raises(Conflict): reopened.execute(sid,'op',0,0,'set_service',{'service':'delivery'})
    assert len(reopened.events(sid))==1

def test_stale_revision_and_epoch_reject(tx):
    sid,_=tx.create()
    tx.execute(sid,'a',0,0,'set_service',{'service':'pickup'})
    with pytest.raises(Conflict):tx.execute(sid,'b',0,0,'set_service',{'service':'delivery'})
    row=tx.load(sid);tx.interrupt(sid)
    with pytest.raises(Conflict):tx.execute(sid,'c',row['state']['revision'],0,'set_service',{'service':'delivery'})
    assert tx.load(sid)['state']['service']=='pickup'

def test_concurrent_stale_writers(tx):
    sid,_=tx.create()
    def write(n):
        try:return tx.execute(sid,str(n),0,0,'set_service',{'service':'pickup'})
        except Conflict:return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        result=list(pool.map(write,range(5)))
    assert sum(x is not None for x in result)==1

def test_receipt_requires_full_real_elapsed_playback(tx,monkeypatch):
    sid,_=ready(tx);quote=tx.load(sid)['state']['quote']
    assert quote['text']==tx.engine.summary(tx.load(sid)['state'])
    receipt=tx.prepare_audio(sid,quote['token'],10)
    with pytest.raises(Conflict):tx.playback(sid,receipt,'completed',10)
    monkeypatch.setattr('sawt.transactions.time.time',lambda:1000)
    tx.playback(sid,receipt,'started')
    with pytest.raises(Conflict):tx.playback(sid,receipt,'completed',10)
    monkeypatch.setattr('sawt.transactions.time.time',lambda:1011)
    with pytest.raises(Conflict):tx.playback(sid,receipt,'completed',2)
    tx.playback(sid,receipt,'completed',10)
    assert tx.load(sid)['state']['quote']['presented']

@pytest.mark.parametrize('change',['interrupt','close','modify'])
def test_old_playback_never_authorizes_changed_order(tx,monkeypatch,change):
    sid,_=ready(tx);quote=tx.load(sid)['state']['quote'];receipt=tx.prepare_audio(sid,quote['token'],.1)
    tx.playback(sid,receipt,'started')
    if change=='modify':command(tx,sid,'set_service',{'service':'delivery'})
    else:tx.interrupt(sid,close=change=='close')
    with pytest.raises(Conflict):tx.playback(sid,receipt,'completed',.1)

@pytest.mark.parametrize('text',['تمام اعتمد لا لحظة أبي أضيف مشروب','نعم بس شيل الثانية','بدون بصل مو بدون صوص','لا تعتمد'])
def test_mixed_acceptance_never_creates_order(tx,monkeypatch,text):
    sid,_=ready(tx);heard(tx,sid,monkeypatch)
    with pytest.raises(RuleError):command(tx,sid,'confirm',utterance=text)
    assert tx.load(sid)['state']['order_id'] is None

def test_order_and_state_and_replay_commit_together(tx,monkeypatch):
    sid,_=ready(tx);heard(tx,sid,monkeypatch);row=tx.load(sid)
    result=tx.execute(sid,'confirm',row['state']['revision'],row['epoch'],'confirm',{},utterance='اعتمد')
    restarted=Transactions(tx.path,tx.engine)
    assert restarted.execute(sid,'confirm',row['state']['revision'],row['epoch'],'confirm',{},utterance='اعتمد')==result
    with restarted.connect() as db:
        order=db.execute('SELECT * FROM placed_orders').fetchall()
    assert len(order)==1 and order[0]['id']==restarted.load(sid)['state']['order_id']

def test_authentication_scope(tx):
    sid,token=tx.create();other,other_token=tx.create()
    assert tx.authorize(sid,token)['id']==sid
    with pytest.raises(PermissionError):tx.authorize(sid,other_token)
    with pytest.raises(PermissionError):tx.authorize(sid,'')

def test_validation_failure_rolls_back(tx):
    sid,_=tx.create()
    with pytest.raises(RuleError):command(tx,sid,'set_service',{'service':'spaceship'})
    assert tx.load(sid)['state']['revision']==0 and not tx.events(sid)

def test_atomic_bundle_and_durable_replay(tx):
    sid,_=tx.create();draft=copy.deepcopy(tx.load(sid)['state']);staged=StagedEngine(tx.engine)
    staged.act(draft,'set_service',{'service':'pickup'})
    staged.act(draft,'set_branch',{'branch_id':'ruh_narjis'})
    assert tx.load(sid)['state']['service'] is None
    tx.commit_bundle(sid,'b',0,0,draft,staged.operations,'pickup',{'ok':True})
    assert tx.load(sid)['state']['revision']==2
    assert tx.replay_bundle(sid,'b','pickup')=={'ok':True}
    with pytest.raises(Conflict):tx.replay_bundle(sid,'b','delivery')

def test_interruption_discards_whole_unpublished_bundle(tx):
    sid,_=tx.create();draft=copy.deepcopy(tx.load(sid)['state']);staged=StagedEngine(tx.engine)
    staged.act(draft,'set_service',{'service':'pickup'})
    staged.act(draft,'set_branch',{'branch_id':'ruh_narjis'})
    tx.interrupt(sid)
    with pytest.raises(Conflict):tx.commit_bundle(sid,'b',0,0,draft,staged.operations)
    assert tx.load(sid)['state']['service'] is None
    assert not [e for e in tx.events(sid) if e['kind']=='tool.committed']

def test_shared_call_budget(tx):
    tx.create(enforce_limits=True);tx.create(enforce_limits=True)
    another=Transactions(tx.path,tx.engine)
    with pytest.raises(Conflict):another.create(enforce_limits=True)


def test_stream_cannot_confirm_before_duration_is_known(tx, monkeypatch):
    sid,_=ready(tx);token=tx.load(sid)['state']['quote']['token']
    rid=tx.prepare_audio(sid,token)
    tx.claim_audio(sid,rid)
    tx.playback(sid,rid,'started')
    with pytest.raises(Conflict):tx.playback(sid,rid,'completed',100)
    tx.finish_audio(sid,rid,.1)
    tx.playback(sid,rid,'completed',.1)
    assert tx.load(sid)['state']['quote']['presented']


def test_stream_is_claimed_once_and_failed_stream_never_confirms(tx):
    sid,_=ready(tx);rid=tx.prepare_audio(sid,tx.load(sid)['state']['quote']['token'])
    tx.claim_audio(sid,rid)
    with pytest.raises(Conflict):tx.claim_audio(sid,rid)
    tx.playback(sid,rid,'started')
    tx.fail_audio(sid,rid)
    with pytest.raises(Conflict):tx.playback(sid,rid,'completed',100)
    with pytest.raises(Conflict):tx.current_receipt(sid,rid)


def test_stream_completion_after_interruption_is_rejected(tx):
    sid,_=ready(tx);rid=tx.prepare_audio(sid,tx.load(sid)['state']['quote']['token'])
    tx.claim_audio(sid,rid);tx.interrupt(sid)
    with pytest.raises(Conflict):tx.finish_audio(sid,rid,5)
