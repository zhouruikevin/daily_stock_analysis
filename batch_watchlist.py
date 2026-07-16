"""批量分析关注列表股票并合并邮件发送"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.services.analyzer_service import analyze_stocks

# .env L52 关注列表（去除雅克科技/中国巨石，新增中国卫通/双环传动/三花智控）
STOCK_CODES = [
    "600522", "601138", "605589", "603986", "002371",
    "002407", "002463", "603650", "002837", "002916",
    "603019", "002518", "603444", "000400", "600378",
    "002517", "601698", "002472", "002050",
]

print(f"开始批量分析 {len(STOCK_CODES)} 只股票...")
results = analyze_stocks(
    stock_codes=STOCK_CODES,
    full_report=True,
    merge_notification=True,
)
print(f"\n分析完成，共获得 {len(results)} 条结果")
for r in results:
    status = "✅" if r.success else "❌"
    print(f"  {status} {r.code} {r.name}")
