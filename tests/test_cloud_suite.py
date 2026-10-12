import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from scripts import v2_cloud_suite as suite
from sawt.v2_provider import ProviderQuotaError


@pytest.mark.parametrize('quota,failed_step,expected_calls',[(True,None,0),(False,0,1),(False,2,3),(False,None,5)])
def test_cloud_runner_stops_on_failure_and_records_incomplete_gates(monkeypatch,tmp_path,quota,failed_step,expected_calls):
    monkeypatch.setattr(suite,'ROOT',tmp_path)
    monkeypatch.setattr(sys,'argv',['suite','--release','expected-release'])
    monkeypatch.setattr(suite,'preflight',AsyncMock(side_effect=ProviderQuotaError('unavailable') if quota else None))
    results=[SimpleNamespace(returncode=1 if i==failed_step else 0,stdout='',stderr='') for i in range(5)]
    run=Mock(side_effect=results);monkeypatch.setattr(suite.subprocess,'run',run)
    code=suite.main()
    report=json.loads(next((tmp_path/'runtime/cloud-suite').glob('*/suite.json')).read_text())
    assert run.call_count==expected_calls
    assert report['passed']==(not quota and failed_step is None)
    assert code==(2 if quota else 1 if failed_step is not None else 0)
    for call in run.call_args_list:
        assert call.kwargs['env']['SAWT_EXPECT_WORKER_RELEASE']=='expected-release'
