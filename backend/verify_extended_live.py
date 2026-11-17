"""Opt-in integration checks using real provider calls and the current snapshot."""
import argparse
import json
from app import load_snapshot
from industries import catalog
from intent_parser import parse_intent
from screen_engine import execute_screen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--provider', choices=['openai', 'deepseek'], default='openai')
    args = parser.parse_args()
    snapshot = load_snapshot()
    industries = catalog(snapshot['stocks'])
    cases = [
        ('市盈率小于10倍，同时大于30倍', 'conflict'),
        ('市净率不超过2倍，净资产收益率至少8%，营收同比增长至少5%', 'financial'),
        ('只看银行股', 'industry'),
        ('银行股，市净率不超过2倍，净资产收益率至少8%', 'combined'),
        ('找科技板块未来必涨的股票', 'unsupported'),
        ('市盈率小于10倍，改成不超过30倍', 'correction'),
    ]
    failures = 0
    for text, kind in cases:
        try:
            result = parse_intent(text, args.provider, industries)
            if kind == 'conflict':
                passed = bool(result['conflicts'])
            elif kind == 'unsupported':
                passed = bool(result['unsupported'])
            else:
                expected = {'financial': {'pb_max': 2, 'roe_min': 8, 'revenue_min': 5},
                            'combined': {'pb_max': 2, 'roe_min': 8}, 'industry': {}, 'correction': {'pe_max': 30}}[kind]
                passed = (not result['conflicts'] and not result['unsupported'] and not result['clarifications']
                          and set(result['active_metrics']) == set(expected)
                          and all(result['parameters'][key] == value for key, value in expected.items()))
                if kind in ('industry', 'combined'):
                    passed = passed and result['industry'] == next(item['code'] for item in industries if item['name'] == '银行')
                if passed:
                    result['screen_summary'] = execute_screen(snapshot['stocks'], {**result['parameters'], 'industry': result['industry']})['summary']
            failures += not passed
            print(json.dumps({'input': text, 'passed': passed, 'result': result}, ensure_ascii=False), flush=True)
        except Exception as exc:
            failures += 1
            print(json.dumps({'input': text, 'passed': False, 'error': str(exc)}, ensure_ascii=False), flush=True)
    print(f'{len(cases)-failures}/{len(cases)} passed', flush=True)
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
