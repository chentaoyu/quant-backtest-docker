import pandas as pd
import pytest

import sim
import watchlist
from conftest import make_bars
from holdings import HoldingError


@pytest.fixture
def env(tmp_path, monkeypatch):
    bars = {s: make_bars(700, start="2023-01-02", seed=i) for i, s in enumerate(["600000", "000001"])}
    monkeypatch.setattr(sim, "SIM_FILE", tmp_path / "sim.json")
    monkeypatch.setattr(sim, "_load", lambda symbol, since, warmup_years=3: bars[symbol])
    monkeypatch.setattr(sim, "load_index", lambda code="000300": bars["000001"])
    monkeypatch.setattr(sim, "load_checkups", lambda: {})
    monkeypatch.setattr(sim, "_names", lambda: {})
    return bars


def _account(**extra):
    return {"id": "a", "name": "t", "initial_cash": 1e6, "created_date": "2024-01-01", "fees": sim.DEFAULT_FEES,
            "slots": [], "orders": [], **extra}


def _slot(**extra):
    return {"id": "s", "symbol": "600000", "name": "x", "strategy": "sma_cross", "params": {"n1": 5, "n2": 20},
            "cash": 100000, "start_date": "2024-01-01", "end_date": None, "entry_on_start": False, **extra}


def test_fee_and_limits():
    assert sim._fee(sim.DEFAULT_FEES, 10000, "BUY") == 5.0  # 最低 5 元
    assert sim._fee(sim.DEFAULT_FEES, 100000, "SELL") == pytest.approx(25 + 50)
    assert sim._limit_hit("600000", 11.0, 10.0, "BUY")
    assert not sim._limit_hit("300750", 11.0, 10.0, "BUY")  # 创业板 20%
    assert sim._limit_hit("600000", 9.0, 10.0, "SELL")


def test_slot_trades_in_lots_after_start(env):
    result = sim.replay_slot(_slot(), env["600000"], sim.DEFAULT_FEES)
    assert result["trades"], "样本数据应产生交易"
    assert all(t["shares"] % 100 == 0 for t in result["trades"])
    assert all(t["date"] > "2024-01-01" for t in result["trades"])
    sides = [t["side"] for t in result["trades"]]
    assert all(a != b for a, b in zip(sides, sides[1:]))  # 买卖交替


def test_stopped_slot_liquidates(env):
    result = sim.replay_slot(_slot(end_date="2024-06-01"), env["600000"], sim.DEFAULT_FEES)
    assert result["shares"] == 0 and result["status"] == "stopped"
    assert all(t["date"] <= "2024-06-10" for t in result["trades"])


def test_account_equity_is_consistent(env):
    orders = [
        {"id": "o1", "symbol": "000001", "name": "y", "side": "BUY", "shares": 1000, "placed_date": "2024-02-01",
         "placed_at": "2024-02-01T10:00", "cancelled": False},
        {"id": "o2", "symbol": "000001", "name": "y", "side": "SELL", "shares": 1000, "placed_date": "2024-02-01",
         "placed_at": "2024-02-01T10:01", "cancelled": False},
    ]
    sim._write([_account(slots=[_slot(), _slot(id="s2", end_date="2024-05-01")], orders=orders)])
    state = sim.account_state("a")
    status = {o["id"]: o for o in state["orders"]}
    assert status["o1"]["status"] == "filled"
    assert status["o2"]["status"] == "failed" and "T+1" in status["o2"]["reason"]
    s = state["summary"]
    active_cash = sum(x["cash_left"] for x in state["slots"] if x["status"] != "stopped")
    assert s["equity"] == pytest.approx(s["cash"] + s["market_value"] + active_cash, abs=0.05)
    assert state["benchmark"] is not None


def test_add_slot_checks_free_cash(env, monkeypatch):
    monkeypatch.setattr(sim, "_today", lambda: "2026-01-05")
    sim._write([_account(created_date="2026-01-05")])
    sim.add_slot("a", "600000", 900000, strategy="sma_cross")
    with pytest.raises(sim.SimError, match="可用现金"):
        sim.add_slot("a", "000001", 200000, strategy="sma_cross")
    with pytest.raises(sim.SimError, match="已在这个账户"):
        sim.add_slot("a", "600000", 1000, strategy="sma_cross")


def test_watchlist_params_validation():
    assert watchlist.check_params("sma_cross", {"n1": 10, "n2": 30}) == {"n1": 10, "n2": 30}
    with pytest.raises(HoldingError, match="约束"):
        watchlist.check_params("sma_cross", {"n1": 40, "n2": 30})
    with pytest.raises(HoldingError, match="之间"):
        watchlist.check_params("sma_cross", {"n1": 1})
