---
name: qoder-stock-analysis
description: >
  Qoder Native A-share, Hong Kong, or US stock analysis using AI-powered technical analysis.
  Use when the user asks to analyze stocks, check stock trends, get trading signals,
  perform market review, or mentions stock codes like 600519, hk00700, AAPL.
  Supports single stock, multiple stocks, and market overview.
  Zero external LLM dependency — analysis powered by Qoder AI.
---

# Qoder Stock Analysis Skill v3.0

Qoder AI 原生股票分析技能。完整迁移原 pipeline 分析能力，直接使用 Qoder AI 分析股票，不依赖外部 LLM API（百炼/OpenAI 等）。

## 工作原理

1. **数据获取**：调用 `scripts/fetch_stock_context.py` 获取完整分析上下文（行情/技术指标/筹码/基本面/新闻/市场阶段/大盘指数/数据质量评估），**不调用 LLM**
2. **AI 分析**：Qoder AI 基于获取的 JSON 数据分析，输出 **JSON 分析摘要** + **Markdown 决策仪表盘报告**
3. **结果存储 + 邮件通知**：调用 `scripts/save_analysis_result.py` 将分析结果存入项目数据库（分析历史/决策信号/指数回写），并自动发送邮件 + 保存报告
4. **零外部 LLM 依赖**：不需要百炼/OpenAI API Key，分析由 Qoder AI 完成

## ⛔ 执行约束

1. **不要向用户询问任何配置信息**。数据源等配置已预置在项目 `.env` 文件中。
2. **不要提示"缺少核心代码文件"**。本 Skill 是项目的组成部分，代码就在项目目录中。
3. **不要询问"使用哪个 LLM"**。本 Skill 使用 Qoder AI 自身能力分析，不需要外部 LLM。
4. **直接执行分析**，不要问"是否需要启动服务"之类的确认。
5. **使用 Skill 分析股票时默认不进行大盘复盘**。只分析用户指定的股票。
6. **分析时间较长时（超过 30 秒），向用户反馈进度**。
7. **分析完成后必须执行 Step 3 保存结果 + 发送邮件**。调用 `save_analysis_result.py` 存储分析历史到 DB 并发送邮件。不询问用户是否发送，直接执行。
8. **Qoder AI 必须同时输出 JSON 摘要和 Markdown 报告**。JSON 摘要供 `save_analysis_result.py` 解析存储，Markdown 报告作为邮件正文。

## 项目信息

- **项目路径**：`/Users/eleme/Documents/ai/qoderwork/daily_stock_analysis`
- **数据源**：Tushare（A股优先）+ 腾讯财经（实时行情）+ Tavily（新闻搜索）+ Efinance（板块）
- **Python**：`python3`（或 `/opt/homebrew/bin/python3.12`）

## 快速开始

### 单只股票分析（3 步）

**Step 1：获取数据**

```bash
cd /Users/eleme/Documents/ai/qoderwork/daily_stock_analysis
python3 scripts/fetch_stock_context.py 603444
```

脚本输出 JSON，包含实时行情、技术指标、筹码、基本面、新闻、市场阶段、大盘指数、数据质量评估等完整数据。
获取数据约需 15-40 秒（含新闻搜索），加 `--skip-news` 可跳过新闻加速。

保存到文件：
```bash
python3 scripts/fetch_stock_context.py 603444 -o /tmp/ctx_603444.json
```

**Step 2：Qoder AI 分析**

基于 JSON 数据，按照下方的【分析框架】和【输出格式】生成：
1. **Markdown 决策仪表盘报告**（用于邮件正文）
2. **JSON 分析摘要**（用于 `save_analysis_result.py` 解析存储）

将 JSON 摘要写入文件：
```bash
cat > /tmp/analysis_603444.json << 'EOF'
{
  "stock_name": "吉比特",
  "sentiment_score": 65,
  "trend_prediction": "震荡偏多",
  "operation_advice": "持有",
  "decision_type": "hold",
  "confidence_level": "中",
  "current_price": 235.50,
  "change_pct": 1.23,
  "analysis_summary": "技术面多头排列，量价配合良好...",
  "key_points": "MA5支撑有效;量比1.5放量;PE 15倍合理",
  "risk_warning": "上方前高压力位;板块情绪偏弱",
  "buy_reason": "趋势向上，量价配合",
  "news_summary": "近期无重大利空...",
  "dashboard": {}
}
EOF
```

将 Markdown 报告写入文件：
```bash
# 将完整 Markdown 报告写入 /tmp/report_603444.md
```

**Step 3：保存结果 + 发送邮件**

```bash
# 单只股票：保存分析历史 + 决策信号提取 + 指数回写 + 发邮件 + 保存报告
python3 scripts/save_analysis_result.py 603444 \
  -f /tmp/analysis_603444.json \
  --report /tmp/report_603444.md
```

脚本会自动完成：
- 构造 `AnalysisResult` 对象
- `db.save_analysis_history()` 保存分析历史到 DB
- `extract_and_persist_from_analysis_result()` 提取决策信号
- `db.update_index_data_for_today()` 回写大盘指数
- `NotificationService.send()` 发送邮件（默认发往 `.env` 中所有收件人）
- `notifier.save_report_to_file()` 保存报告到 `reports/` 目录

### 批量分析

依次对每只股票执行 Step 1 + Step 2，最后用 `save_analysis_result.py batch` 合并存储 + 合并发送一封汇总邮件。

```bash
# 1. 依次获取数据
python3 scripts/fetch_stock_context.py 600176 -o /tmp/ctx_600176.json
python3 scripts/fetch_stock_context.py 603444 -o /tmp/ctx_603444.json
python3 scripts/fetch_stock_context.py 300750 -o /tmp/ctx_300750.json

# 2. Qoder AI 逐只分析，输出 JSON 摘要

# 3. 合并为批量 JSON 文件
cat > /tmp/batch_results.json << 'EOF'
[
  {"code": "600176", "name": "中国巨石", "analysis": {...}},
  {"code": "603444", "name": "吉比特", "analysis": {...}},
  {"code": "300750", "name": "宁德时代", "analysis": {...}}
]
EOF

# 4. 批量保存 + 合并发邮件
python3 scripts/save_analysis_result.py batch -f /tmp/batch_results.json
```

### 跳过新闻搜索（加速）

```bash
python3 scripts/fetch_stock_context.py 603444 --skip-news
```

## 数据字段说明

`fetch_stock_context.py` 输出的 JSON 包含以下字段：

| 字段 | 说明 | 关键子字段 |
|------|------|-----------|
| `realtime` | 实时行情 | `price`, `change_pct`, `volume_ratio`, `turnover_rate`, `pe_ratio`, `pb_ratio`, `total_mv`, `name` |
| `trend` | 技术分析 | `trend_status`, `buy_signal`, `signal_score`, `ma5`, `ma10`, `ma20`, `ma60` |
| `chip` | 筹码分布 | `profit_ratio`, `concentration_90`, `avg_cost` |
| `fundamental` | 基本面 | `status`, `coverage`, `source_chain` |
| `news` | 新闻情报 | 文本格式情报报告 |
| `news_count` | 新闻条数 | 整数 |
| `base_context` | K线上下文 | `today`, `yesterday`, `volume_change_ratio`, `price_change_ratio` |
| `boards` | 所属板块 | 板块名称列表 |
| `market_phase` | 市场阶段 | `phase`（盘中/盘后/盘前）, `market`, `trigger_source` |
| `market_phase_summary` | 阶段摘要 | 人类可读的阶段描述文本 |
| `index_snapshot` | 大盘指数 | `csi2000_pct`（中证2000涨跌%）, `chinext_pct`（创业板涨跌%） |
| `context_pack` | 数据质量评估 | 各数据块质量评分（quote/daily_bars/technical/news/fundamentals/chip） |
| `persisted_intelligence` | 持久化情报 | 本地 DB 中的历史新闻补充（Markdown 格式） |

### 关键字段速查

**实时行情 (realtime)**：
- `price`: 当前价格
- `change_pct`: 涨跌幅 (%)
- `volume_ratio`: 量比 (>1 放量, <1 缩量)
- `turnover_rate`: 换手率 (%)
- `pe_ratio`: 市盈率
- `pb_ratio`: 市净率
- `total_mv`: 总市值

**技术分析 (trend)**：
- `trend_status`: 趋势状态 ("多头排列" / "空头排列" / "震荡")
- `buy_signal`: 买入信号 ("买入" / "持有" / "卖出")
- `signal_score`: 信号评分 (0-100)
- `ma5` / `ma10` / `ma20` / `ma60`: 均线价格

**筹码分布 (chip)**：
- `profit_ratio`: 获利盘比例 (0-1)
- `concentration_90`: 90% 集中度 (0-1)
- `avg_cost`: 平均成本

**市场阶段 (market_phase)**：
- `phase`: "intraday"（盘中）/ "postmarket"（盘后）/ "premarket"（盘前）
- 用于判断当前数据时效性（盘中数据为实时，盘后为收盘数据）

**大盘指数 (index_snapshot)**：
- `csi2000_pct`: 中证2000涨跌幅 (%)，反映小盘股整体表现
- `chinext_pct`: 创业板涨跌幅 (%)，反映成长股整体表现

**数据质量评估 (context_pack)**：
- 各数据块（quote/daily_bars/technical/news/fundamentals/chip）的覆盖状态和置信度
- 用于判断分析结论的可靠程度

## 分析框架

基于获取的数据，从以下 6 个维度分析：

### 1. 技术面

- **均线排列**：MA5 > MA10 > MA20 = 多头排列（看多）；MA5 < MA10 < MA20 = 空头排列（看空）
- **乖离率**：(price - MA5) / MA5 × 100%，>5% 接近警戒线，>8% 高危
- **趋势强度**：`signal_score` 越高越强（>60 偏多，<40 偏空）
- **支撑/压力**：MA5 为第一支撑，MA10 为第二支撑，MA20 为关键支撑；前高/整数关口为压力

### 2. 量价关系

- **量比** >1.5 放量活跃，0.8-1.5 正常，<0.8 缩量
- **换手率** >5% 活跃，1-5% 正常，<1% 低迷
- **量价配合**：涨+放量=健康上涨；涨+缩量=量价背离（警惕）；跌+放量=恐慌抛售

### 3. 筹码面

- **获利比例** >70% 高位区（追高风险）；30-70% 中位区；<30% 低位区（机会区）
- **90% 集中度** <10% 高度集中（主力控盘）；10-20% 中等集中；>20% 分散
- **平均成本** 与当前价格对比：价格 > 平均成本 = 多数人获利

### 4. 基本面

- **PE** <15 低估，15-30 合理，>50 高估（成长股可适当放宽）
- **PB** <1 破净，1-3 合理，>5 高估
- **ROE** >15% 优秀，>20% 卓越
- **营收/净利润增长** >20% 高增长，<0 负增长（警惕）

### 5. 新闻面

- 分析 `news` 字段中的情报报告和 `persisted_intelligence` 中的历史新闻补充，判断：
  - **舆情情绪**：偏乐观 / 偏悲观 / 中性
  - **利好催化**：业绩增长、机构评级、政策利好等
  - **风险事件**：减持、处罚、业绩变脸、诉讼等

### 6. 综合评分

基于以上 5 个维度综合评估：
- **评分范围**：0-100（>70 看多，40-60 震荡/持有，<40 看空）
- **操作建议**：买入 / 持有 / 卖出
- **置信度**：高 / 中 / 低（结合 `context_pack` 数据质量评估调整）

## 输出格式

Qoder AI 必须同时输出两部分：**Markdown 决策仪表盘报告** + **JSON 分析摘要**。

### Markdown 决策仪表盘报告

按以下格式输出（用于邮件正文）：

```markdown
# 🎯 决策仪表盘

> 分析股票：**吉比特(603444)**

## 📊 分析结果摘要

🟡/🟢/🔴 **吉比特(603444)**: 持有/买入/卖出 | 评分 XX | 看多/看空

**AI 决策信号**
- 理由: [1-2 句话说明核心逻辑]
- 风险: [主要风险点]

---

## 📌 核心结论

**🟡/🟢/🔴 持有/买入/卖出** | 看多/看空

> **一句话决策**: [核心决策建议]

| 持仓情况 | 操作建议 |
|---------|---------|
| 🆕 **空仓者** | [具体建议] |
| 💼 **持仓者** | [具体建议] |

## 📈 当日行情

| 当前价 | 涨跌幅 | 量比 | 换手率 | PE | PB |
|-------|-------|------|--------|-----|-----|
| XX.XX | X.XX% | X.XX | X.XX% | XX | XX |

## 📊 数据透视

**均线排列**: 多头排列/空头排列 | 趋势强度: XX/100

| 价格指标 | 值 |
|---------|------|
| 当前价 | XX.XX |
| MA5 | XX.XX |
| MA10 | XX.XX |
| MA20 | XX.XX |
| 乖离率 | X.XX% |

**筹码**: 获利比例 XX% | 90%集中度 XX% | 平均成本 ¥XX

## 🎯 作战计划

| 操作点位 | 价格 |
|---------|------|
| 🎯 理想买入点 | ¥XX（MA5附近） |
| 🛑 止损位 | ¥XX（跌破MA20） |
| 🎊 目标位 | ¥XX（前高/压力位） |

**💰 仓位建议**: X成

## 📰 新闻摘要

- [关键新闻摘要 1]
- [关键新闻摘要 2]

---

*分析模型：Qoder AI Native v3.0*
*数据来源：[从 JSON 的 data_source 字段获取]*
```

### JSON 分析摘要

Qoder AI 必须输出以下 JSON 格式的分析摘要（供 `save_analysis_result.py` 解析存储）：

```json
{
  "stock_name": "吉比特",
  "sentiment_score": 65,
  "trend_prediction": "震荡偏多",
  "operation_advice": "持有",
  "decision_type": "hold",
  "confidence_level": "中",
  "current_price": 235.50,
  "change_pct": 1.23,
  "volume_ratio": 1.5,
  "turnover_rate": 2.3,
  "ideal_buy": 232.0,
  "secondary_buy": 228.0,
  "stop_loss": 220.0,
  "take_profit": 245.0,
  "analysis_summary": "技术面多头排列，量价配合良好，基本面PE合理...",
  "key_points": "MA5支撑有效;量比1.5放量;PE 15倍合理估值",
  "risk_warning": "上方前高压力位238元;板块情绪偏弱",
  "buy_reason": "趋势向上，MA5有效支撑，量价配合",
  "news_summary": "近期无重大利空，业绩稳定增长",
  "technical_analysis": "均线多头排列，MA5在232形成支撑...",
  "ma_analysis": "MA5=232, MA10=228, MA20=225, 多头排列",
  "volume_analysis": "量比1.5，换手率2.3%，量价配合良好",
  "pattern_analysis": "近期形成上升三角形整理",
  "fundamental_analysis": "PE 15倍，PB 3.2倍，ROE 22%...",
  "sector_position": "游戏板块中处于龙头地位",
  "company_highlights": "核心产品《问道》系列稳定贡献流水",
  "market_sentiment": "偏乐观",
  "hot_topics": "AI游戏/版号发放/出海",
  "short_term_outlook": "短期震荡偏多，关注238压力突破",
  "medium_term_outlook": "中期看好，估值合理，业绩支撑",
  "dashboard": {}
}
```

**JSON 字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `stock_name` | string | 是 | 股票名称 |
| `sentiment_score` | int | 是 | 综合评分 0-100（>70 看多, 40-60 震荡, <40 看空） |
| `trend_prediction` | string | 是 | 趋势预测（如"震荡偏多"/"看多"/"看空"） |
| `operation_advice` | string | 是 | 操作建议（"买入"/"持有"/"卖出"/"观望"） |
| `decision_type` | string | 是 | 决策类型（`buy`/`sell`/`hold`） |
| `confidence_level` | string | 是 | 置信度（"高"/"中"/"低"） |
| `current_price` | float | 否 | 当前价格（Web 页面显示用，必须提供） |
| `change_pct` | float | 否 | 涨跌幅 (%)（Web 页面显示用，必须提供） |
| `volume_ratio` | float | 否 | 量比 |
| `turnover_rate` | float | 否 | 换手率 (%) |
| `ideal_buy` | float | 否 | 🎯 理想买入价（纯数值，如 232.0，用于 Web 页面狙击点位显示） |
| `secondary_buy` | float | 否 | 🔵 二次买入价（纯数值，如 228.0） |
| `stop_loss` | float | 否 | 🛑 止损价（纯数值，如 220.0） |
| `take_profit` | float | 否 | 🎊 目标价（纯数值，如 245.0） |
| `analysis_summary` | string | 是 | 综合分析摘要（2-3 句话） |
| `key_points` | string | 否 | 关键看点（分号分隔） |
| `risk_warning` | string | 否 | 风险提示 |
| `buy_reason` | string | 否 | 买入理由 |
| `news_summary` | string | 否 | 新闻摘要 |
| `technical_analysis` | string | 否 | 技术面分析 |
| `ma_analysis` | string | 否 | 均线分析 |
| `volume_analysis` | string | 否 | 量价分析 |
| `pattern_analysis` | string | 否 | 形态分析 |
| `fundamental_analysis` | string | 否 | 基本面分析 |
| `sector_position` | string | 否 | 板块地位 |
| `company_highlights` | string | 否 | 公司亮点 |
| `market_sentiment` | string | 否 | 市场情绪 |
| `hot_topics` | string | 否 | 热门题材 |
| `short_term_outlook` | string | 否 | 短期展望 |
| `medium_term_outlook` | string | 否 | 中期展望 |
| `dashboard` | object | 否 | 原始 dashboard 数据（可选） |

## 存储与邮件通知（默认启用）

分析完成后**必须**执行 Step 3 调用 `save_analysis_result.py`，该脚本会自动完成：

1. **分析历史存储**：`db.save_analysis_history()` → 写入 `analysis_history` 表
2. **决策信号提取**：`extract_and_persist_from_analysis_result()` → 写入 `decision_signals` 表
3. **大盘指数回写**：`db.update_index_data_for_today()` → 写入 `index_daily` 表
4. **邮件通知**：`NotificationService.send(report, email_send_to_all=True)` → 发送邮件
5. **报告保存**：`notifier.save_report_to_file(report)` → 保存到 `reports/` 目录

```bash
# 单只股票
python3 scripts/save_analysis_result.py 603444 \
  -f /tmp/analysis_603444.json \
  --report /tmp/report_603444.md

# 批量（合并邮件）
python3 scripts/save_analysis_result.py batch -f /tmp/batch_results.json

# 不发邮件（仅存储）
python3 scripts/save_analysis_result.py 603444 -f /tmp/analysis_603444.json --no-email
```

- **邮件配置**：在 `.env` 中设置 `EMAIL_SENDER`、`EMAIL_PASSWORD`、`EMAIL_RECEIVERS`
- **批量分析**：`save_analysis_result.py batch` 会合并所有结果为一封汇总邮件
- **不要询问用户是否发送**，直接执行

## 支持的股票市场

| 市场 | 代码格式 | 示例 |
|------|---------|------|
| A股 | 6位数字 | `600519`, `000001`, `300750` |
| 港股 | hk + 5位数字 | `hk00700`, `hk09988` |
| 美股 | 股票代码 | `AAPL`, `TSLA`, `NVDA` |

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| 依赖缺失 | `pip install -r requirements.txt` |
| 数据源失败 | 脚本会自动降级使用可用数据源 (fail-open) |
| 新闻为空 | 检查 Tavily API Key 配额，或加 `--skip-news` 跳过 |
| 脚本超时 | 新闻搜索有 60s 超时保护，超时后跳过继续 |
| 股票代码错误 | A股6位数字，港股加 hk 前缀，美股用字母代码 |
| 邮件未收到 | 检查 `.env` 中 EMAIL_SENDER/EMAIL_PASSWORD/EMAIL_RECEIVERS 配置 |
| 存储失败 | 检查 DB 文件权限，`save_analysis_result.py` 会 fail-open 继续执行 |
| market_phase 缺失 | 非交易日或非交易时段正常，不影响分析 |
| context_pack 缺失 | 数据块不足时无法评估，不影响分析 |

## 与原方案的区别

| 维度 | 原方案（pipeline + 百炼） | 新方案（Qoder Native v3.0） |
|------|--------------------------|---------------------------|
| LLM 依赖 | 需要百炼/OpenAI API Key | 不需要，用 Qoder AI |
| 数据获取 | pipeline 内部获取 | 独立脚本 `fetch_stock_context.py` |
| 分析方式 | GeminiAnalyzer LLM 生成报告 | Qoder AI 直接分析 |
| 分析历史存储 | 自动入库 | 自动入库（`save_analysis_result.py`） |
| 决策信号提取 | 自动提取入库 | 自动提取入库（`save_analysis_result.py`） |
| 大盘指数回写 | 自动回写 | 自动回写（`fetch_stock_context.py` + `save_analysis_result.py`） |
| 新闻情报存DB | 自动存储 | 自动存储（`fetch_stock_context.py`） |
| 基本面快照存DB | 自动存储 | 自动存储（`fetch_stock_context.py`） |
| 市场阶段判断 | pipeline 内部 | 独立获取（`fetch_stock_context.py`） |
| 数据质量评估 | pipeline 内部 | 独立获取（`context_pack` 字段） |
| 持久化情报补充 | pipeline 内部 | 独立获取（`persisted_intelligence` 字段） |
| 报告保存 | 自动保存到 reports/ | 自动保存到 reports/ |
| 邮件通知 | 支持 | 支持（默认发送） |

## 相关资源

- 数据获取脚本：`scripts/fetch_stock_context.py`
- 结果存储脚本：`scripts/save_analysis_result.py`
- 详细参考文档：[REFERENCE.md](REFERENCE.md)
- 配置示例：`.env.example`
- 项目完整指南：`docs/full-guide.md`

## 版本信息

- Skill 版本: 3.0.0
- 更新日期: 2026-06-29
- 变更: 完整迁移原 pipeline 分析能力（市场阶段/大盘指数/数据质量评估/持久化情报/分析历史存储/决策信号提取），新增 3 步工作流（fetch → analyze → save），Qoder AI 输出 JSON 摘要 + Markdown 报告双格式
