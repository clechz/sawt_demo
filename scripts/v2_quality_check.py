"""One-command offline regression and call audit; --live also makes paid model calls."""
import argparse
import subprocess
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Also run paid backend and real-call replay evaluations; playback is simulated')
    args = parser.parse_args()
    output = ROOT / 'runtime/qa' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True)
    commands = [[sys.executable, '-m', 'pytest', '-q', '--junitxml=' + str(output / 'tests.xml')]]
    node = shutil.which('node')
    if not node:
        raise SystemExit('Node.js is required for the browser playback regression suite.')
    commands.append([node, '--experimental-default-type=module', '--test', 'tests/playback.test.mjs', 'tests/audio-meter.test.mjs', 'tests/call-status.test.mjs', 'tests/call-start.test.mjs'])
    if (ROOT / 'runtime/v2.sqlite3').exists():
        commands.append([sys.executable, 'scripts/v2_call_audit.py', '--output', str(output / 'call-quality.json')])
    if args.live:
        commands.append([sys.executable, 'scripts/v2_backend_eval.py', '--output', str(output / 'backend-eval.json')])
        commands.append([sys.executable, 'scripts/v2_call_regression.py', '--output', str(output / 'call-regression.json')])
        commands.append([sys.executable, 'scripts/v2_release_replay.py', '--output', str(output / 'release-live-replay.json')])
    failed = False
    for index, command in enumerate(commands):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf8', errors='replace')
        (output / f'{index+1}.log').write_text(result.stdout + result.stderr, encoding='utf8')
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, end='')
            failed = True
    print('Reports:', output)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
