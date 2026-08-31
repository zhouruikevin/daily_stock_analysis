"""批量分析关注股票并合并邮件发送"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.services.analyzer_service import analyze_stocks

STOCK_CODES = [
    "600522", "601138", "002371", "002407", "002463",
    "603444", "603296", "601899", "600176",
    "603650", "605499", "002315",
    "300308", "688981", "002518", "002415", "000021", "000100",
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
