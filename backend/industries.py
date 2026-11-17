"""Industry identifiers come only from the snapshot's Fuyao/THS memberships."""
import re


def clean_memberships(items):
    if not isinstance(items, list):
        return None
    found = {}
    for item in items:
        if not isinstance(item, dict) or item.get('type') != 'industry':
            return None
        code, name = item.get('thscode'), item.get('name')
        if not isinstance(code, str) or not re.fullmatch(r'\d{6}\.TI', code) or not isinstance(name, str) or not name.strip():
            return None
        if code in found and found[code] != name.strip():
            return None
        found[code] = name.strip()
    return [{'code': code, 'name': name} for code, name in sorted(found.items())] or None


def catalog(stocks):
    found = {}
    for row in stocks:
        for item in row.get('industries') or []:
            entry = found.setdefault(item['code'], {'code': item['code'], 'name': item['name'], 'count': 0})
            entry['count'] += 1
    return sorted(found.values(), key=lambda item: item['name'])
