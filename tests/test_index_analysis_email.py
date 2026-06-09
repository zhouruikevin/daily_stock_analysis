# -*- coding: utf-8 -*-
"""notifier.py 邮件包装测试（离线，全 mock SMTP，不真发邮件）"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "index-analysis" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import notifier  # noqa: E402


# ============================================================
# Fixtures
# ============================================================
def _wrapped(index_key: str, confidence: str = "高置信") -> dict:
    return {
        "index_key": index_key,
        "divergence": {"index_name": {"sh": "上证", "sz": "深成", "cy": "创业"}.get(index_key, index_key)},
        "levels": {"current_price": 4057.78, "immediate_resistance": 4059.20},
        "reversal": {"confidence": confidence, "reason": "...",
                     "distance_to_resistance_pct": 0.03},
    }


# ============================================================
# 1. is_email_configured
# ============================================================
def test_is_email_configured_missing_returns_false(monkeypatch):
    monkeypatch.delenv("EMAIL_SENDER", raising=False)
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    assert notifier.is_email_configured() is False


def test_is_email_configured_partial_returns_false(monkeypatch):
    """只配了 sender 没配 password 也算未配"""
    monkeypatch.setenv("EMAIL_SENDER", "me@qq.com")
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    assert notifier.is_email_configured() is False


def test_is_email_configured_full_returns_true(monkeypatch):
    monkeypatch.setenv("EMAIL_SENDER", "me@qq.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "xxx")
    assert notifier.is_email_configured() is True


# ============================================================
# 2. build_subject
# ============================================================
def test_subject_with_high_confidence_marks_alert():
    """有高置信反转时主题应有警报标志和数量"""
    results = [_wrapped("sh"), _wrapped("sz"), _wrapped("cy", "中置信"), _wrapped("kc")]
    subj = notifier.build_subject(results, today="2026-06-05")
    assert "2026-06-05" in subj
    assert "⚠️" in subj
    assert "3/4" in subj  # 3 个高置信，共 4 个指数


def test_subject_without_high_confidence_no_alert():
    """全无高置信时主题应不带 ⚠️"""
    results = [_wrapped("sh", "无"), _wrapped("sz", "中置信")]
    subj = notifier.build_subject(results, today="2026-06-05")
    assert "⚠️" not in subj
    assert "无高置信" in subj


def test_subject_empty_results():
    """results 为空也不应崩溃"""
    subj = notifier.build_subject([], today="2026-06-05")
    assert "2026-06-05" in subj


# ============================================================
# 3. send_analysis_email
# ============================================================
def test_send_analysis_email_skips_when_unconfigured(monkeypatch, caplog):
    """未配置时应返回 False 并 warning，不抛"""
    monkeypatch.delenv("EMAIL_SENDER", raising=False)
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    with caplog.at_level("WARNING"):
        result = notifier.send_analysis_email("body", [_wrapped("sh")])
    assert result is False
    assert any("未配置" in rec.message for rec in caplog.records)


def test_send_analysis_email_invokes_email_sender(monkeypatch):
    """配置齐全时应实例化 EmailSender 并调 send_to_email"""
    monkeypatch.setenv("EMAIL_SENDER", "me@qq.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "xxx")
    monkeypatch.setenv("EMAIL_RECEIVERS", "a@x.com,b@x.com")

    calls = []

    class _FakeEmailSender:
        def __init__(self, cfg):
            self.cfg = cfg

        def send_to_email(self, content, subject=None, receivers=None):
            calls.append({"content": content, "subject": subject,
                          "receivers": receivers, "cfg_sender": self.cfg.email_sender,
                          "cfg_password": self.cfg.email_password,
                          "cfg_receivers": self.cfg.email_receivers})
            return True

    # patch import
    fake_module = SimpleNamespace(EmailSender=_FakeEmailSender)
    monkeypatch.setitem(sys.modules, "src.notification_sender.email_sender", fake_module)

    result = notifier.send_analysis_email("BODY", [_wrapped("sh"), _wrapped("cy")])
    assert result is True
    assert len(calls) == 1
    call = calls[0]
    assert call["content"] == "BODY"
    assert "⚠️" in call["subject"]  # 2 个高置信
    assert call["cfg_sender"] == "me@qq.com"
    assert call["cfg_password"] == "xxx"
    assert call["cfg_receivers"] == ["a@x.com", "b@x.com"]


def test_send_analysis_email_catches_sender_exception(monkeypatch, caplog):
    """EmailSender.send_to_email 抛异常时应被捕获、返回 False、不向外传播"""
    monkeypatch.setenv("EMAIL_SENDER", "me@qq.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "xxx")

    class _CrashingEmailSender:
        def __init__(self, cfg): pass
        def send_to_email(self, *a, **kw):
            raise RuntimeError("SMTP timeout")

    fake_module = SimpleNamespace(EmailSender=_CrashingEmailSender)
    monkeypatch.setitem(sys.modules, "src.notification_sender.email_sender", fake_module)

    with caplog.at_level("ERROR"):
        result = notifier.send_analysis_email("body", [_wrapped("sh")])
    assert result is False
    assert any("SMTP timeout" in rec.message for rec in caplog.records)


def test_send_analysis_email_returns_false_when_sender_returns_false(monkeypatch):
    """EmailSender 返回 False（鉴权失败等）时应透传"""
    monkeypatch.setenv("EMAIL_SENDER", "me@qq.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "xxx")

    class _FailingEmailSender:
        def __init__(self, cfg): pass
        def send_to_email(self, *a, **kw): return False

    fake_module = SimpleNamespace(EmailSender=_FailingEmailSender)
    monkeypatch.setitem(sys.modules, "src.notification_sender.email_sender", fake_module)

    assert notifier.send_analysis_email("body", [_wrapped("sh")]) is False


def test_send_analysis_email_uses_custom_subject_when_provided(monkeypatch):
    monkeypatch.setenv("EMAIL_SENDER", "me@qq.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "xxx")

    calls = []

    class _RecordSender:
        def __init__(self, cfg): pass
        def send_to_email(self, content, subject=None, receivers=None):
            calls.append(subject); return True

    fake_module = SimpleNamespace(EmailSender=_RecordSender)
    monkeypatch.setitem(sys.modules, "src.notification_sender.email_sender", fake_module)

    notifier.send_analysis_email("body", [_wrapped("sh")], subject="自定义主题")
    assert calls == ["自定义主题"]
