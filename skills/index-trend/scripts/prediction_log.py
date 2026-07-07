#!/usr/bin/env python3
"""预测台账（prediction ledger）—— 闭环的核心。

职责：
1. 每天为每个指数落一条预测（append-only；同 predict_date+index_key 重复跑则更新那条）。
2. 回填：用最新行情，给"已到评估日但还没回填"的旧预测补上真实走势（T+1 与 horizon 末双口径）。
3. 误差指标：方向命中 / 区间覆盖 / 目标偏差 / 概率可靠性。
4. review 报告：把历史表现汇总成可读文本，作为"修正策略"的依据。

存储：ledger/predictions.jsonl，每行一条 JSON（入 git，长期资产）。
写入用 tempfile + os.replace 原子重写整个文件（回填要改历史条目，无法纯 append）。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

_DEFAULT_LEDGER = Path(__file__).resolve().parent.parent / "ledger" / "predictions.jsonl"
SCHEMA_VERSION = 1


# ============================================================
# 读写（原子）
# ============================================================
def load_all(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = Path(path) if path else _DEFAULT_LEDGER
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    out.append(rec)
            except json.JSONDecodeError:
                continue  # 跳过损坏行，不整体失败
    except OSError:
        return []
    return out


def _write_all(records: List[Dict[str, Any]], path: Optional[Path] = None) -> Path:
    path = Path(path) if path else _DEFAULT_LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".jsonl", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False))
                f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


# ============================================================
# 记录构造 + upsert
# ============================================================
def build_record(result: Dict[str, Any], today: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """从单指数 result（含 trend/volume_price/forecast）构造台账记录。异常数据返回 None。"""
    if result.get("error"):
        return None
    fc = result.get("forecast") or {}
    scenarios = fc.get("scenarios") or []
    if not scenarios:
        return None
    primary_type = fc.get("primary_scenario")
    primary = next((s for s in scenarios if s["type"] == primary_type), scenarios[0])
    trend = result.get("trend") or {}
    vp = result.get("volume_price") or {}
    if today is None:
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
    return {
        "schema_version": SCHEMA_VERSION,
        "predict_date": today,
        "index_key": result.get("index_key"),
        "index_name": result.get("index_name"),
        "current_price": result.get("current_price"),
        "horizon": fc.get("horizon", 7),
        "trend": {"direction": trend.get("direction"),
                  "strength": trend.get("strength"),
                  "phase": trend.get("phase"),
                  "health_score": vp.get("health_score")},
        "primary": {"scenario": primary["type"],
                    "direction": primary.get("direction"),
                    "probability": primary.get("probability"),
                    "target_range": primary.get("target_range")},
        "expected_range_t1": fc.get("expected_range_t1"),
        "scenarios_prob": {s["type"]: s.get("probability") for s in scenarios},
        "calibration": result.get("calibration"),
        "outcome_t1": None,
        "outcome_horizon": None,
    }


def upsert(records_new: List[Dict[str, Any]], path: Optional[Path] = None) -> Path:
    """按 (predict_date, index_key) 合并：已存在则替换，否则追加。返回写入路径。"""
    existing = load_all(path)
    index = {(r.get("predict_date"), r.get("index_key")): i for i, r in enumerate(existing)}
    for rec in records_new:
        key = (rec.get("predict_date"), rec.get("index_key"))
        if key in index:
            existing[index[key]] = rec
        else:
            index[key] = len(existing)
            existing.append(rec)
    existing.sort(key=lambda r: (r.get("predict_date", ""), r.get("index_key", "")))
    return _write_all(existing, path)


# ============================================================
# 回填
# ============================================================
def _dir_of(delta: float, base: float, flat_pct: float = 0.3) -> str:
    if base <= 0:
        return "flat"
    pct = delta / base * 100
    if pct > flat_pct:
        return "up"
    if pct < -flat_pct:
        return "down"
    return "flat"


def _in_range(v: float, rng: Optional[Dict[str, float]]) -> Optional[bool]:
    if not rng or v is None:
        return None
    return bool(rng["low"] <= v <= rng["high"])


def backfill(index_dfs: Dict[str, pd.DataFrame], path: Optional[Path] = None) -> int:
    """用最新行情回填未评估的旧预测。index_dfs: {index_key: df(date/OHLC 升序)}。

    返回回填的记录数。按交易日对齐：predict_date 在 df.date 中的位置 + 1 / + horizon。
    """
    records = load_all(path)
    changed = 0
    for rec in records:
        if rec.get("outcome_t1") is not None and rec.get("outcome_horizon") is not None:
            continue
        df = index_dfs.get(rec.get("index_key"))
        if df is None or df.empty:
            continue
        dates = [str(d)[:10] for d in df["date"].tolist()]
        pdate = rec.get("predict_date")
        if pdate not in dates:
            continue
        pos = dates.index(pdate)
        base = rec.get("current_price")
        primary = rec.get("primary") or {}
        pdir = primary.get("direction")

        # T+1 回填
        if rec.get("outcome_t1") is None and pos + 1 < len(dates):
            row = df.iloc[pos + 1]
            close = float(row["close"])
            actual_dir = _dir_of(close - base, base)
            dir_hit = _dir_hit(pdir, actual_dir)
            rec["outcome_t1"] = {
                "actual_date": dates[pos + 1],
                "actual_close": round(close, 2),
                "actual_dir": actual_dir,
                "dir_hit": dir_hit,
                "in_range": _in_range(close, rec.get("expected_range_t1")),
                "err_pct": round((close - base) / base * 100, 2) if base else None,
            }
            changed += 1

        # horizon 末回填
        horizon = int(rec.get("horizon", 7))
        if rec.get("outcome_horizon") is None and pos + horizon < len(dates):
            window = df.iloc[pos + 1: pos + horizon + 1]
            eod = df.iloc[pos + horizon]
            close = float(eod["close"])
            hi = float(window["high"].max())
            lo = float(window["low"].min())
            tr = primary.get("target_range") or {}
            # 主情景是否兑现：路径是否触及目标区间
            primary_hit = None
            if tr:
                primary_hit = bool(lo <= tr.get("high", lo) and hi >= tr.get("low", hi))
            tgt_mid = ((tr.get("low", 0) + tr.get("high", 0)) / 2) if tr else None
            actual_dir = _dir_of(close - base, base)
            rec["outcome_horizon"] = {
                "eval_date": dates[pos + horizon],
                "actual_close": round(close, 2),
                "actual_high": round(hi, 2),
                "actual_low": round(lo, 2),
                "actual_dir": actual_dir,
                "dir_hit": _dir_hit(pdir, actual_dir),
                "primary_hit": primary_hit,
                "in_target_range": _in_range(close, tr) if tr else None,
                "err_pct": round((close - tgt_mid) / base * 100, 2)
                           if (tgt_mid and base) else None,
            }
            changed += 1

    if changed:
        _write_all(records, path)
    return changed


def _dir_hit(predicted: Optional[str], actual: Optional[str]) -> bool:
    if predicted == "range":
        return actual == "flat"
    return predicted == actual


# ============================================================
# 评估指标 + review
# ============================================================
def evaluate(records: List[Dict[str, Any]], index_key: Optional[str] = None) -> Dict[str, Any]:
    """聚合命中率 / 覆盖率 / 偏差 / 概率可靠性。"""
    recs = [r for r in records if (index_key is None or r.get("index_key") == index_key)]
    t1 = [r["outcome_t1"] for r in recs if r.get("outcome_t1")]
    hz = [r["outcome_horizon"] for r in recs if r.get("outcome_horizon")]

    def _rate(items, key):
        vals = [x[key] for x in items if x.get(key) is not None]
        return round(sum(bool(v) for v in vals) / len(vals) * 100, 1) if vals else None

    def _mae(items):
        vals = [abs(x["err_pct"]) for x in items if x.get("err_pct") is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    def _bias(items):
        vals = [x["err_pct"] for x in items if x.get("err_pct") is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {
        "index_key": index_key,
        "n_predictions": len(recs),
        "n_evaluated_t1": len(t1),
        "n_evaluated_horizon": len(hz),
        "t1_dir_hit_rate": _rate(t1, "dir_hit"),
        "t1_range_coverage": _rate(t1, "in_range"),
        "horizon_dir_hit_rate": _rate(hz, "dir_hit"),
        "horizon_primary_hit_rate": _rate(hz, "primary_hit"),
        "horizon_target_coverage": _rate(hz, "in_target_range"),
        "horizon_mae_pct": _mae(hz),
        "horizon_bias_pct": _bias(hz),
        "reliability": _reliability(recs),
    }


def _reliability(recs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """概率可靠性：按主情景声称概率分桶，看 horizon 兑现率 vs 声称率。"""
    buckets = [(0, 40), (40, 55), (55, 70), (70, 101)]
    out = []
    for lo, hi in buckets:
        claimed, hits = [], []
        for r in recs:
            oh = r.get("outcome_horizon")
            p = (r.get("primary") or {}).get("probability")
            if oh is None or p is None or not (lo <= p < hi):
                continue
            claimed.append(p)
            hit = oh.get("primary_hit")
            if hit is not None:
                hits.append(bool(hit))
        if claimed:
            out.append({
                "bucket": f"{lo}-{hi if hi <= 100 else 100}%",
                "n": len(claimed),
                "avg_claimed": round(sum(claimed) / len(claimed), 1),
                "actual_hit_rate": round(sum(hits) / len(hits) * 100, 1) if hits else None,
            })
    return out


def recent_accuracy(records: List[Dict[str, Any]], index_key: str, n: int = 20) -> Dict[str, Any]:
    recs = [r for r in records if r.get("index_key") == index_key][-n:]
    return evaluate(recs, index_key)


def format_review(path: Optional[Path] = None, index_keys: Optional[List[str]] = None) -> str:
    records = load_all(path)
    if not records:
        return "  （台账为空，还没有可评估的历史预测；跑几天后再来看命中率）"
    if index_keys is None:
        index_keys = sorted({r.get("index_key") for r in records if r.get("index_key")})
    lines: List[str] = []
    lines.append(f"\n{'='*78}")
    lines.append(f"  预测台账评估  |  共 {len(records)} 条预测")
    lines.append(f"{'='*78}")
    # 全局
    g = evaluate(records)
    lines.append(_fmt_metrics_block("【全部指数】", g))
    for k in index_keys:
        m = evaluate(records, k)
        name = next((r.get("index_name") for r in records if r.get("index_key") == k), k)
        lines.append(_fmt_metrics_block(f"【{name}】", m))
    lines.append("\n  说明：dir=方向命中率  cover=区间覆盖率  primary=主情景兑现率  "
                 "MAE=目标绝对偏差%  bias=系统偏差%（+偏高/-偏低）")
    return "\n".join(lines)


def _fmt_metrics_block(title: str, m: Dict[str, Any]) -> str:
    def s(v, suf="%"):
        return f"{v}{suf}" if v is not None else "-"
    lines = [f"\n  {title}  预测 {m['n_predictions']} 条 "
             f"(T+1 已评 {m['n_evaluated_t1']} / horizon 已评 {m['n_evaluated_horizon']})"]
    lines.append(f"    T+1     : dir {s(m['t1_dir_hit_rate'])}   cover {s(m['t1_range_coverage'])}")
    lines.append(f"    horizon : dir {s(m['horizon_dir_hit_rate'])}   "
                 f"primary {s(m['horizon_primary_hit_rate'])}   "
                 f"cover {s(m['horizon_target_coverage'])}   "
                 f"MAE {s(m['horizon_mae_pct'])}   bias {s(m['horizon_bias_pct'])}")
    if m["reliability"]:
        rel = "  ".join(
            f"{b['bucket']}:声{b['avg_claimed']}/实{b['actual_hit_rate'] if b['actual_hit_rate'] is not None else '-'}(n{b['n']})"
            for b in m["reliability"]
        )
        lines.append(f"    可靠性  : {rel}")
    return "\n".join(lines)


__all__ = [
    "SCHEMA_VERSION", "load_all", "build_record", "upsert", "backfill",
    "evaluate", "recent_accuracy", "format_review",
]
