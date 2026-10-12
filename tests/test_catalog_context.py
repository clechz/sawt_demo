import copy
from sawt.catalog_context import retrieve
from sawt.v2_runtime import engine
from sawt.domain import new_state


def test_shawarma_candidates_include_both_proteins_without_selecting_either():
    state=new_state();before=copy.deepcopy(state)
    found=retrieve(engine.menu,'طال عمرك أبغى شاورما',state)
    ids={item['id'] for item in found['menu_candidates']['items']}
    assert {'sandwiches_07','sandwiches_08'}<=ids
    assert len(ids)<=5 and state==before


def test_unavailable_qualifier_is_not_proof_of_catalog_availability():
    found=retrieve(engine.menu,'أبي ثلاثة شاي عدني',new_state())
    assert found['candidate_warning'] and 'عدني' not in found['matched_words']
    assert not any('عدني' in item['name'] for item in found['menu_candidates']['items'])


def test_no_full_menu_or_irrelevant_lookup_for_a_short_option_or_greeting():
    assert not retrieve(engine.menu,'كبير',new_state())
    assert not retrieve(engine.menu,'هلا كيف حالك',new_state())


def test_branch_context_is_authoritative_but_never_sets_a_branch():
    state=new_state();found=retrieve(engine.menu,'فرع النرجس بالرياض',state)
    assert 'ruh_narjis' in found['branches'] and not state['branch']


def test_protein_followup_retrieves_shawarma_from_last_question():
    state=new_state();state['history']=[{'role':'assistant','content':'الشاورما دجاج ولا لحم؟'}]
    found=retrieve(engine.menu,'دجاج ساندويتش بصاج بدون حار',state)
    assert 'sandwiches_07' in {i['id'] for i in found['menu_candidates']['items']}


def test_unique_karak_is_identified_but_shawarma_and_adani_stay_ambiguous():
    assert retrieve(engine.menu,'عطني كرك بدال العدني',new_state())['unique_current_name_word']
    assert not retrieve(engine.menu,'أبي شاورما',new_state())['unique_current_name_word']
    assert not retrieve(engine.menu,'أبي شاي عدني',new_state())['unique_current_name_word']


async def test_exact_pizza_request_cannot_end_with_only_a_missing_size_question():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from sawt.agent import Agent
    from tests.test_tool_batches import call
    provider=SimpleNamespace(supports_tool_batches=True,chat=AsyncMock(side_effect=[
        {'content':'بيتزا شاورما تحتاج تحدد الحجم والعجينة ودرجة الحرارة. أي حجم تفضل؟'},
        {'tool_calls':[call('add_item',{'item_id':'pizza_flatbread_07','quantity':1,'options':{},'notes':''},'add'),call('finish_draft',{},'finish')]}]))
    state,reply=await Agent(engine,provider).turn(new_state(),'عطني بيتزا شاورما.')
    assert len(state['basket'])==1 and state['basket'][0]['item_id']=='pizza_flatbread_07'
    assert state['pending_choice']['group_id']=='size' and not state['order_id']
