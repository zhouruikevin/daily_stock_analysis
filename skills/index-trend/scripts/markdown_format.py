#!/usr/bin/env python3
"""把趋势推演结果格式化为结构化 Markdown（邮件 HTML 渲染用）。

终端输出是等宽纯文本，适合 console 但不适合邮件。本模块转成带标题/表格/emoji
的 Markdown，经 EmailSender.markdown_to_html_document() 渲染为排版友好的 HTML。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

_DIR_EMOJI = {"up": "📈", "down": "📉", "range": "➡️"}
_DIR_CN = {"up": "上升", "down": "下降", "range": "震荡"}
_SCENARIO_EMOJI = {"continuation": "🟢", "consolidation": "🟡", "reversal": "🔴"}


def _index_block(r: Dict[str, Any]) -> str:
    if r.get("error"):
        return f"### {r.get('index_name', r.get('index_key'))}\n> ❌ {r['error']}\n"
    t, vp, fc = r["trend"], r["volume_price"], r["forecast"]
    lines: List[str] = []
    emoji = _DIR_EMOJI.get(t["direction"], "")
    lines.append(f"### {emoji} {r['index_name']}（{r['index_code']}）— {r['market']}")
    lines.append(f"> 当前价 **{r['current_price']}** ｜ 截止 {r['latest_date']}")
    lines.append("")
    lines.append("| 维度 | 结论 |")
    lines.append("|------|------|")
    lines.append(f"| 趋势 | {_DIR_CN[t['direction']]} · 强度 {t['strength']}({t['strength_label']}) · {t['phase']} |")
    lines.append(f"| 结构/均线 | {t['structure']} · {t['ma_alignment']} · 斜率 {t['slope_pct_per_day']}%/日 |")
    lines.append(f"| 量价健康 | **{vp['health_score']}**({vp['health_label']}) · {vp['vol_trend']} · {' / '.join(vp['signals'])} |")
    er = fc["expected_range"]
    lines.append(f"| 预期波动带 | {er['low']} ~ {er['high']} |")
    lines.append("")
    lines.append(f"**未来 {fc['horizon_days'][0]}-{fc['horizon_days'][1]} 交易日情景**")
    lines.append("")
    lines.append("| | 情景 | 概率 | 目标区间 | 触发 |")
    lines.append("|---|------|------|----------|------|")
    for s in fc["scenarios"]:
        star = "★" if s["type"] == fc["primary_scenario"] else ""
        se = _SCENARIO_EMOJI.get(s["type"], "")
        tr = s["target_range"]
        lines.append(f"| {star} | {se} {s['name']} | **{s['probability']}%** | "
                     f"{tr['low']}~{tr['high']} | {s['trigger']} |")
    lines.append("")
    lines.append(f"> 💡 {fc['signal']}")
    cal = r.get("calibration") or {}
    if cal.get("applied"):
        adj = cal.get("prob_adjust", {})
        adj_str = ", ".join(f"{k}{v:+g}" for k, v in adj.items()) if adj else "无"
        lines.append(f">")
        lines.append(f"> 🔧 历史校准（样本{cal.get('n_samples')}, w={cal.get('shrink_w')}）："
                     f"概率修正 {adj_str}；目标平移 {cal.get('bias_shift_pct', 0)}%；"
                     f"带宽×{cal.get('widen_factor', 1.0)}")
    lines.append("")
    return "\n".join(lines)


def _overview_table(results: List[Dict[str, Any]]) -> str:
    lines = ["## 总览", "", "| 指数 | 方向 | 强度 | 健康 | 主情景 | 概率 | 目标区间 |",
             "|------|------|------|------|--------|------|----------|"]
    for r in results:
        if r.get("error"):
            lines.append(f"| {r.get('index_name', '?')} | ERROR | | | {r['error']} | | |")
            continue
        t, fc = r["trend"], r["forecast"]
        primary = next((s for s in fc["scenarios"] if s["type"] == fc["primary_scenario"]),
                       fc["scenarios"][0])
        tr = primary["target_range"]
        emoji = _DIR_EMOJI.get(t["direction"], "")
        lines.append(f"| {r['index_name']} | {emoji}{_DIR_CN[t['direction']]} "
                     f"| {t['strength']}({t['strength_label']}) | {r['volume_price']['health_score']} "
                     f"| {primary['name']} | **{primary['probability']}%** | {tr['low']}~{tr['high']} |")
    lines.append("")
    return "\n".join(lines)


def format_markdown_report(results: List[Dict[str, Any]], *,
                           today: Optional[str] = None,
                           accuracy_text: Optional[str] = None) -> str:
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    parts = [f"# 📈 指数趋势推演 — {today}", "",
             "> 顺势为先验 · 量价定置信 · 关键位定路径 · 历史数据校准", "", "---", ""]
    parts.append(_overview_table(results))
    parts.append("---")
    parts.append("")
    parts.append("## 各指数详情")
    parts.append("")
    for r in results:
        parts.append(_index_block(r))
        parts.append("---")
        parts.append("")
    if accuracy_text:
        parts.append("## 历史命中率")
        parts.append("")
        parts.append("```")
        parts.append(accuracy_text)
        parts.append("```")
    return "\n".join(parts)


__all__ = ["format_markdown_report"]
