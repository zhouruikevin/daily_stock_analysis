#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
依赖检查脚本 - 验证股票分析 Skill 运行环境

Usage:
    python scripts/check_deps.py

Exit codes:
    0 - 所有依赖正常
    1 - 发现依赖问题
"""

import sys
from pathlib import Path


def check_python_version():
    """检查 Python 版本 >= 3.10"""
    if sys.version_info < (3, 10):
        return False, f"Python 3.10+ required, found {sys.version_info.major}.{sys.version_info.minor}"
    return True, f"Python {sys.version_info.major}.{sys.version_info.minor} OK"


def check_core_modules():
    """检查核心模块是否可导入"""
    import sys
    from pathlib import Path
    
    issues = []
    
    # 添加项目根目录到 Python 路径
    # scripts/check_deps.py -> skills/stock-analysis/scripts/
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent.parent
    
    # 确保项目根目录在 sys.path 中
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)
    
    # 检查 analyzer_service
    try:
        from analyzer_service import analyze_stock, analyze_stocks, perform_market_review
        core_ok = True
    except ImportError as e:
        issues.append(f"Missing analyzer_service: {e}")
        core_ok = False
    
    # 检查 src.config
    try:
        from src.config import get_config, Config
        config_ok = True
    except ImportError as e:
        issues.append(f"Missing src.config: {e}")
        config_ok = False
    
    # 检查关键依赖包
    required_packages = [
        ("dotenv", "python-dotenv"),
        ("pandas", "pandas"),
    ]
    
    for module_name, package_name in required_packages:
        try:
            __import__(module_name)
        except ImportError:
            issues.append(f"Missing package: {package_name} (pip install {package_name})")
    
    return core_ok and config_ok and len(issues) == 0, issues


def check_env_file():
    """检查 .env 配置文件是否存在"""
    # 查找 .env 文件 (从当前目录向上查找)
    # scripts/check_deps.py -> skills/stock-analysis/scripts/ -> 需要向上 3 级到项目根目录
    current = Path(__file__).resolve().parent.parent.parent
    env_file = current / ".env"
    
    # 如果找不到,尝试再向上一级 (应对符号链接情况)
    if not env_file.exists():
        current = current.parent
        env_file = current / ".env"
    
    if not env_file.exists():
        return False, f".env file not found at {env_file}"
    
    # 读取并检查关键配置
    try:
        from dotenv import dotenv_values
        config = dotenv_values(env_file)
        
        # 必须配置 LLM 模型
        if not config.get("LITELLM_MODEL"):
            return False, "Missing LITELLM_MODEL in .env"
        
        # 检查 API Key (支持多种配置方式)
        has_api_key = any([
            config.get("LITELLM_API_KEY"),           # 标准方式
            config.get("LLM_BAILIAN_API_KEY"),       # 阿里云百炼
            config.get("LLM_ZHIPUAI_API_KEY"),       # 智谱 AI
            config.get("LLM_OPENAI_API_KEY"),        # OpenAI
            config.get("OPENAI_API_KEY"),            # OpenAI 标准
        ])
        
        if not has_api_key:
            return False, "Missing LLM API Key (check LITELLM_API_KEY or LLM_*_API_KEY)"
        
        model = config.get("LITELLM_MODEL", "unknown")
        return True, f".env OK (model={model})"
    except Exception as e:
        return False, f"Error reading .env: {e}"


def check_api_server():
    """检查 API 服务是否运行 (可选)"""
    import urllib.request
    
    try:
        url = "http://localhost:8000/api/health"
        req = urllib.request.urlopen(url, timeout=3)
        if req.status == 200:
            return True, "API server running on port 8000"
    except:
        pass
    
    return None, "API server not running (optional, only needed for API mode)"


def main():
    print("=" * 60)
    print("Stock Analysis Skill - Dependency Check")
    print("=" * 60)
    print()
    
    all_ok = True
    results = []
    
    # 检查 Python 版本
    ok, msg = check_python_version()
    results.append(("Python Version", ok, msg))
    if not ok:
        all_ok = False
    
    # 检查核心模块
    ok, issues = check_core_modules()
    if isinstance(issues, list):
        results.append(("Core Modules", ok, "\n    ".join(issues) if issues else "All modules OK"))
    else:
        results.append(("Core Modules", ok, issues))
    if not ok:
        all_ok = False
    
    # 检查 .env 文件
    ok, msg = check_env_file()
    results.append(("Environment Config", ok, msg))
    if not ok:
        all_ok = False
    
    # 检查 API 服务 (仅提示,不阻塞)
    ok, msg = check_api_server()
    results.append(("API Server (Optional)", ok if ok else None, msg))
    
    # 打印结果
    for name, ok, msg in results:
        if ok is None:
            status = "⚠️ "
        elif ok:
            status = "✅ "
        else:
            status = "❌ "
        print(f"{status} {name}: {msg}")
    
    print()
    print("=" * 60)
    
    if all_ok:
        print("✅ All dependencies OK - Skill is ready to use!")
        print()
        print("Quick start:")
        print("  from analyzer_service import analyze_stock")
        print("  result = analyze_stock('600519')")
    else:
        print("❌ Dependency check failed!")
        print()
        print("Fix issues:")
        print("  1. Install dependencies: pip install -r requirements.txt")
        print("  2. Create .env file: cp .env.example .env")
        print("  3. Configure LITELLM_MODEL and LITELLM_API_KEY in .env")
    
    print("=" * 60)
    
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
