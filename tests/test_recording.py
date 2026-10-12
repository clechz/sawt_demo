import base64
import wave
from sawt.recording import CallRecorder, prune

def test_audit_writer_does_not_block_callback_and_flushes_in_order(tmp_path):
    import threading
    import sqlite3
    from types import SimpleNamespace
    from sawt.recording import AuditWriter
    path=tmp_path/'audit.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE audit(session_id TEXT,at REAL,kind TEXT,payload TEXT)')
    entered=threading.Event();release=threading.Event()
    def connect():
        entered.set()
        assert release.wait(2)
        return sqlite3.connect(path)
    writer=AuditWriter(SimpleNamespace(connect=connect),'s')
    writer.append('first',{'value':1})
    assert entered.wait(2)
    writer.append('second',{'value':2})
    release.set();writer.close()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT kind FROM audit ORDER BY rowid').fetchall()==[('first',),('second',)]

def test_recording_channels_finalize_and_retention(tmp_path):
    recorder=CallRecorder(tmp_path,'call')
    pcm=b'\x00\x00'*2400
    recorder.append('caller',base64.b64encode(pcm).decode())
    recorder.append('generated-assistant',base64.b64encode(pcm*2).decode())
    recorder.close()
    with wave.open(str(tmp_path/'call/caller.wav')) as audio:assert audio.getnframes()==2400
    with wave.open(str(tmp_path/'call/generated-assistant.wav')) as audio:assert audio.getnframes()==4800
    assert prune(tmp_path,7)==0
    assert prune(tmp_path,-1)==1
    assert not (tmp_path/'call').exists()
