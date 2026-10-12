"""Private recording objects; local paths are only temporary working files."""
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta


def enabled():
    return bool(os.getenv('BLOB_READ_WRITE_TOKEN'))


def upload(path, sid):
    if not enabled():
        return
    from vercel.blob import put
    path = Path(path)
    with path.open('rb') as source:
        put(f'calls/{sid}/{path.name}', source, access='private',
            overwrite=True, add_random_suffix=False)


def download(sid, filename):
    from vercel.blob import get, BlobNotFoundError
    try:
        return get(f'calls/{sid}/{filename}', access='private', use_cache=False).content
    except BlobNotFoundError:
        return None


def prune(days=7):
    if not enabled():
        return 0
    from vercel.blob import list_objects, delete
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cursor = None
    removed = 0
    while True:
        page = list_objects(prefix='calls/', limit=1000, cursor=cursor)
        old = [blob.url for blob in page.blobs if blob.uploaded_at < cutoff]
        if old:
            delete(old)
            removed += len(old)
        if not page.has_more:
            return removed
        cursor = page.cursor
