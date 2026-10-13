"""Execute the worker's real shutdown method against fake I/O.

The AST harness keeps this lifecycle contract runnable without paid voice calls
or media SDK startup. CI still runs the project's complete dependency suite.
"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest


def shutdown_method(tx):
    path = Path(__file__).resolve().parents[1] / 'voice_worker.py'
    module = ast.parse(path.read_text(encoding='utf8'))
    cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == 'RestaurantVoice')
    method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'close_failed_voice')
    scope = {'asyncio': asyncio, 'tx': tx, 'CALLS_UNAVAILABLE': 'quota', 'say': lambda _: 'Voice unavailable'}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), scope)
    return scope['close_failed_voice']


def scenario(*, failure=None, separate_pending=False):
    async def run():
        def close_record(*args, **kwargs):
            if failure == 'database':
                raise RuntimeError('database unavailable')
        voice = SimpleNamespace(sid='test-call', pending=None,
            send=AsyncMock(side_effect=RuntimeError('send failed') if failure == 'send' else None),
            media_session=SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError('media failed') if failure == 'media' else None)),
            room=SimpleNamespace(isconnected=lambda: True, disconnect=AsyncMock()))
        async def invoke():
            if not separate_pending:
                voice.pending = asyncio.current_task()
            await shutdown_method(SimpleNamespace(interrupt=close_record))(voice, 'quota')
        pending = asyncio.create_task(asyncio.sleep(30)) if separate_pending else None
        if pending:
            voice.pending = pending
        task = asyncio.create_task(invoke())
        status = 'completed'
        try:
            await task
        except asyncio.CancelledError:
            status = 'cancelled'
        except RuntimeError:
            status = 'failed'
        pending_cancelled = None
        if pending:
            await asyncio.gather(pending, return_exceptions=True)
            pending_cancelled = pending.cancelled()
        return voice, status, pending_cancelled
    return asyncio.run(run())


def test_failing_voice_task_does_not_cancel_its_own_cleanup():
    voice, status, _ = scenario()
    assert status == 'completed'
    voice.send.assert_awaited_once()
    voice.media_session.aclose.assert_awaited_once()
    voice.room.disconnect.assert_awaited_once()


def test_error_handler_still_cancels_a_different_pending_task():
    voice, status, cancelled = scenario(separate_pending=True)
    assert status == 'completed' and cancelled
    voice.room.disconnect.assert_awaited_once()


@pytest.mark.parametrize('failure', ['database', 'send', 'media'])
def test_io_failure_does_not_skip_media_cleanup(failure):
    voice, status, _ = scenario(failure=failure)
    assert status == 'failed'
    voice.media_session.aclose.assert_awaited_once()
    voice.room.disconnect.assert_awaited_once()
