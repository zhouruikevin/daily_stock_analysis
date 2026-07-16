#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qoder AI 批量分析脚本 - 基于 fetch_stock_context 获取的数据生成分析结果。
对每只股票执行6维度分析（技术面/量价/筹码/基本面/新闻面/综合评分），
输出 batch_results.json 和 batch_report.md 供 save_analysis_result.py 使用。
"""
import json
import os
import sys
import math

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

STOCKS = [
    "600522", "601138", "603986", "002371", "002407", "002463",
    "603650", "603019", "603444", "600378", "002517", "002050",
    "603296", "601899", "600118", "000400", "605090",
    "hk00700", "hk01810", "hk03690",
    "600176", "603186", "601208",
]

def load_ctx(code):
    path = f"/tmp/ctx_{code}.json"
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def analyze_one(ctx):
    """Qoder AI 分析单只股票，返回分析摘要 dict。"""
    code = ctx.get("code", "")
    name = ctx.get("name", code)
    rt = ctx.get("realtime") or {}
    tr = ctx.get("trend") or {}
    ch = ctx.get("chip") or {}
    bc = ctx.get("base_context") or {}
    fund = ctx.get("fundamental") or {}
    news = ctx.get("news") or ""
    pi = ctx.get("persisted_intelligence") or ""
    idx = ctx.get("index_snapshot") or {}

    price = rt.get("price") or 0
    change_pct = rt.get("change_pct") or 0
    volume_ratio = rt.get("volume_ratio") or 0
    turnover_rate = rt.get("turnover_rate") or 0
    pe = rt.get("pe_ratio")
    pb = rt.get("pb_ratio")
    total_mv = rt.get("total_mv")

    trend_status = tr.get("trend_status", "震荡")
    buy_signal = tr.get("buy_signal", "观望")
    signal_score = tr.get("signal_score") or 50
    ma5 = tr.get("ma5") or 0
    ma10 = tr.get("ma10") or 0
    ma20 = tr.get("ma20") or 0
    ma60 = tr.get("ma60") or 0

    chip_profit = ch.get("profit_ratio")
    chip_conc90 = ch.get("concentration_90")
    chip_avg_cost = ch.get("avg_cost")

    is_hk = code.startswith("hk")

    # ===== 1. 技术面分析 =====
    # 均线排列判断
    if ma5 > 0 and ma10 > 0 and ma20 > 0:
        if price > ma5 > ma10 > ma20:
            ma_arrangement = "多头排列"
        elif price < ma5 < ma10 < ma20:
            ma_arrangement = "空头排列"
        else:
            ma_arrangement = "震荡排列"
    else:
        ma_arrangement = "数据不足"

    # 乖离率
    bias = ((price - ma5) / ma5 * 100) if ma5 > 0 else 0

    # 趋势强度
    if signal_score >= 60:
        trend_strength = "偏多"
    elif signal_score >= 45:
        trend_strength = "中性"
    else:
        trend_strength = "偏空"

    tech_parts = []
    tech_parts.append(f"均线{ma_arrangement}，MA5={ma5:.2f}，MA10={ma10:.2f}，MA20={ma20:.2f}")
    tech_parts.append(f"趋势强度{signal_score}/100（{trend_strength}），乖离率{bias:.1f}%")
    if ma5 > 0 and ma20 > 0:
        tech_parts.append(f"MA5支撑={ma5:.2f}，MA20关键支撑={ma20:.2f}")
    technical_analysis = "；".join(tech_parts)

    # ===== 2. 量价分析 =====
    vol_parts = []
    if volume_ratio > 0:
        if volume_ratio > 1.5:
            vol_parts.append(f"量比{volume_ratio:.2f}放量活跃")
        elif volume_ratio > 0.8:
            vol_parts.append(f"量比{volume_ratio:.2f}正常")
        else:
            vol_parts.append(f"量比{volume_ratio:.2f}缩量")
    if turnover_rate > 0:
        if turnover_rate > 5:
            vol_parts.append(f"换手率{turnover_rate:.1f}%活跃")
        elif turnover_rate > 1:
            vol_parts.append(f"换手率{turnover_rate:.1f}%正常")
        else:
            vol_parts.append(f"换手率{turnover_rate:.1f}%低迷")

    # 量价配合判断
    if change_pct > 0 and volume_ratio > 1:
        vol_parts.append("涨+放量=健康上涨")
    elif change_pct > 0 and volume_ratio < 0.8:
        vol_parts.append("涨+缩量=量价背离（警惕）")
    elif change_pct < 0 and volume_ratio > 1.5:
        vol_parts.append("跌+放量=恐慌抛售")
    elif change_pct < 0 and volume_ratio < 0.8:
        vol_parts.append("跌+缩量=抛压减弱")

    volume_analysis = "；".join(vol_parts) if vol_parts else "量价数据不足"

    # ===== 3. 筹码分析 =====
    chip_parts = []
    if chip_profit is not None:
        profit_pct = chip_profit * 100
        if profit_pct > 70:
            chip_parts.append(f"获利比例{profit_pct:.0f}%高位区（追高风险）")
        elif profit_pct > 30:
            chip_parts.append(f"获利比例{profit_pct:.0f}%中位区")
        else:
            chip_parts.append(f"获利比例{profit_pct:.0f}%低位区（机会区）")
    if chip_conc90 is not None:
        conc_pct = chip_conc90 * 100
        if conc_pct < 10:
            chip_parts.append(f"90%集中度{conc_pct:.1f}%高度集中（主力控盘）")
        elif conc_pct < 20:
            chip_parts.append(f"90%集中度{conc_pct:.1f}%中等集中")
        else:
            chip_parts.append(f"90%集中度{conc_pct:.1f}%分散")
    if chip_avg_cost is not None and price > 0:
        if price > chip_avg_cost:
            chip_parts.append(f"价格>平均成本{chip_avg_cost:.2f}，多数人获利")
        else:
            chip_parts.append(f"价格<平均成本{chip_avg_cost:.2f}，多数人套牢")
    chip_analysis = "；".join(chip_parts) if chip_parts else "筹码数据不足"

    # ===== 4. 基本面分析 =====
    fund_parts = []
    if pe is not None and pe > 0:
        if pe < 15:
            fund_parts.append(f"PE {pe:.1f}低估")
        elif pe < 30:
            fund_parts.append(f"PE {pe:.1f}合理")
        elif pe < 50:
            fund_parts.append(f"PE {pe:.1f}偏高")
        else:
            fund_parts.append(f"PE {pe:.1f}高估")
    if pb is not None and pb > 0:
        if pb < 1:
            fund_parts.append(f"PB {pb:.2f}破净")
        elif pb < 3:
            fund_parts.append(f"PB {pb:.2f}合理")
        elif pb < 5:
            fund_parts.append(f"PB {pb:.2f}偏高")
        else:
            fund_parts.append(f"PB {pb:.2f}高估")
    fundamental_analysis = "；".join(fund_parts) if fund_parts else "基本面数据不足"

    # ===== 5. 新闻摘要 =====
    # 截取关键新闻
    news_lines = []
    if news:
        for line in news.split("\n"):
            line = line.strip()
            if line and (line.startswith("1.") or line.startswith("2.") or line.startswith("3.")):
                # 截取标题部分
                title_part = line[:120]
                news_lines.append(title_part)
    if pi:
        pi_lines = [l.strip() for l in pi.split("\n") if l.strip().startswith("1.") or l.strip().startswith("2.")]
        news_lines.extend(pi_lines[:2])

    news_summary = "；".join(news_lines[:3]) if news_lines else "近期无重大直接相关新闻"

    # ===== 6. 综合评分 =====
    score = 50  # 基础分

    # 技术面加减分
    if "多头" in ma_arrangement:
        score += 10
    elif "空头" in ma_arrangement:
        score -= 10
    if signal_score >= 60:
        score += 8
    elif signal_score < 40:
        score -= 8

    # 量价加减分
    if change_pct > 5:
        score += 5
    elif change_pct > 0:
        score += 2
    elif change_pct < -5:
        score -= 8
    elif change_pct < 0:
        score -= 3
    if volume_ratio > 1.5 and change_pct > 0:
        score += 3
    if volume_ratio < 0.5:
        score -= 2

    # 筹码加减分
    if chip_profit is not None:
        if chip_profit < 0.2:
            score += 5  # 低位区
        elif chip_profit > 0.7:
            score -= 5  # 高位区
    if chip_conc90 is not None and chip_conc90 < 0.1:
        score += 3  # 高度集中

    # 基本面加减分
    if pe is not None and pe > 0:
        if pe < 15:
            score += 5
        elif pe > 80:
            score -= 3
    if pb is not None and pb > 0:
        if pb < 2:
            score += 3

    # 乖离率
    if bias > 8:
        score -= 5
    elif bias > 5:
        score -= 2

    score = max(10, min(90, score))

    # 决策
    if score >= 65:
        operation_advice = "买入"
        decision_type = "buy"
        confidence = "高" if score >= 70 else "中"
    elif score >= 45:
        operation_advice = "持有"
        decision_type = "hold"
        confidence = "中"
    elif score >= 35:
        operation_advice = "观望"
        decision_type = "hold"
        confidence = "中"
    else:
        operation_advice = "卖出"
        decision_type = "sell"
        confidence = "中"

    if score >= 60:
        trend_pred = "震荡偏多"
    elif score >= 45:
        trend_pred = "震荡"
    else:
        trend_pred = "震荡偏空"

    # 狙击点位
    ideal_buy = ma5 if ma5 > 0 else None
    secondary_buy = ma10 if ma10 > 0 else None
    stop_loss = ma20 if ma20 > 0 else (price * 0.92 if price > 0 else None)
    take_profit = None
    if price > 0:
        if ma_arrangement == "多头排列" and ma20 > 0:
            take_profit = round(price * 1.1, 2)
        else:
            take_profit = round(ma5 * 1.05, 2) if ma5 > 0 else round(price * 1.05, 2)

    # 均线分析文本
    if ma_arrangement == "多头排列":
        ma_analysis = f"MA5={ma5:.2f}>MA10={ma10:.2f}>MA20={ma20:.2f}，多头排列，MA5在{ma5:.2f}形成支撑"
    elif ma_arrangement == "空头排列":
        ma_analysis = f"MA5={ma5:.2f}<MA10={ma10:.2f}<MA20={ma20:.2f}，空头排列，MA20在{ma20:.2f}形成压力"
    else:
        ma_analysis = f"MA5={ma5:.2f}，MA10={ma10:.2f}，MA20={ma20:.2f}，均线交错震荡"

    # 风险提示
    risks = []
    if ma_arrangement == "空头排列":
        risks.append("均线空头排列，下行压力")
    if bias > 5:
        risks.append(f"乖离率{bias:.1f}%偏高")
    if chip_profit and chip_profit > 0.6:
        risks.append("获利盘比例偏高，追高风险")
    if change_pct < -5:
        risks.append(f"大跌{abs(change_pct):.1f}%，短期抛压")
    if pe and pe > 80:
        risks.append(f"PE {pe:.0f}估值偏高")
    risk_warning = "；".join(risks) if risks else "暂无明显风险信号"

    # 买入理由
    buy_reasons = []
    if ma_arrangement == "多头排列":
        buy_reasons.append("均线多头排列")
    if signal_score >= 60:
        buy_reasons.append(f"趋势强度{signal_score}偏多")
    if chip_profit and chip_profit < 0.3:
        buy_reasons.append("筹码低位区")
    if pe and pe < 20:
        buy_reasons.append(f"PE {pe:.1f}估值合理")
    if volume_ratio > 1.2 and change_pct > 0:
        buy_reasons.append("放量上涨")
    buy_reason = "；".join(buy_reasons) if buy_reasons else "暂无明确买入信号"

    # 关键看点
    key_pts = []
    key_pts.append(f"趋势{trend_status}({signal_score}分)")
    if ma_arrangement:
        key_pts.append(ma_arrangement)
    if volume_ratio > 0:
        key_pts.append(f"量比{volume_ratio:.2f}")
    if pe and pe > 0:
        key_pts.append(f"PE {pe:.0f}")
    if chip_profit is not None:
        key_pts.append(f"获利盘{chip_profit*100:.0f}%")
    key_points = "；".join(key_pts)

    # 分析摘要
    analysis_summary = f"技术面{ma_arrangement}，趋势强度{signal_score}，量比{volume_ratio:.2f}" if volume_ratio else f"技术面{ma_arrangement}，趋势强度{signal_score}"
    if chip_profit is not None:
        analysis_summary += f"，获利盘{chip_profit*100:.0f}%"
    if pe and pe > 0:
        analysis_summary += f"，PE {pe:.0f}"
    analysis_summary += f"。综合评分{score}，建议{operation_advice}。"

    # 板块地位和公司亮点
    sector_position = ""
    company_highlights = ""
    # 简单的行业判断
    if code.startswith("60"):
        if code in ("601138",):
            sector_position = "电子制造服务龙头"
            company_highlights = "AI服务器核心供应商，绑定核心客户"
        elif code in ("603986",):
            sector_position = "存储芯片设计龙头"
            company_highlights = "NOR Flash国内领先，MCU业务成长"
        elif code in ("603019",):
            sector_position = "国产服务器龙头"
            company_highlights = "中科院背景，信创核心标的"
        elif code in ("601899",):
            sector_position = "全球矿业巨头"
            company_highlights = "铜金资源丰富，海外矿山持续扩张"
    elif code.startswith("00"):
        if code in ("002371",):
            sector_position = "半导体设备龙头"
            company_highlights = "国产替代核心标的，刻蚀+薄膜设备领先"
        elif code in ("002463",):
            sector_position = "PCB行业龙头"
            company_highlights = "AI服务器PCB核心供应商，高多层板技术领先"
        elif code in ("002517",):
            sector_position = "游戏行业"
            company_highlights = "传奇类游戏稳定贡献，新品储备丰富"
    elif code.startswith("hk"):
        if code == "hk00700":
            sector_position = "互联网平台龙头"
            company_highlights = "游戏+社交+广告+金融科技多元生态"
        elif code == "hk01810":
            sector_position = "消费电子+IoT龙头"
            company_highlights = "手机份额回升，汽车业务快速增长"
        elif code == "hk03690":
            sector_position = "本地生活平台龙头"
            company_highlights = "外卖到店双龙头，盈利持续改善"

    # 市场情绪
    if is_hk:
        market_sentiment = "偏乐观" if change_pct > 0 else "偏谨慎"
    else:
        csi = idx.get("csi2000_pct")
        if csi is not None and csi < -1:
            market_sentiment = "偏悲观（大盘走弱）"
        elif csi is not None and csi > 0:
            market_sentiment = "偏乐观"
        else:
            market_sentiment = "中性"

    # 短期/中期展望
    if score >= 60:
        short_term_outlook = f"短期震荡偏多，关注MA5({ma5:.2f})支撑有效性" if ma5 else "短期偏多"
        medium_term_outlook = "中期看好，趋势向好" if ma_arrangement == "多头排列" else "中期震荡，等待趋势确认"
    elif score >= 45:
        short_term_outlook = "短期震荡，方向不明"
        medium_term_outlook = "中期需观察，等待信号确认"
    else:
        short_term_outlook = f"短期偏空，关注MA20({ma20:.2f})支撑" if ma20 else "短期偏空"
        medium_term_outlook = "中期谨慎，趋势偏弱"

    # 热门题材
    hot_topics = ""
    if "AI" in (news or "").upper() or "芯片" in (news or "") or "半导体" in (news or ""):
        hot_topics = "AI/半导体/国产替代"
    elif "游戏" in (news or "") or code in ("002517", "603444"):
        hot_topics = "游戏/版号/出海"
    elif code in ("601899",):
        hot_topics = "黄金/铜/资源品"
    elif code in ("hk00700", "hk01810", "hk03690"):
        hot_topics = "互联网/消费电子/本地生活"
    elif code in ("002407",):
        hot_topics = "氟化工/锂电材料/六氟磷酸锂"
    elif code in ("002463", "603186", "601208"):
        hot_topics = "PCB/覆铜板/电子材料"
    elif code in ("603019",):
        hot_topics = "信创/算力/国产服务器"
    elif code in ("600118",):
        hot_topics = "卫星互联网/商业航天"
    else:
        hot_topics = "行业轮动/业绩预期"

    # 形态分析
    if change_pct > 9.5:
        pattern_analysis = "今日涨停，资金抢筹明显"
    elif change_pct < -9.5:
        pattern_analysis = "今日跌停，资金出逃明显"
    elif change_pct > 5:
        pattern_analysis = "大涨放量，多头强势"
    elif change_pct < -5:
        pattern_analysis = "大跌放量，空头强势"
    elif volume_ratio > 1.5:
        pattern_analysis = "放量异动，关注后续方向"
    else:
        pattern_analysis = "震荡整理，方向待选择"

    result = {
        "stock_name": name,
        "sentiment_score": score,
        "trend_prediction": trend_pred,
        "operation_advice": operation_advice,
        "decision_type": decision_type,
        "confidence_level": confidence,
        "current_price": round(price, 2) if price else None,
        "change_pct": round(change_pct, 2) if change_pct else 0,
        "volume_ratio": round(volume_ratio, 2) if volume_ratio else None,
        "turnover_rate": round(turnover_rate, 2) if turnover_rate else None,
        "ideal_buy": round(ideal_buy, 2) if ideal_buy else None,
        "secondary_buy": round(secondary_buy, 2) if secondary_buy else None,
        "stop_loss": round(stop_loss, 2) if stop_loss else None,
        "take_profit": round(take_profit, 2) if take_profit else None,
        "analysis_summary": analysis_summary,
        "key_points": key_points,
        "risk_warning": risk_warning,
        "buy_reason": buy_reason,
        "news_summary": news_summary,
        "technical_analysis": technical_analysis,
        "ma_analysis": ma_analysis,
        "volume_analysis": volume_analysis,
        "pattern_analysis": pattern_analysis,
        "fundamental_analysis": fundamental_analysis,
        "sector_position": sector_position,
        "company_highlights": company_highlights,
        "market_sentiment": market_sentiment,
        "hot_topics": hot_topics,
        "short_term_outlook": short_term_outlook,
        "medium_term_outlook": medium_term_outlook,
        "dashboard": {},
    }
    return result


def generate_report(items):
    """生成合并 Markdown 报告。"""
    lines = []
    lines.append("# 🎯 决策仪表盘 - 批量分析汇总报告")
    lines.append("")
    lines.append(f"> 分析时间：2026-07-15 盘中 | 共 {len(items)} 只股票")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 汇总表
    lines.append("## 📊 总览")
    lines.append("")
    lines.append("| 股票 | 代码 | 现价 | 涨跌幅 | 评分 | 建议 | 趋势 |")
    lines.append("|------|------|------|--------|------|------|------|")
    for item in items:
        code = item["code"]
        a = item["analysis"]
        emoji = "🟢" if a["decision_type"] == "buy" else ("🟡" if a["decision_type"] == "hold" else "🔴")
        price_str = f"{a['current_price']}" if a.get("current_price") else "N/A"
        pct_str = f"{a['change_pct']:+.1f}%" if a.get("change_pct") is not None else "N/A"
        lines.append(f"| {a['stock_name']} | {code} | {price_str} | {pct_str} | {a['sentiment_score']} | {emoji} {a['operation_advice']} | {a['trend_prediction']} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 逐只详情
    for item in items:
        code = item["code"]
        name = item["name"]
        a = item["analysis"]
        emoji = "🟢" if a["decision_type"] == "buy" else ("🟡" if a["decision_type"] == "hold" else "🔴")

        lines.append(f"## {emoji} {name}({code})")
        lines.append("")
        lines.append(f"**{a['operation_advice']}** | 评分 {a['sentiment_score']} | {a['trend_prediction']} | 置信度: {a['confidence_level']}")
        lines.append("")

        # 行情
        price_str = f"{a['current_price']}" if a.get("current_price") else "N/A"
        pct_str = f"{a['change_pct']:+.2f}%" if a.get("change_pct") is not None else "N/A"
        vr_str = f"{a['volume_ratio']}" if a.get("volume_ratio") else "N/A"
        tr_str = f"{a['turnover_rate']}%" if a.get("turnover_rate") else "N/A"
        lines.append(f"| 现价 | 涨跌幅 | 量比 | 换手率 |")
        lines.append(f"|------|--------|------|--------|")
        lines.append(f"| {price_str} | {pct_str} | {vr_str} | {tr_str} |")
        lines.append("")

        # 分析摘要
        lines.append(f"**AI决策**: {a['analysis_summary']}")
        lines.append(f"**关键看点**: {a['key_points']}")
        lines.append(f"**风险提示**: {a['risk_warning']}")
        lines.append("")

        # 狙击点位
        ib = a.get("ideal_buy")
        sb = a.get("secondary_buy")
        sl = a.get("stop_loss")
        tp = a.get("take_profit")
        lines.append("| 理想买入 | 二次买入 | 止损位 | 目标位 |")
        lines.append("|---------|---------|--------|--------|")
        lines.append(f"| {ib or '-'} | {sb or '-'} | {sl or '-'} | {tp or '-'} |")
        lines.append("")

        # 详细分析
        lines.append(f"**技术面**: {a['technical_analysis']}")
        lines.append(f"**均线**: {a['ma_analysis']}")
        lines.append(f"**量价**: {a['volume_analysis']}")
        lines.append(f"**筹码**: {a.get('chip_analysis', '数据不足')}")
        lines.append(f"**基本面**: {a['fundamental_analysis']}")
        lines.append(f"**形态**: {a['pattern_analysis']}")
        lines.append(f"**板块**: {a['sector_position'] or 'N/A'}")
        lines.append(f"**公司亮点**: {a['company_highlights'] or 'N/A'}")
        lines.append(f"**短期展望**: {a['short_term_outlook']}")
        lines.append(f"**中期展望**: {a['medium_term_outlook']}")
        lines.append(f"**新闻摘要**: {a['news_summary']}")
        lines.append("")

        if a.get("buy_reason"):
            lines.append(f"**买入理由**: {a['buy_reason']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("*分析模型：Qoder AI Native v3.0*")
    lines.append("*数据来源：Tushare + 腾讯财经 + Tavily + Efinance*")
    lines.append("")

    return "\n".join(lines)


def main():
    items = []
    for code in STOCKS:
        ctx = load_ctx(code)
        if not ctx:
            print(f"Warning: no context for {code}", file=sys.stderr)
            continue
        name = ctx.get("name", code)
        analysis = analyze_one(ctx)

        # 补充筹码分析
        ch = ctx.get("chip") or {}
        if ch:
            chip_parts = []
            profit = ch.get("profit_ratio")
            conc = ch.get("concentration_90")
            avg = ch.get("avg_cost")
            price = (ctx.get("realtime") or {}).get("price") or 0
            if profit is not None:
                profit_pct = profit * 100
                if profit_pct > 70:
                    chip_parts.append(f"获利比例{profit_pct:.0f}%高位区")
                elif profit_pct > 30:
                    chip_parts.append(f"获利比例{profit_pct:.0f}%中位区")
                else:
                    chip_parts.append(f"获利比例{profit_pct:.0f}%低位区")
            if conc is not None:
                conc_pct = conc * 100
                if conc_pct < 10:
                    chip_parts.append(f"90%集中度{conc_pct:.1f}%高度集中")
                elif conc_pct < 20:
                    chip_parts.append(f"90%集中度{conc_pct:.1f}%中等集中")
                else:
                    chip_parts.append(f"90%集中度{conc_pct:.1f}%分散")
            if avg is not None and price > 0:
                if price > avg:
                    chip_parts.append(f"价格>平均成本{avg:.2f}，多数人获利")
                else:
                    chip_parts.append(f"价格<平均成本{avg:.2f}，多数人套牢")
            analysis["chip_analysis"] = "；".join(chip_parts) if chip_parts else "筹码数据不足"
        else:
            analysis["chip_analysis"] = "筹码数据不足（港股不支持）"

        items.append({"code": code, "name": name, "analysis": analysis})
        print(f"✅ {name}({code}): 评分{analysis['sentiment_score']} | {analysis['operation_advice']} | {analysis['trend_prediction']}", file=sys.stderr)

    # 保存 batch JSON
    batch_path = "/tmp/batch_results.json"
    with open(batch_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, default=str, indent=2)
    print(f"\n批量JSON已保存: {batch_path}", file=sys.stderr)

    # 保存 Markdown 报告
    report = generate_report(items)
    report_path = "/tmp/batch_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Markdown报告已保存: {report_path}", file=sys.stderr)

    # 打印汇总
    print("\n" + "=" * 80, file=sys.stderr)
    print("📊 批量分析汇总:", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    for item in items:
        a = item["analysis"]
        emoji = "🟢" if a["decision_type"] == "buy" else ("🟡" if a["decision_type"] == "hold" else "🔴")
        print(f"  {emoji} {a['stock_name']:8s}({item['code']:8s}) 评分{a['sentiment_score']:2d} | {a['operation_advice']:4s} | {a['trend_prediction']}", file=sys.stderr)
    print("=" * 80, file=sys.stderr)

if __name__ == "__main__":
    main()
