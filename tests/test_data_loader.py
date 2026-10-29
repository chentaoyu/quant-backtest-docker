from datetime import datetime

import pandas as pd
import pytest

import data_loader
from conftest import make_bars


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(data_loader, "CACHE_DIR", tmp_path)
    full = make_bars(300, start="2025-01-01")
    calls = []

    def fake_fetch(symbol, start, end, adjust, source):
        calls.append(start)
        return full.loc[pd.Timestamp(start) : pd.Timestamp(end)].copy()

    monkeypatch.setattr(data_loader, "_fetch", fake_fetch)
    return full, calls, tmp_path


def _age_cache(path, when="2020-01-01T00:00:00"):
    meta = data_loader._read_meta(path)
    meta["fetched_at"] = when
    data_loader._meta_file(path).write_text(__import__("json").dumps(meta))


def test_cache_hit_then_incremental(store, monkeypatch):
    full, calls, tmp = store
    first = full.iloc[:200]
    monkeypatch.setattr(data_loader, "_fetch", lambda *a: (calls.append(a[1]), first.copy())[1])
    df = data_loader.load_daily("600000", start="20250101", source="akshare")
    assert len(df) == 200 and calls == ["20250101"]

    df = data_loader.load_daily("600000", start="20250101", source="akshare")
    assert len(calls) == 1  # 新鲜缓存直接命中

    cache = data_loader.cache_file("600000", "qfq", "akshare")
    _age_cache(cache)
    monkeypatch.setattr(
        data_loader, "_fetch", lambda s, start, end, *a: (calls.append(start), full.loc[pd.Timestamp(start):].copy())[1]
    )
    df = data_loader.load_daily("600000", start="20250101", source="akshare")
    assert calls[-1] == first.index[-1].strftime("%Y%m%d")  # 从最后一根完整 bar 开始补
    assert len(df) == len(full)
    assert df.attrs["meta"]["cached"] is False


def test_ex_dividend_triggers_full_refetch(store, monkeypatch):
    full, calls, tmp = store
    data_loader.load_daily("600000", start="20250101", source="akshare")
    cache = data_loader.cache_file("600000", "qfq", "akshare")
    _age_cache(cache)
    adjusted = full * 0.9  # 前复权整体下移，模拟除权
    adjusted["Volume"] = full["Volume"]
    monkeypatch.setattr(data_loader, "_fetch", lambda s, start, *a: (calls.append(start), adjusted.loc[pd.Timestamp(start):].copy())[1])
    df = data_loader.load_daily("600000", start="20250101", source="akshare")
    assert calls[-1] == "20250101"
    assert df["Close"].iloc[0] == pytest.approx(full["Close"].iloc[0] * 0.9)
    assert any("除权" in w for w in df.attrs["meta"]["warnings"])


def test_last_session_close():
    assert data_loader.last_session_close(datetime(2026, 10, 28, 10)).date().isoformat() == "2026-10-27"
    assert data_loader.last_session_close(datetime(2026, 10, 28, 16)).date().isoformat() == "2026-10-28"
    # 周一上午 → 上周五
    assert data_loader.last_session_close(datetime(2026, 10, 26, 9)).date().isoformat() == "2026-10-23"


def test_refetch_when_latest_session_missing(store, monkeypatch):
    full, calls, tmp = store
    data_loader.load_daily("600000", start="20250101", source="akshare")
    cache = data_loader.cache_file("600000", "qfq", "akshare")
    # 收盘后刚抓过，但数据里缺最新交易日（数据源未发布），超过 1 小时应重新补拉
    session = data_loader.last_session_close(datetime.now())
    last = data_loader.pd.read_csv(cache, index_col=0, parse_dates=True).index[-1].date()
    if last >= session.date():
        pytest.skip("样本数据已覆盖最新交易日")
    _age_cache(cache, (session + data_loader.timedelta(minutes=1)).isoformat())
    n = len(calls)
    data_loader.load_daily("600000", start="20250101", source="akshare")
    assert len(calls) == n + (1 if datetime.now() - session > data_loader.RETRY_MISSING else 0)
