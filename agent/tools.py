"""Agent 工具层。

业务数据（持仓/自选/回测/体检/K线）一律走 web 的 HTTP API：数据缓存和体检结果只由 web 进程写，
避免两个进程同时写同一份文件。市场数据只读，直接调 Tushare。
工具返回值都做了精简——只给模型结论性字段，长上下文会明显拖慢本地模型。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_loader import to_ts_code  # noqa: E402  顺带加载 .env 里的 TUSHARE_TOKEN

WEB_URL = os.getenv("WEB_URL", "http://127.0.0.1:8000").rstrip("/")
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_TOOLS: dict[str, tuple[Callable, dict]] = {}

INDEXES = {"000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指", "000300.SH": "沪深300"}
METRICS = {  # backtesting.py 指标名 -> 精简键
    "Return [%]": "return_pct", "Return (Ann.) [%]": "annual_return_pct", "Buy & Hold Return [%]": "buy_hold_pct",
    "Sharpe Ratio": "sharpe", "Max. Drawdown [%]": "max_drawdown_pct", "Win Rate [%]": "win_rate_pct",
    "# Trades": "trades", "Profit Factor": "profit_factor", "Exposure Time [%]": "exposure_pct",
}


class ToolError(RuntimeError):
    pass


def tool(description: str, properties: dict | None = None, required: list[str] | None = None):
    """注册工具：properties 是 JSON Schema 的 properties。"""
    def deco(fn):
        _TOOLS[fn.__name__] = (fn, {"type": "function", "function": {
            "name": fn.__name__, "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        }})
        return fn
    return deco


def schemas() -> list[dict]:
    return [schema for _, schema in _TOOLS.values()]


def call(name: str, args: dict) -> dict:
    """执行工具，异常转成 {"error": ...} 回给模型，让它自己调整。"""
    if name not in _TOOLS:
        return {"error": f"没有工具 {name}"}
    try:
        return _TOOLS[name][0](**(args or {}))
    except TypeError as exc:
        return {"error": f"参数错误：{exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _web(method: str, path: str, body: dict | None = None, timeout: float = 300) -> dict | list:
    req = urllib.request.Request(WEB_URL + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc).get("detail")
        except ValueError:
            detail = exc.reason
        raise ToolError(f"{detail}") from exc
    except urllib.error.URLError as exc:
        raise ToolError(f"连不上回测服务 {WEB_URL}：{exc.reason}") from exc


def _pick(d: dict | None, *keys: str) -> dict:
    return {k: d.get(k) for k in keys} if d else {}


_industry_cache: dict = {"at": 0.0, "map": {}}


def _industries() -> dict[str, str]:
    """股票代码 -> 行业（Tushare stock_basic，一天刷新一次）；没 token 或失败时返回空，不影响主流程。"""
    if time.time() - _industry_cache["at"] > 86400:
        try:
            _, pro = _tushare()
            df = pro.stock_basic(fields="symbol,industry")
            _industry_cache.update(at=time.time(), map=dict(zip(df["symbol"], df["industry"])))
        except Exception:  # noqa: BLE001
            pass
    return _industry_cache["map"]


# ---------------------------------------------------------------- 持仓 / 自选
@tool("获取我的持仓：每只的行业、成本、现价、盈亏、仓位占比、系统建议（加仓/持有/减仓等）和主策略最新信号，以及组合汇总。")
def get_holdings() -> dict:
    data = _web("GET", "/api/holdings/analysis")
    industries = _industries()
    rows = []
    for r in data["rows"]:
        if r.get("error"):
            rows.append({"symbol": r["symbol"], "name": r.get("name"), "error": r["error"]})
            continue
        main = r.get("main") or {}
        rows.append({
            **_pick(r, "symbol", "name"), "industry": industries.get(r["symbol"]),
            **_pick(r, "shares", "cost_price", "close", "change_pct", "pnl_pct", "pnl", "weight_pct",
                    "data_date", "stop_loss_pct", "take_profit_pct"),
            "advice": f"{r['advice']['label']}：{r['advice']['reason']}",
            "main_strategy": _pick(main, "name", "action", "hold_after", "since", "oos_sharpe") or None,
            "consensus": f"{r['consensus']['bull']}/{r['consensus']['total']} 个策略看多",
        })
    return {"summary": data["summary"], "rows": rows}


@tool("获取我的自选股：行业、现价、涨跌幅、所用策略及样本外夏普、最新买卖信号和下一次触发价。")
def get_watchlist() -> dict:
    data = _web("GET", "/api/watchlist")
    industries = _industries()
    rows = []
    for r in data["rows"]:
        sig = r.get("signal") or {}
        rows.append({
            **_pick(r, "symbol", "name"), "industry": industries.get(r["symbol"]),
            **_pick(r, "group", "close", "change_pct", "error"),
            "strategy": _pick(r.get("used"), "name", "oos_sharpe", "source") or None,
            "signal": {**_pick(sig, "action", "hold_after", "since", "last_event"),
                       "triggers": sig.get("triggers")} if sig else None,
        })
    return {"rows": rows, "signal_count": data["signal_count"]}


# ---------------------------------------------------------------- 回测 / 体检
@tool("列出可用的回测策略及其参数（名称、默认值、取值范围）。")
def list_strategies() -> dict:
    meta = _web("GET", "/api/meta")
    return {"strategies": [
        {"name": s["name"], "label": s["label"], "description": s["description"], "defaults": s["defaults"]}
        for s in meta["strategies"]
    ]}


@tool(
    "对单只股票做策略回测。给 split（切分日期）时为样本外验证：训练段（可配合 optimize 寻优）的参数原样用于测试段，"
    "结论应以测试段指标为准。返回收益、夏普、回撤、胜率、交易次数等。",
    {
        "symbol": {"type": "string", "description": "6 位股票代码，如 600519"},
        "strategy": {"type": "string", "description": "策略名，见 list_strategies"},
        "params": {"type": "object", "description": "策略参数，不给用默认值"},
        "start": {"type": "string", "description": "开始日期 YYYYMMDD，默认 20180101"},
        "end": {"type": "string", "description": "结束日期 YYYYMMDD，默认今天"},
        "optimize": {"type": "boolean", "description": "是否在（训练段）网格寻优参数"},
        "split": {"type": "string", "description": "样本外切分日期 YYYYMMDD，之后为测试段"},
    },
    ["symbol", "strategy"],
)
def run_backtest(symbol: str, strategy: str, params: dict | None = None, start: str = "20180101",
                 end: str | None = None, optimize: bool = False, split: str | None = None) -> dict:
    res = _web("POST", "/api/backtest", {
        "symbol": symbol, "strategy": strategy, "params": params or {}, "start": start,
        "end": end or datetime.now().strftime("%Y%m%d"), "optimize": optimize, "split": split,
    })

    def metrics(m: dict) -> dict:
        return {short: round(v, 3) if isinstance(v := m.get(full), float) else v for full, short in METRICS.items()}

    out = {"symbol": symbol, "strategy": strategy, "params": res["params"], "metrics": metrics(res["metrics"]),
           "report_url": res["report_url"], "warnings": res["warnings"]}
    if res.get("oos"):
        oos = res["oos"]
        out["metrics_note"] = "metrics 为测试段（样本外）结果"
        out["oos"] = {"split": oos["split"], "train": metrics(oos["train"]["metrics"]),
                      "test_with_default_params": metrics(oos["test_default"]["metrics"]),
                      "sharpe_decay": oos["sharpe_decay"]}
    return out


@tool(
    "查看个股的策略体检：近 5 年滚动样本外验证（训练 3 年/测试 1 年）下各策略的样本外夏普、交易次数和当前参数，"
    "以及最适合的主策略。没有体检记录或 refresh=true 时会现场体检（约 10 秒）。",
    {"symbol": {"type": "string", "description": "6 位股票代码"},
     "refresh": {"type": "boolean", "description": "是否强制重新体检"}},
    ["symbol"],
)
def get_checkup(symbol: str, refresh: bool = False) -> dict:
    if not refresh:
        try:
            return _compact_checkup(_web("GET", f"/api/checkups/{symbol}"))
        except ToolError:
            pass
    job = _web("POST", "/api/holdings/checkup", {"symbols": [symbol], "force": True})["job"]
    deadline = time.time() + 180
    while job["status"] == "running" and symbol in job["pending"] and time.time() < deadline:
        time.sleep(2)
        job = _web("GET", f"/api/jobs/{job['id']}")
    if symbol in job.get("errors", {}):
        raise ToolError(f"体检失败：{job['errors'][symbol]}")
    return _compact_checkup(_web("GET", f"/api/checkups/{symbol}"))


def _compact_checkup(check: dict) -> dict:
    return {
        "symbol": check["symbol"], "checked_at": check["checked_at"], "data_end": check["data_end"],
        "best": check["best"],
        "strategies": {name: _pick(s, "oos_sharpe", "oos_trades", "live_params", "error")
                       for name, s in check["strategies"].items()},
    }


# ---------------------------------------------------------------- 个股行情
@tool(
    "个股行情概览：最新收盘、近 5/20/60 日涨跌幅、均线位置、量比、区间高低点；给 strategy 时附带该策略的最新信号和触发价。",
    {"symbol": {"type": "string", "description": "6 位股票代码"},
     "strategy": {"type": "string", "description": "可选，策略名"}},
    ["symbol"],
)
def get_stock_overview(symbol: str, strategy: str | None = None) -> dict:
    path = f"/api/kline/{symbol}?days=400" + (f"&strategy={strategy}" if strategy else "")
    data = _web("GET", path)
    bars = data["bars"]  # [date, open, close, low, high, volume]
    closes = [b[2] for b in bars]
    vols = [b[5] for b in bars]
    last = closes[-1]

    def chg(n: int):
        return round((last / closes[-n - 1] - 1) * 100, 2) if len(closes) > n else None

    def ma(n: int):
        return round(sum(closes[-n:]) / n, 3) if len(closes) >= n else None

    recent = bars[-60:]
    out = {
        "symbol": symbol, "date": bars[-1][0], "close": last,
        "change_pct": {"1d": chg(1), "5d": chg(5), "20d": chg(20), "60d": chg(60)},
        "ma": {"ma5": ma(5), "ma20": ma(20), "ma60": ma(60), "ma250": ma(250)},
        "volume_ratio_5d": round(vols[-1] / (sum(vols[-6:-1]) / 5), 2) if len(vols) > 5 and sum(vols[-6:-1]) else None,
        "high_60d": max(b[4] for b in recent), "low_60d": min(b[3] for b in recent),
        "high_250d": max(b[4] for b in bars[-250:]), "low_250d": min(b[3] for b in bars[-250:]),
    }
    if data.get("signal"):
        sig = data["signal"]
        out["signal"] = {**_pick(sig, "strategy", "params", "action", "hold_after", "since", "triggers"),
                         "recent_trades": sig["trades"][-3:]}
    return out


# ---------------------------------------------------------------- 市场（Tushare）
_pro = None


def _tushare():
    global _pro
    import tushare as ts

    if _pro is None:
        token = os.getenv("TUSHARE_TOKEN", "").strip()
        if not token:
            raise ToolError("未配置 TUSHARE_TOKEN，无法获取市场数据")
        _pro = ts.pro_api(token)
    return ts, _pro


@tool(
    "获取实时报价（盘中为最新价，收盘后为当日收盘）。可查个股和指数。",
    {"symbols": {"type": "array", "items": {"type": "string"},
                 "description": "股票代码列表，如 [\"600519\", \"000001.SH\"]；指数需带后缀"}},
    ["symbols"],
)
def get_realtime_quotes(symbols: list[str]) -> dict:
    ts, _ = _tushare()
    df = ts.realtime_quote(ts_code=",".join(to_ts_code(s) for s in symbols[:50]))
    rows = []
    for r in df.to_dict("records"):
        pre = r["PRE_CLOSE"] or 0
        rows.append({"symbol": r["TS_CODE"], "name": r["NAME"], "time": f"{r['DATE']} {r['TIME']}",
                     "price": r["PRICE"], "change_pct": round((r["PRICE"] / pre - 1) * 100, 2) if pre else None,
                     "open": r["OPEN"], "high": r["HIGH"], "low": r["LOW"], "amount_yi": round(r["AMOUNT"] / 1e8, 2)})
    return {"quotes": rows}


_snapshot_cache: dict = {}


@tool("盘中全市场实时快照：主要指数、涨跌家数与涨跌停数、领涨领跌行业。盘中问“现在市场怎么样”用这个；复盘用 market_snapshot。")
def market_live() -> dict:
    from agent.monitor.market import live_market

    return live_market()


@tool(
    "A 股全市场复盘快照（最近一个交易日）：主要指数涨跌、上涨/下跌家数、涨停/跌停/炸板数、成交额、"
    "领涨领跌行业、行业主力资金净流入前后几名。",
    {"trade_date": {"type": "string", "description": "可选，YYYYMMDD；默认最近一个已收盘交易日"}},
)
def market_snapshot(trade_date: str | None = None) -> dict:
    _, pro = _tushare()
    if not trade_date:
        # 收盘数据 17 点后才齐，之前取上一交易日
        now = datetime.now()
        end = now if now.hour >= 17 else now - timedelta(days=1)
        cal = pro.trade_cal(exchange="SSE", start_date=(end - timedelta(days=15)).strftime("%Y%m%d"),
                            end_date=end.strftime("%Y%m%d"), is_open="1")
        trade_date = max(cal["cal_date"])
    if trade_date in _snapshot_cache:
        return _snapshot_cache[trade_date]

    indexes = []
    for code, name in INDEXES.items():
        df = pro.index_daily(ts_code=code, start_date=trade_date, end_date=trade_date)
        if len(df):
            r = df.iloc[0]
            indexes.append({"name": name, "close": round(r["close"], 2), "change_pct": round(r["pct_chg"], 2)})

    daily = pro.daily(trade_date=trade_date)
    if daily.empty:
        raise ToolError(f"{trade_date} 没有日线数据（非交易日或数据未更新）")
    pct = daily["pct_chg"]
    limits = pro.limit_list_d(trade_date=trade_date)
    limit_counts = limits["limit"].value_counts().to_dict() if len(limits) else {}
    up_industries = (limits[limits["limit"] == "U"]["industry"].value_counts().head(5).to_dict()
                     if len(limits) else {})

    flow = pro.moneyflow_ind_dc(trade_date=trade_date)
    ind = flow[flow["content_type"] == "行业"]

    def sector_rows(df):
        return [{"name": r["name"], "change_pct": round(r["pct_change"], 2), "net_inflow_yi": round(r["net_amount"] / 1e8, 2)}
                for r in df.to_dict("records")]

    result = {
        "trade_date": trade_date,
        "indexes": indexes,
        "breadth": {
            "up": int((pct > 0).sum()), "down": int((pct < 0).sum()), "flat": int((pct == 0).sum()),
            "median_change_pct": round(float(pct.median()), 2),
            "up_over_5pct": int((pct >= 5).sum()), "down_over_5pct": int((pct <= -5).sum()),
            "amount_yi": round(float(daily["amount"].sum()) / 1e5, 0),  # amount 单位千元
        },
        "limits": {"limit_up": limit_counts.get("U", 0), "limit_down": limit_counts.get("D", 0),
                   "broken": limit_counts.get("Z", 0), "limit_up_industries": up_industries},
        "sectors": {
            "top": sector_rows(ind.nlargest(5, "pct_change")),
            "bottom": sector_rows(ind.nsmallest(5, "pct_change")),
            "inflow_top": sector_rows(ind.nlargest(5, "net_amount")),
            "outflow_top": sector_rows(ind.nsmallest(5, "net_amount")),
        },
    }
    _snapshot_cache[trade_date] = result
    return result
