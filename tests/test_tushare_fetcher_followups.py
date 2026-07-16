# -*- coding: utf-8 -*-
"""Regression tests for post-merge Tushare follow-up fixes."""

import importlib.util
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

try:
    json_repair_available = importlib.util.find_spec("json_repair") is not None
except ValueError:
    json_repair_available = "json_repair" in sys.modules

if not json_repair_available and "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

from data_provider.tushare_fetcher import TushareFetcher


class TestTushareFetcherFollowUps(unittest.TestCase):
    """Cover rate limiting and cross-day trade-calendar refresh behavior."""

    @staticmethod
    def _make_fetcher() -> TushareFetcher:
        with patch.object(TushareFetcher, "_init_api", return_value=None):
            fetcher = TushareFetcher()
        fetcher._api = MagicMock()
        fetcher.priority = 2
        return fetcher

    def test_get_trade_time_refreshes_trade_calendar_when_day_changes(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.side_effect = [
            pd.DataFrame({"cal_date": ["20260317", "20260314"], "is_open": [1, 1]}),
            pd.DataFrame({"cal_date": ["20260318", "20260317"], "is_open": [1, 1]}),
        ]

        with patch.object(
            fetcher,
            "_get_china_now",
            side_effect=[
                datetime(2026, 3, 17, 20, 0),
                datetime(2026, 3, 17, 20, 0),
                datetime(2026, 3, 18, 20, 0),
                datetime(2026, 3, 18, 20, 0),
            ],
        ), patch.object(fetcher, "_check_rate_limit") as rate_limit_mock:
            self.assertEqual(fetcher.get_trade_time(early_time="00:00", late_time="19:00"), "20260317")
            self.assertEqual(fetcher.get_trade_time(early_time="00:00", late_time="19:00"), "20260318")

        self.assertEqual(fetcher._api.trade_cal.call_count, 2)
        self.assertEqual(rate_limit_mock.call_count, 2)
    def test_get_trade_time_returns_latest_trade_date_on_non_trade_day(self) -> None:
        """Non-trade day (e.g. Saturday) should return the most recent trade
        date (Friday), not the one before it (Thursday).  Fixes #1009."""
        fetcher = self._make_fetcher()
        # 2026-03-21 is Saturday; Friday 20 and Thursday 19 are trade dates
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {
                "cal_date": ["20260314", "20260315", "20260316",
                             "20260317", "20260318", "20260319",
                             "20260320", "20260321"],
                "is_open": [0, 0, 1, 1, 1, 1, 1, 0],
            }
        )

        with patch.object(
            fetcher,
            "_get_china_now",
            # called twice: once by get_trade_time, once by _get_trade_dates
            side_effect=[datetime(2026, 3, 21, 10, 0)] * 2,
        ), patch.object(fetcher, "_check_rate_limit"):
            result = fetcher.get_trade_time(early_time="00:00", late_time="19:00")

        # Should be Friday (20th), NOT Thursday (19th)
        self.assertEqual(result, "20260320")

    def test_get_trade_time_trade_day_before_data_ready_returns_previous(self) -> None:
        """On a trade day within the early-late window, should return the
        previous trade date (data not ready yet for today)."""
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {
                "cal_date": ["20260319", "20260320"],
                "is_open": [1, 1],
            }
        )

        with patch.object(
            fetcher,
            "_get_china_now",
            # Friday 10:00 AM - within 00:00~19:00 window, data not ready
            side_effect=[datetime(2026, 3, 20, 10, 0)] * 2,
        ), patch.object(fetcher, "_check_rate_limit"):
            result = fetcher.get_trade_time(early_time="00:00", late_time="19:00")

        # Data not ready, should fall back to Thursday (19th)
        self.assertEqual(result, "20260319")
        
          
    def test_get_sector_rankings_rate_limits_calendar_and_rankings_api(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {"cal_date": ["20260317", "20260314"], "is_open": [1, 1]}
        )
        fetcher._api.moneyflow_ind_ths.return_value = pd.DataFrame(
            {
                "industry": ["AI", "消费"],
                "pct_change": [1.8, -0.6],
            }
        )

        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 16, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ) as rate_limit_mock:
            top, bottom = fetcher.get_sector_rankings(n=1)

        self.assertEqual(top, [{"name": "AI", "change_pct": 1.8}])
        self.assertEqual(bottom, [{"name": "消费", "change_pct": -0.6}])
        self.assertEqual(rate_limit_mock.call_count, 2)

    def test_get_chip_distribution_rate_limits_all_tushare_calls(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {"cal_date": ["20260317", "20260314"], "is_open": [1, 1]}
        )
        fetcher._api.cyq_chips.return_value = pd.DataFrame(
            {
                "price": [9.0, 10.0, 11.0],
                "percent": [20.0, 50.0, 30.0],
            }
        )
        fetcher._api.daily.return_value = pd.DataFrame({"close": [10.5]})

        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ) as rate_limit_mock:
            chip = fetcher.get_chip_distribution("600519")

        self.assertIsNotNone(chip)
        if chip is None:
            self.fail("expected chip distribution data")
        self.assertEqual(chip.date, "2026-03-17")
        self.assertAlmostEqual(chip.profit_ratio, 0.7)
        self.assertAlmostEqual(chip.avg_cost, 10.1)
        self.assertAlmostEqual(chip.concentration_90, 0.1)
        self.assertAlmostEqual(chip.concentration_70, 0.1)
        self.assertEqual(rate_limit_mock.call_count, 3)

    def test_convert_stock_code_accepts_exchange_prefixed_a_share(self) -> None:
        fetcher = self._make_fetcher()

        self.assertEqual(fetcher._convert_stock_code("SZ000001"), "000001.SZ")
        self.assertEqual(fetcher._convert_stock_code("SH600519"), "600519.SH")
        self.assertEqual(fetcher._convert_stock_code("605218"), "605218.SH")
        self.assertEqual(fetcher._convert_stock_code("600519.SS"), "600519.SH")

    @patch.dict(sys.modules, {"tushare": MagicMock()})
    def test_legacy_realtime_quote_keeps_sz_hint_as_stock_symbol(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.quotation.side_effect = Exception("quota")

        tushare_module = sys.modules["tushare"]
        tushare_module.get_realtime_quotes.return_value = pd.DataFrame(
            [
                {
                    "name": "平安银行",
                    "price": "10.94",
                    "pre_close": "10.88",
                    "volume": "1000",
                    "amount": "2000",
                    "high": "11.00",
                    "low": "10.80",
                    "open": "10.90",
                }
            ]
        )

        quote = fetcher.get_realtime_quote("SZ000001")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, "000001")
        self.assertEqual(quote.name, "平安银行")
        tushare_module.get_realtime_quotes.assert_called_once_with("000001")


class TestTushareEtfVolumeMetrics(unittest.TestCase):
    """ETF 量比/换手率自算（fund_daily + fund_share）。"""

    TRADE_DATES = [
        "20260715", "20260714", "20260713", "20260710", "20260709",
        "20260708", "20260707", "20260706", "20260703", "20260702",
    ]

    @staticmethod
    def _make_fetcher() -> TushareFetcher:
        with patch.object(TushareFetcher, "_init_api", return_value=None):
            fetcher = TushareFetcher()
        fetcher._api = MagicMock()
        fetcher.priority = 2
        return fetcher

    @staticmethod
    def _fund_daily(vols, closes=None) -> pd.DataFrame:
        """构造升序 fund_daily 帧；vols 为「手」，末行=最新交易日。"""
        n = len(vols)
        dates = [f"202607{str(d).zfill(2)}" for d in range(2, 2 + n)]  # 升序
        closes = closes if closes is not None else [3.0] * n
        return pd.DataFrame({
            "ts_code": ["515880.SH"] * n,
            "trade_date": dates,
            "open": closes,
            "high": [c + 0.05 for c in closes],
            "low": [c - 0.05 for c in closes],
            "close": closes,
            "pre_close": closes,
            "change": [0.0] * n,
            "pct_chg": [0.0] * n,
            "vol": vols,
            "amount": [v * 100 * c / 1000 for v, c in zip(vols, closes)],  # 千元
        })

    @staticmethod
    def _fund_share(fd_share) -> pd.DataFrame:
        return pd.DataFrame({
            "ts_code": ["515880.SH", "515880.SH"],
            "trade_date": ["20260714", "20260715"],
            "fd_share": [fd_share, fd_share],  # 万份
            "fund_type": ["ETF", "ETF"],
            "market": ["SH", "SH"],
        })

    def test_normal_computes_volume_ratio_and_turnover(self) -> None:
        fetcher = self._make_fetcher()
        # 前5日均量=500000，今日=1000000 → 量比=2.0
        fetcher._api.fund_daily.return_value = self._fund_daily(
            [500000, 500000, 500000, 500000, 500000, 1000000]
        )
        # 换手率 = (1e6*100)/(1e6*1e4)*100 = 1.0%
        fetcher._api.fund_share.return_value = self._fund_share(1_000_000)

        with patch.object(fetcher, "_get_trade_dates", return_value=self.TRADE_DATES), \
             patch.object(fetcher, "_check_rate_limit"):
            vr, tr = fetcher._compute_etf_volume_metrics("515880")

        self.assertAlmostEqual(vr, 2.0)
        self.assertAlmostEqual(tr, 1.0)

    def test_missing_share_leaves_turnover_none(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.fund_daily.return_value = self._fund_daily(
            [500000, 500000, 500000, 500000, 500000, 1000000]
        )
        fetcher._api.fund_share.return_value = pd.DataFrame()  # 空份额

        with patch.object(fetcher, "_get_trade_dates", return_value=self.TRADE_DATES), \
             patch.object(fetcher, "_check_rate_limit"):
            vr, tr = fetcher._compute_etf_volume_metrics("515880")

        self.assertAlmostEqual(vr, 2.0)
        self.assertIsNone(tr)

    def test_insufficient_history_leaves_volume_ratio_none(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.fund_daily.return_value = self._fund_daily([100, 200, 300])  # 仅3行
        fetcher._api.fund_share.return_value = self._fund_share(1_000_000)

        with patch.object(fetcher, "_get_trade_dates", return_value=self.TRADE_DATES), \
             patch.object(fetcher, "_check_rate_limit"):
            vr, tr = fetcher._compute_etf_volume_metrics("515880")

        self.assertIsNone(vr)

    def test_non_etf_short_circuits_without_api_call(self) -> None:
        fetcher = self._make_fetcher()
        with patch.object(fetcher, "_get_trade_dates", return_value=self.TRADE_DATES), \
             patch.object(fetcher, "_check_rate_limit"):
            vr, tr = fetcher._compute_etf_volume_metrics("600519")

        self.assertEqual((vr, tr), (None, None))
        fetcher._api.fund_daily.assert_not_called()

    def test_fund_daily_exception_degrades_to_none(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.fund_daily.side_effect = Exception("boom")
        with patch.object(fetcher, "_get_trade_dates", return_value=self.TRADE_DATES), \
             patch.object(fetcher, "_check_rate_limit"):
            vr, tr = fetcher._compute_etf_volume_metrics("515880")

        self.assertEqual((vr, tr), (None, None))

    def test_fund_share_exception_keeps_volume_ratio(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.fund_daily.return_value = self._fund_daily(
            [500000, 500000, 500000, 500000, 500000, 1000000]
        )
        fetcher._api.fund_share.side_effect = Exception("boom")
        with patch.object(fetcher, "_get_trade_dates", return_value=self.TRADE_DATES), \
             patch.object(fetcher, "_check_rate_limit"):
            vr, tr = fetcher._compute_etf_volume_metrics("515880")

        self.assertAlmostEqual(vr, 2.0)
        self.assertIsNone(tr)

    def test_turnover_out_of_range_is_discarded(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.fund_daily.return_value = self._fund_daily(
            [500000, 500000, 500000, 500000, 500000, 1000000]
        )
        fetcher._api.fund_share.return_value = self._fund_share(1)  # 份额过小 → 换手率>100%
        with patch.object(fetcher, "_get_trade_dates", return_value=self.TRADE_DATES), \
             patch.object(fetcher, "_check_rate_limit"):
            vr, tr = fetcher._compute_etf_volume_metrics("515880")

        self.assertAlmostEqual(vr, 2.0)
        self.assertIsNone(tr)  # 越界丢弃

    def test_metrics_cached_within_same_trade_date(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.fund_daily.return_value = self._fund_daily(
            [500000, 500000, 500000, 500000, 500000, 1000000]
        )
        fetcher._api.fund_share.return_value = self._fund_share(1_000_000)
        with patch.object(fetcher, "_get_trade_dates", return_value=self.TRADE_DATES), \
             patch.object(fetcher, "_check_rate_limit"):
            fetcher._compute_etf_volume_metrics("515880")
            fetcher._compute_etf_volume_metrics("515880")

        self.assertEqual(fetcher._api.fund_daily.call_count, 1)

    @patch.dict(sys.modules, {"tushare": MagicMock()})
    def test_realtime_quote_falls_back_to_eod_for_etf(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.quotation.side_effect = Exception("no quotation")  # Pro 挂
        sys.modules["tushare"].get_realtime_quotes.return_value = pd.DataFrame()  # legacy 空
        fetcher._api.fund_daily.return_value = self._fund_daily(
            [500000, 500000, 500000, 500000, 500000, 1000000],
            closes=[0.7, 0.72, 0.74, 0.76, 0.78, 0.80],
        )
        fetcher._api.fund_share.return_value = self._fund_share(1_000_000)

        with patch.object(fetcher, "_get_trade_dates", return_value=self.TRADE_DATES), \
             patch.object(fetcher, "_check_rate_limit"):
            quote = fetcher.get_realtime_quote("515880")

        self.assertIsNotNone(quote)
        self.assertAlmostEqual(quote.price, 0.80)  # EOD 最新收盘
        self.assertAlmostEqual(quote.volume_ratio, 2.0)
        self.assertAlmostEqual(quote.turnover_rate, 1.0)

    @patch.dict(sys.modules, {"tushare": MagicMock()})
    def test_realtime_quote_does_not_overwrite_existing_turnover(self) -> None:
        fetcher = self._make_fetcher()
        # Pro 返回带 turnover_ratio 的真实值
        fetcher._api.quotation.return_value = pd.DataFrame([{
            "name": "通信ETF", "price": 0.80, "pct_chg": 1.0, "change": 0.01,
            "vol": 100, "amount": 200, "high": 0.81, "low": 0.79,
            "open": 0.79, "pre_close": 0.79, "turnover_ratio": 3.33,
        }])
        fetcher._api.fund_daily.return_value = self._fund_daily(
            [500000, 500000, 500000, 500000, 500000, 1000000]
        )
        fetcher._api.fund_share.return_value = self._fund_share(1_000_000)

        with patch.object(fetcher, "_get_trade_dates", return_value=self.TRADE_DATES), \
             patch.object(fetcher, "_check_rate_limit"):
            quote = fetcher.get_realtime_quote("515880")

        self.assertIsNotNone(quote)
        self.assertAlmostEqual(quote.turnover_rate, 3.33)  # 真实值不被自算覆盖
        self.assertAlmostEqual(quote.volume_ratio, 2.0)    # 缺失的量比被回填
