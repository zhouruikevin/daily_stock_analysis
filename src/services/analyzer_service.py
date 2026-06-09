# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 分析服务层
===================================

职责：
1. 封装核心分析逻辑，支持多调用方（CLI、WebUI、Bot）
2. 提供清晰的API接口，不依赖于命令行参数
3. 支持依赖注入，便于测试和扩展
4. 统一管理分析流程和配置
"""

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from src.analyzer import AnalysisResult
from src.core.market_review import run_market_review
from src.core.pipeline import StockAnalysisPipeline
from src.config import Config, get_config
from src.enums import ReportType
from src.notification import NotificationService


def _get_default_notifier() -> Optional[NotificationService]:
    """获取默认通知服务（当未显式传入notifier时自动检测邮件配置）"""
    try:
        notifier = NotificationService()
        # 只有当至少有一个渠道可用时才返回
        if notifier.is_available():
            return notifier
    except Exception:
        pass
    return None


def analyze_stock(
    stock_code: str,
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None,
    _no_auto_notify: bool = False
) -> Optional[AnalysisResult]:
    """
    分析单只股票

    Args:
        stock_code: 股票代码
        config: 配置对象（可选，默认使用单例）
        full_report: 是否生成完整报告
        notifier: 通知服务（可选，默认自动检测邮件配置）
        _no_auto_notify: 内部参数，是否禁用自动创建 notifier（用于批量分析场景）

    Returns:
        分析结果对象
    """
    if config is None:
        config = get_config()

    # 如果未显式传入notifier且不禁用自动创建，则检测邮件配置
    if notifier is None and not _no_auto_notify:
        notifier = _get_default_notifier()

    # 创建分析流水线
    pipeline = StockAnalysisPipeline(
        config=config,
        query_id=uuid.uuid4().hex,
        query_source="cli"
    )

    # 使用通知服务（如果提供）
    if notifier:
        pipeline.notifier = notifier

    # 根据full_report参数设置报告类型
    report_type = ReportType.FULL if full_report else ReportType.SIMPLE

    # 运行单只股票分析
    result = pipeline.process_single_stock(
        code=stock_code,
        skip_analysis=False,
        single_stock_notify=notifier is not None,
        report_type=report_type,
    )

    return result


def analyze_stocks(
    stock_codes: List[str],
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None,
    merge_notification: bool = True,
    max_workers: Optional[int] = None
) -> List[AnalysisResult]:
    """
    分析多只股票（支持多线程并发）

    Args:
        stock_codes: 股票代码列表
        config: 配置对象（可选，默认使用单例）
        full_report: 是否生成完整报告
        notifier: 通知服务（可选，默认自动检测邮件配置）
        merge_notification: 是否合并通知为一封邮件（默认 True）
        max_workers: 最大并发线程数（可选，默认从配置读取，一般为3）

    Returns:
        分析结果列表
    """
    if config is None:
        config = get_config()

    # 如果未显式传入notifier，自动检测邮件配置
    if notifier is None:
        notifier = _get_default_notifier()

    # 确定并发数
    if max_workers is None:
        max_workers = getattr(config, 'max_workers', 3)

    report_type = ReportType.FULL if full_report else ReportType.SIMPLE
    results = []

    if max_workers > 1 and len(stock_codes) > 1:
        # 多线程并发分析
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"批量分析启动: {len(stock_codes)} 只股票, {max_workers} 线程并发")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_code = {
                executor.submit(
                    analyze_stock,
                    stock_code, config, full_report,
                    notifier=None,
                    _no_auto_notify=True
                ): stock_code
                for stock_code in stock_codes
            }

            for future in as_completed(future_to_code):
                code = future_to_code[future]
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"分析 {code} 失败: {e}")
    else:
        # 单线程串行分析
        for stock_code in stock_codes:
            result = analyze_stock(
                stock_code, config, full_report,
                notifier=None,
                _no_auto_notify=True
            )
            if result:
                results.append(result)

    # 合并通知: 所有股票分析完成后,生成汇总报告一次性发送
    if merge_notification and notifier and results:
        try:
            aggregate_report = notifier.generate_aggregate_report(
                results, report_type
            )
            if notifier.is_available():
                notifier.send(aggregate_report, email_send_to_all=True)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"合并发送通知失败: {e}")

    return results


def perform_market_review(
    config: Config = None,
    notifier: Optional[NotificationService] = None,
) -> Optional[str]:
    """
    执行大盘复盘

    Args:
        config: 配置对象（可选，默认使用单例）
        notifier: 通知服务（可选，默认自动检测邮件配置）

    Returns:
        复盘报告内容
    """
    if config is None:
        config = get_config()

    # 如果未显式传入notifier，自动检测邮件配置
    if notifier is None:
        notifier = _get_default_notifier()

    # 创建分析流水线以获取analyzer和search_service
    pipeline = StockAnalysisPipeline(
        config=config,
        query_id=uuid.uuid4().hex,
        query_source="cli",
    )

    # 使用提供的通知服务或创建新的
    review_notifier = notifier or pipeline.notifier

    # 调用大盘复盘函数
    return run_market_review(
        notifier=review_notifier,
        analyzer=pipeline.analyzer,
        search_service=pipeline.search_service,
    )
