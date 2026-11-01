"""盯盘规则引擎：纯函数，输入盯盘标的 + 实时报价 / 市场快照，输出告警。级别只由规则决定，LLM 不参与定级。

告警：{rule, level, symbol, name, title, message, data}；level ∈ info < warn < alert。
同一 (rule, symbol) 每天只报一次，升级才再报（去重在 runner 里按库里当天记录做）。
"""
from __future__ import annotations

from signals import price_limit

LEVELS = {"info": 0, "warn": 1, "alert": 2}

INDEX_WARN, INDEX_ALERT, INDEX_UP = -2.0, -3.0, 2.0  # 指数涨跌幅阈值（%）
BREADTH_WARN = 0.8  # 下跌家数占比
LIMIT_DOWN_ALERT = 50  # 跌停家数
MOVE_WARN, MOVE_ALERT = 0.5, 0.8  # 个股涨跌幅达到涨跌停幅度的比例


def _alert(rule: str, level: str, item: dict, title: str, message: str, **data) -> dict:
    return {"rule": rule, "level": level, "symbol": item.get("symbol"), "name": item.get("name"),
            "title": title, "message": message, "data": data}


def _limit(item: dict) -> float:
    return 0.05 if "ST" in (item.get("name") or "").upper() else price_limit(item["symbol"])


def trigger_hit(trig: dict | None, price: float) -> bool:
    """按当前价收盘是否会触发策略信号（语义见 signals.trigger_prices）。"""
    if not trig:
        return False
    below, above = trig.get("below"), trig.get("above")
    if trig.get("fires_flat"):
        return not ((below is not None and price < below) or (above is not None and price > above))
    return (below is not None and price <= below) or (above is not None and price >= above)


def stock_alerts(item: dict, q: dict) -> list[dict]:
    """item：{symbol, name, kind: holding|watch, cost_price?, stop_loss_pct?, take_profit_pct?, strategy?, triggers?}"""
    out: list[dict] = []
    price, pre = q["price"], q["pre_close"]
    if not price or not pre:
        return out
    holding = item["kind"] == "holding"
    tag = "持仓" if holding else "自选"
    chg = (price / pre - 1) * 100
    limit = _limit(item)

    up_px, down_px = round(pre * (1 + limit) + 1e-9, 2), round(pre * (1 - limit) + 1e-9, 2)
    if price >= up_px - 0.005 or price <= down_px + 0.005:
        up = price >= up_px - 0.005
        out.append(_alert("limit_up" if up else "limit_down", "alert" if holding or not up else "warn", item,
                          f"{tag}{item['name']}{'涨停' if up else '跌停'}",
                          f"现价 {price}（{chg:+.2f}%）", price=price, change_pct=round(chg, 2)))
    elif abs(chg) >= limit * 100 * MOVE_WARN:
        level = "alert" if abs(chg) >= limit * 100 * MOVE_ALERT else "warn"
        out.append(_alert("move_up" if chg > 0 else "move_down", level, item,
                          f"{tag}{item['name']}{'大涨' if chg > 0 else '大跌'} {chg:+.2f}%",
                          f"现价 {price}，最高 {q['high']}，最低 {q['low']}", price=price, change_pct=round(chg, 2)))

    if holding and item.get("cost_price"):
        cost = item["cost_price"]
        pnl = (price / cost - 1) * 100
        if item.get("stop_loss_pct") and pnl <= -abs(item["stop_loss_pct"]):
            out.append(_alert("stop_loss", "alert", item, f"{item['name']}触及止损线",
                              f"浮亏 {pnl:.2f}%，止损线 -{abs(item['stop_loss_pct'])}%", pnl_pct=round(pnl, 2)))
        if item.get("take_profit_pct") and pnl >= item["take_profit_pct"]:
            out.append(_alert("take_profit", "warn", item, f"{item['name']}达到止盈线",
                              f"浮盈 {pnl:.2f}%，止盈线 {item['take_profit_pct']}%", pnl_pct=round(pnl, 2)))
        if pre >= cost > price:
            out.append(_alert("cost_break", "warn", item, f"{item['name']}跌破成本价",
                              f"现价 {price}，成本 {cost}", cost=cost))
        elif pre < cost <= price:
            out.append(_alert("cost_regain", "info", item, f"{item['name']}回到成本价上方",
                              f"现价 {price}，成本 {cost}", cost=cost))

    trig = item.get("triggers")
    if trigger_hit(trig, price):
        action = "买入" if trig["action"] == "BUY" else "卖出"
        level = "warn" if holding or trig["action"] == "BUY" else "info"
        bound = " / ".join(f"{k} {v}" for k, v in (("≤", trig.get("below")), ("≥", trig.get("above"))) if v is not None)
        out.append(_alert("signal", level, item, f"{tag}{item['name']}将触发{action}信号",
                          f"按现价 {price} 收盘，{item.get('strategy') or '策略'}会发出{action}信号（触发价 {bound}）",
                          action=trig["action"], strategy=item.get("strategy"), triggers=trig))
    return out


def market_alerts(market: dict) -> list[dict]:
    out: list[dict] = []
    for idx in market.get("indexes") or []:
        chg = idx.get("change_pct")
        if chg is None:
            continue
        item = {"symbol": idx["code"], "name": idx["name"]}
        if chg <= INDEX_WARN:
            out.append(_alert("index_drop", "alert" if chg <= INDEX_ALERT else "warn", item,
                              f"{idx['name']}下跌 {chg:+.2f}%", f"现报 {idx['price']:.2f}", change_pct=chg))
        elif chg >= INDEX_UP:
            out.append(_alert("index_rise", "info", item, f"{idx['name']}上涨 {chg:+.2f}%",
                              f"现报 {idx['price']:.2f}", change_pct=chg))
    b = market.get("breadth")
    if b:
        mkt = {"symbol": None, "name": "全市场"}
        if b.get("down_ratio") is not None and b["down_ratio"] >= BREADTH_WARN:
            out.append(_alert("breadth_down", "warn", mkt, "市场普跌",
                              f"下跌 {b['down']} 家 / 上涨 {b['up']} 家，跌停 {b['limit_down']} 家", **b))
        if b.get("limit_down", 0) >= LIMIT_DOWN_ALERT:
            out.append(_alert("limit_down_wave", "alert", mkt, f"跌停潮：{b['limit_down']} 家跌停",
                              f"涨停 {b['limit_up']} 家，跌超 5% 的 {b['down_over_5pct']} 家", **b))
    return out
