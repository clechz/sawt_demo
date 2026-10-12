"""Verified synthetic fixed phrases; never cache dynamic order summaries."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'data/voice/fixed'


@lru_cache(maxsize=1)
def assets():
    manifest=ROOT/'manifest.json'
    if not manifest.exists():return {}
    result={}
    for row in json.loads(manifest.read_text(encoding='utf8')):
        data=(ROOT/(row['key']+'.pcm')).read_bytes()
        if not row['exact_normalized_match'] or len(data)%2 or hashlib.sha256(data).hexdigest()!=row['sha256']:
            raise ValueError('Invalid fixed speech asset')
        result[(row['text'],row['voice'],row['model'])]=data
    return result


def fixed_pcm(text,voice,model):
    return assets().get((text,voice,model))
