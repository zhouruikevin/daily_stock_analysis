#!/usr/bin/env python3
"""原始概率化情景推演（校准前的模型输出）。

组合 趋势状态 + 量价健康度 + 关键位 + scoring，产出未来 horizon 交易日的
三情景（顺势延续 / 震荡回踩 / 趋势反转），各带概率 + 目标价区间，
外加整体预期波动带（ATR）与 T+1 预期带。校准由 calibration.py 事后叠加。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

import indicators as ind
import scoring
from key_levels import compute_key_levels


def _nearest(levels: List[Dict[str, Any]]) -> Optional[float]:
    return levels[0]["value"] if levels else None


def build_forecast(df: pd.DataFrame, trend: Dict[str, Any], vp: Dict[str, Any],
                   *, horizon: int = 7) -> Dict[str, Any]:
    """返回 forecast dict（原始，未校准）。"""
    current = float(df["close"].iloc[-1])
    atr = float(ind.calc_atr(df).iloc[-1])
    if math.isnan(atr) or atr <= 0:
        atr = current * 0.01  # 兜底 1%
    direction = trend["direction"]
    strength_label = trend["strength_label"]
    health = vp["health_score"]

    levels = compute_key_levels(df, current)
    resistances = levels.get("resistance_levels", [])
    supports = levels.get("support_levels", [])
    imm_r = levels.get("immediate_resistance")
    imm_s = levels.get("immediate_support")

    near_r = imm_r is not None and (imm_r - current) / current * 100 <= scoring.NEAR_LEVEL_PCT
    near_s = imm_s is not None and (current - imm_s) / current * 100 <= scoring.NEAR_LEVEL_PCT

    probs = scoring.raw_scenario_probs(strength_label, health, near_r, near_s, direction)

    slope_pct_day = trend.get("slope_pct_per_day", 0.0) / 100.0  # 转成小数
    band_h = scoring.ATR_TARGET_BAND * atr * math.sqrt(max(1, horizon))

    scenarios: List[Dict[str, Any]] = []

    # --- 顺势延续 ---
    cont_dir = direction if direction in ("up", "down") else "up"
    if direction == "up":
        extrap = current * (1 + max(0.0, slope_pct_day) * horizon)
        cap = imm_r if imm_r else extrap
        # 撞位则目标就在上沿附近；否则取斜率外推与下一阻力的较小值
        target = min(extrap, resistances[-1]["value"]) if resistances else extrap
        target = max(target, current)
        trigger = f"守住 {imm_s:g}" if imm_s else "不破近期低点"
    elif direction == "down":
        extrap = current * (1 + min(0.0, slope_pct_day) * horizon)
        target = max(extrap, supports[-1]["value"]) if supports else extrap
        target = min(target, current)
        trigger = f"压制于 {imm_r:g}" if imm_r else "不破近期高点"
    else:  # range → 顺势=当前箱体内温和
        target = current
        trigger = "箱体内运行"
    scenarios.append({
        "type": "continuation",
        "name": f"{scoring.SCENARIO_CN['continuation']}"
                f"({'上行' if cont_dir == 'up' else '下行'})",
        "direction": cont_dir,
        "probability": probs["continuation"],
        "target_range": _range(target, band_h),
        "trigger": trigger,
        "rationale": f"{strength_label}趋势 + 量价健康{health}",
    })

    # --- 震荡回踩 ---
    lo = imm_s if imm_s else current * (1 - 0.015)
    hi = imm_r if imm_r else current * (1 + 0.015)
    scenarios.append({
        "type": "consolidation",
        "name": scoring.SCENARIO_CN["consolidation"],
        "direction": "range",
        "probability": probs["consolidation"],
        "target_range": {"low": round(min(lo, hi), 2), "high": round(max(lo, hi), 2)},
        "trigger": "上下沿之间反复",
        "rationale": "多空僵持 / 关键位附近拉锯",
    })

    # --- 趋势反转 ---
    rev_dir = "down" if direction == "up" else ("up" if direction == "down" else "down")
    if rev_dir == "down":
        rev_target = imm_s if imm_s else current * (1 - 0.03)
        rev_trigger = f"跌破 {imm_s:g}" if imm_s else "跌破近期支撑"
    else:
        rev_target = imm_r if imm_r else current * (1 + 0.03)
        rev_trigger = f"突破 {imm_r:g}" if imm_r else "突破近期阻力"
    scenarios.append({
        "type": "reversal",
        "name": f"{scoring.SCENARIO_CN['reversal']}"
                f"({'下行' if rev_dir == 'down' else '上行'})",
        "direction": rev_dir,
        "probability": probs["reversal"],
        "target_range": _range(rev_target, band_h),
        "trigger": rev_trigger,
        "rationale": "量价背离 / 撞关键位时抬升",
    })

    primary = max(scenarios, key=lambda s: s["probability"])
    band_h_all = scoring.ATR_HORIZON_BAND * atr * math.sqrt(max(1, horizon))

    return {
        "horizon_days": [max(1, horizon - 2), horizon + 3],
        "horizon": horizon,
        "atr": round(atr, 2),
        "expected_range": _range(current, band_h_all),
        "expected_range_t1": _range(current, scoring.ATR_HORIZON_BAND * atr),
        "scenarios": scenarios,
        "primary_scenario": primary["type"],
        "key_levels": levels,
        "signal": _build_signal(trend, vp, primary, imm_s, imm_r),
    }


def _range(center: float, half: float) -> Dict[str, float]:
    return {"low": round(center - half, 2), "high": round(center + half, 2)}


def _build_signal(trend: Dict[str, Any], vp: Dict[str, Any],
                  primary: Dict[str, Any], imm_s, imm_r) -> str:
    dir_cn = {"up": "上升", "down": "下降", "range": "震荡"}[trend["direction"]]
    tr = primary["target_range"]
    fail = f"跌破 {imm_s:g}" if (trend["direction"] == "up" and imm_s) else \
           (f"突破 {imm_r:g}" if (trend["direction"] == "down" and imm_r) else "关键位")
    return (f"{dir_cn}趋势({trend['strength_label']})，量价{vp['health_label']}"
            f"{vp['health_score']}，未来大概率{primary['name']}至 "
            f"{tr['low']:g}-{tr['high']:g}，{fail}转向")


__all__ = ["build_forecast"]
