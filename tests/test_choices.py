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
