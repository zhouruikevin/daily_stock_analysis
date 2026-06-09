# -*- coding: utf-8 -*-
"""key_levels.compute_key_levels 离线单测（不依赖网络）。

测试策略：
- 用确定性造数 _sample_df，每根 close = 基线 + 小扰动，方便精确算 MA/BOLL
- 整数关口、Fib、合并这些纯算法直接喂构造数据验证边界
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# 把 skill scripts/ 加进 path 以便 import key_levels
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "index-analysis" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import key_levels as kl  # noqa: E402


# ============================================================
# Fixtures
# ============================================================
def _sample_df(rows: int = 260, base: float = 4000.0,
               drift: float = 0.2, amp: float = 5.0) -> pd.DataFrame:
    """造一段确定性的日线：close 线性增 + 小幅 sin 波动；high=close+5、low=close-5。

    rows=260 足够算 MA250。最后一日 close ≈ base + (rows-1)*drift。
    """
    dates = pd.date_range("2025-01-01", periods=rows, freq="D").astype(str).tolist()
    close = np.array([base + i * drift + amp * math.sin(i / 3.0) for i in range(rows)])
    return pd.DataFrame({
        "date": dates,
        "open": close - 1.0,
        "high": close + 5.0,
        "low": close - 5.0,
        "close": close,
        "volume": np.full(rows, 1e9),
        "amount": np.full(rows, 1e10),
    })


# ============================================================
# 1. 候选生成器
# ============================================================
def test_ma_candidates_generated():
    """MA20/60/120/250 都应出现且数值与 pandas rolling().mean() 一致。"""
    df = _sample_df(rows=260)
    cands = kl._ma_candidates(df)
    labels = [c["label"] for c in cands]
    assert labels == ["MA20", "MA60", "MA120", "MA250"]
    # 数值校验
    for c, period in zip(cands, [20, 60, 120, 250]):
        expected = float(df["close"].rolling(period).mean().iloc[-1])
        assert c["value"] == pytest.approx(expected)
    # 强度分级
    strengths = {c["label"]: c["strength"] for c in cands}
    assert strengths["MA20"] == "中"
    assert strengths["MA60"] == "强"
    assert strengths["MA120"] == "强"
    assert strengths["MA250"] == "强"


def test_ma_candidates_skip_when_history_too_short():
    """历史不足 MA250 时只输出可算的，不应崩溃。"""
    df = _sample_df(rows=100)
    cands = kl._ma_candidates(df)
    labels = [c["label"] for c in cands]
    assert "MA20" in labels and "MA60" in labels
    assert "MA250" not in labels  # 算不出


def test_boll_bounds_match_formula():
    """BOLL 上下轨 = MA20 ± 2 * std(close, 20, ddof=0)。"""
    df = _sample_df(rows=100)
    cands = kl._boll_candidates(df)
    assert len(cands) == 2
    ma = df["close"].rolling(20).mean().iloc[-1]
    std = df["close"].rolling(20).std(ddof=0).iloc[-1]
    upper_expected = float(ma + 2 * std)
    lower_expected = float(ma - 2 * std)
    upper = next(c for c in cands if c["label"] == "BOLL上轨")
    lower = next(c for c in cands if c["label"] == "BOLL下轨")
    assert upper["value"] == pytest.approx(upper_expected)
    assert lower["value"] == pytest.approx(lower_expected)
    assert upper["strength"] == "弱"


# ============================================================
# 2. 整数关口
# ============================================================
@pytest.mark.parametrize("price, must_contain", [
    (4057.78, [4100.0, 4050.0, 4000.0]),  # 1k~5k 量级 → step=50 + big_step=500，含 4500 也可
    (3850.0, [3900.0, 3800.0, 4000.0]),   # 1k~5k → step=50；3850 正好整 50 → up==down，但有大整数
    (250.0, [260.0, 240.0, 300.0, 200.0]),  # 100~1k → step=10、big_step=100
    (50.0, [51.0, 49.0, 60.0, 40.0]),     # <100 → step=1、big_step=10；price=50 落整 → 输出 ±1 和 ±10
])
def test_round_number_quantization(price, must_contain):
    cands = kl._round_number_candidates(price)
    values = {c["value"] for c in cands}
    for v in must_contain:
        if v == price:
            # 价格落整数关口上时，普通 step 跳过，但大 step 仍可能加入
            continue
        assert v in values, f"price={price} 应该含整数关口 {v}，实际 {values}"
    for c in cands:
        assert c["strength"] == "强"


def test_round_number_price_equal_threshold_no_duplicate():
    """price 正好落在 step 整数倍上时不应该重复输出同一个值。"""
    cands = kl._round_number_candidates(4000.0)
    values = [c["value"] for c in cands]
    assert values.count(4000.0) == 0  # 跳过和当前价相等的


# ============================================================
# 3. Fib
# ============================================================
def test_fib_levels_anchored_to_lookback_extrema():
    """给定 lookback 段内 high=110、low=100，Fib 5 位 = high - r*range。"""
    df = pd.DataFrame({
        "date": [f"2026-06-{i+1:02d}" for i in range(10)],
        "open": [100.0] * 10,
        "high": [100, 102, 105, 108, 110, 109, 107, 106, 105, 104],
        "low":  [100, 101, 103, 105, 108, 107, 105, 104, 102, 100],
        "close": [101, 103, 104, 107, 109, 108, 106, 105, 104, 102],
        "volume": [1e9] * 10,
    })
    cands = kl._fib_candidates(df, lookback=10)
    by_label = {c["label"]: c["value"] for c in cands}
    high, low = 110.0, 100.0
    rng = high - low
    expected = {
        "Fib 0.236": high - 0.236 * rng,
        "Fib 0.382": high - 0.382 * rng,
        "Fib 0.5":   high - 0.5 * rng,
        "Fib 0.618": high - 0.618 * rng,
        "Fib 0.786": high - 0.786 * rng,
    }
    for label, val in expected.items():
        assert by_label[label] == pytest.approx(val)


def test_fib_no_range_returns_empty():
    """high == low 时（极端无波动）返回空。"""
    df = pd.DataFrame({
        "date": ["2026-06-01"] * 5,
        "open": [100.0] * 5, "high": [100.0] * 5,
        "low": [100.0] * 5, "close": [100.0] * 5,
    })
    assert kl._fib_candidates(df, lookback=5) == []


# ============================================================
# 4. 距离过滤 / 排序 / 截断
# ============================================================
def test_distance_window_filter():
    """band_window_pct=1 时，超出 ±1% 的位被过滤。"""
    df = _sample_df(rows=260)
    current = float(df["close"].iloc[-1])
    out = kl.compute_key_levels(df, current, band_window_pct=1.0, band_limit=99)
    for lvl in out["resistance_levels"] + out["support_levels"]:
        assert abs(lvl["value"] - current) / current * 100 <= 1.0 + 1e-6


def test_levels_sorted_by_distance():
    """上沿从近到远递增、下沿从近到远递减。"""
    df = _sample_df(rows=260)
    current = float(df["close"].iloc[-1])
    out = kl.compute_key_levels(df, current, band_window_pct=5.0, band_limit=99)
    res_values = [lvl["value"] for lvl in out["resistance_levels"]]
    sup_values = [lvl["value"] for lvl in out["support_levels"]]
    assert res_values == sorted(res_values)
    assert sup_values == sorted(sup_values, reverse=True)


def test_band_limit_truncates():
    """band_limit=3 时上下沿各最多 3 条。"""
    df = _sample_df(rows=260)
    current = float(df["close"].iloc[-1])
    out = kl.compute_key_levels(df, current, band_window_pct=10.0, band_limit=3)
    assert len(out["resistance_levels"]) <= 3
    assert len(out["support_levels"]) <= 3


def test_immediate_pointers_match_first_entry():
    """immediate_resistance == resistance_levels[0]['value']。"""
    df = _sample_df(rows=260)
    current = float(df["close"].iloc[-1])
    out = kl.compute_key_levels(df, current, band_window_pct=5.0)
    if out["resistance_levels"]:
        assert out["immediate_resistance"] == out["resistance_levels"][0]["value"]
    if out["support_levels"]:
        assert out["immediate_support"] == out["support_levels"][0]["value"]


# ============================================================
# 5. 合并相近
# ============================================================
def test_merge_nearby_keeps_strongest():
    """MA120=4049.51 + 整数 4050.00 在 0.3% 内合并，强度取强、types 合并。"""
    items = [
        {"value": 4049.51, "label": "MA120", "strength": "强", "types": ["ma"]},
        {"value": 4050.00, "label": "整数关口", "strength": "强", "types": ["round_number"]},
        {"value": 4071.45, "label": "BOLL上轨", "strength": "弱", "types": ["boll"]},
    ]
    out = kl._merge_nearby(items, merge_tol_pct=0.3)
    # 4049.51 和 4050.00 距离 ~0.012%，应合并
    merged_low = [m for m in out if abs(m["value"] - 4049.75) < 0.5]
    assert len(merged_low) == 1
    m = merged_low[0]
    assert m["strength"] == "强"
    assert set(m["types"]) == {"ma", "round_number"}
    assert "MA120" in m["label"] and "整数关口" in m["label"]
    # BOLL 上轨距离远，应独立保留
    boll = [m for m in out if abs(m["value"] - 4071.45) < 0.5]
    assert len(boll) == 1
    assert boll[0]["strength"] == "弱"


def test_merge_nearby_strength_upgrade():
    """弱 + 强 合并时强度应升级为强。"""
    items = [
        {"value": 100.0, "label": "BOLL上轨", "strength": "弱", "types": ["boll"]},
        {"value": 100.1, "label": "MA60", "strength": "强", "types": ["ma"]},
    ]
    out = kl._merge_nearby(items, merge_tol_pct=0.3)
    assert len(out) == 1
    assert out[0]["strength"] == "强"


# ============================================================
# 6. 边界
# ============================================================
def test_empty_history_returns_empty_levels():
    df = pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    out = kl.compute_key_levels(df, 100.0)
    assert out["resistance_levels"] == []
    assert out["support_levels"] == []
    assert out["immediate_resistance"] is None
    assert out["immediate_support"] is None


def test_zero_current_price_returns_empty():
    df = _sample_df(rows=50)
    out = kl.compute_key_levels(df, 0.0)
    assert out["resistance_levels"] == []
    assert out["support_levels"] == []


def test_extrema_excludes_today():
    """当日 high/low 不应被 _extrema_candidates 算进"近 N 日"，避免重复。"""
    # 造数：让最后一天的 high 是全局最高
    df = _sample_df(rows=30)
    df.loc[df.index[-1], "high"] = 9999.0
    extrema = kl._extrema_candidates(df)
    # "近5/20日高点" 不应等于 9999
    for c in extrema:
        if "高点" in c["label"]:
            assert c["value"] != 9999.0


def test_output_schema_has_all_keys():
    """输出 dict 应包含所有约定 key。"""
    df = _sample_df(rows=100)
    out = kl.compute_key_levels(df, float(df["close"].iloc[-1]))
    required = {"current_price", "resistance_levels", "support_levels",
                "immediate_resistance", "immediate_support", "all_candidates_count"}
    assert required.issubset(out.keys())
