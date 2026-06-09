#!/usr/bin/env python3
"""将指数分析结果格式化为结构化 Markdown（用于邮件推送等场景）。

终端输出是等宽对齐的纯文本，适合 console 但不适合邮件 HTML 渲染。
本模块把 mode=both 的 wrapped_results 转成带标题、表格、emoji 标记的 Markdown，
经 EmailSender 的 markdown_to_html_document() 转换后得到排版友好的 HTML 邮件。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# ============================================================
# 反转置信 emoji
# ============================================================
_CONFIDENCE_EMOJI = {
    "高置信": "🔴",
    "中置信": "🟡",
    "无": "⚪",
}

_SEVERITY_EMOJI = {
    "强": "⛔",
    "中": "⚠️",
    "弱": "💬",
    "无": "✅",
}

_STRENGTH_ICON = {
    "强": "●●●",
    "中": "●●○",
    "弱": "●○○",
}


def _score_emoji(score: int | None) -> str:
    """评分对应的 emoji。"""
    if score is None:
        return ""
    if score >= 70:
        return "🔴"
    if score >= 45:
        return "🟠"
    if score >= 15:
        return "🟡"
    return "⚪"


# ============================================================
# 单指数详情
# ============================================================
def _format_index_divergence_md(div: Dict[str, Any]) -> str:
    """单个指数的顶背离段落（Markdown）。"""
    if "error" in div:
        return f"> ❌ 数据错误：{div['error']}\n"

    lines: List[str] = []
    name = div.get("index_name", "?")
    code = div.get("index_code", "?")
    market = div.get("market", "?")
    data_range = div.get("data_range", "?")
    trading_days = div.get("trading_days", "?")

    lines.append(f"### {name}（{code}）— {market}")
    lines.append(f"> 数据区间：{data_range} | {trading_days} 个交易日")
    lines.append("")

    # 背离判断
    macd = "⚠️ 存在" if div.get("macd_divergence") else "❌ 无"
    rsi = "⚠️ 存在" if div.get("rsi_divergence") else "❌ 无"
    vol = "⚠️ 存在" if div.get("vol_divergence") else "❌ 无"
    severity = div.get("divergence_severity", "?")
    signal = div.get("divergence_signal", "")
    sev_icon = _SEVERITY_EMOJI.get(severity, "")

    lines.append("| 指标 | 判定 |")
    lines.append("|------|------|")
    lines.append(f"| MACD 顶背离 | {macd} |")
    lines.append(f"| RSI 顶背离  | {rsi} |")
    lines.append(f"| 量价背离    | {vol} |")
    lines.append(f"| **信号强度** | **{sev_icon} {severity}** — {signal} |")
    lines.append("")

    # 背离细节
    details = div.get("divergence_details", [])
    if details:
        lines.append("<details><summary>背离细节</summary>")
        lines.append("")
        for d in details:
            method = d.get("method", "价格高点对比")
            if method == "dif_peak_comparison":
                lines.append(f"- **DIF 峰值对比**：{d.get('earlier_peak', '?')} → {d.get('later_peak', '?')}")
                lines.append(f"  - 价格：{d.get('earner_price', '?')} → {d.get('later_price', '?')}")
                lines.append(f"  - DIF：{d.get('earner_dif', '?')} → {d.get('later_dif', '?')}")
            elif method == "rsi_peak_comparison":
                lines.append(f"- **RSI 峰值对比**：{d.get('earlier_peak', '?')} → {d.get('later_peak', '?')}")
                lines.append(f"  - 价格：{d.get('earner_price', '?')} → {d.get('later_price', '?')}")
                lines.append(f"  - RSI：{d.get('earner_rsi', '?')} → {d.get('later_rsi', '?')}")
            else:
                lines.append(f"- **价格高点对比**：{d.get('earlier_peak', '?')} → {d.get('later_peak', '?')}")
                ep = d.get('earner_price', '?')
                lp = d.get('later_price', '?')
                lines.append(f"  - 价格：{ep} → {lp}（创新高）")
                if "macd_div" in d:
                    icon = "↓顶背离!" if d["macd_div"] else "↑同步"
                    lines.append(f"  - DIF：{d.get('earner_dif', '?')} → {d.get('later_dif', '?')}（{icon}）")
                if "rsi_div" in d:
                    icon = "↓顶背离!" if d["rsi_div"] else "↑同步"
                    lines.append(f"  - RSI：{d.get('earner_rsi', '?')} → {d.get('later_rsi', '?')}（{icon}）")
                if "vol_div" in d:
                    icon = "↓缩量背离!" if d["vol_div"] else "↑放量"
                    lines.append(f"  - 成交量：{icon}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # 当前状态
    cs = div.get("current_state", {})
    if cs:
        lines.append("**当前状态**（{}）".format(cs.get("date", "?")))
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|------|-----|")
        lines.append(f"| 收盘 | {cs.get('close', '?')} |")

        ma_parts = []
        if cs.get("ma5"):
            ma_parts.append(f"MA5={cs['ma5']}")
        if cs.get("ma10"):
            ma_parts.append(f"MA10={cs['ma10']}")
        if cs.get("ma20"):
            ma_parts.append(f"MA20={cs['ma20']}")
        if cs.get("ma60"):
            ma_parts.append(f"MA60={cs['ma60']}")
        if ma_parts:
            lines.append(f"| 均线 | {'  '.join(ma_parts)} |")

        pos_parts = []
        if cs.get("above_ma5") is not None:
            pos_parts.append("MA5" + ("上" if cs["above_ma5"] else "下"))
        if cs.get("above_ma20") is not None:
            pos_parts.append("MA20" + ("上" if cs["above_ma20"] else "下"))
        if cs.get("above_ma60") is not None:
            pos_parts.append("MA60" + ("上" if cs["above_ma60"] else "下"))
        if pos_parts:
            lines.append(f"| 均线位置 | {'  '.join(pos_parts)} |")

        cross = cs.get("macd_cross", "?")
        lines.append(f"| MACD | DIF={cs.get('dif', '?')}  DEA={cs.get('dea', '?')}  柱={cs.get('macd_hist', '?')}  **{cross}** |")
        lines.append(f"| RSI(14) | {cs.get('rsi', '?')}（{cs.get('rsi_zone', '?')}）|")
        if cs.get("vol_ratio"):
            lines.append(f"| 量比 | {cs['vol_ratio']} |")
        lines.append("")

    return "\n".join(lines)


def _format_index_levels_md(lev: Dict[str, Any]) -> str:
    """单个指数的上下沿段落（Markdown）。"""
    if "error" in lev:
        return f"> ❌ 数据错误：{lev['error']}\n"

    lines: List[str] = []
    current_price = lev.get("current_price", "?")

    lines.append(f"**上下沿（关键位汇总）** | 截止：{lev.get('as_of', '?')} | 当前价：{current_price}")
    lines.append("")

    # 阻力位
    res = lev.get("resistance_levels", [])
    if res:
        lines.append("> **上沿（阻力）**")
        lines.append("")
        lines.append("| 强度 | 价位 | 标签 | 距离 |")
        lines.append("|------|------|------|------|")
        for lvl in res:
            icon = _STRENGTH_ICON.get(lvl.get("strength", ""), "   ")
            lines.append(
                f"| {icon} {lvl.get('strength', '')} "
                f"| {lvl.get('value', 0):.2f} "
                f"| {lvl.get('label', '')} "
                f"| +{lvl.get('distance_pct', 0):.2f}% |"
            )
        lines.append("")

    # 支撑位
    sup = lev.get("support_levels", [])
    if sup:
        lines.append("> **下沿（支撑）**")
        lines.append("")
        lines.append("| 强度 | 价位 | 标签 | 距离 |")
        lines.append("|------|------|------|------|")
        for lvl in sup:
            icon = _STRENGTH_ICON.get(lvl.get("strength", ""), "   ")
            lines.append(
                f"| {icon} {lvl.get('strength', '')} "
                f"| {lvl.get('value', 0):.2f} "
                f"| {lvl.get('label', '')} "
                f"| {lvl.get('distance_pct', 0):.2f}% |"
            )
        lines.append("")

    if not res and not sup:
        lines.append("（3% 窗口内无显著关键位）")
        lines.append("")

    return "\n".join(lines)


def _format_index_reversal_md(rev: Dict[str, Any], index_name: str) -> str:
    """单个指数的反转置信段落（Markdown）。"""
    confidence = rev.get("confidence", "?")
    reason = rev.get("reason", "")
    emoji = _CONFIDENCE_EMOJI.get(confidence, "")
    score = rev.get("divergence_score")
    score_part = ""
    if score is not None:
        score_part = f" ｜ 评分：{_score_emoji(score)} **{score}分**"
    return f"**反转置信**：{emoji} **{confidence}** — {reason}{score_part}"


# ============================================================
# 汇总表
# ============================================================
def _format_divergence_summary_md(results: List[Dict[str, Any]]) -> str:
    """所有指数的顶背离汇总表。"""
    lines: List[str] = []
    lines.append("## 顶背离汇总")
    lines.append("")
    lines.append("| 指数 | 代码 | MACD | RSI | 量价 | 信号 | 说明 |")
    lines.append("|------|------|------|-----|------|------|------|")

    for w in results:
        div = w.get("divergence") or {}
        if div.get("error"):
            lines.append(f"| {w.get('index_key', '?')} | ERROR | {div['error']} | | | | |")
            continue
        macd = "⚠️" if div.get("macd_divergence") else "❌"
        rsi = "⚠️" if div.get("rsi_divergence") else "❌"
        vol = "⚠️" if div.get("vol_divergence") else "❌"
        sev = div.get("divergence_severity", "?")
        sig = div.get("divergence_signal", "")
        lines.append(
            f"| {div.get('index_name', '?')} "
            f"| {div.get('index_code', '?')} "
            f"| {macd} | {rsi} | {vol} "
            f"| **{sev}** | {sig} |"
        )
    lines.append("")
    return "\n".join(lines)


def _format_combined_summary_md(results: List[Dict[str, Any]]) -> str:
    """顶背离 × 上下沿 联动总览表。"""
    lines: List[str] = []
    lines.append("## 联动总览")
    lines.append("")
    lines.append("| 指数 | 背离 | 当前价 | 立即阻力 | 距阻力 | 立即支撑 | 评分 | 反转置信 |")
    lines.append("|------|------|--------|----------|--------|----------|------|----------|")

    for w in results:
        div = w.get("divergence") or {}
        lev = w.get("levels") or {}
        rev = w.get("reversal") or {}
        if div.get("error") or lev.get("error"):
            err = (div.get("error") or lev.get("error") or "unknown")
            lines.append(f"| {w.get('index_key', '?')} | ERROR | {err} | | | | |")
            continue

        name = div.get("index_name", w.get("index_key", "?"))
        sev = div.get("divergence_severity", "?")
        cp = lev.get("current_price", "?")
        ir = lev.get("immediate_resistance")
        ir_str = f"{ir:g}" if ir is not None else "-"
        dist = rev.get("distance_to_resistance_pct")
        dist_str = f"{dist:.2f}%" if dist is not None else "-"
        is_val = lev.get("immediate_support")
        is_str = f"{is_val:g}" if is_val is not None else "-"
        confidence = rev.get("confidence", "?")
        emoji = _CONFIDENCE_EMOJI.get(confidence, "")
        score = rev.get("divergence_score", div.get("divergence_score"))
        score_str = f"{_score_emoji(score)} {score}" if score is not None else "-"

        lines.append(
            f"| {name} | {sev} | {cp} | {ir_str} | {dist_str} | {is_str} "
            f"| {score_str} | {emoji} {confidence} |"
        )

    lines.append("")
    lines.append("> 反转置信：🔴 高置信 = 顶背离 + 撞上沿(<0.5%) ｜ 🟡 中置信 = 仅背离 或 仅撞上沿 ｜ ⚪ 无 = 暂无信号")
    lines.append("")
    return "\n".join(lines)


# ============================================================
# 历史变化（可选）
# ============================================================
def _format_history_md(snapshots: List[Dict[str, Any]],
                       index_keys: Optional[List[str]] = None) -> str:
    """历史变化对比表（Markdown 版）。"""
    if not snapshots:
        return ""

    if index_keys is None:
        index_keys = [i["index_key"] for i in snapshots[-1].get("indices", [])]

    # lazy import 避免循环依赖
    import history as _history

    n_days = len(snapshots)
    lines: List[str] = []
    lines.append(f"## 近 {n_days} 个交易日关键位变化")
    lines.append("")

    for k in index_keys:
        series = _history._per_index_series(snapshots, k)
        if not series:
            continue
        name = series[-1].get("index_name", k)
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| 日期 | 当前价 | 立即阻力 | 阻力标签 | 距阻力 | 反转置信 |")
        lines.append("|------|--------|----------|----------|--------|----------|")

        for day in series:
            ir = day.get("immediate_resistance")
            ir_str = f"{ir:g}" if ir is not None else "-"
            top3 = day.get("resistance_top3", [])
            ir_label = top3[0].get("label", "") if top3 else ""
            dist = day.get("distance_to_resistance_pct")
            dist_str = f"{dist:.2f}%" if dist is not None else "-"
            cp = day.get("current_price")
            cp_str = f"{cp:g}" if cp is not None else "-"
            conf = day.get("reversal_confidence", "?")
            emoji = _CONFIDENCE_EMOJI.get(conf, "")
            lines.append(
                f"| {day['date']} | {cp_str} | {ir_str} | {ir_label} | {dist_str} | {emoji} {conf} |"
            )
        lines.append("")

        # 持续阻力位
        persist_r = [b for b in _history._level_occurrence(series, "resistance") if len(b["dates"]) >= 2]
        persist_s = [b for b in _history._level_occurrence(series, "support") if len(b["dates"]) >= 2]
        if persist_r:
            lines.append("> **持续阻力位**（出现 ≥2 天）")
            lines.append("")
            for b in persist_r[:3]:
                labels = " / ".join(sorted(b["labels"])[:2])
                lines.append(f"> - `{b['repr_value']:.2f}` {labels} — 出现 {len(b['dates'])}/{n_days} 天")
            lines.append("")
        if persist_s:
            lines.append("> **持续支撑位**（出现 ≥2 天）")
            lines.append("")
            for b in persist_s[:3]:
                labels = " / ".join(sorted(b["labels"])[:2])
                lines.append(f"> - `{b['repr_value']:.2f}` {labels} — 出现 {len(b['dates'])}/{n_days} 天")
            lines.append("")

    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================
def format_markdown_report(
    results: List[Dict[str, Any]],
    *,
    today: Optional[str] = None,
    snapshots: Optional[List[Dict[str, Any]]] = None,
    index_keys: Optional[List[str]] = None,
) -> str:
    """将 mode=both 的 wrapped_results 格式化为完整的 Markdown 报告。

    Args:
        results: mode=both 的 wrapped_results
        today: 日期字符串（默认自动取）
        snapshots: 历史 snapshot 列表（可选，传入则附加历史变化表）
        index_keys: 指数 key 列表（可选，用于历史表）

    Returns:
        结构化 Markdown 字符串
    """
    from datetime import datetime

    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")

    # 统计高置信数
    high_count = sum(
        1 for w in results
        if (w.get("reversal") or {}).get("confidence") == "高置信"
    )
    total = len(results)
    if high_count > 0:
        header_alert = f"⚠️ {high_count}/{total} 指数高置信反转"
    else:
        header_alert = f"无高置信信号（{total} 指数）"

    parts: List[str] = []

    # 报告头
    parts.append(f"# 📊 指数分析 — {today}")
    parts.append("")
    parts.append(f"> {header_alert}")
    parts.append("")
    parts.append("---")
    parts.append("")

    # 联动总览（放最前面，一眼看结论）
    parts.append(_format_combined_summary_md(results))

    # 各指数详情
    parts.append("---")
    parts.append("")
    parts.append("## 各指数详情")
    parts.append("")
    for w in results:
        div = w.get("divergence") or {}
        lev = w.get("levels") or {}
        rev = w.get("reversal") or {}

        parts.append(_format_index_divergence_md(div))
        parts.append(_format_index_levels_md(lev))
        if rev:
            parts.append(_format_index_reversal_md(rev, div.get("index_name", "")))
            parts.append("")
            parts.append("---")
            parts.append("")

    # 顶背离汇总
    div_list = [w.get("divergence", {}) for w in results]
    parts.append(_format_divergence_summary_md(results))

    # 历史变化（可选）
    if snapshots:
        history_md = _format_history_md(snapshots, index_keys=index_keys)
        if history_md:
            parts.append("---")
            parts.append("")
            parts.append(history_md)

    return "\n".join(parts)


__all__ = ["format_markdown_report"]
