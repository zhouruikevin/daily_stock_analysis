---
name: stock-analysis
description: >
  Analyze A-share, Hong Kong, or US stocks using AI-powered technical analysis.
  Use when the user asks to analyze stocks, check stock trends, get trading signals,
  perform market review, or mentions stock codes like 600519, hk00700, AAPL.
  Supports single stock, multiple stocks, and market overview.
  Works with Qoder IDE, Claude, and other AI platforms.
---

# Stock Analysis Skill

跨平台股票分析技能,支持 A股/港股/美股智能分析。

## ⛔ 执行约束（必须遵守）

1. **不要向用户询问任何配置信息**。所有配置（LLM 模型、API Key、数据源等）已预置在项目 `.env` 文件中，直接使用即可。
2. **不要提示"缺少核心代码文件"**。本 Skill 是项目的组成部分，代码就在项目目录中，Skill 目录只存放 Skill 描述文件。
3. **不要询问"使用哪个 LLM 提供商和模型"**。LLM 配置已在 `.env` 中设定（当前为 `openai/glm-4.6`），无需用户干预。
4. **分析时间较长时（超过 60 秒），每隔约 1 分钟向用户反馈一次进度**，不要沉默等待。
5. **直接执行分析，不要问"是否需要启动服务"之类的确认**。如果服务未运行，自动启动即可。
6. **使用 Skill 分析股票时默认不进行大盘复盘**。只分析用户指定的股票，不触发 `--market-review`，除非用户明确要求。

## 项目信息

- **项目路径**：`/Users/eleme/Documents/ai/qoderwork/daily_stock_analysis`
- **LLM 配置**：已在项目 `.env` 中配置（`LITELLM_MODEL=openai/glm-4.6`）
- **数据源**：AkShare（免费默认）+ 可选 Tushare/Longbridge
- **Skill 目录只是文档**：`.qoder/skills/stock-analysis/` 仅存放 Skill 描述，核心代码在 `src/`、`data_provider/` 等目录

## 快速开始

### 0. 确保服务运行（首次必做）

**自动启动服务**：
```bash
# 使用管理脚本（推荐）
bash scripts/manage_service.sh start

# 或手动启动
python main.py --serve-only
```

**服务管理**：
```bash
bash scripts/manage_service.sh status   # 查看状态
bash scripts/manage_service.sh stop     # 停止服务
bash scripts/manage_service.sh restart  # 重启服务
```

**服务地址**：`http://localhost:8000`  
**日志位置**：`/tmp/dsa_server.log`

**⚠️ 重要：Skill 执行分析时默认跳过大盘复盘**
- 用户要求分析股票时，只分析指定的股票
- 只有用户明确要求「大盘复盘」、「市场综述」、「market review」时，才执行 `python main.py --market-review`
- 这样可以节省 2-3 分钟分析时间

### 执行优先级

1. **优先使用 Python import** (最快,功能完整)
2. **降级到 API** (如果依赖缺失但服务运行中)
3. **最后使用 CLI** (兜底方案)

运行前执行依赖检查:
```bash
python scripts/check_deps.py
```

### 方式 A: Python Import (推荐)

```python
from analyzer_service import analyze_stock, analyze_stocks, perform_market_review

# 单只股票分析
result = analyze_stock("600519", full_report=False)
if result:
    print(f"股票: {result.name} ({result.code})")
    print(f"核心结论: {result.dashboard['core_conclusion']['one_sentence']}")
    print(f"操作建议: {result.operation_advice}")
    print(f"情绪得分: {result.sentiment_score}")

# 多只股票批量分析
results = analyze_stocks(["600519", "000001", "AAPL"])

# 大盘复盘
report = perform_market_review()
if report:
    print(report)
```

### 方式 B: HTTP API

```python
import requests

# 单只股票
response = requests.post(
    "http://localhost:8000/api/v1/analysis/analyze",
    json={"stock_codes": ["600519"], "full_report": False}
)
result = response.json()

# 查询任务状态 (异步分析)
status = requests.get("http://localhost:8000/api/v1/analysis/status/{task_id}")
```

### 方式 C: CLI 命令

```bash
# 单只股票（默认不进行大盘复盘）
python main.py --stocks 600519 --no-market-review

# 多只股票（默认不进行大盘复盘）
python main.py --stocks 600519,000001,AAPL --no-market-review

# 大盘复盘（仅当用户明确要求时执行）
python main.py --market-review
```

## 输出格式

分析返回 `AnalysisResult` 对象,关键结构:

```python
result.dashboard = {
    "core_conclusion": {
        "one_sentence": "一句话核心结论",
        "signal_type": "buy|hold|sell",
        "position_advice": "仓位建议"
    },
    "battle_plan": {
        "sniper_points": {
            "ideal_buy": 10.5,      # 理想买入价
            "secondary_buy": 10.2,  # 次要买入价
            "stop_loss": 9.8,       # 止损价
            "take_profit": 12.0     # 目标价
        }
    }
}

# 其他关键字段
result.sentiment_score      # 情绪得分 0-100
result.operation_advice     # 操作建议
result.confidence_level     # 置信度
```

**标准展示格式**:
```
📊 [股票名称] [代码]
💡 核心结论: [一句话]
🎯 狙击点: 买入 ¥XX | 止损 ¥XX | 目标 ¥XX
📈 情绪得分: XX/100
💼 操作建议: [买入/持有/卖出]
```

## 支持的股票市场

| 市场 | 代码格式 | 示例 |
|------|---------|------|
| A股 | 6位数字 | `600519`, `000001`, `300750` |
| 港股 | hk + 5位数字 | `hk00700`, `hk09988` |
| 美股 | 股票代码 | `AAPL`, `TSLA`, `NVDA` |
| 美股指数 | 指数代码 | `SPX`, `DJI`, `IXIC` |

## 配置要求

### 必须配置
- `LITELLM_MODEL`: LLM 模型名称 (如 `gpt-4`, `deepseek-chat`)
- `LITELLM_API_KEY`: LLM API Key

### 可选配置 (数据源)
- `TUSHARE_TOKEN`: Tushare 数据源 (A股)
- `LONGBRIDGE_APP_KEY`: Longbridge 数据源 (港股/美股)
- AkShare: 免费,无需配置 (默认数据源)

配置文件位置: `.env` (复制 `.env.example` 并填写)

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| 依赖缺失 | `pip install -r requirements.txt` |
| LLM 未配置 | 在 `.env` 中设置 `LITELLM_MODEL` 和 `LITELLM_API_KEY` |
| 数据源失败 | 分析会继续使用可用数据源 (fail-open 设计) |
| API 服务未运行 | 使用 Python import 模式或执行 `python server.py` 启动 |
| 超时 | 单只股票通常 10-30 秒,批量分析建议使用异步模式 |
| 股票代码错误 | 检查格式:A股6位数字,港股加 hk 前缀,美股用字母代码 |

## 高级用法

### 选择分析策略

```python
from src.config import get_config

config = get_config()
config.agent_skills = ["ma_cross", "volume_breakout"]  # 指定策略

result = analyze_stock("600519", config=config)
```

### 完整报告 vs 简要报告

```python
# 简要报告 (快速,适合批量)
result = analyze_stock("600519", full_report=False)

# 完整报告 (详细,包含基本面、新闻等)
result = analyze_stock("600519", full_report=True)
```

### 自定义通知

**重要**: 默认情况下分析不会发送邮件,需要手动传入 `notifier` 参数。

#### 单只股票通知

```python
from analyzer_service import analyze_stock
from src.notification import NotificationService

# 创建通知服务 (从 .env 读取邮件配置)
notifier = NotificationService()

# 分析并发送邮件
result = analyze_stock("600519", notifier=notifier)
```

#### 批量分析合并通知

批量分析时,默认会将所有股票的分析结果合并为一封汇总邮件发送:

```python
from analyzer_service import analyze_stocks
from src.notification import NotificationService

notifier = NotificationService()

# 默认行为: 合并为一封汇总邮件
results = analyze_stocks(["600519", "000001"], notifier=notifier)

# 禁用合并: 每只股票单独发送一封邮件
results = analyze_stocks(["600519", "000001"], notifier=notifier, merge_notification=False)
```

**参数说明**:
- `merge_notification=True` (默认): 所有股票分析完成后,合并为一封汇总邮件发送
- `merge_notification=False`: 每只股票分析完成后立即发送邮件

**邮件配置要求** (在 `.env` 中配置):
```bash
EMAIL_SENDER=your_email@example.com      # 发件人邮箱
EMAIL_PASSWORD=your_app_password         # 邮箱授权码
EMAIL_RECEIVERS=receiver@example.com     # 收件人邮箱
```

支持的邮件服务:
- 163邮箱 (推荐,免费稳定)
- QQ邮箱
- Gmail (需要开启两步验证)
- 企业邮箱 (QQ企业、阿里企业等)

**注意**: 如果不传入 `notifier` 参数,分析仍会正常进行,只是不会发送邮件通知。

## 相关资源

- 详细 API 文档: [REFERENCE.md](REFERENCE.md)
- 多平台部署示例: [EXAMPLES.md](EXAMPLES.md)
- 项目完整指南: `docs/full-guide.md`
- 配置示例: `.env.example`

## 版本信息

- Skill 版本: 1.0.0
- 最低项目版本: 与当前仓库版本兼容
- 更新日期: 2026-04-16
