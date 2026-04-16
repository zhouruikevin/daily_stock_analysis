#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史分析记录行情指标回补脚本

回补 AnalysisHistory 表中新增的 5 个行情快照字段：
  - change_pct: 当日涨跌幅(%)
  - volume_ratio: 量比
  - turnover_rate: 换手率(%)
  - index_csi2000_pct: 中证2000涨跌幅(%)
  - index_chinext_pct: 创业板涨跌幅(%)

分两步执行：
  Step A (metrics): 从 context_snapshot / raw_result JSON 回补个股行情指标
  Step B (index):   从 TuShare API 回补指数涨跌幅

用法:
  python scripts/backfill_history_metrics.py                    # 完整回补
  python scripts/backfill_history_metrics.py --step metrics     # 仅回补个股行情
  python scripts/backfill_history_metrics.py --step index       # 仅回补指数涨跌
  python scripts/backfill_history_metrics.py --db ./data/stock_analysis.db
  python scripts/backfill_history_metrics.py --dry-run          # 试运行
  python scripts/backfill_history_metrics.py --start-date 2026-03-01 --end-date 2026-04-15
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


# ============ Helpers ============

def _safe_parse_percent(val: Any) -> Optional[float]:
    """Parse a value to float, handling 'N/A', '%', None, etc."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        v = float(val)
        return v if -100 <= v <= 100 else None
    s = str(val).strip()
    if s in ('', 'N/A', 'n/a', 'None', 'none', '--', '-'):
        return None
    if s.endswith('%'):
        s = s[:-1].strip()
    try:
        v = float(s)
        return v if -100 <= v <= 100 else None
    except (ValueError, TypeError):
        return None


def _safe_parse_num(val: Any, lo: float = 0, hi: float = 100) -> Optional[float]:
    """Parse a numeric value with range check."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        v = float(val)
        return v if lo <= v <= hi else None
    s = str(val).strip()
    if s in ('', 'N/A', 'n/a', 'None', 'none', '--', '-'):
        return None
    if s.endswith('%'):
        s = s[:-1].strip()
    try:
        v = float(s)
        return v if lo <= v <= hi else None
    except (ValueError, TypeError):
        return None


def _is_a_share(code: str) -> bool:
    """Check if a stock code is A-share (6-digit numeric)."""
    return bool(code and len(code) == 6 and code.isdigit())


def _parse_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """Safely parse JSON string."""
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


# ============ Step A: Extract metrics from JSON ============

def extract_metrics_from_context(context_snapshot: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Extract change_pct, volume_ratio, turnover_rate from context_snapshot.

    Priority:
      1. enhanced_context.realtime
      2. realtime_quote_raw
    """
    metrics: Dict[str, Optional[float]] = {
        "change_pct": None,
        "volume_ratio": None,
        "turnover_rate": None,
    }

    # Priority 1: enhanced_context.realtime
    ec = context_snapshot.get("enhanced_context") or {}
    rt = ec.get("realtime") or {}
    if rt:
        metrics["change_pct"] = _safe_parse_percent(rt.get("change_pct"))
        metrics["volume_ratio"] = _safe_parse_num(rt.get("volume_ratio"), 0, 200)
        metrics["turnover_rate"] = _safe_parse_num(rt.get("turnover_rate"), 0, 100)

    # Priority 2: realtime_quote_raw
    rqr = context_snapshot.get("realtime_quote_raw") or {}
    if rqr:
        if metrics["change_pct"] is None:
            metrics["change_pct"] = _safe_parse_percent(
                rqr.get("change_pct") or rqr.get("pct_chg")
            )
        if metrics["volume_ratio"] is None:
            metrics["volume_ratio"] = _safe_parse_num(rqr.get("volume_ratio"), 0, 200)
        if metrics["turnover_rate"] is None:
            metrics["turnover_rate"] = _safe_parse_num(rqr.get("turnover_rate"), 0, 100)

    return metrics


def extract_metrics_from_raw_result(raw_result: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Fallback: extract from raw_result (market_snapshot + dashboard)."""
    metrics: Dict[str, Optional[float]] = {
        "change_pct": None,
        "volume_ratio": None,
        "turnover_rate": None,
    }

    # Priority 3: market_snapshot
    ms = raw_result.get("market_snapshot") or {}
    if ms:
        metrics["change_pct"] = _safe_parse_percent(
            ms.get("pct_chg") or ms.get("change_pct")
        )
        metrics["volume_ratio"] = _safe_parse_num(ms.get("volume_ratio"), 0, 200)
        metrics["turnover_rate"] = _safe_parse_num(ms.get("turnover_rate"), 0, 100)

    # Priority 4: dashboard.data_perspective
    dashboard = raw_result.get("dashboard") or {}
    dp = dashboard.get("data_perspective") or {}
    va = dp.get("volume_analysis") or {}
    if va:
        if metrics["volume_ratio"] is None:
            metrics["volume_ratio"] = _safe_parse_num(va.get("volume_ratio"), 0, 200)
        if metrics["turnover_rate"] is None:
            metrics["turnover_rate"] = _safe_parse_num(va.get("turnover_rate"), 0, 100)

    return metrics


def merge_metrics(
    target: Dict[str, Optional[float]],
    source: Dict[str, Optional[float]],
) -> Dict[str, Optional[float]]:
    """Merge source into target, only filling None fields."""
    for key in target:
        if target[key] is None and source.get(key) is not None:
            target[key] = source[key]
    return target


def backfill_metrics(
    session,
    dry_run: bool = False,
    batch_size: int = 100,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, int]:
    """Step A: Backfill change_pct, volume_ratio, turnover_rate from JSON."""
    stats = {
        "total": 0,
        "updated": 0,
        "skipped": 0,
        "change_pct_hits": 0,
        "volume_ratio_hits": 0,
        "turnover_rate_hits": 0,
    }

    # Build where clause
    conditions = ["change_pct IS NULL"]
    params: Dict[str, Any] = {}
    if start_date:
        conditions.append("created_at >= :start_date")
        params["start_date"] = start_date.isoformat()
    if end_date:
        conditions.append("created_at < :end_date_exclusive")
        params["end_date_exclusive"] = (
            date(end_date.year, end_date.month, end_date.day + 1)
            if end_date.day < 28
            else end_date.isoformat()  # simplified
        )

    where_clause = " AND ".join(conditions)

    # Count
    count_sql = f"SELECT COUNT(*) FROM analysis_history WHERE {where_clause}"
    stats["total"] = session.execute(text(count_sql), params).scalar() or 0

    if stats["total"] == 0:
        print(f"[Step A] 无需回补的记录")
        return stats

    print(f"[Step A] 需回补记录数: {stats['total']}")

    # Process in batches using cursor-based pagination (id > last_id)
    # This avoids OFFSET issues when rows are updated during processing
    last_id = 0
    updated_count = 0

    while True:
        query_sql = f"""
            SELECT id, context_snapshot, raw_result
            FROM analysis_history
            WHERE {where_clause} AND id > :last_id
            ORDER BY id
            LIMIT :limit
        """
        batch_params = {**params, "limit": batch_size, "last_id": last_id}
        rows = session.execute(text(query_sql), batch_params).fetchall()

        if not rows:
            break

        for row in rows:
            row_id, ctx_raw, raw_raw = row
            last_id = row_id

            # Try context_snapshot first
            metrics = {"change_pct": None, "volume_ratio": None, "turnover_rate": None}

            ctx = _parse_json(ctx_raw)
            if ctx:
                ctx_metrics = extract_metrics_from_context(ctx)
                metrics = merge_metrics(metrics, ctx_metrics)

            # Also try raw_result as fallback for missing fields
            raw = _parse_json(raw_raw)
            if raw:
                raw_metrics = extract_metrics_from_raw_result(raw)
                metrics = merge_metrics(metrics, raw_metrics)

            # Only update if we found at least one value
            if any(v is not None for v in metrics.values()):
                if not dry_run:
                    update_sql = text("""
                        UPDATE analysis_history
                        SET change_pct = :change_pct,
                            volume_ratio = :volume_ratio,
                            turnover_rate = :turnover_rate
                        WHERE id = :id
                    """)
                    session.execute(update_sql, {
                        "change_pct": metrics["change_pct"],
                        "volume_ratio": metrics["volume_ratio"],
                        "turnover_rate": metrics["turnover_rate"],
                        "id": row_id,
                    })

                updated_count += 1
                if metrics["change_pct"] is not None:
                    stats["change_pct_hits"] += 1
                if metrics["volume_ratio"] is not None:
                    stats["volume_ratio_hits"] += 1
                if metrics["turnover_rate"] is not None:
                    stats["turnover_rate_hits"] += 1
            else:
                stats["skipped"] += 1

        if not dry_run:
            session.commit()

        print(f"  已处理到 ID={last_id}, 已更新 {updated_count} 条", end="\r")

    stats["updated"] = updated_count
    print(f"\n[Step A] 完成: 更新 {updated_count} 条, 跳过 {stats['skipped']} 条")
    print(f"  change_pct 命中: {stats['change_pct_hits']}")
    print(f"  volume_ratio 命中: {stats['volume_ratio_hits']}")
    print(f"  turnover_rate 命中: {stats['turnover_rate_hits']}")

    return stats


# ============ Step B: Fetch index data from TuShare ============

def fetch_index_pct_map(
    dates: List[str],
    tushare_token: str,
    tushare_api_url: Optional[str] = None,
) -> Dict[str, Dict[str, Optional[float]]]:
    """Fetch index pct_chg from TuShare for given dates.

    When TUSHARE_API_URL is configured (proxy endpoint), uses the official
    tushare SDK with pro._DataApi__http_url override, because the proxy
    token only works through the official SDK.
    Otherwise falls back to the built-in _TushareHttpClient.

    Returns:
        {date_str: {"csi2000_pct": float, "chinext_pct": float}}
    """
    if tushare_api_url:
        # 使用官方 tushare SDK + 自定义端点（代理 token 仅通过此方式生效）
        try:
            import tushare as ts
            pro = ts.pro_api(tushare_token)
            pro._DataApi__http_url = tushare_api_url
            print(f"  TuShare: 使用官方 SDK + 代理端点 ({tushare_api_url})")
        except ImportError:
            print("  警告: tushare SDK 未安装，回退到内置 HTTP client；代理端点可能不兼容")
            from data_provider.tushare_fetcher import _TushareHttpClient
            pro = _TushareHttpClient(token=tushare_token, api_url=tushare_api_url)
    else:
        from data_provider.tushare_fetcher import _TushareHttpClient
        pro = _TushareHttpClient(token=tushare_token)
        print("  TuShare: 使用内置 HTTP client (默认端点)")
    index_map: Dict[str, Dict[str, Optional[float]]] = {}

    for d in dates:
        index_map[d] = {"csi2000_pct": None, "chinext_pct": None}

        for ts_code, key in [("399303.SZ", "csi2000_pct"), ("399006.SZ", "chinext_pct")]:
            try:
                df = pro.index_daily(
                    ts_code=ts_code,
                    start_date=d.replace("-", ""),
                    end_date=d.replace("-", ""),
                )
                if df is not None and not df.empty:
                    pct = float(df.iloc[0]["pct_chg"])
                    index_map[d][key] = pct
            except Exception as e:
                print(f"  TuShare index_daily {ts_code} for {d} failed: {e}")

        # Rate limit: TuShare free tier ~80 calls/min
        time.sleep(0.8)

    return index_map


def backfill_index(
    session,
    index_map: Dict[str, Dict[str, Optional[float]]],
    dry_run: bool = False,
    batch_size: int = 100,
) -> Dict[str, int]:
    """Step B: Backfill index_csi2000_pct and index_chinext_pct for A-share records."""
    stats = {"total": 0, "updated": 0}

    for date_str, pcts in index_map.items():
        if pcts["csi2000_pct"] is None and pcts["chinext_pct"] is None:
            continue

        # Find A-share records on this date needing update
        count_sql = text("""
            SELECT COUNT(*) FROM analysis_history
            WHERE DATE(created_at) = :date_str
              AND LENGTH(code) = 6 AND code GLOB '[0-9]*'
              AND (index_csi2000_pct IS NULL OR index_chinext_pct IS NULL)
        """)
        count = session.execute(count_sql, {"date_str": date_str}).scalar() or 0
        stats["total"] += count

        if count == 0:
            continue

        if not dry_run:
            update_sql = text("""
                UPDATE analysis_history
                SET index_csi2000_pct = :csi2000,
                    index_chinext_pct = :chinext
                WHERE DATE(created_at) = :date_str
                  AND LENGTH(code) = 6 AND code GLOB '[0-9]*'
                  AND (index_csi2000_pct IS NULL OR index_chinext_pct IS NULL)
            """)
            result = session.execute(update_sql, {
                "csi2000": pcts["csi2000_pct"],
                "chinext": pcts["chinext_pct"],
                "date_str": date_str,
            })
            stats["updated"] += result.rowcount
            session.commit()
        else:
            stats["updated"] += count

        print(f"  {date_str}: 中证2000={pcts['csi2000_pct']}, 创业板={pcts['chinext_pct']} ({count}条)")

    print(f"[Step B] 完成: 更新 {stats['updated']} 条")
    return stats


# ============ Main ============

def main():
    parser = argparse.ArgumentParser(description="回补历史分析记录行情指标")
    parser.add_argument(
        "--step",
        choices=["metrics", "index", "all"],
        default="all",
        help="回补步骤: metrics(个股行情), index(指数涨跌), all(两步都执行)",
    )
    parser.add_argument(
        "--db",
        default="./data/stock_analysis.db",
        help="数据库路径 (默认: ./data/stock_analysis.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行，不写入数据库",
    )
    parser.add_argument(
        "--start-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        help="开始日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        help="结束日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="批处理大小 (默认: 100)",
    )

    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"错误: 数据库文件不存在: {args.db}")
        sys.exit(1)

    print(f"=== 历史分析记录行情指标回补 ===")
    print(f"数据库: {args.db}")
    print(f"步骤: {args.step}")
    print(f"试运行: {args.dry_run}")
    print()

    engine = create_engine(f"sqlite:///{args.db}")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Step A: Backfill metrics from JSON
        if args.step in ("metrics", "all"):
            backfill_metrics(
                session,
                dry_run=args.dry_run,
                batch_size=args.batch_size,
                start_date=args.start_date,
                end_date=args.end_date,
            )

        # Step B: Backfill index from TuShare
        if args.step in ("index", "all"):
            tushare_token = os.environ.get("TUSHARE_TOKEN", "")
            tushare_api_url = os.environ.get("TUSHARE_API_URL", "") or None
            if not tushare_token:
                # Try loading from .env
                env_file = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    ".env",
                )
                if os.path.exists(env_file):
                    with open(env_file, "r") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("TUSHARE_TOKEN="):
                                tushare_token = line.split("=", 1)[1].strip().strip('"').strip("'")
                            elif line.startswith("TUSHARE_API_URL="):
                                url_val = line.split("=", 1)[1].strip().strip('"').strip("'")
                                if url_val:
                                    tushare_api_url = url_val

            if not tushare_token:
                print("[Step B] 跳过: 未配置 TUSHARE_TOKEN")
                print("  请设置环境变量 TUSHARE_TOKEN 或在 .env 中配置")
            else:
                # Collect distinct dates from A-share records
                date_sql = text("""
                    SELECT DISTINCT DATE(created_at) as d
                    FROM analysis_history
                    WHERE LENGTH(code) = 6 AND code GLOB '[0-9]*'
                      AND (index_csi2000_pct IS NULL OR index_chinext_pct IS NULL)
                    ORDER BY d
                """)
                if args.start_date:
                    date_sql = text("""
                        SELECT DISTINCT DATE(created_at) as d
                        FROM analysis_history
                        WHERE LENGTH(code) = 6 AND code GLOB '[0-9]*'
                          AND (index_csi2000_pct IS NULL OR index_chinext_pct IS NULL)
                          AND created_at >= :start_date
                        ORDER BY d
                    """)

                date_params = {}
                if args.start_date:
                    date_params["start_date"] = args.start_date.isoformat()

                dates_rows = session.execute(date_sql, date_params).fetchall()
                dates = [str(row[0]) for row in dates_rows if row[0]]

                if not dates:
                    print("[Step B] 无需回补指数数据的记录")
                else:
                    print(f"[Step B] 需回补指数数据的日期数: {len(dates)}")
                    index_map = fetch_index_pct_map(dates, tushare_token, tushare_api_url=tushare_api_url)
                    backfill_index(session, index_map, dry_run=args.dry_run, batch_size=args.batch_size)

    finally:
        session.close()

    print("\n=== 回补完成 ===")


if __name__ == "__main__":
    main()
