from pathlib import Path
import pytest
from sawt.domain import Engine, Menu, new_state, RuleError
from sawt.transactions import StagedEngine

@pytest.fixture
def setup():
    engine = Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))
    return StagedEngine(engine, check_choices=True), new_state()

def shawarma(engine, state, text, options):
    return engine.act(state, 'add_item', {'item_id':'sandwiches_08','quantity':1,'options':options,'notes':''}, utterance='شاورما لحم '+text)

@pytest.mark.parametrize('bread',['saj','brioche','lettuce'])
def test_unavailable_brown_is_not_replaced_by_valid_bread(setup,bread):
    engine,state=setup
    result=shawarma(engine,state,'وجبة شاورما لحم، بيتا لا لا معليش خبز بر',{'meal':['meal'],'bread':[bread],'spice_level':['not_spicy']})
    assert state['basket'][0]['options']=={'meal':['meal'],'bread':[],'spice_level':[]}
    assert result['choice_guard']
    engine.act(state,'checkout',{})
    assert state['quote'] is None

def test_brown_is_allowed_for_item_that_actually_has_it(setup):
    engine,state=setup
    engine.act(state,'add_item',{'item_id':'breakfast_01','quantity':1,'options':{'bread':['brown'],'portion':['large']},'notes':''},utterance='شكشوكة كبير بخبز بر')
    assert state['basket'][0]['options']=={'bread':['brown'],'portion':['large']}


@pytest.mark.parametrize('text,bread',[
    ('أبي شكشوكة كبير، تميس وتوصيل.','tamees'),
    ('عطني شكشوكة صاج استلام','saj'),
    ('أبغى شكشوكة حجم عادي مع خبز أسمر','brown')])
def test_clear_single_dish_bread_is_not_lost_when_planner_omits_group(setup,text,bread):
    engine,state=setup
    engine.act(state,'add_item',{'item_id':'breakfast_01','quantity':1,'options':{},'notes':''},utterance=text)
    assert state['basket'][0]['options'].get('bread')==[bread]


@pytest.mark.parametrize('text',[
    'أبي شكشوكة كبير وتميس بالعسل','أبي شكشوكة مع فول صاج',
    'أبي شكشوكة بدون تميس','أبي شكشوكة تميس ولا صاج؟',
    'هل عندكم شكشوكة مع تميس؟','أبي شكشوكة مع تميس إذا كان مجاني'])
def test_missing_bread_is_not_filled_from_mixed_negated_or_conditional_order(setup,text):
    engine,state=setup
    engine.act(state,'add_item',{'item_id':'breakfast_01','quantity':1,'options':{},'notes':''},utterance=text)
    assert not state['basket'][0]['options'].get('bread')


def test_single_dish_fast_path_commits_validated_state_without_a_model(setup,tmp_path,monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from sawt import v2_runtime as runtime
    from sawt.transactions import Transactions
    staged,_=setup;tx=Transactions(tmp_path/'fast.db',staged.engine);sid,_=tx.create()
    monkeypatch.setattr(runtime,'tx',tx)
    provider=SimpleNamespace(chat=AsyncMock(side_effect=AssertionError('No planner required')))
    result=asyncio.run(runtime.delegate(sid,'أبي شكشوكة كبير، تميس وتوصيل.','fast',0,voice_provider=provider))
    assert result['state']['basket'][0]['options']=={'portion':['large'],'bread':['tamees']}
    assert result['state']['service']=='delivery' and result['state']['total']==3000
    assert not result['state']['quote'] and not result['state']['order_id']
    assert 'مدينة' in result['reply'] and 'حي' in result['reply']
    provider.chat.assert_not_awaited()


@pytest.mark.parametrize('text',[
    'أبي اثنين شكشوكة كبير تميس وتوصيل','أبي 2 شكشوكة كبير تميس وتوصيل',
    'أبي شكشوكة كبير تميس ومعها شاي','أبي شكشوكة كبير بدون تميس',
    'أبي شكشوكة كبير تميس لو السعر مجاني','هل عندكم شكشوكة كبير تميس؟',
    'خلها شكشوكة كبير تميس','أبي شكشوكة كبير تميس وصاج',
    'أبي شكشوكة كبير تميس توصيل الرياض حي النرجس'])
def test_single_dish_fast_path_defers_nonmatching_requests(setup,text):
    from sawt.choices import simple_order
    engine,state=setup
    assert simple_order(engine.menu,state,text) is None


def test_single_dish_fast_path_does_not_duplicate_an_existing_basket(setup):
    from sawt.choices import simple_order
    engine,state=setup
    engine.act(state,'add_item',{'item_id':'breakfast_01','quantity':1,'options':{},'notes':''},utterance='شكشوكة')
    assert simple_order(engine.menu,state,'أبي شكشوكة كبير تميس وتوصيل') is None

def test_negated_heat_does_not_authorize_hot(setup):
    engine,state=setup
    shawarma(engine,state,'وجبة مع صاج بدون حار',{'meal':['meal'],'bread':['saj'],'spice_level':['hot']})
    assert state['basket'][0]['options']['spice_level']==[]

def test_correction_clears_previously_valid_bread(setup):
    engine,state=setup
    shawarma(engine,state,'وجبة بصاج بدون حار',{'meal':['meal'],'bread':['saj'],'spice_level':['not_spicy']})
    line=state['basket'][0]
    engine.act(state,'update_item',{'line_id':line['line_id'],'options':{'bread':['brioche']}},utterance='لا خله خبز بر')
    assert line['options']['bread']==[]
    assert line['options']['spice_level']==['not_spicy']

def test_unrelated_quantity_update_preserves_known_choices(setup):
    engine,state=setup
    shawarma(engine,state,'وجبة صاج حار',{'meal':['meal'],'bread':['saj'],'spice_level':['hot']})
    line=state['basket'][0]
    engine.act(state,'update_item',{'line_id':line['line_id'],'quantity':2,'options':line['options']},utterance='خله اثنين')
    assert line['quantity']==2 and line['options']['bread']==['saj']

def test_correction_cannot_keep_old_choice_against_explicit_new_choice(setup):
    engine,state=setup
    shawarma(engine,state,'وجبة صاج حار',{'meal':['meal'],'bread':['saj'],'spice_level':['hot']})
    line=state['basket'][0]
    engine.act(state,'update_item',{'line_id':line['line_id'],'options':{'bread':['saj']}},utterance='بدل الصاج بريوش')
    assert not line['options']['bread']


def test_short_choice_only_for_unambiguous_complete_label(setup):
    from sawt.choices import short_choice
    engine,state=setup
    engine.act(state,'add_item',{'item_id':'breakfast_01','quantity':1,'options':{},'notes':''},utterance='شكشوكة')
    assert short_choice(engine.menu,state,'كبير')['options']=={'portion':['large']}
    assert short_choice(engine.menu,state,'نعم') is None
    assert short_choice(engine.menu,state,'لا كبير') is None
    assert short_choice(engine.menu,state,'كبير ولا عادي؟') is None
    state['basket'].append(dict(state['basket'][0]))
    assert short_choice(engine.menu,state,'كبير') is None


def test_no_cheese_does_not_authorize_cheese_extra(setup):
    engine,state=setup
    shawarma(engine,state,'وجبة صاج حار بدون جبن',{'meal':['meal'],'bread':['saj'],'spice_level':['hot'],'extras':['cheese']})
    assert state['basket'][0]['options']['extras']==[]


def test_adani_cannot_silently_become_another_tea(setup):
    staged,state=setup
    for item in staged.menu.items.values():
        if item['category_id']=='beverages':
            with pytest.raises(RuleError,match='العدني'):
                staged.act(state,'add_item',{'item_id':item['id'],'quantity':3,'options':{},'notes':''},utterance='أبي ثلاثة شاي عدني')
    assert not state['basket']
    staged.act(state,'add_item',{'item_id':'beverages_09','quantity':3,'options':{},'notes':''},utterance='ماشي كرك بدال العدني')
    assert state['basket'][0]['item_id']=='beverages_09'


def test_repeated_saved_crust_is_recognized_after_question_moves_on(setup):
    from sawt.choices import short_choice
    staged,state=setup
    staged.act(state,'add_item',{'item_id':'pizza_flatbread_07','quantity':1,'options':{'size':['large'],'crust':['stuffed']},'notes':''},utterance='بيتزا شاورما كبير محشو بجبن')
    args=short_choice(staged.menu,state,'ماشي محشوب جبن')
    assert args['options']=={'crust':['stuffed']}
    staged.act(state,'update_item',args,utterance='ماشي محشوب جبن')
    assert state['basket'][0]['options']['crust']==['stuffed']
    for text in ['ماشي محشوب جبن؟','لا محشوب جبن','ماشي محشوب جبن وشيل الثانية']:
        assert short_choice(staged.menu,state,text) is None
