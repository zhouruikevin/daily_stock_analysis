#!/bin/bash
# DSA 服务管理脚本 - 自动检测并启动服务

DSA_DIR="/Users/eleme/Documents/ai/qoderwork/daily_stock_analysis"
DSA_URL="http://localhost:8000"
LOG_FILE="/tmp/dsa_server.log"
PID_FILE="/tmp/dsa_server.pid"

# 检查服务是否运行
check_service() {
    if curl -s "${DSA_URL}/api/health" > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# 启动服务
start_service() {
    echo "[DSA] 服务未运行，正在启动..."
    cd "$DSA_DIR"
    
    # 检查依赖
    if ! python -c "import fastapi" 2>/dev/null; then
        echo "[DSA] 错误: 缺少依赖，正在安装..."
        pip install -r requirements.txt -q
    fi
    
    # 后台启动
    nohup python main.py --serve-only > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    
    echo "[DSA] 等待服务启动..."
    for i in $(seq 1 30); do
        if check_service; then
            echo "[DSA] 服务已就绪 (${i}s)"
            return 0
        fi
        sleep 1
    done
    
    echo "[DSA] 错误: 服务启动失败，请查看日志 $LOG_FILE"
    return 1
}

# 停止服务
stop_service() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "[DSA] 停止服务 (PID: $PID)"
            kill "$PID"
            rm -f "$PID_FILE"
        fi
    fi
}

# 主逻辑
case "${1:-status}" in
    start)
        if check_service; then
            echo "[DSA] 服务已运行"
        else
            start_service
        fi
        ;;
    stop)
        stop_service
        echo "[DSA] 服务已停止"
        ;;
    restart)
        stop_service
        sleep 2
        start_service
        ;;
    status)
        if check_service; then
            echo "[DSA] 服务运行中: ${DSA_URL}"
            if [ -f "$PID_FILE" ]; then
                echo "[DSA] PID: $(cat $PID_FILE)"
            fi
        else
            echo "[DSA] 服务未运行"
        fi
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
