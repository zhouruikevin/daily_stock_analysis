#!/usr/bin/env python3
"""A股主要指数 趋势与量价推演（概率化情景预测 + 历史校准闭环）。

信念："市场肯定是对的"——用当前趋势结构与量价配合作先验，默认顺势外推，
量价健康度决定"信多少"，关键位约束"走到哪"，输出未来 5-10 交易日的概率化情景。
每次预测落台账，回填 T+1 与 horizon 末真实走势，并用历史台账校准后续预测。

用法:
  python index_trend.py                              # 默认: 四大指数, 校准开, 写台账+回填
  python index_trend.py --indices sh                 # 仅上证
  python index_trend.py --horizon 10                 # 预测跨度改 10 交易日
  python index_trend.py --json                       # JSON 输出
  python index_trend.py --review                      # 只看历史预测命中率/校准报告
  python index_trend.py --backfill-only              # 只回填旧预测的真实走势
  python index_trend.py --no-calibration             # 关闭历史校准(只出原始模型)
"""
import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 把 project root + 脚本目录加进 sys.path：复用仓库级 data_provider / 同目录模块
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from data_provider import DataFetcherManager  # noqa: E402
import trend_state as _trend  # noqa: E402
import volume_price as _vp  # noqa: E402
import forecast as _forecast  # noqa: E402
import calibration as _calib  # noqa: E402
import channel as _channel  # noqa: E402
import prediction_log as _ledger  # noqa: E402
import notifier as _notifier  # noqa: E402

_MANAGER: Optional["DataFetcherManager"] = None


def _get_manager() -> "DataFetcherManager":
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = DataFetcherManager()
    return _MANAGER


INDEX_CONFIG = {
    "sh": {"name": "上证指数", "code": "000001", "akshare_symbol": "sh000001", "market": "主板"},
    "sz": {"name": "深证成指", "code": "399001", "akshare_symbol": "sz399001", "market": "主板"},
    "cy": {"name": "创业板指", "code": "399006", "akshare_symbol": "sz399006", "market": "创业板"},
    "kc": {"name": "科创50", "code": "000688", "akshare_symbol": "sh000688", "market": "科创板"},
}
DEFAULT_INDICES = ["sh", "sz", "cy", "kc"]


def _fetch_df(index_key: str, days: int):
    cfg = INDEX_CONFIG[index_key]
    df = _get_manager().get_index_daily(cfg["akshare_symbol"], include_today=True)
    if df is None or df.empty:
        return None
    return df.tail(days + 60).copy().reset_index(drop=True)


def analyze_index(index_key: str, *, horizon: int = 7, days: int = 120,
                  swing_threshold: float = 3.0, calibrate: bool = True,
                  channel_lookback: int = 40, channel_k: float = 2.0,
                  channel_r2: float = 0.5,
                  ledger_records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """单指数完整分析：趋势 → 量价 → 上下沿通道 → 原始情景 → 历史校准 → result。"""
    cfg = INDEX_CONFIG[index_key]
    df = _fetch_df(index_key, days)
    if df is None:
        return {"error": f"无法获取 {cfg['name']} 数据", "index_key": index_key,
                "index_name": cfg["name"]}

    current = round(float(df["close"].iloc[-1]), 2)
    trend = _trend.analyze_trend(df, swing_threshold=swing_threshold)
    vp = _vp.analyze_volume_price(df, trend["direction"])
    ch = _channel.compute_channel(df, lookback=channel_lookback,
                                  k=channel_k, trend_r2=channel_r2)
    ch["judgement"] = _channel.judge_breakout(ch, vp)
    raw = _forecast.build_forecast(df, trend, vp, horizon=horizon)

    calibration_meta = {"applied": False, "n_samples": 0}
    forecast = raw
    if calibrate:
        records = ledger_records if ledger_records is not None else _ledger.load_all()
        stats = _calib.load_stats(records, index_key)
        forecast, calibration_meta = _calib.apply(raw, stats)

    # 精简 trend（去掉 pivots 大对象，verbose 时再带）
    trend_slim = {k: v for k, v in trend.items() if k != "pivots"}

    result = {
        "index_key": index_key,
        "index_name": cfg["name"],
        "index_code": cfg["code"],
        "market": cfg["market"],
        "latest_date": str(df["date"].iloc[-1])[:10],
        "data_range": f"{str(df['date'].iloc[0])[:10]} ~ {str(df['date'].iloc[-1])[:10]}",
        "current_price": current,
        "trend": trend_slim,
        "volume_price": vp,
        "channel": ch,
        "key_levels": forecast.get("key_levels"),
        "forecast": {k: v for k, v in forecast.items() if k != "key_levels"},
        "forecast_raw": {k: v for k, v in raw.items() if k != "key_levels"} if calibrate else None,
        "calibration": calibration_meta,
        "_pivots": trend.get("pivots"),  # 内部用，JSON 精简时剔除
        "error": None,
    }
    return result


# ============================================================
# 格式化
# ============================================================
_DIR_CN = {"up": "上升", "down": "下降", "range": "震荡"}
_DIR_ARROW = {"up": "↗", "down": "↘", "range": "→"}


def format_result(r: Dict[str, Any], verbose: bool = False) -> str:
    if r.get("error"):
        return f"❌ {r.get('index_name', r.get('index_key'))}: {r['error']}"
    lines = []
    t = r["trend"]
    vp = r["volume_price"]
    fc = r["forecast"]
    lines.append("=" * 72)
    lines.append(f"  {r['index_name']} ({r['index_code']}) — {r['market']}  当前价 {r['current_price']}")
    lines.append(f"  数据: {r['data_range']}  |  截止 {r['latest_date']}")
    lines.append("=" * 72)

    lines.append(f"\n--- 趋势状态 ---")
    lines.append(f"  方向: {_DIR_CN[t['direction']]}{_DIR_ARROW[t['direction']]}  "
                 f"强度: {t['strength']}({t['strength_label']})  阶段: {t['phase']}")
    lines.append(f"  结构: {t['structure']}  均线: {t['ma_alignment']}  "
                 f"斜率: {t['slope_pct_per_day']}%/日  拟合r²: {t['r2']}")

    lines.append(f"\n--- 量价健康度 ---")
    lines.append(f"  健康度: {vp['health_score']}({vp['health_label']})  "
                 f"量比: {vp['vol_ratio']}  量能: {vp['vol_trend']}")
    lines.append(f"  信号: {' / '.join(vp['signals'])}")

    ch = r.get("channel") or {}
    lines.append(f"\n--- 上下沿通道 ---")
    if ch.get("available"):
        j = ch.get("judgement", {})
        pos_pct = int(round(ch["pos_in_channel"] * 100))
        lines.append(f"  类型: {ch['type']}({ch['direction']}, r²={ch['r2']})  "
                     f"近{ch['lookback']}日  带宽{ch['width_pct']}%")
        lines.append(f"  上沿(阻力): {ch['upper']}   中轨: {ch['mid']}   下沿(支撑): {ch['lower']}")
        lines.append(f"  当前价 {ch['current_price']}   位置 {pos_pct}%")
        lines.append(f"  判断: {j.get('bias','?')}({j.get('confidence','?')})  —  {j.get('reason','')}")
    else:
        lines.append(f"  （{ch.get('reason', '数据不足')}，暂无通道）")

    lines.append(f"\n--- 走势推演 (未来{fc['horizon_days'][0]}-{fc['horizon_days'][1]}交易日) ---")
    er = fc["expected_range"]
    lines.append(f"  预期波动带: {er['low']} ~ {er['high']}  (ATR={fc['atr']})")
    for s in fc["scenarios"]:
        star = "★" if s["type"] == fc["primary_scenario"] else " "
        tr = s["target_range"]
        lines.append(f"  {star} [{s['probability']:>2}%] {s['name']:<12} "
                     f"目标 {tr['low']}~{tr['high']}  触发:{s['trigger']}")
    lines.append(f"  结论: {fc['signal']}")

    cal = r.get("calibration") or {}
    if cal.get("applied"):
        adj = cal.get("prob_adjust", {})
        adj_str = ", ".join(f"{k}{v:+g}" for k, v in adj.items()) if adj else "无概率调整"
        lines.append(f"\n--- 历史校准 (样本{cal.get('n_samples')}, w={cal.get('shrink_w')}) ---")
        lines.append(f"  概率修正: {adj_str}  目标平移: {cal.get('bias_shift_pct', 0)}%  "
                     f"带宽×{cal.get('widen_factor', 1.0)}")
    elif cal.get("n_samples", 0) == 0:
        lines.append(f"\n  (历史校准: 台账暂无样本, 用原始模型; 跑几天积累后自动生效)")

    if verbose and r.get("_pivots"):
        lines.append(f"\n--- 摆动枢轴 ---")
        for p in r["_pivots"][-8:]:
            lines.append(f"  {p['date']}  {p['kind']}  {p['price']:.2f}")
    return "\n".join(lines)


def format_summary(results: List[Dict[str, Any]]) -> str:
    lines = ["\n" + "=" * 72, "  指数趋势推演 总览", "=" * 72, ""]
    lines.append(f"  {'指数':<8} {'方向':<6} {'强度':<8} {'健康':<6} {'主情景(概率)':<18} "
                 f"{'目标区间':<18} {'通道位置/判断':<16}")
    lines.append(f"  {'-'*88}")
    for r in results:
        if r.get("error"):
            lines.append(f"  {r.get('index_name', r.get('index_key','?')):<8} ERROR {r['error']}")
            continue
        t, fc = r["trend"], r["forecast"]
        primary = next((s for s in fc["scenarios"] if s["type"] == fc["primary_scenario"]),
                       fc["scenarios"][0])
        tr = primary["target_range"]
        dir_cell = _DIR_CN[t["direction"]] + _DIR_ARROW[t["direction"]]
        strength_cell = f"{t['strength']}({t['strength_label']})"
        primary_cell = f"{primary['name']}({primary['probability']}%)"
        ch = r.get("channel") or {}
        if ch.get("available"):
            ch_cell = f"{int(round(ch['pos_in_channel']*100))}% {ch.get('judgement',{}).get('bias','')}"
        else:
            ch_cell = "-"
        lines.append(
            f"  {r['index_name']:<8} {dir_cell:<6} {strength_cell:<8} "
            f"{r['volume_price']['health_score']:<6} {primary_cell:<18} "
            f"{tr['low']}~{tr['high']:<12} {ch_cell:<16}"
        )
    return "\n".join(lines)


def _strip_for_json(r: Dict[str, Any], verbose: bool) -> Dict[str, Any]:
    out = {k: v for k, v in r.items() if k != "_pivots"}
    if verbose and r.get("_pivots"):
        out["pivots"] = r["_pivots"]
    if not verbose:
        out.pop("forecast_raw", None)
    return out


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="A股主要指数 趋势与量价推演 + 历史校准闭环")
    parser.add_argument("--indices", type=str, default="sh,sz,cy,kc",
                        help="逗号分隔。sh=上证 sz=深成 cy=创业板 kc=科创50（默认全部）")
    parser.add_argument("--horizon", type=int, default=7, help="预测跨度(交易日, 默认7)")
    parser.add_argument("--days", type=int, default=120, help="分析窗口交易日(默认120)")
    parser.add_argument("--swing-threshold", type=float, default=3.0, help="zigzag 幅度过滤%%(默认3.0)")
    parser.add_argument("--channel-lookback", type=int, default=40, help="上下沿通道回溯交易日(默认40)")
    parser.add_argument("--channel-k", type=float, default=2.0, help="回归通道带宽=k*残差σ(默认2.0)")
    parser.add_argument("--channel-r2", type=float, default=0.5,
                        help="r²≥此值用回归通道, 否则水平箱体(默认0.5)")
    parser.add_argument("--no-calibration", action="store_true", help="关闭历史校准")
    parser.add_argument("--review", action="store_true", help="只评估历史台账、出命中率/校准报告")
    parser.add_argument("--review-days", type=int, default=0, help="review 只看最近 N 条(0=全部)")
    parser.add_argument("--backfill-only", action="store_true", help="只回填旧预测真实走势, 不做新预测")
    parser.add_argument("--no-save", action="store_true", help="不写台账/不回填")
    parser.add_argument("--no-email", action="store_true", help="不发邮件")
    parser.add_argument("--verbose", action="store_true", help="附摆动枢轴/原始预测")
    parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 输出")
    args = parser.parse_args()

    indices = [k.strip() for k in args.indices.split(",") if k.strip()]
    for idx in indices:
        if idx not in INDEX_CONFIG:
            print(f"❌ 未知指数代码: {idx}，可选: {list(INDEX_CONFIG.keys())}")
            sys.exit(1)

    # --- review 模式：只出评估报告 ---
    if args.review:
        print(_ledger.format_review(index_keys=indices))
        return

    # --- backfill-only：只回填 ---
    if args.backfill_only:
        dfs = {}
        for idx in indices:
            df = _fetch_df(idx, max(args.days, args.horizon + 5))
            if df is not None:
                dfs[idx] = df
        n = _ledger.backfill(dfs)
        print(f"✅ 已回填 {n} 项历史预测的真实走势")
        return

    # --- 正常预测 ---
    ledger_records = None if args.no_save and args.no_calibration else _ledger.load_all()
    results: List[Dict[str, Any]] = []
    for idx in indices:
        print(f"正在分析 {INDEX_CONFIG[idx]['name']} ...", file=sys.stderr)
        try:
            r = analyze_index(idx, horizon=args.horizon, days=args.days,
                              swing_threshold=args.swing_threshold,
                              calibrate=not args.no_calibration,
                              channel_lookback=args.channel_lookback,
                              channel_k=args.channel_k, channel_r2=args.channel_r2,
                              ledger_records=ledger_records)
        except Exception as e:
            r = {"error": str(e), "index_key": idx, "index_name": INDEX_CONFIG[idx]["name"]}
        results.append(r)

    # 写台账 + 回填（默认开）
    if not args.no_save:
        try:
            new_recs = [rec for rec in (_ledger.build_record(r) for r in results) if rec]
            if new_recs:
                _ledger.upsert(new_recs)
            # 回填历史（用本次已取的最新数据）
            dfs = {}
            for idx in indices:
                df = _fetch_df(idx, max(args.days, args.horizon + 5))
                if df is not None:
                    dfs[idx] = df
            _ledger.backfill(dfs)
        except Exception as e:
            print(f"[ledger] 台账写入/回填失败: {e}", file=sys.stderr)

    if args.json_output:
        print(json.dumps([_strip_for_json(r, args.verbose) for r in results],
                         ensure_ascii=False, indent=2))
        return

    # 文本输出（捕获到 buffer 以便邮件正文 = 终端输出）
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for r in results:
            print(format_result(r, verbose=args.verbose))
            print()
        if len(results) > 1:
            print(format_summary(results))
        # 附最近命中率摘要
        if not args.no_save:
            try:
                recs = _ledger.load_all()
                if any(r.get("outcome_horizon") or r.get("outcome_t1") for r in recs):
                    print(_ledger.format_review(index_keys=indices))
            except Exception:
                pass
    text = buf.getvalue()
    sys.stdout.write(text)
    sys.stdout.flush()

    # 邮件
    if not args.no_email:
        try:
            _notifier.send_analysis_email(text, results)
        except Exception as e:
            print(f"[notifier] 邮件发送异常: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
