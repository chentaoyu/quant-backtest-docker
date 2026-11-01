import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.monitor import rules, runner, store  # noqa: E402


def quote(price, pre=10.0):
    return {"price": price, "pre_close": pre, "high": max(price, pre), "low": min(price, pre)}


def holding(**kw):
    return {"symbol": "600000", "name": "浦发银行", "kind": "holding", "cost_price": 10.0, **kw}


def watch(**kw):
    return {"symbol": "600000", "name": "浦发银行", "kind": "watch", **kw}


def rules_of(alerts):
    return {a["rule"]: a["level"] for a in alerts}


# ---------------------------------------------------------------- 个股规则
def test_move_threshold_scales_with_price_limit():
    assert rules_of(rules.stock_alerts(watch(), quote(10.6))) == {"move_up": "warn"}  # 主板 +6% ≥ 5%
    assert rules_of(rules.stock_alerts(watch(), quote(9.1))) == {"move_down": "alert"}  # -9% ≥ 8%
    assert rules.stock_alerts(watch(symbol="300001"), quote(10.6)) == []  # 创业板 20%：+6% 不报
    st = watch(name="*ST 某某")
    assert rules_of(rules.stock_alerts(st, quote(10.3))) == {"move_up": "warn"}  # ST 5%：+3% ≥ 2.5%


def test_limit_up_and_down():
    assert rules_of(rules.stock_alerts(watch(), quote(11.0))) == {"limit_up": "warn"}
    assert rules_of(rules.stock_alerts(holding(cost_price=None), quote(11.0))) == {"limit_up": "alert"}
    assert rules_of(rules.stock_alerts(watch(), quote(9.0))) == {"limit_down": "alert"}


def test_holding_cost_and_stops():
    alerts = rules_of(rules.stock_alerts(holding(cost_price=10.0), quote(9.9, pre=10.05)))
    assert alerts == {"cost_break": "warn"}
    alerts = rules_of(rules.stock_alerts(holding(cost_price=12.0, stop_loss_pct=15), quote(9.9, pre=10.0)))
    assert alerts == {"stop_loss": "alert"}  # 浮亏 17.5%
    alerts = rules_of(rules.stock_alerts(holding(cost_price=8.0, take_profit_pct=20), quote(10.1)))
    assert alerts == {"take_profit": "warn"}
    assert rules_of(rules.stock_alerts(holding(cost_price=10.0), quote(10.05, pre=9.95))) == {"cost_regain": "info"}


@pytest.mark.parametrize("trig,price,hit", [
    ({"action": "SELL", "fires_flat": False, "below": 9.5, "above": None}, 9.4, True),
    ({"action": "SELL", "fires_flat": False, "below": 9.5, "above": None}, 9.6, False),
    ({"action": "BUY", "fires_flat": False, "below": None, "above": 10.5}, 10.5, True),
    ({"action": "BUY", "fires_flat": True, "below": 9.8, "above": None}, 10.0, True),  # 平收也触发
    ({"action": "BUY", "fires_flat": True, "below": 9.8, "above": None}, 9.7, False),
    ({"action": "BUY", "fires_flat": False, "below": None, "above": None}, 10.0, False),
    (None, 10.0, False),
])
def test_trigger_hit(trig, price, hit):
    assert rules.trigger_hit(trig, price) is hit


def test_signal_alert_level_depends_on_kind():
    sell = {"action": "SELL", "fires_flat": False, "below": 9.9, "above": None}
    held = rules.stock_alerts(holding(cost_price=None, triggers=sell, strategy="macd"), quote(9.85))
    assert rules_of(held) == {"signal": "warn"} and "卖出" in held[0]["title"]
    assert rules_of(rules.stock_alerts(watch(triggers=sell), quote(9.85))) == {"signal": "info"}


# ---------------------------------------------------------------- 市场规则
def test_market_alerts():
    market = {
        "indexes": [{"code": "399006.SZ", "name": "创业板指", "price": 2400.0, "change_pct": -3.5},
                    {"code": "000001.SH", "name": "上证指数", "price": 3600.0, "change_pct": -1.0},
                    {"code": "000300.SH", "name": "沪深300", "price": 4000.0, "change_pct": 2.1}],
        "breadth": {"up": 500, "down": 4500, "limit_up": 20, "limit_down": 60, "down_over_5pct": 900,
                    "down_ratio": 0.9},
    }
    got = {(a["rule"], a["symbol"]): a["level"] for a in rules.market_alerts(market)}
    assert got == {("index_drop", "399006.SZ"): "alert", ("index_rise", "000300.SH"): "info",
                   ("breadth_down", None): "warn", ("limit_down_wave", None): "alert"}
    assert rules.market_alerts({"indexes": None, "breadth": None}) == []


# ---------------------------------------------------------------- 存储 + 调度去重
@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "m.db")


def test_store_roundtrip_and_fired(db):
    store.add("2026-11-02T10:00:00", "2026-11-02", [
        {"rule": "move_down", "level": "warn", "symbol": "600000", "title": "t", "data": {"x": 1}},
        {"rule": "move_down", "level": "alert", "symbol": "600000", "title": "t2"},
    ])
    assert store.fired("2026-11-02") == {("move_down", "600000"): 2}
    rows = store.recent()
    assert [r["title"] for r in rows] == ["t2", "t"] and rows[1]["data"] == {"x": 1}
    assert store.recent(since_id=rows[0]["id"]) == []
    assert store.max_id() == rows[0]["id"]


def test_tick_dedupes_and_escalates(db, monkeypatch):
    prices = {"600000": 10.6}
    monkeypatch.setattr(runner, "NOTE_ENABLED", False)
    monkeypatch.setattr(runner.market, "live_market", lambda: {"indexes": [], "breadth": None, "sectors": None})
    monkeypatch.setattr(runner.market, "live_quotes", lambda syms: {s: quote(prices[s]) for s in syms})
    monkeypatch.setattr(runner.tools, "_industries", lambda: {})
    monkeypatch.setattr(runner.tools, "_web", lambda method, path, *a, **k: {"rows": [
        {"symbol": "600000", "name": "浦发银行", "signal": None, "used": None}] if "watchlist" in path else []})

    m = runner.Monitor()
    assert rules_of(m.tick()) == {"move_up": "warn"}
    assert m.tick() == []  # 同级别不重复
    prices["600000"] = 10.85  # +8.5% 升级为 alert
    assert rules_of(m.tick()) == {"move_up": "alert"}
    assert m.info()["watch_count"] == 1 and m.status["ticks"] == 3


def test_sse_stream_yields_new_alerts(db):
    gen = runner.sse_stream(last_id=0, poll=0, ping=999)
    assert next(gen).startswith("retry:")
    store.add("2026-11-02T10:00:00", "2026-11-02", [{"rule": "r", "level": "info", "symbol": None, "title": "hello"}])
    event = next(gen)
    assert event.startswith("id: 1\nevent: alert\n") and '"title": "hello"' in event


# ---------------------------------------------------------------- web 反向代理
def test_web_proxies_agent_api(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from fastapi.testclient import TestClient

    import web.app as webapp

    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"path": "%s"}' % self.path.encode()
            status = 404 if "missing" in self.path else 200
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(webapp, "AGENT_URL", f"http://127.0.0.1:{server.server_port}")
    client = TestClient(webapp.app)
    try:
        res = client.get("/api/agent/alerts?limit=5")
        assert res.status_code == 200 and res.json() == {"path": "/api/agent/alerts?limit=5"}
        assert client.get("/api/agent/missing").status_code == 404  # 上游状态码透传
    finally:
        server.shutdown()
    monkeypatch.setattr(webapp, "AGENT_URL", "http://127.0.0.1:9")  # 不可达
    assert "Agent 服务不可用" in client.get("/api/agent/monitor/status").json()["detail"]
