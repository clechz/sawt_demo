import sys
from types import SimpleNamespace
from unittest.mock import Mock
from sawt import cloud_storage


def test_cloud_recordings_are_always_private(monkeypatch,tmp_path):
    monkeypatch.setenv('BLOB_READ_WRITE_TOKEN','test-only')
    put=Mock();get=Mock(return_value=SimpleNamespace(content=b'RIFF'))
    monkeypatch.setitem(sys.modules,'vercel.blob',SimpleNamespace(put=put,get=get,BlobNotFoundError=FileNotFoundError))
    path=tmp_path/'caller.wav';path.write_bytes(b'RIFF')
    cloud_storage.upload(path,'call-id')
    assert put.call_args.args[0]=='calls/call-id/caller.wav'
    assert put.call_args.kwargs['access']=='private'
    assert cloud_storage.download('call-id','caller.wav')==b'RIFF'
    assert get.call_args.kwargs['access']=='private'


def test_local_mode_never_uploads_without_cloud_configuration(monkeypatch,tmp_path):
    monkeypatch.delenv('BLOB_READ_WRITE_TOKEN',raising=False)
    put=Mock();monkeypatch.setitem(sys.modules,'vercel.blob',SimpleNamespace(put=put))
    cloud_storage.upload(tmp_path/'missing.wav','call-id')
    put.assert_not_called()
