import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import llm, server, tools  # noqa: E402


def tool_call(name, args="{}", cid="c1"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}


@pytest.fixture
def fake_chat(monkeypatch):
    """按顺序返回预设的模型消息，并记录每次收到的 messages。"""
    calls = []

    def install(*replies):
        queue = list(replies)

        def chat(messages, **kwargs):
            calls.append([dict(m) for m in messages])
            return {"message": queue.pop(0), "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

        monkeypatch.setattr(llm, "chat", chat)
        return calls

    return install


# ---------------------------------------------------------------- 工具调用循环
def test_run_agent_executes_tools_then_answers(fake_chat):
    calls = fake_chat(
        {"role": "assistant", "content": None, "tool_calls": [tool_call("echo", '{"x": 1}')]},
        {"role": "assistant", "content": "完成"},
    )
    seen = []
    result = llm.run_agent([{"role": "user", "content": "hi"}], schemas=[],
                           call=lambda name, args: seen.append((name, args)) or {"y": 2})
    assert result["reply"] == "完成"
    assert seen == [("echo", {"x": 1})]
    assert result["steps"][0]["tool"] == "echo" and result["steps"][0]["ok"]
    assert result["usage"] == {"prompt_tokens": 20, "completion_tokens": 10}
    # 第二轮请求里带上了工具结果
    assert calls[1][-1] == {"role": "tool", "tool_call_id": "c1", "content": '{"y": 2}'}


def test_run_agent_stops_at_max_steps(fake_chat):
    fake_chat(*[{"role": "assistant", "content": "", "tool_calls": [tool_call("echo")]}] * 3)
    result = llm.run_agent([], schemas=[], call=lambda *_: {"error": "x"}, max_steps=3)
    assert "最大轮数" in result["reply"]
    assert len(result["steps"]) == 3 and not result["steps"][0]["ok"]


def test_run_agent_tolerates_bad_arguments(fake_chat):
    fake_chat({"role": "assistant", "tool_calls": [tool_call("echo", "{bad json")]},
              {"role": "assistant", "content": "ok"})
    seen = []
    llm.run_agent([], schemas=[], call=lambda n, a: seen.append(a) or {})
    assert seen == [{}]


def test_long_tool_result_is_clipped():
    assert len(llm._clip("x" * 10000)) < 7000


# ---------------------------------------------------------------- 工具层
def test_call_reports_errors_instead_of_raising():
    assert "没有工具" in tools.call("nope", {})["error"]
    assert "参数错误" in tools.call("get_holdings", {"bad": 1})["error"]


def test_every_tool_has_valid_schema():
    names = {s["function"]["name"] for s in tools.schemas()}
    assert {"get_holdings", "run_backtest", "get_checkup", "market_snapshot"} <= names
    for s in tools.schemas():
        params = s["function"]["parameters"]
        assert set(params["required"]) <= set(params["properties"])


def test_run_backtest_compacts_oos_result(monkeypatch):
    metrics = {"Sharpe Ratio": 0.87654, "# Trades": 34, "Return [%]": 14.3, "Equity Final [$]": 1}
    monkeypatch.setattr(tools, "_web", lambda method, path, body=None, **_: {
        "params": {"fast": 12}, "metrics": metrics, "report_url": "/r.html", "warnings": [],
        "oos": {"split": "2024-01-01", "train": {"metrics": metrics}, "test_default": {"metrics": metrics},
                "sharpe_decay": 1.0},
    })
    out = tools.run_backtest("600519", "macd", split="20240101")
    assert out["metrics"]["sharpe"] == 0.877 and out["metrics"]["trades"] == 34
    assert "Equity Final [$]" not in str(out)
    assert out["oos"]["split"] == "2024-01-01"


def test_stock_overview_computes_returns_and_ma(monkeypatch):
    bars = [[f"d{i}", 10, 10 + i, 9, 11 + i, 100] for i in range(300)]
    monkeypatch.setattr(tools, "_web", lambda *a, **k: {"bars": bars, "signal": None})
    out = tools.get_stock_overview("600519")
    assert out["close"] == 309
    assert out["change_pct"]["1d"] == round((309 / 308 - 1) * 100, 2)
    assert out["ma"]["ma5"] == 307
    assert out["volume_ratio_5d"] == 1.0
    assert "signal" not in out


def test_checkup_runs_job_when_missing(monkeypatch):
    state = {"checked": False}

    def web(method, path, body=None, **_):
        if path == "/api/checkups/600519":
            if not state["checked"]:
                raise tools.ToolError("还没有体检记录")
            return {"symbol": "600519", "checked_at": "t", "data_end": "d", "best": "macd",
                    "strategies": {"macd": {"oos_sharpe": 0.9, "oos_trades": 20, "live_params": {}, "windows": []}}}
        if path == "/api/holdings/checkup":
            state["checked"] = True
            return {"job": {"id": "j1", "status": "done", "pending": [], "errors": {}}}
        raise AssertionError(path)

    monkeypatch.setattr(tools, "_web", web)
    out = tools.get_checkup("600519")
    assert out["best"] == "macd" and "windows" not in out["strategies"]["macd"]


# ---------------------------------------------------------------- 服务
def test_ask_builds_messages_and_hides_transcript(fake_chat):
    calls = fake_chat({"role": "assistant", "content": "你好"})
    result = server.ask("在吗", history=[{"role": "user", "content": "前一句"}, {"role": "assistant", "content": "嗯"}])
    assert result["reply"] == "你好" and "messages" not in result
    sent = calls[0]
    assert sent[0]["role"] == "system" and "A 股" in sent[0]["content"]
    assert [m["content"] for m in sent[1:]] == ["前一句", "嗯", "在吗"]
