# -*- coding: utf-8 -*-
"""Tests for DataFetcherManager.get_index_daily fallback."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider.base import BaseFetcher, DataFetcherManager  # noqa: E402


_UNSET = object()  # 单例 sentinel：DataFrame 不能用 == 跟字符串安全比较


class _StubFetcher(BaseFetcher):
    """Minimal stub recording every call; configurable per-test."""

    def __init__(self, name: str, priority: int,
                 result: Any = _UNSET,
                 exc: Optional[Exception] = None) -> None:
        self.name = name
        self.priority = priority
        self._result = result
        self._exc = exc
        self.calls: List[Dict[str, Any]] = []

    # BaseFetcher 强制要实现的两个抽象方法
    def _fetch_raw_data(self, stock_code, start_date, end_date):  # pragma: no cover
        raise NotImplementedError

    def _normalize_data(self, df, stock_code):  # pragma: no cover
        raise NotImplementedError

    def get_index_daily(self, symbol, start_date=None,
                        end_date=None, include_today=True):
        self.calls.append({
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "include_today": include_today,
        })
        if self._exc is not None:
            raise self._exc
        if self._result is _UNSET:
            return super().get_index_daily(symbol, start_date, end_date, include_today)
        return self._result


def _make_manager(*fetchers) -> DataFetcherManager:
    """Bypass _init_default_fetchers by passing explicit list."""
    return DataFetcherManager(list(fetchers))


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "2026-06-03", "open": 4068.34, "high": 4107.05,
             "low": 4059.91, "close": 4083.97, "volume": 6.68e10, "amount": 7.5e11},
            {"date": "2026-06-04", "open": 4053.67, "high": 4080.72,
             "low": 4043.43, "close": 4057.78, "volume": 6.21e10, "amount": 1.27e12},
        ]
    )


def test_uses_highest_priority_when_succeeds():
    primary = _StubFetcher("tushare", priority=-1, result=_sample_df())
    secondary = _StubFetcher("akshare", priority=1, result=_sample_df())
    mgr = _make_manager(primary, secondary)

    df = mgr.get_index_daily("sh000001")

    assert df is not None
    assert df["date"].iloc[-1] == "2026-06-04"
    assert len(primary.calls) == 1
    # 首选成功后不应再问次源
    assert secondary.calls == []


def test_falls_back_when_primary_returns_none():
    primary = _StubFetcher("tushare", priority=-1, result=None)
    secondary = _StubFetcher("akshare", priority=1, result=_sample_df())
    mgr = _make_manager(primary, secondary)

    df = mgr.get_index_daily("sh000001")

    assert df is not None
    assert len(primary.calls) == 1
    assert len(secondary.calls) == 1


def test_falls_back_when_primary_raises(caplog):
    primary = _StubFetcher("tushare", priority=-1,
                           exc=TimeoutError("upstream slow"))
    secondary = _StubFetcher("akshare", priority=1, result=_sample_df())
    mgr = _make_manager(primary, secondary)

    with caplog.at_level("WARNING"):
        df = mgr.get_index_daily("sh000001")

    assert df is not None
    assert len(secondary.calls) == 1
    # 异常应该被记录但不抛出
    assert any("get_index_daily" in rec.message and "失败" in rec.message
               for rec in caplog.records)


def test_returns_none_when_all_sources_fail(caplog):
    primary = _StubFetcher("tushare", priority=-1, result=None)
    secondary = _StubFetcher("akshare", priority=1,
                             exc=ConnectionError("blocked"))
    tertiary = _StubFetcher("yfinance", priority=2, result=None)
    mgr = _make_manager(primary, secondary, tertiary)

    with caplog.at_level("WARNING"):
        df = mgr.get_index_daily("sh000001")

    assert df is None
    assert len(primary.calls) == 1
    assert len(secondary.calls) == 1
    assert len(tertiary.calls) == 1
    assert any("所有数据源" in rec.message for rec in caplog.records)


def test_falls_back_when_primary_returns_empty_df():
    """空 DataFrame 也应当继续 fallback，而不是被当作成功。"""
    primary = _StubFetcher("tushare", priority=-1, result=pd.DataFrame())
    secondary = _StubFetcher("akshare", priority=1, result=_sample_df())
    mgr = _make_manager(primary, secondary)

    df = mgr.get_index_daily("sh000001")

    assert df is not None
    assert len(df) == 2
    assert len(secondary.calls) == 1


def test_args_passed_through_to_fetchers():
    primary = _StubFetcher("tushare", priority=-1, result=_sample_df())
    mgr = _make_manager(primary)

    mgr.get_index_daily("sh000001", start_date="2026-05-01",
                        end_date="2026-06-04", include_today=False)

    assert primary.calls == [{
        "symbol": "sh000001",
        "start_date": "2026-05-01",
        "end_date": "2026-06-04",
        "include_today": False,
    }]


def test_priority_ordering_respected():
    """priority 大的应排后，即使在传入列表里位置靠前。"""
    high_priority = _StubFetcher("tushare", priority=-1, result=_sample_df())
    low_priority = _StubFetcher("akshare", priority=5, result=_sample_df())
    # 故意把低优先级 fetcher 放在前面
    mgr = _make_manager(low_priority, high_priority)

    mgr.get_index_daily("sh000001")

    # 应当先调用 tushare (priority=-1)
    assert len(high_priority.calls) == 1
    assert low_priority.calls == []
