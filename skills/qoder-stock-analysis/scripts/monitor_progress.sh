#!/bin/bash
# 分析任务进度监控脚本

TASK_ID="$1"
DSA_BASE_URL="${2:-http://localhost:8000}"

if [ -z "$TASK_ID" ]; then
    echo "用法: $0 <task_id> [DSA_BASE_URL]"
    echo "示例: $0 abc123def456"
    exit 1
fi

echo "🔍 监控任务: $TASK_ID"
echo "📡 API: $DSA_BASE_URL"
echo "================================"

START_TIME=$(date +%s)

while true; do
    ELAPSED=$(( $(date +%s) - START_TIME ))
    MINUTES=$(( ELAPSED / 60 ))
    SECONDS=$(( ELAPSED % 60 ))
    
    # 查询任务状态
    STATUS=$(curl -s "${DSA_BASE_URL}/api/v1/analysis/status/${TASK_ID}" 2>/dev/null)
    
    if [ -z "$STATUS" ]; then
        echo "❌ 无法连接到 DSA 服务"
        exit 1
    fi
    
    STATE=$(echo "$STATUS" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('status', 'unknown'))
except:
    print('error')
" 2>/dev/null)
    
    # 获取进度信息
    PROGRESS=$(echo "$STATUS" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    progress = data.get('progress', {})
    stage = progress.get('stage', '未知')
    percent = progress.get('percent', 0)
    print(f'{stage} ({percent}%)')
except:
    print('未知')
" 2>/dev/null)
    
    # 显示状态
    case "$STATE" in
        completed)
            echo ""
            echo "✅ 分析完成！耗时: ${MINUTES}分${SECONDS}秒"
            echo ""
            # 显示结果摘要
            echo "$STATUS" | python3 -c "
import sys, json
data = json.load(sys.stdin)
result = data.get('result', {})
print(f\"股票: {result.get('name', 'N/A')} ({result.get('code', 'N/A')})\")
dashboard = result.get('dashboard', {})
core = dashboard.get('core_conclusion', {})
print(f\"结论: {core.get('one_sentence', 'N/A')}\")
print(f\"建议: {result.get('operation_advice', 'N/A')}\")
print(f\"得分: {result.get('sentiment_score', 'N/A')}/100\")
" 2>/dev/null
            break
            ;;
        failed)
            echo ""
            echo "❌ 分析失败！耗时: ${MINUTES}分${SECONDS}秒"
            echo ""
            echo "错误信息:"
            echo "$STATUS" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('error', '未知错误'))
" 2>/dev/null
            break
            ;;
        running|pending)
            # 每分钟输出进度
            if [ $(( ELAPSED % 60 )) -eq 0 ] || [ $ELAPSED -lt 5 ]; then
                echo "⏳ ${MINUTES}分${SECONDS}秒 | 状态: $STATE | 进度: $PROGRESS"
            fi
            ;;
        *)
            echo "⚠️ 未知状态: $STATE"
            ;;
    esac
    
    # 超时检查（10 分钟）
    if [ $ELAPSED -gt 600 ]; then
        echo ""
        echo "⚠️ 分析超时（超过 10 分钟）"
        echo "建议检查日志: tail -f /tmp/dsa_server.log"
        break
    fi
    
    sleep 10
done
