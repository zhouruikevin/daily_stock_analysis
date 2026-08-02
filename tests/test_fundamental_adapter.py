# -*- coding: utf-8 -*-
"""
Tests for fundamental adapter helpers.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.fundamental_adapter import (
    AkshareFundamentalAdapter,
    TushareFundamentalAdapter,
    _build_dividend_payload,
    _extract_latest_row,
    _parse_dividend_plan_to_per_share,
)


class TestFundamentalAdapter(unittest.TestCase):
    def test_parse_dividend_plan_to_per_share_supports_cn_patterns(self) -> None:
        self.assertAlmostEqual(_parse_dividend_plan_to_per_share("10派3元(含税)"), 0.3, places=6)
        self.assertAlmostEqual(_parse_dividend_plan_to_per_share("每10股派发2.5元"), 0.25, places=6)
        self.assertAlmostEqual(_parse_dividend_plan_to_per_share("每股派0.8元"), 0.8, places=6)
        self.assertIsNone(_parse_dividend_plan_to_per_share("仅送股，不现金分红"))

    def test_extract_latest_row_returns_none_when_code_mismatch(self) -> None:
        df = pd.DataFrame(
            {
                "股票代码": ["600000", "000001"],
                "值": [1, 2],
            }
        )
        row = _extract_latest_row(df, "600519")
        self.assertIsNone(row)

    def test_extract_latest_row_fallback_when_no_code_column(self) -> None:
        df = pd.DataFrame({"值": [1, 2]})
        row = _extract_latest_row(df, "600519")
        self.assertIsNotNone(row)
        self.assertEqual(row["值"], 1)

    def test_dragon_tiger_no_match_with_code_column_is_ok(self) -> None:
        adapter = AkshareFundamentalAdapter()
        df = pd.DataFrame(
            {
                "股票代码": ["600000"],
                "日期": ["2026-01-01"],
            }
        )
        with patch.object(adapter, "_call_df_candidates", return_value=(df, "stock_lhb_stock_statistic_em", [])):
            result = adapter.get_dragon_tiger_flag("600519")
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["is_on_list"])
        self.assertEqual(result["recent_count"], 0)

    def test_dragon_tiger_match_is_ok(self) -> None:
        adapter = AkshareFundamentalAdapter()
        today = pd.Timestamp.now().strftime("%Y-%m-%d")
        df = pd.DataFrame(
            {
                "股票代码": ["600519"],
                "日期": [today],
            }
        )
        with patch.object(adapter, "_call_df_candidates", return_value=(df, "stock_lhb_stock_statistic_em", [])):
            result = adapter.get_dragon_tiger_flag("600519")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["is_on_list"])
        self.assertGreaterEqual(result["recent_count"], 1)

    def test_fundamental_bundle_includes_financial_report_and_dividend_payload(self) -> None:
        adapter = AkshareFundamentalAdapter()
        now = datetime.now()
        within_ttm = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        future_day = (now + timedelta(days=10)).strftime("%Y-%m-%d")
        old_day = (now - timedelta(days=500)).strftime("%Y-%m-%d")
        fin_df = pd.DataFrame(
            {
                "股票代码": ["600519"],
                "报告期": [within_ttm],
                "营业总收入": [1000.0],
                "归母净利润": [300.0],
                "经营活动产生的现金流量净额": [500.0],
                "净资产收益率": [18.2],
                "营业收入同比": [12.0],
                "净利润同比": [9.5],
            }
        )
        forecast_df = pd.DataFrame({"股票代码": ["600519"], "预告": ["预增"]})
        quick_df = pd.DataFrame({"股票代码": ["600519"], "快报": ["快报摘要"]})
        dividend_df = pd.DataFrame(
            {
                "股票代码": ["600519", "600519", "600519", "600519"],
                "除息日": [within_ttm, within_ttm, future_day, old_day],
                "分配方案": ["10派3元(含税)", "10派3元(含税)", "10派5元", "10派1元"],
            }
        )

        with patch.object(
            adapter,
            "_call_df_candidates",
            side_effect=[
                (fin_df, "stock_financial_abstract", []),
                (forecast_df, "stock_yjyg_em", []),
                (quick_df, "stock_yjkb_em", []),
                (dividend_df, "stock_fhps_detail_em", []),
                (None, None, []),
                (None, None, []),
            ],
        ):
            result = adapter.get_fundamental_bundle("600519")

        financial_report = result["earnings"].get("financial_report", {})
        self.assertEqual(financial_report.get("report_date"), within_ttm)
        self.assertEqual(financial_report.get("revenue"), 1000.0)
        self.assertEqual(financial_report.get("net_profit_parent"), 300.0)
        self.assertEqual(financial_report.get("operating_cash_flow"), 500.0)
        self.assertEqual(financial_report.get("roe"), 18.2)

        dividend_payload = result["earnings"].get("dividend", {})
        events = dividend_payload.get("events", [])
        self.assertEqual(len(events), 2)  # duplicate + future day filtered
        self.assertEqual(dividend_payload.get("ttm_event_count"), 1)
        self.assertAlmostEqual(dividend_payload.get("ttm_cash_dividend_per_share"), 0.3, places=6)

    def test_build_dividend_payload_returns_empty_when_code_not_matched(self) -> None:
        now = datetime.now().strftime("%Y-%m-%d")
        df = pd.DataFrame(
            {
                "股票代码": ["000001"],
                "除息日": [now],
                "分配方案": ["10派3元(含税)"],
            }
        )

        payload = _build_dividend_payload(df, stock_code="600519")
        self.assertEqual(payload, {})

    def test_build_dividend_payload_skips_after_tax_plan(self) -> None:
        now = datetime.now().strftime("%Y-%m-%d")
        df = pd.DataFrame(
            {
                "股票代码": ["600519"],
                "除息日": [now],
                "分配方案": ["10派3元(税后)"],
            }
        )

        payload = _build_dividend_payload(df, stock_code="600519")
        self.assertEqual(payload, {})

    def test_build_dividend_payload_ttm_window_boundary(self) -> None:
        now = datetime.now()
        day_365 = (now - timedelta(days=365)).strftime("%Y-%m-%d")
        day_366 = (now - timedelta(days=366)).strftime("%Y-%m-%d")
        df = pd.DataFrame(
            {
                "股票代码": ["600519", "600519"],
                "除息日": [day_365, day_366],
                "分配方案": ["10派3元(含税)", "10派5元(含税)"],
            }
        )

        payload = _build_dividend_payload(df, stock_code="600519")
        self.assertEqual(payload.get("ttm_event_count"), 1)
        self.assertAlmostEqual(payload.get("ttm_cash_dividend_per_share"), 0.3, places=6)


class TestTushareFundamentalUnits(unittest.TestCase):
    """Tushare income/express amounts are 元; they must reach consumers unscaled.

    Real 002373 figures are used so a regression shows up as a recognisably wrong
    report line rather than an abstract number mismatch.
    """

    # 002373.SZ 2026Q1 income statement, verbatim from the Tushare income API
    _INCOME_REVENUE = 1312997128.0   # 13.13 亿元
    _INCOME_NET_PROFIT = 3735873.0   # 373.59 万元

    # 002373.SZ 2020 annual express, verbatim from the Tushare express API
    _EXPRESS_REVENUE = 9477651800.0      # 94.78 亿元
    _EXPRESS_NET_INCOME = 1070597700.0   # 10.71 亿元
    _EXPRESS_NP_LAST_YEAR = 1013374200.0  # 去年同期净利润, 元 (NOT a percentage)

    def _income_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ts_code": ["002373.SZ"],
                "ann_date": ["20260428"],
                "end_date": ["20260331"],
                "total_revenue": [self._INCOME_REVENUE],
                "revenue": [self._INCOME_REVENUE],
                "n_income_attr_p": [self._INCOME_NET_PROFIT],
            }
        )

    _UNSET = object()  # distinct from None, which is itself a case under test

    def _express_df(self, np_last_year: object = _UNSET) -> pd.DataFrame:
        if np_last_year is self._UNSET:
            np_last_year = self._EXPRESS_NP_LAST_YEAR
        return pd.DataFrame(
            {
                "ts_code": ["002373.SZ"],
                "ann_date": ["20210227"],
                "end_date": ["20201231"],
                "revenue": [self._EXPRESS_REVENUE],
                "n_income": [self._EXPRESS_NET_INCOME],
                "yoy_net_profit": [np_last_year],
            }
        )

    def test_income_statement_keeps_yuan_unit(self) -> None:
        adapter = TushareFundamentalAdapter()
        with patch.object(adapter, "_call_api", return_value=self._income_df()):
            result = adapter.get_income_statement("002373")

        self.assertAlmostEqual(result["revenue"], self._INCOME_REVENUE, places=2)
        self.assertAlmostEqual(result["n_income_parent"], self._INCOME_NET_PROFIT, places=2)

    def test_financial_report_amounts_render_with_correct_unit(self) -> None:
        """Locks the provider contract to the notification renderer's 元 assumption."""
        from src.notification import NotificationService

        adapter = TushareFundamentalAdapter()
        with patch.object(adapter, "_call_api", return_value=self._income_df()):
            result = adapter.get_income_statement("002373")

        self.assertEqual(NotificationService._format_amount_cn(result["revenue"]), "13.13 亿元")
        self.assertEqual(
            NotificationService._format_amount_cn(result["n_income_parent"]), "373.59 万元"
        )

    def test_express_summary_labels_yi_from_yuan(self) -> None:
        adapter = TushareFundamentalAdapter()
        with patch.object(adapter, "_call_api", return_value=self._express_df()):
            result = adapter.get_express("002373")

        summary = result["quick_report_summary"]
        self.assertIn("营收94.78亿", summary)
        self.assertIn("净利润10.71亿", summary)
        # the 1e4-off values that shipped before the fix must not reappear
        self.assertNotIn("947765", summary)
        self.assertNotIn("107059", summary)

    def test_express_yoy_derived_from_last_year_amount(self) -> None:
        """express.yoy_net_profit is 去年同期净利润(元), not a growth rate."""
        adapter = TushareFundamentalAdapter()
        with patch.object(adapter, "_call_api", return_value=self._express_df()):
            result = adapter.get_express("002373")

        # (1070597700 - 1013374200) / 1013374200 = +5.65%
        self.assertAlmostEqual(result["n_income_yoy"], 5.6467, places=3)
        self.assertAlmostEqual(result["np_last_year"], self._EXPRESS_NP_LAST_YEAR, places=2)
        self.assertIn("同比增长5.6%", result["quick_report_summary"])
        self.assertNotIn("1013374200", result["quick_report_summary"])

    def test_express_omits_yoy_when_last_year_non_positive(self) -> None:
        """A zero/negative base makes the growth rate meaningless — omit it, don't fabricate."""
        for base in (0.0, -1234.0, None):
            with self.subTest(np_last_year=base):
                adapter = TushareFundamentalAdapter()
                with patch.object(adapter, "_call_api", return_value=self._express_df(base)):
                    result = adapter.get_express("002373")

                self.assertIsNone(result["n_income_yoy"])
                self.assertNotIn("同比", result["quick_report_summary"])
                # the rest of the summary still renders
                self.assertIn("营收94.78亿", result["quick_report_summary"])


if __name__ == "__main__":
    unittest.main()
