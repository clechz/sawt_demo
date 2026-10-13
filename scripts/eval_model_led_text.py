"""Bounded real-provider text evaluation, never a microphone or audio-quality score.

Run in a trusted environment with OPENAI_API_KEY already configured:
    python scripts/eval_model_led_text.py --mode model_led --repeat 3
    python scripts/eval_model_led_text.py --mode legacy --repeat 3
No credentials are printed or saved. Uses isolated SQLite and synthetic caller
text. A missing key or failed provider is a blocked/failed result, never a pass.
The held-out set and native-speaker listening evaluation remain separate gates.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sawt.domain import Engine, Menu, new_state
from sawt.hospitality_runtime import prepare_turn, commit_turn
from sawt.provider import config, ProviderError
from sawt.transactions import Transactions, encode
from sawt.v2_provider import V2Provider

CASES = (
    ('information_not_order', [
        'المضغوط اللحم موجود؟ أنا أسأل بس، لا تضيف لي شيء.'], 'unchanged'),
    ('messy_correction_and_rice', [
        'لا لا، الدجاج ما أبيه. لحم مكانه، وخليها ثلاث، لا تضيف طلب ثاني.',
        'الرز اختاره أنت، الشطة خفيفة، والحجم لا تختاره للحين.'], 'corrected'),
    ('negated_delegation', [
        'لا تختار الرز عني، بس علمني وش الأنواع الموجودة.'], 'no_options'),
    ('scoped_delegation', [
        'اختار لي الرز بس، لا تختار الحجم ولا الشطة.'], 'rice_only'),
    ('revoked_delegation', [
        'اختار لي الرز.',
        'غيرت رأيي، لا تختار عني مرة ثانية، خل الرز أبيض.'], 'override'),
    ('contextual_short_answer', ['إيه مناسب.'], 'short_answer'),
)


class BudgetedProvider(V2Provider):
    def __init__(self, max_calls):
        super().__init__()
        self.max_calls = max_calls
        self.calls = 0

    async def chat(self, messages, tools):
        if self.calls >= self.max_calls:
            raise ProviderError('Evaluation provider-call budget exhausted')
        self.calls += 1
        return await super().chat(messages, tools)


def initial_state(engine, name):
    state = new_state()
    engine.act(state, 'add_item', {'item_id': 'rice_05', 'quantity': 1, 'options': {}, 'notes': ''})
    if name == 'contextual_short_answer':
        # Scenario setup supplies an actual previous question. No generated audio
        # or receipt is fabricated; this is deliberately a text-only test.
        state['history'] = [{'role': 'assistant', 'content': 'أقترح الرز الأصلي، يناسبك؟'}]
    return state


def check_case(kind, initial, state):
    items = state['basket']
    checks = {'one_line': len(items) == 1, 'no_unrequested_order': not state.get('order_id'),
              'no_unrequested_fulfillment': state['service'] is None and state['branch'] is None,
              'line_identity_preserved': bool(items) and items[0]['line_id'] == initial['basket'][0]['line_id']}
    if not items:
        return checks
    line = items[0]
    options = line['options']
    if kind == 'unchanged':
        checks['basket_unchanged'] = items == initial['basket']
    elif kind == 'corrected':
        checks.update(meat=line['item_id'] == 'rice_06', quantity=line['quantity'] == 3,
                      rice=bool(options.get('rice')), mild=options.get('spice_level') == ['mild'],
                      portion_unselected=not options.get('portion'))
    elif kind == 'no_options':
        checks['no_options_selected'] = not options
    elif kind in ('rice_only', 'short_answer'):
        checks['only_rice_selected'] = set(options) == {'rice'}
        if kind == 'short_answer':
            checks['correct_previous_proposal'] = options.get('rice') == ['original']
    elif kind == 'override':
        checks['latest_choice_wins'] = options.get('rice') == ['white']
        checks['unrelated_options_unchanged'] = set(options) == {'rice'}
        grants = state.get('choice_permissions', {}).get(line['line_id'], {})
        checks['no_active_rice_delegation'] = grants.get('rice', {}).get('status') != 'active'
    return checks


async def evaluate(args):
    report = {'scope': 'real-provider text, synthetic cases, isolated SQLite; not received audio or Saudi-listener evidence',
              'mode': args.mode, 'planner_model': config()['llm'], 'passed': False,
              'status': 'blocked', 'cases': [], 'provider_calls': 0,
              'menu_sha256': hashlib.sha256((ROOT/'data/restaurant-menu-complex.csv').read_bytes()).hexdigest()}
    if not config()['key']:
        report['blocker'] = 'OPENAI_API_KEY is not available in this test environment'
        return report
    engine = Engine(Menu(ROOT/'data/restaurant-menu-complex.csv'))
    provider = BudgetedProvider(args.max_provider_calls)
    try:
        with tempfile.TemporaryDirectory(prefix='sawt-model-eval-') as tmp:
            tx = Transactions(Path(tmp)/'calls.db', engine)
            for repeat in range(args.repeat):
                for name, turns, kind in CASES:
                    sid, _ = tx.create()
                    initial = initial_state(engine, name)
                    with tx.connect() as db:
                        db.execute('UPDATE calls SET state=? WHERE id=?', (encode(initial), sid))
                    case = {'name': name, 'repeat': repeat+1, 'turns': [], 'passed': False}
                    try:
                        for i, text in enumerate(turns):
                            started = time.perf_counter()
                            prepared = await asyncio.wait_for(prepare_turn(engine, provider, tx.load(sid), text,
                                conversation_mode=args.mode), timeout=40)
                            result = await commit_turn(tx, sid, f'{name}-{repeat}-{i}', prepared)
                            case['turns'].append({'caller': text, 'reply': result['reply'],
                                'seconds': round(time.perf_counter()-started, 3),
                                'tools': [op['tool'] for op in prepared.operations],
                                'requires_acoustic_verification_in_voice': prepared.requires_verification})
                        case['checks'] = check_case(kind, initial, tx.load(sid)['state'])
                        case['passed'] = all(case['checks'].values())
                    except Exception as exc:
                        # Do not log provider response bodies, URLs or credentials.
                        case['error_type'] = type(exc).__name__
                    finally:
                        tx.interrupt(sid, close=True)
                    report['cases'].append(case)
                    if provider.calls >= args.max_provider_calls:
                        report['blocker'] = 'Evaluation provider-call budget exhausted'
                        return report
        report['passed'] = len(report['cases']) == len(CASES)*args.repeat and all(c['passed'] for c in report['cases'])
        report['status'] = 'passed' if report['passed'] else 'failed'
        return report
    finally:
        report['provider_calls'] = provider.calls
        await provider.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['legacy', 'model_led'], default='model_led')
    parser.add_argument('--repeat', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--max-provider-calls', type=int, default=60)
    parser.add_argument('--output', type=Path, default=ROOT/'runtime/model-led-text-eval.json')
    args = parser.parse_args()
    if not 1 <= args.max_provider_calls <= 300:
        parser.error('--max-provider-calls must be between 1 and 300')
    report = asyncio.run(evaluate(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'status': report['status'], 'passed': report['passed'],
                      'provider_calls': report['provider_calls'], 'report': str(args.output)}))
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
