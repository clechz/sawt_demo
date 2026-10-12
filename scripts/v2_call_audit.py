"""Read-only call metrics. No transcripts, addresses, audio or credentials in output.

Review flags describe incomplete or suspicious flows, not automatic quality grades.
"""
import argparse
import json
import math
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def distribution(values):
    values = sorted(values)
    if not values:
        return {'n': 0, 'p50_ms': None, 'p95_ms': None, 'worst_ms': None}
    return {'n': len(values), 'p50_ms': statistics.median(values),
            'p95_ms': values[math.ceil(.95 * len(values)) - 1], 'worst_ms': values[-1]}


def audit(database):
    # mode=ro avoids creating or mutating the production database.
    with sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        calls = []
        for call in db.execute('SELECT id,created,closed,state FROM calls ORDER BY created DESC'):
            events = [{**dict(e), 'payload': json.loads(e['payload'])} for e in db.execute(
                'SELECT at,kind,payload FROM audit WHERE session_id=? ORDER BY sequence', (call['id'],))]
            counts = Counter(e['kind'] for e in events)
            if not counts['voice.connected']:
                continue
            state = json.loads(call['state'])
            backend = [e['payload']['duration_ms'] for e in events if e['kind'] == 'delegation.completed']
            tts = [e['payload']['tts_ms'] for e in events if e['kind'] == 'readback.generated']
            first_bytes = [e['payload']['tts_first_byte_ms'] for e in events if e['kind'] == 'readback.first_byte']
            starts = {e['payload']['receipt_id']: e['at'] - e['payload']['tts_first_byte_ms']/1000
                      for e in events if e['kind'] == 'readback.first_byte'}
            browser_start = [round((e['at']-starts[e['payload']['receipt_id']])*1000) for e in events
                             if e['kind'] == 'playback.started' and e['payload']['receipt_id'] in starts]
            errors = sorted({e['payload'].get('error_type') or
                             e['payload'].get('error', {}).get('code', 'unspecified')
                             for e in events if e['kind'] in ('error', 'delegation.failed', 'readback.failed')})
            review = []
            if errors:
                review.append('provider_or_backend_error')
            if counts['readback.generated'] and not counts['playback.completed']:
                review.append('no_complete_readback_receipt: interruption, playback failure or hangup needs review')
            if counts['voice.connected'] and not counts['transcript.user']:
                review.append('no_user_transcript: silent call or input/startup failure needs review')
            if state.get('order_id') and not counts['playback.completed']:
                review.append('CRITICAL: order_without_recorded_playback_completion')
            calls.append({'call_id': call['id'], 'created_utc': datetime.fromtimestamp(call['created'], timezone.utc).isoformat(),
                          'closed': bool(call['closed']), 'confirmed_order': bool(state.get('order_id')),
                          'basket_lines': len(state.get('basket', [])), 'counts': dict(counts),
                          'backend': distribution(backend), 'readback_generation': distribution(tts),
                          'readback_first_byte': distribution(first_bytes),
                          'readback_browser_start': distribution(browser_start),
                          'error_codes': errors, 'review_flags': review})
    return {'generated_utc': datetime.now(timezone.utc).isoformat(),
            'notes': ['Backend timings exclude the transcript settlement wait and client playback.',
                      'P95 uses nearest rank; small samples are descriptive, not a production SLO.',
                      'No completed order can mean an intentional abandonment, not a failed test.',
                      'Browser start is a server-timed onplaying acknowledgement, not a microphone measurement.',
                      'Accent, semantic correctness and actual first useful heard audio are not graded here.'],
            'calls': calls}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'runtime/v2.sqlite3')
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime/call-quality.json')
    args = parser.parse_args()
    report = audit(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(f"Audited {len(report['calls'])} voice calls. Local report: {args.output}")
