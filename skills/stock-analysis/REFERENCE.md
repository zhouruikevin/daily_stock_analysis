# Stock Analysis Skill - API 参考文档

本文档提供 Stock Analysis Skill 的详细 API 说明。

## 核心函数

### 1. analyze_stock()

分析单只股票。

**函数签名**:
```python
def analyze_stock(
    stock_code: str,
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None
) -> Optional[AnalysisResult]
```

**参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| stock_code | str | ✅ | - | 股票代码 (如 `600519`, `hk00700`, `AAPL`) |
| config | Config | ❌ | None | 配置对象,默认使用 `.env` 配置 |
| full_report | bool | ❌ | False | 是否生成完整报告 (包含基本面、新闻等) |
| notifier | NotificationService | ❌ | None | 通知服务,提供时自动发送通知 |

**返回值**:
- `AnalysisResult` 对象: 分析成功
- `None`: 分析失败

**示例**:

```python
from analyzer_service import analyze_stock

# 基础用法
result = analyze_stock("600519")

# 完整报告
result = analyze_stock("600519", full_report=True)

# 自定义配置
from src.config import get_config
config = get_config()
config.agent_skills = ["ma_cross"]  # 指定策略
result = analyze_stock("600519", config=config)
```

---

### 2. analyze_stocks()

批量分析多只股票。

**函数签名**:
```python
def analyze_stocks(
    stock_codes: List[str],
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None
) -> List[AnalysisResult]
```

**参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| stock_codes | List[str] | ✅ | - | 股票代码列表 |
| config | Config | ❌ | None | 配置对象 |
| full_report | bool | ❌ | False | 是否为每只股票生成完整报告 |
| notifier | NotificationService | ❌ | None | 通知服务 |

**返回值**:
- `List[AnalysisResult]`: 分析结果列表 (仅包含成功的股票)

**示例**:

```python
from analyzer_service import analyze_stocks

# 批量分析
results = analyze_stocks(["600519", "000001", "AAPL"])

# 处理结果
for result in results:
    print(f"{result.name}: {result.operation_advice}")
```

**注意事项**:
- 串行执行,每只股票约 10-30 秒
- 单只股票失败不影响其他股票
- 大量股票建议使用异步 API

---

### 3. perform_market_review()

执行大盘复盘。

**函数签名**:
```python
def perform_market_review(
    config: Config = None,
    notifier: Optional[NotificationService] = None
) -> Optional[str]
```

**参数**:

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| config | Config | ❌ | None | 配置对象 |
| notifier | NotificationService | ❌ | None | 通知服务 |

**返回值**:
- `str`: 复盘报告内容 (Markdown 格式)
- `None`: 复盘失败

**示例**:

```python
from analyzer_service import perform_market_review

# A股复盘
report = perform_market_review()

# 保存到文件
if report:
    with open("market_review.md", "w") as f:
        f.write(report)
```

---

## AnalysisResult 对象结构

### 顶层字段

```python
result = AnalysisResult(
    code="600519",                    # 股票代码
    name="宝胜股份",                   # 股票名称
    sentiment_score=75.5,             # 情绪得分 (0-100)
    operation_advice="买入",           # 操作建议
    confidence_level="高",             # 置信度
    dashboard={...},                  # 决策仪表盘 (详见下方)
    full_report="...",                # 完整报告文本 (full_report=True 时)
    timestamp="2026-04-16 15:30:00"   # 分析时间
)
```

### dashboard 结构

```python
result.dashboard = {
    "core_conclusion": {
        "one_sentence": "短期多头趋势明显,建议逢低介入",
        "signal_type": "buy",              # buy | hold | sell
        "position_advice": "建议仓位 30-50%"
    },
    
    "data_perspective": {
        "trend_status": "多头排列",
        "price_position": "MA5 上方",
        "volume_analysis": "放量突破",
        "chip_structure": "筹码集中"
    },
    
    "intelligence": {
        "news_summary": "公司发布业绩预告,预计净利润增长 50%",
        "risk_alerts": ["股东减持计划", "行业政策风险"],
        "positive_catalysts": ["业绩超预期", "机构增持"]
    },
    
    "battle_plan": {
        "sniper_points": {
            "ideal_buy": 10.5,           # 理想买入价
            "secondary_buy": 10.2,       # 次要买入价
            "stop_loss": 9.8,            # 止损价
            "take_profit": 12.0          # 目标价
        },
        "position_strategy": "分批建仓,首次 30%,回调加仓",
        "risk_control": [
            "跌破 MA20 止损",
            "乖离率 >5% 不追高",
            "放量下跌减仓"
        ]
    }
}
```

### 访问示例

```python
# 核心结论
print(result.dashboard["core_conclusion"]["one_sentence"])

# 买卖点位
sniper = result.dashboard["battle_plan"]["sniper_points"]
print(f"买入: {sniper['ideal_buy']}, 止损: {sniper['stop_loss']}")

# 风险警报
risks = result.dashboard["intelligence"]["risk_alerts"]
for risk in risks:
    print(f"⚠️ {risk}")
```

---

## Config 对象

### 获取配置

```python
from src.config import get_config, Config

# 使用全局单例 (从 .env 加载)
config = get_config()

# 手动创建
config = Config(
    litellm_model="gpt-4",
    litellm_api_key="sk-xxx",
    # ... 其他配置
)
```

### 常用配置项

| 配置项 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| LITELLM_MODEL | str | LLM 模型 | `gpt-4`, `deepseek-chat` |
| LITELLM_API_KEY | str | LLM API Key | `sk-xxx` |
| LITELLM_API_BASE | str | API 基础 URL | `https://api.openai.com/v1` |
| agent_skills | List[str] | 启用的策略技能 | `["ma_cross", "volume_breakout"]` |
| news_max_days | int | 新闻最大时效(天) | `3` |
| report_language | str | 报告语言 | `zh`, `en` |

### 动态修改配置

```python
config = get_config()

# 修改模型
config.litellm_model = "claude-3-opus"

# 指定策略
config.agent_skills = ["ma_cross"]

# 使用修改后的配置
result = analyze_stock("600519", config=config)
```

---

## NotificationService

### 基础用法

```python
from src.notification import NotificationService

notifier = NotificationService()
result = analyze_stock("600519", notifier=notifier)
```

### 配置通知渠道

在 `.env` 中配置:

```bash
# 企业微信
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

# 飞书
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx

# Telegram
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx

# 邮件
SMTP_SERVER=smtp.gmail.com
SMTP_USER=your@email.com
SMTP_PASSWORD=xxx
```

---

## HTTP API 端点

### 1. 触发分析

**POST** `/api/v1/analysis/analyze`

**请求体**:
```json
{
  "stock_codes": ["600519", "000001"],
  "full_report": false,
  "notify": true
}
```

**响应**:
```json
{
  "task_id": "abc123",
  "status": "pending",
  "stock_codes": ["600519", "000001"]
}
```

### 2. 查询任务状态

**GET** `/api/v1/analysis/status/{task_id}`

**响应**:
```json
{
  "task_id": "abc123",
  "status": "completed",  // pending | running | completed | failed
  "results": [
    {
      "code": "600519",
      "name": "宝胜股份",
      "sentiment_score": 75.5,
      "operation_advice": "买入"
    }
  ],
  "created_at": "2026-04-16T15:30:00",
  "completed_at": "2026-04-16T15:30:25"
}
```

### 3. 查询历史记录

**GET** `/api/v1/history`

**查询参数**:
- `code`: 股票代码 (可选)
- `limit`: 返回条数 (默认 20)
- `offset`: 偏移量 (默认 0)

**响应**:
```json
{
  "total": 100,
  "items": [
    {
      "id": 1,
      "code": "600519",
      "name": "宝胜股份",
      "analysis_date": "2026-04-16",
      "operation_advice": "买入",
      "sentiment_score": 75.5
    }
  ]
}
```

---

## CLI 命令

### main.py 参数

```bash
python main.py [OPTIONS]
```

**常用参数**:

| 参数 | 说明 | 示例 |
|------|------|------|
| `--stocks CODES` | 股票代码 (逗号分隔) | `--stocks 600519,000001` |
| `--market-review` | 执行大盘复盘 | `--market-review` |
| `--full-report` | 生成完整报告 | `--full-report` |
| `--dry-run` | 仅获取数据,不分析 | `--dry-run` |
| `--debug` | 调试模式 | `--debug` |
| `--schedule` | 定时运行模式 | `--schedule` |
| `--serve` | 启动 API 服务 | `--serve` |

**示例**:

```bash
# 分析单只股票
python main.py --stocks 600519

# 分析多只股票 + 完整报告
python main.py --stocks 600519,000001 --full-report

# 大盘复盘
python main.py --market-review

# 快速测试 (不发送通知)
python main.py --stocks 600519 --dry-run

# 启动 API 服务
python main.py --serve
```

---

## 错误处理

### 常见异常

```python
from analyzer_service import analyze_stock

try:
    result = analyze_stock("INVALID")
    if result is None:
        print("分析失败,请检查股票代码")
except Exception as e:
    print(f"分析出错: {e}")
```

### 错误码 (API 模式)

| HTTP 状态码 | 说明 | 解决方案 |
|------------|------|---------|
| 400 | 请求参数错误 | 检查股票代码格式 |
| 401 | 未认证 | 提供有效的 API Token |
| 429 | 请求频率过高 | 降低请求频率 |
| 500 | 服务器内部错误 | 查看日志,稍后重试 |

---

## 性能优化

### 1. 使用简要报告

```python
# 快速模式 (推荐批量分析)
result = analyze_stock("600519", full_report=False)  # ~10-15秒

# 完整模式 (详细分析)
result = analyze_stock("600519", full_report=True)   # ~20-30秒
```

### 2. 并行分析 (API 模式)

```python
import asyncio
import aiohttp

async def analyze_parallel(stocks):
    async with aiohttp.ClientSession() as session:
        tasks = []
        for code in stocks:
            task = session.post(
                "http://localhost:8000/api/v1/analysis/analyze",
                json={"stock_codes": [code]}
            )
            tasks.append(task)
        
        responses = await asyncio.gather(*tasks)
        return [await r.json() for r in responses]
```

### 3. 缓存配置

```python
# 启用数据缓存 (减少重复请求)
config = get_config()
config.enable_cache = True

# 缓存目录
cache_dir = Path("data/cache")
cache_dir.mkdir(exist_ok=True)
```

---

## 高级功能

### 1. 自定义策略

```python
from src.config import get_config

config = get_config()

# 启用特定策略
config.agent_skills = [
    "ma_cross",           # 均线金叉
    "volume_breakout",    # 放量突破
    "bottom_volume"       # 底部放量
]

result = analyze_stock("600519", config=config)
```

### 2. 多语言支持

```python
config = get_config()
config.report_language = "en"  # 英文报告

result = analyze_stock("AAPL", config=config)
```

### 3. 回测集成

```python
# 查询历史分析准确率
from src.repositories import AnalysisHistoryRepository

repo = AnalysisHistoryRepository()
history = repo.get_backtest_summary("600519")
print(f"5日窗口准确率: {history.accuracy_5d}%")
```

---

## 最佳实践

### 1. 分析前检查

```python
# 运行依赖检查
import subprocess
result = subprocess.run(
    ["python", "skills/stock-analysis/scripts/check_deps.py"],
    capture_output=True,
    text=True
)
print(result.stdout)
```

### 2. 错误重试

```python
import time
from analyzer_service import analyze_stock

def analyze_with_retry(stock_code, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = analyze_stock(stock_code)
            if result:
                return result
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            time.sleep(5)
    return None
```

### 3. 结果持久化

```python
import json
from datetime import datetime

result = analyze_stock("600519")

# 保存分析结果
output = {
    "code": result.code,
    "name": result.name,
    "sentiment_score": result.sentiment_score,
    "operation_advice": result.operation_advice,
    "timestamp": datetime.now().isoformat()
}

with open(f"analysis_{result.code}_{datetime.now().strftime('%Y%m%d')}.json", "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
```

---

## 相关资源

- 快速入门: [SKILL.md](SKILL.md)
- 多平台部署: [EXAMPLES.md](EXAMPLES.md)
- 项目完整指南: `docs/full-guide.md`
- 配置示例: `.env.example`
- API 端点文档: `docs/bot/`
