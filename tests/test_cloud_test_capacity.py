import httpx
import pytest
from unittest.mock import AsyncMock
from scripts import cloud_test_capacity as capacity


def response(status,body):
    return httpx.Response(status,json=body,request=httpx.Request('POST','https://example.test/api/calls'))

async def test_capacity_wait_retries_only_budget_conflict(monkeypatch):
    monkeypatch.setattr(capacity.asyncio,'sleep',AsyncMock())
    client=AsyncMock()
    client.post.side_effect=[response(409,{'detail':'Call budget reached: at most 2 active calls and 20 starts/hour'}),response(200,{'id':'synthetic'})]
    assert await capacity.create_call(client,60)=={'id':'synthetic'}
    assert client.post.await_count==2
    for call in client.post.await_args_list:
        assert call.args==('/api/calls',) and call.kwargs=={'json':{'recording_consent':True}}

@pytest.mark.parametrize('status,body',[(401,{'detail':'Unauthorized'}),(409,{'detail':'Different conflict'}),(500,{'detail':'Error'})])
async def test_unrelated_failures_are_not_retried_or_hidden(status,body):
    client=AsyncMock();client.post.return_value=response(status,body)
    with pytest.raises(httpx.HTTPStatusError):await capacity.create_call(client,60)
    assert client.post.await_count==1

async def test_zero_wait_retains_capacity_failure():
    client=AsyncMock();client.post.return_value=response(409,{'detail':'Call budget reached'})
    with pytest.raises(httpx.HTTPStatusError):await capacity.create_call(client,0)
