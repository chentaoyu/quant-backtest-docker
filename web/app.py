"""本地 Web 回测台：配置、运行、查看回测结果。

启动：uv run uvicorn web.app:app --port 8000
打开：http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import sys
import threading
import warnings
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest_engine import (  # noqa: E402
    WEB_RUNS_DIR,
    BacktestError,
    RunConfig,
    list_runs,
    load_run,
    run,
)
from data_loader import CACHE_DIR, DataError, available_symbols, has_tushare_token, resolve_source  # noqa: E402
from stock_list import load_stock_list  # noqa: E402
import advisor  # noqa: E402
import holdings  # noqa: E402
import sim  # noqa: E402
import watchlist  # noqa: E402
from strategies import STRATEGIES  # noqa: E402

# Web 端不把进度条刷到服务日志里（CLI 保留进度条）
from backtesting import backtesting as _bt  # noqa: E402

_bt._tqdm = lambda seq, **_: seq
warnings.filterwarnings("ignore", message="If you want to use multi-process optimization", category=RuntimeWarning)

STATIC_DIR = Path(__file__).parent / "static"
RUN_LOCK = threading.Lock()



@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 后台预热股票列表，避免第一次打开页面时下拉框空等
    threading.Thread(target=load_stock_list, daemon=True).start()
    yield


app = FastAPI(title="quant-backtest 本地回测台", version="0.3.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
WEB_RUNS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class BacktestRequest(BaseModel):
    symbol: str = "600519"
    strategy: str = "sma_cross"
    source: str = "auto"
    start: str = "20180101"
    end: str = "20261231"
    cash: float = 1_000_000
    commission: float = 0.0005
    optimize: bool = False
    split: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    ranges: dict[str, dict] = Field(default_factory=dict)
    refresh: bool = False


class HoldingRequest(BaseModel):
    symbol: str
    shares: float
    cost_price: float
    buy_date: str | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    strategy: str | None = None
    note: str = ""


class ImportRequest(BaseModel):
    text: str
    mode: str = "append"
    dry_run: bool = True


class WatchItemRequest(BaseModel):
    symbol: str
    group: str | None = None
    strategy: str | None = None
    params: dict[str, float] | None = None
    note: str = ""


class WatchAddRequest(BaseModel):
    text: str
    group: str | None = None


class AccountRequest(BaseModel):
    name: str = "模拟账户"
    initial_cash: float = 1_000_000
    fees: dict[str, float] | None = None


class SlotRequest(BaseModel):
    symbol: str
    cash: float = 100_000
    strategy: str | None = None
    params: dict[str, float] | None = None
    entry_on_start: bool = False


class OrderRequest(BaseModel):
    symbol: str
    side: str
    shares: int


class CheckupRequest(BaseModel):
    symbols: list[str] | None = None
    force: bool = False


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/stocks")
def stocks(refresh: bool = False) -> dict:
    return load_stock_list(refresh=refresh)


@app.get("/api/meta")
def meta() -> dict:
    strategies = []
    for name, cls in STRATEGIES.items():
        strategies.append(
            {
                "name": name,
                "label": getattr(cls, "label", name),
                "description": getattr(cls, "description", ""),
                "notes": getattr(cls, "notes", {}),
                "params": getattr(cls, "param_spec", []),
                "defaults": {p["name"]: p["default"] for p in getattr(cls, "param_spec", [])},
                "default_ranges": getattr(cls, "default_ranges", {}),
            }
        )
    return {
        "strategies": strategies,
        "strategy_count": len(strategies),
        "sources": [
            {"value": "auto", "label": "自动（有 TUSHARE_TOKEN 用 Tushare，否则 akshare）"},
            {"value": "tushare", "label": "Tushare Pro"},
            {"value": "akshare", "label": "akshare（东财）"},
        ],
        "symbols": available_symbols(),
        "defaults": {
            "symbol": "600519",
            "start": "20180101",
            "end": datetime.now().strftime("%Y%m%d"),
            "cash": 1_000_000,
            "commission": 0.0005,
        },
        "tushare_token": has_tushare_token(),
        "auto_source": resolve_source(None),
        "cache_dir": str(CACHE_DIR),
    }


@app.post("/api/backtest")
def backtest(payload: BacktestRequest) -> dict:
    config = RunConfig(**payload.model_dump())
    try:
        with RUN_LOCK:
            return run(config)
    except (BacktestError, DataError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 交给前端展示
        raise HTTPException(status_code=500, detail=f"回测执行失败：{exc}") from exc


@app.get("/api/runs")
def runs(limit: int = 30) -> list[dict]:
    return list_runs(max(1, min(limit, 100)))


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    try:
        return load_run(run_id)
    except BacktestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------- 持仓
def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@app.get("/api/holdings")
def holdings_list() -> list[dict]:
    return holdings.list_holdings()


@app.put("/api/holdings")
def holdings_upsert(payload: HoldingRequest) -> dict:
    if payload.strategy and payload.strategy not in STRATEGIES:
        raise HTTPException(status_code=400, detail=f"未知策略：{payload.strategy}")
    try:
        return holdings.upsert(payload.model_dump())
    except holdings.HoldingError as exc:
        raise _bad_request(exc) from exc


@app.delete("/api/holdings/{symbol}")
def holdings_delete(symbol: str) -> dict:
    try:
        holdings.delete(symbol)
    except holdings.HoldingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/holdings/import")
def holdings_import(payload: ImportRequest) -> dict:
    """dry_run=True 只返回预览；False 时写入并对未体检的股票启动体检。"""
    try:
        rows = holdings.parse_import(payload.text)
        if payload.dry_run:
            return {"rows": rows, "valid": sum(r["ok"] for r in rows)}
        items = holdings.commit_import(rows, payload.mode)
    except holdings.HoldingError as exc:
        raise _bad_request(exc) from exc
    stale = advisor.stale_symbols()
    job = advisor.jobs.start_checkup(stale) if stale else None
    return {"holdings": items, "job": job}


@app.get("/api/holdings/analysis")
def holdings_analysis() -> dict:
    return advisor.analyze_all()


@app.post("/api/holdings/checkup")
def holdings_checkup(payload: CheckupRequest) -> dict:
    symbols = payload.symbols or advisor.stale_symbols(force=payload.force)
    if not symbols:
        return {"job": None, "message": "所有持仓的体检都在 30 天内，无需重跑"}
    return {"job": advisor.jobs.start_checkup(symbols)}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict:
    job = advisor.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.get("/api/checkups/{symbol}")
def checkup_detail(symbol: str) -> dict:
    check = advisor.load_checkups().get(symbol)
    if check is None:
        raise HTTPException(status_code=404, detail=f"{symbol} 还没有体检记录")
    return check


@app.get("/api/kline/{symbol}")
def kline(symbol: str, days: int = 750, strategy: str | None = None, params: str | None = None) -> dict:
    try:
        symbol = holdings.normalize_symbol(symbol)
        parsed = json.loads(params) if params else None
        return advisor.kline(symbol, max(60, min(days, 365 * 15)), strategy, parsed)
    except (holdings.HoldingError, BacktestError, DataError, ValueError) as exc:
        raise _bad_request(exc) from exc


# ---------------------------------------------------------------- 自选股
USER_ERRORS = (holdings.HoldingError, sim.SimError, BacktestError, DataError)


@app.get("/api/watchlist")
def watchlist_analysis() -> dict:
    result = advisor.analyze_watchlist()
    slots = sim.active_slots_by_symbol()
    for row in result["rows"]:
        row["sim"] = slots.get(row["symbol"], [])
    return result


@app.put("/api/watchlist")
def watchlist_upsert(payload: WatchItemRequest) -> dict:
    try:
        item = watchlist.upsert(payload.model_dump())
    except USER_ERRORS as exc:
        raise _bad_request(exc) from exc
    stale = advisor.stale_symbols()
    return {"item": item, "job": advisor.jobs.start_checkup(stale) if stale else None}


@app.post("/api/watchlist/add")
def watchlist_add(payload: WatchAddRequest) -> dict:
    try:
        result = watchlist.add_many(payload.text, payload.group)
    except USER_ERRORS as exc:
        raise _bad_request(exc) from exc
    stale = advisor.stale_symbols()
    return {**result, "job": advisor.jobs.start_checkup(stale) if stale else None}


@app.delete("/api/watchlist/{symbol}")
def watchlist_delete(symbol: str) -> dict:
    try:
        watchlist.delete(symbol)
    except USER_ERRORS as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


# ---------------------------------------------------------------- 模拟仓
def _sim_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except USER_ERRORS as exc:
        raise _bad_request(exc) from exc


@app.get("/api/sim/accounts")
def sim_accounts() -> list[dict]:
    return [{k: a[k] for k in ("id", "name", "initial_cash", "created_date")} for a in sim.list_accounts()]


@app.post("/api/sim/accounts")
def sim_create_account(payload: AccountRequest) -> dict:
    return _sim_call(sim.create_account, payload.name, payload.initial_cash, payload.fees)


@app.delete("/api/sim/accounts/{account_id}")
def sim_delete_account(account_id: str) -> dict:
    _sim_call(sim.delete_account, account_id)
    return {"ok": True}


@app.get("/api/sim/accounts/{account_id}")
def sim_account(account_id: str) -> dict:
    return _sim_call(sim.account_state, account_id)


@app.post("/api/sim/accounts/{account_id}/slots")
def sim_add_slot(account_id: str, payload: SlotRequest) -> dict:
    if payload.strategy:
        _sim_call(watchlist.check_params, payload.strategy, payload.params)
    return _sim_call(sim.add_slot, account_id, payload.symbol, payload.cash, payload.strategy,
                     payload.params, payload.entry_on_start)


@app.post("/api/sim/accounts/{account_id}/slots/{slot_id}/stop")
def sim_stop_slot(account_id: str, slot_id: str) -> dict:
    _sim_call(sim.stop_slot, account_id, slot_id)
    return {"ok": True}


@app.post("/api/sim/accounts/{account_id}/orders")
def sim_place_order(account_id: str, payload: OrderRequest) -> dict:
    return _sim_call(sim.place_order, account_id, payload.symbol, payload.side, payload.shares)


@app.delete("/api/sim/accounts/{account_id}/orders/{order_id}")
def sim_cancel_order(account_id: str, order_id: str) -> dict:
    _sim_call(sim.cancel_order, account_id, order_id)
    return {"ok": True}


@app.get("/reports/{folder}/{filename}", include_in_schema=False)
def report(folder: str, filename: str) -> FileResponse:
    if folder != "web":
        raise HTTPException(status_code=404, detail="报告不存在")
    if not filename.endswith(".html") or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=404, detail="报告不存在")
    path = WEB_RUNS_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="报告不存在")
    return FileResponse(path, media_type="text/html; charset=utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.app:app", host="127.0.0.1", port=8000)
