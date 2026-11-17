"""Opt-in persona checks against the selected AI API (incurs API usage)."""
import argparse
import json
from intent_parser import parse_intent


CASES = [
    ("我想找市场估值偏低的股票", ["pe_max"], {"pe_max": None}, False),
    ("市盈率低于20倍", ["pe_max"], {"pe_max": 20}, False),
    ("风险低的股票", [], {}, True),
    ("PE小于20，净利润同比超过15%", ["pe_max", "profit_min"], {"pe_max": 20, "profit_min": 15}, False),
    ("我想找潜力股", [], {}, True),
    ("我想找潜力股\n补充说明：我指的是利润比去年增长至少10%的公司", ["profit_min"], {"profit_min": 10}, False),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--provider", choices=["openai", "deepseek"], default="openai")
    args = parser.parse_args()
    failures = 0
    for text, metrics, parameters, clarify in CASES:
        try:
            result = parse_intent(text, provider=args.provider)
            passed = (result["active_metrics"] == metrics and not result["unsupported"] and
                      bool(result["clarifications"]) == clarify and
                      all(result["parameters"][key] == value for key, value in parameters.items()))
            failures += not passed
            print(json.dumps({"input": text, "passed": passed, "result": result}, ensure_ascii=False), flush=True)
        except (RuntimeError, ValueError) as exc:
            failures += 1
            print(json.dumps({"input": text, "passed": False, "error": str(exc)}, ensure_ascii=False), flush=True)
    print(f"Persona live verification: {len(CASES)-failures}/{len(CASES)} passed", flush=True)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
