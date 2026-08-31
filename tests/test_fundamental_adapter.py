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

    def test_extract_latest_row_uses_date_col_regardless_of_input_order(self) -> None:
        """传 date_col 时按日期取最新，不依赖上游返回顺序（东财 daykline 是升序）。"""
        df = pd.DataFrame(
            {
                "日期": ["2026-08-03", "2026-08-10", "2026-08-06"],
                "主力净流入-净额": [100.0, 300.0, 200.0],
            }
        )
        row = _extract_latest_row(df, "600519", date_col="日期")
        self.assertIsNotNone(row)
        self.assertEqual(row["主力净流入-净额"], 300.0)

    def test_extract_latest_row_default_behavior_unchanged(self) -> None:
        """不传 date_col 时仍取首行——保护其它复用该函数的区块。"""
        df = pd.DataFrame(
            {
                "日期": ["2026-08-03", "2026-08-10"],
                "值": [1, 2],
            }
        )
        row = _extract_latest_row(df, "600519")
        self.assertEqual(row["值"], 1)

    def test_extract_latest_row_ignores_unparsable_date_col(self) -> None:
        """日期列不可解析时回落首行，不能因为排序失败就丢数据。"""
        df = pd.DataFrame({"日期": ["n/a", "--"], "值": [7, 8]})
        row = _extract_latest_row(df, "600519", date_col="日期")
        self.assertEqual(row["值"], 7)

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


class TestTushareCapitalFlow(unittest.TestCase):
    """Tushare 资金流：单位换算、主力口径、滚动求和、板块源优先级。

    单位是这条链路唯一容易静默出错的地方（moneyflow 万元 / ind_ths 亿元 / ind_dc 元），
    所以每个换算系数都在这里钉住。
    """

    # 各行主力净额（万元）：最新一天 100，逐日递增，便于直接验算滚动和
    _DAILY_MAIN_NET_WAN = [
        ("20260810", 100.0),
        ("20260809", 200.0),
        ("20260808", 300.0),
        ("20260807", 400.0),
        ("20260806", 500.0),
        ("20260805", 600.0),
        ("20260804", 700.0),
        ("20260803", 800.0),
        ("20260802", 900.0),
        ("20260801", 1000.0),
        # 第 11、12 天不应进入 5日/10日 求和
        ("20260731", 99999.0),
        ("20260730", 99999.0),
    ]
    _NET_MF_AMOUNT_DECOY = 777777.0

    def setUp(self) -> None:
        # 板块榜缓存是类级共享的，用例间必须清空，否则前一条用例缓存的 DC 结果
        # 会让「DC 挂掉降级 THS」这类用例拿到陈旧数据而假通过。
        TushareFundamentalAdapter.clear_sector_flow_cache_for_tests()

    def tearDown(self) -> None:
        TushareFundamentalAdapter.clear_sector_flow_cache_for_tests()

    def _moneyflow_df(self) -> pd.DataFrame:
        rows = []
        for trade_date, main_net_wan in self._DAILY_MAIN_NET_WAN:
            rows.append(
                {
                    "trade_date": trade_date,
                    # 主力 = 超大单 + 大单
                    "buy_elg_amount": main_net_wan,
                    "buy_lg_amount": 0.0,
                    "sell_elg_amount": 0.0,
                    "sell_lg_amount": 0.0,
                    # 中小单必须被排除在主力口径之外，给个大值放哨
                    "buy_md_amount": 50000.0,
                    "sell_md_amount": 0.0,
                    "buy_sm_amount": 60000.0,
                    "sell_sm_amount": 0.0,
                    # Tushare 现成的 net_mf_amount 口径不同，不应被使用
                    "net_mf_amount": self._NET_MF_AMOUNT_DECOY,
                }
            )
        # 乱序输入，验证内部按 trade_date 降序排序
        shuffled = rows[5:] + rows[:5]
        return pd.DataFrame(shuffled)

    @staticmethod
    def _dc_df() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "content_type": ["行业", "行业", "地域", "概念", "行业"],
                "name": ["半导体设备", "银行", "上海板块", "AI", "食品饮料"],
                # DC 的 net_amount 已是元，应原样透传
                "net_amount": [3.0e9, -2.0e9, 9.9e9, 8.8e9, 1.0e9],
            }
        )

    @staticmethod
    def _ths_df() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "industry": ["银行", "白酒", "钢铁"],
                # THS 的 net_amount 是亿元，需 ×1e8
                "net_amount": [21.0, 19.0, -5.0],
            }
        )

    def _adapter(self, *, moneyflow=None, dc=None, ths=None) -> TushareFundamentalAdapter:
        adapter = TushareFundamentalAdapter()
        # 不依赖本机是否配置了 TUSHARE_TOKEN，显式置为可用
        adapter._api = object()
        table = {
            "moneyflow": moneyflow,
            "moneyflow_ind_dc": dc,
            "moneyflow_ind_ths": ths,
        }
        patcher = patch.object(
            adapter, "_call_api", side_effect=lambda api_name, **kwargs: table.get(api_name)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return adapter

    def test_main_net_inflow_uses_main_force_caliber_in_yuan(self) -> None:
        adapter = self._adapter(moneyflow=self._moneyflow_df(), dc=self._dc_df())
        flow = adapter.get_capital_flow("600519")["stock_flow"]

        # 最新交易日 20260810 主力净额 100 万元 -> 1e6 元
        self.assertAlmostEqual(flow["main_net_inflow"], 100.0 * 1e4, places=2)
        # 绝不能用 net_mf_amount（口径含中小单，与 AkShare 路径不可比）
        self.assertNotAlmostEqual(
            flow["main_net_inflow"], self._NET_MF_AMOUNT_DECOY * 1e4, places=2
        )

    def test_rolling_sums_respect_date_order_and_window(self) -> None:
        adapter = self._adapter(moneyflow=self._moneyflow_df(), dc=self._dc_df())
        flow = adapter.get_capital_flow("600519")["stock_flow"]

        self.assertAlmostEqual(flow["inflow_5d"], 1500.0 * 1e4, places=2)
        self.assertAlmostEqual(flow["inflow_10d"], 5500.0 * 1e4, places=2)
        # 第 11/12 天的 99999 未被计入，说明窗口和排序都对
        self.assertLess(flow["inflow_10d"], 99999.0 * 1e4)

    def test_sector_dc_passes_yuan_through_and_filters_non_industry(self) -> None:
        adapter = self._adapter(moneyflow=self._moneyflow_df(), dc=self._dc_df())
        result = adapter.get_capital_flow("600519")
        rankings = result["sector_rankings"]

        self.assertEqual(rankings["top"][0]["name"], "半导体设备")
        self.assertAlmostEqual(rankings["top"][0]["net_inflow"], 3.0e9, places=2)
        self.assertEqual(rankings["bottom"][0]["name"], "银行")
        # 地域 / 概念 行必须被过滤掉，否则会污染行业榜
        names = [item["name"] for item in rankings["top"] + rankings["bottom"]]
        self.assertNotIn("上海板块", names)
        self.assertNotIn("AI", names)
        self.assertIn("capital_sector:tushare_moneyflow_ind_dc", result["source_chain"])

    def test_sector_falls_back_to_ths_and_converts_yi_to_yuan(self) -> None:
        adapter = self._adapter(moneyflow=self._moneyflow_df(), dc=None, ths=self._ths_df())
        result = adapter.get_capital_flow("600519")
        rankings = result["sector_rankings"]

        self.assertEqual(rankings["top"][0]["name"], "银行")
        # 21 亿元 -> 2.1e9 元
        self.assertAlmostEqual(rankings["top"][0]["net_inflow"], 21.0 * 1e8, places=2)
        self.assertIn("capital_sector:tushare_moneyflow_ind_ths", result["source_chain"])
        self.assertIn("moneyflow_ind_dc_api_failed", result["errors"])

    def test_stock_flow_survives_sector_failure(self) -> None:
        """板块两源都挂时，个股数据仍要保留（fail-open，不能整块丢弃）。"""
        adapter = self._adapter(moneyflow=self._moneyflow_df(), dc=None, ths=None)
        result = adapter.get_capital_flow("600519")

        self.assertEqual(result["status"], "partial")
        self.assertIsNotNone(result["stock_flow"]["main_net_inflow"])
        self.assertEqual(result["sector_rankings"]["top"], [])

    def test_not_available_without_token(self) -> None:
        adapter = TushareFundamentalAdapter()
        adapter._api = None
        result = adapter.get_capital_flow("600519")

        self.assertEqual(result["status"], "not_supported")
        self.assertIn("tushare_not_available", result["errors"])

    def test_moneyflow_api_failure_reports_error(self) -> None:
        adapter = self._adapter(moneyflow=None, dc=None, ths=None)
        result = adapter.get_capital_flow("600519")

        self.assertEqual(result["status"], "not_supported")
        self.assertIn("moneyflow_api_failed", result["errors"])

    def _counting_adapter(self, calls: list) -> TushareFundamentalAdapter:
        """记录每次 _call_api 的接口名，用于验证板块榜只拉一次。"""
        adapter = TushareFundamentalAdapter()
        adapter._api = object()
        table = {"moneyflow": self._moneyflow_df(), "moneyflow_ind_dc": self._dc_df()}

        def _fake(api_name, **_kwargs):
            calls.append(api_name)
            return table.get(api_name)

        patcher = patch.object(adapter, "_call_api", side_effect=_fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return adapter

    def test_sector_rankings_fetched_once_across_stocks(self) -> None:
        """板块资金流对同一交易日的所有个股完全相同，17 只不该拉 17 次。"""
        calls: list = []
        adapter = self._counting_adapter(calls)

        for code in ("600519", "002463", "002371"):
            result = adapter.get_capital_flow(code)
            self.assertEqual(result["sector_rankings"]["top"][0]["name"], "半导体设备")
            self.assertIn("capital_sector:tushare_moneyflow_ind_dc", result["source_chain"])

        self.assertEqual(calls.count("moneyflow"), 3, "个股资金流必须每只都取")
        self.assertEqual(calls.count("moneyflow_ind_dc"), 1, "板块榜应命中缓存只取一次")

    def test_sector_rankings_cache_isolated_by_trade_date(self) -> None:
        """跨交易日不能复用：换日必须重新取，否则会拿昨天的板块榜。"""
        calls: list = []
        adapter = self._counting_adapter(calls)
        adapter.get_capital_flow("600519")
        self.assertEqual(calls.count("moneyflow_ind_dc"), 1)

        TushareFundamentalAdapter.clear_sector_flow_cache_for_tests()
        adapter.get_capital_flow("600519")
        self.assertEqual(calls.count("moneyflow_ind_dc"), 2)

    def test_cached_sector_rankings_are_copied_not_shared(self) -> None:
        """缓存必须发拷贝：上层改了返回值不能污染后续股票的板块榜。"""
        calls: list = []
        adapter = self._counting_adapter(calls)

        first = adapter.get_capital_flow("600519")
        first["sector_rankings"]["top"][0]["name"] = "被污染"

        second = adapter.get_capital_flow("002463")
        self.assertEqual(second["sector_rankings"]["top"][0]["name"], "半导体设备")

    def test_sector_failure_is_not_cached(self) -> None:
        """板块两源都挂时不能把空结果缓存住，否则同一轮后续股票全部没有板块榜。"""
        calls: list = []
        adapter = TushareFundamentalAdapter()
        adapter._api = object()
        state = {"dc": None}
        table = {"moneyflow": self._moneyflow_df()}

        def _fake(api_name, **_kwargs):
            calls.append(api_name)
            if api_name == "moneyflow_ind_dc":
                return state["dc"]
            return table.get(api_name)

        patcher = patch.object(adapter, "_call_api", side_effect=_fake)
        patcher.start()
        self.addCleanup(patcher.stop)

        first = adapter.get_capital_flow("600519")
        self.assertEqual(first["sector_rankings"]["top"], [])

        state["dc"] = self._dc_df()
        second = adapter.get_capital_flow("002463")
        self.assertEqual(second["sector_rankings"]["top"][0]["name"], "半导体设备")


if __name__ == "__main__":
    unittest.main()
