#!/usr/bin/env python3
"""
币安每日涨幅榜/跌幅榜采集脚本
支持现货（api.binance.com）和合约永续（fapi.binance.com）
由 GitHub Actions 定时触发运行
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

API_BASE  = "https://api.binance.com"
FAPI_BASE = "https://fapi.binance.com"
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "history.json")

TOP_N  = int(os.environ.get("TOP_N", "5"))
QUOTE  = os.environ.get("QUOTE", "USDT")
MARKET = os.environ.get("MARKET", "spot")   # 'spot' | 'futures'

BEIJING_TZ = timezone(timedelta(hours=8))


def fetch_json(url, timeout=15):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_valid_symbols(quote):
    """获取所有正常交易中的指定计价货币交易对"""
    if MARKET == "futures":
        data = fetch_json(f"{FAPI_BASE}/fapi/v1/exchangeInfo")
        return {
            s["symbol"]
            for s in data["symbols"]
            if s["quoteAsset"] == quote
            and s["status"] == "TRADING"
            and s.get("contractType") == "PERPETUAL"
        }
    else:
        data = fetch_json(f"{API_BASE}/api/v3/exchangeInfo")
        return {
            s["symbol"]
            for s in data["symbols"]
            if s["quoteAsset"] == quote
            and s["status"] == "TRADING"
            and s.get("isSpotTradingAllowed", False)
        }


def get_top_gainers_losers(valid_symbols, top_n):
    """获取24h涨幅榜前N名和跌幅榜前N名"""
    if MARKET == "futures":
        tickers = fetch_json(f"{FAPI_BASE}/fapi/v1/ticker/24hr")
    else:
        tickers = fetch_json(f"{API_BASE}/api/v3/ticker/24hr")

    filtered = [t for t in tickers if t["symbol"] in valid_symbols]
    sorted_tickers = sorted(
        filtered, key=lambda t: float(t["priceChangePercent"]), reverse=True
    )
    gainers = sorted_tickers[:top_n]
    losers  = list(reversed(sorted_tickers[-top_n:]))
    return gainers, losers


def load_history():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_history(history):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def today_str():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")


def now_time_str():
    return datetime.now(BEIJING_TZ).strftime("%H:%M:%S")


def main():
    market_label = "合约(永续)" if MARKET == "futures" else "现货"
    print(f"[{now_time_str()}] 开始采集 {market_label} TOP{TOP_N} {QUOTE} 涨幅/跌幅榜...")

    try:
        valid_symbols = get_valid_symbols(QUOTE)
        print(f"  有效交易对数量: {len(valid_symbols)}")

        gainers, losers = get_top_gainers_losers(valid_symbols, TOP_N)
        print(f"  涨幅榜 TOP{TOP_N}: {[t['symbol'] for t in gainers]}")
        print(f"  跌幅榜 TOP{TOP_N}: {[t['symbol'] for t in losers]}")
    except URLError as e:
        print(f"  错误：无法连接API: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"  错误：采集失败: {e}", file=sys.stderr)
        sys.exit(1)

    history = load_history()
    today = today_str()

    if today not in history:
        history[today] = []

    # 按 symbol+type 去重：同一币种当天可以同时记录在涨幅榜和跌幅榜（冲高回落场景）
    existing_keys = {
        f"{c['symbol']}|{'loser' if c.get('type') == 'loser' else 'gainer'}"
        for c in history[today]
    }
    new_count = 0

    # 追加涨幅榜
    for idx, t in enumerate(gainers):
        symbol = t["symbol"]
        if f"{symbol}|gainer" in existing_keys:
            continue
        history[today].append({
            "symbol": symbol,
            "pct": round(float(t["priceChangePercent"]), 2),
            "price": float(t["lastPrice"]),
            "firstSeen": now_time_str(),
            "rank": idx + 1,
            "type": "gainer",
            "market": MARKET,
        })
        existing_keys.add(f"{symbol}|gainer")
        new_count += 1

    # 追加跌幅榜
    for idx, t in enumerate(losers):
        symbol = t["symbol"]
        if f"{symbol}|loser" in existing_keys:
            continue
        history[today].append({
            "symbol": symbol,
            "pct": round(float(t["priceChangePercent"]), 2),
            "price": float(t["lastPrice"]),
            "firstSeen": now_time_str(),
            "rank": idx + 1,
            "type": "loser",
            "market": MARKET,
        })
        existing_keys.add(f"{symbol}|loser")
        new_count += 1

    # 清理超过120天的旧数据
    MAX_DAYS = 120
    if len(history) > MAX_DAYS:
        sorted_dates = sorted(k for k in history.keys() if k != "_meta")
        for old_date in sorted_dates[:len(history) - MAX_DAYS]:
            del history[old_date]

    history["_meta"] = {
        "lastUpdate": datetime.now(BEIJING_TZ).isoformat(),
        "topN": TOP_N,
        "quote": QUOTE,
        "market": MARKET,
    }

    save_history(history)

    if new_count > 0:
        print(f"  ✅ 新增 {new_count} 个币种到 {today} 的记录")
    else:
        print(f"  ℹ️  本轮无新增（TOP{TOP_N}均已记录过）")

    print(f"[{now_time_str()}] 采集完成")


if __name__ == "__main__":
    main()
