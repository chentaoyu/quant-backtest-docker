"""回测执行引擎：CLI 与本地 Web 共用同一套逻辑。

一次 run 会完成：取数（带缓存与数据体检）→ 回测 / 网格优化 → 样本外切分
→ 指标、净值、交易、图表报告与元数据落盘。
"""
from __future__ import annotations

import json
import math
import re
import secrets
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from backtesting import Backtest

from data_loader import DataError, load_daily
from strategies import STRATEGIES

PROJECT_ROOT = Path(__file__).resolve().parent
REPORTS_DIR = PROJECT_ROOT / "reports"
WEB_RUNS_DIR = REPORTS_DIR / "web"

DEFAULT_CASH = 1_000_000.0
DEFAULT_COMMISSION = 0.0005
MAX_COMBOS = 5000
MIN_SPLIT_BARS = 60
KEEP_RUNS = 200

SYMBOL_RE = re.compile(r"^[0-9]{6}(\.[A-Z]{2})?$")
SKIP_METRICS = {"_strategy", "_equity_curve", "_trades"}


class BacktestError(ValueError):
    """参数或回测本身不合法。"""


# ---------------------------------------------------------------- 配置
@dataclass
class RunConfig:
    symbol: str = "600519"
    strategy: str = "sma_cross"
    source: str = "auto"
    start: str = "20180101"
    end: str = "20261231"
    cash: float = DEFAULT_CASH
    commission: float = DEFAULT_COMMISSION
    optimize: bool = False
    split: str | None = None
    params: dict = field(default_factory=dict)
    ranges: dict = field(default_factory=dict)
    refresh: bool = False

    def normalized(self) -> "RunConfig":
        symbol = str(self.symbol).strip().upper()
        if not SYMBOL_RE.match(symbol):
            raise BacktestError("股票代码需为 6 位数字，可带 .SH/.SZ/.BJ 后缀")
        if self.strategy not in STRATEGIES:
            raise BacktestError(f"未知策略：{self.strategy}")
        try:
            cash = float(self.cash)
            commission = float(self.commission)
        except (TypeError, ValueError):
            raise BacktestError("初始资金和手续费必须是数字") from None
        if cash <= 0:
            raise BacktestError("初始资金需大于 0")
        if not 0 <= commission < 0.05:
            raise BacktestError("手续费率应在 0（含）到 5% 之间")
        start = _norm_date(self.start, "开始日期")
        end = _norm_date(self.end, "结束日期")
        if start > end:
            raise BacktestError("开始日期不能晚于结束日期")
        split = _norm_date(self.split, "切分日期") if self.split else None
        if split and not (start < split < end):
            raise BacktestError("切分日期需位于回测区间内部")
        return RunConfig(
            symbol=symbol,
            strategy=self.strategy,
            source=self.source or "auto",
            start=start,
            end=end,
            cash=cash,
            commission=commission,
            optimize=bool(self.optimize),
            split=split,
            params={k: v for k, v in (self.params or {}).items() if v not in (None, "")},
            ranges={k: v for k, v in (self.ranges or {}).items() if v},
            refresh=bool(self.refresh),
        )


def _norm_date(value, label: str) -> str:
    try:
        ts = pd.Timestamp(str(value).strip())
    except (ValueError, TypeError):
        raise BacktestError(f"{label}格式不正确：{value}") from None
    return ts.strftime("%Y%m%d")


def _walk_forward_windows(
    start: str, end: str, train_years: int, test_years: int, max_folds: int = 20
) -> list[dict]:
    """滚动训练/测试窗口：训练窗长度固定，测试窗按 test_years 向前滚动，测试段不重叠。"""
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts >= end_ts:
        return []

    windows: list[dict] = []
    train_start = start_ts
    while len(windows) < max_folds:
        test_start = train_start + pd.DateOffset(years=train_years)
        if test_start >= end_ts:
            break
        test_end = test_start + pd.DateOffset(years=test_years) - pd.Timedelta(days=1)
        if test_end > end_ts:
            test_end = end_ts
        if (test_end - test_start).days < 30:
            break
        windows.append(
            {
                "index": len(windows) + 1,
                "label": f"F{len(windows) + 1} {test_start.date()} → {test_end.date()}",
                "train_start": train_start.strftime("%Y%m%d"),
                "test_start": test_start.strftime("%Y%m%d"),
                "test_end": test_end.strftime("%Y%m%d"),
            }
        )
        if test_end >= end_ts:
            break
        train_start = train_start + pd.DateOffset(years=test_years)
    return windows


def _default_params(strategy_cls) -> dict:
    return {p["name"]: p["default"] for p in getattr(strategy_cls, "param_spec", [])}


def _resolve_params(strategy_cls, overrides: dict) -> dict:
    params = _default_params(strategy_cls)
    spec = {p["name"]: p for p in getattr(strategy_cls, "param_spec", [])}
    for name, value in overrides.items():
        if name not in spec:
            raise BacktestError(f"策略 {strategy_cls.__name__} 没有参数 {name}")
        try:
            params[name] = int(value) if int(value) == float(value) else float(value)
        except (TypeError, ValueError):
            raise BacktestError(f"参数 {name} 必须是数字") from None
    _check_constraint(strategy_cls, params)
    return params


def _check_constraint(strategy_cls, params: dict) -> None:
    constraint = getattr(strategy_cls, "constraint", None)
    if constraint and not constraint(SimpleNamespace(**params)):
        raise BacktestError(f"参数不满足策略约束：{params}")


def _grid_values(name: str, meta: dict, rng: dict) -> list:
    """按参数类型生成网格；整数参数用 int，浮点参数保留小数。"""
    float_mode = (
        isinstance(meta.get("default"), float)
        or isinstance(meta.get("step"), float)
        or any(isinstance(rng.get(k), float) for k in ("start", "stop", "step"))
    )
    if float_mode:
        low = float(rng.get("start", meta["min"]))
        high = float(rng.get("stop", meta["max"]))
        step = float(rng.get("step", 1) or 1)
        if step <= 0:
            raise BacktestError(f"参数 {name} 的步长需大于 0")
        if low > high:
            raise BacktestError(f"参数 {name} 的最小值不能大于最大值")
        count = int(math.floor((high - low) / step + 1e-9)) + 1
        values = [round(low + i * step, 6) for i in range(max(count, 0))]
    else:
        low = int(rng.get("start", meta["min"]))
        high = int(rng.get("stop", meta["max"]))
        step = int(rng.get("step", 1) or 1)
        if step <= 0:
            raise BacktestError(f"参数 {name} 的步长需大于 0")
        if low > high:
            raise BacktestError(f"参数 {name} 的最小值不能大于最大值")
        values = list(range(low, high + 1, step))
    if not values:
        raise BacktestError(f"参数 {name} 的取值区间为空")
    return values


def _build_grid(strategy_cls, ranges: dict) -> dict:
    spec = {p["name"]: p for p in getattr(strategy_cls, "param_spec", [])}
    grid: dict[str, list] = {}
    for name, meta in spec.items():
        rng = ranges.get(name)
        if not rng:
            default_grid = getattr(strategy_cls, "param_grid", {}).get(name)
            if default_grid is None:
                default_ranges = getattr(strategy_cls, "default_ranges", {}) or {}
                spec_range = default_ranges.get(name)
                if spec_range:
                    default_grid = _grid_values(name, meta, spec_range)
            if default_grid is None:
                continue
            grid[name] = list(default_grid)
            continue
        grid[name] = _grid_values(name, meta, rng)

    combos = math.prod(len(v) for v in grid.values()) if grid else 0
    if combos == 0:
        raise BacktestError("没有可优化的参数")
    if combos > MAX_COMBOS:
        raise BacktestError(f"参数组合 {combos} 组，超过上限 {MAX_COMBOS}，请缩小网格")
    return grid


def _num(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    return value


def _params_from_stats(stats, strategy_cls) -> dict:
    strategy = stats._strategy
    return {name: _num(getattr(strategy, name)) for name in _default_params(strategy_cls)}


def _optimize(bt: Backtest, strategy_cls, ranges: dict):
    grid = _build_grid(strategy_cls, ranges)
    constraint = getattr(strategy_cls, "constraint", None)
    kwargs = {"maximize": "Sharpe Ratio", "return_heatmap": False}
    if constraint is not None:
        kwargs["constraint"] = constraint
    stats = bt.optimize(**grid, **kwargs)
    if stats.get("Sharpe Ratio") is None or not math.isfinite(float(stats["Sharpe Ratio"])):
        raise BacktestError("参数网格没有产生有效结果（可能全部无交易），请调整网格")
    return stats


def _make_bt(df: pd.DataFrame, cfg: RunConfig) -> Backtest:
    return Backtest(
        df,
        STRATEGIES[cfg.strategy],
        cash=cfg.cash,
        commission=cfg.commission,
        trade_on_close=False,
        exclusive_orders=True,
        finalize_trades=True,
    )


# ---------------------------------------------------------------- 序列化
def _metrics(stats) -> dict:
    out = {}
    for key, value in stats.items():
        if key in SKIP_METRICS:
            continue
        if isinstance(value, pd.Timestamp):
            out[key] = value.isoformat()
        elif isinstance(value, pd.Timedelta):
            out[key] = str(value)
        elif isinstance(value, (np.bool_, bool)):
            out[key] = bool(value)
        else:
            out[key] = _num(value)
    return out


def _equity(stats, limit: int = 1200) -> list[dict]:
    curve = stats._equity_curve
    if curve is None or curve.empty:
        return []
    step = max(1, -(-len(curve) // limit))
    sampled = curve.iloc[::step]
    if sampled.index[-1] != curve.index[-1]:
        sampled = pd.concat([sampled, curve.iloc[[-1]]])
    equity_col = "Equity" if "Equity" in curve else curve.columns[0]
    dd_col = "DrawdownPct" if "DrawdownPct" in curve else None
    out = []
    for ts, row in sampled.iterrows():
        item = {"t": ts.date().isoformat(), "e": round(float(row[equity_col]), 2)}
        if dd_col:
            # backtesting.py 的 DrawdownPct 是正数幅度，这里统一成负值便于画图
            item["dd"] = -round(abs(float(row[dd_col])) * 100, 2)
        out.append(item)
    return out


def _trades(stats) -> list[dict]:
    trades = stats._trades
    if trades is None or trades.empty:
        return []
    out = []
    for _, row in trades.iterrows():
        out.append(
            {
                "entry": pd.Timestamp(row["EntryTime"]).date().isoformat(),
                "exit": pd.Timestamp(row["ExitTime"]).date().isoformat(),
                "size": round(float(row["Size"]), 2),
                "entry_price": round(float(row["EntryPrice"]), 3),
                "exit_price": round(float(row["ExitPrice"]), 3),
                "pnl": round(float(row["PnL"]), 2),
                "return_pct": round(float(row["ReturnPct"]) * 100, 2),
                "duration": str(row["Duration"]),
            }
        )
    return out


# ---------------------------------------------------------------- 报告
def _banner(meta: dict) -> str:
    cfg = meta["config"]
    data = meta["data"]
    params = meta.get("params") or {}
    chips = [
        f"{cfg['symbol']}",
        cfg["strategy"],
        f"{data.get('source')} · {data.get('adjust')}",
        f"{data.get('start')} → {data.get('end')} · {data.get('rows')} 根",
        " ".join(f"{k}={v}" for k, v in params.items()),
        f"初始 ¥{cfg['cash']:,.0f} · 费率 {cfg['commission'] * 100:.3f}%",
        f"生成于 {meta['created_at']}",
    ]
    if cfg.get("split"):
        chips.insert(1, f"样本外切分 {cfg['split']} · 图表为测试段")
    chips_html = "".join(f'<span class="chip">{_esc(c)}</span>' for c in chips if c.strip())
    warnings = list(data.get("warnings") or []) + list(meta.get("warnings") or [])
    warn_html = ""
    if warnings:
        items = "".join(f"<li>{_esc(w)}</li>" for w in dict.fromkeys(warnings))
        warn_html = f'<ul class="warns">{items}</ul>'
    return f"""<style>
  #quant-run-meta {{
    position: relative; z-index: 10; display: flex; flex-wrap: wrap; gap: 6px 8px;
    align-items: center; padding: 8px 14px; background: #0f172a; color: #e2e8f0;
    font: 12px/1.6 -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  }}
  #quant-run-meta .chip {{ background: #1e293b; border: 1px solid #334155; border-radius: 999px; padding: 1px 9px; }}
  #quant-run-meta .warns {{ flex-basis: 100%; margin: 2px 0 0; padding-left: 18px; color: #fca5a5; }}
</style>
<div id="quant-run-meta">{chips_html}{warn_html}</div>"""


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _write_report(bt: Backtest, stats, path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bt.plot(results=stats, filename=str(path), open_browser=False)
    html = path.read_text(encoding="utf-8")
    title = f"{meta['config']['symbol']} · {meta['config']['strategy']} · quant-backtest"
    if "<title>" in html:
        start = html.index("<title>") + len("<title>")
        end = html.index("</title>")
        html = html[:start] + _esc(title) + html[end:]
    if "<body>" in html:
        html = html.replace("<body>", "<body>\n" + _banner(meta), 1)
    # backtesting.py 会在 document_ready 时插入一个隐藏 iframe 做站点统计，
    # 本地回测台不需要外部请求，替换成 about:blank。
    html = html.replace("https://kernc.github.io/backtesting.py/plx.gif.html?utm_source=", "about:blank#")
    path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------- 主流程
def _report_url(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(REPORTS_DIR.resolve()).as_posix()
    except ValueError:
        return f"/reports/web/{path.name}"
    return f"/reports/{rel}"


def run(
    config: RunConfig,
    *,
    report_dir: Path = WEB_RUNS_DIR,
    report_name: str | None = None,
    write_manifest: bool = True,
) -> dict:
    started = time.time()
    cfg = config.normalized()
    strategy_cls = STRATEGIES[cfg.strategy]
    warnings: list[str] = []

    data = load_daily(cfg.symbol, start=cfg.start, end=cfg.end, source=cfg.source, refresh=cfg.refresh)
    data_meta = dict(data.attrs.get("meta") or {})
    warnings.extend(data_meta.get("warnings") or [])

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    report_file = f"{cfg.symbol}_{cfg.strategy}_{run_id}.html"
    report_path = Path(report_dir) / (report_name + ".html" if report_name else report_file)

    oos = None
    if cfg.split:
        split_ts = pd.Timestamp(cfg.split)
        train = data[data.index < split_ts]
        test = data[data.index >= split_ts]
        if len(train) < MIN_SPLIT_BARS or len(test) < MIN_SPLIT_BARS:
            raise BacktestError(
                f"切分后训练段 {len(train)} 根、测试段 {len(test)} 根，至少各需 {MIN_SPLIT_BARS} 根"
            )

        bt_train = _make_bt(train, cfg)
        if cfg.optimize:
            train_stats = _optimize(bt_train, strategy_cls, cfg.ranges)
            train_params = _params_from_stats(train_stats, strategy_cls)
        else:
            train_params = _resolve_params(strategy_cls, cfg.params)
            train_stats = bt_train.run(**train_params)

        bt_test = _make_bt(test, cfg)
        test_stats = bt_test.run(**train_params)
        default_params = _default_params(strategy_cls)
        test_default = test_stats if default_params == train_params else bt_test.run(**default_params)
        test_oracle = None
        test_oracle_params = None
        if cfg.optimize:
            test_oracle = _optimize(bt_test, strategy_cls, cfg.ranges)
            test_oracle_params = _params_from_stats(test_oracle, strategy_cls)

        train_sharpe = _num(train_stats.get("Sharpe Ratio"))
        test_sharpe = _num(test_stats.get("Sharpe Ratio"))
        decay = None
        if train_sharpe and train_sharpe > 0 and test_sharpe is not None:
            decay = round(test_sharpe / train_sharpe, 2)

        oos = {
            "split": split_ts.date().isoformat(),
            "mode": "optimize" if cfg.optimize else "fixed",
            "train": {
                "rows": int(len(train)),
                "start": train.index[0].date().isoformat(),
                "end": train.index[-1].date().isoformat(),
                "params": train_params,
                "metrics": _metrics(train_stats),
            },
            "test_params": {
                "rows": int(len(test)),
                "start": test.index[0].date().isoformat(),
                "end": test.index[-1].date().isoformat(),
                "params": train_params,
                "metrics": _metrics(test_stats),
            },
            "test_default": {"params": default_params, "metrics": _metrics(test_default)},
            "test_oracle": (
                {"params": test_oracle_params, "metrics": _metrics(test_oracle)} if test_oracle is not None else None
            ),
            "sharpe_decay": decay,
            "sharpe_decay_note": (
                "训练段夏普 ≤ 0，衰减比无意义" if decay is None else "测试段 Sharpe / 训练段 Sharpe；>0.5 较稳健，<0 说明样本外失效"
            ),
        }
        stats = test_stats
        params = train_params
        chart_bt = bt_test
        chart_stats = test_stats
    else:
        bt = _make_bt(data, cfg)
        if cfg.optimize:
            stats = _optimize(bt, strategy_cls, cfg.ranges)
            params = _params_from_stats(stats, strategy_cls)
        else:
            params = _resolve_params(strategy_cls, cfg.params)
            stats = bt.run(**params)
        chart_bt = bt
        chart_stats = stats

    metrics = _metrics(stats)
    created_at = datetime.now().isoformat(timespec="seconds")
    meta = {
        "run_id": run_id,
        "created_at": created_at,
        "config": asdict(cfg),
        "data": data_meta,
        "params": params,
        "warnings": warnings,
    }
    _write_report(chart_bt, chart_stats, report_path, meta)

    result = {
        "run_id": run_id,
        "created_at": created_at,
        "config": asdict(cfg),
        "data": data_meta,
        "params": params,
        "metrics": metrics,
        "equity": _equity(stats),
        "trades": _trades(stats),
        "oos": oos,
        "warnings": list(dict.fromkeys(warnings)),
        "report_file": report_path.name,
        "report_url": _report_url(report_path),
        "duration_sec": round(time.time() - started, 2),
    }

    if write_manifest:
        manifest_dir = Path(report_dir)
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / f"{run_id}.json").write_text(
            json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        _prune(manifest_dir)

    return result


def _prune(directory: Path) -> None:
    """只保留最近 KEEP_RUNS 次 Web 运行，避免 reports/web 无限增长。"""
    try:
        manifests = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in manifests[KEEP_RUNS:]:
            html = old.with_suffix(".html")
            old.unlink(missing_ok=True)
            html.unlink(missing_ok=True)
    except OSError:
        pass


def run_from_dict(payload: dict, **kwargs) -> dict:
    known = {f.name for f in RunConfig.__dataclass_fields__.values()}
    return run(RunConfig(**{k: v for k, v in payload.items() if k in known}), **kwargs)


def list_runs(limit: int = 30) -> list[dict]:
    if not WEB_RUNS_DIR.exists():
        return []
    items = []
    for path in sorted(WEB_RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items.append(
            {
                "run_id": data.get("run_id"),
                "created_at": data.get("created_at"),
                "symbol": data.get("config", {}).get("symbol"),
                "strategy": data.get("config", {}).get("strategy"),
                "source": data.get("data", {}).get("source"),
                "split": data.get("config", {}).get("split"),
                "return_pct": data.get("metrics", {}).get("Return [%]"),
                "sharpe": data.get("metrics", {}).get("Sharpe Ratio"),
                "report_url": data.get("report_url"),
            }
        )
    return items


def load_run(run_id: str) -> dict:
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{6}", run_id):
        raise BacktestError("运行 ID 不合法")
    path = WEB_RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        raise BacktestError("找不到这次运行")
    return json.loads(path.read_text(encoding="utf-8"))
