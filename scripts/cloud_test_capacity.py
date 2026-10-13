"""Wait for existing demo capacity; never modify or bypass its limits."""
import asyncio
import time
from sawt.v2_provider import ProviderQuotaError, CALLS_UNAVAILABLE


def assert_provider_available(events):
    """Billing failure is a suite blocker, not a silent-turn timeout to retry."""
    for event in events:
        payload=event.get('payload',{})
        if (event.get('code')=='credit_balance_exhausted'
                or (event.get('fatal') and event.get('message')==CALLS_UNAVAILABLE)
                or (event.get('kind')=='voice.provider_unavailable' and payload.get('reason')=='credit_balance_exhausted')):
            raise ProviderQuotaError('credit_balance_exhausted')
        if event.get('type')=='error' and event.get('fatal'):
            raise RuntimeError('Voice provider failed before the call could continue')


async def create_call(client, wait_seconds=0, *, experience=None):
    deadline=time.monotonic()+wait_seconds
    while True:
        response=await client.post('/api/calls',json={'recording_consent':True,**(experience or {})})
        if response.status_code!=409 or 'Call budget reached' not in response.text:
            response.raise_for_status()
            return response.json()
        remaining=deadline-time.monotonic()
        if remaining<=0:
            response.raise_for_status()
        print('Waiting for existing cloud call capacity; limits unchanged.',flush=True)
        await asyncio.sleep(min(30,remaining))
