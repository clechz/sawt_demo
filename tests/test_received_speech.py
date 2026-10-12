import pytest
from scripts.v2_conversation_review import check_fulfillment_speech


@pytest.mark.parametrize('heard',['تبيه توصيل ولا تستلمه؟','توصيل ولا استلام؟'])
def test_heard_fulfillment_question_matches_saved_bread(heard):
    check_fulfillment_speech(heard)


@pytest.mark.parametrize('heard',['عادي ولا أسمر؟','', 'توصيل ولا استلام، والخبز أسمر؟'])
def test_correct_basket_cannot_hide_wrong_or_missing_spoken_question(heard):
    with pytest.raises(AssertionError):check_fulfillment_speech(heard)
