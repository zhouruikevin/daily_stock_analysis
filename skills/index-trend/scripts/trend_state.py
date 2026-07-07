#!/usr/bin/env python3
"""趋势状态刻画：方向 / 强度 / 阶段（客观量化，不贴形态标签）。

核心信念："市场肯定是对的"——先客观读出当前趋势结构，作为后续预测的先验，
不预设反转。方向由三因子投票；强度是 0-100 连续分；阶段刻画趋势所处生命周期。
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

import indicators as ind
from swing_points import build_zigzag, last_n_pivots

# 方向阈值：近 20 日归一化斜率 %/日
_SLOPE_UP = 0.10
_SLOPE_DOWN = -0.10


def _structure_vote(pivots: List[Dict[str, Any]], df: pd.DataFrame) -> str:
    """由最近的高低点结构判断：HH+HL=up / LH+LL=down / 其余=range。

    摆动点不足时（趋势太干净、几乎无 3% 级回调，zigzag 挑不出足够枢轴），
    退化用分析窗口的净涨跌粗判方向——否则一条笔直上行的趋势会被误判成 range。
    """
    highs = [p for p in pivots if p["kind"] == "H"]
    lows = [p for p in pivots if p["kind"] == "L"]
    if len(highs) < 2 or len(lows) < 2:
        close = df["close"]
        if len(close) < 2:
            return "range"
        net = (float(close.iloc[-1]) - float(close.iloc[0])) / max(abs(float(close.iloc[0])), 1e-9) * 100
        if net > 3:
            return "up"
        if net < -3:
            return "down"
        return "range"
    hh = highs[-1]["price"] > highs[-2]["price"]
    hl = lows[-1]["price"] > lows[-2]["price"]
    lh = highs[-1]["price"] < highs[-2]["price"]
    ll = lows[-1]["price"] < lows[-2]["price"]
    if hh and hl:
        return "up"
    if lh and ll:
        return "down"
    return "range"


def _ma_vote(df: pd.DataFrame) -> str:
    """均线排列：ma5>10>20>60=多头 / 完全反向=空头 / 交错=range。"""
    close = df["close"]
    ma = {p: float(ind.calc_ma(close, p).iloc[-1]) for p in (5, 10, 20, 60)}
    if any(np.isnan(v) for v in ma.values()):
        # 长均线数据不足：退化用可得的短均线
        ma = {p: v for p, v in ma.items() if not np.isnan(v)}
        if len(ma) < 2:
            return "range"
    ordered = [ma[p] for p in sorted(ma)]
    if all(ordered[i] > ordered[i + 1] for i in range(len(ordered) - 1)):
        return "up"
    if all(ordered[i] < ordered[i + 1] for i in range(len(ordered) - 1)):
        return "down"
    return "range"


def _ma_alignment_label(df: pd.DataFrame) -> str:
    v = _ma_vote(df)
    return {"up": "多头排列", "down": "空头排列", "range": "纠缠"}[v]


def _slope_vote(df: pd.DataFrame, lookback: int = 20) -> tuple:
    """斜率投票。r² 高（趋势干净）时放宽阈值：慢而稳的趋势也算趋势，
    否则 0.084%/日、r²=0.997 这种极干净的缓涨会被误判成 range。"""
    slope_pct, r2 = ind.slope_pct_per_bar(df["close"], lookback)
    up_th, down_th = _SLOPE_UP, _SLOPE_DOWN
    if r2 > 0.75:
        up_th, down_th = _SLOPE_UP * 0.4, _SLOPE_DOWN * 0.4
    if slope_pct > up_th:
        v = "up"
    elif slope_pct < down_th:
        v = "down"
    else:
        v = "range"
    return v, slope_pct, r2


def _direction_consistency(df: pd.DataFrame, direction: str, lookback: int = 20) -> float:
    """近 lookback 日中，日涨跌与 direction 同向的天数占比 [0,1]。"""
    chg = df["close"].diff().tail(lookback).to_numpy(dtype=float)
    chg = chg[~np.isnan(chg)]
    if len(chg) == 0:
        return 0.0
    if direction == "up":
        return float(np.mean(chg > 0))
    if direction == "down":
        return float(np.mean(chg < 0))
    # range：接近 0.5 最"震荡"，一致性得分取 1-|2p-1|
    p_up = float(np.mean(chg > 0))
    return 1.0 - abs(2 * p_up - 1)


def analyze_trend(df: pd.DataFrame, *, swing_threshold: float = 3.0) -> Dict[str, Any]:
    """输出趋势方向 / 强度(0-100) / 阶段 / 结构描述。df 需含 date/OHLC。"""
    pivots = build_zigzag(df, pct_threshold=swing_threshold)
    struct_v = _structure_vote(last_n_pivots(pivots, 6), df)
    ma_v = _ma_vote(df)
    slope_v, slope_pct, r2 = _slope_vote(df)

    # 三因子投票（平票偏 range）
    votes = [struct_v, ma_v, slope_v]
    for cand in ("up", "down"):
        if votes.count(cand) >= 2:
            direction = cand
            break
    else:
        direction = "range"

    # 强度 0-100：斜率陡度40 + 均线发散25 + r2*20 + 方向一致性15
    close = df["close"]
    ma5 = float(ind.calc_ma(close, 5).iloc[-1])
    ma60 = float(ind.calc_ma(close, 60).iloc[-1]) if len(close) >= 60 else np.nan
    cur = float(close.iloc[-1])
    slope_score = min(1.0, abs(slope_pct) / 0.6) * 40  # 0.6%/日≈满分
    if not np.isnan(ma60) and cur > 0:
        divergence = abs(ma5 - ma60) / cur * 100
        div_score = min(1.0, divergence / 5.0) * 25  # 5% 发散≈满分
    else:
        div_score = 0.0
    r2_score = r2 * 20
    consistency = _direction_consistency(df, direction)
    cons_score = consistency * 15
    strength = int(round(slope_score + div_score + r2_score + cons_score))
    strength = max(0, min(100, strength))
    if direction == "range":
        strength = min(strength, 40)  # 震荡趋势强度天然受限
    strength_label = "强" if strength >= 67 else ("中" if strength >= 34 else "弱")

    phase = _infer_phase(df, direction, slope_pct)

    structure_desc = {"up": "HH+HL", "down": "LH+LL", "range": "混合"}[struct_v]
    return {
        "direction": direction,
        "strength": strength,
        "strength_label": strength_label,
        "phase": phase,
        "structure": structure_desc,
        "ma_alignment": _ma_alignment_label(df),
        "slope_pct_per_day": round(slope_pct, 3),
        "r2": round(r2, 3),
        "votes": {"structure": struct_v, "ma": ma_v, "slope": slope_v},
        "pivots": pivots,
    }


def _infer_phase(df: pd.DataFrame, direction: str, slope_pct: float) -> str:
    """初期/加速/稳定/衰竭：由斜率二阶变化 + 量价配合近似。"""
    close = df["close"]
    if len(close) < 30:
        return "初期"
    # 近 10 日 vs 前 10 日斜率对比
    recent_slope, _ = ind.slope_pct_per_bar(close.tail(10), 10)
    prev_slope, _ = ind.slope_pct_per_bar(close.iloc[-20:-10], 10)

    # 方向刚翻转：前段与当前方向相反
    if direction == "up" and prev_slope < -_SLOPE_UP and recent_slope > 0:
        return "初期"
    if direction == "down" and prev_slope > _SLOPE_UP and recent_slope < 0:
        return "初期"

    accel = abs(recent_slope) - abs(prev_slope)
    # 量能是否配合（顺势放量）
    vol = df["volume"]
    vol_ma5 = float(ind.calc_ma(vol, 5).iloc[-1])
    vol_ma20 = float(ind.calc_ma(vol, 20).iloc[-1]) if len(vol) >= 20 else vol_ma5
    vol_expand = vol_ma20 > 0 and vol_ma5 > vol_ma20

    if direction == "range":
        return "稳定"
    if accel > 0.05 and vol_expand:
        return "加速"
    if accel < -0.05 or (not vol_expand and abs(recent_slope) < abs(prev_slope)):
        return "衰竭"
    return "稳定"


__all__ = ["analyze_trend"]
