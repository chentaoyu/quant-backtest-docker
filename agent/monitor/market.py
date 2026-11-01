"""盘中行情：持仓/自选实时价（Tushare）+ 全市场快照（指数、涨跌分布、行业板块）。"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import date, datetime, time as dtime

from data_loader import to_ts_code

INDEXES = {"000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指", "000300.SH": "沪深300"}
SESSIONS = ((dtime(9, 30), dtime(11, 30)), (dtime(13, 0), dtime(15, 0)))
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 国内行情源直连
_trade_days: dict[date, bool] = {}


def _get(url: str, referer: str, encoding: str = "utf-8") -> str:
    req = urllib.request.Request(url, headers={**_UA, "Referer": referer})
    with _opener.open(req, timeout=10) as resp:
        return resp.read().decode(encoding, errors="replace")


def _ts():
    import tushare as ts

    return ts


def is_trade_day(day: date) -> bool:
    if day not in _trade_days:
        try:
            ts = _ts()
            cal = ts.pro_api(os.environ["TUSHARE_TOKEN"]).trade_cal(
                exchange="SSE", start_date=day.strftime("%Y%m%d"), end_date=day.strftime("%Y%m%d"))
            _trade_days[day] = bool(len(cal)) and str(cal.iloc[0]["is_open"]) == "1"
        except Exception:  # noqa: BLE001 - 取不到交易日历就按工作日估计
            return day.weekday() < 5
    return _trade_days[day]


def is_trading_time(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return any(a <= now.time() <= b for a, b in SESSIONS) and is_trade_day(now.date())


def _quote_row(r: dict) -> dict:
    pre = float(r["PRE_CLOSE"] or 0)
    price = float(r["PRICE"] or 0)
    return {"name": r["NAME"], "price": price, "pre_close": pre, "open": float(r["OPEN"] or 0),
            "high": float(r["HIGH"] or 0), "low": float(r["LOW"] or 0), "amount": float(r["AMOUNT"] or 0),
            "change_pct": round((price / pre - 1) * 100, 2) if pre and price else None,
            "time": f"{r['DATE']} {r['TIME']}"}


def live_quotes(symbols: list[str]) -> dict[str, dict]:
    """个股实时报价：{symbol: quote}。停牌/无成交（price=0）的不返回。"""
    ts = _ts()
    out = {}
    for i in range(0, len(symbols), 50):
        df = ts.realtime_quote(ts_code=",".join(to_ts_code(s) for s in symbols[i:i + 50]))
        for r in df.to_dict("records"):
            q = _quote_row(r)
            if q["price"] > 0:
                out[r["TS_CODE"].split(".")[0]] = q
    return out


def live_indexes() -> list[dict]:
    # 注意：Tushare 把上证指数的 TS_CODE 返回成 000001.SZ（与平安银行冲突），只能按请求顺序对应
    df = _ts().realtime_quote(ts_code=",".join(INDEXES))
    rows = df.to_dict("records")
    if len(rows) != len(INDEXES):
        raise RuntimeError("指数行情返回条数不符")
    return [{"code": code, **_quote_row(r), "name": name} for (code, name), r in zip(INDEXES.items(), rows)]


def live_breadth() -> dict:
    """东财涨跌分布：键为涨跌幅区间（±11 为涨跌停，0 为平盘）。"""
    text = _get("https://push2ex.eastmoney.com/getTopicZDFenBu?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt",
                "https://quote.eastmoney.com/")
    data = json.loads(text)["data"]
    dist = {int(k): v for item in data["fenbu"] for k, v in item.items()}
    up = sum(v for k, v in dist.items() if k > 0)
    down = sum(v for k, v in dist.items() if k < 0)
    return {"date": str(data["qdate"]), "up": up, "down": down, "flat": dist.get(0, 0),
            "limit_up": dist.get(11, 0), "limit_down": dist.get(-11, 0),
            "up_over_5pct": sum(v for k, v in dist.items() if 5 <= k <= 11),
            "down_over_5pct": sum(v for k, v in dist.items() if -11 <= k <= -5),
            "down_ratio": round(down / (up + down), 3) if up + down else None}


def live_sectors(top: int = 5) -> dict:
    """新浪行业板块涨跌：领涨/领跌前 N。"""
    text = _get("https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php", "https://finance.sina.com.cn", "gbk")
    raw = json.loads(re.search(r"=\s*(\{.*\})", text, re.S).group(1))
    rows = []
    for value in raw.values():
        f = value.split(",")
        rows.append({"name": f[1], "count": int(f[2]), "change_pct": round(float(f[5]), 2),
                     "leader": f[12], "leader_change_pct": round(float(f[9]), 2)})
    rows.sort(key=lambda r: r["change_pct"], reverse=True)
    return {"top": rows[:top], "bottom": rows[::-1][:top]}


def live_market() -> dict:
    """全市场快照；单个数据源失败不影响其他部分。"""
    out: dict = {"at": datetime.now().isoformat(timespec="seconds"), "errors": {}}
    for key, fn in (("indexes", live_indexes), ("breadth", live_breadth), ("sectors", live_sectors)):
        try:
            out[key] = fn()
        except Exception as exc:  # noqa: BLE001
            out[key] = None
            out["errors"][key] = str(exc)[:200]
    return out
