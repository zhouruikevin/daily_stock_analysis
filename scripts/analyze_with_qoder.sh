#!/bin/bash
# 用 Qoder（qodercli）经原分析管道分析股票，逐只反馈进度，最后发合并邮件。
# 模型：QODER_PROXY_MODEL（默认 DeepSeek-V4-Flash），可用 QODER_PROXY_MODEL=xxx 覆盖。
#
# 用法（在项目根目录执行）：
#   bash scripts/analyze_with_qoder.sh                    # 分析 .env 的 STOCK_LIST（关注列表）
#   bash scripts/analyze_with_qoder.sh 600519,603444      # 分析指定股票
#   MAX_WORKERS=5 bash scripts/analyze_with_qoder.sh      # 调并发线程数（默认 4）
#   NO_EMAIL=1 bash scripts/analyze_with_qoder.sh 603444  # 只分析存库不发邮件（联调）
#
# 进度：每只分析完成即打印一行  [进度 k/N] <code> <name> ✅ 评分.. <操作>
# 原理：启动 qoder_llm_proxy（若未运行）→ 把 LLM 渠道临时指向该代理 →
#       逐只走原管道 analyze_stock（报告/财务/板块/格式全部沿用原管道）→ 合并发一封邮件。
# 不修改 .env，默认 LLM 配置不受影响；本脚本仅在本次进程内用环境变量覆盖。
set -euo pipefail

cd "$(dirname "$0")/.."
PY=.venv/bin/python3
PROXY_URL="http://127.0.0.1:8765"
export QODER_PROXY_MODEL="${QODER_PROXY_MODEL:-DeepSeek-V4-Flash}"

# 1) 确保代理在运行（未启动则自动拉起）
if ! curl -s "${PROXY_URL}/health" >/dev/null 2>&1; then
  echo "[qoder] 代理未运行，正在启动 (model=${QODER_PROXY_MODEL}) ..."
  nohup "$PY" scripts/qoder_llm_proxy.py > /tmp/qoder_proxy.log 2>&1 &
  for _ in $(seq 1 15); do
    sleep 1
    curl -s "${PROXY_URL}/health" >/dev/null 2>&1 && break
  done
fi
HEALTH="$(curl -s "${PROXY_URL}/health" 2>/dev/null || true)"
[ -n "$HEALTH" ] || { echo "[qoder] 代理启动失败，见 /tmp/qoder_proxy.log"; exit 1; }
echo "[qoder] 代理就绪: ${HEALTH}"

# 2) 把 LLM 渠道临时指向 qoder 代理（仅本次进程）
export LLM_CHANNELS=qoder
export LLM_QODER_PROTOCOL=openai
export LLM_QODER_BASE_URL="${PROXY_URL}/v1"
export LLM_QODER_API_KEY=dummy
export LLM_QODER_MODELS=deepseek-v4-flash
export LLM_QODER_ENABLED=true
export LITELLM_MODEL=openai/deepseek-v4-flash
export MAX_WORKERS="${MAX_WORKERS:-4}"
# LLM 调用约 30-120s，叠加数据源抖动可能顶爆管道
# 200s 单股预算可能不足，这里放宽到 360s，仅影响本脚本这条链路。
export SINGLE_STOCK_ANALYSIS_TIMEOUT="${SINGLE_STOCK_ANALYSIS_TIMEOUT:-360}"
# 关闭数据源库(efinance/akshare)的 tqdm 进度条噪声，让日志只剩清晰的逐只进度
export TQDM_DISABLE=1

# 3) 运行分析（逐只进度 + 合并邮件）
PYTHONPATH="$PWD" CODES_ARG="${1:-}" NO_EMAIL="${NO_EMAIL:-0}" "$PY" - <<'PYEOF'
import os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.config import get_config
from src.services.analyzer_service import analyze_stock
from src.notification import NotificationService

codes_arg = os.environ.get("CODES_ARG", "").strip()
if codes_arg:
    codes = [c.strip() for c in codes_arg.replace("，", ",").split(",") if c.strip()]
else:
    codes = get_config().stock_list

send_email = os.environ.get("NO_EMAIL", "0") != "1"
workers = int(os.environ.get("MAX_WORKERS", "4"))
N = len(codes)

model_label = os.environ.get("LITELLM_MODEL") or "(默认)"
print(f"[qoder] ▶ 开始分析 {N} 只 (workers={workers}, 发邮件={send_email}, 模型={model_label})", flush=True)
print(f"[qoder] 列表: {','.join(codes)}", flush=True)

t0 = time.time()
results = {}
with ThreadPoolExecutor(max_workers=workers) as ex:
    futs = {ex.submit(analyze_stock, c, full_report=True, _no_auto_notify=True): c for c in codes}
    done = 0
    for fut in as_completed(futs):
        c = futs[fut]
        done += 1
        try:
            r = fut.result()
        except Exception as e:
            results[c] = None
            print(f"[进度 {done}/{N}] {c} ❌ 异常: {e}", flush=True)
            continue
        results[c] = r
        if r and getattr(r, "success", False):
            print(f"[进度 {done}/{N}] {c} {r.name} ✅ 评分{r.sentiment_score} {r.operation_advice} (累计{time.time()-t0:.0f}s)", flush=True)
        else:
            print(f"[进度 {done}/{N}] {c} ❌ 分析失败", flush=True)

ordered = [results[c] for c in codes if results.get(c) and getattr(results[c], "success", False)]
print(f"[qoder] ■ 分析完成 用时{time.time()-t0:.0f}s 成功{len(ordered)}/{N}", flush=True)

if not ordered:
    print("[qoder] 无成功结果，跳过邮件", flush=True)
elif not send_email:
    print("[qoder] NO_EMAIL=1，仅分析存库未发邮件", flush=True)
else:
    try:
        n = NotificationService()
        if n.is_available():
            if len(ordered) > 1:
                report = n.generate_aggregate_report(ordered, report_type="full")
            else:
                report = n.generate_dashboard_report(ordered)
            n.send(report, email_send_to_all=True)
            n.save_report_to_file(report)
            print(f"[qoder] 📧 合并邮件已发送（{len(ordered)}只）+ 报告已存 reports/", flush=True)
        else:
            print("[qoder] 邮件渠道不可用（检查 .env EMAIL_*），跳过发送", flush=True)
    except Exception as e:
        print(f"[qoder] 邮件发送失败: {e}", flush=True)
PYEOF