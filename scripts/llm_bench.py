"""本地模型工具调用对比测试：同一组任务 + mock 工具，比较速度与输出质量。

用法：python3 scripts/llm_bench.py qwen3.5:27b qwen3.5:35b-a3b [--think]
"""

import json
import sys
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434/api/chat"

TOOLS = [
    {"type": "function", "function": {
        "name": "get_holdings", "description": "获取当前持仓列表（代码、名称、股数、成本价、现价）",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "run_backtest",
        "description": "对单只股票运行滚动样本外回测（训练3年/测试1年），返回样本外夏普、年化收益、最大回撤、交易次数",
        "parameters": {"type": "object", "properties": {
            "symbol": {"type": "string", "description": "6位股票代码"},
            "strategy": {"type": "string", "enum": ["sma_cross", "macd", "rsi_reversion", "bollinger", "donchian", "momentum"]},
        }, "required": ["symbol", "strategy"]}}},
    {"type": "function", "function": {
        "name": "get_market_snapshot", "description": "获取A股全市场快照：指数、涨跌家数、涨跌停数、领涨领跌板块",
        "parameters": {"type": "object", "properties": {}}}},
]

BACKTESTS = {
    "sma_cross": {"oos_sharpe": 0.31, "annual_return": 0.062, "max_drawdown": -0.214, "trades": 18},
    "macd": {"oos_sharpe": 0.87, "annual_return": 0.143, "max_drawdown": -0.126, "trades": 34},
}


def mock_tool(name: str, args: dict) -> dict:
    if name == "get_holdings":
        return {"holdings": [
            {"symbol": "600519", "name": "贵州茅台", "shares": 100, "cost": 1720.0, "price": 1598.5},
            {"symbol": "300750", "name": "宁德时代", "shares": 300, "cost": 198.0, "price": 236.4},
        ]}
    if name == "run_backtest":
        return {"symbol": args.get("symbol"), "strategy": args.get("strategy"),
                **BACKTESTS.get(args.get("strategy"), {"oos_sharpe": 0.1, "annual_return": 0.01, "max_drawdown": -0.3, "trades": 10})}
    if name == "get_market_snapshot":
        return {"sh_index": {"close": 3268.2, "pct": -1.42}, "up": 812, "down": 4371, "limit_up": 23, "limit_down": 61,
                "top_sectors": ["黄金", "电力"], "bottom_sectors": ["半导体", "白酒", "证券"]}
    return {"error": f"unknown tool {name}"}


TASKS = [
    {
        "id": "research",
        "prompt": "看下我持仓里亏损的那只股票，分别用 sma_cross 和 macd 做样本外回测，告诉我哪个策略更适合它，并给出一句操作建议。",
        "check": lambda calls, text: {
            "调用了持仓": any(c["name"] == "get_holdings" for c in calls),
            "回测参数正确": {(c["args"].get("symbol"), c["args"].get("strategy")) for c in calls if c["name"] == "run_backtest"}
                       >= {("600519", "sma_cross"), ("600519", "macd")},
            "结论选 macd": "macd" in text.lower() and "0.87" in text,
        },
    },
    {
        "id": "monitor",
        "prompt": "先查一下大盘情况和我的持仓，然后只输出一个 JSON（不要其他文字）："
                  '{"level": "info|warn|alert", "summary": "不超过40字的盘中提醒"}',
        "check": lambda calls, text: {
            "调用了快照": any(c["name"] == "get_market_snapshot" for c in calls),
            "调用了持仓": any(c["name"] == "get_holdings" for c in calls),
            "输出合法JSON": _json_ok(text),
        },
    },
]

SYSTEM = "你是A股量化助手。必须通过工具获取数据，不要编造数字。回答简洁，用中文。"


def _json_ok(text: str) -> bool:
    s = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        obj = json.loads(s)
        return obj.get("level") in ("info", "warn", "alert") and len(obj.get("summary", "")) <= 60
    except Exception:
        return False


def chat(model: str, messages: list, think: bool) -> dict:
    body = {"model": model, "messages": messages, "tools": TOOLS, "stream": False, "think": think,
            "options": {"temperature": 0, "num_ctx": 8192}}
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def unload_all() -> None:
    """卸载所有已加载模型，避免多个大模型争抢内存导致测速失真。"""
    with urllib.request.urlopen(OLLAMA.replace("/chat", "/ps"), timeout=10) as r:
        loaded = [m["name"] for m in json.load(r).get("models", [])]
    for name in loaded:
        body = json.dumps({"model": name, "keep_alive": 0}).encode()
        urllib.request.urlopen(urllib.request.Request(OLLAMA.replace("/chat", "/generate"), body), timeout=60).read()


def run_task(model: str, task: dict, think: bool) -> dict:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task["prompt"]}]
    calls, stat = [], {"rounds": 0, "prompt_tok": 0, "prompt_s": 0.0, "gen_tok": 0, "gen_s": 0.0}
    t0 = time.time()
    for _ in range(8):
        resp = chat(model, messages, think)
        stat["rounds"] += 1
        stat["prompt_tok"] += resp.get("prompt_eval_count", 0)
        stat["prompt_s"] += resp.get("prompt_eval_duration", 0) / 1e9
        stat["gen_tok"] += resp.get("eval_count", 0)
        stat["gen_s"] += resp.get("eval_duration", 0) / 1e9
        msg = resp["message"]
        messages.append(msg)
        if not msg.get("tool_calls"):
            break
        for tc in msg["tool_calls"]:
            fn = tc["function"]
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            calls.append({"name": fn["name"], "args": args})
            messages.append({"role": "tool", "tool_name": fn["name"], "content": json.dumps(mock_tool(fn["name"], args), ensure_ascii=False)})
    text = msg.get("content", "")
    return {"wall_s": time.time() - t0, **stat, "calls": calls, "text": text, "checks": task["check"](calls, text)}


def main() -> None:
    think = "--think" in sys.argv
    models = [a for a in sys.argv[1:] if not a.startswith("--")]
    rows = []
    for model in models:
        try:
            unload_all()
            chat(model, [{"role": "user", "content": "hi"}], False)  # 预热加载
        except Exception as exc:
            print(f"\n跳过 {model}: {exc}")
            continue
        for task in TASKS:
            r = run_task(model, task, think)
            rows.append((model, task["id"], r))
            print(f"\n=== {model} / {task['id']} ===")
            print("工具调用:", json.dumps(r["calls"], ensure_ascii=False))
            print("最终输出:", r["text"])
            print("检查项:", r["checks"], f"| 耗时 {r['wall_s']:.1f}s, 生成 {r['gen_tok'] / max(r['gen_s'], 1e-9):.1f} tok/s")

    print(f"\n{'模型':<22}{'任务':<10}{'总耗时s':>8}{'轮数':>5}{'生成tok/s':>10}{'预填tok/s':>10}{'生成tok':>8}  通过")
    for model, tid, r in rows:
        gen = r["gen_tok"] / r["gen_s"] if r["gen_s"] else 0
        pre = r["prompt_tok"] / r["prompt_s"] if r["prompt_s"] else 0
        passed = f"{sum(r['checks'].values())}/{len(r['checks'])}"
        print(f"{model:<22}{tid:<10}{r['wall_s']:>8.1f}{r['rounds']:>5}{gen:>10.1f}{pre:>10.1f}{r['gen_tok']:>8}  {passed}")


if __name__ == "__main__":
    main()
