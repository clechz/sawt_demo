"""Local, bounded audio capture; provider output is NOT a playback receipt."""
import base64
import json
import queue
import threading
import time
import wave
import logging
from pathlib import Path


class AuditWriter:
    """Diagnostic writes never block audio callbacks; business commits stay synchronous."""
    def __init__(self, transactions, sid):
        self.transactions, self.sid = transactions, sid
        self.queue = queue.Queue(maxsize=4000)
        self.closed = False
        self.dropped = 0
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def append(self, kind, payload):
        if self.closed: return
        try:
            self.queue.put_nowait((time.time(), kind, json.dumps(payload,ensure_ascii=False)))
        except queue.Full:
            self.dropped += 1

    def _write(self):
        while True:
            item = self.queue.get()
            if item is None: return
            batch = [item]
            stopping = False
            # Amortize SQLite commits instead of competing with an interruption
            # transaction for every caption/audio-output token.
            time.sleep(.05)
            while len(batch)<100:
                try: item = self.queue.get_nowait()
                except queue.Empty: break
                if item is None:
                    stopping = True
                    break
                batch.append(item)
            try:
                with self.transactions.connect() as db:
                    db.executemany('INSERT INTO audit(session_id,at,kind,payload) VALUES(?,?,?,?)',[(self.sid,*record) for record in batch])
            except Exception:
                logging.getLogger('sawt').exception('Unable to persist queued voice diagnostic')
            if stopping: return

    def close(self):
        if self.closed: return
        self.closed = True
        self.queue.put(None,timeout=5)
        self.thread.join(timeout=5)


class CallRecorder:
    def __init__(self, root, sid, rate=24000):
        self.path = Path(root) / sid
        self.path.mkdir(parents=True, exist_ok=True)
        self.rate = rate
        self.queue = queue.Queue(maxsize=1000)
        self.dropped = 0
        self.closed = False
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def append(self, channel, encoded):
        if self.closed:
            return
        try:
            self.queue.put_nowait((channel, encoded))
        except queue.Full:
            self.dropped += 1

    def _write(self):
        files = {}
        try:
            for name in ['caller', 'generated-assistant']:
                stream = wave.open(str(self.path / (name + '.wav')), 'wb')
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(self.rate)
                files[name] = stream
            while True:
                item = self.queue.get()
                if item is None:
                    break
                channel, encoded = item
                files[channel].writeframesraw(base64.b64decode(encoded))
        finally:
            for stream in files.values():
                stream.close()
            (self.path / 'capture.json').write_text(json.dumps({
                'closed_at': time.time(), 'dropped_chunks': self.dropped,
                'sample_rate': self.rate,
                'output_semantics': 'Provider-generated audio, including muted/unheard portions. Use playback timeline and controlled-readback files to audit delivery.'
            }, indent=2), encoding='utf8')

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.queue.put(None, timeout=5)
        self.thread.join(timeout=5)


def prune(root, days=7):
    """Remove only known capture artifacts older than retention; never follow links."""
    root = Path(root).resolve()
    if not root.exists():
        return 0
    removed = 0
    for directory in root.iterdir():
        if directory.is_symlink() or not directory.is_dir() or directory.resolve().parent != root:
            continue
        manifest = directory / 'capture.json'
        if not manifest.is_file() or manifest.stat().st_mtime > time.time() - days * 86400:
            continue
        for file in directory.iterdir():
            if file.is_file() and not file.is_symlink() and file.suffix in ('.wav', '.mp3', '.json'):
                file.unlink()
        if not any(directory.iterdir()):
            directory.rmdir(); removed += 1
    return removed
