"""StockLens FastAPI. Dynamic selection via optional screening thresholds."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=os.getenv("STOCKLENS_ENV") != "production")

from intent_parser import parse_intent  # noqa: E402
from screen_engine import execute_screen  # noqa: E402
from collect_data import data_directory  # noqa: E402
from refresh_worker import read_json  # noqa: E402
from industries import catalog  # noqa: E402
import accounts  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

app = FastAPI(title="StockLens API", version="0.4.0")
app.include_router(accounts.router)


@app.middleware('http')
async def access_control(request, call_next):
    if accounts.enabled() and request.method != 'OPTIONS' and request.url.path.startswith('/api/') and request.url.path != '/api/health' and not request.url.path.startswith('/api/account/'):
        try:
            if request.method in ('POST', 'PUT', 'DELETE'):
                accounts.mutation_origin(request)
            user = accounts.principal(request)
            if request.url.path == '/api/interpret':
                # Reject malformed requests before consuming a reservation.
                InterpretRequest.model_validate(await request.json())
                accounts.reserve_call(user['id'])
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
        except ValueError:
            return JSONResponse({'detail': '请求格式无效'}, status_code=422)
    return await call_next(request)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "STOCKLENS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)


class ScreenParams(BaseModel):
    """Null means disabled, not zero. At least one condition must be enabled."""
    model_config = ConfigDict(extra="forbid")
    pe_max: float | None = Field(default=None, gt=0, le=100000)
    profit_min: float | None = Field(default=None, ge=-10000, le=10000)
    vol_max: float | None = Field(default=None, ge=0, le=1000)
    pb_max: float | None = Field(default=None, gt=0, le=100000)
    roe_min: float | None = Field(default=None, ge=-10000, le=10000)
    revenue_min: float | None = Field(default=None, ge=-10000, le=10000)
    industry: str | None = Field(default=None, pattern=r'^\d{6}\.TI$')

    @model_validator(mode="after")
    def at_least_one(self) -> "ScreenParams":
        if all(value is None for value in (self.pe_max, self.profit_min, self.vol_max, self.pb_max, self.roe_min, self.revenue_min, self.industry)):
            raise ValueError("至少启用一个筛选条件")
        return self


class ScreenRequest(ScreenParams):
    snapshot_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class InterpretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=2, max_length=500)
    provider: Literal["openai", "deepseek"] = "openai"


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: ScreenParams
    after: ScreenParams
    snapshot_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


def snapshot_path() -> Path:
    configured = os.getenv("STOCKLENS_SNAPSHOT", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else ROOT / path
    latest = data_directory() / "stock_snapshot_latest.json"
    if latest.exists():
        return latest
    candidates = list(data_directory().glob("stock_snapshot_*.json"))
    candidates.extend(data_directory().glob("stock_snapshot.json"))
    if not candidates:
        raise HTTPException(status_code=503, detail="尚无可用数据，请先完成首次数据采集")
    return max(candidates, key=lambda item: item.stat().st_mtime)


def load_snapshot(snapshot_id: str | None = None) -> dict[str, Any]:
    if snapshot_id is not None and not re.fullmatch(r"[a-f0-9]{32}", snapshot_id):
        raise HTTPException(status_code=422, detail="数据快照标识格式不正确")
    history = data_directory() / "history" / f"{snapshot_id}.json" if snapshot_id else None
    # History remains available even if the latest snapshot is being replaced.
    path = history if history and history.is_file() else snapshot_path()
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="读取数据快照失败，请稍后重试") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("stocks"), list):
        raise HTTPException(status_code=503, detail="数据快照结构不正确：缺少 stocks 数组")
    if snapshot_id and snapshot_id != (payload.get("metadata") or {}).get("snapshot_id"):
        raise HTTPException(status_code=409, detail="原数据快照已不可用，请选择使用最新数据重新筛选")
    return payload


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.4.0"}


@app.get("/api/data/status")
def data_status() -> dict[str, Any]:
    snapshot = load_snapshot()
    return {"stock_count": len(snapshot["stocks"]), "metadata": snapshot.get("metadata") or {},
            "industries": catalog(snapshot['stocks']),
            "refresh": read_json(data_directory() / "refresh_status.json"),
            "scheduler": read_json(data_directory() / "scheduler_status.json")}


@app.post("/api/interpret")
def interpret(payload: InterpretRequest) -> dict[str, Any]:
    try:
        return parse_intent(payload.text, provider=payload.provider, industry_catalog=catalog(load_snapshot()['stocks']))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def validate_industry(code, snapshot):
    if code and code not in {item['code'] for item in catalog(snapshot['stocks'])}:
        raise HTTPException(status_code=422, detail='所选行业在本次快照中没有可用分类数据，请使用最新数据或重新选择行业。')


@app.post("/api/screen")
def screen(payload: ScreenRequest) -> dict[str, Any]:
    snapshot = load_snapshot(getattr(payload, "snapshot_id", None))
    validate_industry(payload.industry, snapshot)
    result = execute_screen(snapshot["stocks"], payload.model_dump(exclude={"snapshot_id"}))
    result["snapshot_metadata"] = snapshot.get("metadata") or {}
    return result


@app.post("/api/compare")
def compare(payload: CompareRequest) -> dict[str, Any]:
    # Read one snapshot only: before and after must use precisely the same data.
    snapshot = load_snapshot(payload.snapshot_id)
    validate_industry(payload.before.industry, snapshot)
    validate_industry(payload.after.industry, snapshot)
    if payload.snapshot_id and payload.snapshot_id != snapshot.get("metadata", {}).get("snapshot_id"):
        raise HTTPException(status_code=409, detail="原数据快照已不可用，请选择使用最新数据重新筛选")
    stocks = snapshot["stocks"]
    before = execute_screen(stocks, payload.before.model_dump())
    after = execute_screen(stocks, payload.after.model_dump())
    before_selected = {r["thscode"] for r in before["results"] if r["status"] == "SELECTED"}
    after_selected = {r["thscode"] for r in after["results"] if r["status"] == "SELECTED"}
    lookup = {r["thscode"]: {"thscode": r["thscode"], "name": r["name"]} for r in after["results"]}

    def briefs(ids: set[str]) -> list[dict[str, str]]:
        return [lookup[code] for code in sorted(ids)]

    return {
        "before": {"strategy": before["strategy"], "summary": before["summary"]},
        "after": {"strategy": after["strategy"], "summary": after["summary"]},
        "changes": {
            "newly_selected": briefs(after_selected - before_selected),
            "no_longer_selected": briefs(before_selected - after_selected),
            "still_selected": briefs(before_selected & after_selected),
        },
        "snapshot_metadata": snapshot.get("metadata") or {},
    }
