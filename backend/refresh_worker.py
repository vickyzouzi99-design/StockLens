"""One server worker, four Shanghai-time slots, persisted completion and retries."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import time

from dotenv import load_dotenv
from collect_data import (ROOT, SHANGHAI, ApiError, FuyaoClient, atomic_json,
                          data_directory, refresh_lock, run_refresh, trading_days)

SLOTS = ((9, 30), (11, 30), (13, 0), (15, 0))
RETRY_SECONDS = 600


def due_slot(now):
    if now.tzinfo is None:
        raise ValueError("调度时间必须包含时区")
    local = now.astimezone(SHANGHAI)
    if local.weekday() >= 5:
        return None
    passed = [(hour, minute) for hour, minute in SLOTS if (hour, minute) <= (local.hour, local.minute)]
    if not passed:
        return None
    hour, minute = passed[-1]
    # Restart catches up only the latest due slot today, never replays four old jobs.
    return f"{local.date().isoformat()}T{hour:02d}:{minute:02d}+08:00"


def read_json(path):
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def should_attempt(status, slot, now):
    if status.get("last_success_slot") == slot:
        return False
    retry_from = status.get("last_finished_at") or status.get("last_attempt_at")
    if status.get("slot") == slot and retry_from:
        try:
            attempted = datetime.fromisoformat(retry_from)
            if now - attempted < timedelta(seconds=RETRY_SECONDS):
                return False
        except (ValueError, TypeError):
            pass
    return True


def tick(client, directory, now=None, limit=300):
    now = (now or datetime.now(timezone.utc)).astimezone(SHANGHAI)
    scheduler = {"last_checked_at": now.isoformat(), "timezone": "Asia/Shanghai",
                 "schedule": [f"{h:02d}:{m:02d}" for h, m in SLOTS], "state": "waiting"}
    slot = due_slot(now)
    directory.mkdir(parents=True, exist_ok=True)
    previous_scheduler = read_json(directory / "scheduler_status.json")
    # Preserve failed calendar/collection attempts across worker restarts.
    for key in ("slot", "last_attempt_at", "last_finished_at", "error"):
        if key in previous_scheduler:
            scheduler[key] = previous_scheduler[key]
    atomic_json(directory / "scheduler_status.json", scheduler)
    if slot is None:
        return "waiting"
    with refresh_lock(directory):
        status = read_json(directory / "refresh_status.json")
        if not should_attempt(status, slot, now):
            return "already_done_or_cooldown"
        if scheduler.get("error") and not should_attempt(scheduler, slot, now):
            scheduler["state"] = "retry_wait"
            atomic_json(directory / "scheduler_status.json", scheduler)
            return "already_done_or_cooldown"
        calendar_path = directory / "calendar_today.json"
        calendar = read_json(calendar_path)
        scheduler.update(slot=slot, last_attempt_at=now.isoformat())
        scheduler.pop("error", None)
        scheduler.pop("last_finished_at", None)
        try:
            if calendar.get("date") != now.date().isoformat() or not isinstance(calendar.get("is_trading_day"), bool):
                days, request_id = trading_days(client, now.date(), now.date())
                calendar = {"date": now.date().isoformat(), "is_trading_day": now.date() in days, "request_id": request_id}
                atomic_json(calendar_path, calendar)
            if not calendar["is_trading_day"]:
                scheduler["state"] = "market_closed"
                atomic_json(directory / "scheduler_status.json", scheduler)
                return "market_closed"
            scheduler["state"] = "collecting"
            atomic_json(directory / "scheduler_status.json", scheduler)
            run_refresh(client, directory, limit=limit, slot=slot)
        except Exception as exc:
            scheduler.update(state="error", last_finished_at=datetime.now(timezone.utc).isoformat(),
                             error=str(exc) if isinstance(exc, (ApiError, ValueError, RuntimeError)) else type(exc).__name__)
            atomic_json(directory / "scheduler_status.json", scheduler)
            raise
        scheduler.update(state="updated", last_finished_at=datetime.now(timezone.utc).isoformat())
        atomic_json(directory / "scheduler_status.json", scheduler)
        return "updated"


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="交易日北京时间四次更新；需独立常驻运行")
    parser.add_argument("--once", action="store_true", help="只检查一次到期任务，供服务器定时器调用")
    args = parser.parse_args()
    client = FuyaoClient(os.getenv("FUYAO_API_KEY"))
    directory = data_directory()
    limit = int(os.getenv("STOCKLENS_UNIVERSE_LIMIT", "300"))
    while True:
        try:
            print(tick(client, directory, limit=limit), flush=True)
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ApiError, ValueError, RuntimeError)) else type(exc).__name__
            print("调度更新失败：" + message, flush=True)
            # tick persists retry timestamps; do not erase them here.
            if args.once:
                raise SystemExit(1)
        if args.once:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
