#!/usr/bin/env python3
"""上下沿通道（自适应）+ 量价突破判断。

用户心智："通道就是上下沿"——近期走势被框在一条上沿、一条下沿之间。
自适应：
- 有趋势（回归 r² ≥ trend_r2）→ 回归通道，中轨随趋势倾斜 ± 波动带（残差 σ）。
- 震荡（r² < trend_r2）→ 水平箱体，上沿=近 N 日阻力带、下沿=支撑带（用分位抗插针）。
  （实盘验证：震荡市回归通道斜率无意义，故降级为水平箱体。）

再结合量价（复用 volume_price 的结果）判断当前更可能：
突破上沿 / 跌破下沿 / 通道内震荡 / 上沿假突破回落 / 下沿企稳反弹。
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

import indicators as ind

# 贴边阈值
_NEAR_UP = 0.8
_NEAR_DOWN = 0.2
_EXTREME_UP = 0.9
_EXTREME_DOWN = 0.1
# 方向斜率阈值（%/bar）
_SLOPE_FLAT = 0.05


def compute_channel(df: pd.DataFrame, *, lookback: int = 40,
                    k: float = 2.0, trend_r2: float = 0.5) -> Dict[str, Any]:
    """自适应上下沿通道。返回 available=False 表示数据不足/退化，上层应优雅跳过。"""
    if df is None or len(df) < max(10, lookback // 2):
        return {"available": False, "reason": "数据不足"}

    lb = min(lookback, len(df))
    close = df["close"].tail(lb).to_numpy(dtype=float)
    high = df["high"].tail(lb).to_numpy(dtype=float)
    low = df["low"].tail(lb).to_numpy(dtype=float)
    cur = float(df["close"].iloc[-1])
    if cur <= 0:
        return {"available": False, "reason": "价格异常"}

    slope, intercept, r2 = ind.linreg(close)
    mean_y = float(np.mean(close)) or 1e-9
    slope_pct = slope / mean_y * 100

    if r2 >= trend_r2:
        # 回归通道：中轨随趋势倾斜 ± k·残差σ
        x = np.arange(len(close), dtype=float)
        fit = slope * x + intercept
        sigma = float(np.std(close - fit))
        mid = float(slope * (len(close) - 1) + intercept)
        upper = mid + k * sigma
        lower = mid - k * sigma
        ctype = "回归通道"
        direction = ("上升" if slope_pct > _SLOPE_FLAT
                     else "下降" if slope_pct < -_SLOPE_FLAT else "横向")
    else:
        # 水平箱体：分位数抗插针（90/10 分位）
        upper = float(np.percentile(high, 90))
        lower = float(np.percentile(low, 10))
        mid = (upper + lower) / 2.0
        ctype = "水平箱体"
        direction = "横向"

    if upper - lower < cur * 1e-4:  # 通道几乎无宽度，退化
        return {"available": False, "reason": "通道宽度过窄"}

    pos = (cur - lower) / (upper - lower)
    pos = max(0.0, min(1.0, pos))

    return {
        "available": True,
        "type": ctype,
        "lookback": lb,
        "upper": round(upper, 2),
        "mid": round(mid, 2),
        "lower": round(lower, 2),
        "current_price": round(cur, 2),
        "pos_in_channel": round(pos, 3),
        "direction": direction,
        "r2": round(r2, 3),
        "slope_pct_per_bar": round(slope_pct, 3),
        "width_pct": round((upper - lower) / cur * 100, 2),
    }


def judge_breakout(channel: Dict[str, Any], vp: Dict[str, Any]) -> Dict[str, Any]:
    """结合当前通道位置 + 量价，给出 突破/跌破/震荡 判断。"""
    if not channel.get("available"):
        return {"bias": "无（通道不可用）", "confidence": "无", "reason": ""}

    pos = channel["pos_in_channel"]
    upper = channel["upper"]
    lower = channel["lower"]
    vol_trend = vp.get("vol_trend", "平稳")
    signals = vp.get("signals", [])
    stagnant = any("滞涨" in s for s in signals)  # 放量滞涨 → 假突破风险

    price_str = f"放量看突破 {upper:g}，缩量回踩 {lower:g}"

    if pos >= _NEAR_UP:  # 贴上沿
        if vol_trend == "放量" and not stagnant:
            bias, reason = "倾向突破上沿", f"贴上沿且放量，{price_str}"
        elif vol_trend == "缩量" or stagnant:
            bias, reason = "上沿假突破回落", f"贴上沿但量能不继，易假突破回落至 {lower:g}"
        else:
            bias, reason = "临近上沿待突破确认", f"贴上沿，等量能表态；{price_str}"
    elif pos <= _NEAR_DOWN:  # 贴下沿
        if vol_trend == "放量":
            bias, reason = "倾向跌破下沿", f"贴下沿且放量下杀，跌破 {lower:g} 转弱"
        elif vol_trend == "缩量":
            bias, reason = "下沿企稳反弹", f"贴下沿且缩量企稳，易反弹守 {lower:g}"
        else:
            bias, reason = "临近下沿待企稳确认", f"贴下沿，等企稳信号；下破 {lower:g} 转弱"
    else:  # 中部
        bias = "通道内震荡"
        reason = f"位于通道中部（{channel['type']}），上沿 {upper:g}／下沿 {lower:g} 间反复"

    # 置信：贴边程度 + 判断是否明确
    extreme = pos >= _EXTREME_UP or pos <= _EXTREME_DOWN
    near = pos >= _NEAR_UP or pos <= _NEAR_DOWN
    decisive = bias not in ("临近上沿待突破确认", "临近下沿待企稳确认", "通道内震荡")
    if near and decisive:
        confidence = "强" if extreme else "中"
    elif near:
        confidence = "中"
    else:
        confidence = "弱"

    return {"bias": bias, "confidence": confidence, "reason": reason}


__all__ = ["compute_channel", "judge_breakout"]
