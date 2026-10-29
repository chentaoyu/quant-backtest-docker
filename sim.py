"""模拟仓（纸上交易）：只从创建当天往后跑，结果由"配置 + 行情"重放得出，不存成交。

- 策略跟单（slot）：给某只股票分配一笔资金，冻结创建时的策略和参数；
  每日收盘出信号，次日开盘成交。停止跟单后次日开盘清仓，资金回到账户可用现金。
- 手动单（order）：下单后下一交易日开盘成交；先卖后买，可卖股数遵守 T+1。
- A 股规则：买入 100 股整数倍；佣金（有最低额）+ 卖出印花税；开盘涨停买不进、跌停卖不出，顺延。
"""
from __future__ import annotations

import json
import math
import threading
import uuid
from datetime import date, datetime

import pandas as pd

from advisor import load_checkups, resolve_strategy
from data_loader import CACHE_DIR, load_daily, load_index
from holdings import _names, normalize_symbol
from signals import latest_signal, price_limit
from strategies import STRATEGIES

SIM_FILE = CACHE_DIR / "sim_accounts.json"
DEFAULT_FEES = {"commission": 0.00025, "min_commission": 5.0, "stamp_tax": 0.0005}
WARMUP_YEARS = 3
LOT = 100
_LOCK = threading.Lock()


class SimError(ValueError):
    """模拟仓操作不合法。"""


# ---------------------------------------------------------------- 存储
def _read() -> list[dict]:
    try:
        return json.loads(SIM_FILE.read_text(encoding="utf-8")).get("accounts", [])
    except (OSError, ValueError):
        return []


def _write(accounts: list[dict]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    tmp = SIM_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"accounts": accounts}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SIM_FILE)


def _today() -> str:
    return date.today().isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _mutate(account_id: str, change) -> dict:
    with _LOCK:
        accounts = _read()
        account = next((a for a in accounts if a["id"] == account_id), None)
        if account is None:
            raise SimError("模拟账户不存在")
        result = change(account)
        _write(accounts)
        return result


def list_accounts() -> list[dict]:
    with _LOCK:
        return _read()


def create_account(name: str, initial_cash: float, fees: dict | None = None) -> dict:
    if not 1e4 <= initial_cash <= 1e9:
        raise SimError("初始资金应在 1 万到 10 亿之间")
    account = {
        "id": _new_id(),
        "name": (name or "模拟账户").strip()[:30],
        "initial_cash": float(initial_cash),
        "created_date": _today(),
        "fees": {**DEFAULT_FEES, **(fees or {})},
        "slots": [],
        "orders": [],
    }
    with _LOCK:
        accounts = _read()
        accounts.append(account)
        _write(accounts)
    return account


def delete_account(account_id: str) -> None:
    with _LOCK:
        accounts = _read()
        rest = [a for a in accounts if a["id"] != account_id]
        if len(rest) == len(accounts):
            raise SimError("模拟账户不存在")
        _write(rest)


def add_slot(account_id: str, symbol: str, cash: float, strategy: str | None = None,
             params: dict | None = None, entry_on_start: bool = False) -> dict:
    symbol = normalize_symbol(symbol)
    check = load_checkups().get(symbol)
    name, params, _ = resolve_strategy(strategy, params, check)
    if not name:
        raise SimError(f"{symbol} 没有可用策略：先做策略体检，或手动指定策略")
    if cash < 1000:
        raise SimError("分配资金至少 1000 元")
    free = account_state(account_id)["summary"]["cash"]
    if cash > free + 1e-6:
        raise SimError(f"可用现金只有 {free:.2f}，不足以分配 {cash:.2f}")

    def change(account):
        if any(s["symbol"] == symbol and not s.get("end_date") for s in account["slots"]):
            raise SimError(f"{symbol} 已在这个账户里跟单")
        slot = {"id": _new_id(), "symbol": symbol, "name": _names().get(symbol, symbol), "strategy": name,
                "params": params, "cash": float(cash), "start_date": _today(), "end_date": None,
                "entry_on_start": bool(entry_on_start)}
        account["slots"].append(slot)
        return slot

    return _mutate(account_id, change)


def stop_slot(account_id: str, slot_id: str) -> None:
    def change(account):
        slot = next((s for s in account["slots"] if s["id"] == slot_id), None)
        if slot is None:
            raise SimError("跟单不存在")
        if slot["start_date"] == _today():
            account["slots"].remove(slot)  # 当天建当天撤：还没有任何成交，直接删除
        elif not slot.get("end_date"):
            slot["end_date"] = _today()

    _mutate(account_id, change)


def place_order(account_id: str, symbol: str, side: str, shares: int) -> dict:
    symbol = normalize_symbol(symbol)
    if side not in ("BUY", "SELL"):
        raise SimError("方向只能是 BUY 或 SELL")
    if shares <= 0 or (side == "BUY" and shares % LOT):
        raise SimError("买入股数需为 100 的整数倍")

    def change(account):
        order = {"id": _new_id(), "symbol": symbol, "name": _names().get(symbol, symbol), "side": side,
                 "shares": int(shares), "placed_date": _today(), "placed_at": datetime.now().isoformat(timespec="seconds"),
                 "cancelled": False}
        account["orders"].append(order)
        return order

    return _mutate(account_id, change)


def cancel_order(account_id: str, order_id: str) -> None:
    state = account_state(account_id)
    order = next((o for o in state["orders"] if o["id"] == order_id), None)
    if order is None:
        raise SimError("订单不存在")
    if order["status"] != "pending":
        raise SimError("订单已成交或已失败，不能撤销")

    def change(account):
        next(o for o in account["orders"] if o["id"] == order_id)["cancelled"] = True

    _mutate(account_id, change)


# ---------------------------------------------------------------- 规则
def _fee(fees: dict, amount: float, side: str) -> float:
    fee = max(amount * fees["commission"], fees["min_commission"])
    if side == "SELL":
        fee += amount * fees["stamp_tax"]
    return round(fee, 2)


def _limit_hit(symbol: str, open_: float, prev_close: float, side: str) -> bool:
    """开盘即涨停（买不进）/ 跌停（卖不出）。"""
    limit = price_limit(symbol)
    if side == "BUY":
        return open_ >= round(prev_close * (1 + limit), 2) - 0.005
    return open_ <= round(prev_close * (1 - limit), 2) + 0.005


def _max_lots(cash: float, price: float, fees: dict) -> int:
    shares = math.floor(cash / (price * (1 + fees["commission"])) / LOT) * LOT
    while shares > 0 and shares * price + _fee(fees, shares * price, "BUY") > cash:
        shares -= LOT
    return shares


# ---------------------------------------------------------------- 重放
def _load(symbol: str, since: str, warmup_years: int = WARMUP_YEARS) -> pd.DataFrame:
    # 多留半个月：保证第一笔成交前总有"前收盘价"可用于涨跌停判断
    start = (pd.Timestamp(since) - pd.DateOffset(years=warmup_years) - pd.Timedelta(days=15)).strftime("%Y%m%d")
    return load_daily(symbol, start=start)


def replay_slot(slot: dict, df: pd.DataFrame, fees: dict) -> dict:
    """按策略信号重放一只股票的跟单，返回成交、逐日权益、当前持仓和明日挂单。"""
    symbol = slot["symbol"]
    start = pd.Timestamp(slot["start_date"])
    end = pd.Timestamp(slot["end_date"]) if slot.get("end_date") else None
    sig = latest_signal(df, STRATEGIES[slot["strategy"]], slot["params"])

    # 想要持有的区间 [买入成交日, 卖出成交日)；跨越起点的那笔只在 entry_on_start 时跟
    windows = []
    for t in sig["trades"]:
        entry = pd.Timestamp(t["entry_date"])
        exit_ = pd.Timestamp(t["exit_date"]) if t["exit_date"] else None
        if entry > start:
            windows.append((entry, exit_))
        elif slot.get("entry_on_start") and (exit_ is None or exit_ > start):
            windows.append((start + pd.Timedelta(days=1), exit_))

    def desired(day: pd.Timestamp) -> bool:
        if end is not None and day > end:
            return False
        return any(a <= day and (b is None or day < b) for a, b in windows)

    cash, shares, cost, bought_on = slot["cash"], 0, 0.0, None
    trades, notes, equity = [], [], {}
    closes = df["Close"]
    for i in range(1, len(df)):
        day = df.index[i]
        if day <= start:
            continue
        bar, prev = df.iloc[i], closes.iloc[i - 1]
        want = desired(day)
        if want and not shares:
            if _limit_hit(symbol, bar.Open, prev, "BUY"):
                notes.append({"date": day.date().isoformat(), "note": "开盘涨停，买入顺延"})
            else:
                qty = _max_lots(cash, bar.Open, fees)
                if qty:
                    amount = qty * bar.Open
                    fee = _fee(fees, amount, "BUY")
                    cash -= amount + fee
                    shares, cost, bought_on = qty, (amount + fee) / qty, day
                    trades.append({"date": day.date().isoformat(), "side": "BUY", "price": round(bar.Open, 3),
                                   "shares": qty, "fee": fee, "pnl": None})
                else:
                    notes.append({"date": day.date().isoformat(), "note": "资金不足一手，未买入"})
        elif not want and shares and day > bought_on:
            if _limit_hit(symbol, bar.Open, prev, "SELL"):
                notes.append({"date": day.date().isoformat(), "note": "开盘跌停，卖出顺延"})
            else:
                amount = shares * bar.Open
                fee = _fee(fees, amount, "SELL")
                cash += amount - fee
                trades.append({"date": day.date().isoformat(), "side": "SELL", "price": round(bar.Open, 3),
                               "shares": shares, "fee": fee, "pnl": round(amount - fee - shares * cost, 2),
                               "return_pct": round((bar.Open * (1 - fees["commission"] - fees["stamp_tax"]) / cost - 1) * 100, 2)})
                shares, cost = 0, 0.0
        equity[day.date().isoformat()] = round(cash + shares * bar.Close, 2)

    stopped = end is not None
    # 停止后资金归还日：有清仓卖出就是卖出日，否则是停止后的第一个交易日
    released = None
    if stopped and not shares:
        sells = [t["date"] for t in trades if t["side"] == "SELL" and t["date"] > slot["end_date"]]
        after = [d for d in df.index if d > end]
        released = sells[-1] if sells else (after[0].date().isoformat() if after else None)
    pending = None
    if not stopped and sig["action"]:
        pending = sig["action"]
    elif shares and stopped:
        pending = "SELL"  # 停止跟单后等待清仓
    last_close = float(closes.iloc[-1])
    return {
        **slot,
        "label": STRATEGIES[slot["strategy"]].label,
        "status": "stopped" if released else ("stopping" if stopped else "active"),
        "hold": sig["hold"],
        "shares": shares,
        "cost": round(cost, 3) if shares else None,
        "close": round(last_close, 3),
        "cash_left": round(cash, 2),
        "market_value": round(shares * last_close, 2),
        "equity": equity,
        "value": round(cash + shares * last_close, 2),
        "trades": trades,
        "notes": notes,
        "pending": pending,
        "liquidated_on": released,
    }


def replay_orders(orders: list[dict], bars: dict[str, pd.DataFrame], fees: dict, ledger: dict[str, float],
                  initial_cash: float, days: list[str]) -> dict:
    """手动单重放。ledger：日期 → 跟单占用/归还资金带来的现金变化（占用为负）。"""
    cash = initial_cash
    holdings: dict[str, dict] = {}  # symbol -> {shares, cost, lots: [(date, shares)]}
    status = {o["id"]: {"status": "cancelled" if o["cancelled"] else "pending", "fill": None, "reason": None} for o in orders}
    trades, equity = [], {}
    ordered = sorted(orders, key=lambda o: (o["placed_at"], o["side"] != "SELL"))
    for day in days:
        cash += ledger.get(day, 0.0)
        todays = [o for o in ordered if status[o["id"]]["status"] == "pending" and o["placed_date"] < day]
        for o in sorted(todays, key=lambda o: o["side"] != "SELL"):  # 先卖后买
            df = bars.get(o["symbol"])
            ts = pd.Timestamp(day)
            if df is None or ts not in df.index:
                continue  # 停牌：继续挂单
            i = df.index.get_loc(ts)
            bar, prev = df.iloc[i], df["Close"].iloc[i - 1]
            if _limit_hit(o["symbol"], bar.Open, prev, o["side"]):
                status[o["id"]]["reason"] = f"{day} 开盘{'涨停' if o['side'] == 'BUY' else '跌停'}，顺延"
                continue
            pos = holdings.setdefault(o["symbol"], {"shares": 0, "cost": 0.0, "lots": []})
            amount = o["shares"] * bar.Open
            fee = _fee(fees, amount, o["side"])
            if o["side"] == "BUY":
                if amount + fee > cash:
                    status[o["id"]].update(status="failed", reason=f"{day} 可用现金不足")
                    continue
                cash -= amount + fee
                pos["cost"] = (pos["cost"] * pos["shares"] + amount + fee) / (pos["shares"] + o["shares"])
                pos["shares"] += o["shares"]
                pos["lots"].append((day, o["shares"]))
                pnl = None
            else:
                sellable = sum(n for d, n in pos["lots"] if d < day)  # T+1
                if o["shares"] > sellable:
                    status[o["id"]].update(status="failed", reason=f"{day} 可卖股数 {sellable} 不足（T+1）")
                    continue
                cash += amount - fee
                pnl = round(amount - fee - o["shares"] * pos["cost"], 2)
                pos["shares"] -= o["shares"]
                left = o["shares"]
                for k, (d, n) in enumerate(pos["lots"]):
                    take = min(n, left)
                    pos["lots"][k] = (d, n - take)
                    left -= take
                pos["lots"] = [(d, n) for d, n in pos["lots"] if n]
            status[o["id"]].update(status="filled", fill={"date": day, "price": round(bar.Open, 3), "fee": fee})
            trades.append({"date": day, "symbol": o["symbol"], "name": o["name"], "side": o["side"],
                           "price": round(bar.Open, 3), "shares": o["shares"], "fee": fee, "pnl": pnl, "source": "manual"})
        value = 0.0
        for symbol, pos in holdings.items():
            df = bars.get(symbol)
            if pos["shares"] and df is not None:
                value += pos["shares"] * float(df["Close"].loc[: pd.Timestamp(day)].iloc[-1])
        equity[day] = round(cash + value, 2)
    return {"cash": round(cash, 2), "holdings": holdings, "status": status, "trades": trades, "equity": equity}


def _max_dd(values: list[float]) -> float | None:
    peak, worst = None, 0.0
    for v in values:
        peak = v if peak is None else max(peak, v)
        worst = min(worst, v / peak - 1)
    return round(worst * 100, 2) if values else None


def _benchmark(days: list[str]) -> dict | None:
    if len(days) < 1:
        return None
    try:
        index = load_index("000300")
    except Exception:  # noqa: BLE001 - 基准拿不到不影响模拟仓
        return None
    closes = index["Close"]
    base_rows = closes.loc[: pd.Timestamp(days[0]) - pd.Timedelta(days=1)]
    if base_rows.empty:
        return None
    base = float(base_rows.iloc[-1])
    series = {d: round(float(closes.loc[: pd.Timestamp(d)].iloc[-1]) / base, 4) for d in days}
    return {"name": "沪深300", "series": series, "return_pct": round((series[days[-1]] - 1) * 100, 2)}


def account_state(account_id: str) -> dict:
    account = next((a for a in list_accounts() if a["id"] == account_id), None)
    if account is None:
        raise SimError("模拟账户不存在")
    fees = account["fees"]
    checkups = load_checkups()

    slots, bars = [], {}
    for slot in account["slots"]:
        try:
            df = bars.get(slot["symbol"])
            if df is None:
                df = bars[slot["symbol"]] = _load(slot["symbol"], slot["start_date"])
            slots.append(replay_slot(slot, df, fees))
        except Exception as exc:  # noqa: BLE001 - 单只取数失败不影响账户其他部分
            slots.append({**slot, "error": str(exc), "value": slot["cash"], "equity": {}, "trades": [],
                          "shares": 0, "market_value": 0.0, "status": "error", "pending": None, "notes": []})
    for o in account["orders"]:
        if o["symbol"] not in bars:
            bars[o["symbol"]] = _load(o["symbol"], o["placed_date"], warmup_years=0)

    # 交易日：账户创建之后，所有相关股票出现过的日期
    created = pd.Timestamp(account["created_date"])
    days = sorted({d.date().isoformat() for df in bars.values() for d in df.index if d > created})

    # 跟单占用 / 归还资金：创建当天占用，清仓当天归还
    ledger: dict[str, float] = {}
    first_day = lambda after: next((d for d in days if d > after), None)  # noqa: E731
    for s in slots:
        key = first_day(s["start_date"]) or "9999-12-31"
        ledger[key] = ledger.get(key, 0.0) - s["cash"]
        if s.get("liquidated_on"):
            ledger[s["liquidated_on"]] = ledger.get(s["liquidated_on"], 0.0) + s["cash_left"]
    manual = replay_orders(account["orders"], bars, fees, ledger, account["initial_cash"], days)
    # 尚未进入交易日的占用（今天刚建的跟单）也要从可用现金里扣掉
    free_cash = manual["cash"] + ledger.get("9999-12-31", 0.0)

    total = []
    for day in days:
        slot_value = sum(
            s["equity"].get(day, s["cash"]) if not s.get("liquidated_on") or day < s["liquidated_on"] else 0.0
            for s in slots
            if day > s["start_date"]
        )
        total.append(manual["equity"].get(day, account["initial_cash"]) + slot_value)

    positions = []
    for s in slots:
        if s.get("shares"):
            positions.append({"symbol": s["symbol"], "name": s["name"], "source": "strategy", "strategy": s["label"],
                              "shares": s["shares"], "cost": s["cost"], "close": s["close"],
                              "market_value": s["market_value"], "pnl": round(s["market_value"] - s["shares"] * s["cost"], 2)})
    for symbol, pos in manual["holdings"].items():
        if pos["shares"]:
            close = float(bars[symbol]["Close"].iloc[-1])
            positions.append({"symbol": symbol, "name": _names().get(symbol, symbol), "source": "manual", "strategy": None,
                              "shares": pos["shares"], "cost": round(pos["cost"], 3), "close": round(close, 3),
                              "market_value": round(pos["shares"] * close, 2),
                              "pnl": round(pos["shares"] * (close - pos["cost"]), 2)})

    trades = manual["trades"] + [
        {**t, "symbol": s["symbol"], "name": s["name"], "source": "strategy", "strategy": s["label"]}
        for s in slots for t in s["trades"]
    ]
    trades.sort(key=lambda t: t["date"], reverse=True)
    orders = [{**o, **manual["status"][o["id"]]} for o in account["orders"]]

    equity = total[-1] if total else account["initial_cash"]
    market_value = sum(p["market_value"] for p in positions)
    return {
        "account": {k: account[k] for k in ("id", "name", "initial_cash", "created_date", "fees")},
        "summary": {
            "equity": round(equity, 2),
            "cash": round(free_cash, 2),
            "slot_cash": round(sum(s.get("cash_left", 0.0) for s in slots if s.get("status") in ("active", "stopping")), 2),
            "market_value": round(market_value, 2),
            "pnl": round(equity - account["initial_cash"], 2),
            "pnl_pct": round((equity / account["initial_cash"] - 1) * 100, 2),
            "day_pnl": round(total[-1] - total[-2], 2) if len(total) > 1 else 0.0,
            "max_dd_pct": _max_dd(total),
            "days": len(days),
            "data_date": days[-1] if days else None,
        },
        "curve": [{"date": d, "equity": round(v, 2)} for d, v in zip(days, total)],
        "benchmark": _benchmark(days),
        "slots": [{k: v for k, v in s.items() if k != "equity"} for s in slots],
        "positions": positions,
        "orders": orders,
        "trades": trades,
        "scorecard": scorecard(slots, checkups),
    }


def scorecard(slots: list[dict], checkups: dict) -> list[dict]:
    """按策略统计模拟仓里已平仓的跟单交易，并和体检时的样本外夏普对照。"""
    groups: dict[str, dict] = {}
    for s in slots:
        g = groups.setdefault(s["strategy"], {"strategy": s["strategy"], "label": STRATEGIES[s["strategy"]].label,
                                              "slots": 0, "returns": [], "pnl": 0.0, "sharpes": []})
        g["slots"] += 1
        sharpe = ((checkups.get(s["symbol"]) or {}).get("strategies", {}).get(s["strategy"]) or {}).get("oos_sharpe")
        if sharpe is not None:
            g["sharpes"].append(sharpe)
        for t in s.get("trades", []):
            if t["side"] == "SELL":
                g["returns"].append(t["return_pct"])
                g["pnl"] += t["pnl"]
    result = []
    for g in groups.values():
        r = g["returns"]
        wins = [x for x in r if x > 0]
        losses = [x for x in r if x <= 0]
        result.append({
            "strategy": g["strategy"],
            "label": g["label"],
            "slots": g["slots"],
            "closed_trades": len(r),
            "win_rate_pct": round(len(wins) / len(r) * 100, 1) if r else None,
            "avg_return_pct": round(sum(r) / len(r), 2) if r else None,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if wins and losses and sum(losses) < 0 else None,
            "pnl": round(g["pnl"], 2),
            "checkup_sharpe": round(sum(g["sharpes"]) / len(g["sharpes"]), 2) if g["sharpes"] else None,
        })
    return sorted(result, key=lambda x: x["pnl"], reverse=True)


def active_slots_by_symbol() -> dict[str, list[dict]]:
    """自选股页用：每只股票在哪些账户里跟单。"""
    result: dict[str, list[dict]] = {}
    for a in list_accounts():
        for s in a["slots"]:
            if not s.get("end_date"):
                result.setdefault(s["symbol"], []).append({"account_id": a["id"], "account": a["name"], "slot_id": s["id"]})
    return result

