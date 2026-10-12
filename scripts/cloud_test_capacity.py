"""Wait for existing demo capacity; never modify or bypass its limits."""
import asyncio
import time


async def create_call(client, wait_seconds=0):
    deadline=time.monotonic()+wait_seconds
    while True:
        response=await client.post('/api/calls',json={'recording_consent':True})
        if response.status_code!=409 or 'Call budget reached' not in response.text:
            response.raise_for_status()
            return response.json()
        remaining=deadline-time.monotonic()
        if remaining<=0:
            response.raise_for_status()
        print('Waiting for existing cloud call capacity; limits unchanged.',flush=True)
        await asyncio.sleep(min(30,remaining))
