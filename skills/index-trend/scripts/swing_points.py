#!/usr/bin/env python3
"""摆动高低点 / zigzag —— 趋势方向的高低点结构底座。

思路借鉴 index-analysis 的 find_peaks（前后 window 根内的局部极值），
再合并成强制 高/低 交替的 zigzag，并过滤掉幅度小于阈值的微幅摆动，
使 HH/HL（higher-high + higher-low）、LH/LL 的判断稳健。
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd


def _find_local_extrema(df: pd.DataFrame, col: str, kind: str,
                        window: int = 3, min_gap: int = 5) -> List[Dict[str, Any]]:
    """局部极值点。kind='H' 找高点(col 越大越极端)，'L' 找低点。"""
    pts: List[Dict[str, Any]] = []
    vals = df[col].to_numpy(dtype=float)
    n = len(vals)
    for i in range(window, n - window):
        v = vals[i]
        is_ext = True
        for j in range(1, window + 1):
            if kind == "H":
                if v < vals[i - j] or v < vals[i + j]:
                    is_ext = False
                    break
            else:
                if v > vals[i - j] or v > vals[i + j]:
                    is_ext = False
                    break
        if is_ext:
            pts.append({"idx": i, "price": float(v), "kind": kind,
                        "date": str(df["date"].iloc[i])[:10]})

    # 合并相近同类极值，保留更极端的
    merged: List[Dict[str, Any]] = []
    for p in pts:
        if not merged or p["idx"] - merged[-1]["idx"] > min_gap:
            merged.append(p)
        else:
            more_extreme = (p["price"] > merged[-1]["price"]) if kind == "H" \
                else (p["price"] < merged[-1]["price"])
            if more_extreme:
                merged[-1] = p
    return merged


def find_swing_highs(df: pd.DataFrame, window: int = 3, min_gap: int = 5) -> List[Dict[str, Any]]:
    return _find_local_extrema(df, "high", "H", window, min_gap)


def find_swing_lows(df: pd.DataFrame, window: int = 3, min_gap: int = 5) -> List[Dict[str, Any]]:
    return _find_local_extrema(df, "low", "L", window, min_gap)


def build_zigzag(df: pd.DataFrame, pct_threshold: float = 3.0,
                 window: int = 3, min_gap: int = 5) -> List[Dict[str, Any]]:
    """合并 highs/lows → 按 idx 排序 → 强制 H/L 交替（同类相邻取更极端）→
    过滤相邻摆动幅度 < pct_threshold% 的噪音。返回按时间排序的枢轴列表。
    """
    highs = find_swing_highs(df, window, min_gap)
    lows = find_swing_lows(df, window, min_gap)
    pivots = sorted(highs + lows, key=lambda p: p["idx"])
    if not pivots:
        return []

    # 1. 强制交替：相邻同类只留更极端的
    alt: List[Dict[str, Any]] = []
    for p in pivots:
        if not alt:
            alt.append(p)
            continue
        if p["kind"] == alt[-1]["kind"]:
            if p["kind"] == "H":
                if p["price"] > alt[-1]["price"]:
                    alt[-1] = p
            else:
                if p["price"] < alt[-1]["price"]:
                    alt[-1] = p
        else:
            alt.append(p)

    # 2. 过滤微幅摆动：相邻枢轴变化 < 阈值则回退（去掉后一枢轴并保留更极端端点）
    filtered: List[Dict[str, Any]] = []
    for p in alt:
        if not filtered:
            filtered.append(p)
            continue
        prev = filtered[-1]
        move_pct = abs(p["price"] - prev["price"]) / max(prev["price"], 1e-9) * 100
        if move_pct < pct_threshold:
            # 幅度不够：视为噪音。若同向更极端则替换 prev，否则丢弃 p
            if p["kind"] == prev["kind"]:
                filtered[-1] = p
            # 不同类但幅度太小 → 丢弃 p（保留 prev 作为有效端点）
            continue
        filtered.append(p)
    return filtered


def last_n_pivots(pivots: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    return pivots[-n:] if n > 0 else []


__all__ = [
    "find_swing_highs", "find_swing_lows", "build_zigzag", "last_n_pivots",
]
