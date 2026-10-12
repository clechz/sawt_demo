import hashlib
import json
from unittest.mock import Mock
import pytest
from sawt.conversation import say
from sawt.domain import normalize
from sawt.fixed_voice import assets,fixed_pcm,ROOT
from sawt.v2_provider import V2Provider


def test_fixed_assets_match_the_current_words_and_independent_transcription():
    rows=json.loads((ROOT/'manifest.json').read_text(encoding='utf8'))
    assert {r['key'] for r in rows}=={'audio_check','unclear','goodbye_empty','goodbye_draft','goodbye_handoff'}
    for row in rows:
        assert row['text']==say(row['key'])
        assert normalize(row['independent_transcription'])==normalize(row['text'])
        data=fixed_pcm(row['text'],'marin',row['model'])
        assert data and len(data)==row['bytes'] and len(data)%2==0
        assert hashlib.sha256(data).hexdigest()==row['sha256']
        assert len(data)/48000<6


@pytest.mark.parametrize('key',['audio_check','unclear','goodbye_empty','goodbye_draft','goodbye_handoff','goodbye_confirmed'])
async def test_fixed_pcm_plays_without_provider_network(monkeypatch,key):
    monkeypatch.setattr('sawt.v2_provider.config',lambda:{'tts':'gpt-4o-mini-tts'})
    monkeypatch.setattr('sawt.v2_provider.voice_name',lambda:'marin')
    provider=V2Provider();provider.client=Mock(side_effect=AssertionError('No network for a fixed phrase'))
    data=b''.join([chunk async for chunk in provider.speech_chunks(say(key),'pcm')])
    assert data==fixed_pcm(say(key),'marin','gpt-4o-mini-tts')
    provider.client.assert_not_called()


def test_different_words_voice_or_model_never_get_old_cached_speech():
    assert fixed_pcm('تم تأكيد الطلب','marin','gpt-4o-mini-tts') is None
    assert fixed_pcm(say('goodbye_draft'),'cedar','gpt-4o-mini-tts') is None
    assert fixed_pcm(say('goodbye_draft'),'marin','other-model') is None


def test_corrupt_cached_audio_is_rejected(tmp_path,monkeypatch):
    rows=json.loads((ROOT/'manifest.json').read_text(encoding='utf8'))[:1]
    (tmp_path/'manifest.json').write_text(json.dumps(rows),encoding='utf8')
    (tmp_path/(rows[0]['key']+'.pcm')).write_bytes(b'corrupt')
    assets.cache_clear();monkeypatch.setattr('sawt.fixed_voice.ROOT',tmp_path)
    try:
        with pytest.raises(ValueError):assets()
    finally:assets.cache_clear()
