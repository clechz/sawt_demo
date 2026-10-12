import pytest
from sawt.spoken_numbers import integer_words


@pytest.mark.parametrize('number,expected',[
    (0,'صفر'),(18,'ثمانية عشر'),(36,'ستة وثلاثين'),(117,'مئة وسبعة عشر'),
    (2000,'ألفين'),(3215,'ثلاثة آلاف ومئتين وخمسة عشر'),(1000001,'مليون وواحد')])
def test_spoken_money_integer_preserves_each_place_value(number,expected):
    assert integer_words(number)==expected


@pytest.mark.parametrize('invalid',[-1,18.5])
def test_speech_renderer_cannot_round_or_drop_a_sign(invalid):
    with pytest.raises(ValueError):integer_words(invalid)
