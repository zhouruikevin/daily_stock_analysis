# Qoder 中使用 Stock Analysis Skill

## 快速开始

### 1. 首次使用 - 启动服务

在 Qoder 终端中执行：

```bash
cd /Users/eleme/Documents/ai/qoderwork/daily_stock_analysis
bash .qoder/skills/stock-analysis/scripts/manage_service.sh start
```

服务会在后台启动，大约需要 5-10 秒就绪。

### 2. 在 Qoder 对话中使用

直接在 Qoder 对话中请求分析股票：

```
分析 600519
帮我看看茅台的走势
分析 AAPL
```

Qoder 会自动调用 stock-analysis Skill 并返回分析结果。

### 3. 服务管理

```bash
# 查看服务状态
bash .qoder/skills/stock-analysis/scripts/manage_service.sh status

# 重启服务
bash .qoder/skills/stock-analysis/scripts/manage_service.sh restart

# 停止服务
bash .qoder/skills/stock-analysis/scripts/manage_service.sh stop
```

## 工作原理

1. **Skill 自动检测**：Qoder 会根据你的请求自动匹配 stock-analysis Skill
2. **服务检查**：Skill 会先检查 DSA API 服务是否运行
3. **自动启动**：如果服务未运行，会自动启动（需要 ~10 秒）
4. **执行分析**：调用 API 进行分析并返回结果

## 分析方式

Skill 会按以下优先级执行：

1. **Python Import**（最快，功能完整）
2. **HTTP API**（服务运行中时）
3. **CLI 命令**（兜底方案）

## 常见问题

### Q: 服务启动失败？
A: 检查日志 `/tmp/dsa_server.log`，常见原因：
- 缺少依赖：运行 `pip install -r requirements.txt`
- 端口占用：修改 `.env` 中的 `SERVER_PORT`
- 配置错误：检查 `.env` 文件

### Q: 分析很慢？
A: 正常情况，单次分析约 1-3 分钟，取决于：
- LLM API 响应速度
- 数据源获取速度
- 是否启用搜索功能

### Q: 如何在后台保持服务运行？
A: 服务已通过 nohup 后台运行，关闭终端不影响。重启电脑后需要重新启动。

### Q: 分析结果在哪里查看？
A: 
- 终端直接显示
- 报告保存在 `reports/` 目录
- 日志保存在 `logs/` 目录

## 环境变量

确保 `.env` 文件配置了必要的参数：

```bash
# 必需
LITELLM_MODEL=gpt-4  # 或其他模型
LITELLM_API_KEY=your_key

# 可选（数据源）
TUSHARE_TOKEN=your_token
LONGBRIDGE_APP_KEY=your_key
```

## 技能文件位置

- **Skill 配置**：`.qoder/skills/stock-analysis/SKILL.md`
- **服务管理脚本**：`.qoder/skills/stock-analysis/scripts/manage_service.sh`
- **依赖检查脚本**：`scripts/check_deps.py`
- **示例文档**：`.qoder/skills/stock-analysis/EXAMPLES.md`
- **参考文档**：`.qoder/skills/stock-analysis/REFERENCE.md`
