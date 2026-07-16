#!/usr/bin/env python3
"""历史回放回测引擎（仅做多，单一仓位）。

在每个历史 bar t，用**截至 t 的数据切片** df.iloc[:t+1] 重算 trend/量价/通道/关键位/信号
（复用现有分析函数，全部只回看、无未来函数），据此在 t+1 及以后模拟买卖，
统计胜率 / 盈亏比 / Profit Factor / 期望R / 最大回撤 / 超额收益。

防未来函数（look-ahead）的两道保证：
1. 信号只用 ≤t 数据（切片）；
2. 成交只发生在信号计算日之后的 bar（挂单在 t 收盘、最早 t+1 撮合）。

保守假设：同一 bar 内 high、low 同时穿越目标与止损时，日线无法判先后 → 统一记止损
（不利假设，避免虚高胜率）。v1 全进全出单一仓位，减仓/加仓（需仓位规模模型）留作 v2：
回测中「减仓」不强制离场，只有「清仓」信号才平仓（次日开盘）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

import trend_state as _trend
import volume_price as _vp
import channel as _channel
import forecast as _forecast
import signals as _signals

_BARS_PER_MONTH = 21
_ENTRY_ACTIONS = (_signals.ACT_SNIPE, _signals.ACT_BUILD)


# ============================================================
# 单 bar 信号（喂切片，防未来函数）
# ============================================================
def signal_at(slice_df: pd.DataFrame, *, horizon: int, channel_lookback: int,
              channel_k: float, channel_r2: float, swing_threshold: float) -> Dict[str, Any]:
    """用截至切片末尾的数据算一条信号。与 analyze_index(calibrate=False) 等价。"""
    trend = _trend.analyze_trend(slice_df, swing_threshold=swing_threshold)
    vp = _vp.analyze_volume_price(slice_df, trend["direction"])
    ch = _channel.compute_channel(slice_df, lookback=channel_lookback,
                                  k=channel_k, trend_r2=channel_r2)
    ch["judgement"] = _channel.judge_breakout(ch, vp)
    fc = _forecast.build_forecast(slice_df, trend, vp, horizon=horizon)
    cur = round(float(slice_df["close"].iloc[-1]), 2)
    result = {
        "current_price": cur,
        "trend": {k: v for k, v in trend.items() if k != "pivots"},
        "volume_price": vp,
        "channel": ch,
        "key_levels": fc.get("key_levels"),
        "forecast": {k: v for k, v in fc.items() if k != "key_levels"},
    }
    return _signals.build_signals(result, slice_df)


# ============================================================
# 撮合 / 出场
# ============================================================
def _try_fill(order: Dict[str, Any], bar) -> Optional[float]:
    """在给定 bar 上尝试撮合进场单，返回成交价或 None。"""
    if order["setup"] == "突破":
        if float(bar.high) >= order["trigger"]:
            return order["trigger"]              # 放量站上阻力 → 按触发价成交
        return None
    # 低吸 / 试探：限价挂在买入区上沿，触及即成交（保守按区上沿）
    ez = order["entry_zone"]
    if ez and float(bar.low) <= ez["high"]:
        return round(min(ez["high"], float(bar.high)), 2)
    return None


def _check_exit(pos: Dict[str, Any], bar, held: int, horizon: int):
    """返回 (reason, price) 或 None。优先级：信号清仓(开盘) > 止损 > 目标2 > 目标1 > timeout。

    同 bar 双触止损与目标 → 保守判 stop。
    """
    if pos.get("signal_exit"):
        return ("signal_exit", float(bar.open))
    lo, hi = float(bar.low), float(bar.high)
    if pos["stop"] is not None and lo <= pos["stop"]:
        return ("stop", pos["stop"])
    if pos["t2"] is not None and hi >= pos["t2"]:
        return ("target2", pos["t2"])
    if pos["t1"] is not None and hi >= pos["t1"]:
        return ("target1", pos["t1"])
    if held >= horizon:
        return ("timeout", float(bar.close))
    return None


# ============================================================
# 回测主循环
# ============================================================
def run_backtest(index_key: str, df_full: pd.DataFrame, *, index_name: Optional[str] = None,
                 horizon: int = 7, channel_lookback: int = 40, channel_k: float = 2.0,
                 channel_r2: float = 0.5, swing_threshold: float = 3.0,
                 months: Optional[int] = 6, warmup: Optional[int] = None) -> Dict[str, Any]:
    warmup = warmup or max(channel_lookback, 60)
    n = 0 if df_full is None else len(df_full)
    if n == 0:
        return _empty_report(index_key, index_name, "无数据")
    start = warmup
    if months:
        start = max(warmup, n - months * _BARS_PER_MONTH)
    if start >= n - 1:
        return _empty_report(index_key, index_name, "数据不足以回放（热身期过长）")

    dates = [str(d)[:10] for d in df_full["date"].tolist()]
    position: Optional[Dict[str, Any]] = None
    pending: Optional[Dict[str, Any]] = None
    trades: List[Dict[str, Any]] = []
    equity = 1.0
    equity_curve: List[List[Any]] = []

    for t in range(start, n):
        bar = df_full.iloc[t]

        # 1. 有挂单且空仓 → 在本 bar 撮合（本 bar 即信号日之后的执行 bar）
        if position is None and pending is not None:
            fill = _try_fill(pending, bar)
            if fill is not None:
                position = {
                    "entry_price": fill, "entry_date": dates[t], "entry_t": t,
                    "stop": pending["stop"], "t1": pending["t1"], "t2": pending["t2"],
                    "setup": pending["setup"], "signal_exit": False,
                }
                pending = None

        # 2. 持仓 → 本 bar 判出场
        if position is not None:
            held = t - position["entry_t"]
            ex = _check_exit(position, bar, held, horizon)
            if ex is not None:
                reason, px = ex
                trades.append(_close_trade(position, reason, px, dates[t]))
                equity *= (1 + trades[-1]["pnl_pct"] / 100.0)
                position = None

        # 3. 本 bar 收盘算信号（只用 ≤t 数据）
        slice_df = df_full.iloc[:t + 1].reset_index(drop=True)
        sig = signal_at(slice_df, horizon=horizon, channel_lookback=channel_lookback,
                        channel_k=channel_k, channel_r2=channel_r2,
                        swing_threshold=swing_threshold)

        # 4. 按信号布置下一 bar 的动作
        if position is None:
            pending = None
            if sig["action"] in _ENTRY_ACTIONS and sig.get("entry_zone") and t + 1 < n:
                pending = {"setup": sig.get("setup_type"), "entry_zone": sig["entry_zone"],
                           "trigger": sig.get("trigger_price"), "stop": sig.get("stop"),
                           "t1": sig.get("target1"), "t2": sig.get("target2")}
        else:
            if sig["action"] == _signals.ACT_CLEAR:
                position["signal_exit"] = True   # 次日开盘平

        equity_curve.append([dates[t], round(equity, 4)])

    # 收尾：回放末仍持仓 → 按最后收盘平（timeout 口径）
    if position is not None:
        last = df_full.iloc[n - 1]
        trades.append(_close_trade(position, "timeout", float(last["close"]), dates[n - 1]))
        equity *= (1 + trades[-1]["pnl_pct"] / 100.0)

    return _summarize(index_key, index_name, trades, equity_curve, df_full, start, n, warmup)


def _close_trade(pos: Dict[str, Any], reason: str, exit_px: float, exit_date: str) -> Dict[str, Any]:
    entry = pos["entry_price"]
    pnl_pct = (exit_px - entry) / entry * 100 if entry else 0.0
    risk = entry - pos["stop"] if pos["stop"] is not None else None
    r_mult = round((exit_px - entry) / risk, 2) if (risk and risk > 0) else None
    return {
        "setup": pos["setup"], "entry_date": pos["entry_date"],
        "entry_price": round(entry, 2), "exit_date": exit_date,
        "exit_reason": reason, "exit_price": round(exit_px, 2),
        "pnl_pct": round(pnl_pct, 2), "r_multiple": r_mult, "win": pnl_pct > 0,
    }


# ============================================================
# 汇总指标
# ============================================================
def _max_drawdown(curve: List[List[Any]]) -> Optional[float]:
    if not curve:
        return None
    peak = curve[0][1]
    mdd = 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            mdd = max(mdd, (peak - eq) / peak)
    return round(mdd * 100, 2)


def _summarize(index_key, index_name, trades, equity_curve, df_full, start, n, warmup) -> Dict[str, Any]:
    nt = len(trades)
    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    sum_win = sum(t["pnl_pct"] for t in wins)
    sum_loss = sum(t["pnl_pct"] for t in losses)   # 负值
    avg_win = round(sum_win / len(wins), 2) if wins else None
    avg_loss = round(sum_loss / len(losses), 2) if losses else None
    payoff = round(avg_win / abs(avg_loss), 2) if (avg_win and avg_loss) else None
    pf = round(sum_win / abs(sum_loss), 2) if sum_loss != 0 else (None if sum_win == 0 else float("inf"))
    r_vals = [t["r_multiple"] for t in trades if t["r_multiple"] is not None]
    avg_r = round(sum(r_vals) / len(r_vals), 2) if r_vals else None

    total_return = round((equity_curve[-1][1] - 1) * 100, 2) if equity_curve else 0.0
    base_close = float(df_full["close"].iloc[start])
    end_close = float(df_full["close"].iloc[n - 1])
    buyhold = round((end_close / base_close - 1) * 100, 2) if base_close else None

    per_setup: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        b = per_setup.setdefault(t["setup"] or "?", {"n": 0, "wins": 0})
        b["n"] += 1
        b["wins"] += 1 if t["win"] else 0
    for b in per_setup.values():
        b["win_rate"] = round(b["wins"] / b["n"] * 100, 1) if b["n"] else None

    return {
        "index_key": index_key, "index_name": index_name or index_key,
        "period": f"{str(df_full['date'].iloc[start])[:10]} ~ {str(df_full['date'].iloc[n-1])[:10]}",
        "bars_replayed": n - start, "warmup": warmup,
        "n_trades": nt,
        "win_rate": round(len(wins) / nt * 100, 1) if nt else None,
        "avg_pnl_pct": round(sum(t["pnl_pct"] for t in trades) / nt, 2) if nt else None,
        "avg_win_pct": avg_win, "avg_loss_pct": avg_loss,
        "payoff_ratio": payoff, "profit_factor": pf, "avg_r": avg_r,
        "max_drawdown_pct": _max_drawdown(equity_curve),
        "total_return_pct": total_return, "buyhold_pct": buyhold,
        "excess_pct": round(total_return - buyhold, 2) if buyhold is not None else None,
        "per_setup": per_setup,
        "trades": trades,
        "equity_curve": equity_curve,
        "error": None,
    }


def _empty_report(index_key, index_name, reason) -> Dict[str, Any]:
    return {"index_key": index_key, "index_name": index_name or index_key,
            "n_trades": 0, "trades": [], "equity_curve": [], "error": reason}


# ============================================================
# 终端渲染
# ============================================================
def format_backtest(rep: Dict[str, Any]) -> str:
    name = rep.get("index_name", rep.get("index_key"))
    if rep.get("error"):
        return f"❌ {name} 回测: {rep['error']}"

    def s(v, suf=""):
        if v is None:
            return "-"
        if v == float("inf"):
            return "∞"
        return f"{v}{suf}"

    lines = []
    lines.append("=" * 72)
    lines.append(f"  {name} 回测  ({rep['period']}, {rep['bars_replayed']}bar, 热身{rep['warmup']})")
    lines.append("=" * 72)
    if rep["n_trades"] == 0:
        lines.append("  回放窗口内未触发任何交易（信号偏保守或行情不符）")
        return "\n".join(lines)
    lines.append(f"  交易 {rep['n_trades']}  胜率 {s(rep['win_rate'],'%')}  "
                 f"盈亏比 {s(rep['payoff_ratio'])}  PF {s(rep['profit_factor'])}  "
                 f"期望R {s(rep['avg_r'])}")
    lines.append(f"  平均收益 {s(rep['avg_pnl_pct'],'%')}  "
                 f"(盈 {s(rep['avg_win_pct'],'%')} / 亏 {s(rep['avg_loss_pct'],'%')})")
    lines.append(f"  总收益 {s(rep['total_return_pct'],'%')}  "
                 f"基准(买入持有) {s(rep['buyhold_pct'],'%')}  "
                 f"超额 {s(rep['excess_pct'],'%')}  最大回撤 {s(rep['max_drawdown_pct'],'%')}")
    if rep.get("per_setup"):
        seg = "  ".join(f"{k} {v['n']}笔 胜率{s(v.get('win_rate'),'%')}"
                        for k, v in rep["per_setup"].items())
        lines.append(f"  分形态: {seg}")
    # 交易明细（最多末 8 笔）
    lines.append("  明细:")
    for t in rep["trades"][-8:]:
        r = f" R{t['r_multiple']:+g}" if t["r_multiple"] is not None else ""
        lines.append(f"    {t['entry_date']} {t['setup'] or '?'}@{t['entry_price']} "
                     f"→{t['exit_reason']}@{t['exit_price']} {t['pnl_pct']:+g}%{r}")
    return "\n".join(lines)


__all__ = ["run_backtest", "format_backtest", "signal_at"]
