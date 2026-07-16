#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取股票分析上下文数据（不调 LLM），输出 JSON 供 Qoder AI 分析。

复用项目的 data_provider / 技术分析 / 新闻搜索，但不调用 GeminiAnalyzer（LLM）。
用法：
    python scripts/fetch_stock_context.py 603444
    python scripts/fetch_stock_context.py 603444 --skip-news
    python scripts/fetch_stock_context.py 603444 -o /tmp/context.json
"""

import sys
import os
import json
import logging
import threading
from datetime import date, datetime, timedelta

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

import pandas as pd
from src.config import get_config, FUNDAMENTAL_STAGE_TIMEOUT_SECONDS_DEFAULT
from data_provider import DataFetcherManager
from src.stock_analyzer import StockTrendAnalyzer
from src.search_service import SearchService
from src.storage import get_db

# v3.0 新增：市场阶段 / 大盘指数 / 数据质量评估 / 持久化情报
from src.core.trading_calendar import build_market_phase_context, get_market_for_stock
from src.market_phase_summary import render_market_phase_summary
from src.services.analysis_context_builder import AnalysisContextBuilder, PipelineAnalysisArtifacts

logger = logging.getLogger(__name__)


def safe_to_dict(obj):
    """安全将对象转为可 JSON 序列化的 dict。"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, (str, int, float, bool)):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def augment_with_realtime(df, realtime_quote):
    """用实时行情增强历史 K 线最后一行（盘中技术指标用实时价格）。"""
    if df is None or df.empty or realtime_quote is None:
        return df
    price = getattr(realtime_quote, "price", None)
    if not (isinstance(price, (int, float)) and price > 0):
        return df

    df = df.copy()
    last_val = df["date"].max()
    last_date = last_val.date() if hasattr(last_val, "date") else pd.Timestamp(last_val).date()
    today = date.today()

    open_p = getattr(realtime_quote, "open_price", None) or getattr(realtime_quote, "pre_close", None)
    high_p = getattr(realtime_quote, "high", None) or price
    low_p = getattr(realtime_quote, "low", None) or price
    vol = getattr(realtime_quote, "volume", None) or 0
    amt = getattr(realtime_quote, "amount", None)
    pct = getattr(realtime_quote, "change_pct", None) or getattr(realtime_quote, "pct_chg", None)

    if last_date >= today:
        idx = df.index[-1]
        df.loc[idx, "close"] = price
        if open_p:
            df.loc[idx, "open"] = open_p
        if high_p:
            df.loc[idx, "high"] = high_p
        if low_p:
            df.loc[idx, "low"] = low_p
        if vol:
            df.loc[idx, "volume"] = vol
        if amt is not None:
            df.loc[idx, "amount"] = amt
        if pct is not None:
            df.loc[idx, "pct_chg"] = pct
    else:
        new_row = {
            "date": today,
            "open": open_p or price,
            "high": high_p,
            "low": low_p,
            "close": price,
            "volume": vol,
        }
        if amt is not None:
            new_row["amount"] = amt
        if pct is not None:
            new_row["pct_chg"] = pct
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    return df


def fetch_context(code, skip_news=False):
    """
    获取股票完整分析上下文（不调 LLM）。

    Returns:
        dict: 包含行情、技术指标、筹码、基本面、新闻等数据。
    """
    config = get_config()
    db = get_db()
    fetcher = DataFetcherManager()
    trend_analyzer = StockTrendAnalyzer()

    # 初始化搜索服务
    search_service = None
    try:
        search_service = SearchService(
            bocha_keys=config.bocha_api_keys,
            tavily_keys=config.tavily_api_keys,
            anspire_keys=config.anspire_api_keys,
            brave_keys=config.brave_api_keys,
            serpapi_keys=config.serpapi_keys,
            bailian_keys=config.bailian_api_keys,
            searxng_base_urls=config.searxng_base_urls,
            searxng_public_instances_enabled=config.searxng_public_instances_enabled,
            news_max_age_days=config.news_max_age_days,
            news_strategy_profile=getattr(config, "news_strategy_profile", "short"),
        )
    except Exception as e:
        logger.warning("搜索服务初始化失败: %s", e)

    result = {"code": code, "fetch_time": datetime.now().isoformat()}

    # 1. 股票名称
    stock_name = code
    try:
        name = fetcher.get_stock_name(code, allow_realtime=False)
        if name:
            stock_name = name
    except Exception as e:
        result["error_name"] = str(e)
    result["name"] = stock_name

    # 1.5 市场阶段上下文（盘中/盘后/盘前判断）
    market = None
    try:
        from data_provider.base import normalize_stock_code
        normalized = normalize_stock_code(code)
        market = get_market_for_stock(normalized)
        phase_ctx = build_market_phase_context(
            market=market, current_time=datetime.now(),
            trigger_source="skill", analysis_phase="auto",
        )
        phase_dict = phase_ctx.to_dict()
        result["market_phase"] = phase_dict
        result["market_phase_summary"] = render_market_phase_summary(phase_dict)
    except Exception as e:
        result["error_market_phase"] = str(e)

    # 1.6 大盘指数（中证2000 / 创业板）
    try:
        if market and market == "cn":
            pct_map = fetcher.get_index_change_pct(['399303', '399006'])
            result["index_snapshot"] = {
                "csi2000_pct": pct_map.get('399303'),
                "chinext_pct": pct_map.get('399006'),
            }
    except Exception as e:
        result["error_index"] = str(e)

    # 2. 获取历史 K 线并保存到数据库
    try:
        df_hist, source_name = fetcher.get_daily_data(code, days=60)
        if df_hist is not None and not df_hist.empty:
            db.save_daily_data(df_hist, code, source_name)
            result["data_source"] = source_name
    except Exception as e:
        result["error_history_fetch"] = str(e)

    # 3. 实时行情
    realtime_quote = None
    try:
        if config.enable_realtime_quote:
            realtime_quote = fetcher.get_realtime_quote(code, log_final_failure=False)
            if realtime_quote:
                result["realtime"] = safe_to_dict(realtime_quote)
                if realtime_quote.name:
                    stock_name = realtime_quote.name
                    result["name"] = stock_name
    except Exception as e:
        result["error_realtime"] = str(e)

    # 4. 基础上下文（today / yesterday K 线）
    try:
        context = db.get_analysis_context(code)
        if context:
            result["base_context"] = context
    except Exception as e:
        result["error_base_context"] = str(e)

    # 5. 技术分析（均线 / 趋势 / 量价）
    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=89)
        historical_bars = db.get_data_range(code, start_date, end_date)
        if historical_bars:
            df = pd.DataFrame([bar.to_dict() for bar in historical_bars])
            if realtime_quote:
                df = augment_with_realtime(df, realtime_quote)
            trend = trend_analyzer.analyze(df, code)
            if trend:
                result["trend"] = safe_to_dict(trend)
    except Exception as e:
        result["error_trend"] = str(e)

    # 6. 筹码分布
    try:
        if config.enable_chip_distribution:
            chip = fetcher.get_chip_distribution(code)
            if chip:
                result["chip"] = safe_to_dict(chip)
    except Exception as e:
        result["error_chip"] = str(e)

    # 7. 基本面（PE / PB / ROE / 财报）
    try:
        fundamental = fetcher.get_fundamental_context(
            code,
            budget_seconds=getattr(
                config,
                "fundamental_stage_timeout_seconds",
                FUNDAMENTAL_STAGE_TIMEOUT_SECONDS_DEFAULT,
            ),
        )
        if fundamental:
            result["fundamental"] = fundamental
            # v3.0: 保存基本面快照到 DB（write-only, fail-open）
            try:
                import uuid
                query_id = str(uuid.uuid4())
                db.save_fundamental_snapshot(
                    query_id=query_id, code=code, payload=fundamental,
                    source_chain=fundamental.get("source_chain", []),
                    coverage=fundamental.get("coverage", {}),
                )
            except Exception as fs_e:
                logger.debug("基本面快照写入失败: %s", fs_e)
    except Exception as e:
        result["error_fundamental"] = str(e)

    # 8. 所属板块
    try:
        boards = fetcher.get_belong_board(code)
        if boards:
            result["boards"] = boards if isinstance(boards, list) else [boards]
    except Exception:
        pass  # 板块信息非关键，静默

    # 9. 新闻情报搜索
    if not skip_news:
        try:
            if search_service and search_service.is_available:
                logger.info("开始情报搜索: %s(%s)", stock_name, code)
                intel_container = {"results": None, "exception": None}

                def _do_search():
                    try:
                        intel_container["results"] = search_service.search_comprehensive_intel(
                            stock_code=code,
                            stock_name=stock_name,
                            max_searches=5,
                        )
                    except Exception as exc:
                        intel_container["exception"] = exc

                search_thread = threading.Thread(target=_do_search, daemon=True)
                search_thread.start()
                search_thread.join(timeout=60)

                if search_thread.is_alive():
                    result["error_news"] = "搜索超时(60s)"
                elif intel_container["exception"]:
                    result["error_news"] = str(intel_container["exception"])
                else:
                    intel_results = intel_container["results"] or {}
                    if intel_results:
                        news_context = search_service.format_intel_report(
                            intel_results, stock_name
                        )
                        result["news"] = news_context
                        total = sum(
                            len(r.results)
                            for r in intel_results.values()
                            if r and hasattr(r, "results")
                        )
                        result["news_count"] = total

                        # v3.0: 保存新闻情报到 DB
                        try:
                            for dim_name, response in intel_results.items():
                                if response and response.success and response.results:
                                    db.save_news_intel(
                                        code=code, name=stock_name,
                                        dimension=dim_name,
                                        query=response.query,
                                        response=response,
                                    )
                        except Exception as ni_e:
                            logger.debug("新闻情报保存失败: %s", ni_e)
        except Exception as e:
            result["error_news"] = str(e)

    # 10. 持久化情报上下文（历史新闻补充）
    try:
        from src.services.intelligence_service import IntelligenceService
        intel_service = IntelligenceService()
        days = max(1, int(getattr(config, "news_max_age_days", 7) or 7))
        collected = []
        seen_urls = set()
        # 构建符号查找值
        raw_code = str(code or "").strip()
        symbol_values = [raw_code, raw_code.upper(), raw_code.lower()]
        if raw_code.upper().startswith("HK") and raw_code[2:].isdigit():
            digits = raw_code[2:]
            symbol_values.extend([digits, digits.lstrip("0") or digits])
        symbol_filters = [
            {"scope_type": "symbol", "scope_value": sv, "market": market or "cn"}
            for sv in symbol_values
        ]
        symbol_filters.append({"scope_type": "market", "market": market or "cn"})
        for filters in symbol_filters:
            payload = intel_service.list_items(published_days=days, page=1, page_size=6, **filters)
            for item in payload.get("items", []):
                url = str(item.get("url") or "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                collected.append(item)
                if len(collected) >= 6:
                    break
            if len(collected) >= 6:
                break
        if collected:
            lines = [f"## 本地资讯证据池（{stock_name}/{code}）"]
            for idx, item in enumerate(collected[:6], 1):
                title = str(item.get("title") or "未命名资讯").strip()
                summary = str(item.get("summary") or "").strip()
                source = str(item.get("source") or item.get("source_name") or "local-intel").strip()
                published = str(item.get("published_at") or "").strip()
                url = str(item.get("url") or "").strip()
                meta = " / ".join(p for p in (source, published) if p)
                lines.append(f"{idx}. {title}" + (f"（{meta}）" if meta else ""))
                if summary:
                    lines.append(f"   摘要：{summary[:220]}")
                if url and not url.startswith("no-url:intel:"):
                    lines.append(f"   来源：{url}")
            result["persisted_intelligence"] = "\n".join(lines)
    except Exception as e:
        result["error_persisted_intel"] = str(e)

    # 11. AnalysisContextPack（数据质量评估）
    try:
        context = result.get("base_context") or {}
        enhanced_context = dict(context)
        if realtime_quote:
            enhanced_context["realtime"] = safe_to_dict(realtime_quote)
        if result.get("trend"):
            enhanced_context["trend_analysis"] = result["trend"]
        if result.get("chip"):
            enhanced_context["chip_distribution"] = result["chip"]

        artifacts = PipelineAnalysisArtifacts(
            code=code,
            stock_name=stock_name,
            market=market or "cn",
            phase=result.get("market_phase"),
            base_context=context,
            enhanced_context=enhanced_context,
            realtime_quote=safe_to_dict(realtime_quote),
            trend_result=result.get("trend"),
            chip_data=result.get("chip"),
            fundamental_context=result.get("fundamental"),
            news_context=result.get("news"),
            news_result_count=result.get("news_count"),
            metadata={"trigger_source": "skill"},
        )
        pack = AnalysisContextBuilder.build(artifacts)
        result["context_pack"] = pack.model_dump()
    except Exception as e:
        result["error_context_pack"] = str(e)

    # 12. 指数数据回写 DB（与 pipeline._backfill_index_data_for_stock 对齐）
    try:
        idx = result.get("index_snapshot") or {}
        if idx.get("csi2000_pct") is not None or idx.get("chinext_pct") is not None:
            db.update_index_data_for_today(
                code=code,
                csi2000_pct=idx.get("csi2000_pct"),
                chinext_pct=idx.get("chinext_pct"),
            )
    except Exception as e:
        logger.debug("指数数据回写失败: %s", e)

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="获取股票分析上下文数据（不调 LLM），输出 JSON 供 Qoder AI 分析"
    )
    parser.add_argument("stock_code", help="股票代码（如 600519, hk00700, AAPL）")
    parser.add_argument("--skip-news", action="store_true", help="跳过新闻搜索（加速）")
    parser.add_argument("--output", "-o", help="输出文件路径（默认 stdout）")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    data = fetch_context(args.stock_code, skip_news=args.skip_news)
    output = json.dumps(data, ensure_ascii=False, default=str, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"数据已保存到 {args.output}", file=sys.stderr)
    else:
        print(output)
