#!/usr/bin/env python3
"""狙击(买入) / 卖出(离场) 信号 —— 把趋势/量价/通道/关键位翻译成纪律动作 + 价位。

设计信念（沿用技能既有哲学）：
- "市场肯定是对的"，顺势为先验：狙击点偏向"顺势回踩企稳"或"放量突破追击"，
  卖出点偏向"撞阻力量价背离 / 趋势破坏"。
- 仅做多：A股散户只能借道 ETF 做多；下降趋势默认空仓观望，不逆势抄底
  （唯一例外：明确缩量企稳反弹才轻仓试探）。
- 不引入新指标：以 channel.judgement.bias 为主驱动（bias 已把 pos+量价编码进去），
  trend / health / vol 只作阈值门与置信度微调；价位锚来自 key_levels + 通道 + ATR。

信号是"顺势框架下的机械纪律"，不是投资建议；价位与校准无关（来自结构位而非校准后目标）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

# ============================================================
# 常量集中区（类比 scoring.py，复用既有 label 边界避免拍脑袋）
# ============================================================
HEALTH_HEALTHY = 67      # == volume_price "健康" 边界
HEALTH_WEAK = 34         # == volume_price "背离衰竭" 边界
STRENGTH_MID = 34        # == trend strength_label "中" 边界

# 价位缓冲：全部以 ATR 为单位，天然按指数量级自适应
BUY_ZONE_ABOVE_ATR = 0.20    # 低吸买入区上沿 = 支撑 + 0.20·ATR（提前挂单）
BUY_ZONE_BELOW_ATR = 0.30    # 低吸买入区下沿 = 支撑 - 0.30·ATR（容忍插针）
BREAKOUT_CHASE_ATR = 0.50    # 突破追击区宽度 = 上沿 → 上沿 + 0.50·ATR
BREAKOUT_ENTRY_ATR = 0.25    # 突破成交参考 = 上沿 + 0.25·ATR
STOP_ATR = 1.20              # 止损 = 结构位 - 1.20·ATR
REDUCE_BELOW_ATR = 0.20      # 减仓区 = 阻力 - 0.20·ATR → 阻力

# 置信度评分权重（合计上限 100）
CONF_CH = {"强": 35, "中": 20, "弱": 5, "无": 0}   # 来自 channel.judgement.confidence
CONF_TREND_MAX = 25          # 顺势(up)按 strength 线性给分；range 减半；down 归零
CONF_HEALTH_MAX = 20
CONF_SETUP = 20              # primary=continuation 且 bias 决断 → 满分
CONF_STRONG = 67             # 强狙击门槛
CONF_MID = 40

# 动作枚举（仅做多）
ACT_SNIPE = "强狙击"
ACT_BUILD = "建仓"
ACT_HOLD = "持有"
ACT_REDUCE = "减仓"
ACT_CLEAR = "清仓"
ACT_WAIT = "观望"

_ENTRY_ACTIONS = (ACT_SNIPE, ACT_BUILD)   # 进场类（回填/回测只评这两类）


def _r2(v: Optional[float]) -> Optional[float]:
    return round(float(v), 2) if v is not None else None


def _resistance_above(res_levels: List[Dict[str, Any]], price: float) -> Optional[float]:
    """返回严格高于 price 的最近一档阻力值（res_levels 近→远排序）。"""
    for lv in res_levels:
        if lv.get("value") is not None and lv["value"] > price:
            return float(lv["value"])
    return None


def build_signals(result: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
    """从 result 的 trend/channel/volume_price/key_levels/forecast.atr 推导做多动作 + 价位。

    通道不可用 / 数据异常时优雅降级为 观望（价位全 None）。
    """
    trend = result.get("trend") or {}
    vp = result.get("volume_price") or {}
    ch = result.get("channel") or {}
    kl = result.get("key_levels") or {}
    fc = result.get("forecast") or {}
    cur = result.get("current_price")

    direction = trend.get("direction")
    strength = trend.get("strength", 0) or 0
    health = vp.get("health_score", 50) or 50
    vol = vp.get("vol_trend", "平稳")
    vp_signals = vp.get("signals", []) or []
    stagnant = any("滞涨" in s for s in vp_signals)

    atr = fc.get("atr")
    horizon = int(fc.get("horizon", 7) or 7)
    primary = fc.get("primary_scenario")
    slope_d = (trend.get("slope_pct_per_day", 0.0) or 0.0) / 100.0

    imm_s = kl.get("immediate_support")
    imm_r = kl.get("immediate_resistance")
    res_levels = kl.get("resistance_levels", []) or []
    lower = ch.get("lower")
    upper = ch.get("upper")
    pos = ch.get("pos_in_channel")
    judgement = ch.get("judgement") or {}
    bias = judgement.get("bias")
    ch_conf = judgement.get("confidence", "无")

    # 通道不可用：无法定位上下沿 → 直接观望
    if not ch.get("available"):
        return _wait("通道不可用，无明确狙击/离场结构")

    # 置信度（先算，动作分级要用）
    conf = _confidence(direction, strength, health, ch_conf, primary, bias)
    conf_label = "强" if conf >= CONF_STRONG else ("中" if conf >= CONF_MID else "弱")

    # ---------- 动作判定：先离场/风控，后进场 ----------
    action = ACT_WAIT
    setup: Optional[str] = None

    if direction == "down" and strength >= STRENGTH_MID and bias == "倾向跌破下沿":
        action = ACT_CLEAR                       # 趋势破坏 + 放量下杀
    elif bias == "上沿假突破回落" or (
        pos is not None and pos >= 0.8 and (stagnant or (vol == "放量" and health < HEALTH_HEALTHY))
    ):
        action = ACT_REDUCE                      # 撞上沿量价背离 / 假突破
    elif direction == "up" and health < HEALTH_WEAK:
        action = ACT_REDUCE                      # 顺势但量价背离衰竭 → 降暴露
    elif direction in ("up", "range") and bias == "下沿企稳反弹":
        action = ACT_SNIPE if (conf >= CONF_STRONG and health >= HEALTH_WEAK) else ACT_BUILD
        setup = "低吸"
    elif direction == "up" and bias == "倾向突破上沿" and health >= HEALTH_HEALTHY:
        action = ACT_SNIPE if conf >= CONF_STRONG else ACT_BUILD
        setup = "突破"
    elif direction in ("up", "range") and bias == "临近下沿待企稳确认" and vol == "缩量":
        action = ACT_BUILD                       # 弱一档：回踩待确认
        setup = "低吸"
    elif direction == "up" and bias in ("临近上沿待突破确认", "通道内震荡"):
        action = ACT_HOLD                        # 已在趋势中，无新进场点
    elif direction == "down" and bias == "下沿企稳反弹" and vol == "缩量":
        action = ACT_BUILD                       # 逆势轻仓试探（哲学允许的唯一例外）
        setup = "超跌企稳(试探)"
        conf, conf_label = min(conf, CONF_MID - 1), "弱"   # 试探强制降置信
    else:
        action = ACT_WAIT

    # ---------- 价位计算 ----------
    out: Dict[str, Any] = {
        "action": action,
        "setup_type": setup,
        "confidence": conf,
        "confidence_label": conf_label,
        "entry_zone": None,
        "trigger_price": None,
        "stop": None,
        "target1": None,
        "target2": None,
        "reduce_zone": None,
        "rr1": None,
        "note": "",
    }

    if atr is None or atr <= 0 or cur is None:
        out["note"] = "ATR/价格缺失，价位不可用"
        return out

    if setup in ("低吸", "超跌企稳(试探)"):
        anchor = imm_s if imm_s is not None else lower
        if anchor is None:
            out["note"] = "缺支撑锚，暂不给价位"
            return out
        buy_high = anchor + BUY_ZONE_ABOVE_ATR * atr
        buy_low = anchor - BUY_ZONE_BELOW_ATR * atr
        entry_ref = anchor
        trigger = anchor
        stop = anchor - STOP_ATR * atr
        t1 = imm_r if imm_r is not None else upper
        # 目标2：第二档阻力，否则斜率外推兜底
        t2 = None
        if len(res_levels) >= 2 and res_levels[1].get("value") is not None:
            t2 = float(res_levels[1]["value"])
        if t2 is None:
            extrap = cur * (1 + max(0.0, slope_d) * horizon)
            t2 = max(upper if upper is not None else extrap, extrap)
        out.update(_fill_entry(buy_low, buy_high, trigger, entry_ref, stop, t1, t2))

    elif setup == "突破":
        anchor = imm_r if imm_r is not None else upper
        if anchor is None:
            out["note"] = "缺阻力锚，暂不给价位"
            return out
        buy_low = anchor
        buy_high = anchor + BREAKOUT_CHASE_ATR * atr
        entry_ref = anchor + BREAKOUT_ENTRY_ATR * atr
        trigger = anchor
        stop = anchor - STOP_ATR * atr
        width = (upper - lower) if (upper is not None and lower is not None) else atr
        nxt = _resistance_above(res_levels, anchor)
        t1 = nxt if nxt is not None else anchor + width
        t2 = t1 + width
        out.update(_fill_entry(buy_low, buy_high, trigger, entry_ref, stop, t1, t2))

    elif action in (ACT_REDUCE, ACT_CLEAR):
        reduce_high = imm_r if imm_r is not None else upper
        if reduce_high is not None:
            out["reduce_zone"] = {"low": _r2(reduce_high - REDUCE_BELOW_ATR * atr),
                                  "high": _r2(reduce_high)}
        # 清仓给一个防守止损位（跌破即全清）
        if action == ACT_CLEAR:
            defend = lower if lower is not None else (imm_s if imm_s is not None else None)
            if defend is not None:
                out["stop"] = _r2(defend - STOP_ATR * atr)

    out["note"] = _build_note(action, setup, out, bias, vol)
    return out


def _fill_entry(buy_low, buy_high, trigger, entry_ref, stop, t1, t2) -> Dict[str, Any]:
    """组装进场类价位字段 + RR。保证 buy_low < buy_high、目标 > 参考。"""
    lo, hi = min(buy_low, buy_high), max(buy_low, buy_high)
    rr1 = None
    risk = entry_ref - stop
    if risk > 0 and t1 is not None:
        rr1 = round((t1 - entry_ref) / risk, 2)
    return {
        "entry_zone": {"low": _r2(lo), "high": _r2(hi)},
        "trigger_price": _r2(trigger),
        "stop": _r2(stop),
        "target1": _r2(t1),
        "target2": _r2(t2),
        "rr1": rr1,
    }


def _confidence(direction, strength, health, ch_conf, primary, bias) -> int:
    conf = CONF_CH.get(ch_conf, 0)
    if direction == "up":
        conf += CONF_TREND_MAX * (strength / 100.0)
    elif direction == "range":
        conf += CONF_TREND_MAX * 0.5 * (strength / 100.0)
    # down 不加趋势分
    conf += max(0.0, (health - 50) / 50.0) * CONF_HEALTH_MAX
    if primary == "continuation" and bias in ("下沿企稳反弹", "倾向突破上沿"):
        conf += CONF_SETUP
    return int(round(min(100.0, conf)))


def _build_note(action, setup, out, bias, vol) -> str:
    if action == ACT_WAIT:
        return f"{bias or '结构模糊'}，暂无明确狙击点，观望"
    if action == ACT_CLEAR:
        s = out.get("stop")
        return f"趋势破坏({bias})，清仓离场" + (f"，跌破 {s:g} 确认" if s else "")
    if action == ACT_REDUCE:
        rz = out.get("reduce_zone")
        zone = f"{rz['low']:g}~{rz['high']:g}" if rz else "阻力区"
        return f"撞阻力量价背离({bias})，{zone} 减仓止盈"
    if action == ACT_HOLD:
        return f"已在趋势中({bias})，持有待新信号"
    # 进场类
    ez = out.get("entry_zone") or {}
    parts = [f"{setup}"]
    if ez:
        parts.append(f"{ez.get('low'):g}~{ez.get('high'):g} 挂单")
    if out.get("stop") is not None:
        parts.append(f"跌破 {out['stop']:g} 止损")
    if out.get("target1") is not None:
        t2 = out.get("target2")
        parts.append(f"看 {out['target1']:g}" + (f"/{t2:g}" if t2 is not None else ""))
    if out.get("rr1") is not None:
        parts.append(f"RR≈{out['rr1']}")
    return "，".join(parts)


def _wait(reason: str) -> Dict[str, Any]:
    return {
        "action": ACT_WAIT, "setup_type": None,
        "confidence": 0, "confidence_label": "弱",
        "entry_zone": None, "trigger_price": None, "stop": None,
        "target1": None, "target2": None, "reduce_zone": None, "rr1": None,
        "note": reason,
    }


__all__ = ["build_signals", "ACT_SNIPE", "ACT_BUILD", "ACT_HOLD",
           "ACT_REDUCE", "ACT_CLEAR", "ACT_WAIT"]
