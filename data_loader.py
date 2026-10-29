"""A 股日线数据获取，本地 CSV 缓存。

数据源必须可追溯：每次加载都会解析出实际来源（source），并把来源、复权方式、
行数、实际区间、被剔除的未完成 bar 记录在 `df.attrs["meta"]` 里。

规则：
- 数据源优先级：显式参数 > 环境变量 QUANT_DATA_SOURCE > 有 TUSHARE_TOKEN 用 tushare，否则 akshare
- 当日 15:05 前（未收盘），或缓存是盘中抓取留下的最后一根日线，会被剔除，
  避免把半根 K 线当成完整 bar 参与回测
- 读取缓存时校验列名、索引、空表、重复行与 OHLC 合理性；脏缓存会被丢弃并重新拉取
- 每个 source / 标的 / 复权方式一份主缓存，过期后只增量补拉缺失的日线；
  前复权遇到除权会改写历史价格，增量拉取时比对重叠 bar，不一致就全量重拉
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
CACHE_DIR = PROJECT_ROOT / "data"
COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _load_dotenv(path: Path) -> None:
    """读取项目 .env（不覆盖已有环境变量）。

    只处理最简单的 KEY=VALUE / export KEY=VALUE 形式，避免把任意 shell
    代码带进服务进程。token 建议放 .env，而不是依赖 .zshrc。
    """
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")
_load_dotenv(PROJECT_ROOT / ".env.local")
DEFAULT_START = "20180101"
DEFAULT_END = "20261231"
SOURCES = ("tushare", "akshare")

# A 股 15:00 收盘，留 5 分钟给数据源结算
MARKET_CLOSE = dtime(15, 5)
RETRY_MISSING = timedelta(hours=1)


class DataError(RuntimeError):
    """数据获取或校验失败。"""


def resolve_source(source: str | None) -> str:
    """把 'auto'/None 解析成确定的数据源，并把来源交给调用方记录。"""
    if source:
        source = str(source).strip().lower()
        if source and source != "auto":
            if source not in SOURCES:
                raise DataError(f"未知数据源：{source}，可选 {', '.join(SOURCES)}")
            return source

    env = (os.getenv("QUANT_DATA_SOURCE") or "").strip().lower()
    if env and env != "auto":
        if env not in SOURCES:
            raise DataError(f"环境变量 QUANT_DATA_SOURCE={env} 不合法，可选 auto, {', '.join(SOURCES)}")
        return env

    return "tushare" if has_tushare_token() else "akshare"


def has_tushare_token() -> bool:
    return bool((os.getenv("TUSHARE_TOKEN") or "").strip())


def to_ts_code(symbol: str) -> str:
    """600519 -> 600519.SH，000001 -> 000001.SZ，8/4/9 开头 -> .BJ"""
    if "." in symbol:
        return symbol.upper()
    suffix = {"6": "SH", "0": "SZ", "3": "SZ"}.get(symbol[0], "BJ")
    return f"{symbol}.{suffix}"



def cache_file(symbol: str, adjust: str, source: str) -> Path:
    return CACHE_DIR / f"{source}_{symbol}_{adjust}.csv"


def _meta_file(cache: Path) -> Path:
    return cache.with_suffix(".meta.json")


def _read_meta(cache: Path) -> dict:
    try:
        return json.loads(_meta_file(cache).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _legacy_caches(symbol: str, adjust: str, source: str) -> list[Path]:
    """旧版按区间命名的缓存：{source}_{symbol}_{start}_{end}_{adjust}.csv"""
    return [p for p in CACHE_DIR.glob(f"{source}_{symbol}_*_*_{adjust}.csv") if len(p.stem.split("_")) == 5]


def _migrate_legacy(symbol: str, adjust: str, source: str, cache: Path) -> None:
    """把行数最多的旧缓存转成主缓存，然后删掉旧文件。"""
    best, best_rows, best_meta = None, 0, {}
    for path in _legacy_caches(symbol, adjust, source):
        try:
            df = _clean(pd.read_csv(path, index_col=0, parse_dates=True), path.name)
        except (DataError, ValueError, pd.errors.ParserError):
            continue
        if len(df) > best_rows:
            best, best_rows, best_meta = df, len(df), _read_meta(path)
    if best is not None:
        fetched_at = best_meta.get("fetched_at") or datetime.now().isoformat(timespec="seconds")
        start = best_meta.get("start") or best.index[0].strftime("%Y%m%d")
        _write_cache(best, cache, {"symbol": symbol, "source": source, "adjust": adjust,
                                   "start": str(start).replace("-", ""), "fetched_at": fetched_at})
    for path in _legacy_caches(symbol, adjust, source):
        path.unlink(missing_ok=True)
        _meta_file(path).unlink(missing_ok=True)


def last_session_close(now: datetime) -> datetime:
    """最近一个已收盘交易日的收盘时刻（只排除周末，节假日多拉一次无害）。"""
    day = now.date()
    if now.time() < MARKET_CLOSE:
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime.combine(day, MARKET_CLOSE)


def _slice_dates(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    try:
        return df.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    except (ValueError, TypeError):
        return df


def _from_akshare(symbol, start, end, adjust):
    import akshare as ak

    df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end, adjust=adjust)
    if df is None or df.empty:
        raise DataError(f"akshare 未返回数据：{symbol}，请检查代码、日期或网络")
    df = df.rename(columns={"日期": "Date", "开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"})
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date")[COLUMNS]


def _from_tushare(symbol, start, end, adjust):
    import tushare as ts

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise DataError("数据源设为 tushare 但没有设置 TUSHARE_TOKEN 环境变量")
    pro = ts.pro_api(token)
    df = ts.pro_bar(ts_code=to_ts_code(symbol), api=pro, adj=adjust or None, start_date=start, end_date=end)
    if df is None or df.empty:
        raise DataError(f"Tushare 未返回数据：{symbol}，请检查代码、日期或积分权限")
    df = df.rename(columns={"trade_date": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close", "vol": "Volume"})
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date")[COLUMNS]


def _clean(df: pd.DataFrame, where: str) -> pd.DataFrame:
    """校验并规整 OHLCV，脏数据直接报错，避免悄悄污染回测。"""
    if df is None or df.empty:
        raise DataError(f"{where}：数据为空")

    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise DataError(f"{where}：缺少列 {missing}")

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, errors="coerce")
    if df.index.isna().any():
        raise DataError(f"{where}：存在无法解析的日期")
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)

    df = df[COLUMNS].apply(pd.to_numeric, errors="coerce")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna()

    if df.empty:
        raise DataError(f"{where}：清洗后没有有效数据")

    # OHLC 合理性：最高价不能低于开/收/最低，最低价不能高于开/收/最高
    bad = (df["High"] < df[["Open", "Close", "Low"]].max(axis=1)) | (
        df["Low"] > df[["Open", "Close", "High"]].min(axis=1)
    )
    if bad.any():
        raise DataError(f"{where}：有 {int(bad.sum())} 行 OHLC 关系不合理")
    if (df[["Open", "High", "Low", "Close"]] <= 0).any().any():
        raise DataError(f"{where}：存在非正价格")
    if (df["Volume"] < 0).any():
        raise DataError(f"{where}：存在负成交量")

    return df


def _drop_partial_bar(df: pd.DataFrame, fetched_at: datetime | None, now: datetime):
    """剔除当日未完成的日线，返回 (df, 被剔除的日期字符串或 None)。"""
    if df.empty:
        return df, None

    last = df.index[-1]
    today = now.date()
    if last.date() != today:
        return df, None

    intraday_now = now.time() < MARKET_CLOSE
    stale_fetch = (
        fetched_at is None
        or fetched_at.date() < today
        or (fetched_at.date() == today and fetched_at.time() < MARKET_CLOSE)
    )
    if intraday_now or stale_fetch:
        return df.iloc[:-1], last.date().isoformat()
    return df, None


def _fetch(symbol: str, start: str, end: str, adjust: str, source: str) -> pd.DataFrame:
    fetch = _from_tushare if source == "tushare" else _from_akshare
    return fetch(symbol, start, end, adjust)



def _write_cache(df: pd.DataFrame, cache: Path, meta: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    meta = {**meta, "rows": int(len(df)), "end": df.index[-1].strftime("%Y%m%d")}
    df.to_csv(cache)
    _meta_file(cache).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _cache_lock(cache: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(cache, threading.Lock())


def _sync_cache(symbol: str, start: str, adjust: str, source: str, refresh: bool, warnings: list[str]):
    """保证主缓存覆盖 start 至最近收盘日，返回 (df, fetched_at, 是否命中缓存)。"""
    cache = cache_file(symbol, adjust, source)
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    if not cache.exists():
        _migrate_legacy(symbol, adjust, source, cache)

    df, meta = None, {}
    if cache.exists() and not refresh:
        try:
            df = _clean(pd.read_csv(cache, index_col=0, parse_dates=True), f"缓存 {cache.name}")
            meta = _read_meta(cache)
        except (DataError, ValueError, pd.errors.ParserError) as exc:
            warnings.append(f"缓存不可用，已重新拉取：{exc}")
            df = None

    def full(begin: str):
        fresh = _clean(_fetch(symbol, begin, today, adjust, source), f"{source} {symbol}")
        fetched = datetime.now()
        _write_cache(fresh, cache, {"symbol": symbol, "source": source, "adjust": adjust,
                                    "start": begin, "fetched_at": fetched.isoformat(timespec="seconds")})
        return fresh, fetched, False

    cached_start = str(meta.get("start") or "")
    if df is None or not cached_start or cached_start > start:
        if refresh and cache.exists():
            warnings.append("按 refresh 要求忽略缓存，重新拉取")
        return full(min(start, cached_start) if cached_start else start)

    try:
        fetched_at = datetime.fromisoformat(meta["fetched_at"])
    except (KeyError, TypeError, ValueError):
        fetched_at = datetime.fromtimestamp(cache.stat().st_mtime)
    # 收盘后数据源可能还没发布当天日线：缓存缺最新交易日时，每小时最多重试一次
    session = last_session_close(now)
    complete = df.index[-1].date() >= session.date()
    if fetched_at >= session and (complete or now - fetched_at < RETRY_MISSING):
        return df, fetched_at, True

    # 增量：先去掉盘中留下的半根 bar，再从最后一根完整 bar 开始补拉（重叠 1 根用于除权校验）
    base, _ = _drop_partial_bar(df, fetched_at, now)
    if base.empty:
        return full(cached_start)
    anchor = base.index[-1]
    try:
        tail = _clean(_fetch(symbol, anchor.strftime("%Y%m%d"), today, adjust, source), f"{source} {symbol} 增量")
    except Exception as exc:  # noqa: BLE001 - 网络失败时退回旧缓存
        warnings.append(f"增量更新失败，使用 {anchor.date()} 前的缓存：{exc}")
        return df, fetched_at, True
    if anchor in tail.index:
        old, new = float(base.loc[anchor, "Close"]), float(tail.loc[anchor, "Close"])
        if abs(new - old) / old > 0.001:
            warnings.append(f"检测到除权（{anchor.date()} 收盘价 {old} → {new}），已全量重拉")
            return full(cached_start)
    merged = pd.concat([base[base.index < anchor], tail])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    fetched = datetime.now()
    _write_cache(merged, cache, {**meta, "fetched_at": fetched.isoformat(timespec="seconds")})
    return merged, fetched, False


def load_daily(
    symbol: str,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    adjust: str = "qfq",
    source: str | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """返回 backtesting.py 需要的 OHLCV 数据（默认前复权）。

    实际使用的数据源、是否命中缓存、被剔除的未完成 bar 等信息，
    记录在返回值的 `df.attrs["meta"]` 中。
    """
    source = resolve_source(source)
    cache = cache_file(symbol, adjust, source)
    warnings: list[str] = []
    with _cache_lock(cache):
        df, fetched_at, cached = _sync_cache(symbol, start, adjust, source, refresh, warnings)

    df = _slice_dates(df, start, end)
    if df.empty:
        raise DataError(f"{symbol} 在 {start} ~ {end} 没有数据")
    df, dropped = _drop_partial_bar(df, fetched_at, datetime.now())
    if dropped:
        warnings.append(f"已剔除未完成日线 {dropped}（当前未收盘或数据源尚未结算）")
    return _with_meta(
        df.copy(),
        source=source,
        adjust=adjust,
        symbol=symbol,
        cached=cached,
        cache=cache,
        fetched_at=fetched_at,
        dropped=dropped,
        warnings=warnings,
    )


def _with_meta(df, *, source, adjust, symbol, cached, cache, fetched_at, dropped, warnings) -> pd.DataFrame:
    if len(df) < 250:
        warnings.append(f"数据仅 {len(df)} 行，指标可能不稳定")
    df.attrs["meta"] = {
        "symbol": symbol,
        "source": source,
        "adjust": adjust,
        "cached": bool(cached),
        "cache_file": cache.name,
        "fetched_at": fetched_at.isoformat(timespec="seconds") if fetched_at else None,
        "rows": int(len(df)),
        "start": df.index[0].date().isoformat() if len(df) else None,
        "end": df.index[-1].date().isoformat() if len(df) else None,
        "partial_bar_dropped": dropped,
        "warnings": warnings,
    }
    return df


def available_symbols() -> list[dict]:
    """扫描本地主缓存，返回 [{symbol, sources, rows, start, end}]，供 Web 下拉框使用。"""
    found: dict[str, dict] = {}
    if not CACHE_DIR.exists():
        return []
    for path in sorted(CACHE_DIR.glob("*.csv")):
        parts = path.stem.split("_")
        if len(parts) != 3 or parts[0] not in SOURCES:
            continue
        source, symbol, adjust = parts
        meta = _read_meta(path)
        item = found.setdefault(
            symbol,
            {"symbol": symbol, "sources": [], "rows": 0, "start": None, "end": None, "adjust": adjust},
        )
        item["sources"].append(source)
        rows = int(meta.get("rows") or 0)
        if rows > item["rows"] and meta.get("end"):
            item.update(
                rows=rows,
                start=pd.Timestamp(str(meta.get("start"))).date().isoformat(),
                end=pd.Timestamp(str(meta["end"])).date().isoformat(),
                adjust=adjust,
            )
    return sorted(found.values(), key=lambda x: x["symbol"])


def load_index(code: str = "000300") -> pd.DataFrame:
    """指数日线（akshare，不复权），用作模拟仓基准；新鲜度规则同个股。"""
    cache = CACHE_DIR / f"index_{code}.csv"
    now = datetime.now()
    with _cache_lock(cache):
        if cache.exists():
            df = pd.read_csv(cache, index_col=0, parse_dates=True)
            meta = _read_meta(cache)
            try:
                fetched_at = datetime.fromisoformat(meta["fetched_at"])
            except (KeyError, TypeError, ValueError):
                fetched_at = datetime.min
            session = last_session_close(now)
            complete = df.index[-1].date() >= session.date()
            if fetched_at >= session and (complete or now - fetched_at < RETRY_MISSING):
                return df
        try:
            import akshare as ak

            raw = ak.stock_zh_index_daily(symbol=("sh" if code.startswith("000") else "sz") + code)
            raw = raw.rename(columns={"date": "Date", "open": "Open", "high": "High", "low": "Low",
                                      "close": "Close", "volume": "Volume"})
            raw["Date"] = pd.to_datetime(raw["Date"])
            df = _clean(raw.set_index("Date")[COLUMNS], f"指数 {code}")
        except Exception as exc:  # noqa: BLE001 - 网络失败时用旧缓存
            if cache.exists():
                return pd.read_csv(cache, index_col=0, parse_dates=True)
            raise DataError(f"指数 {code} 获取失败：{exc}") from exc
        _write_cache(df, cache, {"symbol": code, "source": "akshare", "start": df.index[0].strftime("%Y%m%d"),
                                 "fetched_at": now.isoformat(timespec="seconds")})
        return df

