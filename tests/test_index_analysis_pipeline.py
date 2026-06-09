# -*- coding: utf-8 -*-
"""index-analysis skill 的联动评估 + manager 接入测试（离线）。

不触发网络：
- assess_reversal 直接喂 mock dict
- analyze_levels 用 monkeypatch 替换 _get_manager 返回 stub
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "index-analysis" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# 注意：index_analysis 顶层 import data_provider —— 在仓库根跑时正常
import index_analysis as ind  # noqa: E402


# ============================================================
# assess_reversal: 三档置信
# ============================================================
def _div(macd: bool = False, rsi: bool = False, vol: bool = False) -> dict:
    return {"macd_divergence": macd, "rsi_divergence": rsi, "vol_divergence": vol,
            "divergence_severity": "强" if macd and rsi else ("中" if macd else "无")}


def _lev(current: float, immediate_r: float) -> dict:
    return {"current_price": current, "immediate_resistance": immediate_r,
            "immediate_support": current * 0.99}


def test_high_confidence_when_div_and_near_resistance():
    """有顶背离 + 价格距上沿 0.3% → 高置信"""
    div = _div(macd=True)
    lev = _lev(current=4057.78, immediate_r=4070.0)  # 距离 ~0.30%
    rev = ind.assess_reversal(div, lev, near_pct=0.5)
    assert rev["confidence"] == "高置信"
    assert "顶背离" in rev["reason"]
    assert rev["distance_to_resistance_pct"] == pytest.approx(0.30, abs=0.05)


def test_mid_confidence_when_only_divergence():
    """有顶背离但距上沿 1.8% → 中置信"""
    div = _div(rsi=True)
    lev = _lev(current=4057.78, immediate_r=4130.0)  # 距离 ~1.78%
    rev = ind.assess_reversal(div, lev, near_pct=0.5)
    assert rev["confidence"] == "中置信"
    assert "仅顶背离" in rev["reason"]


def test_mid_confidence_when_only_near_resistance():
    """无顶背离但价格撞上沿 → 中置信"""
    div = _div()  # 无任何背离
    lev = _lev(current=4057.78, immediate_r=4070.0)  # 距离 ~0.30%
    rev = ind.assess_reversal(div, lev, near_pct=0.5)
    assert rev["confidence"] == "中置信"
    assert "撞上沿" in rev["reason"]


def test_no_confidence_when_neither():
    """无背离 + 距上沿 5% → 无"""
    div = _div()
    lev = _lev(current=4057.78, immediate_r=4260.0)
    rev = ind.assess_reversal(div, lev, near_pct=0.5)
    assert rev["confidence"] == "无"


def test_vol_divergence_alone_not_high_confidence():
    """量价背离单独不算顶背离信号（太弱）"""
    div = _div(vol=True)  # 只有量价背离
    lev = _lev(current=4057.78, immediate_r=4070.0)
    rev = ind.assess_reversal(div, lev, near_pct=0.5)
    # 价格撞上沿仍是中置信，但理由应是"撞上沿"不是"顶背离"
    assert rev["confidence"] == "中置信"
    assert "撞上沿" in rev["reason"]
    assert "顶背离" not in rev["reason"]


def test_no_immediate_resistance_falls_back_gracefully():
    """上沿为空时不应崩溃"""
    div = _div(macd=True)
    lev = {"current_price": 100.0, "immediate_resistance": None,
           "immediate_support": 99.0}
    rev = ind.assess_reversal(div, lev)
    assert rev["confidence"] == "中置信"  # 有背离但没法判断距离
    assert rev["distance_to_resistance_pct"] is None


# ============================================================
# analyze_levels 走 manager + include_today=True
# ============================================================
class _StubManager:
    """记录 get_index_daily 的调用参数，可注入返回值。"""

    def __init__(self, df: pd.DataFrame):
        self._df = df
        self.calls = []

    def get_index_daily(self, symbol, start_date=None, end_date=None, include_today=True):
        self.calls.append({"symbol": symbol, "start_date": start_date,
                           "end_date": end_date, "include_today": include_today})
        return self._df


def _fake_index_df(rows: int = 260) -> pd.DataFrame:
    dates = pd.date_range("2025-06-01", periods=rows, freq="D").astype(str).tolist()
    close = np.array([4000.0 + i * 0.2 for i in range(rows)])
    return pd.DataFrame({
        "date": dates,
        "open": close - 1.0,
        "high": close + 5.0,
        "low": close - 5.0,
        "close": close,
        "volume": np.full(rows, 1e9),
        "amount": np.full(rows, 1e10),
    })


def test_analyze_levels_uses_manager_with_include_today(monkeypatch):
    """analyze_levels 应通过 _get_manager 调用 get_index_daily，且 include_today=True"""
    stub = _StubManager(_fake_index_df())
    monkeypatch.setattr(ind, "_get_manager", lambda: stub)

    result = ind.analyze_levels("sh", history_days=260, band_window_pct=2.0)

    assert len(stub.calls) == 1
    assert stub.calls[0]["symbol"] == "sh000001"
    assert stub.calls[0]["include_today"] is True
    # 关键输出字段都在
    assert result["index_key"] == "sh"
    assert result["index_name"] == "上证指数"
    assert "current_price" in result
    assert "resistance_levels" in result
    assert "support_levels" in result
    assert "immediate_resistance" in result
    assert "as_of" in result


def test_analyze_levels_returns_error_on_empty(monkeypatch):
    """manager 返回空 → 返回 error dict 而不是崩溃"""
    stub = _StubManager(pd.DataFrame())
    monkeypatch.setattr(ind, "_get_manager", lambda: stub)
    result = ind.analyze_levels("sh")
    assert "error" in result
    assert "无法获取" in result["error"]


def test_analyze_levels_passes_band_args_to_compute(monkeypatch):
    """band_window_pct / band_limit 应被传给 compute_key_levels"""
    stub = _StubManager(_fake_index_df())
    monkeypatch.setattr(ind, "_get_manager", lambda: stub)
    result = ind.analyze_levels("sh", band_window_pct=1.0, band_limit=2)
    # 上下沿应被裁到 1% 以内
    current = result["current_price"]
    for lvl in result["resistance_levels"] + result["support_levels"]:
        assert abs(lvl["value"] - current) / current * 100 <= 1.0 + 1e-6
    # 截断到 2 条以内
    assert len(result["resistance_levels"]) <= 2
    assert len(result["support_levels"]) <= 2


# ============================================================
# compute_divergence_score: 评分纯函数
# ============================================================
def test_score_zero_when_no_divergence():
    """无任何背离 → 评分 0"""
    assert ind.compute_divergence_score(False, False, False, "无") == 0


def test_score_macd_only():
    """仅 MACD 顶背离，severity=中 → 40"""
    assert ind.compute_divergence_score(True, False, False, "中") == 40


def test_score_strong_dual_divergence():
    """MACD+RSI 双重背离，severity=强 → 40+30+15=85"""
    assert ind.compute_divergence_score(True, True, False, "强") == 85


def test_score_all_divergence_with_high_confidence():
    """三重背离 + 共振 + 高置信微调 → 100 (cap)"""
    raw = 40 + 30 + 15 + 15  # =100
    assert ind.compute_divergence_score(True, True, True, "强", "高置信") == 100


def test_score_no_confidence_penalty():
    """RSI+量价背离，severity=强，反转置信=无 → 30+15+15-5=55"""
    assert ind.compute_divergence_score(False, True, True, "强", "无") == 55


def test_score_to_level_mapping():
    """评分 → 风险等级映射"""
    assert ind.score_to_level(0) == "无信号"
    assert ind.score_to_level(14) == "无信号"
    assert ind.score_to_level(15) == "低风险"
    assert ind.score_to_level(44) == "低风险"
    assert ind.score_to_level(45) == "中风险"
    assert ind.score_to_level(69) == "中风险"
    assert ind.score_to_level(70) == "高风险"
    assert ind.score_to_level(100) == "高风险"


def test_assess_reversal_includes_divergence_score():
    """assess_reversal 返回 dict 应包含 divergence_score 字段"""
    div = _div(macd=True, rsi=True)
    div["vol_divergence"] = True
    div["divergence_severity"] = "强"
    lev = _lev(current=4057.78, immediate_r=4070.0)
    rev = ind.assess_reversal(div, lev, near_pct=0.5)
    assert "divergence_score" in rev
    # MACD(40)+RSI(30)+VOL(15)+共振(15)+高置信(+5) = 100(capped)
    assert rev["divergence_score"] == 100
