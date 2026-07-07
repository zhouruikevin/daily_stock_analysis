#!/usr/bin/env python3
"""量价健康度：判断当前趋势的量价配合是否健康。

设计原则（呼应"市场是对的"）：基准分偏高（默认顺势可延续），
量价背离只做减分、降低"趋势延续的置信"，**不直接判反转**。
输出 health_score(0-100) + label + 命中的量价信号。
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

import indicators as ind

_BASE = 60          # 顺势基准：默认相信趋势能延续
_TIANLIANG = 2.5    # 天量量比阈值


def analyze_volume_price(df: pd.DataFrame, direction: str) -> Dict[str, Any]:
    """direction 来自 trend_state，用于判断"顺势"方向。"""
    close = df["close"]
    vol = df["volume"]
    if len(df) < 6:
        return {"health_score": _BASE, "health_label": "中性",
                "vol_ratio": None, "vol_trend": "平稳", "signals": []}

    vol_ma5 = float(ind.calc_ma(vol, 5).iloc[-1])
    vol_ma20 = float(ind.calc_ma(vol, 20).iloc[-1]) if len(vol) >= 20 else vol_ma5
    last_vol = float(vol.iloc[-1])
    vol_ratio = last_vol / vol_ma5 if vol_ma5 > 0 else None

    vol_trend = "平稳"
    if vol_ma20 > 0:
        if vol_ma5 > vol_ma20 * 1.05:
            vol_trend = "放量"
        elif vol_ma5 < vol_ma20 * 0.95:
            vol_trend = "缩量"

    # 近 5 日价 / 量 变化
    price_chg = float(close.iloc[-1] - close.iloc[-6]) / max(abs(close.iloc[-6]), 1e-9)
    price_up = price_chg > 0.002
    price_down = price_chg < -0.002

    score = _BASE
    signals: List[str] = []

    # 顺势放量 / 逆势缩量 = 健康
    if direction == "up":
        if price_up and vol_trend == "放量":
            score += 20
            signals.append("顺势放量")
        elif price_up and vol_trend == "缩量":
            score -= 20
            signals.append("价升量缩背离")
        elif price_down and vol_trend == "缩量":
            score += 5
            signals.append("回调缩量(健康)")
    elif direction == "down":
        if price_down and vol_trend == "放量":
            score += 20
            signals.append("顺势放量下跌")
        elif price_down and vol_trend == "缩量":
            score += 5
            signals.append("缩量阴跌")
        elif price_up and vol_trend == "放量":
            score -= 15
            signals.append("反抽放量(存疑)")
    else:  # range
        if vol_trend == "缩量":
            score += 5
            signals.append("缩量整理")

    # 放量滞涨：量比高但价格未创近 5 日新高
    if vol_ratio is not None and vol_ratio > 1.5:
        recent_high = float(df["high"].iloc[-6:-1].max())
        if float(df["high"].iloc[-1]) <= recent_high:
            score -= 15
            signals.append("放量滞涨")

    # 天量预警（按位置：上升趋势天量易见顶）
    if vol_ratio is not None and vol_ratio >= _TIANLIANG:
        if direction == "up":
            score -= 10
            signals.append("天量预警(顶部风险)")
        elif direction == "down":
            score -= 5
            signals.append("天量(或恐慌盘)")

    score = max(0, min(100, score))
    label = "健康" if score >= 67 else ("中性" if score >= 34 else "背离衰竭")
    if not signals:
        signals.append("量价平稳")

    return {
        "health_score": int(round(score)),
        "health_label": label,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "vol_trend": vol_trend,
        "signals": signals,
    }


__all__ = ["analyze_volume_price"]
