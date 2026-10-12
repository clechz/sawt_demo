import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sawt.agent import Agent
from sawt.domain import Engine, Menu, new_state
from sawt.provider import ProviderError

def call(name,args,id):
    return {'id':id,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}

def run(messages):
    engine=Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))
    provider=SimpleNamespace(supports_tool_batches=True,chat=AsyncMock(side_effect=messages))
    original=new_state()
    state,reply=asyncio.run(Agent(engine,provider).turn(original,'أبي شكشوكة عادي صاج استلام من النرجس'))
    return original,state,reply,provider

def test_batch_applies_in_order_with_each_result_and_no_duplicate_add():
    add=call('add_item',{'item_id':'breakfast_01','quantity':1,'options':{'portion':['regular'],'bread':['saj']},'notes':''},'a')
    duplicate={**add,'id':'b'}
    original,state,reply,provider=run([
        {'tool_calls':[call('set_service',{'service':'pickup'},'s'),call('set_branch',{'branch_id':'ruh_narjis'},'r'),add,duplicate]},
        {'content':'باقي شي؟'}])
    assert state['service']=='pickup' and state['branch']=='ruh_narjis'
    assert len(state['basket'])==1 and state['basket'][0]['quantity']==1
    assert not original['basket'] and not state['order_id']
    assert provider.chat.await_count==2
    messages=provider.chat.call_args_list[-1].args[0]
    assert [m['tool_call_id'] for m in messages if m['role']=='tool']==['s','r','a','b']

def test_mixed_confirmation_batch_executes_nothing():
    original,state,reply,_=run([
        {'tool_calls':[call('set_service',{'service':'pickup'},'s'),call('confirm',{},'c')]},
        {'content':'نحتاج تفاصيل الطلب.'}])
    assert state['service'] is None and state['order_id'] is None and not reply['events']

def test_invalid_option_in_batch_cannot_enter_state():
    _,state,reply,_=run([
        {'tool_calls':[call('set_service',{'service':'pickup'},'s'),call('add_item',{'item_id':'breakfast_01','quantity':1,'options':{'bread':['invented']},'notes':''},'a')]},
        {'content':'وش نوع الخبز؟'}])
    assert not state['basket'] and any(e['result'].get('error') for e in reply['events'])

def test_provider_failure_after_batch_does_not_mutate_original():
    engine=Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))
    original=new_state()
    provider=SimpleNamespace(supports_tool_batches=True,chat=AsyncMock(side_effect=[
        {'tool_calls':[call('set_service',{'service':'pickup'},'s'),call('set_branch',{'branch_id':'ruh_narjis'},'b')]},ProviderError('offline')]))
    with pytest.raises(ProviderError):asyncio.run(Agent(engine,provider).turn(original,'استلام النرجس'))
    assert original['service'] is None and original['revision']==0


def test_service_change_cannot_be_claimed_without_tool_call():
    engine=Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))
    provider=SimpleNamespace(supports_tool_batches=True,chat=AsyncMock(side_effect=[
        {'content':'تم تغيير الخدمة إلى التوصيل.'},
        {'tool_calls':[call('set_service',{'service':'delivery'},'s'),call('set_delivery_details',{'city':'الطائف','zone':'الحلقة'},'a')]},
        {'content':'ما نوصل للمنطقة.'}]))
    state,reply=asyncio.run(Agent(engine,provider).turn(new_state(),'غيرها توصيل للطائف حي الحلقة'))
    assert state['service']=='delivery' and state['location'] is None
    assert any(e['tool']=='set_delivery_details' for e in reply['events'])


def test_service_change_does_not_count_as_saving_requested_food():
    _,state,reply,provider=run([
        {'tool_calls':[call('set_service',{'service':'pickup'},'s'),call('search_menu',{'query':'شكشوكة'},'q')]},
        {'content':'أي فرع؟'},
        {'tool_calls':[call('add_item',{'item_id':'breakfast_01','quantity':1,'options':{'portion':['regular'],'bread':['saj']},'notes':''},'a')]},
        {'content':'أي فرع؟'}])
    assert len(state['basket'])==1 and provider.chat.await_count==4


def test_empty_full_address_saves_partial_fields():
    engine=Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))
    provider=SimpleNamespace(supports_tool_batches=True,chat=AsyncMock(side_effect=[
        {'tool_calls':[call('set_location',{'city':'الرياض','zone':'النرجس','address':''},'l')]},
        {'content':'واسم الشارع ورقم المبنى؟'}]))
    state,reply=asyncio.run(Agent(engine,provider).turn(new_state(),'الرياض النرجس'))
    assert state['delivery_details']=={'city':'الرياض','zone':'النرجس'}
    assert state['location'] is None and reply['events'][0]['tool']=='set_delivery_details'
