#!/usr/bin/env python3
"""历史数据校准 —— "用已发生的数据修正后面的答案"。

读预测台账，统计该指数的历史表现（近期指数加权），对 forecast 的**原始**输出
做**有界 + 收缩式**修正：
- 收缩权重 w = n/(n+K)：样本少 → w→0 → 几乎不改（冷启动安全）；样本多 → 更信数据。
- 概率校准：把每个情景概率朝其历史实际兑现率移动（cap ±15），再归一化。
- 目标纠偏：按历史系统性偏差平移目标区间（cap ±2%）。
- 带宽自适应：历史覆盖率不足 → 适度放宽目标区间（cap 1.5×）。

全部修正在返回的 meta 里列明，保证透明可审计；样本不足时自动跳过。
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

import scoring

K_SHRINK = 20          # 收缩常数：样本达到 K 时数据与先验各半
DECAY = 0.97           # 近期样本指数加权衰减
MIN_BUCKET = 5         # 单情景类型至少样本数才用其兑现率
PROB_ADJ_CAP = 15.0    # 单情景概率修正上限
BIAS_SHIFT_CAP = 0.02  # 目标平移上限（±2%）
WIDEN_CAP = 1.5        # 带宽放大上限
COVERAGE_TARGET = 70.0


def load_stats(records: List[Dict[str, Any]], index_key: str) -> Dict[str, Any]:
    """聚合该指数历史表现（近期加权）。返回 stats dict。"""
    recs = [r for r in records
            if r.get("index_key") == index_key and r.get("outcome_horizon")]
    n = len(recs)
    if n == 0:
        return {"n": 0, "per_type": {}, "bias_pct": None, "coverage": None}

    # 近期加权：最新的权重最高
    weighted = []
    for age, r in enumerate(reversed(recs)):
        weighted.append((DECAY ** age, r))

    per_type: Dict[str, Dict[str, float]] = {}
    for w, r in weighted:
        primary = r.get("primary") or {}
        t = primary.get("scenario")
        p = primary.get("probability")
        oh = r.get("outcome_horizon") or {}
        hit = oh.get("primary_hit")
        if t is None or p is None:
            continue
        d = per_type.setdefault(t, {"wsum": 0.0, "claimed": 0.0, "hits": 0.0, "hitw": 0.0, "n": 0})
        d["wsum"] += w
        d["claimed"] += w * p
        d["n"] += 1
        if hit is not None:
            d["hitw"] += w
            d["hits"] += w * (1.0 if hit else 0.0)

    per_type_out = {}
    for t, d in per_type.items():
        per_type_out[t] = {
            "n": int(d["n"]),
            "claimed_avg": round(d["claimed"] / d["wsum"], 1) if d["wsum"] else None,
            "hit_rate": round(d["hits"] / d["hitw"] * 100, 1) if d["hitw"] else None,
        }

    # 目标偏差 / 覆盖率（近期加权）
    bias_num = bias_den = 0.0
    cov_num = cov_den = 0.0
    for w, r in weighted:
        oh = r.get("outcome_horizon") or {}
        err = oh.get("err_pct")
        if err is not None:
            bias_num += w * err
            bias_den += w
        cov = oh.get("in_target_range")
        if cov is not None:
            cov_num += w * (1.0 if cov else 0.0)
            cov_den += w

    return {
        "n": n,
        "per_type": per_type_out,
        "bias_pct": round(bias_num / bias_den, 3) if bias_den else None,
        "coverage": round(cov_num / cov_den * 100, 1) if cov_den else None,
    }


def apply(raw_forecast: Dict[str, Any], stats: Dict[str, Any]) -> Dict[str, Any]:
    """对原始 forecast 应用校准，返回 (calibrated_forecast, meta)。原始不被改动。"""
    meta: Dict[str, Any] = {"n_samples": stats.get("n", 0), "applied": False,
                            "prob_adjust": {}, "bias_shift_pct": 0.0, "widen_factor": 1.0}
    n = stats.get("n", 0)
    if n == 0:
        return copy.deepcopy(raw_forecast), meta

    fc = copy.deepcopy(raw_forecast)
    w = n / (n + K_SHRINK)
    meta["shrink_w"] = round(w, 3)
    per_type = stats.get("per_type", {})

    # 1. 概率校准：每个情景朝其历史兑现率移动
    new_probs: Dict[str, float] = {}
    for s in fc["scenarios"]:
        t = s["type"]
        p = float(s["probability"])
        pt = per_type.get(t)
        if pt and pt["n"] >= MIN_BUCKET and pt["hit_rate"] is not None:
            raw_adj = w * (pt["hit_rate"] - p)
            adj = max(-PROB_ADJ_CAP, min(PROB_ADJ_CAP, raw_adj))
            new_probs[t] = p + adj
            meta["prob_adjust"][t] = round(adj, 1)
        else:
            new_probs[t] = p
    normalized = scoring.normalize_probs(new_probs)
    for s in fc["scenarios"]:
        s["probability"] = normalized[s["type"]]

    # 2. 目标纠偏：历史系统性偏差（+偏高）→ 目标整体下移
    bias = stats.get("bias_pct")
    if bias is not None and abs(bias) > 0.05:
        shift = max(-BIAS_SHIFT_CAP, min(BIAS_SHIFT_CAP, w * bias / 100.0))
        meta["bias_shift_pct"] = round(shift * 100, 3)
        for s in fc["scenarios"]:
            _shift_range(s.get("target_range"), -shift)
        _shift_range(fc.get("expected_range"), -shift)

    # 3. 带宽自适应：覆盖率不足 → 放宽目标区间
    cov = stats.get("coverage")
    if cov is not None and cov < COVERAGE_TARGET:
        factor = min(WIDEN_CAP, 1.0 + w * 0.5)
        meta["widen_factor"] = round(factor, 3)
        for s in fc["scenarios"]:
            _widen_range(s.get("target_range"), factor)
        _widen_range(fc.get("expected_range"), factor)

    # 重算主情景 + 信号
    primary = max(fc["scenarios"], key=lambda s: s["probability"])
    fc["primary_scenario"] = primary["type"]
    meta["applied"] = True
    return fc, meta


def _shift_range(rng: Optional[Dict[str, float]], shift: float) -> None:
    if not rng:
        return
    rng["low"] = round(rng["low"] * (1 + shift), 2)
    rng["high"] = round(rng["high"] * (1 + shift), 2)


def _widen_range(rng: Optional[Dict[str, float]], factor: float) -> None:
    if not rng:
        return
    mid = (rng["low"] + rng["high"]) / 2
    half = (rng["high"] - rng["low"]) / 2 * factor
    rng["low"] = round(mid - half, 2)
    rng["high"] = round(mid + half, 2)


__all__ = ["load_stats", "apply"]
