"""StockLens deterministic AND screener with optional (active-only) conditions.

Snapshot schema: {"metadata": {...}, "stocks": [{...}]}
Uses data already collected by collect_data.py; never asks the LLM for stock values.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

METRICS = {
    "pe_max": ("pe_ttm", "市盈率 PE TTM", "倍"),
    "profit_min": ("parent_net_profit_growth_pct", "归母净利润同比增长率", "%"),
    "vol_max": ("volatility_20d_pct", "近20日波动率", "%"),
    "pb_max": ("pb_mrq", "市净率 PB MRQ", "倍"),
    "roe_min": ("roe_pct", "加权平均净资产收益率", "%"),
    "revenue_min": ("revenue_growth_pct", "营业收入同比增长率", "%"),
}


def _as_float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def build_strategy(params: Mapping[str, Any]) -> dict[str, Any]:
    """Only non-null thresholds are active; all active checks use AND."""
    conditions = []
    for key, (field, label, unit) in METRICS.items():
        threshold = _as_float(params.get(key))
        if threshold is None:
            continue
        operator = "positive_le" if key in ("pe_max", "pb_max") else "ge" if key.endswith("_min") else "le"
        conditions.append({
            "key": key, "field": field, "label": label,
            "operator": operator, "threshold": threshold, "unit": unit,
        })
    if params.get('industry'):
        conditions.append({'key': 'industry', 'field': 'industries', 'label': '同花顺行业',
                           'operator': 'member', 'threshold': params['industry'], 'unit': ''})
    if not conditions:
        raise ValueError("至少启用一个具有明确阈值的筛选条件")
    return {"logic": "AND", "conditions": conditions, "active_metrics": [c["key"] for c in conditions]}


def evaluate_condition(stock: Mapping[str, Any], condition: Mapping[str, Any]) -> dict[str, Any]:
    field = str(condition["field"])
    label = str(condition["label"])
    operator = str(condition["operator"])
    if operator == 'member':
        memberships = stock.get('industries')
        actual = '、'.join(item['name'] for item in memberships) if memberships else '未知'
        passed = any(item['code'] == condition['threshold'] for item in memberships or [])
        selected = condition.get('industry_name', condition['threshold'])
        return {'field': field, 'status': ('PASS' if passed else 'FAIL') if memberships else 'UNKNOWN',
                'actual': None, 'actual_text': actual, 'unit': '',
                'reason': f'同花顺行业实际为 {actual}，要求归属 {selected}。' if memberships else '缺少有效行业分类数据，无法判断行业条件。'}
    threshold = float(condition["threshold"])
    unit = str(condition["unit"])
    actual = _as_float(stock.get(field))

    if actual is None:
        return {
            "field": field, "status": "UNKNOWN", "actual": None, "unit": unit,
            "reason": f"{label}缺少可用数据，无法判断是否满足条件。",
        }
    if operator == "positive_le":
        passed = 0 < actual <= threshold
        requirement = f"0 < {label} ≤ {threshold:g}{unit}"
        if actual <= 0:
            requirement += "（负值或零值不能视为低估值）"
    elif operator == "ge":
        passed = actual >= threshold
        requirement = f"指标 ≥ {threshold:g}{unit}"
    elif operator == "le":
        passed = actual <= threshold
        requirement = f"指标 ≤ {threshold:g}{unit}"
    else:
        raise ValueError(f"不支持的比较运算符：{operator}")

    return {
        "field": field, "status": "PASS" if passed else "FAIL",
        "actual": actual, "unit": unit,
        "reason": f"{label}实际为 {actual:.2f}{unit}，要求 {requirement}。",
    }


def screen_stock(stock: Mapping[str, Any], strategy: Mapping[str, Any]) -> dict[str, Any]:
    checks = [evaluate_condition(stock, c) for c in strategy["conditions"]]
    if any(check["status"] == "FAIL" for check in checks):
        status = "EXCLUDED"
    elif any(check["status"] == "UNKNOWN" for check in checks):
        status = "INSUFFICIENT_DATA"
    else:
        status = "SELECTED"

    return {
        "thscode": stock.get("thscode") or "",
        "ticker": stock.get("ticker") or "",
        "name": stock.get("name") or stock.get("ticker") or stock.get("thscode") or "未知股票",
        "status": status,
        "checks": checks,
        "financial_report": stock.get("financial_report") or "",
        "industries": stock.get('industries'),
        "industry_fetched_at": stock.get('industry_fetched_at'),
        "valuation_timestamp": stock.get("valuation_timestamp"),
        "kline_timestamp": stock.get("kline_timestamp"),
        "sources": stock.get("sources") or {},
        "data_errors": stock.get("errors") or [],
    }


def execute_screen(stocks: list[dict[str, Any]], params: Mapping[str, Any]) -> dict[str, Any]:
    strategy = build_strategy(params)
    for condition in strategy['conditions']:
        if condition['key'] == 'industry':
            condition['industry_name'] = next((item['name'] for row in stocks for item in row.get('industries') or [] if item['code'] == condition['threshold']), condition['threshold'])
    results = [screen_stock(stock, strategy) for stock in stocks]
    summary = {
        "selected": sum(r["status"] == "SELECTED" for r in results),
        "excluded": sum(r["status"] == "EXCLUDED" for r in results),
        "insufficient_data": sum(r["status"] == "INSUFFICIENT_DATA" for r in results),
    }
    return {"strategy": strategy, "summary": summary, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="StockLens 动态条件选股引擎")
    parser.add_argument("--file", default=str(Path(__file__).resolve().parent.parent / "data" / "stock_snapshot_5.json"))
    parser.add_argument("--pe-max", type=float, default=None)
    parser.add_argument("--profit-min", type=float, default=None)
    parser.add_argument("--vol-max", type=float, default=None)
    args = parser.parse_args()
    with Path(args.file).open(encoding="utf-8") as f:
        snapshot = json.load(f)
    result = execute_screen(snapshot["stocks"], {
        "pe_max": args.pe_max, "profit_min": args.profit_min, "vol_max": args.vol_max,
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
