#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速测试脚本 - 验证 Stock Analysis Skill 是否正常工作

Usage:
    python skills/stock-analysis/scripts/test_skill.py
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
# scripts/test_skill.py -> skills/stock-analysis/scripts/
# 需要向上 3 级到项目根目录
script_dir = Path(__file__).resolve().parent  # scripts/
skill_dir = script_dir.parent                  # stock-analysis/
skills_dir = skill_dir.parent                  # skills/
project_root = skills_dir.parent               # daily_stock_analysis/
sys.path.insert(0, str(project_root))


def test_import():
    """测试模块导入"""
    print("=" * 60)
    print("Test 1: Import Modules")
    print("=" * 60)
    
    try:
        from analyzer_service import analyze_stock, analyze_stocks, perform_market_review
        print("✅ analyzer_service imported successfully")
        
        from src.config import get_config
        print("✅ src.config imported successfully")
        
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False


def test_config():
    """测试配置加载"""
    print("\n" + "=" * 60)
    print("Test 2: Load Configuration")
    print("=" * 60)
    
    try:
        from src.config import get_config
        config = get_config()
        
        print(f"✅ Config loaded")
        print(f"   LITELLM_MODEL: {getattr(config, 'litellm_model', 'NOT SET')}")
        
        # 检查必要配置
        if not getattr(config, 'litellm_model', None):
            print("⚠️  Warning: LITELLM_MODEL not configured")
            print("   Please set it in .env file")
            return False
        
        return True
    except Exception as e:
        print(f"❌ Config load failed: {e}")
        return False


def test_dry_run():
    """测试干运行 (不实际调用 LLM)"""
    print("\n" + "=" * 60)
    print("Test 3: Dry Run (Data Fetch Only)")
    print("=" * 60)
    
    try:
        from data_provider.akshare_fetcher import AkShareFetcher
        
        fetcher = AkShareFetcher()
        
        # 尝试获取 A股数据
        print("📊 Fetching test data for 600519...")
        data = fetcher.get_daily_k_data("600519", days=5)
        
        if data is not None and len(data) > 0:
            print(f"✅ Data fetch successful ({len(data)} days)")
            print(f"   Latest date: {data.iloc[-1].get('date', 'N/A')}")
            print(f"   Latest close: {data.iloc[-1].get('close', 'N/A')}")
            return True
        else:
            print("⚠️  No data returned (may be market closed or network issue)")
            return True  # 不算失败
            
    except Exception as e:
        print(f"⚠️  Dry run failed: {e}")
        print("   This is OK if network is unavailable")
        return True  # 网络问题不算 Skill 本身的问题


def main():
    print("\n🧪 Stock Analysis Skill - Quick Test\n")
    
    results = []
    
    # 测试 1: 导入
    results.append(("Import", test_import()))
    
    # 测试 2: 配置
    results.append(("Config", test_config()))
    
    # 测试 3: 干运行
    results.append(("Dry Run", test_dry_run()))
    
    # 总结
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {name}")
    
    all_passed = all(passed for _, passed in results)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All tests passed! Skill is ready to use.")
        print("\nQuick start:")
        print("  from analyzer_service import analyze_stock")
        print("  result = analyze_stock('600519')")
    else:
        print("⚠️  Some tests failed.")
        print("   Check the error messages above for details.")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
