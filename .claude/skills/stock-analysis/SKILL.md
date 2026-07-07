---
name: stock-analysis
description: >
  用 Claude(claude-opus-4-8) 经项目原分析管道分析 A股/港股/美股并发合并邮件。
  当用户要分析股票、分析关注列表/自选股、看走势、要交易信号，或提到股票代码
  （如 600519、hk00700、AAPL）时调用。自动启动 LLM 代理、实时反馈每只进度。
---

# Stock Analysis Skill（Claude 大脑 + 原管道）

用 **Claude(claude-opus-4-8)** 作为分析大脑，**沿用项目原分析管道**（`analyze_stock`）产出报告——
舆情/业绩预期/风险/利好、当日行情、数据透视、作战计划、财务摘要、关联板块全部由原管道原生生成，
与百炼版报告结构完全一致。分析结果自动存库（分析历史/决策信号/指数），最后发一封合并邮件。

## 执行方式（Claude 按此操作）

**唯一入口脚本**：`scripts/analyze_with_claude.sh`（自动拉起 LLM 代理，无需手动启动服务）。

### 1. 确定分析范围

- 用户说“分析关注列表 / 自选股 / STOCK_LIST” 或未指定具体代码 → **不带参数**（脚本读 `.env` 的 `STOCK_LIST`）。
- 用户给了具体代码 → 作为第一个参数，逗号分隔，如 `600519,603444`。
- 用户说“先别发邮件 / 只看不发 / 联调” → 前面加 `NO_EMAIL=1`。

### 2. 后台启动分析并实时监控进度（关键：给用户反馈）

**必须后台运行 + 用 Monitor 汇报进度**，不要前台干等（19 只约 12-15 分钟）。

用 Bash `run_in_background: true` 启动，输出重定向到日志：

```bash
bash scripts/analyze_with_claude.sh > /tmp/stock_analysis_run.log 2>&1
```

（分析指定股票：`bash scripts/analyze_with_claude.sh 600519,603444 > /tmp/stock_analysis_run.log 2>&1`）

然后用 **Monitor 工具**盯住进度行，逐条转达给用户：

```
tail -f /tmp/stock_analysis_run.log | grep --line-buffered -E "▶|\[进度|■|📧|失败|异常|不可用"
```

进度行格式：
- `[claude] ▶ 开始分析 19 只 ...` —— 开始
- `[进度 3/19] 603444 吉比特 ✅ 评分65 持有 (累计128s)` —— 每只完成
- `[claude] ■ 分析完成 用时...成功 N/19` —— 全部完成
- `[claude] 📧 合并邮件已发送（N只）+ 报告已存 reports/` —— 邮件已发

### 3. 汇报结果

分析完成后向用户汇报：成功/失败数量、买入/持有/卖出分布、邮件是否发送、报告路径（`reports/`）。
如有 FAIL 的股票，如实列出。

## ⛔ 执行约束

1. **不要询问配置**：数据源、邮件、模型都已就绪；直接执行。
2. **不要手动启代理**：脚本会自动检测并拉起 `claude_llm_proxy.py`。
3. **必须后台跑 + Monitor 汇报进度**：让用户随时看到“跑到第几只”，不要闷头等。
4. **默认发合并邮件**，不额外询问；用户明确说不发才加 `NO_EMAIL=1`。
5. **只用 claude-opus-4-8**（账号唯一可用模型）。

## 常用命令速查

```bash
# 关注列表 + 发邮件（最常用）
bash scripts/analyze_with_claude.sh

# 指定股票 + 发邮件
bash scripts/analyze_with_claude.sh 600519,603444,AAPL

# 只分析存库不发邮件（联调）
NO_EMAIL=1 bash scripts/analyze_with_claude.sh 603444

# 提高并发（默认 4）
MAX_WORKERS=5 bash scripts/analyze_with_claude.sh
```

## 支持的市场

| 市场 | 代码格式 | 示例 |
|------|---------|------|
| A股 | 6位数字 | 600519, 000001, 300750 |
| 港股 | hk+5位数字 | hk00700, hk09988 |
| 美股 | 字母代码 | AAPL, TSLA, NVDA |

## 关键文件

- 入口脚本：`scripts/analyze_with_claude.sh`（自动拉代理 + 逐只进度 + 合并邮件）
- LLM 代理：`scripts/claude_llm_proxy.py`（OpenAI 兼容，转发到本地 claude CLI）
- 关注列表：`.env` 的 `STOCK_LIST`
- 邮件配置：`.env` 的 `EMAIL_SENDER / EMAIL_PASSWORD / EMAIL_RECEIVERS`
- 分析管道：`src/services/analyzer_service.py` → `src/core/pipeline.py`（原管道，未改动）

## 故障排查

| 现象 | 处理 |
|------|------|
| 代理启动失败 | 看 `/tmp/claude_proxy.log`；确认 `claude` CLI 已登录（`claude -p` 能返回） |
| 某只 FAIL | 网关限流或数据缺失，脚本 fail-open 继续其余；可单独重跑该只 |
| 模型报“需要授权/不存在” | 仅 `claude-opus-4-8` 可用；其它需网关开授权 |
| 邮件未收到 | 检查 `.env` EMAIL_* 配置；`is_available()` 为假会跳过发送 |
| 分析很慢 | opus 单只约 100-130s；提高 `MAX_WORKERS`（注意网关限流） |
