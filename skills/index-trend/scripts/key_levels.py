#!/usr/bin/env python3
"""指数关键位（上沿/下沿）汇总计算。

输入：日线 DataFrame（含 date/open/high/low/close）+ 当前价
输出：上沿（阻力）列表 + 下沿（支撑）列表，按距离当前价从近到远排序，
      并按强中弱分级，相近的位会合并成一条（取最强）。

候选来源：MA20/60/120/250、EMA20/60、BOLL(20,2)、近 N 日极值、
当日 high/low、整数关口、Fibonacci 回撤位。

设计动机：单一指标当上下沿太脆弱（比如纯 BOLL 上轨容易被穿透），
多指标共振才是真"关口"，故合并相近位时优先保留强信号（MA60/MA120/
整数关口/Fib0.5/0.618），把弱信号当成辅助证据并入 types 列表。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import pandas as pd


# 强度分级常量，便于 _merge_nearby 按"强 > 中 > 弱"取最强
_STRENGTH_RANK = {"弱": 1, "中": 2, "强": 3}
_RANK_TO_STRENGTH = {v: k for k, v in _STRENGTH_RANK.items()}


# ============================================================
# 候选生成器：每个返回 List[{value, label, strength, types}]
# ============================================================
def _ma_candidates(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """MA20/60/120/250。MA20=中、其余=强。"""
    out: List[Dict[str, Any]] = []
    specs = [(20, "中"), (60, "强"), (120, "强"), (250, "强")]
    close = df["close"]
    for period, strength in specs:
        if len(close) < period:
            continue
        val = float(close.rolling(period).mean().iloc[-1])
        if math.isnan(val):
            continue
        out.append({"value": val, "label": f"MA{period}",
                    "strength": strength, "types": ["ma"]})
    return out


def _ema_candidates(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """EMA20=中、EMA60=强。"""
    out: List[Dict[str, Any]] = []
    specs = [(20, "中"), (60, "强")]
    close = df["close"]
    for period, strength in specs:
        if len(close) < period:
            continue
        val = float(close.ewm(span=period, adjust=False).mean().iloc[-1])
        if math.isnan(val):
            continue
        out.append({"value": val, "label": f"EMA{period}",
                    "strength": strength, "types": ["ema"]})
    return out


def _boll_candidates(df: pd.DataFrame, period: int = 20,
                     n_std: float = 2.0) -> List[Dict[str, Any]]:
    """BOLL(20,2) 上下轨。归类为弱：常被有效突破，单独作判据不可靠。"""
    close = df["close"]
    if len(close) < period:
        return []
    ma = close.rolling(period).mean()
    # ddof=0 与同花顺/通达信一致（总体标准差）
    std = close.rolling(period).std(ddof=0)
    upper = float(ma.iloc[-1] + n_std * std.iloc[-1])
    lower = float(ma.iloc[-1] - n_std * std.iloc[-1])
    if math.isnan(upper) or math.isnan(lower):
        return []
    return [
        {"value": upper, "label": "BOLL上轨", "strength": "弱", "types": ["boll"]},
        {"value": lower, "label": "BOLL下轨", "strength": "弱", "types": ["boll"]},
    ]


def _extrema_candidates(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """近 5/20/60 日的最高/最低。5=弱、20=中、60=强。

    排除最后一根（"当日"），避免和 _today_candidates 重复且把当日 high/low
    误标为"近 N 日极值"。
    """
    out: List[Dict[str, Any]] = []
    if len(df) < 2:
        return out
    body = df.iloc[:-1]  # 不含当日
    specs = [(5, "弱"), (20, "中"), (60, "强")]
    for window, strength in specs:
        if len(body) < window:
            continue
        recent = body.tail(window)
        out.append({"value": float(recent["high"].max()),
                    "label": f"近{window}日高点", "strength": strength,
                    "types": ["extrema"]})
        out.append({"value": float(recent["low"].min()),
                    "label": f"近{window}日低点", "strength": strength,
                    "types": ["extrema"]})
    return out


def _today_candidates(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """当日 high/low。中等强度：反映当日博弈，但盘中可能被反复测试。"""
    if len(df) == 0:
        return []
    last = df.iloc[-1]
    return [
        {"value": float(last["high"]), "label": "当日高点",
         "strength": "中", "types": ["today"]},
        {"value": float(last["low"]), "label": "当日低点",
         "strength": "中", "types": ["today"]},
    ]


def _round_number_candidates(current_price: float) -> List[Dict[str, Any]]:
    """整数关口：上下相邻的 step 倍数 + 上下相邻的 10×step 倍数（更强）。

    step 按当前价量级自动选：
    - <100   → 1
    - 100~1k → 10
    - 1k~5k  → 50（典型上证 4000）
    - ≥5k    → 100
    """
    if current_price <= 0:
        return []
    if current_price < 100:
        step = 1
    elif current_price < 1000:
        step = 10
    elif current_price < 5000:
        step = 50
    else:
        step = 100
    big_step = step * 10

    out: List[Dict[str, Any]] = []

    def _emit(step_val: int, label: str, types: List[str]) -> None:
        """生成 step_val 量级下、严格大于 / 小于 current_price 的两个最近关口。"""
        down = math.floor(current_price / step_val) * step_val
        up = math.ceil(current_price / step_val) * step_val
        # current_price 正好落在 step 倍数上时，floor==ceil==current_price，
        # 此时上下相邻的关口应取 current_price ± step。
        if down >= current_price:
            down = current_price - step_val
        if up <= current_price:
            up = current_price + step_val
        for val in [up, down]:
            if val > 0:
                out.append({"value": float(val), "label": label,
                            "strength": "强", "types": list(types)})

    _emit(step, "整数关口", ["round_number"])
    _emit(big_step, f"整数关口(×{big_step})", ["round_number_big"])
    return out


_FIB_RATIOS = [
    (0.236, "弱"),
    (0.382, "中"),
    (0.5, "强"),
    (0.618, "强"),
    (0.786, "弱"),
]


def _fib_candidates(df: pd.DataFrame, lookback: int = 60) -> List[Dict[str, Any]]:
    """以 lookback 内绝对最高 / 最低为参考段，算 5 个 Fib 回撤位。

    用 "high - retracement × range" 的标准黄金分割定义：
    - 上涨段（最低在前）：0.236 是最浅回撤、0.786 是最深回撤
    - 下跌段（最高在前）：同样的 5 个比例位，作为反弹阻力
    本实现不区分方向（双向都视作 high - r×range），因为我们只关心 5 个位的绝对价格，
    给上沿/下沿判断用。
    """
    if len(df) < 2:
        return []
    recent = df.tail(lookback)
    high = float(recent["high"].max())
    low = float(recent["low"].min())
    rng = high - low
    if rng <= 0:
        return []
    out: List[Dict[str, Any]] = []
    for ratio, strength in _FIB_RATIOS:
        val = high - ratio * rng
        out.append({"value": float(val), "label": f"Fib {ratio:.3f}".rstrip("0").rstrip("."),
                    "strength": strength, "types": ["fib"]})
    return out


# ============================================================
# 合并 / 排序 / 截断
# ============================================================
def _merge_nearby(items: List[Dict[str, Any]],
                  merge_tol_pct: float) -> List[Dict[str, Any]]:
    """同一价位 ±merge_tol_pct% 内合并成一条：保留强度最高，label 拼接。

    实现：先按 value 排序，然后线性扫一遍。注意基准价用合并后的 value 均值
    更稳，避免链式合并漂移。
    """
    if not items:
        return []
    items_sorted = sorted(items, key=lambda c: c["value"])
    merged: List[Dict[str, Any]] = []
    for cur in items_sorted:
        if not merged:
            merged.append({**cur, "value": float(cur["value"]),
                           "_labels": [cur["label"]],
                           "_types": set(cur["types"])})
            continue
        last = merged[-1]
        if abs(cur["value"] - last["value"]) / max(last["value"], 1e-9) * 100 <= merge_tol_pct:
            # 强度取更强的
            if _STRENGTH_RANK[cur["strength"]] > _STRENGTH_RANK[last["strength"]]:
                last["strength"] = cur["strength"]
            # value 用最强的那一类的 value；若同强度，取均值
            if _STRENGTH_RANK[cur["strength"]] > _STRENGTH_RANK.get(
                    _RANK_TO_STRENGTH.get(_STRENGTH_RANK[last["strength"]], "弱"), 0):
                pass
            last["_labels"].append(cur["label"])
            last["_types"].update(cur["types"])
            # value 用合并后两端的中点（保守做法）
            last["value"] = (last["value"] + cur["value"]) / 2.0
        else:
            merged.append({**cur, "value": float(cur["value"]),
                           "_labels": [cur["label"]],
                           "_types": set(cur["types"])})

    # 输出：label 用 "+" 连接（最多展示 3 个，避免太长）
    out: List[Dict[str, Any]] = []
    for m in merged:
        labels = m["_labels"]
        if len(labels) > 3:
            label = "+".join(labels[:3]) + f"等{len(labels)}项"
        else:
            label = "+".join(labels)
        out.append({
            "value": round(m["value"], 2),
            "label": label,
            "strength": m["strength"],
            "types": sorted(m["_types"]),
        })
    return out


def _annotate(items: List[Dict[str, Any]],
              current_price: float) -> List[Dict[str, Any]]:
    """补 distance_pct 字段。"""
    out = []
    for it in items:
        diff_pct = (it["value"] - current_price) / current_price * 100
        out.append({**it, "distance_pct": round(diff_pct, 2)})
    return out


# ============================================================
# 公开 API
# ============================================================
def compute_key_levels(
    df: pd.DataFrame,
    current_price: float,
    *,
    band_window_pct: float = 3.0,
    band_limit: int = 5,
    merge_tol_pct: float = 0.3,
    fib_lookback: int = 60,
) -> Dict[str, Any]:
    """计算指数上下沿（阻力 / 支撑）。

    Args:
        df: 含 date/open/high/low/close 的日线 DataFrame，最后一行是最新一日
        current_price: 当前参考价（一般传入 df["close"].iloc[-1]）
        band_window_pct: 距当前价 ±band_window_pct% 以外的位会被裁掉
        band_limit: 上沿 / 下沿各最多保留多少条
        merge_tol_pct: 同一价位 ±merge_tol_pct% 内合并成一条
        fib_lookback: Fib 参考段：取最近 fib_lookback 日内的最高 / 最低

    Returns:
        {
          "current_price": float,
          "resistance_levels": [ {value, label, strength, distance_pct, types}, ... ],
          "support_levels":    [ ... ],
          "immediate_resistance": Optional[float],
          "immediate_support":    Optional[float],
          "all_candidates_count": int,
        }
    """
    if df is None or len(df) == 0 or current_price <= 0:
        return {
            "current_price": round(current_price, 2) if current_price else None,
            "resistance_levels": [],
            "support_levels": [],
            "immediate_resistance": None,
            "immediate_support": None,
            "all_candidates_count": 0,
        }

    candidates = (
        _ma_candidates(df)
        + _ema_candidates(df)
        + _boll_candidates(df)
        + _extrema_candidates(df)
        + _today_candidates(df)
        + _round_number_candidates(current_price)
        + _fib_candidates(df, lookback=fib_lookback)
    )

    # 1. 按距离过滤
    filtered = [
        c for c in candidates
        if abs(c["value"] - current_price) / current_price * 100 <= band_window_pct
    ]

    # 2. 拆 above / below（== 当前价的位归为下沿，避免遗漏）
    above = [c for c in filtered if c["value"] > current_price]
    below = [c for c in filtered if c["value"] <= current_price]

    # 3. 合并相近
    above_merged = _merge_nearby(above, merge_tol_pct)
    below_merged = _merge_nearby(below, merge_tol_pct)

    # 4. 排距离（从近到远）
    above_merged.sort(key=lambda c: c["value"] - current_price)
    below_merged.sort(key=lambda c: current_price - c["value"])

    # 5. 截断 + 算 distance_pct
    above_out = _annotate(above_merged[:band_limit], current_price)
    below_out = _annotate(below_merged[:band_limit], current_price)

    return {
        "current_price": round(current_price, 2),
        "resistance_levels": above_out,
        "support_levels": below_out,
        "immediate_resistance": above_out[0]["value"] if above_out else None,
        "immediate_support": below_out[0]["value"] if below_out else None,
        "all_candidates_count": len(filtered),
    }


__all__ = ["compute_key_levels"]
