"""LLM 网关：只认 OpenAI 兼容接口（默认本机 Ollama），换 LM Studio / 云端模型只改配置（页面或 .env）。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

from agent import settings

MAX_TOOL_CHARS = 6000  # 单次工具结果塞进上下文的上限，长上下文会拖慢预填

# 本地模型不走系统代理（macOS 开了全局代理时 urllib 会自动套上）
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class LLMError(RuntimeError):
    pass


def config() -> settings.LLMSettings:
    return settings.get().llm


def _request(method: str, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
    cfg = config()
    req = urllib.request.Request(
        cfg.base_url.rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg.api_key}"},
    )
    try:
        with _opener.open(req, timeout=timeout or cfg.timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise LLMError(f"LLM 接口返回 {exc.code}：{exc.read().decode(errors='replace')[:300]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LLMError(f"连不上 LLM 服务 {cfg.base_url}：{exc}") from exc


def model_name(model: str) -> str:
    cfg = config()
    return {"main": cfg.main, "fast": cfg.fast}.get(model, model)


def list_models() -> list[str]:
    return [m["id"] for m in _request("GET", "/models", timeout=10).get("data", [])]


def model_details() -> list[dict]:
    """可选模型：Ollama 时补充体积/参数量/量化/是否已加载，其他 OpenAI 兼容服务只有名字。"""
    root = config().base_url.rstrip("/").removesuffix("/v1")
    try:
        with _opener.open(root + "/api/tags", timeout=5) as resp:
            tags = json.load(resp)["models"]
        with _opener.open(root + "/api/ps", timeout=5) as resp:
            loaded = {m["name"] for m in json.load(resp)["models"]}
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        return [{"name": m} for m in list_models()]
    return [{"name": m["name"], "size_gb": round(m["size"] / 1e9, 1), "loaded": m["name"] in loaded,
             "params": m.get("details", {}).get("parameter_size"),
             "quant": m.get("details", {}).get("quantization_level")} for m in tags]


def chat(messages: list[dict], *, model: str = "main", tools: list[dict] | None = None,
         reasoning: str | None = None, temperature: float = 0.2, json_mode: bool = False) -> dict:
    """单次对话，返回 {"message": ..., "usage": ...}。"""
    body: dict = {"model": model_name(model), "messages": messages, "temperature": temperature}
    if tools:
        body["tools"] = tools
    if reasoning or config().reasoning:
        body["reasoning_effort"] = reasoning or config().reasoning
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    data = _request("POST", "/chat/completions", body)
    return {"message": data["choices"][0]["message"], "usage": data.get("usage") or {}}


def _clip(text: str) -> str:
    return text if len(text) <= MAX_TOOL_CHARS else text[:MAX_TOOL_CHARS] + "…（已截断）"


def run_agent(messages: list[dict], *, schemas: list[dict], call: Callable[[str, dict], dict],
              model: str = "main", reasoning: str | None = None, max_steps: int = 8) -> dict:
    """工具调用循环：模型要工具就执行并回填，直到给出最终回答或超过轮数。"""
    messages = list(messages)
    steps: list[dict] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    started = time.time()
    reply = f"已达到最大轮数（{max_steps}），未能得出结论。"
    for _ in range(max_steps):
        resp = chat(messages, model=model, tools=schemas, reasoning=reasoning)
        for key in usage:
            usage[key] += resp["usage"].get(key, 0)
        msg = resp["message"]
        calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         **({"tool_calls": calls} if calls else {})})
        if not calls:
            reply = msg.get("content") or ""
            break
        for tc in calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            t0 = time.time()
            result = call(name, args)
            steps.append({"tool": name, "args": args, "ok": "error" not in result,
                          "ms": int((time.time() - t0) * 1000)})
            messages.append({"role": "tool", "tool_call_id": tc.get("id", name),
                             "content": _clip(json.dumps(result, ensure_ascii=False, default=str))})
    return {"reply": reply, "steps": steps, "usage": usage, "model": model_name(model),
            "elapsed_sec": round(time.time() - started, 2), "messages": messages}
