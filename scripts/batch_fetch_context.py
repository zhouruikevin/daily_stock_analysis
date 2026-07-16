#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量获取多只股票的上下文数据，保存到 /tmp/ctx_<code>.json
"""
import sys
import os
import json
import logging
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from scripts.fetch_stock_context import fetch_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

STOCKS = [
    "600522", "601138", "603986", "002371", "002407", "002463",
    "603650", "603019", "603444", "600378", "002517", "002050",
    "603296", "601899", "600118", "000400", "605090",
    "hk00700", "hk01810", "hk03690",
    "600176", "603186", "601208",
]

SKIP_NEWS = False  # Set to True to skip news for faster fetch

def main():
    total = len(STOCKS)
    success = 0
    for i, code in enumerate(STOCKS, 1):
        logger.info("[%d/%d] 正在获取 %s ...", i, total, code)
        t0 = time.time()
        try:
            data = fetch_context(code, skip_news=SKIP_NEWS)
            outpath = f"/tmp/ctx_{code}.json"
            with open(outpath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str, indent=2)
            elapsed = time.time() - t0
            name = data.get("name", code)
            logger.info("[%d/%d] %s(%s) 完成, 耗时 %.1fs, 保存到 %s", i, total, name, code, elapsed, outpath)
            success += 1
        except Exception as e:
            logger.error("[%d/%d] %s 获取失败: %s", i, total, code, e)
    logger.info("批量获取完成: %d/%d 成功", success, total)

if __name__ == "__main__":
    main()
