# -*- coding: utf-8 -*-
"""Regression tests for pipeline-level related board enrichment."""

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
from unittest.mock import MagicMock

from api.v1.schemas.history import ReportDetails
from data_provider import base as base_module
from data_provider.base import BaseFetcher, DataFetcherManager
from src.core.pipeline import StockAnalysisPipeline
from src.services.market_hotspot_service import MarketHotspotService
from src.services.market_structure_service import MarketStructureService
from src.utils.data_processing import (
    extract_board_detail_fields,
    extract_market_structure_detail_field,
)


class _SlowConceptRankingFetcher:
    name = "SlowConceptRankingFetcher"

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def get_concept_rankings(self, n: int = 5):
        with self._lock:
            self.calls += 1
        time.sleep(0.05)
        return (
            [{"name": f"top-{n}", "change_pct": 1.2}],
            [{"name": f"bottom-{n}", "change_pct": -0.8}],
        )


class _HangingConceptRankingFetcher:
    def __init__(self, delay_seconds: float = 0.5) -> None:
        self.calls = 0
        self.delay_seconds = delay_seconds

    def get_concept_rankings(self, n: int = 5):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return (
            [{"name": f"top-{n}", "change_pct": 1.0}],
            [{"name": f"bottom-{n}", "change_pct": -1.0}],
        )


class PipelineRelatedBoardsTestCase(unittest.TestCase):
    def tearDown(self) -> None:
        DataFetcherManager.clear_concept_rankings_cache_for_tests()

    def test_attach_belong_boards_shallow_copies_context_before_injecting(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.return_value = [{"name": "白酒", "type": "行业"}]

        cached_context = {
            "market": "cn",
            "status": "ok",
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("600519", cached_context)

        self.assertIsNot(enriched, cached_context)
        self.assertNotIn("belong_boards", cached_context)
        self.assertEqual(enriched["belong_boards"], [{"name": "白酒", "type": "行业"}])

    def test_attach_belong_boards_adds_concept_rankings_for_cn(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.return_value = [{"name": "机器人概念", "type": "概念"}]
        pipeline.fetcher_manager.get_concept_rankings.return_value = (
            [{"name": "机器人概念", "change_pct": 4.2}],
            [{"name": "转基因", "change_pct": -2.05}],
        )

        context = {
            "market": "cn",
            "status": "ok",
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("600519", context)

        self.assertEqual(enriched["concept_boards"]["data"]["top"][0]["name"], "机器人概念")
        self.assertEqual(enriched["concept_boards"]["data"]["bottom"][0]["change_pct"], -2.05)

    def test_attach_belong_boards_reuses_concept_rankings_per_pipeline_run(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.side_effect = [
            [{"name": "Robot Theme", "type": "concept"}],
            [{"name": "AI Theme", "type": "concept"}],
        ]
        pipeline.fetcher_manager.get_concept_rankings.return_value = (
            [{"name": "Robot Theme", "change_pct": 4.2}],
            [{"name": "Chip Theme", "change_pct": -2.05}],
        )

        context = {
            "market": "cn",
            "status": "ok",
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        first = pipeline._attach_belong_boards_to_fundamental_context("600519", context)
        second = pipeline._attach_belong_boards_to_fundamental_context("000001", context)

        pipeline.fetcher_manager.get_concept_rankings.assert_called_once_with(5)
        self.assertEqual(first["concept_boards"]["data"]["top"][0]["name"], "Robot Theme")
        self.assertEqual(second["concept_boards"]["data"]["top"][0]["name"], "Robot Theme")

    def test_empty_concept_rankings_are_reused_by_market_structure_builds(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.side_effect = [
            [{"name": "Robot Theme", "type": "concept"}],
            [{"name": "AI Theme", "type": "concept"}],
        ]
        pipeline.fetcher_manager.get_concept_rankings.return_value = ([], [])

        context = {
            "market": "cn",
            "status": "ok",
            "coverage": {"boards": "ok"},
            "boards": {
                "status": "ok",
                "data": {
                    "top": [{"name": "Technology", "change_pct": 1.2}],
                    "bottom": [],
                },
            },
        }

        first = pipeline._attach_belong_boards_to_fundamental_context("600519", context)
        second = pipeline._attach_belong_boards_to_fundamental_context("000001", context)

        self.assertEqual(first["concept_boards"]["status"], "partial")
        self.assertEqual(first["concept_boards"]["data"]["top"], [])
        self.assertTrue(first["concept_boards"]["data"]["fetch_attempted"])
        self.assertEqual(
            extract_board_detail_fields(
                {"fundamental_context": first}
            )["concept_rankings"],
            {"top": [], "bottom": [], "status": "partial"},
        )

        market_structure_service = MarketStructureService(
            fetcher_manager=pipeline.fetcher_manager,
        )
        market_structure_service.build_context(
            code="600519",
            stock_name="First",
            market="cn",
            fundamental_context=first,
        )
        market_structure_service.build_context(
            code="000001",
            stock_name="Second",
            market="cn",
            fundamental_context=second,
        )

        pipeline.fetcher_manager.get_concept_rankings.assert_called_once_with(5)

    def test_get_concept_rankings_for_market_no_long_block_with_hanging_fetcher(self) -> None:
        fetcher = _HangingConceptRankingFetcher()
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = fetcher
        pipeline.market_hotspot_service = MarketHotspotService(
            fetcher_manager=fetcher,
            ranking_fetch_timeout_seconds=0.05,
        )
        pipeline._concept_rankings_cache = {}
        pipeline._concept_rankings_cache_lock = threading.Lock()

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(pipeline._get_concept_rankings_for_market, "cn")
            second = executor.submit(pipeline._get_concept_rankings_for_market, "cn")
            first_result = first.result()
            second_result = second.result()

        duration = time.perf_counter() - start
        self.assertLess(duration, 0.30)
        self.assertEqual(first_result, ([], []))
        self.assertEqual(second_result, ([], []))
        self.assertGreaterEqual(fetcher.calls, 1)

    def test_concept_rankings_cache_is_shared_across_manager_instances(self) -> None:
        fetcher = _SlowConceptRankingFetcher()
        first_manager = DataFetcherManager.__new__(DataFetcherManager)
        first_manager._fetchers = [fetcher]
        second_manager = DataFetcherManager.__new__(DataFetcherManager)
        second_manager._fetchers = [fetcher]

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_result, second_result = list(
                executor.map(
                    lambda manager: manager.get_concept_rankings(5),
                    [first_manager, second_manager],
                )
            )

        self.assertEqual(fetcher.calls, 1)
        self.assertEqual(first_result, second_result)

        first_result[0][0]["name"] = "mutated"
        fresh_result = second_manager.get_concept_rankings(5)

        self.assertEqual(fetcher.calls, 1)
        self.assertEqual(fresh_result[0][0]["name"], "top-5")

    def test_extract_board_details_exposes_concept_rankings(self) -> None:
        snapshot = {
            "fundamental_context": {
                "belong_boards": [{"name": "机器人概念", "type": "概念"}],
                "concept_boards": {
                    "status": "ok",
                    "data": {
                        "top": [{"name": "机器人概念", "change_pct": "4.2%", "source": "akshare"}],
                        "bottom": [],
                    },
                },
            },
        }

        extracted = extract_board_detail_fields(snapshot)
        details = ReportDetails(context_snapshot=snapshot)

        self.assertEqual(extracted["concept_rankings"]["top"][0]["name"], "机器人概念")
        self.assertEqual(extracted["concept_rankings"]["top"][0]["change_pct"], 4.2)
        self.assertEqual(extracted["concept_rankings"]["top"][0]["source"], "akshare")
        self.assertEqual(details.concept_rankings["top"][0]["name"], "机器人概念")

    def test_extract_market_structure_details_from_enhanced_context(self) -> None:
        snapshot = {
            "enhanced_context": {
                "market_structure_context": {
                    "schema_version": "market-structure-v1",
                    "status": "partial",
                    "market": "cn",
                    "market_theme_context": {
                        "schema_version": "market-theme-v1",
                        "status": "partial",
                        "market": "cn",
                        "active_themes": [{"name": "机器人概念"}],
                    },
                    "stock_market_position": {
                        "schema_version": "stock-market-position-v1",
                        "status": "partial",
                        "stock_code": "300024",
                        "market": "cn",
                        "primary_theme": {"name": "机器人概念"},
                    },
                }
            }
        }

        extracted = extract_market_structure_detail_field(snapshot)
        details = ReportDetails(context_snapshot=snapshot)

        self.assertEqual(extracted["stock_market_position"]["primary_theme"]["name"], "机器人概念")
        self.assertEqual(details.market_structure["market_theme_context"]["active_themes"][0]["name"], "机器人概念")

    def test_extract_market_structure_details_from_raw_result_fallback(self) -> None:
        payload = {
            "schema_version": "market-structure-v1",
            "status": "partial",
            "market": "cn",
            "market_theme_context": {
                "schema_version": "market-theme-v1",
                "status": "partial",
                "market": "cn",
                "active_themes": [{"name": "机器人概念"}],
            },
            "stock_market_position": {
                "schema_version": "stock-market-position-v1",
                "status": "partial",
                "stock_code": "300024",
                "market": "cn",
                "primary_theme": {"name": "机器人概念"},
            },
        }

        extracted = extract_market_structure_detail_field(
            None,
            {"market_structure_context": payload},
        )
        details = ReportDetails(raw_result={"market_structure_context": payload})

        self.assertEqual(extracted["stock_market_position"]["primary_theme"]["name"], "机器人概念")
        self.assertEqual(details.market_structure["market_theme_context"]["active_themes"][0]["name"], "机器人概念")

    def test_attach_belong_boards_copies_existing_board_list(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()

        existing_boards = [{"name": "白酒", "type": "行业"}]
        context = {
            "market": "cn",
            "status": "ok",
            "belong_boards": existing_boards,
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("600519", context)

        self.assertIsNot(enriched, context)
        self.assertEqual(enriched["belong_boards"], existing_boards)
        self.assertIsNot(enriched["belong_boards"], existing_boards)
        pipeline.fetcher_manager.get_belong_boards.assert_not_called()

    def test_attach_belong_boards_refetches_empty_cn_board_list(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.return_value = [{"name": "白酒", "type": "行业"}]

        context = {
            "market": "cn",
            "status": "ok",
            "belong_boards": [],
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("600519", context)

        self.assertEqual(enriched["belong_boards"], [{"name": "白酒", "type": "行业"}])
        pipeline.fetcher_manager.get_belong_boards.assert_called_once_with("600519")

    def test_attach_belong_boards_skips_provider_for_non_cn(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()

        context = {"market": "us", "status": "not_supported"}
        enriched = pipeline._attach_belong_boards_to_fundamental_context("AAPL", context)

        self.assertEqual(enriched["belong_boards"], [])
        pipeline.fetcher_manager.get_belong_boards.assert_not_called()

    def test_attach_belong_boards_preserves_adapter_boards_for_offshore(self) -> None:
        """HK/US adapters populate belong_boards from yfinance; pipeline must not clobber."""
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()

        existing_boards = [
            {"name": "Technology", "type": "行业"},
            {"name": "Consumer Electronics", "type": "概念"},
        ]
        context = {"market": "us", "status": "ok", "belong_boards": existing_boards}
        enriched = pipeline._attach_belong_boards_to_fundamental_context("AAPL", context)

        self.assertEqual(enriched["belong_boards"], existing_boards)
        pipeline.fetcher_manager.get_belong_boards.assert_not_called()

    def test_attach_belong_boards_skips_provider_when_board_block_not_supported(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()

        context = {
            "market": "cn",
            "status": "partial",
            "coverage": {"boards": "not_supported"},
            "boards": {"status": "not_supported", "data": {}},
            "errors": ["etf not fully supported"],
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("159915", context)

        self.assertEqual(enriched["belong_boards"], [])
        pipeline.fetcher_manager.get_belong_boards.assert_not_called()

    def test_attach_belong_boards_skips_provider_when_pipeline_disabled_payload(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()

        context = {
            "market": "cn",
            "status": "not_supported",
            "coverage": {"boards": "not_supported"},
            "boards": {"status": "not_supported", "data": {}},
            "errors": ["fundamental pipeline disabled"],
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("600519", context)

        self.assertEqual(enriched["belong_boards"], [])
        pipeline.fetcher_manager.get_belong_boards.assert_not_called()

    def test_attach_belong_boards_uses_normalized_a_share_code_when_market_missing(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.return_value = [{"name": "白酒"}]

        context = {
            "status": "ok",
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("SH600519", context)

        self.assertEqual(enriched["belong_boards"], [{"name": "白酒"}])
        pipeline.fetcher_manager.get_belong_boards.assert_called_once_with("SH600519")


class _FailingConceptRankingFetcher:
    name = "FailingConceptRankingFetcher"

    def __init__(self) -> None:
        self.calls = 0

    def get_concept_rankings(self, n: int = 5):
        self.calls += 1
        raise ConnectionError("Remote end closed connection without response")


class _UnimplementedConceptRankingFetcher(BaseFetcher):
    """未覆写概念排行的数据源，沿用基类默认的 None 返回。"""

    name = "UnimplementedConceptRankingFetcher"

    def _fetch_raw_data(self, *args, **kwargs):  # pragma: no cover - 测试占位
        return None

    def _normalize_data(self, *args, **kwargs):  # pragma: no cover - 测试占位
        return None


class ConceptRankingsFallbackTestCase(unittest.TestCase):
    """概念排行只有 Akshare 一个真实实现，失败时不能被无实现数据源掩盖根因。"""

    def tearDown(self) -> None:
        DataFetcherManager.clear_concept_rankings_cache_for_tests()

    def _manager(self, fetchers):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = fetchers
        return manager

    def test_unimplemented_fetcher_does_not_mask_real_error(self) -> None:
        failing = _FailingConceptRankingFetcher()
        manager = self._manager([failing, _UnimplementedConceptRankingFetcher()])

        with self.assertLogs("data_provider.base", level="WARNING") as captured:
            self.assertEqual(manager.get_concept_rankings(5), ([], []))

        summary = [line for line in captured.output if "所有数据源均失败" in line]
        self.assertEqual(len(summary), 1)
        # 根因必须是 Akshare 侧的连接错误，而不是无实现数据源的“返回空结果”
        self.assertIn("FailingConceptRankingFetcher", summary[0])
        self.assertIn("Remote end closed connection", summary[0])
        self.assertNotIn("UnimplementedConceptRankingFetcher返回空结果", summary[0])

    def test_unimplemented_fetcher_is_not_invoked(self) -> None:
        unimplemented = _UnimplementedConceptRankingFetcher()
        manager = self._manager([unimplemented])

        with self.assertLogs("data_provider.base", level="WARNING") as captured:
            self.assertEqual(manager.get_concept_rankings(5), ([], []))

        self.assertTrue(
            any("无数据源实现" in line for line in captured.output),
            f"应明确提示无实现，实际日志: {captured.output}",
        )

    def test_failed_lookup_is_cached_long_enough_to_avoid_hammering(self) -> None:
        """限流是按 IP 粘性的，失败缓存过短会让单轮分析内反复叩门。"""
        failing = _FailingConceptRankingFetcher()
        manager = self._manager([failing])

        clock = {"now": 1000.0}
        # 只替换 base.py 引用的 time 名字，避免把全局 time.monotonic 也改掉
        fake_time = mock.Mock(wraps=time)
        fake_time.monotonic = lambda: clock["now"]
        with mock.patch.object(base_module, "time", fake_time):
            manager.get_concept_rankings(5)
            self.assertEqual(failing.calls, 1)

            # 单轮分析常见跨度（本轮 16 只跑了约 905s），60s 后不应重新打接口
            clock["now"] += 60.0
            manager.get_concept_rankings(5)
            self.assertEqual(failing.calls, 1)

    def test_akshare_propagates_network_error_instead_of_returning_none(self) -> None:
        """Akshare 是概念排行唯一真实实现，吞掉异常会让管理器把限流误判成“数据为空”。"""
        from data_provider.akshare_fetcher import AkshareFetcher

        fetcher = AkshareFetcher.__new__(AkshareFetcher)
        fetcher._set_random_user_agent = lambda: None
        fetcher._enforce_rate_limit = lambda: None

        boom = ConnectionError("Remote end closed connection without response")
        with mock.patch(
            "akshare.stock_board_concept_name_em", side_effect=boom
        ):
            with self.assertRaises(ConnectionError):
                fetcher.get_concept_rankings(5)

    def test_empty_upstream_data_still_reported_as_empty_not_failure(self) -> None:
        """区分“确实没数据”和“取数失败”：空 DataFrame 仍应是 None，不应抛异常。"""
        import pandas as pd

        from data_provider.akshare_fetcher import AkshareFetcher

        fetcher = AkshareFetcher.__new__(AkshareFetcher)
        fetcher._set_random_user_agent = lambda: None
        fetcher._enforce_rate_limit = lambda: None

        with mock.patch(
            "akshare.stock_board_concept_name_em", return_value=pd.DataFrame()
        ):
            self.assertIsNone(fetcher.get_concept_rankings(5))

    def test_akshare_failure_reason_reaches_summary_log(self) -> None:
        """端到端：管理器摘要行必须带上 Akshare 的真实失败原因，而不是“返回空结果”。"""
        from data_provider.akshare_fetcher import AkshareFetcher

        fetcher = AkshareFetcher.__new__(AkshareFetcher)
        fetcher._set_random_user_agent = lambda: None
        fetcher._enforce_rate_limit = lambda: None
        manager = self._manager([fetcher, _UnimplementedConceptRankingFetcher()])

        boom = ConnectionError("Remote end closed connection without response")
        with mock.patch("akshare.stock_board_concept_name_em", side_effect=boom):
            with self.assertLogs("data_provider.base", level="WARNING") as captured:
                self.assertEqual(manager.get_concept_rankings(5), ([], []))

        summary = [line for line in captured.output if "所有数据源均失败" in line]
        self.assertEqual(len(summary), 1)
        self.assertIn("Remote end closed connection", summary[0])
        self.assertNotIn("AkshareFetcher返回空结果", summary[0])

    def test_successful_lookup_short_circuits_remaining_fetchers(self) -> None:
        failing = _FailingConceptRankingFetcher()
        working = _SlowConceptRankingFetcher()
        manager = self._manager([failing, working])

        top, bottom = manager.get_concept_rankings(5)

        self.assertEqual(top[0]["name"], "top-5")
        self.assertEqual(bottom[0]["name"], "bottom-5")
        self.assertEqual(failing.calls, 1)
        self.assertEqual(working.calls, 1)


if __name__ == "__main__":
    unittest.main()
