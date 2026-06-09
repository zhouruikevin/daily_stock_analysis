#!/usr/bin/env python3
"""
A股主要指数分析工具：顶背离 + 上下沿（关键位）+ 联动反转置信

支持指数:
  - 上证指数 (000001) - 主板
  - 深证成指 (399001) - 主板
  - 创业板指 (399006) - 创业板
  - 科创50  (000688) - 科创板

用法:
  python index_analysis.py                                # 默认: 三大指数 + 全部分析
  python index_analysis.py --indices sh                   # 仅上证
  python index_analysis.py --indices sh,sz,cy,kc          # 加上科创50
  python index_analysis.py --mode levels                  # 仅上下沿（关键位）
  python index_analysis.py --mode divergence              # 仅顶背离
  python index_analysis.py --mode both                    # 联动评估（默认）
  python index_analysis.py --json                         # JSON 输出

指标说明:
  - MACD顶背离: 价格创新高但DIF未创新高 → 中期上涨动能衰竭
  - RSI顶背离:  价格创新高但RSI未创新高 → 短期涨跌力度衰减
  - 量价背离:   价格创新高但成交量缩减   → 市场参与度下降
  - 上下沿:     MA/EMA/BOLL/极值/整数关口/Fib 综合候选 + 强中弱分级 + 距离裁剪
  - 反转置信:   顶背离 + 撞上沿 联动 → 高/中/无 三档
"""

import argparse
import contextlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# 把 project root 加进 sys.path 以便 import data_provider / 同目录 key_levels
# skill 脚本可以独立分发，但在仓库内跑时优先享受完整数据源能力（Tushare 优先 + 当日拼接 + fallback）
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from data_provider import DataFetcherManager  # noqa: E402
from key_levels import compute_key_levels  # noqa: E402
import history as _history  # noqa: E402
import notifier as _notifier  # noqa: E402


_MANAGER: Optional["DataFetcherManager"] = None


def _get_manager() -> "DataFetcherManager":
    """懒初始化 manager。CLI 一次性进程下省了 Tushare 重复 ~2s 初始化。"""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = DataFetcherManager()
    return _MANAGER


# ============================================================
# 指数配置
# ============================================================
INDEX_CONFIG = {
    "sh": {
        "name": "上证指数",
        "code": "000001",
        "akshare_symbol": "sh000001",
        "market": "主板",
    },
    "sz": {
        "name": "深证成指",
        "code": "399001",
        "akshare_symbol": "sz399001",
        "market": "主板",
    },
    "cy": {
        "name": "创业板指",
        "code": "399006",
        "akshare_symbol": "sz399006",
        "market": "创业板",
    },
    "kc": {
        "name": "科创50",
        "code": "000688",
        "akshare_symbol": "sh000688",
        "market": "科创板",
    },
}

DEFAULT_INDICES = ["sh", "sz", "cy", "kc"]


# ============================================================
# 技术指标计算
# ============================================================
def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple:
    ema_fast = calc_ema(df["close"], fast)
    ema_slow = calc_ema(df["close"], slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    macd_hist = 2 * (dif - dea)
    return dif, dea, macd_hist


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period, min_periods=1).mean()
    avg_loss = loss.rolling(window=period, min_periods=1).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


# ============================================================
# 峰值检测
# ============================================================
def find_peaks(df: pd.DataFrame, col: str, window: int = 3, min_gap: int = 5) -> list:
    """寻找序列的局部峰值点"""
    peaks = []
    for i in range(window, len(df) - window):
        is_peak = True
        for j in range(1, window + 1):
            if df[col].iloc[i] < df[col].iloc[i - j] or df[col].iloc[i] < df[col].iloc[i + j]:
                is_peak = False
                break
        if is_peak:
            peaks.append({"idx": i, "val": df[col].iloc[i]})

    # 合并相近峰值，保留最高的
    filtered = []
    for p in peaks:
        if not filtered or p["idx"] - filtered[-1]["idx"] > min_gap:
            filtered.append(p)
        elif p["val"] > filtered[-1]["val"]:
            filtered[-1] = p
    return filtered


# ============================================================
# 顶背离分析核心
# ============================================================
def analyze_divergence(
    index_key: str,
    trading_days: int = 44,
    extra_days: int = 40,
) -> dict:
    """
    对指定指数进行顶背离分析。

    Args:
        index_key: 指数短码 (sh/sz/cy/kc)
        trading_days: 分析的交易天数 (默认44 ≈ 2个月)
        extra_days: 额外取的天数用于计算MA60等长周期指标

    Returns:
        dict: 分析结果
    """
    cfg = INDEX_CONFIG[index_key]
    symbol = cfg["akshare_symbol"]

    # 1. 获取数据：走 manager，Tushare 优先 + akshare fallback + 当日盘后实时拼接
    df = _get_manager().get_index_daily(symbol, include_today=True)
    if df is None or df.empty:
        return {"error": f"无法获取 {cfg['name']} 数据", "index_key": index_key}

    latest_date = str(df["date"].iloc[-1])[:10]
    total_days = trading_days + extra_days
    df = df.tail(total_days).copy().reset_index(drop=True)

    # 2. 计算指标
    df["dif"], df["dea"], df["macd_hist"] = calc_macd(df)
    df["rsi"] = calc_rsi(df)
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    # 截取分析窗口
    recent = df.tail(trading_days).copy().reset_index(drop=True)

    # 3. 检测阶段性价格高点
    price_peaks = find_peaks(recent, "high", window=3, min_gap=5)

    price_peak_details = []
    for p in price_peaks:
        row = recent.iloc[p["idx"]]
        price_peak_details.append({
            "date": str(row["date"])[:10],
            "high": round(float(row["high"]), 2),
            "close": round(float(row["close"]), 2),
            "dif": round(float(row["dif"]), 2),
            "dea": round(float(row["dea"]), 2),
            "macd_hist": round(float(row["macd_hist"]), 2),
            "rsi": round(float(row["rsi"]), 1),
            "volume": int(row["volume"]),
        })

    # 4. 检测DIF峰值和RSI峰值
    dif_peaks = find_peaks(recent, "dif", window=2, min_gap=5)
    rsi_peaks = find_peaks(recent, "rsi", window=2, min_gap=5)

    dif_peak_details = []
    for p in dif_peaks:
        row = recent.iloc[p["idx"]]
        dif_peak_details.append({
            "date": str(row["date"])[:10],
            "dif": round(float(row["dif"]), 2),
            "close": round(float(row["close"]), 2),
        })

    rsi_peak_details = []
    for p in rsi_peaks:
        row = recent.iloc[p["idx"]]
        rsi_peak_details.append({
            "date": str(row["date"])[:10],
            "rsi": round(float(row["rsi"]), 1),
            "close": round(float(row["close"]), 2),
        })

    # 5. 顶背离判断
    macd_divergence = False
    rsi_divergence = False
    vol_divergence = False
    divergence_details = []

    # 5a. 价格高点两两对比
    if len(price_peak_details) >= 2:
        for i in range(len(price_peak_details) - 1):
            p1 = price_peak_details[i]
            p2 = price_peak_details[i + 1]
            price_higher = p2["high"] > p1["high"]
            dif_lower = p2["dif"] < p1["dif"]
            rsi_lower = p2["rsi"] < p1["rsi"]
            vol_lower = p2["volume"] < p1["volume"]

            if price_higher:
                detail = {
                    "earlier_peak": p1["date"],
                    "later_peak": p2["date"],
                    "price_change": "higher",
                    "macd_div": dif_lower,
                    "rsi_div": rsi_lower,
                    "vol_div": vol_lower,
                    "earner_price": p1["high"],
                    "later_price": p2["high"],
                    "earner_dif": p1["dif"],
                    "later_dif": p2["dif"],
                    "earner_rsi": p1["rsi"],
                    "later_rsi": p2["rsi"],
                }
                divergence_details.append(detail)
                if dif_lower:
                    macd_divergence = True
                if rsi_lower:
                    rsi_divergence = True
                if vol_lower:
                    vol_divergence = True

    # 5b. DIF峰值对比 (更精确的MACD背离判断)
    if len(dif_peak_details) >= 2:
        d1, d2 = dif_peak_details[-2], dif_peak_details[-1]
        if d2["close"] > d1["close"] and d2["dif"] < d1["dif"]:
            macd_divergence = True
            divergence_details.append({
                "method": "dif_peak_comparison",
                "earlier_peak": d1["date"],
                "later_peak": d2["date"],
                "macd_div": True,
                "earner_dif": d1["dif"],
                "later_dif": d2["dif"],
                "earner_price": d1["close"],
                "later_price": d2["close"],
            })

    # 5c. RSI峰值对比 (更精确的RSI背离判断)
    if len(rsi_peak_details) >= 2:
        r1, r2 = rsi_peak_details[-2], rsi_peak_details[-1]
        if r2["close"] > r1["close"] and r2["rsi"] < r1["rsi"]:
            rsi_divergence = True
            divergence_details.append({
                "method": "rsi_peak_comparison",
                "earlier_peak": r1["date"],
                "later_peak": r2["date"],
                "rsi_div": True,
                "earner_rsi": r1["rsi"],
                "later_rsi": r2["rsi"],
                "earner_price": r1["close"],
                "later_price": r2["close"],
            })

    # 6. 当前状态
    last = recent.iloc[-1]
    last_date = str(last["date"])[:10]
    current_state = {
        "date": last_date,
        "close": round(float(last["close"]), 2),
        "ma5": round(float(last["ma5"]), 2) if not np.isnan(last["ma5"]) else None,
        "ma10": round(float(last["ma10"]), 2) if not np.isnan(last["ma10"]) else None,
        "ma20": round(float(last["ma20"]), 2) if not np.isnan(last["ma20"]) else None,
        "ma60": round(float(last["ma60"]), 2) if not np.isnan(last["ma60"]) else None,
        "above_ma5": bool(last["close"] > last["ma5"]) if not np.isnan(last["ma5"]) else None,
        "above_ma20": bool(last["close"] > last["ma20"]) if not np.isnan(last["ma20"]) else None,
        "above_ma60": bool(last["close"] > last["ma60"]) if not np.isnan(last["ma60"]) else None,
        "dif": round(float(last["dif"]), 2),
        "dea": round(float(last["dea"]), 2),
        "macd_hist": round(float(last["macd_hist"]), 2),
        "macd_cross": "金叉" if last["dif"] > last["dea"] else "死叉",
        "rsi": round(float(last["rsi"]), 1),
        "rsi_zone": "超买" if last["rsi"] > 70 else ("超卖" if last["rsi"] < 30 else "正常"),
        "vol_ratio": round(float(last["volume"] / last["vol_ma5"]), 2)
        if not np.isnan(last["vol_ma5"]) and last["vol_ma5"] > 0
        else None,
    }

    # 7. 综合评估
    div_count = sum([macd_divergence, rsi_divergence, vol_divergence])
    if div_count >= 2:
        severity = "强"
        signal = "高度警惕，多重背离共振"
    elif div_count == 1:
        if macd_divergence:
            severity = "中"
            signal = "预警，MACD背离已确认"
        elif rsi_divergence:
            severity = "弱"
            signal = "早期预警，RSI背离需MACD确认"
        else:
            severity = "弱"
            signal = "量价背离需其他指标确认"
    else:
        severity = "无"
        signal = "暂无顶背离信号"

    # 8. 日线数据
    daily_data = []
    for _, row in recent.iterrows():
        vol_ratio = (
            round(float(row["volume"] / row["vol_ma5"]), 2)
            if not np.isnan(row["vol_ma5"]) and row["vol_ma5"] > 0
            else None
        )
        daily_data.append({
            "date": str(row["date"])[:10],
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "dif": round(float(row["dif"]), 2),
            "dea": round(float(row["dea"]), 2),
            "macd_hist": round(float(row["macd_hist"]), 2),
            "rsi": round(float(row["rsi"]), 1),
            "volume": int(row["volume"]),
            "vol_ratio": vol_ratio,
            "macd_cross": "金叉" if row["dif"] > row["dea"] else "死叉",
        })

    return {
        "index_key": index_key,
        "index_name": cfg["name"],
        "index_code": cfg["code"],
        "market": cfg["market"],
        "latest_date": latest_date,
        "data_range": f"{recent['date'].iloc[0]} ~ {recent['date'].iloc[-1]}",
        "trading_days": len(recent),
        "macd_divergence": macd_divergence,
        "rsi_divergence": rsi_divergence,
        "vol_divergence": vol_divergence,
        "divergence_severity": severity,
        "divergence_signal": signal,
        "divergence_details": divergence_details,
        "price_peaks": price_peak_details,
        "dif_peaks": dif_peak_details,
        "rsi_peaks": rsi_peak_details,
        "current_state": current_state,
        "divergence_score": compute_divergence_score(
            macd_divergence, rsi_divergence, vol_divergence, severity
        ),
        "daily_data": daily_data,
    }


# ============================================================
# 上下沿（关键位汇总）+ 反转置信
# ============================================================
def analyze_levels(
    index_key: str,
    history_days: int = 260,
    band_window_pct: float = 3.0,
    band_limit: int = 5,
) -> dict:
    """计算指定指数的上下沿（阻力 / 支撑）。

    Args:
        index_key: 指数短码 (sh/sz/cy/kc)
        history_days: 取多少日历史用于算 MA250（默认 260 ≈ 1 年）
        band_window_pct: 上下沿各只保留距当前价 ±band_window_pct% 内的位
        band_limit: 上沿 / 下沿各最多多少条
    """
    cfg = INDEX_CONFIG[index_key]
    df = _get_manager().get_index_daily(cfg["akshare_symbol"], include_today=True)
    if df is None or df.empty:
        return {"error": f"无法获取 {cfg['name']} 数据", "index_key": index_key}
    df = df.tail(history_days).copy().reset_index(drop=True)
    current_price = float(df["close"].iloc[-1])
    levels = compute_key_levels(
        df, current_price,
        band_window_pct=band_window_pct,
        band_limit=band_limit,
    )
    return {
        "index_key": index_key,
        "index_name": cfg["name"],
        "index_code": cfg["code"],
        "market": cfg["market"],
        "as_of": str(df["date"].iloc[-1])[:10],
        **levels,
    }


def assess_reversal(div: dict, lev: dict, near_pct: float = 0.5) -> dict:
    """顶背离 + 上下沿 联动评估：高/中/无 三档反转置信。

    判定规则：
    - 高置信：MACD 或 RSI 顶背离 且 价格距上沿 ≤ near_pct%
    - 中置信：仅顶背离 / 仅撞上沿 之一
    - 无：     都没有
    量价背离单独太弱，不参与判定。
    """
    has_div = bool(div.get("macd_divergence") or div.get("rsi_divergence"))
    immediate_r = lev.get("immediate_resistance")
    current = lev.get("current_price")
    distance_pct: Optional[float] = None
    near_resistance = False
    if immediate_r is not None and current:
        distance_pct = (immediate_r - current) / current * 100
        near_resistance = distance_pct <= near_pct

    if has_div and near_resistance:
        confidence = "高置信"
        reason = f"顶背离+价格距上沿 {distance_pct:.2f}%"
    elif has_div:
        if distance_pct is not None:
            reason = f"仅顶背离，距上沿 {distance_pct:.2f}%"
        else:
            reason = "仅顶背离，无可用上沿"
        confidence = "中置信"
    elif near_resistance:
        confidence = "中置信"
        reason = f"撞上沿 {distance_pct:.2f}%，无背离"
    else:
        confidence = "无"
        reason = "无顶背离信号"
    final_score = compute_divergence_score(
        bool(div.get("macd_divergence")),
        bool(div.get("rsi_divergence")),
        bool(div.get("vol_divergence")),
        div.get("divergence_severity", "无"),
        reversal_confidence=confidence,
    )
    return {
        "confidence": confidence,
        "reason": reason,
        "distance_to_resistance_pct": (round(distance_pct, 2)
                                       if distance_pct is not None else None),
        "divergence_score": final_score,
    }


# ============================================================
# 顶背离评分
# ============================================================
_DIVERGENCE_WEIGHTS = {
    "macd": 40,       # 中期动能衰竭，最可靠
    "rsi": 30,        # 短期力度衰减，先行指标
    "vol": 15,        # 参与度下降，弱信号
    "resonance": 15,  # 多指标共振加成 (severity=强)
}
# 权重和=100，score 自然是 0-100，无需归一化

_SCORE_LEVELS = [
    (70, "高风险"),
    (45, "中风险"),
    (15, "低风险"),
    (0, "无信号"),
]


def compute_divergence_score(
    macd_div: bool,
    rsi_div: bool,
    vol_div: bool,
    severity: str,
    reversal_confidence: str = "",
) -> int:
    """计算顶背离评分 (0-100)。

    原始分 = Σ(命中指标权重) + 共振加成
    最终分 = 原始分 ± 反转置信微调 (cap 100, floor 0)

    Args:
        macd_div: MACD 顶背离是否成立
        rsi_div: RSI 顶背离是否成立
        vol_div: 量价背离是否成立
        severity: 背离信号强度 (强/中/弱/无)
        reversal_confidence: 反转置信 (高置信/中置信/无)，空字符串跳过微调

    Returns:
        0-100 整数评分
    """
    score = 0
    if macd_div:
        score += _DIVERGENCE_WEIGHTS["macd"]
    if rsi_div:
        score += _DIVERGENCE_WEIGHTS["rsi"]
    if vol_div:
        score += _DIVERGENCE_WEIGHTS["vol"]
    if severity == "强":
        score += _DIVERGENCE_WEIGHTS["resonance"]
    # 反转置信微调
    if reversal_confidence == "高置信":
        score = min(100, score + 5)
    elif reversal_confidence == "无":
        score = max(0, score - 5)
    return score


def score_to_level(score: int) -> str:
    """评分 → 风险等级映射。"""
    for threshold, label in _SCORE_LEVELS:
        if score >= threshold:
            return label
    return "无信号"


# ============================================================
# 格式化输出
# ============================================================
def format_result(result: dict, verbose: bool = False) -> str:
    """将分析结果格式化为可读文本"""
    if "error" in result:
        return f"❌ {result['error']}"

    lines = []
    lines.append(f"{'='*70}")
    lines.append(f"  {result['index_name']} ({result['index_code']}) — {result['market']}")
    lines.append(f"  顶背离分析 | 数据: {result['data_range']} | {result['trading_days']}个交易日")
    lines.append(f"{'='*70}")

    # 背离结果
    lines.append(f"\n--- 顶背离判断 ---")
    macd_icon = "⚠️ 存在" if result["macd_divergence"] else "❌ 不存在"
    rsi_icon = "⚠️ 存在" if result["rsi_divergence"] else "❌ 不存在"
    vol_icon = "⚠️ 存在" if result["vol_divergence"] else "❌ 不存在"
    lines.append(f"  MACD顶背离: {macd_icon}")
    lines.append(f"  RSI顶背离:  {rsi_icon}")
    lines.append(f"  量价背离:   {vol_icon}")
    lines.append(f"  信号强度:   {result['divergence_severity']} — {result['divergence_signal']}")

    # 背离细节
    if result["divergence_details"]:
        lines.append(f"\n--- 背离细节 ---")
        for d in result["divergence_details"]:
            method = d.get("method", "价格高点对比")
            if method == "dif_peak_comparison":
                lines.append(f"  DIF峰值对比: {d['earlier_peak']} → {d['later_peak']}")
                lines.append(f"    价格: {d.get('earner_price', '?')} → {d.get('later_price', '?')}  DIF: {d.get('earner_dif', '?')} → {d.get('later_dif', '?')}")
            elif method == "rsi_peak_comparison":
                lines.append(f"  RSI峰值对比: {d['earlier_peak']} → {d['later_peak']}")
                lines.append(f"    价格: {d.get('earner_price', '?')} → {d.get('later_price', '?')}  RSI: {d.get('earner_rsi', '?')} → {d.get('later_rsi', '?')}")
            else:
                lines.append(f"  价格高点对比: {d['earlier_peak']} → {d['later_peak']}")
                lines.append(f"    价格: {d.get('earner_price', '?')} → {d.get('later_price', '?')} (创新高)")
                if "macd_div" in d:
                    lines.append(f"    DIF: {d.get('earner_dif', '?')} → {d.get('later_dif', '?')} ({'↓顶背离!' if d['macd_div'] else '↑同步'})")
                if "rsi_div" in d:
                    lines.append(f"    RSI: {d.get('earner_rsi', '?')} → {d.get('later_rsi', '?')} ({'↓顶背离!' if d['rsi_div'] else '↑同步'})")
                if "vol_div" in d:
                    lines.append(f"    成交量: {'↓缩量背离!' if d['vol_div'] else '↑放量'})")

    # 阶段高点
    if result["price_peaks"]:
        lines.append(f"\n--- 阶段性价格高点 ---")
        for p in result["price_peaks"]:
            lines.append(f"  {p['date']}  最高:{p['high']:>9.2f}  DIF:{p['dif']:>8.2f}  RSI:{p['rsi']:>5.1f}")

    # DIF/RSI峰值
    if result["dif_peaks"]:
        lines.append(f"\n--- DIF峰值 ---")
        for p in result["dif_peaks"]:
            lines.append(f"  {p['date']}  DIF:{p['dif']:>8.2f}  收盘:{p['close']:>9.2f}")

    if result["rsi_peaks"]:
        lines.append(f"\n--- RSI峰值 ---")
        for p in result["rsi_peaks"]:
            lines.append(f"  {p['date']}  RSI:{p['rsi']:>5.1f}  收盘:{p['close']:>9.2f}")

    # 当前状态
    cs = result["current_state"]
    lines.append(f"\n--- 当前状态 ({cs['date']}) ---")
    lines.append(f"  收盘: {cs['close']}")
    if cs["ma5"]: lines.append(f"  MA5={cs['ma5']}  MA10={cs['ma10']}  MA20={cs['ma20']}  MA60={cs['ma60']}")
    lines.append(f"  价格位置: MA5{'上' if cs['above_ma5'] else '下'}  MA20{'上' if cs['above_ma20'] else '下'}  MA60{'上' if cs['above_ma60'] else '下'}")
    lines.append(f"  MACD: DIF={cs['dif']}  DEA={cs['dea']}  柱={cs['macd_hist']}  {cs['macd_cross']}")
    lines.append(f"  RSI(14): {cs['rsi']} ({cs['rsi_zone']})")
    if cs["vol_ratio"]:
        lines.append(f"  量比: {cs['vol_ratio']}")

    # 日线数据（verbose模式）
    if verbose and result["daily_data"]:
        lines.append(f"\n--- 日线数据 ---")
        for d in result["daily_data"]:
            lines.append(
                f"  {d['date']}  开:{d['open']:>9.2f}  高:{d['high']:>9.2f}  "
                f"低:{d['low']:>9.2f}  收:{d['close']:>9.2f}  "
                f"DIF:{d['dif']:>8.2f}  DEA:{d['dea']:>8.2f}  "
                f"柱:{d['macd_hist']:>8.2f}  RSI:{d['rsi']:>5.1f}  "
                f"量比:{d['vol_ratio'] or 'N/A'}  {d['macd_cross']}"
            )

    return "\n".join(lines)


def format_summary(results: list) -> str:
    """汇总所有指数的背离结果（兼容旧契约：results 元素是 divergence dict）"""
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  A股主要指数顶背离汇总")
    lines.append(f"  数据截止: {results[0]['latest_date'] if results else 'N/A'}")
    lines.append(f"{'='*70}")
    lines.append("")
    lines.append(f"  {'指数':<12} {'代码':<8} {'MACD背离':<10} {'RSI背离':<10} {'量价背离':<10} {'信号强度':<6} {'说明'}")
    lines.append(f"  {'-'*70}")

    for r in results:
        if "error" in r:
            lines.append(f"  {r.get('index_key', '?'):<12} {'ERROR':<8} {r['error']}")
            continue
        macd = "⚠️ 存在" if r["macd_divergence"] else "❌ 无"
        rsi = "⚠️ 存在" if r["rsi_divergence"] else "❌ 无"
        vol = "⚠️ 存在" if r["vol_divergence"] else "❌ 无"
        lines.append(
            f"  {r['index_name']:<12} {r['index_code']:<8} {macd:<10} {rsi:<10} {vol:<10} "
            f"{r['divergence_severity']:<6} {r['divergence_signal']}"
        )

    lines.append("")
    lines.append("  说明: MACD背离=中期动能衰竭 | RSI背离=短期力度衰减 | 量价背离=参与度下降")
    lines.append("  信号强度: 强=多重背离共振 | 中=MACD背离确认 | 弱=RSI早期预警 | 无=暂无信号")
    return "\n".join(lines)


_STRENGTH_BADGE = {"强": "●●●", "中": "●●○", "弱": "●○○"}


def format_levels(result: dict) -> str:
    """格式化上下沿（关键位汇总）结果"""
    if "error" in result:
        return f"❌ {result['error']}"

    lines = []
    lines.append(f"{'='*70}")
    lines.append(f"  {result['index_name']} ({result['index_code']}) — {result['market']}")
    lines.append(f"  上下沿（关键位汇总） | 截止: {result['as_of']} | 当前价: {result['current_price']}")
    lines.append(f"{'='*70}")

    res = result.get("resistance_levels", [])
    sup = result.get("support_levels", [])

    lines.append("\n--- 上沿（阻力）---")
    if not res:
        lines.append("  （3% 窗口内无显著阻力位）")
    else:
        for lvl in res:
            badge = _STRENGTH_BADGE.get(lvl["strength"], "   ")
            lines.append(f"  {badge} {lvl['strength']}  {lvl['value']:>10.2f}  "
                         f"{lvl['label']:<30}  +{lvl['distance_pct']:.2f}%")

    lines.append("\n--- 下沿（支撑）---")
    if not sup:
        lines.append("  （3% 窗口内无显著支撑位）")
    else:
        for lvl in sup:
            badge = _STRENGTH_BADGE.get(lvl["strength"], "   ")
            lines.append(f"  {badge} {lvl['strength']}  {lvl['value']:>10.2f}  "
                         f"{lvl['label']:<30}  {lvl['distance_pct']:.2f}%")

    lines.append(f"\n  候选总数(裁剪前): {result.get('all_candidates_count', 0)}")
    return "\n".join(lines)


def format_reversal(rev: dict, index_name: str) -> str:
    """格式化反转置信单条"""
    badge = {"高置信": "⚠️⚠️", "中置信": "⚠️", "无": "·"}.get(rev["confidence"], "")
    return f"  {index_name:<10} {badge} {rev['confidence']:<7} {rev['reason']}"


def format_combined_summary(wrapped_results: list) -> str:
    """mode=both 时的总览：每个指数一行『背离信号 | 距上沿 | 反转置信』。

    wrapped_results: List[{index_key, divergence, levels, reversal}]
    """
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  A股主要指数 顶背离 × 上下沿 联动总览")
    lines.append(f"{'='*70}")
    lines.append("")
    def _topn(levels: list, n: int = 3) -> str:
        """取上/下沿前 N 条的 value，斜杠分隔。避免被「立即阻力」单值误导而漏看共振位。"""
        if not levels:
            return "-"
        vals = [f"{lv['value']:g}" for lv in levels[:n]]
        return " / ".join(vals)

    lines.append(f"  {'指数':<8} {'评分':<12} {'背离':<6} {'当前价':<10} "
                 f"{'上沿 top3':<32} {'距阻力':<7} "
                 f"{'下沿 top3':<32} {'反转置信':<8}")
    lines.append(f"  {'-'*120}")
    for w in wrapped_results:
        div = w.get("divergence") or {}
        lev = w.get("levels") or {}
        rev = w.get("reversal") or {}
        if div.get("error") or lev.get("error"):
            err = div.get("error") or lev.get("error")
            lines.append(f"  {w.get('index_key', '?'):<8} ERROR  {err}")
            continue
        sev = div.get("divergence_severity", "?")
        score = rev.get("divergence_score", div.get("divergence_score"))
        level = score_to_level(score) if score is not None else "?"
        score_str = f"{score}分({level})" if score is not None else "-"
        dist = rev.get("distance_to_resistance_pct")
        dist_str = f"{dist:.2f}%" if dist is not None else "-"
        lines.append(
            f"  {div.get('index_name', w.get('index_key', '?')):<8} "
            f"{score_str:<12} "
            f"{sev:<6} "
            f"{lev.get('current_price', '?'):<10} "
            f"{_topn(lev.get('resistance_levels', []), 3):<32} "
            f"{dist_str:<7} "
            f"{_topn(lev.get('support_levels', []), 3):<32} "
            f"{rev.get('confidence', '?'):<8}"
        )
    lines.append("")
    lines.append("  上沿/下沿 top3: 距当前价从近到远的前 3 条；完整列表（含强度、label）见上方各指数详情区")
    lines.append("  反转置信: 高置信=顶背离+撞上沿(<0.5%) | 中置信=仅背离 或 仅撞上沿 | 无=暂无信号")
    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================
def _strip_daily_data(r: dict) -> dict:
    """JSON 输出时去掉 daily_data 以减少体积（顶层 + 嵌套 divergence 两处）"""
    if not isinstance(r, dict):
        return r
    out = {k: v for k, v in r.items() if k != "daily_data"}
    if isinstance(out.get("divergence"), dict):
        out["divergence"] = {k: v for k, v in out["divergence"].items() if k != "daily_data"}
    return out


def main():
    parser = argparse.ArgumentParser(description="A股主要指数 顶背离 + 上下沿 + 联动评估")
    parser.add_argument(
        "--indices",
        type=str,
        default="sh,sz,cy,kc",
        help="要分析的指数，逗号分隔。sh=上证指数, sz=深证成指, cy=创业板指, kc=科创50（默认全部 4 个；不想看某个就显式列出剩下的，如 --indices sh,sz）",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["divergence", "levels", "both"],
        default="both",
        help="分析模式：divergence=仅顶背离 / levels=仅上下沿 / both=联动评估（默认）",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=44,
        help="顶背离窗口的交易日天数 (默认44 ≈ 2个月)",
    )
    parser.add_argument(
        "--band-window",
        type=float,
        default=3.0,
        help="上下沿距当前价 ±N%% 内才保留 (默认 3.0)",
    )
    parser.add_argument(
        "--band-limit",
        type=int,
        default=5,
        help="上沿 / 下沿各最多多少条 (默认 5)",
    )
    parser.add_argument(
        "--near-pct",
        type=float,
        default=0.5,
        help="反转置信判定阈值：价格距上沿 ≤N%% 视为撞上沿 (默认 0.5)",
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=10,
        help="默认展示近 N 个交易日的关键位变化 (默认 10；仅 --mode both 生效)",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="不展示历史变化表（默认展示）",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="跑分析但不保存当天 snapshot（调参 / 探索时用）",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="不发送邮件（默认：若已配 EMAIL_SENDER/EMAIL_PASSWORD 则自动发；仅 --mode both 非 JSON 时生效）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="顶背离段输出完整日线数据",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="输出JSON格式",
    )
    args = parser.parse_args()

    indices = [k.strip() for k in args.indices.split(",") if k.strip()]
    for idx in indices:
        if idx not in INDEX_CONFIG:
            print(f"❌ 未知指数代码: {idx}，可选: {list(INDEX_CONFIG.keys())}")
            sys.exit(1)

    results: list = []
    for idx in indices:
        cfg = INDEX_CONFIG[idx]
        print(f"正在分析 {cfg['name']} ({cfg['akshare_symbol']}) ...", file=sys.stderr)
        wrapped: dict = {"index_key": idx}
        try:
            if args.mode in ("divergence", "both"):
                wrapped["divergence"] = analyze_divergence(idx, trading_days=args.days)
            if args.mode in ("levels", "both"):
                wrapped["levels"] = analyze_levels(
                    idx,
                    band_window_pct=args.band_window,
                    band_limit=args.band_limit,
                )
            if args.mode == "both":
                wrapped["reversal"] = assess_reversal(
                    wrapped["divergence"], wrapped["levels"],
                    near_pct=args.near_pct,
                )
        except Exception as e:
            wrapped["error"] = str(e)
        # divergence-only / levels-only 模式保持旧契约：直接吐 div / lev dict
        if args.mode == "divergence":
            results.append(wrapped.get("divergence", {"error": wrapped.get("error", "unknown"),
                                                      "index_key": idx}))
        elif args.mode == "levels":
            results.append(wrapped.get("levels", {"error": wrapped.get("error", "unknown"),
                                                   "index_key": idx}))
        else:
            results.append(wrapped)

    # mode=both 时保存当日 snapshot（默认开，--no-save 关）。
    # JSON 输出也保存：持久化跟展示无关。其他 mode 不保存（snapshot 需要 div+lev+rev 三件套）。
    if args.mode == "both" and not args.no_save:
        try:
            snap = _history.build_daily_snapshot(results)
            if snap["indices"]:
                _history.save_daily(snap)
        except Exception as e:
            # 保存失败不影响主流程，只记到 stderr
            print(f"[history] 保存失败：{e}", file=sys.stderr)

    if args.json_output:
        output = [_strip_daily_data(r) if not args.verbose else r for r in results]
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    # 文本输出（捕获到 buffer 以便末尾发邮件；同时仍 print 到真 stdout）
    # Why 捕获：邮件内容要跟终端看到的完全一致，重新生成一份就要维护两套格式化
    _buf = io.StringIO()
    _mail_snapshots = None   # 传给邮件的 history 数据
    _mail_index_keys = None
    with contextlib.redirect_stdout(_buf):
        if args.mode == "divergence":
            for r in results:
                print(format_result(r, verbose=args.verbose))
            if len(results) > 1:
                print(format_summary(results))
        elif args.mode == "levels":
            for r in results:
                print(format_levels(r))
        else:  # both
            for w in results:
                div = w.get("divergence", {})
                lev = w.get("levels", {})
                rev = w.get("reversal", {})
                print(format_result(div, verbose=args.verbose))
                print(format_levels(lev))
                if rev:
                    print(f"\n--- 反转置信 ---\n"
                          f"  {rev.get('confidence', '?')}  —  {rev.get('reason', '')}")
            if len(results) > 1:
                # 旧 divergence 汇总（兼容已有消费方）
                div_list = [w.get("divergence", {}) for w in results]
                print(format_summary(div_list))
                # 新联动总览
                print(format_combined_summary(results))

            # 历史变化表（默认展示，--no-history 关）
            if not args.no_history:
                try:
                    snapshots = _history.load_recent(days=args.history_days)
                    if snapshots:
                        index_keys = [w.get("index_key") for w in results if w.get("index_key")]
                        print(_history.format_history_table(snapshots, index_keys=index_keys))
                        _mail_snapshots = snapshots
                        _mail_index_keys = index_keys
                    else:
                        print("\n  （历史为空，今天是第一次跑；明天再跑就有变化对比了）")
                except Exception as e:
                    print(f"[history] 加载失败：{e}", file=sys.stderr)

    # 真 stdout 输出
    text_output = _buf.getvalue()
    sys.stdout.write(text_output)
    sys.stdout.flush()

    # 邮件推送：仅 mode=both 且非 --no-email 且配置齐全时触发
    # Why 限定 both：snapshot/反转置信只有 both 才齐全；其他 mode 是调试/查询场景
    if args.mode == "both" and not args.no_email:
        try:
            _notifier.send_analysis_email(
                text_output, results,
                snapshots=_mail_snapshots,
                index_keys=_mail_index_keys,
            )
        except Exception as e:
            print(f"[notifier] 邮件发送异常：{e}", file=sys.stderr)


if __name__ == "__main__":
    main()
