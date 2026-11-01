"""Agent HTTP 服务。

启动：uv run uvicorn agent.server:app --port 8100
对话：curl -s localhost:8100/api/agent/chat -H 'Content-Type: application/json' -d '{"message":"我的持仓今天怎么样"}'
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent import llm, tools
from agent.monitor import market, store
from agent.monitor.runner import monitor, sse_stream

SYSTEM_PROMPT = """你是用户的 A 股量化投研助手，今天是 {today}。
- 数据必须来自工具，不要编造任何价格、收益、指标；工具报错就如实说明。
- 用户要求的每一步都要调用对应工具完成，全部做完再回答：要求回测就必须调用 run_backtest，不能拿体检结果代替。
- 体检（get_checkup，滚动样本外）和回测（run_backtest，单次区间）是不同数据，引用时注明来源。
- 个股所属行业以工具返回的 industry 为准；行业分类口径不同时（如 Tushare 行业 vs 板块资金行业）按名称近似匹配并说明。
- 涉及“哪个策略更好”时，以样本外指标为准，并说明交易次数是否足够（少于 10 次结论不可靠）。
- 回答用中文，先给结论再列关键数字，简洁，不写空话。
- 只做分析和建议，不替用户下单；必要时提示风险。"""

@asynccontextmanager
async def lifespan(_app: FastAPI):
    monitor.start()
    yield
    monitor.stop()


app = FastAPI(title="quant-agent", version="0.2.0", lifespan=lifespan)


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[Turn] = Field(default_factory=list)
    model: str = "main"
    reasoning: str | None = None
    max_steps: int = Field(default=8, ge=1, le=20)


def ask(message: str, history: list[dict] | None = None, model: str = "main",
        reasoning: str | None = None, max_steps: int = 8) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=datetime.now().strftime("%Y-%m-%d %A"))},
                *(history or []), {"role": "user", "content": message}]
    result = llm.run_agent(messages, schemas=tools.schemas(), call=tools.call,
                           model=model, reasoning=reasoning, max_steps=max_steps)
    result.pop("messages")
    return result


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/agent/status")
def status() -> dict:
    """依赖检查：LLM 服务、所需模型、回测服务。"""
    out = {"llm_base_url": llm.BASE_URL, "models": llm.MODELS, "web_url": tools.WEB_URL}
    try:
        available = llm.list_models()
        out["llm"] = {"ok": True, "missing": [m for m in llm.MODELS.values() if m not in available]}
    except llm.LLMError as exc:
        out["llm"] = {"ok": False, "error": str(exc)}
    try:
        tools._web("GET", "/api/health", timeout=5)
        out["web"] = {"ok": True}
    except tools.ToolError as exc:
        out["web"] = {"ok": False, "error": str(exc)}
    return out


@app.get("/api/agent/tools")
def tool_list() -> list[dict]:
    return tools.schemas()


@app.post("/api/agent/chat")
def chat(payload: ChatRequest) -> dict:
    try:
        return ask(payload.message, [t.model_dump() for t in payload.history], payload.model,
                   payload.reasoning, payload.max_steps)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------- 盯盘
@app.get("/api/agent/monitor/status")
def monitor_status() -> dict:
    return monitor.info()


@app.post("/api/agent/monitor/tick")
def monitor_tick() -> dict:
    """立即跑一轮（不受交易时段限制，便于盘后检查/调试）。"""
    try:
        new = monitor.tick()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"盯盘失败：{exc}") from exc
    return {"new": new, "status": monitor.info()}


@app.get("/api/agent/monitor/market")
def monitor_market(refresh: bool = False) -> dict:
    if refresh or monitor.market is None:
        monitor.market = market.live_market()
    return monitor.market


@app.get("/api/agent/alerts")
def alerts(limit: int = 100, since_id: int = 0, day: str | None = None) -> list[dict]:
    return store.recent(max(1, min(limit, 500)), since_id, day)


@app.get("/api/agent/alerts/stream")
def alerts_stream(last_id: int | None = None) -> StreamingResponse:
    return StreamingResponse(sse_stream(last_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
