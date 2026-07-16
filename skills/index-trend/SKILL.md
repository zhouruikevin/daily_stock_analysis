---
name: index-trend
description: >
  A股主要指数趋势与量价推演 + 概率化走势预测 + 历史数据校准闭环。
  以"市场肯定是对的"为信念：用当前趋势结构与量价配合作先验，默认顺势外推，
  量价健康度决定置信、关键位约束路径，输出未来 5-10 交易日的
  顺势延续/震荡回踩/趋势反转 三情景（各带概率+目标价区间）。
  每次预测落台账，回填 T+1 与 horizon 末真实走势，用历史命中率校准后续预测。
  另含自适应「上下沿通道」：有趋势用回归通道、震荡用水平箱体，给出上沿/下沿/
  当前位置 + 量价突破判断（突破上沿/跌破下沿/通道内震荡），判断纳入台账评估。
  另含「狙击/离场信号」（仅做多）：把趋势/量价/通道/关键位翻译成明确动作
  （强狙击/建仓/持有/减仓/清仓/观望）+ 价位（狙击买入区/止损/目标/盈亏比），
  并支持历史回放回测（--backtest：逐日 replay + 模拟买卖，出胜率/盈亏比/回撤/超额）。
  Use when the user asks about 指数走势预测, 后续走势, 后市, 趋势研判, 顺势,
  量价, 量价配合, 量价健康, 趋势延续/反转, 震荡回踩, 目标位, 预测命中率,
  预测校准, 上下沿, 通道, 上沿, 下沿, 阻力支撑, 突破, 跌破,
  买点, 卖点, 狙击点, 进场点, 离场点, 止损, 目标位, 回测, 胜率, 指导操作,
  index trend/forecast/momentum/channel/entry/exit/backtest,
  or mentions 上证/深成/创业板/科创50 后市。
  与 index-analysis(顶背离+关键位) 互补：那个判"是否见顶"，这个预测"接下来怎么走"。
  Default indices: sh/sz/cy/kc（上证/深成/创业板/科创50）。
---

# 指数 趋势 × 量价 走势推演技能

A股主要指数（上证/深成/创业板/科创50）的**概率化走势预测 + 自我校准闭环**。

核心信念：**市场肯定是对的**。不预设反转、不贴形态标签，而是读出当前趋势与量价结构作先验，默认顺势外推，用证据（量价健康度、关键位）调整置信，输出可证伪、可迭代的预测。

- **顺势为先验**：趋势方向由高低点结构 + 均线排列 + 回归斜率三因子投票客观判定。
- **量价定置信**：顺势放量=健康(信趋势延续)；价升量缩/放量滞涨=背离(降置信，但不判反转)。
- **关键位定路径**：复用关键位汇总（MA/EMA/BOLL/极值/整数关口/Fib）当目标锚点。
- **概率化三情景**：顺势延续 / 震荡回踩 / 趋势反转，各给概率 + 目标价区间（未来 5-10 交易日）。
- **狙击/离场信号（仅做多）**：把上述结构翻译成一个纪律动作（强狙击/建仓/持有/减仓/清仓/观望）+ 一组价位（狙击买入区/触发确认/止损/目标1·2/减仓区/盈亏比），指导操作。
- **自我校准闭环**：每天记录预测 → 回填 T+1 与 horizon 末真实走势 → 用历史命中率校准下一次预测。
- **历史回放回测**：`--backtest` 逐日 replay 信号 + 模拟单一仓位买卖，立即出胜率/盈亏比/最大回撤/超额收益，供验证与调参。

## ⛔ 执行约束

1. **不要向用户询问任何配置信息**。数据源走 `DataFetcherManager`：配了 `TUSHARE_TOKEN` 走 Tushare 优先 + akshare fallback；没配也能跑（akshare 免费兜底）。
2. **直接执行分析，不要确认**。脚本已封装完整逻辑，直接运行即可。
3. **分析耗时约 5-15 秒**（取决于网络和指数数量）。
4. **盘后实时**：数据层自带"历史日线 + 当日盘后实时拼接"，盘中/盘后都能拿到完整当日 K。
5. **默认写台账 + 回填**：每次跑会把预测追加到 `ledger/predictions.jsonl`（入 git），并回填到期旧预测的真实走势。调参探索时用 `--no-save`。
6. **信号是纪律非建议**：狙击/离场信号是顺势框架下的机械纪律输出（仅做多），**非投资建议**；回测为历史统计，不代表未来。用 `--no-signals` 可关闭信号生成与展示。

## 支持的指数

| 短码 | 指数名称 | 代码 | 市场 | 默认 |
|------|---------|------|------|------|
| `sh` | 上证指数 | 000001 | 主板 | ✅ |
| `sz` | 深证成指 | 399001 | 主板 | ✅ |
| `cy` | 创业板指 | 399006 | 创业板 | ✅ |
| `kc` | 科创50 | 000688 | 科创板 | ✅ |

## 快速使用

```bash
cd /Users/eleme/Documents/ai/qoderwork/daily_stock_analysis

# 默认：四大指数，概率化预测 + 历史校准，写台账 + 回填
# 注意：需在已激活项目虚拟环境下运行（依赖 tenacity/fake_useragent/akshare，见 requirements.txt）
# 未激活时可直接用 venv 解释器： .venv/bin/python skills/index-trend/scripts/index_trend.py
python3 skills/index-trend/scripts/index_trend.py

# 指定指数 / 预测跨度
python3 skills/index-trend/scripts/index_trend.py --indices sh
python3 skills/index-trend/scripts/index_trend.py --indices sh,cy --horizon 10

# JSON 输出（供程序消费）
python3 skills/index-trend/scripts/index_trend.py --json
python3 skills/index-trend/scripts/index_trend.py --json | jq '.[0].forecast.scenarios'

# 只看历史预测命中率 / 校准报告（不做新预测）
python3 skills/index-trend/scripts/index_trend.py --review

# 只回填旧预测的真实走势（不做新预测）
python3 skills/index-trend/scripts/index_trend.py --backfill-only

# 关闭历史校准（只出原始模型），或不写台账、不发邮件
python3 skills/index-trend/scripts/index_trend.py --no-calibration
python3 skills/index-trend/scripts/index_trend.py --no-save --no-email

# 历史回放回测（仅做多，逐日 replay + 模拟买卖 → 胜率/盈亏比/回撤/超额）
python3 skills/index-trend/scripts/index_trend.py --backtest --indices sh
python3 skills/index-trend/scripts/index_trend.py --backtest --backtest-months 12
python3 skills/index-trend/scripts/index_trend.py --backtest --indices sh --json | jq '.trades'

# 关闭狙击/离场信号（回到旧行为，只出走势推演）
python3 skills/index-trend/scripts/index_trend.py --no-signals
```

### 邮件推送

配置 `EMAIL_SENDER` + `EMAIL_PASSWORD`（可选 `EMAIL_RECEIVERS`）后，默认每次跑完自动发邮件，正文 = 终端输出的结构化 Markdown（自动转 HTML 表格）。未配置时静默跳过，不阻断主流程。复用仓库 `src/notification_sender/email_sender.py`。

```bash
python3 skills/index-trend/scripts/index_trend.py --no-email   # 不发邮件
```

主题示例：`📈 指数趋势 - 2026-07-07 - 上证顺势上行(P58) | 创业板转震荡`

## 算法

### 1. 趋势状态（客观量化，不贴形态名）

- **方向**（三因子投票 → `up/down/range`）：高低点结构（HH+HL=up / LH+LL=down）+ 均线排列（ma5>10>20>60=多头）+ 近 20 日归一化回归斜率（>+0.1%/日=up）。多数决，平票偏 range。
- **强度 0-100**：斜率陡度(40) + 均线发散度(25) + 回归 r²(20) + 方向一致性(15)。映射 强≥67/中≥34/弱。震荡趋势强度上限 40。
- **阶段** 初期/加速/稳定/衰竭：由斜率二阶变化 + 量价配合近似。

### 2. 量价健康度（顺势基准偏高，背离只减分）

基准 60。顺势放量 +20 / 价升量缩背离 -20 / 放量滞涨 -15 / 天量(量比>2.5)按位置减分 / 缩量整理轻微。输出 `health_score`(0-100) + 标签（健康≥67/中性≥34/背离衰竭）+ 命中信号列表。

### 3. 上下沿通道（自适应：回归通道 / 水平箱体）

"通道就是上下沿"——近期走势被框在一条上沿、一条下沿之间。自适应选形态：

- **有趋势**（近 N 日回归 r² ≥ `--channel-r2`，默认 0.5）→ **回归通道**：中轨=回归线随趋势倾斜，上沿=中轨+`k`·残差σ、下沿=中轨−`k`·σ（`k`=`--channel-k`，默认 2）。
- **震荡**（r² < 阈值）→ **水平箱体**：上沿=近 N 日 high 的 90 分位、下沿=low 的 10 分位（分位抗插针）。
  - 实盘依据：震荡市回归通道斜率无意义，故降级为水平箱体。

输出 `type`/`upper`/`mid`/`lower`/`pos_in_channel`(0-1)/`direction`/`r2`/`width_pct`。再结合量价给 `judgement`：
贴上沿(pos≥0.8)+放量→倾向突破上沿、+缩量/滞涨→上沿假突破回落；贴下沿(pos≤0.2)+放量→倾向跌破下沿、+缩量→下沿企稳反弹；中部→通道内震荡。

**评估**：通道判断随预测一起入台账，回填时按 horizon 窗口算 **含纳率**（收盘落在通道内比例）、**bias 命中率**（判断是否兑现）、**上/下沿误差%**，`--review` 展示（见第 6 节）。

### 4. 概率化情景推演

| 情景 | 方向 | 目标区间来源 |
|------|------|------|
| 顺势延续 | 当前趋势方向 | min(斜率外推, 下一顺势关键位) ± 0.5·ATR·√h |
| 震荡回踩 | 区间 | 当前箱体 [立即支撑, 立即阻力] |
| 趋势反转 | 反向 | 反向第一个关键位 ± 0.5·ATR·√h |

概率模型（`scoring.py`，顺势先验）：

```
p_cont = {range:35,弱:45,中:55,强:65}[强度] + (health-50)*0.4 ; 撞位 -10
p_rev  = {range:25,弱:20,中:15,强:10}[强度] + (50-health)*0.3 ; 撞位 +8
p_cons = 100 - p_cont - p_rev
三者 clamp[5,85] 后归一化到 100
```

整体预期波动带 = `current ± 1.0·ATR14·√horizon`；T+1 预期带 = `current ± 1.0·ATR14`。

### 5. 历史校准（用已发生数据修正后面的答案）

读台账聚合该指数历史表现（**近期指数加权**），对原始预测做**有界 + 收缩式**修正：

- 收缩权重 `w = n/(n+20)`：样本少→w→0→几乎不改（冷启动安全）；样本多→更信数据。
- **概率校准**：每情景概率朝其历史实际兑现率移动，单项 cap ±15，再归一化。
- **目标纠偏**：按历史系统性偏差平移目标区间，cap ±2%。
- **带宽自适应**：历史区间覆盖率 < 70% → 放宽目标区间，cap 1.5×。

修正量在输出的 `calibration` 段显式列明（样本数 / w / 各项调整），透明可审计。`--no-calibration` 关闭。

### 6. 预测台账与回填（`ledger/predictions.jsonl`，入 git）

- 每次跑为每指数落一条预测（同 predict_date+index_key 重复跑则更新那条）。
- **T+1 回填**：predict_date 后第 1 个交易日的真实收盘 → 方向命中 / 区间覆盖 / 偏差%。
- **horizon 末回填**：第 horizon 个交易日 → 主情景是否兑现 / 目标覆盖 / 偏差%。
- 按交易日对齐，缺跑也能补（行情含完整历史）。原子重写整文件防损坏。
- **信号回填**：进场类信号（强狙击/建仓）按 horizon 窗口评估——是否触发买入、先触目标还是先触止损、`pnl_pct` / `r_multiple` / `win`。`--review` 汇总信号胜率/盈亏比/PF/期望R + 分形态命中，并对样本足够但持续亏损的形态给**只读调参建议**（不自动改常量）。

### 7. 狙击/离场信号（仅做多，动作 + 价位）

把已算好的 趋势/量价/通道/关键位/ATR **翻译成一个纪律动作 + 一组价位**，不引入新指标、不做空。以 `channel.judgement.bias` 为主驱动（bias 已把贴边+量价编码进去），`trend/health/vol` 作阈值门与置信度微调。

- **动作枚举**：`强狙击 / 建仓 / 持有 / 减仓 / 清仓 / 观望`。判定顺序先离场后进场（安全优先）：
  - `下降趋势(强度≥34) + 倾向跌破下沿` → **清仓**；`上沿假突破回落` 或 贴上沿放量滞涨/背离 → **减仓**；`上升 + 量价背离衰竭(health<34)` → **减仓**。
  - `上升/震荡 + 下沿企稳反弹` → **强狙击/建仓**（低吸）；`上升 + 倾向突破上沿 + health≥67` → **强狙击/建仓**（突破）；`临近下沿待企稳 + 缩量` → **建仓**；`上升 + 通道内震荡/临近上沿` → **持有**；其余（含下降默认、通道不可用）→ **观望**。
  - 唯一逆势例外：`下降 + 下沿企稳反弹 + 缩量` → **轻仓试探建仓**，置信强制降"弱"。
- **价位（以 ATR 为单位自适应）**：低吸买入区 `支撑±(0.2/0.3)ATR`、止损 `支撑−1.2ATR`、目标1=最近阻力/上沿、目标2=次档阻力或斜率外推；突破追击区 `上沿→上沿+0.5ATR`、目标按等距测量。附盈亏比 `rr1`。
- **置信度 0-100**：通道置信 + 顺势强度（up满/range半/down零）+ 量价健康 + 顺势 setup 加成，映射 强≥67/中≥40/弱。

### 8. 历史回放回测（`--backtest`，仅做多单一仓位）

用一段历史逐日 replay：每个 bar `t` 用**切片 `df.iloc[:t+1]`** 重算全链路信号（所有分析函数只回看、无未来函数），成交只发生在 `t+1` 及以后（信号 `t` 收盘产生，最早次日撮合）。

- **状态机**：空仓遇进场信号挂单（低吸=限价触及买入区、突破=站上触发价）→ 持仓按 **止损>目标2>目标1>信号清仓(次日开盘)>timeout(H根后收盘)** 离场。
- **保守假设**：同一 bar high/low 同时穿越目标与止损时，日线无法判先后 → **统一记止损**（避免虚高胜率）。v1 全进全出，减仓/加仓（需仓位规模模型）留 v2——回测中「减仓」不强制离场。
- **产出**：交易次数、胜率、平均盈/亏、盈亏比、Profit Factor、期望R、最大回撤、总收益 vs 买入持有基准、超额收益、分形态胜率、交易明细。

## 输出字段（`--json`）

```json
{
  "index_key":"sh","index_name":"上证指数","current_price":3977.67,
  "trend":{"direction":"range","strength":20,"strength_label":"弱","phase":"稳定",
           "structure":"混合","ma_alignment":"空头排列","slope_pct_per_day":0.01,"r2":0.002},
  "volume_price":{"health_score":65,"health_label":"中性","vol_ratio":0.76,
                  "vol_trend":"缩量","signals":["缩量整理"]},
  "channel":{"available":true,"type":"水平箱体","upper":4192.58,"mid":4081.73,"lower":3970.89,
             "pos_in_channel":0.087,"direction":"横向","r2":0.292,"width_pct":5.56,
             "judgement":{"bias":"临近下沿待企稳确认","confidence":"中","reason":".."}},
  "key_levels":{"resistance_levels":[...],"support_levels":[...],
                "immediate_resistance":...,"immediate_support":...},
  "forecast":{"horizon_days":[5,10],"atr":64.25,
    "expected_range":{"low":..,"high":..},"expected_range_t1":{"low":..,"high":..},
    "scenarios":[{"type":"continuation","name":"顺势延续(上行)","direction":"up",
                  "probability":40,"target_range":{"low":..,"high":..},
                  "trigger":"..","rationale":".."}, ...],
    "primary_scenario":"consolidation","signal":"..."},
  "signals":{"action":"强狙击","setup_type":"低吸","confidence":78,"confidence_label":"强",
             "entry_zone":{"low":..,"high":..},"trigger_price":..,"stop":..,
             "target1":..,"target2":..,"reduce_zone":null,"rr1":2.3,"note":".."},
  "forecast_raw":{...},   // --verbose 时带，校准前的原始预测
  "calibration":{"n_samples":34,"applied":true,"shrink_w":0.63,
                 "prob_adjust":{"continuation":-4.2},"bias_shift_pct":-0.3,"widen_factor":1.1},
  "error":null
}
```

`--backtest --json` 输出的是回测报告：`{index_key,index_name,period,n_trades,win_rate,payoff_ratio,profit_factor,avg_r,max_drawdown_pct,total_return_pct,buyhold_pct,excess_pct,per_setup,trades[],equity_curve[]}`。

## Python API

```python
import sys
sys.path.insert(0, '/Users/eleme/Documents/ai/qoderwork/daily_stock_analysis/skills/index-trend/scripts')
from index_trend import analyze_index
import prediction_log as ledger

r = analyze_index("sh", horizon=7)          # 单指数完整预测（含校准 + 信号）
print(r["forecast"]["signal"])
print(r["signals"]["action"], r["signals"]["entry_zone"], r["signals"]["stop"])  # 狙击点
print(ledger.format_review(index_keys=["sh"]))   # 历史命中率 + 信号胜率报告

import backtest
from index_trend import _fetch_df
rep = backtest.run_backtest("sh", _fetch_df("sh", 300), months=6)
print(backtest.format_backtest(rep))        # 历史回放回测报告
```

## 技术参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--horizon` | 7 | 预测跨度（交易日） |
| `--days` | 120 | 分析窗口（额外多取 60 算长均线/ATR） |
| `--swing-threshold` | 3.0 | zigzag 幅度过滤 % |
| `--channel-lookback` | 40 | 上下沿通道回溯交易日 |
| `--channel-k` | 2.0 | 回归通道带宽 = k×残差σ |
| `--channel-r2` | 0.5 | r²≥此值用回归通道，否则水平箱体 |
| `--backtest` | off | 进入历史回放回测模式 |
| `--backtest-months` | 6 | 回测回放最近 N 个月（≈N×21 交易日） |
| `--no-signals` | off | 关闭狙击/离场信号生成与展示 |
| 信号止损 | 1.2·ATR | 结构位下方止损距离 |
| 信号买入区 | ±0.2/0.3·ATR | 低吸买入区上/下缓冲 |
| 置信门槛 | 67/40 | 强狙击/建仓（中）分界 |
| 顺势基准 | 35/45/55/65 | range/弱/中/强 |
| health 基准 | 60 | 量价健康度起点 |
| 撞位阈值 | 1.5% | 顺势方向距最近关键位 |
| ATR 预期带系数 | 1.0 | 整体波动带宽 |
| 收缩常数 K | 20 | 校准样本达 K 时数据/先验各半 |
| 近期加权衰减 | 0.97 | 台账样本指数衰减 |
| 概率修正上限 | ±15 | 单情景 |

## 故障排查

| 问题 | 解决 |
|------|------|
| AkShare 连接失败 | 重试或检查网络 |
| 数据不足致长均线为空 | 对应因子自动降级跳过，不崩 |
| 台账暂无样本 | 校准自动跳过用原始模型，跑几天积累后生效 |
| 某指数停牌/代码变更 | 该指数进 error，不影响其它指数 |

## 版本信息

- Skill 版本: 1.2.0
- 更新日期: 2026-07-15
- 依赖: pandas, numpy, 仓库内 `data_provider`（Tushare/akshare）、`src/notification_sender`（邮件）
- 与 `index-analysis` 互补，不共享脚本（各自包含）。
- v1.2.0：新增「狙击/离场信号」（仅做多，动作+价位）+ 历史回放回测 `--backtest` + 信号落台账/回填/胜率统计；信号阈值 v1 手动调参（不自动校准）。
- v1.1.0：新增自适应「上下沿通道」（回归通道/水平箱体）+ 量价突破判断 + 通道判断纳入台账评估。
