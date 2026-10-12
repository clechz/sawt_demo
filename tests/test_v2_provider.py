import asyncio
import httpx
import pytest
from sawt.v2_provider import V2Provider
from sawt.provider import ProviderError
from sawt.v2_provider import ProviderQuotaError, CALLS_UNAVAILABLE


@pytest.mark.parametrize('code',['insufficient_quota','credit_balance_exhausted'])
def test_billing_failure_is_actionable_without_leaking_provider_details(code):
    response=httpx.Response(429,json={'error':{'code':code,'message':'secret provider details'}})
    with pytest.raises(ProviderQuotaError) as error:V2Provider.check(response)
    assert str(error.value)==CALLS_UNAVAILABLE


def test_temporary_rate_limit_is_not_reported_as_exhausted_credit():
    with pytest.raises(ProviderError) as error:
        V2Provider.check(httpx.Response(429,json={'error':{'code':'rate_limit_exceeded'}}))
    assert not isinstance(error.value,ProviderQuotaError)


async def test_streaming_speech_reads_error_before_classifying_billing(monkeypatch):
    monkeypatch.setattr('sawt.v2_provider.config',lambda:{'key':'test','tts':'test-tts'})
    provider=V2Provider();provider._loop=asyncio.get_running_loop()
    provider._client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(429,
        stream=httpx.ByteStream(b'{"error":{"code":"credit_balance_exhausted"}}'))))
    try:
        with pytest.raises(ProviderQuotaError):await provider.speak('test')
    finally:await provider.aclose()

def test_pool_reused_and_closed(monkeypatch):
    created=[]
    original=httpx.AsyncClient
    def client(**kwargs):
        result=original(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'ok':True})),**kwargs)
        created.append(result)
        return result
    monkeypatch.setattr('sawt.v2_provider.config',lambda:{'key':'test'})
    monkeypatch.setattr(httpx,'AsyncClient',client)
    async def run():
        provider=V2Provider()
        await provider.request('first');await provider.request('second')
        assert len(created)==1
        await provider.aclose()
        assert created[0].is_closed
        await provider.request('third')
        assert len(created)==2
        await provider.aclose()
    asyncio.run(run())

def test_provider_error_does_not_leak_response_body(monkeypatch):
    monkeypatch.setattr('sawt.v2_provider.config',lambda:{'key':'test'})
    async def run():
        provider=V2Provider();provider._loop=asyncio.get_running_loop()
        provider._client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(401,text='secret-provider-payload')))
        with pytest.raises(ProviderError) as exc:await provider.request('chat/completions')
        assert 'secret-provider-payload' not in str(exc.value)
        await provider.aclose()
    asyncio.run(run())


def test_closing_one_call_does_not_close_another_calls_pool(monkeypatch):
    monkeypatch.setattr('sawt.v2_provider.config',lambda:{'key':'test'})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json={})),**kw))
    async def run():
        first,second=V2Provider(),V2Provider()
        await asyncio.gather(first.request('one'),second.request('two'))
        other_client=second.client()
        await first.aclose()
        assert not other_client.is_closed
        await second.request('still-working')
        assert second.client() is other_client
        await second.aclose()
    asyncio.run(run())


async def test_speech_uses_bounded_idle_timeout_without_shortening_planner(monkeypatch):
    monkeypatch.setattr('sawt.v2_provider.config',lambda:{'key':'test','tts':'test'})
    timeouts=[]
    def handle(request):
        timeouts.append(request.extensions['timeout'])
        return httpx.Response(200,content=b'speech')
    provider=V2Provider();provider._loop=asyncio.get_running_loop()
    provider._client=httpx.AsyncClient(timeout=35,transport=httpx.MockTransport(handle))
    try:
        assert await provider.speak('test')==b'speech'
        await provider.request('other')
        assert timeouts[0]['read']==8 and timeouts[0]['connect']==5
        assert timeouts[1]['read']==35
    finally:await provider.aclose()
