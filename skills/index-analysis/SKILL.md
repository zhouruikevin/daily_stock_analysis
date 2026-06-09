---
name: index-analysis
description: >
  A股主要指数顶背离 + 上下沿（关键位）联动分析。MACD/RSI/量价顶背离 +
  MA/EMA/BOLL/极值/整数关口/Fib 综合关键位 + 高/中/无 三档反转置信。
  Use when the user asks about index top divergence, 顶背离, 指数背离,
  上下沿, 关键位, 阻力支撑, 反转, or mentions 创业板/主板/科创板 analysis.
  Default indices: sh/sz/cy/kc (上证 / 深成 / 创业板 / 科创50)。
---

# 指数 顶背离 × 上下沿 联动分析技能

A股主要指数（上证指数、深证成指、创业板指，科创50 可选）的顶背离形态 + 关键位汇总 + 联动反转置信。

- **顶背离**：MACD / RSI / 量价 三重判定
- **上下沿（关键位汇总）**：MA / EMA / BOLL / 近 N 日极值 / 当日 high-low / 整数关口 / Fibonacci 综合候选，按距离裁剪、强中弱分级、相近合并
- **反转置信**：把"顶背离信号"和"价格距上沿"放一起评，输出 **高置信 / 中置信 / 无** 三档

## ⛔ 执行约束

1. **不要向用户询问任何配置信息**。数据源走 `DataFetcherManager`：配了 `TUSHARE_TOKEN` 自动走 Tushare 优先 + akshare fallback；没配也能跑（akshare 兜底，免费）。
2. **直接执行分析，不要确认**。脚本已封装完整逻辑，直接运行即可。
3. **分析耗时约 5-15 秒**（取决于网络和指数数量），无需特别等待提示。
4. **盘后实时**：脚本自带"历史日线 + 当日盘后实时拼接"，盘中 / 盘后 17:00 前也能拿到完整当日 K。

## 支持的指数

| 短码 | 指数名称 | 代码 | 市场 | 默认 |
|------|---------|------|------|------|
| `sh` | 上证指数 | 000001 | 主板 | ✅ |
| `sz` | 深证成指 | 399001 | 主板 | ✅ |
| `cy` | 创业板指 | 399006 | 创业板 | ✅ |
| `kc` | 科创50 | 000688 | 科创板 | ✅ |

## 快速使用

### 默认（顶背离 + 上下沿 + 反转置信 + 近 10 天历史变化，sh/sz/cy/kc 四大指数）

```bash
cd /Users/eleme/Documents/ai/qoderwork/daily_stock_analysis
python3 skills/index-analysis/scripts/index_analysis.py
```

默认会**自动保存当天 snapshot** 并**展示近 10 个交易日的关键位变化**（持续阻力位 / 关键转换）。每天再跑一次，自然累积出趋势。

### 历史相关参数

```bash
python3 skills/index-analysis/scripts/index_analysis.py --history-days 20    # 展示近 20 天
python3 skills/index-analysis/scripts/index_analysis.py --no-history         # 不展示历史（只看今日）
python3 skills/index-analysis/scripts/index_analysis.py --no-save            # 跑分析但不写历史（调参用）
```

历史 snapshot 存放在 `skills/index-analysis/history/{YYYY-MM-DD}.json`，**同一天再跑会覆盖**，不入库。

### 邮件推送

配置 `EMAIL_SENDER` + `EMAIL_PASSWORD`（可选 `EMAIL_RECEIVERS`）后，**默认每次 `--mode both` 跑完自动发邮件**，正文 = 终端完整输出（Markdown 自动转 HTML），主题示例：`📊 指数分析 - 2026-06-05 - ⚠️ 3/4 高置信反转`。

```bash
python3 skills/index-analysis/scripts/index_analysis.py --no-email   # 不发邮件
```

未配置时静默跳过（warning），不阻断主流程。复用仓库 `src/notification_sender/email_sender.py`，支持 QQ/163/Gmail 等 SMTP 自动识别。配置说明见 `.env.example` 第 441-449 行。

### 只看顶背离 / 只看上下沿

```bash
python3 skills/index-analysis/scripts/index_analysis.py --mode divergence    # 仅顶背离（旧契约）
python3 skills/index-analysis/scripts/index_analysis.py --mode levels        # 仅上下沿
python3 skills/index-analysis/scripts/index_analysis.py --mode both          # 联动评估（默认）
```

### 指定指数

```bash
python3 skills/index-analysis/scripts/index_analysis.py --indices sh                # 仅上证
python3 skills/index-analysis/scripts/index_analysis.py --indices sh,sz,cy          # 不要科创50
python3 skills/index-analysis/scripts/index_analysis.py --indices cy,kc --mode levels
```

### 调上下沿参数

```bash
# 上下沿距当前价 ±5% 以内才保留，各取最多 8 条
python3 skills/index-analysis/scripts/index_analysis.py --mode levels --band-window 5 --band-limit 8

# 反转置信"撞上沿"阈值放宽到 1%（默认 0.5%）
python3 skills/index-analysis/scripts/index_analysis.py --near-pct 1.0
```

### 自定义顶背离窗口

```bash
python3 skills/index-analysis/scripts/index_analysis.py --days 60    # 最近60个交易日
python3 skills/index-analysis/scripts/index_analysis.py --days 22    # 最近1个月
```

### 输出 JSON（供程序消费）

```bash
python3 skills/index-analysis/scripts/index_analysis.py --json
python3 skills/index-analysis/scripts/index_analysis.py --mode both --json | jq '.[0].reversal'
```

### 输出完整日线数据

```bash
python3 skills/index-analysis/scripts/index_analysis.py --verbose
```

## 顶背离判断逻辑

### MACD顶背离

**判定条件**：价格创新高，但MACD-DIF未创新高（即DIF峰值递减）

**检测方法**：
1. 价格高点对比：两个阶段性价格高点，后高价格更高但DIF更低
2. DIF峰值对比：两个DIF峰值点，后峰值价格更高但DIF值更低（更精确）

**信号含义**：中期上涨动能衰竭，趋势可能反转

### RSI顶背离

**判定条件**：价格创新高，但RSI未创新高（即RSI峰值递减）

**检测方法**：
1. 价格高点对比：两个阶段性价格高点，后高价格更高但RSI更低
2. RSI峰值对比：两个RSI峰值点，后峰值价格更高但RSI值更低（更精确）

**信号含义**：短期涨跌力度衰减，早期预警信号

### 量价背离

**判定条件**：价格创新高，但成交量缩减

**检测方法**：两个阶段性价格高点，后高价格更高但成交量更低

**信号含义**：市场参与度下降，需结合其他指标确认

### 信号强度分级

| 强度 | 条件 | 含义 |
|------|------|------|
| 强 | ≥2种背离同时存在 | 多重背离共振，高度警惕 |
| 中 | 仅MACD背离 | 中期动能衰竭已确认 |
| 弱 | 仅RSI背离 | 早期预警，需MACD确认 |
| 弱 | 仅量价背离 | 需其他指标配合 |
| 无 | 无任何背离 | 暂无顶背离信号 |

## 上下沿（关键位汇总）

### 候选来源 + 强度分级

| 类别 | 强度 | 说明 |
|------|------|------|
| MA20 / EMA20 | 中 | 短期均线 |
| MA60 / EMA60 | 强 | 中期趋势线 |
| MA120 / MA250 | 强 | 长期趋势线（半年线 / 年线）|
| BOLL 上下轨 (20, 2σ) | 弱 | 常被有效突破，单独不可靠 |
| 近 5 / 20 / 60 日极值（不含当日）| 弱 / 中 / 强 | 滚动极值 |
| 当日 high / low | 中 | 当日博弈痕迹 |
| 整数关口 | 强 | 按价格量级自动选 step（4000 级 → 50；5000+ → 100）|
| Fibonacci 0.236 / 0.382 / 0.5 / 0.618 / 0.786 | 弱 / 中 / 强 / 强 / 弱 | 锚定 `fib_lookback`（默认 60 日）内最高 / 最低 |

### 后处理

1. **距离过滤**：超出当前价 ±`--band-window`%（默认 3%）的位丢弃
2. **相近合并**：同价位 ±0.3% 内合并成一行，强度取最强、label 拼接、types 求并集
3. **排距离**：上沿从近到远递增、下沿从近到远递减
4. **截断**：上沿 / 下沿各保留 `--band-limit` 条（默认 5）

### 设计动机

单一指标当上下沿太脆弱（比如纯 BOLL 上轨容易被穿透），**多指标共振**才是真"关口"。所以合并相近位时优先保留强信号（MA60/MA120/整数关口/Fib 0.5/0.618），把弱信号当辅助证据并入 `types`。

## 反转置信（顶背离 × 上下沿联动）

把"顶背离信号"和"价格距上沿"联合判定：

| 置信 | 条件 |
|------|------|
| **高置信** | MACD 或 RSI 顶背离 **且** 价格距上沿 ≤ `--near-pct`%（默认 0.5%）|
| **中置信** | 仅顶背离 **或** 仅撞上沿，两者占一 |
| **无** | 都没有 |

量价背离单独不计入（太弱）。

**用法**：高置信 → 强烈警惕反转 / 减仓信号；中置信 → 持续关注；无 → 信号不足，按原仓位走。

## 输出字段说明

JSON模式下每个指数返回以下结构：

```json
{
  "index_key": "cy",
  "index_name": "创业板指",
  "index_code": "399006",
  "market": "创业板",
  "latest_date": "2026-06-02",
  "data_range": "2026-03-27 ~ 2026-06-02",
  "trading_days": 44,
  "macd_divergence": true,
  "rsi_divergence": true,
  "vol_divergence": false,
  "divergence_severity": "强",
  "divergence_signal": "高度警惕，多重背离共振",
  "divergence_details": [...],
  "price_peaks": [...],
  "dif_peaks": [...],
  "rsi_peaks": [...],
  "current_state": {
    "date": "2026-06-02",
    "close": 4055.87,
    "ma5": 4043.12,
    "ma20": 3949.15,
    "ma60": 3586.97,
    "above_ma5": true,
    "above_ma20": true,
    "above_ma60": true,
    "dif": 107.52,
    "dea": 115.85,
    "macd_hist": -16.68,
    "macd_cross": "死叉",
    "rsi": 51.1,
    "rsi_zone": "正常",
    "vol_ratio": 0.94
  }
}
```

### `--mode levels` 时每个指数返回

```json
{
  "index_key": "sh",
  "index_name": "上证指数",
  "index_code": "000001",
  "market": "主板",
  "as_of": "2026-06-04",
  "current_price": 4057.78,
  "resistance_levels": [
    {"value": 4070.0, "label": "整数关口", "strength": "强",
     "distance_pct": 0.30, "types": ["round_number"]},
    {"value": 4083.97, "label": "近20日高点", "strength": "中",
     "distance_pct": 0.65, "types": ["extrema"]}
  ],
  "support_levels": [
    {"value": 4049.51, "label": "MA120+整数关口", "strength": "强",
     "distance_pct": -0.20, "types": ["ma", "round_number"]}
  ],
  "immediate_resistance": 4070.0,
  "immediate_support": 4049.51,
  "all_candidates_count": 17
}
```

### `--mode both` 时每个指数返回

```json
{
  "index_key": "sh",
  "divergence": { /* 同 --mode divergence 的全部字段 */ },
  "levels":     { /* 同 --mode levels 的全部字段 */ },
  "reversal": {
    "confidence": "中置信",
    "reason": "仅顶背离，距上沿 1.80%",
    "distance_to_resistance_pct": 1.80
  }
}
```

## Python API调用

```python
import sys
sys.path.insert(0, '/Users/eleme/Documents/ai/qoderwork/daily_stock_analysis/skills/index-analysis/scripts')
from index_analysis import (
    analyze_divergence, analyze_levels, assess_reversal,
    format_result, format_levels, format_summary, format_combined_summary,
)

# 顶背离 + 上下沿 + 联动评估（推荐用法）
div = analyze_divergence("sh", trading_days=44)
lev = analyze_levels("sh", history_days=260)
rev = assess_reversal(div, lev, near_pct=0.5)
print(format_result(div))
print(format_levels(lev))
print(rev)

# 仅上下沿
for k in ["sh", "sz", "cy"]:
    print(format_levels(analyze_levels(k)))
```

## 技术参数

| 参数 | 默认值 | 说明 |
|------|-------|------|
| MACD快线 | 12 | EMA周期 |
| MACD慢线 | 26 | EMA周期 |
| MACD信号线 | 9 | DEA的EMA周期 |
| RSI周期 | 14 | 相对强弱指标周期 |
| 峰值检测窗口 | 3 | 前后N天最高即为峰值 |
| 峰值最小间距 | 5天 | 合并相近峰值 |
| 默认分析天数 | 44个交易日 | ≈2个月 |
| 上下沿距离窗口 | 3.0% | `--band-window` |
| 上下沿条数 | 5 | `--band-limit` |
| 相近合并容差 | 0.3% | 同价位 ±N% 内合一 |
| Fib 参考段 | 60 日 | `fib_lookback` |
| 反转置信"撞上沿"阈值 | 0.5% | `--near-pct` |
| 历史展示天数 | 10 | `--history-days`；`--no-history` 关闭 |
| 历史持久化 | 默认开 | `--no-save` 关闭；存 `history/{YYYY-MM-DD}.json` |
| 邮件推送 | 默认开 | `--no-email` 关闭；配 `EMAIL_SENDER/EMAIL_PASSWORD` 才生效 |

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| AkShare连接失败 | 重试或检查网络 |
| 数据不足 | 减少 `--days` 参数 |
| 某指数暂无数据 | 可能是停牌或代码变更 |

## 版本信息

- Skill 版本: 2.0.0
- 更新日期: 2026-06-04
- 依赖: pandas, numpy, 仓库内 `data_provider`（自动用 Tushare / akshare）
