#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提取所有股票上下文的关键指标，输出紧凑摘要供 Qoder AI 分析。"""
import json
import os
import glob

STOCKS = [
    "600522", "601138", "603986", "002371", "002407", "002463",
    "603650", "603019", "603444", "600378", "002517", "002050",
    "603296", "601899", "600118", "000400", "605090",
    "hk00700", "hk01810", "hk03690",
    "600176", "603186", "601208",
]

def extract(code):
    path = f"/tmp/ctx_{code}.json"
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)

    rt = d.get("realtime") or {}
    tr = d.get("trend") or {}
    ch = d.get("chip") or {}
    bc = d.get("base_context") or {}
    fund = d.get("fundamental") or {}
    news = d.get("news") or ""
    pi = d.get("persisted_intelligence") or ""
    idx = d.get("index_snapshot") or {}
    cp = d.get("context_pack") or {}

    # today/yesterday K-line
    today = bc.get("today") or {}
    yesterday = bc.get("yesterday") or {}

    return {
        "code": code,
        "name": d.get("name", code),
        "price": rt.get("price"),
        "change_pct": rt.get("change_pct"),
        "volume_ratio": rt.get("volume_ratio"),
        "turnover_rate": rt.get("turnover_rate"),
        "pe_ratio": rt.get("pe_ratio"),
        "pb_ratio": rt.get("pb_ratio"),
        "total_mv": rt.get("total_mv"),
        "amplitude": rt.get("amplitude"),
        "trend_status": tr.get("trend_status"),
        "buy_signal": tr.get("buy_signal"),
        "signal_score": tr.get("signal_score"),
        "ma5": tr.get("ma5"),
        "ma10": tr.get("ma10"),
        "ma20": tr.get("ma20"),
        "ma60": tr.get("ma60"),
        "chip_profit_ratio": ch.get("profit_ratio"),
        "chip_concentration_90": ch.get("concentration_90"),
        "chip_avg_cost": ch.get("avg_cost"),
        "today_close": today.get("close"),
        "today_volume": today.get("volume"),
        "yesterday_close": yesterday.get("close"),
        "volume_change_ratio": bc.get("volume_change_ratio"),
        "price_change_ratio": bc.get("price_change_ratio"),
        "fund_status": fund.get("status"),
        "fund_coverage": fund.get("coverage"),
        "news_text": (news[:800] if news else ""),
        "persisted_intel": (pi[:400] if pi else ""),
        "index_csi2000": idx.get("csi2000_pct"),
        "index_chinext": idx.get("chinext_pct"),
        "cp_quote": (cp.get("quote") or {}).get("status") if isinstance(cp.get("quote"), dict) else None,
        "cp_daily": (cp.get("daily_bars") or {}).get("status") if isinstance(cp.get("daily_bars"), dict) else None,
        "cp_tech": (cp.get("technical") or {}).get("status") if isinstance(cp.get("technical"), dict) else None,
        "cp_news": (cp.get("news") or {}).get("status") if isinstance(cp.get("news"), dict) else None,
        "cp_fund": (cp.get("fundamentals") or {}).get("status") if isinstance(cp.get("fundamentals"), dict) else None,
        "cp_chip": (cp.get("chip") or {}).get("status") if isinstance(cp.get("chip"), dict) else None,
        "data_source": d.get("data_source", ""),
    }

results = []
for code in STOCKS:
    r = extract(code)
    if r:
        results.append(r)

# Output as compact JSON
print(json.dumps(results, ensure_ascii=False, default=str, indent=2))
