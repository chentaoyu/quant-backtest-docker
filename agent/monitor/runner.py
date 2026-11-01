"""盯盘调度：交易时段每 interval 秒跑一轮 规则 → 去重 → （大模型写一句解读）→ 入库。配置见 agent.settings。"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

from agent import llm, settings, tools
from agent.monitor import market, rules, store

log = logging.getLogger("agent.monitor")

WATCH_TTL = 900  # 持仓/自选清单与触发价 15 分钟刷新一次（触发价基于昨收，盘中不变）

NOTE_PROMPT = """你是 A 股盘中盯盘助手。根据告警、个股行业和市场快照，用一句话（不超过 50 字）点出这条告警值得注意的原因或应对思路。
不要重复告警里的数字；只能依据给出的数据，不要推断策略或指标状态，信息不足就说明需要关注什么。"""


class Monitor:
    def __init__(self):
        self.watch: list[dict] = []
        self.watch_at = 0.0
        self.market: dict | None = None
        self.status = {"last_tick": None, "last_error": None, "last_new": 0, "ticks": 0}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # ---------------------------------------------------------------- 盯盘清单
    def _refresh_watch(self) -> None:
        if self.watch and time.time() - self.watch_at < WATCH_TTL:
            return
        items: dict[str, dict] = {}
        for r in tools._web("GET", "/api/watchlist")["rows"]:
            sig, used = r.get("signal") or {}, r.get("used") or {}
            items[r["symbol"]] = {"symbol": r["symbol"], "name": r.get("name") or r["symbol"], "kind": "watch",
                                  "strategy": used.get("name"), "triggers": sig.get("triggers")}
        for r in tools._web("GET", "/api/holdings/analysis")["rows"]:  # 持仓覆盖同名自选
            main = r.get("main") or {}
            items[r["symbol"]] = {**{k: r.get(k) for k in ("symbol", "cost_price", "stop_loss_pct", "take_profit_pct")},
                                  "name": r.get("name") or r["symbol"], "kind": "holding",
                                  "strategy": main.get("name"), "triggers": main.get("triggers")}
        industries = tools._industries()
        for item in items.values():
            item["industry"] = industries.get(item["symbol"])
        self.watch, self.watch_at = list(items.values()), time.time()

    # ---------------------------------------------------------------- 一轮
    def tick(self) -> list[dict]:
        with self._lock:  # 定时线程和手动触发不并发
            now = datetime.now()
            cfg = settings.get().monitor
            thresholds = cfg.model_dump(include=set(rules.DEFAULTS))
            self._refresh_watch()
            self.market = market.live_market()
            quotes = market.live_quotes([w["symbol"] for w in self.watch]) if self.watch else {}

            alerts = rules.market_alerts(self.market, thresholds)
            for item in self.watch:
                if item["symbol"] in quotes:
                    alerts += rules.stock_alerts(item, quotes[item["symbol"]], thresholds)
            alerts = [a for a in alerts if a["rule"] not in cfg.disabled_rules]

            day = now.strftime("%Y-%m-%d")
            seen = store.fired(day)
            new = [a for a in alerts if rules.LEVELS[a["level"]] > seen.get((a["rule"], a["symbol"]), -1)]
            for a in new:
                if cfg.llm_note and a["symbol"] and a["level"] != "info" and a["symbol"] in quotes:
                    a["note"] = self._note(a, cfg.note_model)
            store.add(now.isoformat(timespec="seconds"), day, new)
            self.status.update(last_tick=now.isoformat(timespec="seconds"), last_error=None, last_new=len(new),
                               ticks=self.status["ticks"] + 1)
            return new

    def _note(self, alert: dict, model: str) -> str | None:
        item = next((w for w in self.watch if w["symbol"] == alert["symbol"]), {})
        m = self.market or {}
        context = {
            "alert": {k: alert[k] for k in ("level", "title", "message")},
            "stock": {k: item.get(k) for k in ("kind", "industry", "strategy")},
            "indexes": [{"name": i["name"], "change_pct": i["change_pct"]} for i in m.get("indexes") or []],
            "breadth": m.get("breadth"),
            "sectors": m.get("sectors"),
        }
        try:
            resp = llm.chat([{"role": "system", "content": NOTE_PROMPT},
                             {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
                            model=model, reasoning="none", temperature=0.3)
            return (resp["message"].get("content") or "").strip()[:120] or None
        except llm.LLMError as exc:
            log.warning("告警解读失败：%s", exc)
            return None

    # ---------------------------------------------------------------- 后台线程
    def start(self) -> None:
        threading.Thread(target=self._loop, name="monitor", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # 每轮重新读配置：页面改开关/间隔无需重启
        while not self._stop.wait(settings.get().monitor.interval):
            if not settings.get().monitor.enabled or not market.is_trading_time():
                continue
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - 单轮失败下一轮再试
                log.exception("盯盘失败")
                self.status["last_error"] = f"{datetime.now():%H:%M:%S} {exc}"

    def info(self) -> dict:
        cfg = settings.get().monitor
        return {**self.status, "enabled": cfg.enabled, "interval": cfg.interval,
                "trading": market.is_trading_time(), "watch_count": len(self.watch),
                "holdings": sum(w["kind"] == "holding" for w in self.watch)}


monitor = Monitor()


def sse_stream(last_id: int | None = None, poll: float = 2.0, ping: float = 15.0):
    """SSE：轮询库里新告警推给前端；定期发注释行保活并探测断开。"""
    last = store.max_id() if last_id is None else last_id
    yield "retry: 5000\n\n"
    idle = 0.0
    while True:
        rows = store.recent(limit=50, since_id=last)
        for row in reversed(rows):
            last = row["id"]
            yield f"id: {row['id']}\nevent: alert\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
        time.sleep(poll)
        idle += poll
        if idle >= ping:
            idle = 0.0
            yield ": ping\n\n"
