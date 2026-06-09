# -*- coding: utf-8 -*-
"""Tests for AkshareFetcher.get_index_daily (history + today spot stitching)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider import akshare_fetcher as akf  # noqa: E402
from data_provider.akshare_fetcher import AkshareFetcher  # noqa: E402


@pytest.fixture
def fetcher(monkeypatch) -> AkshareFetcher:
    f = AkshareFetcher.__new__(AkshareFetcher)
    f.sleep_min = 0.0
    f.sleep_max = 0.0
    f._last_request_time = None
    f._history_call_timeout = 1.0
    # 关掉真实的 sleep / UA 噪音，专注业务逻辑
    monkeypatch.setattr(f, "_set_random_user_agent", lambda: None)
    monkeypatch.setattr(f, "_enforce_rate_limit", lambda: None)
    # 跳过 multiprocessing，直接同步调用以便 mock 生效
    monkeypatch.setattr(
        akf,
        "_akshare_call_with_timeout",
        lambda func, *args, timeout=None, call_name="", **kwargs: func(*args, **kwargs),
    )
    return f


def _hist_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "2026-06-01", "open": 4067.16, "close": 4057.74,
             "high": 4093.04, "low": 4045.69, "volume": 6.76e10},
            {"date": "2026-06-02", "open": 4061.46, "close": 4075.10,
             "high": 4089.58, "low": 4032.58, "volume": 6.42e10},
            {"date": "2026-06-03", "open": 4068.34, "close": 4083.97,
             "high": 4107.05, "low": 4059.91, "volume": 6.68e10},
        ]
    )


def _spot_df(today_close: float = 4057.78) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"代码": "sh000001", "名称": "上证指数", "最新价": today_close,
             "涨跌额": -26.19, "涨跌幅": -0.64, "昨收": 4083.97,
             "今开": 4053.67, "最高": 4080.72, "最低": 4043.43,
             "成交量": 621194774, "成交额": 1.27e12},
            {"代码": "sh000016", "名称": "上证50", "最新价": 0,
             "涨跌额": 0, "涨跌幅": 0, "昨收": 0,
             "今开": 0, "最高": 0, "最低": 0, "成交量": 0, "成交额": 0},
        ]
    )


def _patch_today(monkeypatch, date_str: str) -> None:
    class _FakeDateTime:
        @classmethod
        def now(cls):
            return SimpleNamespace(strftime=lambda fmt: date_str)
    monkeypatch.setattr(akf, "datetime", _FakeDateTime)


def _patch_akshare(monkeypatch, hist=None, spot=None,
                   hist_exc: Optional[Exception] = None,
                   spot_exc: Optional[Exception] = None) -> None:
    """Patch ak.stock_zh_index_daily / spot_sina via sys.modules so import inside
    the method picks up our fakes."""
    import sys

    def _daily(symbol):
        if hist_exc is not None:
            raise hist_exc
        return hist

    def _spot():
        if spot_exc is not None:
            raise spot_exc
        return spot

    fake_ak = SimpleNamespace(
        stock_zh_index_daily=_daily,
        stock_zh_index_spot_sina=_spot,
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)


def test_appends_today_when_history_missing_today(fetcher, monkeypatch):
    _patch_today(monkeypatch, "2026-06-04")
    _patch_akshare(monkeypatch, hist=_hist_df(), spot=_spot_df())

    df = fetcher.get_index_daily("sh000001")

    assert df is not None
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]
    assert df["date"].tolist() == ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]
    last = df.iloc[-1]
    assert last["open"] == pytest.approx(4053.67)
    assert last["high"] == pytest.approx(4080.72)
    assert last["low"] == pytest.approx(4043.43)
    assert last["close"] == pytest.approx(4057.78)
    # spot 的「成交量」单位是手，须 ×100 对齐历史接口的「股」单位
    assert last["volume"] == pytest.approx(621194774 * 100)
    assert last["amount"] == pytest.approx(1.27e12)


def test_does_not_duplicate_when_history_already_has_today(fetcher, monkeypatch):
    _patch_today(monkeypatch, "2026-06-03")  # 今天 == 历史末日
    _patch_akshare(monkeypatch, hist=_hist_df(), spot=_spot_df())

    df = fetcher.get_index_daily("sh000001")

    assert df is not None
    assert df["date"].tolist() == ["2026-06-01", "2026-06-02", "2026-06-03"]
    # 末日仍是历史那根，没有被 spot 覆盖
    assert df.iloc[-1]["close"] == pytest.approx(4083.97)


def test_include_today_false_skips_spot(fetcher, monkeypatch):
    _patch_today(monkeypatch, "2026-06-04")
    spot_calls: List[int] = []

    def _spot_raise():
        spot_calls.append(1)
        raise AssertionError("spot 不应被调用")

    import sys
    fake_ak = SimpleNamespace(
        stock_zh_index_daily=lambda symbol: _hist_df(),
        stock_zh_index_spot_sina=_spot_raise,
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    df = fetcher.get_index_daily("sh000001", include_today=False)

    assert df is not None
    assert df["date"].iloc[-1] == "2026-06-03"
    assert spot_calls == []


def test_spot_failure_falls_back_to_history_only(fetcher, monkeypatch, caplog):
    _patch_today(monkeypatch, "2026-06-04")
    _patch_akshare(monkeypatch, hist=_hist_df(),
                   spot_exc=ConnectionError("spot 接口被风控"))

    with caplog.at_level("WARNING"):
        df = fetcher.get_index_daily("sh000001")

    assert df is not None
    assert df["date"].tolist() == ["2026-06-01", "2026-06-02", "2026-06-03"]
    assert any("今日 spot 拼接失败" in rec.message for rec in caplog.records)


def test_history_failure_returns_none(fetcher, monkeypatch, caplog):
    _patch_today(monkeypatch, "2026-06-04")
    _patch_akshare(monkeypatch, hist_exc=TimeoutError("history timeout"))

    with caplog.at_level("ERROR"):
        df = fetcher.get_index_daily("sh000001")

    assert df is None
    assert any("拉取指数" in rec.message for rec in caplog.records)


def test_date_range_filter(fetcher, monkeypatch):
    _patch_today(monkeypatch, "2026-06-04")
    _patch_akshare(monkeypatch, hist=_hist_df(), spot=_spot_df())

    df = fetcher.get_index_daily(
        "sh000001", start_date="2026-06-02", end_date="2026-06-03"
    )

    assert df is not None
    assert df["date"].tolist() == ["2026-06-02", "2026-06-03"]


def test_empty_symbol_returns_none(fetcher):
    assert fetcher.get_index_daily("") is None


def test_spot_with_all_zero_price_is_skipped(fetcher, monkeypatch):
    """spot 接口返回了行但全是 0（如未开盘）不应拼接。"""
    _patch_today(monkeypatch, "2026-06-04")
    zero_spot = pd.DataFrame(
        [{"代码": "sh000001", "名称": "上证指数", "最新价": 0,
          "涨跌额": 0, "涨跌幅": 0, "昨收": 0,
          "今开": 0, "最高": 0, "最低": 0, "成交量": 0, "成交额": 0}]
    )
    _patch_akshare(monkeypatch, hist=_hist_df(), spot=zero_spot)

    df = fetcher.get_index_daily("sh000001")

    assert df is not None
    assert df["date"].iloc[-1] == "2026-06-03"  # 没拼今天
