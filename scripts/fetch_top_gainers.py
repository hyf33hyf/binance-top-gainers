#!/usr/bin/env python3
"""
币安每日涨幅榜采集脚本
由 GitHub Actions 定时触发运行，每次执行：
1. 拉取币安24h行情数据
2. 按涨幅排序取 TOP N
3. 读取已有的 data/history.json
4. 把当天还没记录过的新币种追加进去（同一天同一币种不重复）
5. 写回 history.json，由 GitHub Actions 自动提交到仓库
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

API_BASE = "https://api.binance.com"
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "history.json")

# 可通过环境变量配置，默认 TOP5 / USDT
TOP_N = int(os.environ.get("TOP_N", "5"))
QUOTE = os.environ.get("QUOTE", "USDT")

# 使用北京时间（UTC+8）作为日期归档标准，与用户感知的"今天"一致
BEIJING_TZ = timezone(timedelta(hours=8))


def fetch_json(url, timeout=15):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_valid_symbols(quote):
    """获取所有正常交易中的指定计价货币现货交易对"""
    data = fetch_json(f"{API_BASE}/api/v3/exchangeInfo")
    return {
        s["symbol"]
        for s in data["symbols"]
        if s["quoteAsset"] == quote
        and s["status"] == "TRADING"
        and s.get("isSpotTradingAllowed", False)
    }


def get_top_gainers(valid_symbols, top_n):
    """获取24h涨幅榜前N名（仅限valid_symbols范围内）"""
    tickers = fetch_json(f"{API_BASE}/api/v3/ticker/24hr")
    filtered = [t for t in tickers if t["symbol"] in valid_symbols]
    sorted_tickers = sorted(
        filtered, key=lambda t: float(t["priceChangePercent"]), reverse=True
    )
    return sorted_tickers[:top_n]


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
    print(f"[{now_time_str()}] 开始采集 TOP{TOP_N} {QUOTE} 涨幅榜...")

    try:
        valid_symbols = get_valid_symbols(QUOTE)
        print(f"  有效交易对数量: {len(valid_symbols)}")

        top_list = get_top_gainers(valid_symbols, TOP_N)
        print(f"  本轮 TOP{TOP_N}: {[t['symbol'] for t in top_list]}")
    except URLError as e:
        print(f"  错误：无法连接币安API: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"  错误：采集失败: {e}", file=sys.stderr)
        sys.exit(1)

    history = load_history()
    today = today_str()

    if today not in history:
        history[today] = []

    existing_symbols = {c["symbol"] for c in history[today]}
    new_count = 0

    for idx, t in enumerate(top_list):
        symbol = t["symbol"]
        if symbol in existing_symbols:
            continue  # 当天已记录过，跳过（核心去重逻辑）

        history[today].append({
            "symbol": symbol,
            "pct": round(float(t["priceChangePercent"]), 2),
            "price": float(t["lastPrice"]),
            "firstSeen": now_time_str(),
            "rank": idx + 1,
        })
        new_count += 1

    # 清理超过120天的旧数据，避免文件无限增长
    MAX_DAYS = 120
    if len(history) > MAX_DAYS:
        sorted_dates = sorted(history.keys())
        for old_date in sorted_dates[: len(history) - MAX_DAYS]:
            del history[old_date]

    # 记录最后更新时间，供网页展示
    history["_meta"] = {
        "lastUpdate": datetime.now(BEIJING_TZ).isoformat(),
        "topN": TOP_N,
        "quote": QUOTE,
    }

    save_history(history)

    if new_count > 0:
        print(f"  ✅ 新增 {new_count} 个币种到 {today} 的记录")
    else:
        print(f"  ℹ️  本轮无新增（TOP{TOP_N}均已记录过）")

    print(f"[{now_time_str()}] 采集完成")


if __name__ == "__main__":
    main()
