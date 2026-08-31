# -*- coding: utf-8 -*-
"""Tests for AkshareFetcher index daily behaviors.

Covers two suites:
1. get_index_daily history + today spot stitching (include_today semantics).
2. Index daily routing via get_daily_data/_fetch_index_data and index name lookup.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider import akshare_fetcher as akf  # noqa: E402
from data_provider.akshare_fetcher import AkshareFetcher  # noqa: E402
from data_provider.base import DataFetchError, RateLimitError, STANDARD_COLUMNS  # noqa: E402


# ============================================================
# Suite 1: get_index_daily（history + today spot stitching）
# ============================================================

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


# ============================================================
# Suite 2: index daily routing & index name lookup（upstream）
# ============================================================

def _make_fetcher() -> AkshareFetcher:
    with patch(
        "data_provider.akshare_fetcher.get_config",
        return_value=SimpleNamespace(enable_eastmoney_patch=False),
    ):
        return AkshareFetcher(sleep_min=0, sleep_max=0)


def _call_akshare_inline(func, *args, timeout=None, call_name="", **kwargs):
    return func(*args, **kwargs)


def test_akshare_recognized_index_uses_index_daily_api_and_standard_columns() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-08-20", "2026-08-21"],
            "open": [100.0, 101.0],
            "close": [101.0, 102.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "volume": [1000, 1100],
            "amount": [101000.0, 112200.0],
        }
    )
    index_daily = MagicMock(return_value=raw)
    fake_akshare = types.SimpleNamespace(stock_zh_index_daily_em=index_daily)
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
        fetcher, "_set_random_user_agent"
    ), patch.object(fetcher, "_enforce_rate_limit"), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ) as timeout_call:
        df = fetcher.get_daily_data(
            "sh000016", start_date="2026-08-01", end_date="2026-08-21"
        )

    index_daily.assert_called_once_with(
        symbol="sh000016", start_date="20260801", end_date="20260821"
    )
    timeout_call.assert_called_once_with(
        index_daily,
        timeout=fetcher._history_call_timeout,
        call_name="ak.stock_zh_index_daily_em",
        symbol="sh000016",
        start_date="20260801",
        end_date="20260821",
    )
    assert set(STANDARD_COLUMNS).issubset(df.columns)
    assert set(["code", "ma5", "ma10", "ma20"]).issubset(df.columns)
    assert df["code"].tolist() == ["sh000016", "sh000016"]
    assert df["pct_chg"].round(2).tolist() == [0.0, 0.99]


def test_akshare_index_daily_sorts_and_handles_missing_amount_and_infinite_pct() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-08-21", "2026-08-20"],
            "open": [10.0, 0.0],
            "close": [10.0, 0.0],
            "high": [11.0, 0.0],
            "low": [9.0, 0.0],
            "volume": [1000, 900],
        }
    )
    fake_akshare = types.SimpleNamespace(
        stock_zh_index_daily_em=MagicMock(return_value=raw)
    )
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ), patch.object(fetcher, "_set_random_user_agent"), patch.object(
        fetcher, "_enforce_rate_limit"
    ):
        result = fetcher._fetch_index_data(
            "sh000016", "2026-08-01", "2026-08-21"
        )

    assert result["date"].tolist() == ["2026-08-20", "2026-08-21"]
    assert "amount" in result.columns
    assert result["amount"].isna().all()
    assert result["pct_chg"].iloc[0] == 0.0
    assert pd.isna(result["pct_chg"].iloc[1])


def test_akshare_index_daily_rejects_invalid_required_schema() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-08-21"],
            "open": [10.0],
            "close": [10.0],
            "high": [11.0],
            "low": [9.0],
        }
    )
    fake_akshare = types.SimpleNamespace(
        stock_zh_index_daily_em=MagicMock(return_value=raw)
    )
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ), patch.object(fetcher, "_set_random_user_agent"), patch.object(
        fetcher, "_enforce_rate_limit"
    ), pytest.raises(DataFetchError, match="volume"):
        fetcher._fetch_index_data("sh000016", "2026-08-01", "2026-08-21")


def test_akshare_index_daily_rejects_unparseable_dates() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-08-20", "not-a-date"],
            "open": [10.0, 10.1],
            "close": [10.1, 10.2],
            "high": [10.2, 10.3],
            "low": [9.9, 10.0],
            "volume": [1000, 1100],
        }
    )
    fake_akshare = types.SimpleNamespace(
        stock_zh_index_daily_em=MagicMock(return_value=raw)
    )
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ), patch.object(fetcher, "_set_random_user_agent"), patch.object(
        fetcher, "_enforce_rate_limit"
    ), pytest.raises(DataFetchError, match="date"):
        fetcher._fetch_index_data("sh000016", "2026-08-01", "2026-08-21")


@pytest.mark.parametrize("error_type", [ConnectionError, TimeoutError])
def test_akshare_index_daily_preserves_retryable_builtin_errors(error_type) -> None:
    fake_akshare = types.SimpleNamespace(stock_zh_index_daily_em=object())
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=error_type("retry me"),
    ), patch.object(fetcher, "_set_random_user_agent"), patch.object(
        fetcher, "_enforce_rate_limit"
    ), pytest.raises(error_type, match="retry me"):
        fetcher._fetch_index_data("sh000016", "2026-08-01", "2026-08-21")


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (RuntimeError("rate limit reached"), RateLimitError),
        (ValueError("bad payload"), DataFetchError),
    ],
)
def test_akshare_index_daily_classifies_non_retryable_errors(
    error, expected_type
) -> None:
    fake_akshare = types.SimpleNamespace(stock_zh_index_daily_em=object())
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=error,
    ), patch.object(fetcher, "_set_random_user_agent"), patch.object(
        fetcher, "_enforce_rate_limit"
    ), pytest.raises(expected_type):
        fetcher._fetch_index_data("sh000016", "2026-08-01", "2026-08-21")


def test_akshare_generic_normalization_does_not_fill_index_only_columns() -> None:
    fetcher = _make_fetcher()
    raw = pd.DataFrame(
        {
            "日期": ["2026-08-21"],
            "开盘": [10.0],
            "收盘": [10.2],
            "最高": [10.5],
            "最低": [9.8],
            "成交量": [1000],
        }
    )

    result = fetcher._normalize_data(raw, "600519")

    assert "amount" not in result.columns
    assert "pct_chg" not in result.columns


def test_akshare_bare_conflict_code_stays_on_stock_api() -> None:
    fetcher = _make_fetcher()
    stock_result = pd.DataFrame({"日期": ["2026-08-21"]})

    with patch.object(
        fetcher, "_fetch_stock_data", return_value=stock_result
    ) as fetch_stock, patch.object(
        fetcher, "_fetch_index_data", return_value=pd.DataFrame()
    ) as fetch_index:
        result = fetcher._fetch_raw_data("000016", "2026-08-01", "2026-08-21")

    assert result is stock_result
    fetch_stock.assert_called_once_with("000016", "2026-08-01", "2026-08-21")
    fetch_index.assert_not_called()


def test_akshare_index_name_filters_exchange_spot_table() -> None:
    spot = MagicMock(
        return_value=pd.DataFrame(
            {
                "代码": ["000001", "000016"],
                "名称": ["上证指数", "上证50"],
            }
        )
    )
    fake_akshare = types.SimpleNamespace(stock_zh_index_spot_em=spot)
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
        fetcher, "_set_random_user_agent"
    ), patch.object(fetcher, "_enforce_rate_limit"), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ) as timeout_call:
        name = fetcher.get_stock_name("sh000016")

    assert name == "上证50"
    spot.assert_called_once_with(symbol="上证系列指数")
    timeout_call.assert_called_once_with(
        spot,
        timeout=fetcher._history_call_timeout,
        call_name="ak.stock_zh_index_spot_em",
        symbol="上证系列指数",
    )


def test_akshare_index_name_uses_shenzhen_spot_table() -> None:
    spot = MagicMock(
        return_value=pd.DataFrame({"代码": [399001], "名称": ["深证成指"]})
    )
    fake_akshare = types.SimpleNamespace(stock_zh_index_spot_em=spot)
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
        fetcher, "_set_random_user_agent"
    ), patch.object(fetcher, "_enforce_rate_limit"), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ):
        name = fetcher.get_stock_name("sz399001")

    assert name == "深证成指"
    spot.assert_called_once_with(symbol="深证系列指数")


def test_akshare_index_name_rejects_missing_name_value() -> None:
    spot = MagicMock(
        return_value=pd.DataFrame({"代码": ["000016"], "名称": [pd.NA]})
    )
    fake_akshare = types.SimpleNamespace(stock_zh_index_spot_em=spot)
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
        fetcher, "_set_random_user_agent"
    ), patch.object(fetcher, "_enforce_rate_limit"), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ):
        name = fetcher.get_stock_name("sh000016")

    assert name is None


def test_akshare_index_name_uses_first_non_blank_duplicate() -> None:
    spot = MagicMock(
        return_value=pd.DataFrame(
            {
                "代码": ["000016", "000016", "000016"],
                "名称": [pd.NA, "   ", "上证50"],
            }
        )
    )
    fake_akshare = types.SimpleNamespace(stock_zh_index_spot_em=spot)
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
        fetcher, "_set_random_user_agent"
    ), patch.object(fetcher, "_enforce_rate_limit"), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ):
        name = fetcher.get_stock_name("sh000016")

    assert name == "上证50"
