"""Detect impossible numeric bounds; never pick one side of a contradiction."""
import math
import re

ALIASES = {
    'pe_max': r'市盈率|PE(?:\s*TTM)?',
    'profit_min': r'归母净利润(?:同比)?(?:增长率|增长)?|净利润(?:同比)?(?:增长率|增长)?|利润(?:同比)?(?:增长率|增长)',
    'vol_max': r'波动率',
    'pb_max': r'市净率|PB(?:\s*MRQ)?',
    'roe_min': r'净资产收益率|ROE',
    'revenue_min': r'营收(?:同比)?(?:增长率|增长)?|营业收入(?:同比)?(?:增长率|增长)?',
}
LABELS = {'pe_max': '市盈率', 'profit_min': '归母利润增长率', 'vol_max': '波动率',
          'pb_max': '市净率', 'roe_min': '净资产收益率', 'revenue_min': '营收增长率'}
OPS = {'不超过': 'le', '不高于': 'le', '小于等于': 'le', '<=': 'le', '≤': 'le',
       '不低于': 'ge', '不少于': 'ge', '至少': 'ge', '大于等于': 'ge', '>=': 'ge', '≥': 'ge',
       '低于': 'lt', '小于': 'lt', '<': 'lt', '高于': 'gt', '大于': 'gt', '超过': 'gt', '>': 'gt', '等于': 'eq', '=': 'eq'}
BOUND = re.compile('(' + '|'.join(re.escape(op) for op in OPS) + r')\s*([+-]?\d+(?:\.\d+)?)', re.I)


def explicit_bounds(text):
    # Corrections, negations and alternatives need semantic parsing, not a flat AND.
    if re.search(r'或者|或|\bOR\b|不要|不是|改为|改成|取消|去掉|不再|补充说明', text, re.I):
        return []
    result, field = [], None
    for clause in re.split(r'[,，;；。\n]|同时|并且|且', text):
        if not clause.strip():
            continue
        matches = [(match.start(), key, match.end()) for key, pattern in ALIASES.items()
                   for match in re.finditer(pattern, clause, re.I)]
        if matches:
            mentions = []
            for start, key, end in sorted(matches):
                if not mentions or start >= mentions[-1][2]:
                    mentions.append((start, key, end))
            for index, (_, key, end) in enumerate(mentions):
                stop = mentions[index + 1][0] if index + 1 < len(mentions) else len(clause)
                for match in BOUND.finditer(clause[end:stop]):
                    result.append({'metric': key, 'op': OPS[match[1]], 'value': float(match[2])})
            field = mentions[-1][1]
            continue
        elif not BOUND.match(clause.strip()):
            field = None
        if field:
            for match in BOUND.finditer(clause):
                result.append({'metric': field, 'op': OPS[match[1]], 'value': float(match[2])})
    return result


def numeric_conflicts(constraints):
    if not isinstance(constraints, list):
        raise ValueError('AI 的 numeric_constraints 必须是数组')
    bounds = {}
    for item in constraints:
        if not isinstance(item, dict) or item.get('metric') not in ALIASES or item.get('op') not in {'lt', 'le', 'gt', 'ge', 'eq'}:
            raise ValueError('AI 的数值约束格式不正确')
        value = item.get('value')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('AI 的数值约束必须是有限数字')
        group = bounds.setdefault(item['metric'], {'lower': [], 'upper': []})
        if item['op'] in ('gt', 'ge', 'eq'):
            group['lower'].append((value, item['op'] == 'gt'))
        if item['op'] in ('lt', 'le', 'eq'):
            group['upper'].append((value, item['op'] == 'lt'))
    conflicts = []
    for key, group in bounds.items():
        if not group['lower'] or not group['upper']:
            continue
        lo, lo_strict = max(group['lower'])
        hi, hi_strict = min(group['upper'], key=lambda pair: (pair[0], not pair[1]))
        if lo > hi or (lo == hi and (lo_strict or hi_strict)):
            conflicts.append(f"{LABELS[key]}同时要求{'大于' if lo_strict else '不低于'} {lo:g} 和{'小于' if hi_strict else '不超过'} {hi:g}，无法同时满足。请修改其中一项要求。")
    return conflicts
