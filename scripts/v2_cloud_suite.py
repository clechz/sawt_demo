"""PAID sequential cloud call checks; no browser or human recordings.

Stops on the first failed gate. All logs remain in ignored runtime files.
Passing synthetic fixtures does not certify native accent or production quality.
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sawt.v2_provider import V2Provider, ProviderQuotaError
from sawt.provider import config


async def preflight():
    provider=V2Provider()
    try:
        await provider.request('chat/completions',json={'model':config()['llm'],
            'messages':[{'role':'user','content':'Reply OK'}],'max_tokens':2})
    finally:
        await provider.aclose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True,help='Exact expected worker release')
    args=parser.parse_args()
    output=ROOT/'runtime/cloud-suite'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True)
    report={'expected_worker_release':args.release,'browser':'none','passed':False,'steps':[]}
    env={**os.environ,'SAWT_EXPECT_WORKER_RELEASE':args.release,'PYTHONIOENCODING':'utf-8'}
    steps=[
        ('received-speech','v2_conversation_review.py',['--output',str(output/'received-speech.json')]),
        ('journeys','v2_cloud_journeys.py',['--output',str(output/'journeys.json'),'--wait-for-capacity-seconds','120']),
        ('interruptions','v2_cloud_interruptions.py',['--output',str(output/'interruptions.json')]),
        ('checkout','v2_cloud_acceptance.py',['--wait-for-capacity-seconds','120']),
        ('storage','verify_cloud_persistence.py',[]),
    ]
    try:
        try:
            asyncio.run(preflight())
        except ProviderQuotaError:
            report['blocked']='OpenAI credit_balance_exhausted; restore API credit before retesting.'
            print(report['blocked'],flush=True)
            return 2
        for name,script,extra in steps:
            print('Running '+name,flush=True)
            result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts'/script),*extra],
                cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf8',errors='replace')
            (output/(name+'.log')).write_text(result.stdout+result.stderr,encoding='utf8')
            report['steps'].append({'name':name,'exit_code':result.returncode})
            print(result.stdout,flush=True)
            if name in ('checkout','storage'):
                source=ROOT/'runtime'/('cloud-acceptance.json' if name=='checkout' else 'cloud-persistence.json')
                if source.exists():shutil.copyfile(source,output/(name+'.json'))
            if result.returncode:
                print('Failed '+name+'; inspect '+str(output/(name+'.log')),flush=True)
                return result.returncode
        report['passed']=True
        return 0
    except Exception as error:
        report['error_type']=type(error).__name__
        raise
    finally:
        (output/'suite.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print('Reports: '+str(output),flush=True)


if __name__=='__main__':
    raise SystemExit(main())
