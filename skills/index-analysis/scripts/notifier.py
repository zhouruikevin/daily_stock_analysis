#!/usr/bin/env python3
"""邮件通知：分析完成后把完整文本输出发到 EMAIL_RECEIVERS。

复用 src/notification_sender/email_sender.py:EmailSender —— 它已经处理了：
- SMTP 自动识别（QQ / 163 / Gmail 等）
- Markdown 自动转 HTML（确保终端等宽内容在邮件里也对齐）
- 鉴权 / 连接 错误的可读提示

skill 不引入主项目 Config 重型依赖，而是用 SimpleNamespace 包一份最小 config 喂给 EmailSender
（EmailSender.__init__ 只读 4 个属性：email_sender / email_password / email_sender_name / email_receivers）。

未配置 EMAIL_SENDER + EMAIL_PASSWORD 时静默跳过（warning），不阻断主流程。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _build_min_config() -> SimpleNamespace:
    """从环境变量构造最小 config，供 EmailSender 消费。"""
    return SimpleNamespace(
        email_sender=os.getenv("EMAIL_SENDER"),
        email_password=os.getenv("EMAIL_PASSWORD"),
        email_sender_name=os.getenv("EMAIL_SENDER_NAME", "指数分析助手"),
        email_receivers=[r.strip() for r in os.getenv("EMAIL_RECEIVERS", "").split(",") if r.strip()],
    )


def is_email_configured() -> bool:
    """是否最小配置齐全：EMAIL_SENDER 和 EMAIL_PASSWORD 都非空。

    EMAIL_RECEIVERS 可留空（EmailSender 内部会回退到发给自己）。
    """
    cfg = _build_min_config()
    return bool(cfg.email_sender and cfg.email_password)


def _count_high_confidence(results: List[Dict[str, Any]]) -> int:
    """统计 mode=both 结果里高置信反转的指数数。"""
    n = 0
    for w in results:
        rev = w.get("reversal") or {}
        if rev.get("confidence") == "高置信":
            n += 1
    return n


def build_subject(results: List[Dict[str, Any]],
                  today: Optional[str] = None) -> str:
    """主题示例：📊 指数分析 - 2026-06-05 - ⚠️ 3/4 高置信反转

    高置信数为 0 时去掉警报标志，避免 inbox 视觉污染。
    """
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    total = len(results)
    high = _count_high_confidence(results)
    if total == 0:
        return f"📊 指数分析 - {today}"
    if high == 0:
        return f"📊 指数分析 - {today} - 无高置信信号 ({total} 指数)"
    return f"📊 指数分析 - {today} - ⚠️ {high}/{total} 高置信反转"


def send_analysis_email(content: str,
                        results: List[Dict[str, Any]],
                        *,
                        subject: Optional[str] = None,
                        receivers: Optional[List[str]] = None,
                        snapshots: Optional[List[Dict[str, Any]]] = None,
                        index_keys: Optional[List[str]] = None) -> bool:
    """发送分析邮件。返回 True 表示发送成功，False 表示跳过 / 失败。

    Args:
        content: 终端纯文本输出（作为纯文本 fallback）
        results: mode=both 的 wrapped_results，用于推导主题 & 生成 Markdown
        subject: 自定义主题（不传则自动生成）
        receivers: 自定义收件人（不传则用 EMAIL_RECEIVERS / 发件人自身）
        snapshots: 历史 snapshot 列表（可选，传入则在邮件末尾附加历史变化表）
        index_keys: 指数 key 列表（可选，用于历史表过滤）

    邮件正文使用结构化 Markdown（经 markdown_format.py 生成），
    由 EmailSender 的 markdown_to_html_document() 渲染为 HTML 表格+标题排版。
    终端纯文本 content 仅作为 MIME multipart/alternative 的纯文本部分保留。

    错误处理：未配置 → warning 跳过；SMTP 失败 → error log，但不抛出。
    """
    if not is_email_configured():
        logger.warning("[notifier] 未配置 EMAIL_SENDER / EMAIL_PASSWORD，跳过邮件发送")
        return False

    # 延迟 import：避免在不需要发邮件时拉主项目依赖
    try:
        from src.notification_sender.email_sender import EmailSender
    except ImportError as e:
        logger.warning(f"[notifier] 无法 import EmailSender（仓库依赖缺失），跳过邮件: {e}")
        return False

    # 生成结构化 Markdown（邮件 HTML 渲染用）
    try:
        import markdown_format as _md
        md_content = _md.format_markdown_report(
            results,
            snapshots=snapshots,
            index_keys=index_keys,
        )
    except Exception as e:
        logger.warning(f"[notifier] Markdown 格式化失败，回退到终端纯文本: {e}")
        md_content = content

    cfg = _build_min_config()
    sender = EmailSender(cfg)
    if subject is None:
        subject = build_subject(results)

    try:
        ok = sender.send_to_email(md_content, subject=subject, receivers=receivers)
        if ok:
            logger.info(f"[notifier] 邮件已发送，主题: {subject}")
        return ok
    except Exception as e:
        logger.error(f"[notifier] 发送异常: {e}")
        return False


__all__ = ["is_email_configured", "build_subject", "send_analysis_email"]
