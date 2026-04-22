# -*- coding: utf-8 -*-
"""
Tavily Key 故障切换单元测试

覆盖范围：
- KeyBlacklist：持久化黑名单管理（基本功能、持久化、月度过期）
- BaseSearchProvider._is_quota_exhausted()：配额耗尽错误识别
- BaseSearchProvider._execute_search()：配额耗尽时自动重试
- BaseSearchProvider._get_next_key()：跳过黑名单 Key
"""

import json
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.search_service import BaseSearchProvider, KeyBlacklist, SearchResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubProvider(BaseSearchProvider):
    """最小具体子类，仅实现 _do_search 以便测试 _execute_search"""

    def __init__(self, api_keys, name="stub"):
        super().__init__(api_keys, name)

    def _do_search(self, query, api_key, max_results, days=7, **kwargs):
        # 默认返回成功；测试中会用 mock 替换
        return SearchResponse(
            query=query, results=[], provider=self._name, success=True
        )


def _make_success_response(query="test", provider="stub"):
    return SearchResponse(
        query=query, results=[], provider=provider, success=True
    )


def _make_failure_response(query="test", provider="stub", error="unknown error"):
    return SearchResponse(
        query=query, results=[], provider=provider, success=False, error_message=error
    )


# ===================================================================
# 1. KeyBlacklist 基本功能
# ===================================================================


class TestKeyBlacklistBasic:
    """KeyBlacklist 基本功能测试"""

    def test_mark_and_check_exhausted(self, tmp_path):
        """mark_exhausted 后 is_exhausted 返回 True"""
        path = str(tmp_path / "blacklist.json")
        bl = KeyBlacklist(path=path)
        key = "tvly-dev-abcdef123456"
        bl.mark_exhausted(key)
        assert bl.is_exhausted(key) is True

    def test_not_exhausted_by_default(self, tmp_path):
        """未标记的 Key 返回 False"""
        path = str(tmp_path / "blacklist.json")
        bl = KeyBlacklist(path=path)
        assert bl.is_exhausted("tvly-dev-nevermarked") is False

    def test_expired_entry_auto_cleanup(self, tmp_path):
        """过期条目自动清理：手动设置过期时间为过去，验证 is_exhausted 返回 False"""
        path = str(tmp_path / "blacklist.json")
        bl = KeyBlacklist(path=path)
        key = "tvly-dev-expiredkey1"

        # 先标记
        bl.mark_exhausted(key)
        assert bl.is_exhausted(key) is True

        # 手动修改 JSON 文件，将 expires_at 设为过去
        with open(path, "r") as f:
            data = json.load(f)

        prefix = key[:16]
        data[prefix]["expires_at"] = "2000-01-01T00:00:00"

        with open(path, "w") as f:
            json.dump(data, f)

        # 重新加载
        bl2 = KeyBlacklist(path=path)
        assert bl2.is_exhausted(key) is False

        # 验证文件已清理
        with open(path, "r") as f:
            saved = json.load(f)
        assert prefix not in saved


# ===================================================================
# 2. KeyBlacklist 持久化
# ===================================================================


class TestKeyBlacklistPersistence:
    """KeyBlacklist 持久化测试"""

    def test_persistence_across_instances(self, tmp_path):
        """第一个实例 mark_exhausted，第二个实例（同路径）能读到"""
        path = str(tmp_path / "blacklist.json")
        key = "tvly-dev-persistkey1"

        bl1 = KeyBlacklist(path=path)
        bl1.mark_exhausted(key)

        bl2 = KeyBlacklist(path=path)
        assert bl2.is_exhausted(key) is True

    def test_missing_file_graceful(self, tmp_path):
        """文件不存在时正常初始化"""
        path = str(tmp_path / "nonexistent" / "blacklist.json")
        bl = KeyBlacklist(path=path)
        # 不应抛异常，且 is_exhausted 返回 False
        assert bl.is_exhausted("tvly-dev-anykey") is False


# ===================================================================
# 3. KeyBlacklist 月度过期
# ===================================================================


class TestKeyBlacklistMonthlyExpiration:
    """KeyBlacklist 月度过期测试"""

    def test_monthly_expiration(self, tmp_path):
        """mock datetime.now 为月末（非12月），验证 expires_at 为下月1号"""
        path = str(tmp_path / "blacklist.json")
        key = "tvly-dev-monthtest1"

        # Mock datetime.now 为 2026-03-15
        fake_now = datetime(2026, 3, 15, 10, 0, 0)
        with patch("src.search_service.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            bl = KeyBlacklist(path=path)
            bl.mark_exhausted(key)

        # 读取文件检查 expires_at
        with open(path, "r") as f:
            data = json.load(f)

        prefix = key[:16]
        assert prefix in data
        # 3月 -> 下月1号应为 2026-04-01
        assert data[prefix]["expires_at"] == "2026-04-01T00:00:00"

    def test_december_year_rollover(self, tmp_path):
        """12月标记，验证过期时间为次年1月1日"""
        path = str(tmp_path / "blacklist.json")
        key = "tvly-dev-dectest12"

        # Mock datetime.now 为 2026-12-20
        fake_now = datetime(2026, 12, 20, 10, 0, 0)
        with patch("src.search_service.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            bl = KeyBlacklist(path=path)
            bl.mark_exhausted(key)

        # 读取文件检查 expires_at
        with open(path, "r") as f:
            data = json.load(f)

        prefix = key[:16]
        assert prefix in data
        # 12月 -> 次年1月1号
        assert data[prefix]["expires_at"] == "2027-01-01T00:00:00"


# ===================================================================
# 4. _is_quota_exhausted 识别
# ===================================================================


class TestIsQuotaExhausted:
    """BaseSearchProvider._is_quota_exhausted 测试"""

    def test_quota_exhausted_patterns(self):
        """测试各种配额耗尽错误消息匹配"""
        patterns = [
            "HTTP 432 Too Many Requests",
            "This exceeds your plan limit",
            "usage limit reached for this month",
            "rate limit exceeded",
            "quota exceeded for API key",
            "[QUOTA_EXHAUSTED] monthly limit reached",
        ]
        for msg in patterns:
            assert BaseSearchProvider._is_quota_exhausted(msg) is True, f"应匹配: {msg}"

    def test_non_quota_errors(self):
        """超时、连接错误等不应被识别为配额耗尽"""
        non_quota_msgs = [
            "Connection timed out after 30s",
            "ConnectionError: Failed to establish connection",
            "SSL: CERTIFICATE_VERIFY_FAILED",
            "Internal Server Error",
            "invalid api key",
            "",
            None,
        ]
        for msg in non_quota_msgs:
            assert BaseSearchProvider._is_quota_exhausted(msg or "") is False, f"不应匹配: {msg}"


# ===================================================================
# 5. _execute_search 自动重试
# ===================================================================


class TestExecuteSearchFailover:
    """BaseSearchProvider._execute_search 自动重试测试"""

    def test_failover_on_quota_exhausted(self, tmp_path):
        """配置 3 个 Key，第一个返回配额耗尽，验证自动切换到下一个 Key 并成功"""
        keys = ["tvly-dev-key001aaa", "tvly-dev-key002bbb", "tvly-dev-key003ccc"]
        # 使用独立的 KeyBlacklist 以避免类级别单例干扰
        provider = _StubProvider(keys, name="failover_test")
        provider._blacklist = KeyBlacklist(path=str(tmp_path / "bl.json"))

        call_log = []

        def fake_do_search(query, api_key, max_results, days=7, **kwargs):
            call_log.append(api_key)
            if api_key == keys[0]:
                return _make_failure_response(
                    error="HTTP 432: quota exceeded"
                )
            return _make_success_response()

        provider._do_search = fake_do_search

        response = provider._execute_search("test query")

        assert response.success is True
        # 第一个 Key 被调用且失败，第二个 Key 被调用且成功
        assert keys[0] in call_log
        assert any(k != keys[0] for k in call_log)

    def test_all_keys_exhausted_returns_failure(self, tmp_path):
        """所有 Key 都配额耗尽，验证返回失败"""
        keys = ["tvly-dev-key101aaa", "tvly-dev-key102bbb", "tvly-dev-key103ccc"]
        provider = _StubProvider(keys, name="all_exhausted_test")
        provider._blacklist = KeyBlacklist(path=str(tmp_path / "bl.json"))

        def fake_do_search(query, api_key, max_results, days=7, **kwargs):
            return _make_failure_response(
                error=f"[QUOTA_EXHAUSTED] key {api_key[:8]} quota used up"
            )

        provider._do_search = fake_do_search

        response = provider._execute_search("test query")

        assert response.success is False
        # 错误消息应反映配额耗尽
        assert response.error_message is not None

    def test_temp_error_no_retry(self, tmp_path):
        """临时错误（如超时）不触发重试，直接返回"""
        keys = ["tvly-dev-key201aaa", "tvly-dev-key202bbb"]
        provider = _StubProvider(keys, name="temp_error_test")
        provider._blacklist = KeyBlacklist(path=str(tmp_path / "bl.json"))

        call_count = [0]

        def fake_do_search(query, api_key, max_results, days=7, **kwargs):
            call_count[0] += 1
            return _make_failure_response(
                error="Connection timed out after 30s"
            )

        provider._do_search = fake_do_search

        response = provider._execute_search("test query")

        assert response.success is False
        # 临时错误不触发重试，应该只调用一次
        assert call_count[0] == 1


# ===================================================================
# 6. _get_next_key 跳过黑名单
# ===================================================================


class TestGetNextKeySkipBlacklist:
    """BaseSearchProvider._get_next_key 跳过黑名单测试"""

    def test_skip_blacklisted_key(self, tmp_path):
        """将一个 Key 加入黑名单，验证 _get_next_key 跳过它"""
        keys = ["tvly-dev-key301aaa", "tvly-dev-key302bbb", "tvly-dev-key303ccc"]
        provider = _StubProvider(keys, name="skip_test")
        provider._blacklist = KeyBlacklist(path=str(tmp_path / "bl.json"))

        # 将第一个 Key 加入黑名单
        provider._blacklist.mark_exhausted(keys[0])

        # 多次获取，确保黑名单 Key 被跳过
        returned_keys = set()
        for _ in range(20):
            k = provider._get_next_key()
            if k:
                returned_keys.add(k)

        assert keys[0] not in returned_keys, "黑名单中的 Key 不应被返回"
        assert keys[1] in returned_keys or keys[2] in returned_keys, "应返回非黑名单 Key"

    def test_all_blacklisted_returns_none(self, tmp_path):
        """所有 Key 都在黑名单中，返回 None"""
        keys = ["tvly-dev-key401aaa", "tvly-dev-key402bbb"]
        provider = _StubProvider(keys, name="all_bl_test")
        provider._blacklist = KeyBlacklist(path=str(tmp_path / "bl.json"))

        # 将所有 Key 加入黑名单
        for key in keys:
            provider._blacklist.mark_exhausted(key)

        result = provider._get_next_key()
        assert result is None
