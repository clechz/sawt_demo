import asyncio
import httpx
import pytest
from sawt.v2_provider import V2Provider
from sawt.provider import ProviderError

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
