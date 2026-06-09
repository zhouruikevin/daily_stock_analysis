# -*- coding: utf-8 -*-
"""history.py 持久化 + 变化分析测试（离线，不触发网络）"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "index-analysis" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import history as h  # noqa: E402


# ============================================================
# Fixtures
# ============================================================
def _sample_wrapped(index_key: str = "sh",
                    index_name: str = "上证指数",
                    current_price: float = 4057.78,
                    immediate_r: float = 4059.20,
                    immediate_s: float = 4048.78,
                    macd_div: bool = False,
                    rsi_div: bool = True,
                    confidence: str = "高置信") -> dict:
    """造一个 mode=both 的 wrapped result（模拟 index_analysis 输出）"""
    return {
        "index_key": index_key,
        "divergence": {
            "index_name": index_name,
            "macd_divergence": macd_div,
            "rsi_divergence": rsi_div,
            "vol_divergence": False,
            "divergence_severity": "弱" if not macd_div else "强",
        },
        "levels": {
            "current_price": current_price,
            "resistance_levels": [
                {"value": immediate_r, "label": "MA60", "strength": "强", "types": ["ma"]},
                {"value": immediate_r + 22, "label": "Fib 0.382", "strength": "中", "types": ["fib"]},
                {"value": immediate_r + 48, "label": "整数关口+EMA20+近5日高点",
                 "strength": "强", "types": ["round_number", "ema", "extrema"]},
            ],
            "support_levels": [
                {"value": immediate_s, "label": "当日低点+整数关口+MA120",
                 "strength": "强", "types": ["today", "round_number", "ma"]},
            ],
            "immediate_resistance": immediate_r,
            "immediate_support": immediate_s,
        },
        "reversal": {
            "confidence": confidence,
            "reason": "顶背离+价格距上沿 0.03%" if confidence == "高置信" else "无",
            "distance_to_resistance_pct": 0.03 if confidence == "高置信" else None,
        },
    }


# ============================================================
# 1. snapshot 构造
# ============================================================
def test_build_index_snapshot_extracts_key_fields():
    snap = h.build_index_snapshot(_sample_wrapped())
    assert snap["index_key"] == "sh"
    assert snap["index_name"] == "上证指数"
    assert snap["current_price"] == 4057.78
    assert snap["divergence_severity"] == "弱"
    assert snap["macd_divergence"] is False
    assert snap["rsi_divergence"] is True
    assert snap["immediate_resistance"] == 4059.20
    assert snap["reversal_confidence"] == "高置信"
    assert len(snap["resistance_top3"]) == 3
    assert snap["resistance_top3"][0] == {"value": 4059.20, "label": "MA60", "strength": "强"}


def test_build_index_snapshot_skips_error():
    """divergence/levels 含 error 应返回 None，避免污染历史"""
    wrapped = {"divergence": {"error": "数据源失败"}, "levels": {}}
    assert h.build_index_snapshot(wrapped) is None


def test_build_daily_snapshot_aggregates_indices():
    wrapped_list = [
        _sample_wrapped("sh"),
        _sample_wrapped("sz", "深证成指", 15661.57, 15685.10, 15600.0),
        _sample_wrapped("cy", "创业板指", 4088.88, 4100.0, 4050.57, macd_div=True),
    ]
    snap = h.build_daily_snapshot(wrapped_list, today="2026-06-04")
    assert snap["date"] == "2026-06-04"
    assert snap["schema_version"] == h.SCHEMA_VERSION
    assert len(snap["indices"]) == 3
    assert [i["index_key"] for i in snap["indices"]] == ["sh", "sz", "cy"]
    # 创业板的 severity = 强
    assert snap["indices"][2]["divergence_severity"] == "强"


# ============================================================
# 2. 读写
# ============================================================
def test_save_daily_creates_file(tmp_path):
    snap = h.build_daily_snapshot([_sample_wrapped()], today="2026-06-04")
    target = h.save_daily(snap, history_dir=tmp_path)
    assert target == tmp_path / "2026-06-04.json"
    assert target.exists()
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["date"] == "2026-06-04"


def test_save_daily_same_day_overwrites(tmp_path):
    """同一天再写应直接覆盖文件，不留多条"""
    snap1 = h.build_daily_snapshot([_sample_wrapped(current_price=4057.78)], today="2026-06-04")
    h.save_daily(snap1, history_dir=tmp_path)
    snap2 = h.build_daily_snapshot([_sample_wrapped(current_price=4060.00)], today="2026-06-04")
    h.save_daily(snap2, history_dir=tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 1  # 只有 1 个文件
    loaded = json.loads((tmp_path / "2026-06-04.json").read_text(encoding="utf-8"))
    assert loaded["indices"][0]["current_price"] == 4060.00  # 后写的赢


def test_save_daily_atomic_no_tempfile_leftover(tmp_path):
    """正常保存完不应留下 .tmp_ 临时文件"""
    snap = h.build_daily_snapshot([_sample_wrapped()], today="2026-06-04")
    h.save_daily(snap, history_dir=tmp_path)
    leftovers = list(tmp_path.glob(".tmp_*"))
    assert leftovers == []


def test_load_recent_returns_in_date_order(tmp_path):
    for date in ["2026-06-04", "2026-06-02", "2026-06-03", "2026-06-01"]:
        snap = h.build_daily_snapshot([_sample_wrapped()], today=date)
        h.save_daily(snap, history_dir=tmp_path)
    recent = h.load_recent(days=10, history_dir=tmp_path)
    assert [s["date"] for s in recent] == ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]


def test_load_recent_takes_last_n(tmp_path):
    for date in ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]:
        snap = h.build_daily_snapshot([_sample_wrapped()], today=date)
        h.save_daily(snap, history_dir=tmp_path)
    recent = h.load_recent(days=3, history_dir=tmp_path)
    assert [s["date"] for s in recent] == ["2026-06-03", "2026-06-04", "2026-06-05"]


def test_load_recent_empty_when_no_dir(tmp_path):
    nonexistent = tmp_path / "no-such"
    assert h.load_recent(days=10, history_dir=nonexistent) == []


def test_load_recent_skips_corrupted_files(tmp_path):
    """损坏的 JSON 应被跳过不抛"""
    snap = h.build_daily_snapshot([_sample_wrapped()], today="2026-06-04")
    h.save_daily(snap, history_dir=tmp_path)
    (tmp_path / "2026-06-03.json").write_text("{ broken json", encoding="utf-8")
    recent = h.load_recent(days=10, history_dir=tmp_path)
    assert len(recent) == 1
    assert recent[0]["date"] == "2026-06-04"


def test_load_recent_skips_unknown_schema(tmp_path):
    """schema_version 不匹配的文件应被跳过"""
    bad = {"schema_version": 999, "date": "2026-06-04", "indices": []}
    (tmp_path / "2026-06-04.json").write_text(json.dumps(bad), encoding="utf-8")
    assert h.load_recent(days=10, history_dir=tmp_path) == []


# ============================================================
# 3. 变化分析格式化
# ============================================================
def test_format_history_table_empty():
    out = h.format_history_table([])
    assert "历史为空" in out


def test_format_history_table_renders_dates_in_order():
    snaps = [
        h.build_daily_snapshot([_sample_wrapped(current_price=4083.97, immediate_r=4107.22)],
                               today="2026-06-02"),
        h.build_daily_snapshot([_sample_wrapped(current_price=4075.10, immediate_r=4083.97)],
                               today="2026-06-03"),
        h.build_daily_snapshot([_sample_wrapped(current_price=4057.78, immediate_r=4059.20)],
                               today="2026-06-04"),
    ]
    out = h.format_history_table(snaps)
    # 3 个日期都在
    for d in ["2026-06-02", "2026-06-03", "2026-06-04"]:
        assert d in out
    # 标题反映天数
    assert "近 3 个交易日" in out


def test_format_history_table_persistent_levels():
    """连续出现的阻力位应在『持续阻力位』段被点名"""
    snaps = [
        h.build_daily_snapshot(
            [_sample_wrapped(immediate_r=4107.0)], today=f"2026-06-{d:02d}")
        for d in [1, 2, 3, 4]
    ]
    out = h.format_history_table(snaps)
    assert "持续阻力位" in out
    # 4 天里都出现的 4107 应在持续位列表
    assert "4107" in out


def test_format_history_table_key_transition():
    """immediate_resistance 跨天明显变化（>0.05%）应输出『关键转换』"""
    snaps = [
        h.build_daily_snapshot([_sample_wrapped(immediate_r=4107.22)],
                               today="2026-06-03"),
        h.build_daily_snapshot([_sample_wrapped(immediate_r=4059.20)],
                               today="2026-06-04"),
    ]
    out = h.format_history_table(snaps)
    assert "关键转换" in out
    assert "下移" in out


def test_format_history_table_filters_by_index_keys():
    """指定 index_keys 时只输出对应指数"""
    wrapped_list = [
        _sample_wrapped("sh", "上证指数"),
        _sample_wrapped("cy", "创业板指", 4088.88, 4100.0, 4050.57),
    ]
    snap = h.build_daily_snapshot(wrapped_list, today="2026-06-04")
    out = h.format_history_table([snap], index_keys=["sh"])
    assert "上证指数" in out
    assert "创业板指" not in out
