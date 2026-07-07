#!/usr/bin/env python3
"""技术指标（自带一份，不跨 skill import）。

只依赖 pandas / numpy，供 trend_state / volume_price / forecast 复用。
均线/MACD/RSI 与仓库 index-analysis 的算法一致（保证同一指数两个 skill 结论可比）。
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_ma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def calc_macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
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
    return 100 - (100 / (1 + rs))


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """真实波幅均值。用于波动带宽度与目标区间的自适应缩放。"""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=1).mean()


def linreg(y: np.ndarray) -> Tuple[float, float, float]:
    """对等间隔序列做一元线性回归。

    Returns: (slope 每 bar 变化, intercept, r2)。样本不足 2 返回 (0,首值,0)。
    """
    y = np.asarray(y, dtype=float)
    y = y[~np.isnan(y)]
    n = len(y)
    if n < 2:
        return 0.0, float(y[-1]) if n else 0.0, 0.0
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    y_hat = slope * x + intercept
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return float(slope), float(intercept), float(max(0.0, min(1.0, r2)))


def slope_pct_per_bar(series: pd.Series, lookback: int) -> Tuple[float, float]:
    """近 lookback 根的归一化斜率（%/bar）+ 拟合 r2。

    归一化基准用窗口均价，避免不同指数点位量级不可比。
    """
    y = series.tail(lookback).to_numpy(dtype=float)
    y = y[~np.isnan(y)]
    if len(y) < 2:
        return 0.0, 0.0
    slope, _, r2 = linreg(y)
    base = float(np.nanmean(y))
    if base <= 1e-9:
        return 0.0, r2
    return slope / base * 100.0, r2


__all__ = [
    "calc_ema", "calc_ma", "calc_macd", "calc_rsi", "calc_atr",
    "linreg", "slope_pct_per_bar",
]
