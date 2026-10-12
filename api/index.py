"""Vercel entry point: expose only the authenticated caller surface."""
import os
os.environ.setdefault('SAWT_RUNTIME_DIR', '/tmp/sawt')
if not os.getenv('DATABASE_URL'):
    raise RuntimeError('Cloud deployment requires DATABASE_URL; local storage is disabled.')
from private_demo import app
