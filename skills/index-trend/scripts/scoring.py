#!/usr/bin/env python3
"""概率 / 评分模型常量与函数（集中放这里，便于后续用台账数据校准调参）。

三情景概率模型体现"顺势先验"：趋势越强、量价越健康 → 顺势延续概率越高；
量价背离 + 撞关键位 → 抬升震荡 / 反转概率。所有魔数在此定义，勿散落各处。
"""
from __future__ import annotations

from typing import Dict, List

# 顺势延续基准（按趋势强度标签）
CONT_BASE = {"range": 35, "弱": 45, "中": 55, "强": 65}
# 反转基准（趋势越强越不易反转）
REV_BASE = {"range": 25, "弱": 20, "中": 15, "强": 10}

HEALTH_CONT_COEF = 0.4   # health 每偏离 50 一分，对顺势概率的调节
HEALTH_REV_COEF = 0.3    # health 每低于 50 一分，对反转概率的调节
NEAR_LEVEL_PCT = 1.5     # 顺势方向距最近关键位 < 此值视为"撞位"
NEAR_CONT_PENALTY = 10   # 撞位对顺势概率的扣减
NEAR_REV_BONUS = 8       # 撞位对反转概率的加成

PROB_FLOOR = 5
PROB_CEIL = 85

# 目标区间 / 波动带
ATR_HORIZON_BAND = 1.0   # 整体预期带 = current ± k*ATR*sqrt(horizon)
ATR_TARGET_BAND = 0.5    # 情景目标区间半宽 = k*ATR*sqrt(horizon)


def raw_scenario_probs(strength_label: str, health_score: int,
                       near_resistance: bool, near_support: bool,
                       direction: str) -> Dict[str, int]:
    """原始三情景概率（未经历史校准），返回 {continuation, consolidation, reversal}，和=100。

    near_resistance/near_support：顺势方向前方是否紧贴关键位。
    """
    p_cont = CONT_BASE.get(strength_label, 45)
    p_cont += (health_score - 50) * HEALTH_CONT_COEF

    p_rev = REV_BASE.get(strength_label, 20)
    p_rev += (50 - health_score) * HEALTH_REV_COEF

    # 撞位：顺势方向前方有近关键位 → 顺势难、反转/震荡易
    hit = (direction == "up" and near_resistance) or (direction == "down" and near_support)
    if hit:
        p_cont -= NEAR_CONT_PENALTY
        p_rev += NEAR_REV_BONUS

    # range 无明确顺势方向 → 顺势概率进一步压低，震荡主导
    if direction == "range":
        p_cont = min(p_cont, 40)

    p_cont = _clamp(p_cont)
    p_rev = _clamp(p_rev)
    p_cons = 100 - p_cont - p_rev
    p_cons = _clamp(p_cons)

    return _normalize({"continuation": p_cont, "consolidation": p_cons, "reversal": p_rev})


def _clamp(v: float) -> float:
    return max(PROB_FLOOR, min(PROB_CEIL, v))


def _normalize(probs: Dict[str, float]) -> Dict[str, int]:
    total = sum(probs.values())
    if total <= 0:
        n = len(probs)
        return {k: round(100 / n) for k in probs}
    scaled = {k: v / total * 100 for k, v in probs.items()}
    # 取整并把舍入误差补到最大项，保证和恰好 100
    out = {k: int(round(v)) for k, v in scaled.items()}
    diff = 100 - sum(out.values())
    if diff != 0:
        top = max(out, key=out.get)
        out[top] += diff
    return out


def normalize_probs(probs: Dict[str, float]) -> Dict[str, int]:
    """供 calibration 复用的归一化（clamp + 归一 + 和=100）。"""
    clamped = {k: _clamp(v) for k, v in probs.items()}
    return _normalize(clamped)


SCENARIO_CN = {
    "continuation": "顺势延续",
    "consolidation": "震荡回踩",
    "reversal": "趋势反转",
}


__all__ = [
    "CONT_BASE", "REV_BASE", "NEAR_LEVEL_PCT",
    "ATR_HORIZON_BAND", "ATR_TARGET_BAND",
    "raw_scenario_probs", "normalize_probs", "SCENARIO_CN",
]
