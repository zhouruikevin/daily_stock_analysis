#!/usr/bin/env python3
"""每日指数分析历史持久化 + 变化对比。

存储约定：
- 目录: skills/index-analysis/history/{YYYY-MM-DD}.json
- 同一天多次跑 → 覆盖（用 tempfile + os.replace 原子写，避免半截文件）
- 不入库（.gitignore），是个人复盘数据
- schema_version=1，未来扩字段时加载侧容忍未知字段

每日 snapshot 形态（精简结论，约 2 KB/天）：
{
  "schema_version": 1,
  "date": "2026-06-04",
  "as_of": "2026-06-04T19:42:31+08:00",
  "indices": [
    {
      "index_key": "sh",
      "index_name": "上证指数",
      "current_price": 4057.78,
      "divergence_severity": "弱",
      "macd_divergence": false,
      "rsi_divergence": true,
      "resistance_top3": [{"value": ..., "label": ..., "strength": ...}, ...],
      "support_top3":    [...],
      "immediate_resistance": 4059.2,
      "immediate_support": 4048.78,
      "reversal_confidence": "高置信",
      "reversal_reason": "顶背离+价格距上沿 0.03%",
      "distance_to_resistance_pct": 0.03
    }
  ]
}
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# 默认目录：脚本同级 ../history/
_DEFAULT_HISTORY_DIR = Path(__file__).resolve().parent.parent / "history"

SCHEMA_VERSION = 1


# ============================================================
# 工具：从一次 wrapped result 抽取精简 snapshot
# ============================================================
def _topn_brief(levels: List[Dict[str, Any]], n: int = 3) -> List[Dict[str, Any]]:
    """只保留 value/label/strength 三个字段，去掉 types/distance_pct 等冗余。"""
    out = []
    for lv in levels[:n]:
        out.append({
            "value": lv.get("value"),
            "label": lv.get("label"),
            "strength": lv.get("strength"),
        })
    return out


def build_index_snapshot(wrapped: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 mode=both 单条 wrapped (含 divergence/levels/reversal) 抽出精简 snapshot。

    返回 None 如果数据残缺（比如 divergence error）。
    """
    div = wrapped.get("divergence") or {}
    lev = wrapped.get("levels") or {}
    rev = wrapped.get("reversal") or {}
    if div.get("error") or lev.get("error"):
        return None
    return {
        "index_key": wrapped.get("index_key") or div.get("index_key"),
        "index_name": div.get("index_name") or lev.get("index_name"),
        "current_price": lev.get("current_price"),
        "divergence_severity": div.get("divergence_severity"),
        "macd_divergence": bool(div.get("macd_divergence")),
        "rsi_divergence": bool(div.get("rsi_divergence")),
        "vol_divergence": bool(div.get("vol_divergence")),
        "resistance_top3": _topn_brief(lev.get("resistance_levels", []), 3),
        "support_top3": _topn_brief(lev.get("support_levels", []), 3),
        "immediate_resistance": lev.get("immediate_resistance"),
        "immediate_support": lev.get("immediate_support"),
        "reversal_confidence": rev.get("confidence"),
        "reversal_reason": rev.get("reason"),
        "distance_to_resistance_pct": rev.get("distance_to_resistance_pct"),
        "divergence_score": rev.get("divergence_score"),
    }


def build_daily_snapshot(wrapped_results: List[Dict[str, Any]],
                         today: Optional[str] = None) -> Dict[str, Any]:
    """构造一份完整的每日 snapshot。"""
    if today is None:
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
    snap_indices = []
    for w in wrapped_results:
        s = build_index_snapshot(w)
        if s is not None:
            snap_indices.append(s)
    return {
        "schema_version": SCHEMA_VERSION,
        "date": today,
        "as_of": datetime.now().astimezone().isoformat(timespec="seconds"),
        "indices": snap_indices,
    }


# ============================================================
# 读写
# ============================================================
def save_daily(snapshot: Dict[str, Any],
               history_dir: Optional[Path] = None) -> Path:
    """原子写入 history/{date}.json。同日存在则覆盖。

    Why 原子写：进程中途被杀也不会留半截文件 → 加载侧拿到的要么是旧版要么是新版。
    """
    history_dir = Path(history_dir) if history_dir else _DEFAULT_HISTORY_DIR
    history_dir.mkdir(parents=True, exist_ok=True)
    target = history_dir / f"{snapshot['date']}.json"

    # tempfile 在同目录，避免跨设备 rename 失败
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=history_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, target)  # 原子
    except Exception:
        # 清理临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return target


def load_recent(days: int = 10,
                history_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """按文件名字典序拿最近 N 个 snapshot（自动等价于"最近 N 个有数据的日期"）。

    跳过解析失败的文件（比如未来 schema_version 不兼容），只忽略不抛。
    返回按日期升序。
    """
    history_dir = Path(history_dir) if history_dir else _DEFAULT_HISTORY_DIR
    if not history_dir.exists():
        return []
    files = sorted(p for p in history_dir.glob("*.json") if p.is_file())
    files = files[-days:]
    out: List[Dict[str, Any]] = []
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION:
                out.append(data)
        except (json.JSONDecodeError, OSError):
            continue  # 损坏的 / 不可读的文件静默跳过
    return out


# ============================================================
# 变化分析 + 格式化
# ============================================================
def _per_index_series(snapshots: List[Dict[str, Any]],
                      index_key: str) -> List[Dict[str, Any]]:
    """从多日 snapshot 抽某个指数的时间序列。"""
    out = []
    for snap in snapshots:
        for idx in snap.get("indices", []):
            if idx.get("index_key") == index_key:
                out.append({"date": snap["date"], **idx})
                break
    return out


def _level_occurrence(series: List[Dict[str, Any]],
                      band: str = "resistance",
                      tol_pct: float = 0.3) -> List[Dict[str, Any]]:
    """统计某个价位在 series 里出现的天数（用于"持续阻力位"判断）。

    把 ±tol_pct% 内的价位视为同一个，按出现频次降序返回 top。
    """
    key = "resistance_top3" if band == "resistance" else "support_top3"
    buckets: List[Dict[str, Any]] = []
    for day in series:
        for lv in day.get(key, []):
            val = lv.get("value")
            if val is None:
                continue
            # 找已有 bucket
            matched = None
            for b in buckets:
                if abs(val - b["repr_value"]) / max(b["repr_value"], 1e-9) * 100 <= tol_pct:
                    matched = b
                    break
            if matched:
                matched["dates"].add(day["date"])
                matched["labels"].add(lv.get("label", ""))
                # 代表值不随后续小幅漂移：tol 已合并相近位，再算均值反而失真
                # （比如 4107.22 出现 3 次 + 4101.20 出现 1 次，应保留 4107.22 而非 4104.21）
            else:
                buckets.append({
                    "repr_value": float(val),
                    "dates": {day["date"]},
                    "labels": {lv.get("label", "")},
                })
    # 按出现天数降序
    buckets.sort(key=lambda b: (-len(b["dates"]), -b["repr_value"]))
    return buckets


def format_history_table(snapshots: List[Dict[str, Any]],
                         index_keys: Optional[List[str]] = None) -> str:
    """格式化变化对比表：每个指数一段，含每日关键字段 + 持续阻力位汇总。"""
    if not snapshots:
        return "  （历史为空，今天是第一次跑；明天再跑就有变化对比了）"

    if index_keys is None:
        # 从最新一天的 indices 抽
        index_keys = [i["index_key"] for i in snapshots[-1].get("indices", [])]

    n_days = len(snapshots)
    lines: List[str] = []
    lines.append(f"\n{'='*78}")
    lines.append(f"  关键位 × 反转置信  近 {n_days} 个交易日变化")
    lines.append(f"{'='*78}")

    for k in index_keys:
        series = _per_index_series(snapshots, k)
        if not series:
            continue
        name = series[-1].get("index_name", k)
        lines.append(f"\n  ===== {name} =====")
        lines.append(f"  {'日期':<12} {'当前价':<10} {'评分':<14} {'立即阻力':<10} "
                     f"{'阻力 label':<28} {'距阻力':<7} {'反转置信':<8}")
        lines.append(f"  {'-'*102}")
        _prev_score = None
        for day in series:
            ir = day.get("immediate_resistance")
            ir_str = f"{ir:g}" if ir is not None else "-"
            # 找 immediate_resistance 对应的 label（top3 第一条）
            top3 = day.get("resistance_top3", [])
            ir_label = top3[0].get("label", "") if top3 else ""
            dist = day.get("distance_to_resistance_pct")
            dist_str = f"{dist:.2f}%" if dist is not None else "-"
            cp = day.get("current_price")
            cp_str = f"{cp:g}" if cp is not None else "-"
            # 评分列
            sc = day.get("divergence_score")
            if sc is not None:
                change = ""
                if _prev_score is not None:
                    diff = sc - _prev_score
                    change = f"({diff:+d})" if diff else "(=)"
                score_str = f"{sc}分{change}"
                _prev_score = sc
            else:
                score_str = "-"
            lines.append(
                f"  {day['date']:<12} {cp_str:<10} {score_str:<14} {ir_str:<10} "
                f"{ir_label[:26]:<28} {dist_str:<7} "
                f"{day.get('reversal_confidence', '?'):<8}"
            )

        # 持续阻力位：出现 ≥2 天的（避免噪音）
        persist_r = [b for b in _level_occurrence(series, "resistance") if len(b["dates"]) >= 2]
        persist_s = [b for b in _level_occurrence(series, "support") if len(b["dates"]) >= 2]
        if persist_r:
            lines.append(f"\n  ★ 持续阻力位（出现 ≥2 天）：")
            for b in persist_r[:3]:
                labels = " / ".join(sorted(b["labels"])[:2])
                lines.append(f"      {b['repr_value']:>9.2f}   {labels:<40} 出现 {len(b['dates'])}/{n_days} 天")
        if persist_s:
            lines.append(f"  ★ 持续支撑位（出现 ≥2 天）：")
            for b in persist_s[:3]:
                labels = " / ".join(sorted(b["labels"])[:2])
                lines.append(f"      {b['repr_value']:>9.2f}   {labels:<40} 出现 {len(b['dates'])}/{n_days} 天")

        # 关键转换：今日 immediate_resistance 跟昨日不同
        if len(series) >= 2:
            prev_ir = series[-2].get("immediate_resistance")
            cur_ir = series[-1].get("immediate_resistance")
            if prev_ir is not None and cur_ir is not None and abs(cur_ir - prev_ir) / max(prev_ir, 1e-9) * 100 > 0.05:
                direction = "下移" if cur_ir < prev_ir else "上移"
                lines.append(f"  ★ 关键转换：立即阻力 {prev_ir:g} → {cur_ir:g}（{direction}）")

    return "\n".join(lines)


__all__ = [
    "SCHEMA_VERSION",
    "build_index_snapshot",
    "build_daily_snapshot",
    "save_daily",
    "load_recent",
    "format_history_table",
]
