# 多平台部署示例

本文档说明如何将 Stock Analysis Skill 部署到不同平台。

## 目录结构

```
skills/stock-analysis/          # Skill 源文件 (版本控制)
├── SKILL.md                    # 主技能定义
├── REFERENCE.md                # API 文档
├── EXAMPLES.md                 # 本文件
└── scripts/
    └── check_deps.py           # 依赖检查
```

## 部署方式概览

| 平台 | 部署位置 | 部署方式 | 更新方式 |
|------|---------|---------|---------|
| Qoder IDE (项目级) | `.qoder/skills/stock-analysis/` | 符号链接或复制 | 自动同步(符号链接) / 手动复制 |
| Qoder IDE (个人全局) | `~/.qoder/skills/stock-analysis/` | 符号链接或复制 | 自动同步(符号链接) / 手动复制 |
| Claude Desktop | `.claude/skills/stock-analysis/` | 复制 | 手动复制 |
| 其他 Agent 平台 | 平台指定的 skills 目录 | 复制 | 手动复制 |
| 独立分享 | tar.gz / zip 压缩包 | 打包分发 | 重新打包 |

---

## 1. Qoder IDE - 项目级部署

### 方式 A: 符号链接 (推荐)

**macOS / Linux:**
```bash
cd /path/to/daily_stock_analysis
ln -s $(pwd)/skills/stock-analysis .qoder/skills/stock-analysis
```

**Windows (PowerShell):**
```powershell
cd C:\path\to\daily_stock_analysis
New-Item -ItemType SymbolicLink -Path ".qoder\skills\stock-analysis" -Target "$(Get-Location)\skills\stock-analysis"
```

**优点**: 
- 源文件更新后自动同步
- 只需维护一份代码
- Git 可跟踪符号链接

**验证**:
```bash
ls -la .qoder/skills/stock-analysis/SKILL.md
# 应该显示指向 skills/stock-analysis/SKILL.md 的链接
```

### 方式 B: 直接复制

```bash
cp -r skills/stock-analysis .qoder/skills/
```

**优点**: 
- 兼容所有文件系统
- 不依赖符号链接支持

**缺点**: 
- 源文件更新后需要手动重新复制

---

## 2. Qoder IDE - 个人全局部署

让 Skill 在所有 Qoder 项目中可用:

### macOS / Linux:
```bash
# 创建符号链接
ln -s /path/to/daily_stock_analysis/skills/stock-analysis ~/.qoder/skills/stock-analysis

# 或者复制
cp -r /path/to/daily_stock_analysis/skills/stock-analysis ~/.qoder/skills/
```

### Windows (PowerShell):
```powershell
# 符号链接
New-Item -ItemType SymbolicLink -Path "$env:USERPROFILE\.qoder\skills\stock-analysis" -Target "C:\path\to\daily_stock_analysis\skills\stock-analysis"

# 或者复制
Copy-Item -Recurse "C:\path\to\daily_stock_analysis\skills\stock-analysis" "$env:USERPROFILE\.qoder\skills\"
```

**验证**:
在任意 Qoder 项目中输入 "分析 600519",应该能触发 Skill。

---

## 3. Claude Desktop / 其他 Claude Agent

### 部署到 Claude:

```bash
# 复制 Skill 到 Claude skills 目录
cp -r skills/stock-analysis ~/.claude/skills/

# 验证
ls ~/.claude/skills/stock-analysis/SKILL.md
```

### 在 Claude 中使用:

直接在对话中输入:
- "帮我分析 600519"
- "AAPL 走势如何"
- "今天大盘怎么样"

Claude 会自动识别并调用 Stock Analysis Skill。

---

## 4. 其他 AI 平台

### 通用部署步骤:

1. **找到平台的 skills 目录位置**
   - 查阅平台文档
   - 通常位于 `~/.平台名/skills/` 或项目根目录的 `.平台名/skills/`

2. **复制 Skill 文件**
   ```bash
   cp -r skills/stock-analysis /path/to/platform/skills/
   ```

3. **验证部署**
   - 检查 SKILL.md 是否存在
   - 运行依赖检查: `python scripts/check_deps.py`

4. **重启平台服务** (如果需要)

---

## 5. 打包分享

### 创建压缩包:

**tar.gz (macOS/Linux):**
```bash
cd /path/to/daily_stock_analysis
tar -czf stock-analysis-skill.tar.gz skills/stock-analysis/
```

**zip (跨平台):**
```bash
cd /path/to/daily_stock_analysis
zip -r stock-analysis-skill.zip skills/stock-analysis/
```

### 接收方部署:

```bash
# 解压
tar -xzf stock-analysis-skill.tar.gz
# 或
unzip stock-analysis-skill.zip

# 部署到目标平台
cp -r skills/stock-analysis ~/.qoder/skills/  # Qoder
# 或
cp -r skills/stock-analysis ~/.claude/skills/  # Claude
```

### 分享前检查清单:

- [ ] 删除 `__pycache__/` 目录
- [ ] 删除 `.env` 文件 (如果意外包含)
- [ ] 确认 SKILL.md 版本信息已更新
- [ ] 测试解压后能否正常运行

---

## 6. 版本管理与更新

### 版本号规范

在 `SKILL.md` 的 frontmatter 中维护版本:

```yaml
---
name: stock-analysis
description: ...
version: 1.0.0
---
```

### 更新策略

**小更新** (文档修正、Bug 修复):
- 修改 `PATCH` 版本号 (1.0.0 → 1.0.1)
- 使用符号链接的用户自动获得更新

**功能更新** (新增能力、API 变更):
- 修改 `MINOR` 版本号 (1.0.0 → 1.1.0)
- 在 REFERENCE.md 中说明变更

**破坏性更新** (不兼容的 API 变更):
- 修改 `MAJOR` 版本号 (1.0.0 → 2.0.0)
- 提供迁移指南

### 同步更新

**使用符号链接**:
```bash
# 源文件更新后,符号链接自动生效
# 无需额外操作
```

**使用复制**:
```bash
# 重新复制覆盖
rm -rf ~/.qoder/skills/stock-analysis
cp -r skills/stock-analysis ~/.qoder/skills/
```

---

## 7. 故障排查

### 问题: Skill 未被触发

**检查清单**:
1. SKILL.md 的 `description` 是否包含触发关键词
2. Skill 是否部署到正确目录
3. 平台是否需要重启才能识别新 Skill

**调试命令**:
```bash
# Qoder IDE
ls -la .qoder/skills/stock-analysis/SKILL.md

# Claude
ls -la ~/.claude/skills/stock-analysis/SKILL.md
```

### 问题: 依赖检查失败

```bash
# 运行诊断
python skills/stock-analysis/scripts/check_deps.py

# 根据提示修复
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填写 LITELLM_MODEL 和 LITELLM_API_KEY
```

### 问题: 符号链接无效

**macOS/Linux**:
```bash
# 检查链接目标是否存在
ls -la .qoder/skills/stock-analysis

# 重新创建链接
rm .qoder/skills/stock-analysis
ln -s $(pwd)/skills/stock-analysis .qoder/skills/stock-analysis
```

**Windows**:
```powershell
# 需要管理员权限创建符号链接
Remove-Item .qoder\skills\stock-analysis
New-Item -ItemType SymbolicLink -Path ".qoder\skills\stock-analysis" -Target "$(Get-Location)\skills\stock-analysis"
```

---

## 8. 最佳实践

### 推荐部署方式

| 场景 | 推荐方式 | 原因 |
|------|---------|------|
| 本地开发 | 符号链接 | 自动同步,便于调试 |
| 团队共享 | 复制 + Git 跟踪 | 兼容性好,避免链接问题 |
| 生产环境 | 复制 | 稳定性优先 |
| 个人全局使用 | 符号链接 | 一次部署,多处使用 |

### 安全注意事项

- ⚠️ **永远不要** 将 `.env` 文件包含在分享包中
- ⚠️ **永远不要** 提交包含 API Key 的配置文件到 Git
- ✅ 使用 `.gitignore` 排除敏感文件
- ✅ 分享前运行 `check_deps.py` 验证环境

### 维护建议

- 定期更新 `SKILL.md` 中的版本号和日期
- 重大变更同步更新 `CHANGELOG.md`
- 保持 `REFERENCE.md` 与实际 API 一致
- 测试多平台部署至少每季度一次

---

## 9. 快速参考卡片

复制以下内容到笔记中便于快速查阅:

```
Stock Analysis Skill 部署速查

1. Qoder 项目级 (符号链接):
   ln -s $(pwd)/skills/stock-analysis .qoder/skills/stock-analysis

2. Qoder 全局 (符号链接):
   ln -s $(pwd)/skills/stock-analysis ~/.qoder/skills/stock-analysis

3. Claude:
   cp -r skills/stock-analysis ~/.claude/skills/

4. 打包分享:
   tar -czf stock-analysis-skill.tar.gz skills/stock-analysis/

5. 依赖检查:
   python skills/stock-analysis/scripts/check_deps.py

6. 测试触发:
   在 IDE 中输入: "分析 600519"
```
