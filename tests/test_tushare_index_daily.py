# -*- coding: utf-8 -*-
"""Tests for TushareFetcher.get_index_daily (Pro index_daily + optional rt_idx_k stitching)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider.tushare_fetcher import TushareFetcher  # noqa: E402


class _FakeApi:
    def __init__(
        self,
        index_daily_df: Optional[pd.DataFrame] = None,
        index_daily_exc: Optional[Exception] = None,
        rt_idx_k_df: Optional[pd.DataFrame] = None,
        rt_idx_k_exc: Optional[Exception] = None,
        has_rt_idx_k: bool = True,
    ) -> None:
        self.index_daily_df = index_daily_df
        self.index_daily_exc = index_daily_exc
        self.rt_idx_k_df = rt_idx_k_df
        self.rt_idx_k_exc = rt_idx_k_exc
        self.index_daily_calls: List[Dict[str, Any]] = []
        self.rt_idx_k_calls: List[Dict[str, Any]] = []
        if not has_rt_idx_k:
            # 模拟自研 HTTP client 不支持 rt_idx_k：删掉属性触发 AttributeError
            pass

    def index_daily(self, **kwargs) -> pd.DataFrame:
        self.index_daily_calls.append(kwargs)
        if self.index_daily_exc is not None:
            raise self.index_daily_exc
        return self.index_daily_df

    def rt_idx_k(self, **kwargs) -> pd.DataFrame:
        self.rt_idx_k_calls.append(kwargs)
        if self.rt_idx_k_exc is not None:
            raise self.rt_idx_k_exc
        return self.rt_idx_k_df


def _make_fetcher(api: Optional[_FakeApi], now: datetime) -> TushareFetcher:
    f = TushareFetcher.__new__(TushareFetcher)
    f._api = api
    f.rate_limit_per_minute = 1000
    f._call_count = 0
    f._minute_start = None
    # 固定 "now" 以便比较日期
    f._get_china_now = lambda: now  # type: ignore[assignment]
    return f


def _hist_df() -> pd.DataFrame:
    # Tushare index_daily 返回降序，按真实接口造样本
    return pd.DataFrame(
        [
            {"ts_code": "000001.SH", "trade_date": "20260603",
             "open": 4068.34, "high": 4107.05, "low": 4059.91, "close": 4083.97,
             "pre_close": 4075.10, "change": 8.87, "pct_chg": 0.22,
             "vol": 668452630, "amount": 7.5e8},
            {"ts_code": "000001.SH", "trade_date": "20260602",
             "open": 4061.46, "high": 4089.58, "low": 4032.58, "close": 4075.10,
             "pre_close": 4057.74, "change": 17.36, "pct_chg": 0.43,
             "vol": 642244660, "amount": 7.2e8},
            {"ts_code": "000001.SH", "trade_date": "20260601",
             "open": 4067.16, "high": 4093.04, "low": 4045.69, "close": 4057.74,
             "pre_close": 4083.97, "change": -26.23, "pct_chg": -0.64,
             "vol": 676025860, "amount": 7.6e8},
        ]
    )


def _rt_df(close: float = 4057.78) -> pd.DataFrame:
    return pd.DataFrame(
        [{"ts_code": "000001.SH",
          "open": 4053.67, "high": 4080.72, "low": 4043.43, "close": close,
          "pre_close": 4083.97, "vol": 621194774, "amount": 1.27e9}]
    )


# ---------- ts_code 转换 ----------

@pytest.mark.parametrize("raw, expected", [
    ("sh000001", "000001.SH"),
    ("SH000001", "000001.SH"),
    ("sz399006", "399006.SZ"),
    ("sz399303", "399303.SZ"),
    ("000001.SH", "000001.SH"),
    ("399006.sz", "399006.SZ"),
    ("000001", "000001.SH"),  # 000xxx → SH
    ("600519", "600519.SH"),  # 6xxxxx → SH
    ("399006", "399006.SZ"),  # 其它 → SZ
])
def test_ts_code_conversion(raw, expected):
    assert TushareFetcher._to_tushare_index_ts_code(raw) == expected


@pytest.mark.parametrize("raw", ["", "abcxyz", None])
def test_ts_code_conversion_invalid(raw):
    assert TushareFetcher._to_tushare_index_ts_code(raw) is None


# ---------- get_index_daily 行为 ----------

def test_returns_none_when_api_not_initialized():
    f = _make_fetcher(None, datetime(2026, 6, 4, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert f.get_index_daily("sh000001") is None


def test_history_only_when_already_includes_today():
    # 历史末日就是「今天」→ 不应调 rt_idx_k
    now = datetime(2026, 6, 3, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    api = _FakeApi(index_daily_df=_hist_df(), rt_idx_k_df=_rt_df())
    f = _make_fetcher(api, now)

    df = f.get_index_daily("sh000001")

    assert df is not None
    assert df["date"].tolist() == ["2026-06-01", "2026-06-02", "2026-06-03"]
    assert api.rt_idx_k_calls == []
    # 单位对齐：vol×100、amount×1000
    last = df.iloc[-1]
    assert last["volume"] == pytest.approx(668452630 * 100)
    assert last["amount"] == pytest.approx(7.5e8 * 1000)


def test_stitches_today_via_rt_idx_k_when_history_lags():
    now = datetime(2026, 6, 4, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    api = _FakeApi(index_daily_df=_hist_df(), rt_idx_k_df=_rt_df())
    f = _make_fetcher(api, now)

    df = f.get_index_daily("sh000001")

    assert df is not None
    assert df["date"].tolist() == ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]
    assert api.rt_idx_k_calls == [{"ts_code": "000001.SH"}]
    last = df.iloc[-1]
    assert last["open"] == pytest.approx(4053.67)
    assert last["close"] == pytest.approx(4057.78)
    assert last["volume"] == pytest.approx(621194774 * 100)
    assert last["amount"] == pytest.approx(1.27e9 * 1000)


def test_rt_idx_k_unsupported_falls_back_to_history_only(caplog):
    now = datetime(2026, 6, 4, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    api = _FakeApi(
        index_daily_df=_hist_df(),
        rt_idx_k_exc=AttributeError("rt_idx_k not supported"),
    )
    f = _make_fetcher(api, now)

    with caplog.at_level("DEBUG"):
        df = f.get_index_daily("sh000001")

    assert df is not None
    assert df["date"].iloc[-1] == "2026-06-03"  # 没拼今天


def test_include_today_false_skips_rt_call():
    now = datetime(2026, 6, 4, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    api = _FakeApi(index_daily_df=_hist_df(), rt_idx_k_df=_rt_df())
    f = _make_fetcher(api, now)

    df = f.get_index_daily("sh000001", include_today=False)

    assert df is not None
    assert df["date"].iloc[-1] == "2026-06-03"
    assert api.rt_idx_k_calls == []


def test_history_exception_returns_none(caplog):
    now = datetime(2026, 6, 4, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    api = _FakeApi(index_daily_exc=TimeoutError("upstream slow"))
    f = _make_fetcher(api, now)

    with caplog.at_level("ERROR"):
        df = f.get_index_daily("sh000001")
    assert df is None


def test_history_empty_returns_none():
    now = datetime(2026, 6, 4, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    api = _FakeApi(index_daily_df=pd.DataFrame())
    f = _make_fetcher(api, now)
    assert f.get_index_daily("sh000001") is None


def test_invalid_symbol_returns_none():
    now = datetime(2026, 6, 4, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    api = _FakeApi(index_daily_df=_hist_df())
    f = _make_fetcher(api, now)
    assert f.get_index_daily("not-a-code") is None
    assert api.index_daily_calls == []  # 未识别就不应发起调用


def test_date_window_passed_through_to_tushare():
    """显式 start_date/end_date 应直接转 YYYYMMDD 透传给 index_daily。"""
    now = datetime(2026, 6, 4, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    api = _FakeApi(index_daily_df=_hist_df())
    f = _make_fetcher(api, now)

    f.get_index_daily("sh000001", start_date="2026-05-01",
                      end_date="2026-06-03", include_today=False)

    assert api.index_daily_calls == [
        {"ts_code": "000001.SH", "start_date": "20260501", "end_date": "20260603"}
    ]
