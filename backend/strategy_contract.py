"""Validate the existing frontend strategy schema before account persistence."""
import json
import math
from datetime import datetime
from fastapi import HTTPException

RULES = {'pe_max': ('positive_le', '倍', 0, 100000), 'pb_max': ('positive_le', '倍', 0, 100000),
         'vol_max': ('le', '%', 0, 1000), 'profit_min': ('ge', '%', -10000, 10000),
         'roe_min': ('ge', '%', -10000, 10000), 'revenue_min': ('ge', '%', -10000, 10000)}


def validate_library(items):
    try:
        if len(json.dumps(items)) > 250000: raise ValueError()
        ids, clean = set(), []
        for item in items:
            if item.get('schemaVersion') != 2 or not isinstance(item.get('id'), str) or not 1 <= len(item['id']) <= 80 or item['id'] in ids: raise ValueError()
            ids.add(item['id'])
            if not isinstance(item.get('name'), str) or not 1 <= len(item['name'].strip()) <= 60: raise ValueError()
            if not isinstance(item.get('query'), str) or len(item['query']) > 500 or item.get('provider') not in ('openai', 'deepseek'): raise ValueError()
            for field in ('createdAt', 'updatedAt'): datetime.fromisoformat(item[field].replace('Z', '+00:00'))
            snapshot = item['snapshot']
            if snapshot['universeId'] != 'CSI300' or snapshot['conditionLogic'] != 'AND': raise ValueError()
            industry = snapshot['industry']
            import re
            if industry is not None and (not isinstance(industry, str) or not re.fullmatch(r'\d{6}\.TI', industry)): raise ValueError()
            conditions = snapshot['conditions']
            if len(conditions) != 6 or {c['metricId'] for c in conditions} != set(RULES): raise ValueError()
            rows = []
            for c in conditions:
                op, unit, lo, hi = RULES[c['metricId']]
                if type(c['enabled']) is not bool or c['operator'] != op or c['unit'] != unit: raise ValueError()
                value = c['value']
                if value is None:
                    if c['enabled']: raise ValueError()
                elif type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi or (op == 'positive_le' and value == 0): raise ValueError()
                rows.append({k: c[k] for k in ('metricId', 'enabled', 'operator', 'unit', 'value')})
            if not industry and not any(c['enabled'] for c in rows): raise ValueError()
            clean.append({**{k: item[k] for k in ('schemaVersion', 'id', 'name', 'query', 'provider', 'createdAt', 'updatedAt')}, 'snapshot': {'universeId': 'CSI300', 'conditionLogic': 'AND', 'industry': industry, 'conditions': rows}})
        return clean
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(422, '策略格式、指标或阈值无效，未覆盖已有数据。') from None
