import copy
from pathlib import Path
import pytest
from sawt.domain import BRANCHES, Engine, Menu, RuleError, explicit_confirmation, new_state, normalize, requests_human

@pytest.fixture(scope='session')
def menu(): return Menu(Path(__file__).resolve().parents[1] / 'data/restaurant-menu-complex.csv')

@pytest.fixture
def engine(menu): return Engine(menu)

def valid_options(item):
    return {gid: list(g['options'])[:g['min']] for gid,g in item['groups'].items() if g['min']}

def ready(engine, branch='ruh_narjis', item_id=None):
    state = new_state()
    if item_id is None: item_id = next(i['id'] for i in engine.menu.items.values() if branch in i['available'])
    engine.act(state, 'set_location', {'city': BRANCHES[branch]['city'], 'zone': BRANCHES[branch]['zones'][0], 'address': 'شارع التجربة، مبنى ١٢'})
    item = engine.menu.get(item_id)
    engine.act(state, 'add_item', {'item_id': item_id, 'quantity': 2, 'options': valid_options(item), 'notes': 'بدون بصل'})
    return state

def test_fixture(menu):
    assert (len(menu.items), menu.row_count, len(menu.columns)) == (144,1728,20)
    assert len({i['category_id'] for i in menu.items.values()}) == 12

@pytest.mark.parametrize('item_index', range(144))
def test_every_item_option_price_and_constraints(menu, item_index):
    item = list(menu.items.values())[item_index]
    opts = valid_options(item)
    line = {'item_id':item['id'],'line_id':'x','quantity':2,'options':opts,'notes':''}
    expected = 2*(item['base']+sum(item['groups'][g]['options'][o]['delta'] for g,os in opts.items() for o in os))
    result=menu.validate_line(line,item['available'][0] if item['available'] else None)
    assert result['line_total']==expected
    assert not result['missing']
    for gid,g in item['groups'].items():
        for oid,option in g['options'].items():
            candidate=copy.deepcopy(line);candidate['options'][gid]=[oid]
            got=menu.validate_line(candidate)
            expected_delta=sum(item['groups'][g2]['options'][o]['delta'] for g2,os in candidate['options'].items() for o in os)
            assert got['unit_price']==item['base']+expected_delta

def test_delivery_to_pickup_clears_fee_address_quote(engine):
    s=ready(engine);engine.act(s,'checkout',{});before=engine.view(s)
    engine.act(s,'set_service',{'service':'pickup'});after=engine.view(s)
    assert after['delivery_fee']==0 and s['location'] is None and s['quote'] is None
    assert after['subtotal']==before['subtotal'] and after['total']==before['total']-before['delivery_fee']

def test_pickup_to_delivery_requires_fresh_location(engine):
    s=ready(engine);engine.act(s,'set_service',{'service':'pickup'});engine.act(s,'set_service',{'service':'delivery'})
    assert engine.view(s)['issues'] and s['location'] is None

def test_location_change_revalidates_availability_and_eta(engine):
    item=next(i for i in engine.menu.items.values() if 'ruh_narjis' in i['available'] and 'ruh_olaya' not in i['available'])
    s=ready(engine,item_id=item['id']);engine.act(s,'checkout',{})
    engine.act(s,'set_location',{'city':'الرياض','zone':'العليا','address':'عنوان جديد'})
    v=engine.view(s)
    assert v['branch_id']=='ruh_olaya' and v['delivery_fee']==1200 and v['eta_minutes']==35
    assert v['basket'][0]['available'] is False and s['quote'] is None
    assert 'error' in engine.act(s,'checkout',{})

def test_unsupported_correction_cannot_keep_old_address(engine):
    s=ready(engine);result=engine.act(s,'set_location',{'city':'الرياض','zone':'بعيد','address':'عنوان جديد'})
    assert result['error'] and s['location'] is None and s['branch'] is None

def test_update_remove_after_quote_requires_new_confirmation(engine):
    s=ready(engine);engine.act(s,'checkout',{});s['quote']['presented']=True
    engine.act(s,'update_item',{'line_id':s['basket'][0]['line_id'],'quantity':1})
    assert s['quote'] is None
    with pytest.raises(RuleError):engine.act(s,'confirm',{},can_confirm=True)
    engine.act(s,'remove_item',{'line_id':s['basket'][0]['line_id']})
    assert not s['basket'] and 'error' in engine.act(s,'checkout',{})

@pytest.mark.parametrize('quantity',[0,-1,21,1.5,'٢',True])
def test_invalid_quantity_no_mutation(engine,quantity):
    s=ready(engine);before=copy.deepcopy(s)
    with pytest.raises(RuleError):engine.act(s,'update_item',{'line_id':s['basket'][0]['line_id'],'quantity':quantity})
    assert s==before

def test_required_options_block_checkout(engine):
    s=new_state();engine.act(s,'set_service',{'service':'pickup'});engine.act(s,'set_branch',{'branch_id':'ruh_narjis'})
    engine.act(s,'add_item',{'item_id':'chicken_01','quantity':1,'options':{}})
    assert engine.view(s)['basket'][0]['missing'] and 'error' in engine.act(s,'checkout',{})

@pytest.mark.parametrize('options',[{'fake':['x']},{'portion':['fake']},{'portion':['regular','large']},{'portion':['regular','regular']},{'portion':'regular'}])
def test_invalid_modifiers(engine,options):
    s=new_state()
    with pytest.raises(RuleError):engine.act(s,'add_item',{'item_id':'chicken_01','quantity':1,'options':options})
    assert not s['basket']

def test_early_items_preserved(engine):
    s=new_state();engine.act(s,'add_item',{'item_id':'chicken_01','quantity':1,'options':{}})
    assert len(s['basket'])==1 and s['branch'] is None
    engine.act(s,'set_location',{'city':'الرياض','zone':'النرجس','address':'شارع ٢'})
    assert len(s['basket'])==1

def test_confirm_requires_readback_delivery_and_explicit_gate(engine):
    s=ready(engine)
    with pytest.raises(RuleError):engine.act(s,'confirm',{},can_confirm=True)
    engine.act(s,'checkout',{})
    with pytest.raises(RuleError):engine.act(s,'confirm',{},can_confirm=True)
    s['quote']['presented']=True
    with pytest.raises(RuleError):engine.act(s,'confirm',{},can_confirm=False)
    first=engine.act(s,'confirm',{},can_confirm=True)
    second=engine.act(s,'confirm',{},can_confirm=True)
    assert first['order_id']==second['order_id']

def test_no_edits_after_order(engine):
    s=ready(engine);engine.act(s,'checkout',{});s['quote']['presented']=True;engine.act(s,'confirm',{},can_confirm=True)
    with pytest.raises(RuleError):engine.act(s,'remove_item',{'line_id':s['basket'][0]['line_id']})

@pytest.mark.parametrize('phase',['empty','basket','quote','confirmed'])
def test_handoff_anytime(engine,phase):
    s=new_state() if phase=='empty' else ready(engine)
    if phase in ['quote','confirmed']:engine.act(s,'checkout',{})
    if phase=='confirmed':s['quote']['presented']=True;engine.act(s,'confirm',{},can_confirm=True)
    result=engine.act(s,'handoff',{'reason':'شكوى'})
    assert result['terminal'] and s['handoff'] and s['quote'] is None
    with pytest.raises(RuleError):engine.act(s,'add_item',{'item_id':'chicken_01','quantity':1,'options':{}})

@pytest.mark.parametrize('text',['نعم','إيه','موافق','أكد الطلب','اعتمد الطلب'])
def test_clear_confirmations(text):assert explicit_confirmation(text)

@pytest.mark.parametrize('text',['نعم بس احذف وجبة','لا','ممكن','تمام غير العنوان','لا تؤكد الطلب','yes remove one'])
def test_ambiguous_or_modified_confirmations(text):assert not explicit_confirmation(text)

def test_arabic_normalization_and_search(menu):
    assert normalize('أَبِي ٢ وجبة')==normalize('ابي 2 وجبه')
    assert menu.search('Shakshuka')['items'][0]['id']=='breakfast_01'
    assert menu.search('شكشوكه')['items'][0]['id']=='breakfast_01'
    assert len(menu.search('')['items'])==5

def test_readback_contains_details_and_fee(engine):
    s=ready(engine);v=engine.view(s);text=engine.act(s,'checkout',{})['reply']
    assert v['basket'][0]['name'] in text and 'بدون بصل' in text and '15.00' in text and 'هل تؤكد الطلب' in text

def test_delivery_branch_cannot_be_overridden(engine):
    s=ready(engine)
    with pytest.raises(RuleError):engine.act(s,'set_branch',{'branch_id':'jed_rawdah'})

@pytest.mark.parametrize('text',['ما أبي موظف','لا تحولني','ما عندي شكوى','ما أبي أكلم موظف','بدون خدمة العملاء'])
def test_negated_handoff_deferred_to_model(text):
    assert not requests_human(text)

@pytest.mark.parametrize('text',['أبي موظف','عندي شكوى','لو سمحت حولني','أبغى أكلم موظف'])
def test_clear_handoff_shortcut(text):
    assert requests_human(text)

@pytest.mark.parametrize('city,zone,branch',[('مدينة الرياض','حي النرجس','ruh_narjis'),('الرياض','حَيّ العُلْيَا','ruh_olaya'),('مدينه جده','حي الروضه','jed_rawdah'),('الرياض','حي حطين','ruh_malqa')])
def test_spoken_place_prefixes(engine,city,zone,branch):
    s=new_state()
    engine.act(s,'set_location',{'city':city,'zone':zone,'address':'شارع ١٢'})
    assert s['branch']==branch
    assert s['location']['zone'] in BRANCHES[branch]['zones']

@pytest.mark.parametrize('city,zone',[('أبها','خارج النطاق'),('الرياض','الملقا')])
def test_incomplete_address_correction_clears_previous_destination(engine,city,zone):
    s=ready(engine);basket=copy.deepcopy(s['basket'])
    result=engine.act(s,'set_location',{'city':city,'zone':zone,'address':''})
    assert result['error'] and s['location'] is None and s['basket']==basket
    assert 'error' in engine.act(s,'checkout',{})

@pytest.mark.parametrize('size',['large_meal','large meal','Large','كبير','وجبة كبيرة'])
def test_size_alias_and_sauce_removal_are_atomic(engine,size):
    s=ready(engine,item_id='chicken_01');line=s['basket'][0]
    engine.act(s,'update_item',{'line_id':line['line_id'],'options':{'sauce':['garlic']}})
    result=engine.act(s,'update_item',{'line_id':line['line_id'],'options':{'portion':[size],'sauce':[]}})
    assert result['basket'][0]['options']['portion']==['large']
    assert result['basket'][0]['options']['sauce']==[]
    assert result['basket'][0]['unit_price']==4600

def test_model_confirmation_question_always_gets_authoritative_readback(engine):
    from sawt.agent import Agent
    s=ready(engine)
    s,result=Agent(engine,None).finish(s,'هذا كل طلبي','المجموع 1 ريال. هل تؤكد الطلب؟',[])
    assert s['quote'] and not s['quote']['presented']
    assert result['reply']==engine.summary(s)
    assert result['events'][-1]['source']=='readback_guard'
