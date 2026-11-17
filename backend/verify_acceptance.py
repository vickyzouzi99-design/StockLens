"""Explicit opt-in semantic acceptance through the running HTTP application."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import requests

CASES = [
    ('spoken_number', '利润比去年多两成的公司', {'profit_min': 20}, None),
    ('missing_threshold', '市盈率不超过20倍，近期股价波动小', {'pe_max': 20, 'vol_max': None}, None),
    ('or', '市盈率不超过20倍或者ROE至少10%', {}, 'unsupported'),
    ('exclude_industry', '不要银行股，市盈率不超过20倍', {}, 'unsupported'),
    ('chinese_conflict', '市盈率小于十倍，同时大于三十倍', {}, 'conflicts'),
    ('revenue_not_profit', '营收增长至少5%，利润增长至少10%', {'revenue_min': 5, 'profit_min': 10}, None),
    ('vague_risk', '找安全稳健、风险低的股票', {}, 'clarifications'),
    ('clarified_goal', '找潜力股，这里潜力指利润比去年增长至少10%', {'profit_min': 10}, None),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', required=True, action='store_true')
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--provider', choices=['openai', 'deepseek', 'both'], default='both')
    parser.add_argument('--case', action='append')
    parser.add_argument('--output', default='artifacts/semantic-acceptance.json')
    args = parser.parse_args()
    providers = ['openai', 'deepseek'] if args.provider == 'both' else [args.provider]
    cases = [c for c in CASES if not args.case or c[0] in args.case]
    def run(provider):
        rows = []
        for identity, prompt, expected, required in cases:
            row = {'provider': provider, 'case': identity, 'prompt': prompt, 'passed': False}
            try:
                response = requests.post(args.base_url + '/api/interpret', json={'provider': provider, 'text': prompt}, timeout=70)
                data = response.json()
                row['http'] = response.status_code
                row['result'] = data
                if response.ok:
                    if required:
                        row['passed'] = bool(data.get(required))
                    else:
                        row['passed'] = (not any(data.get(k) for k in ['conflicts', 'unsupported', 'clarifications']) and set(data['active_metrics']) == set(expected) and all(data['parameters'].get(k) == v for k, v in expected.items()))
                        if row['passed'] and all(v is not None for v in expected.values()):
                            screened = requests.post(args.base_url + '/api/screen', json=data['parameters'], timeout=10)
                            row['screen_http'] = screened.status_code
                            row['passed'] = screened.ok
                            if screened.ok: row['screen_summary'] = screened.json()['summary']
            except (requests.RequestException, ValueError, KeyError) as exc:
                row['error_type'] = type(exc).__name__
            print(f"{provider} {identity}: {'PASS' if row['passed'] else 'FAIL'}", flush=True)
            rows.append(row)
        return rows
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [row for group in executor.map(run, providers) for row in group]
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'tested_at': datetime.now(timezone.utc).isoformat(), 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"{sum(row['passed'] for row in results)}/{len(results)} passed; report: {path}")
    raise SystemExit(any(not row['passed'] for row in results))


if __name__ == '__main__': main()
