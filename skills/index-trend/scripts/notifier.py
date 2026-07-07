#!/usr/bin/env python3
"""邮件通知：趋势推演完成后把结果发到 EMAIL_RECEIVERS。

复用 src/notification_sender/email_sender.py:EmailSender（SMTP 自动识别、
Markdown→HTML、鉴权错误提示）。用 SimpleNamespace 喂最小 config，不引入主项目 Config。
未配置 EMAIL_SENDER + EMAIL_PASSWORD 时静默跳过，不阻断主流程。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DIR_CN = {"up": "上行", "down": "下行", "range": "震荡"}


def _build_min_config() -> SimpleNamespace:
    return SimpleNamespace(
        email_sender=os.getenv("EMAIL_SENDER"),
        email_password=os.getenv("EMAIL_PASSWORD"),
        email_sender_name=os.getenv("EMAIL_SENDER_NAME", "指数趋势助手"),
        email_receivers=[r.strip() for r in os.getenv("EMAIL_RECEIVERS", "").split(",") if r.strip()],
    )


def is_email_configured() -> bool:
    cfg = _build_min_config()
    return bool(cfg.email_sender and cfg.email_password)


def build_subject(results: List[Dict[str, Any]], today: Optional[str] = None) -> str:
    """主题示例：📈 指数趋势 - 2026-07-07 - 上证顺势上行(P58) | 创业板背离转震荡

    取主情景概率最高者领衔，最多再带一个显著背离/反转的指数。
    """
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    ok = [r for r in results if not r.get("error")]
    if not ok:
        return f"📈 指数趋势 - {today}"

    def _headline(r: Dict[str, Any]) -> str:
        fc = r["forecast"]
        primary = next((s for s in fc["scenarios"] if s["type"] == fc["primary_scenario"]),
                       fc["scenarios"][0])
        short = r["index_name"].replace("指数", "").replace("成指", "")
        if primary["type"] == "continuation":
            desc = f"顺势{_DIR_CN.get(primary['direction'], '')}"
        elif primary["type"] == "reversal":
            desc = f"转{_DIR_CN.get(primary['direction'], '')}"
        else:
            desc = "转震荡" if r["volume_price"]["health_label"] == "背离衰竭" else "震荡"
        return f"{short}{desc}(P{primary['probability']})"

    ranked = sorted(ok, key=lambda r: max(s["probability"] for s in r["forecast"]["scenarios"]),
                    reverse=True)
    parts = [_headline(ranked[0])]
    # 附带一个健康度差(背离衰竭)的指数以示警
    warn = next((r for r in ranked[1:] if r["volume_price"]["health_label"] == "背离衰竭"), None)
    if warn:
        parts.append(_headline(warn))
    return f"📈 指数趋势 - {today} - " + " | ".join(parts)


def send_analysis_email(content: str, results: List[Dict[str, Any]], *,
                        subject: Optional[str] = None,
                        receivers: Optional[List[str]] = None,
                        accuracy_text: Optional[str] = None) -> bool:
    """发送趋势推演邮件。返回 True=成功，False=跳过/失败。"""
    if not is_email_configured():
        logger.warning("[notifier] 未配置 EMAIL_SENDER / EMAIL_PASSWORD，跳过邮件发送")
        return False
    try:
        from src.notification_sender.email_sender import EmailSender
    except ImportError as e:
        logger.warning(f"[notifier] 无法 import EmailSender，跳过邮件: {e}")
        return False

    try:
        import markdown_format as _md
        md_content = _md.format_markdown_report(results, accuracy_text=accuracy_text)
    except Exception as e:
        logger.warning(f"[notifier] Markdown 格式化失败，回退纯文本: {e}")
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
