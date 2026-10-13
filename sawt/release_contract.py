"""Shared API/worker contract: detect version/config drift before inviting speech.

This is a compatibility check, not cryptographic remote attestation or an audio
quality score. It includes no credentials. The API persists its expectation in
call state, and the worker computes its own facts from its deployed files.
"""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    'voice_worker.py', 'sawt/hospitality_voice.py', 'sawt/hospitality_runtime.py',
    'sawt/conversation_policy.py', 'sawt/conversation_requirements.py',
    'sawt/choice_permissions.py', 'sawt/release_contract.py',
    'sawt/domain.py', 'sawt/transactions.py', 'sawt/choices.py',
    'sawt/experience.py', 'sawt/hospitality.py', 'sawt/v2_provider.py',
    'sawt/provider.py', 'sawt/recognition.py', 'sawt/audio_gate.py',
    'sawt/reply_evidence.py',
    'data/hospitality-profile.json', 'data/restaurant-menu-complex.csv',
)
FIELDS = ('protocol', 'source_fingerprint', 'experience_version', 'conversation_mode',
          'voice', 'planner_model', 'voice_model')


def source_fingerprint(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name in SOURCE_FILES:
        try:
            data = (root / name).read_bytes()
        except OSError as exc:
            raise RuntimeError('Incomplete release package: ' + name) from exc
        # Git on Windows and Linux may materialize identical source with
        # different newlines. The immutable CSV stays byte-exact.
        if not name.endswith('.csv'):
            data = data.replace(b'\r\n', b'\n')
        digest.update(name.encode('utf8') + b'\0' + hashlib.sha256(data).digest())
    return digest.hexdigest()


@lru_cache(maxsize=1)
def deployed_fingerprint() -> str:
    return source_fingerprint()


def worker_contract(experience: dict) -> dict:
    from .conversation_policy import conversation_mode
    return {'protocol': 1, 'source_fingerprint': deployed_fingerprint(),
            'experience_version': experience['version'],
            'conversation_mode': conversation_mode(experience.get('conversation_mode')),
            'voice': experience['voice'],
            'planner_model': os.getenv('LLM_MODEL', 'gpt-4.1'),
            'voice_model': 'gpt-live-1'}


def check_worker_contract(required: dict, actual: dict) -> None:
    if not isinstance(required, dict) or not isinstance(actual, dict):
        raise ValueError('Missing worker compatibility contract')
    for key in FIELDS:
        if key not in required or key not in actual or required[key] != actual[key]:
            raise ValueError('Worker compatibility mismatch: ' + key)
    fingerprint = actual.get('source_fingerprint')
    if (actual['protocol'] != 1 or not isinstance(fingerprint, str) or len(fingerprint) != 64
            or any(c not in '0123456789abcdef' for c in fingerprint)):
        raise ValueError('Invalid worker compatibility contract')
