"""Fuyao -> validated, atomic snapshots. Importing never calls an API."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import tempfile
import time
import uuid
import requests
from dotenv import load_dotenv
from industries import clean_memberships

ROOT = Path(__file__).resolve().parent.parent
SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
CORE_FIELDS = ("pe_ttm", "parent_net_profit_growth_pct", "volatility_20d_pct", "pb_mrq", "roe_pct", "revenue_growth_pct")


def data_directory():
    path = Path(os.getenv("STOCKLENS_DATA_DIR", "data"))
    return path if path.is_absolute() else ROOT / path


def to_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value.strip().replace(",", "").removesuffix("%") if isinstance(value, str) else value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".pending-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


@contextmanager
def refresh_lock(directory):
    """OS lock releases on crashes; one writer across manual/worker processes."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "refresh.lock").open("a+b") as handle:
        try:
            # fstat does not read the locked byte on Windows. Reading it would
            # fail before the intended non-blocking lock acquisition.
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("已有数据更新任务运行中") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class ApiError(RuntimeError):
    pass


class FuyaoClient:
    def __init__(self, api_key, interval=0.5):
        if not api_key:
            raise ApiError("未配置 FUYAO_API_KEY")
        self.session = requests.Session()
        self.session.headers["X-api-key"] = api_key
        self.interval = max(0.3, interval)
        self.previous_request = 0.0

    def get(self, path, params):
        for attempt in range(4):
            time.sleep(max(0, self.interval - (time.monotonic() - self.previous_request)))
            self.previous_request = time.monotonic()
            try:
                response = self.session.get("https://fuyao.aicubes.cn" + path, params=params, timeout=(10, 45))
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.RequestException("retryable HTTP response")
                if not response.ok:
                    raise ApiError(f"{path}: HTTP {response.status_code}")
                result = json.loads(response.content.decode("utf-8"))
                if not isinstance(result, dict):
                    raise ApiError(f"{path}: 响应结构错误")
                if result.get("code") in (4001, 5002, 5003):
                    raise requests.RequestException("retryable business response")
                if result.get("code") != 0:
                    raise ApiError(f"{path}: 业务错误 {result.get('code')}")
                if not isinstance(result.get("data"), dict):
                    raise ApiError(f"{path}: 缺少 data 对象")
                return result
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise ApiError(f"{path}: 网络或数据错误，已重试4次") from None
                time.sleep(2 ** (attempt + 1))
        raise ApiError("请求未完成")


def batches(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def trading_days(client, start, end):
    result = client.get("/api/a-share/calendar/trading-days", {
        "start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d")})
    rows = result["data"].get("item")
    if not isinstance(rows, list):
        raise ApiError("交易日历缺少 item 数组；不猜测交易日")
    days = set()
    for row in rows:
        try:
            day = datetime.strptime(row["date"], "%Y%m%d").date()
        except (KeyError, TypeError, ValueError):
            raise ApiError("交易日历日期格式无效") from None
        if start <= day <= end:
            days.add(day)
    return sorted(days), result.get("request_id")


def report_candidates(now):
    current = now.year * 4 + (now.month - 1) // 3
    return [f"{(current - offset) // 4}-{(current - offset) % 4 + 1}" for offset in range(1, 5)]


def clean_bars(bars, now):
    by_day, conflicts, rejected = {}, set(), 0
    for bar in bars:
        if not isinstance(bar, dict):
            rejected += 1
            continue
        stamp, close = to_number(bar.get("date_ms")), to_number(bar.get("close_price"))
        try:
            day = datetime.fromtimestamp(stamp / 1000, SHANGHAI).date() if stamp is not None else None
        except (OverflowError, OSError, ValueError):
            day = None
        if day is None or close is None or close <= 0:
            rejected += 1
            continue
        if day > now.date() or (day == now.date() and (now.hour, now.minute) < (15, 0)):
            rejected += 1
            continue
        if day in by_day and by_day[day]["close_price"] != close:
            conflicts.add(day)
        by_day[day] = {"date_ms": int(datetime.combine(day, datetime.min.time(), SHANGHAI).timestamp() * 1000), "close_price": close}
    return [by_day[day] for day in sorted(by_day) if day not in conflicts], rejected + len(conflicts)


def calculate_volatility(bars):
    if len(bars) < 21:
        return None
    closes = [bar["close_price"] for bar in bars[-21:]]
    value = statistics.stdev([(b / a - 1) * 100 for a, b in zip(closes, closes[1:])])
    return round(value, 4) if math.isfinite(value) else None


def indexed_rows(result, allowed):
    rows = result["data"].get("item")
    if not isinstance(rows, list):
        raise ApiError("响应缺少 item 数组")
    lookup, duplicates = {}, set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("thscode", "")).strip().upper()
        if code not in allowed:
            continue
        if code in lookup and lookup[code] != row:
            duplicates.add(code)
        lookup[code] = row
    return {code: row for code, row in lookup.items() if code not in duplicates}


def collect_snapshot(client, limit=300, now=None, progress=print):
    now = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    if not 1 <= limit <= 300:
        raise ValueError("采集数量必须在1至300之间")
    started = datetime.now(timezone.utc).isoformat()
    days, calendar_id = trading_days(client, now.date() - timedelta(days=180), now.date())
    completed = [day for day in days if day < now.date() or (now.hour, now.minute) >= (15, 0)]
    if len(completed) < 21:
        raise ApiError("交易日历覆盖不足21个完整交易日")
    expected_days = completed[-21:]
    progress("获取沪深300成分股")
    pool = client.get("/api/a-share-index/constituents/ths-stock-list", {"thscode": "000300.SH"})
    items = pool["data"].get("item")
    if not isinstance(items, list):
        raise ApiError("成分股列表结构错误")
    unique = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("thscode", "")).strip().upper()
        if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code):
            unique.setdefault(code, item)
    if len(unique) < limit:
        raise ApiError(f"成分股仅{len(unique)}只，小于目标{limit}；不发布缩水快照")
    codes = list(unique)[:limit]
    records = {code: {"thscode": code, "ticker": code.split(".")[0], "name": unique[code].get("name") or code,
                      "financial_report": None, "errors": [], "sources": {"pool_request_id": pool.get("request_id")},
                      **{field: None for field in CORE_FIELDS}, "industries": None} for code in codes}
    progress("采集同花顺行业分类")
    for group in batches(codes, 100):
        try:
            result = client.get("/api/a-share-index/constituents/ths-index-list-by-stock", {"thscode": ",".join(group), "type": "industry"})
            lookup = indexed_rows(result, group)
            for code in group:
                row = records[code]
                row['industries'] = clean_memberships(lookup.get(code, {}).get('index_list'))
                row['industry_fetched_at'] = datetime.now(timezone.utc).isoformat()
                row['sources']['industry_request_id'] = result.get('request_id')
                if row['industries'] is None:
                    row['errors'].append('行业关系缺失或无效，不能判断行业条件')
        except ApiError as exc:
            for code in group:
                records[code]['errors'].append(str(exc))
    progress(f"采集{len(codes)}只股票的估值")
    for group in batches(codes, 100):
        try:
            result = client.get("/api/a-share/valuations/snapshot", {"thscodes": ",".join(group)})
            lookup = indexed_rows(result, group)
            for code in group:
                row = records[code]
                for field in ("pe_ttm", "pe_mrq", "pb_mrq", "ps_ttm", "pcf_ttm"):
                    row[field] = to_number(lookup.get(code, {}).get(field))
                row["valuation_timestamp"] = to_number(result["data"].get("timestamp"))
                row["sources"]["valuation_request_id"] = result.get("request_id")
                if row["pe_ttm"] is None:
                    row["errors"].append("市盈率缺失或无效")
        except ApiError as exc:
            for code in group:
                records[code]["errors"].append(str(exc))
    progress("采集日K线，清洗并计算完整交易日的波动率")
    for group in batches(codes, 10):
        try:
            result = client.get("/api/a-share/prices/historical-batch", {
                "thscodes": ",".join(group), "interval": "1d", "adjust": "forward",
                "start": int((now - timedelta(days=180)).timestamp() * 1000), "end": int(now.timestamp() * 1000)})
            lookup = indexed_rows(result, group)
            for code in group:
                row = records[code]
                bars = lookup.get(code, {}).get("item", [])
                cleaned, rejected = clean_bars(bars if isinstance(bars, list) else [], now)
                row["recent_closes"] = cleaned[-21:]
                row["kline_count"] = len(cleaned)
                row["kline_timestamp"] = cleaned[-1]["date_ms"] if cleaned else None
                row["sources"]["kline_request_id"] = result.get("request_id")
                actual_days = [datetime.fromtimestamp(bar["date_ms"] / 1000, SHANGHAI).date() for bar in cleaned[-21:]]
                if actual_days == expected_days:
                    row["volatility_20d_pct"] = calculate_volatility(cleaned)
                else:
                    row["errors"].append("最近21个完整交易日日K线不齐或尚未更新，波动率留空")
                if rejected:
                    row["errors"].append(f"已剔除{rejected}条无效、冲突或未收盘K线")
        except ApiError as exc:
            for code in group:
                records[code]["errors"].append(str(exc))
    reports = [os.environ["STOCKLENS_REPORT"]] if os.getenv("STOCKLENS_REPORT") else report_candidates(now)
    if any(not re.fullmatch(r"\d{4}-[1-4]", report) for report in reports):
        raise ValueError("STOCKLENS_REPORT 格式必须为 yyyy-1 至 yyyy-4")
    progress(f"逐只采集财务指标，优先报告期{reports[0]}")
    for index, code in enumerate(codes, 1):
        row = records[code]
        for report in reports:
            try:
                result = client.get("/api/a-share/financials/indicators", {"thscode": code, "report": report})
                data = result["data"]
                if data.get("thscode") != code or data.get("report") != report:
                    raise ApiError("财务返回股票或报告期与请求不一致")
                indicators = {item["index_id"]: to_number(item.get("value"))
                              for ability in data.get("abilities", []) if isinstance(ability, dict)
                              for item in ability.get("indicators", []) if isinstance(item, dict) and "index_id" in item}
                # Never replace parent-company profit with generic net_profit_yoy.
                profit = indicators.get("calculate_parent_holder_net_profit_yoy_growth_ratio")
                revenue = indicators.get("calculate_operating_income_yoy_growth_ratio")
                if revenue is None:
                    revenue = indicators.get("operating_income_yoy_growth_ratio")
                roe = indicators.get("index_weighted_avg_roe")
                if all(value is None for value in (profit, revenue, roe)):
                    continue
                row.update({"financial_report": report, "parent_net_profit_growth_pct": profit,
                            "revenue_growth_pct": revenue,
                            "roe_pct": roe, "financial_fetched_at": datetime.now(timezone.utc).isoformat()})
                row["sources"]["financial_request_id"] = result.get("request_id")
                if report != reports[0]:
                    row["errors"].append(f"最新目标期无可用财务指标，使用实际可用报告期{report}")
                break
            except ApiError as exc:
                row["errors"].append(str(exc))
                break
        if row["financial_report"] is None:
            row["errors"].append("没有可用财务指标，保留缺失")
        for field in ('parent_net_profit_growth_pct', 'roe_pct', 'revenue_growth_pct'):
            if row.get(field) is None:
                row['errors'].append(f'{field} 缺失，不能用于判断该条件')
        if index % 25 == 0 or index == len(codes):
            progress(f"财务指标进度 {index}/{len(codes)}")
    report_set = sorted({row["financial_report"] for row in records.values() if row["financial_report"]})
    return {"metadata": {"project": "StockLens", "source": "Fuyao Financial Data API", "universe": "CSI 300",
                         "universe_size": len(unique), "sample_size": len(records), "snapshot_id": uuid.uuid4().hex,
                         "started_at": started, "collected_at": datetime.now(timezone.utc).isoformat(),
                         "report": report_set[0] if len(report_set) == 1 else "多报告期", "reports": report_set,
                         "target_report": reports[0], "calendar_request_id": calendar_id,
                         "last_completed_trade_date": expected_days[-1].isoformat(), "missing_values": "null",
                         "timezone": "Asia/Shanghai", "industry_taxonomy": "同花顺行业（扶摇当前关系数据）",
                         "volatility_basis": "最近21个完整交易日，前复权，未年化"},
            "stocks": list(records.values())}


def validate_snapshot(snapshot, expected_count, minimum_coverage=0.8):
    rows = snapshot["stocks"]
    if len(rows) != expected_count or len({row["thscode"] for row in rows}) != expected_count:
        raise ValueError("快照股票数量或唯一性校验失败")
    if not 0 < minimum_coverage <= 1:
        raise ValueError("数据覆盖率门槛必须大于0且不超过1")
    coverage = {field: sum(to_number(row.get(field)) is not None for row in rows) / len(rows) for field in CORE_FIELDS}
    coverage['industries'] = sum(bool(row.get('industries')) for row in rows) / len(rows)
    if any(value < minimum_coverage for value in coverage.values()):
        raise ValueError("数据覆盖率未通过，保留上次快照：" + json.dumps(coverage))
    json.dumps(snapshot, allow_nan=False)
    snapshot["metadata"]["quality"] = {"coverage": coverage, "minimum_coverage": minimum_coverage,
                                         "rows_with_warnings": sum(bool(row["errors"]) for row in rows)}
    return coverage


def publish_snapshot(snapshot, directory, expected_count, minimum_coverage=0.8):
    validate_snapshot(snapshot, expected_count, minimum_coverage)
    identity = snapshot["metadata"]["snapshot_id"]
    atomic_json(directory / "history" / f"{identity}.json", snapshot)
    atomic_json(directory / "stock_snapshot_latest.json", snapshot)


def run_refresh(client, directory, limit=300, slot=None):
    status_path = directory / "refresh_status.json"
    try:
        previous = json.loads(status_path.read_text(encoding="utf-8"))
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    status = {"state": "running", "last_attempt_at": datetime.now(timezone.utc).isoformat(),
              "last_success_at": previous.get("last_success_at"), "last_success_slot": previous.get("last_success_slot"),
              "slot": slot, "target_count": limit, "schedule": ["09:30", "11:30", "13:00", "15:00"], "timezone": "Asia/Shanghai"}
    def progress(message):
        status["progress"] = message
        status["last_progress_at"] = datetime.now(timezone.utc).isoformat()
        atomic_json(status_path, status)
        print(message, flush=True)
    try:
        progress("开始更新")
        snapshot = collect_snapshot(client, limit, progress=progress)
        publish_snapshot(snapshot, directory, limit, float(os.getenv("STOCKLENS_MIN_COVERAGE", "0.8")))
        status.update(state="success", last_success_at=snapshot["metadata"]["collected_at"],
                      last_finished_at=datetime.now(timezone.utc).isoformat(),
                      last_success_slot=slot or previous.get("last_success_slot"), snapshot_id=snapshot["metadata"]["snapshot_id"],
                      quality=snapshot["metadata"]["quality"], progress="更新完成")
        atomic_json(status_path, status)
        return snapshot
    except Exception as exc:
        status.update(state="failed", last_finished_at=datetime.now(timezone.utc).isoformat(),
                      error=str(exc) if isinstance(exc, (ApiError, ValueError)) else type(exc).__name__)
        atomic_json(status_path, status)
        raise


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="采集、清洗并原子发布沪深300数据")
    parser.add_argument("limit", nargs="?", type=int, default=int(os.getenv("STOCKLENS_UNIVERSE_LIMIT", "300")))
    args = parser.parse_args()
    directory = data_directory()
    with refresh_lock(directory):
        result = run_refresh(FuyaoClient(os.getenv("FUYAO_API_KEY")), directory, args.limit)
    print(json.dumps(result["metadata"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
