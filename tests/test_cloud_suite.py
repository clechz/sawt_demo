import json
import os
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


@pytest.mark.parametrize('error',['Unexpected worker release','credit_balance_exhausted'])
def test_release_or_billing_failure_stops_even_when_independent_failures_can_continue(monkeypatch,tmp_path,error):
    monkeypatch.setattr(suite,'ROOT',tmp_path)
    monkeypatch.setattr(sys,'argv',['suite','--release','expected','--continue-on-failure'])
    monkeypatch.setattr(suite,'preflight',AsyncMock())
    run=Mock(return_value=SimpleNamespace(returncode=1,stdout='',stderr=error))
    monkeypatch.setattr(suite.subprocess,'run',run)
    assert suite.main()==1
    run.assert_called_once()
    report=json.loads(next((tmp_path/'runtime/cloud-suite').glob('*/suite.json')).read_text())
    assert not report['passed'] and len(report['steps'])==1


def test_failed_checkout_never_reuses_previous_success_file(monkeypatch,tmp_path):
    monkeypatch.setattr(suite,'ROOT',tmp_path)
    monkeypatch.setattr(sys,'argv',['suite','--release','expected','--continue-on-failure'])
    monkeypatch.setattr(suite,'preflight',AsyncMock())
    (tmp_path/'runtime').mkdir()
    old=tmp_path/'runtime/cloud-acceptance.json'
    old.write_text('{"passed":true}')
    os.utime(old,(1,1))
    run=Mock(side_effect=[SimpleNamespace(returncode=1 if i==3 else 0,stdout='',stderr='') for i in range(4)])
    monkeypatch.setattr(suite.subprocess,'run',run)
    assert suite.main()==1
    folder=next((tmp_path/'runtime/cloud-suite').iterdir())
    assert not (folder/'checkout.json').exists()
    report=json.loads((folder/'suite.json').read_text())
    assert 'skipped' in report['steps'][-1] and not report['passed']
