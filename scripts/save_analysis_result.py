#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保存 Qoder AI 分析结果到项目数据库 + 发送邮件通知。

Qoder AI 分析完成后，调用此脚本：
1. 构造 AnalysisResult 对象
2. 保存分析历史到 DB（save_analysis_history）
3. 提取决策信号（extract_and_persist_from_analysis_result）
4. 生成 dashboard 报告（generate_dashboard_report）
5. 发送邮件 + 保存报告

用法：
    # 从 JSON 文件读取分析结果
    python3 scripts/save_analysis_result.py 603444 -f /tmp/analysis.json

    # 同时传入 Markdown 报告（用于邮件正文）
    python3 scripts/save_analysis_result.py 603444 -f /tmp/analysis.json --report /tmp/report.md

    # 多只股票批量保存（合并邮件）
    python3 scripts/save_analysis_result.py batch -f /tmp/batch_results.json
"""

import sys
import os
import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from src.config import get_config
from src.storage import get_db
from src.analyzer import AnalysisResult
from src.notification import NotificationService

logger = logging.getLogger(__name__)


def _build_sniper_points(
    data: Dict[str, Any], name: str = "current_price"
) -> Dict[str, Optional[float]]:
    """从 JSON 数据中提取狙击点位（纯数值）。

    优先读取顶层数值字段 (ideal_buy/secondary_buy/stop_loss/take_profit)，
    若无则尝试从 dashboard.battle_plan.sniper_points 解析。
    """
    points: Dict[str, Optional[float]] = {}
    for key in ("ideal_buy", "secondary_buy", "stop_loss", "take_profit"):
        val = data.get(key)
        if val is not None:
            try:
                f = float(val)
                if f > 0:
                    points[key] = f
                    continue
            except (ValueError, TypeError):
                pass
        # 兼容中文文本格式: "理想买入点：1680.5元"
        if isinstance(val, str):
            import re
            nums = re.findall(r"\d+(?:\.\d+)?", str(val))
            if nums:
                try:
                    f = float(nums[-1])
                    if f > 0:
                        points[key] = f
                        continue
                except (ValueError, TypeError):
                    pass
        points[key] = None
    return points


def _build_enriched_dashboard(data: Dict[str, Any]) -> Dict[str, Any]:
    """构建带狙击点位的 dashboard 结构，确保 save_analysis_history 能提取到。"""
    existing = data.get("dashboard") or {}
    if not isinstance(existing, dict):
        existing = {}

    # 如果已有 sniper_points 则不覆盖（但确保数值化）
    bp = existing.get("battle_plan") or {}
    if not isinstance(bp, dict):
        bp = {}
    sp = bp.get("sniper_points") or {}
    if not isinstance(sp, dict):
        sp = {}

    sniper = _build_sniper_points(data)
    # 仅填充缺失的 / 数值类型
    for key in ("ideal_buy", "secondary_buy", "stop_loss", "take_profit"):
        if sp.get(key) is None and sniper.get(key) is not None:
            sp[key] = sniper[key]
        elif sp.get(key) is not None and sniper.get(key) is not None:
            # 已有值但不一定是数值，用 extracted 覆盖
            sp[key] = sniper[key]

    bp["sniper_points"] = sp
    existing["battle_plan"] = bp
    return existing


def build_analysis_result(code: str, stock_name: str, data: Dict[str, Any]) -> AnalysisResult:
    """
    从 Qoder AI 输出的 JSON 构造 AnalysisResult 对象。

    Args:
        code: 股票代码
        stock_name: 股票名称
        data: Qoder AI 输出的分析结果 JSON
    """
    # 构建带狙击点位的 dashboard
    dashboard = _build_enriched_dashboard(data)

    # 构建 market_snapshot 方便 _extract_market_metrics 回退读取
    market_snapshot = data.get("market_snapshot") or {}
    if not isinstance(market_snapshot, dict):
        market_snapshot = {}
    if market_snapshot.get("change_pct") is None:
        market_snapshot["change_pct"] = data.get("change_pct")
    if market_snapshot.get("volume_ratio") is None:
        market_snapshot["volume_ratio"] = data.get("volume_ratio")

    result = AnalysisResult(
        code=code,
        name=stock_name or data.get("stock_name", code),
        sentiment_score=int(data.get("sentiment_score", 50)),
        trend_prediction=data.get("trend_prediction", "震荡"),
        operation_advice=data.get("operation_advice", "观望"),
        decision_type=data.get("decision_type", "hold"),
        confidence_level=data.get("confidence_level", "中"),
        report_language=data.get("report_language", "zh"),
        action=data.get("action"),
        action_label=data.get("action_label"),
        dashboard=dashboard,
        trend_analysis=data.get("trend_analysis", ""),
        short_term_outlook=data.get("short_term_outlook", ""),
        medium_term_outlook=data.get("medium_term_outlook", ""),
        technical_analysis=data.get("technical_analysis", ""),
        ma_analysis=data.get("ma_analysis", ""),
        volume_analysis=data.get("volume_analysis", ""),
        pattern_analysis=data.get("pattern_analysis", ""),
        fundamental_analysis=data.get("fundamental_analysis", ""),
        sector_position=data.get("sector_position", ""),
        company_highlights=data.get("company_highlights", ""),
        news_summary=data.get("news_summary", ""),
        market_sentiment=data.get("market_sentiment", ""),
        hot_topics=data.get("hot_topics", ""),
        analysis_summary=data.get("analysis_summary", ""),
        key_points=data.get("key_points", ""),
        risk_warning=data.get("risk_warning", ""),
        buy_reason=data.get("buy_reason", ""),
        market_snapshot=market_snapshot,
        search_performed=bool(data.get("search_performed", False)),
        data_sources=data.get("data_sources", "Qoder AI Native"),
        success=True,
        current_price=data.get("current_price"),
        change_pct=data.get("change_pct"),
        model_used=data.get("model_used", "Qoder AI Native"),
    )
    return result


def save_single(
    code: str,
    stock_name: str,
    analysis_data: Dict[str, Any],
    report_markdown: Optional[str] = None,
    send_email: bool = True,
) -> bool:
    """
    保存单只股票的分析结果。

    Args:
        code: 股票代码
        stock_name: 股票名称
        analysis_data: Qoder AI 输出的分析结果 JSON
        report_markdown: 可选的 Markdown 报告（用于邮件正文）
        send_email: 是否发送邮件

    Returns:
        是否成功
    """
    db = get_db()
    config = get_config()
    query_id = str(uuid.uuid4())

    # 1. 构造 AnalysisResult
    result = build_analysis_result(code, stock_name, analysis_data)
    result.query_id = query_id

    # 2. 保存分析历史
    history_id = 0
    context_snapshot = None
    try:
        # 构建 enhanced_context，包含实时行情供 _extract_market_metrics 提取
        enhanced_context = dict(analysis_data.get("enhanced_context") or {})
        # 注入 realtime 数据（_extract_market_metrics 优先从此路径读取 change_pct）
        realtime_data = {}
        cp = analysis_data.get("current_price")
        if cp is not None:
            realtime_data["price"] = cp
        pct = analysis_data.get("change_pct")
        if pct is not None:
            realtime_data["change_pct"] = pct
        vr = analysis_data.get("volume_ratio")
        if vr is not None:
            realtime_data["volume_ratio"] = vr
        tr = analysis_data.get("turnover_rate")
        if tr is not None:
            realtime_data["turnover_rate"] = tr
        if realtime_data:
            enhanced_context["realtime"] = realtime_data
        context_snapshot = {
            "enhanced_context": enhanced_context,
            "news_content": analysis_data.get("news_summary", ""),
        }
        history_id = db.save_analysis_history(
            result=result,
            query_id=query_id,
            report_type="full",
            news_content=analysis_data.get("news_summary", ""),
            context_snapshot=context_snapshot,
            save_snapshot=True,
        )
        logger.info("分析历史已保存: %s(%s) history_id=%s", stock_name, code, history_id)
    except Exception as e:
        logger.error("保存分析历史失败: %s", e)

    # 3. 决策信号提取
    try:
        from src.services.decision_signal_extractor import extract_and_persist_from_analysis_result
        extract_and_persist_from_analysis_result(
            result,
            context_snapshot=context_snapshot,
            source_report_id=history_id if history_id > 0 else None,
            trace_id=query_id,
            query_source="skill",
            report_type="full",
        )
        logger.info("决策信号已提取: %s(%s)", stock_name, code)
    except Exception as e:
        logger.debug("决策信号提取失败: %s", e)

    # 4. 指数数据回写
    try:
        idx = analysis_data.get("index_snapshot") or {}
        if idx.get("csi2000_pct") is not None or idx.get("chinext_pct") is not None:
            db.update_index_data_for_today(
                code=code,
                csi2000_pct=idx.get("csi2000_pct"),
                chinext_pct=idx.get("chinext_pct"),
            )
    except Exception as e:
        logger.debug("指数回写失败: %s", e)

    # 5. 发送邮件 + 保存报告
    if send_email:
        try:
            notifier = NotificationService()
            if notifier.is_available():
                if report_markdown:
                    report_content = report_markdown
                else:
                    report_content = notifier.generate_dashboard_report([result])
                notifier.send(report_content, email_send_to_all=True)
                notifier.save_report_to_file(report_content)
                logger.info("邮件已发送，报告已保存: %s(%s)", stock_name, code)
            else:
                logger.warning("邮件通知渠道不可用，跳过发送")
        except Exception as e:
            logger.error("邮件发送失败: %s", e)

    return history_id > 0


def save_batch(
    items: List[Dict[str, Any]],
    report_markdown: Optional[str] = None,
    send_email: bool = True,
) -> int:
    """
    批量保存分析结果（合并邮件）。

    Args:
        items: 每个元素包含 {code, name, analysis, report?}
        report_markdown: 可选的合并 Markdown 报告
        send_email: 是否发送邮件

    Returns:
        成功保存的数量
    """
    db = get_db()
    results: List[AnalysisResult] = []
    saved_count = 0

    for item in items:
        code = item.get("code", "")
        name = item.get("name", code)
        analysis = item.get("analysis") or item.get("analysis_data") or {}
        try:
            result = build_analysis_result(code, name, analysis)
            query_id = str(uuid.uuid4())
            result.query_id = query_id

            # 保存历史
            # 构建 enhanced_context，包含实时行情供 _extract_market_metrics 提取
            enhanced_context = dict(analysis.get("enhanced_context") or {})
            realtime_data = {}
            cp = analysis.get("current_price")
            if cp is not None:
                realtime_data["price"] = cp
            pct = analysis.get("change_pct")
            if pct is not None:
                realtime_data["change_pct"] = pct
            vr = analysis.get("volume_ratio")
            if vr is not None:
                realtime_data["volume_ratio"] = vr
            tr = analysis.get("turnover_rate")
            if tr is not None:
                realtime_data["turnover_rate"] = tr
            if realtime_data:
                enhanced_context["realtime"] = realtime_data
            context_snapshot = {
                "enhanced_context": enhanced_context,
                "news_content": analysis.get("news_summary", ""),
            }
            history_id = db.save_analysis_history(
                result=result,
                query_id=query_id,
                report_type="full",
                news_content=analysis.get("news_summary", ""),
                context_snapshot=context_snapshot,
                save_snapshot=True,
            )

            # 决策信号
            try:
                from src.services.decision_signal_extractor import (
                    extract_and_persist_from_analysis_result,
                )
                extract_and_persist_from_analysis_result(
                    result,
                    context_snapshot=context_snapshot,
                    source_report_id=history_id if history_id > 0 else None,
                    trace_id=query_id,
                    query_source="skill",
                    report_type="full",
                )
            except Exception:
                pass

            # 指数回写
            try:
                idx = analysis.get("index_snapshot") or {}
                if idx.get("csi2000_pct") is not None or idx.get("chinext_pct") is not None:
                    db.update_index_data_for_today(
                        code=code,
                        csi2000_pct=idx.get("csi2000_pct"),
                        chinext_pct=idx.get("chinext_pct"),
                    )
            except Exception:
                pass

            results.append(result)
            if history_id > 0:
                saved_count += 1
            logger.info("已保存: %s(%s)", name, code)
        except Exception as e:
            logger.error("保存失败: %s(%s): %s", name, code, e)

    # 合并发送邮件
    if send_email and results:
        try:
            notifier = NotificationService()
            if notifier.is_available():
                if report_markdown:
                    report_content = report_markdown
                else:
                    report_content = notifier.generate_aggregate_report(
                        results, report_type="full"
                    )
                notifier.send(report_content, email_send_to_all=True)
                notifier.save_report_to_file(report_content)
                logger.info("合并邮件已发送（%d 只股票）", len(results))
        except Exception as e:
            logger.error("合并邮件发送失败: %s", e)

    return saved_count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="保存 Qoder AI 分析结果到项目数据库 + 发送邮件"
    )
    parser.add_argument("code", help="股票代码（如 603444），或 'batch' 表示批量模式")
    parser.add_argument("-f", "--file", required=True, help="分析结果 JSON 文件路径")
    parser.add_argument("--name", default="", help="股票名称（可选，默认从 JSON 读取）")
    parser.add_argument("--report", default=None, help="Markdown 报告文件路径（可选）")
    parser.add_argument("--no-email", action="store_true", help="不发送邮件")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # 读取 JSON
    with open(args.file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 读取 Markdown 报告
    report_md = None
    if args.report:
        with open(args.report, "r", encoding="utf-8") as f:
            report_md = f.read()

    send_email = not args.no_email

    if args.code == "batch":
        # 批量模式：JSON 应为列表
        items = data if isinstance(data, list) else data.get("items", [])
        count = save_batch(items, report_markdown=report_md, send_email=send_email)
        print(f"批量保存完成: {count}/{len(items)} 成功")
    else:
        # 单只模式
        stock_name = args.name or data.get("stock_name", args.code)
        ok = save_single(
            args.code, stock_name, data,
            report_markdown=report_md, send_email=send_email,
        )
        print(f"保存{'成功' if ok else '失败'}: {stock_name}({args.code})")
