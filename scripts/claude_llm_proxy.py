"""
Claude LLM Proxy - OpenAI 兼容代理服务

将 OpenAI 格式的 /v1/chat/completions 请求转发到本地 Claude Code CLI (`claude`)，
复用 Claude 订阅额度替代百炼/Qoder token。让现有分析管道（analyze_stocks）原样运行，
只把 LLM 大脑换成 Claude —— 报告结构、格式化、财务/板块渲染全部沿用原管道。

前置条件：
  1. 本地已安装 Claude Code CLI 且已登录（claude -p 能正常返回）
  2. Python 环境有 fastapi + uvicorn（项目 requirements 已含）

使用方式：
  python scripts/claude_llm_proxy.py
  # 然后在 .env 配置：
  #   LLM_CHANNELS=claudecode,bailian
  #   LLM_CLAUDECODE_PROTOCOL=openai
  #   LLM_CLAUDECODE_BASE_URL=http://127.0.0.1:8766/v1
  #   LLM_CLAUDECODE_API_KEY=dummy
  #   LLM_CLAUDECODE_MODELS=claude-analysis
  #   LITELLM_MODEL=openai/claude-analysis

环境变量：
  CLAUDE_PROXY_HOST     监听地址（默认 127.0.0.1）
  CLAUDE_PROXY_PORT     监听端口（默认 8766）
  CLAUDE_PATH           claude 可执行文件路径（默认 /opt/homebrew/bin/claude，回退 claude）
  CLAUDE_PROXY_TIMEOUT  单次请求超时秒数（默认 300）
  CLAUDE_PROXY_MODEL    传给 claude 的模型（默认空=用账号默认模型；可设 sonnet/opus/haiku）
  CLAUDE_PROXY_CWD      claude 子进程工作目录（默认 /tmp，避免读到项目 CLAUDE.md）

对比 qoder_llm_proxy.py 的差异：
  - qoder: qodercli -p --tools "" -m <model> --permission-mode bypass_permissions --max-output-tokens N
  - claude: claude -p --bare --permission-mode bypassPermissions [--model <model>]
    · claude 用驼峰 bypassPermissions（非 bypass_permissions）
    · claude 无 --max-output-tokens
    · --bare = 最小无状态模式（跳过 hooks/LSP/plugin/CLAUDE.md），最适合当代理后端
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("claude_proxy")

app = FastAPI(title="Claude LLM Proxy", version="1.0.0")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROXY_HOST: str = os.getenv("CLAUDE_PROXY_HOST", "127.0.0.1")
PROXY_PORT: int = int(os.getenv("CLAUDE_PROXY_PORT", "8766"))
_DEFAULT_CLAUDE = "/opt/homebrew/bin/claude"
CLAUDE_PATH: str = os.getenv(
    "CLAUDE_PATH",
    _DEFAULT_CLAUDE if os.path.exists(_DEFAULT_CLAUDE) else "claude",
)
REQUEST_TIMEOUT: int = int(os.getenv("CLAUDE_PROXY_TIMEOUT", "300"))
# 空字符串 => 不传 --model，用账号默认模型（与交互式一致）
DEFAULT_MODEL: str = os.getenv("CLAUDE_PROXY_MODEL", "").strip()
CLAUDE_CWD: str = os.getenv("CLAUDE_PROXY_CWD", "/tmp")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def messages_to_prompt(messages: List[Dict[str, Any]]) -> str:
    """把 OpenAI messages 列表拼成单个 prompt 字符串。"""
    parts: list[str] = []
    for msg in messages:
        role: str = msg.get("role", "user")
        content: Any = msg.get("content", "")

        if isinstance(content, list):
            text_blocks: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_blocks.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_blocks.append(block)
            content = "\n".join(text_blocks)

        content = str(content) if content else ""

        if role == "system":
            parts.append(f"[System Instructions]\n{content}")
        elif role == "user":
            parts.append(content)
        elif role == "assistant":
            parts.append(f"[Previous Assistant Response]\n{content}")
        elif role == "tool":
            parts.append(f"[Tool Result]\n{content}")

    return "\n\n".join(parts)


def resolve_model(model: str) -> Optional[str]:
    """把 litellm model name 映射到 claude --model 值；返回 None 表示用账号默认。"""
    if not model:
        return DEFAULT_MODEL or None
    if "/" in model:
        model = model.rsplit("/", 1)[-1]
    m = model.lower().strip()
    for alias in ("opus", "sonnet", "haiku"):
        if alias in m:
            return alias
    # 未识别 => 用代理默认（可能为空=账号默认）
    return DEFAULT_MODEL or None


def extract_json_if_needed(text: str) -> str:
    """如果文本包含 markdown 代码块包裹的 JSON，提取出来。"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        extracted = m.group(1).strip()
        if extracted.startswith(("{", "[")):
            return extracted
    return text


# ---------------------------------------------------------------------------
# Core: call claude
# ---------------------------------------------------------------------------
async def call_claude(prompt: str, model: Optional[str]) -> str:
    """通过 subprocess 调用 claude CLI，prompt 经 stdin 传入，返回 AI 文本输出。"""
    cmd = [
        CLAUDE_PATH,
        "-p",
        "--bare",
        "--permission-mode", "bypassPermissions",
    ]
    if model:
        cmd += ["--model", model]

    logger.info(
        "[claude] model=%s prompt_len=%d",
        model or "(account default)",
        len(prompt),
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=CLAUDE_CWD if os.path.isdir(CLAUDE_CWD) else None,
        )
    except FileNotFoundError:
        logger.error("[claude] command not found: %s", CLAUDE_PATH)
        raise RuntimeError(
            f"claude not found at '{CLAUDE_PATH}'. "
            "Please install Claude Code CLI and ensure it is in PATH, "
            "or set CLAUDE_PATH."
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=REQUEST_TIMEOUT,
        )
    except (TimeoutError, asyncio.TimeoutError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        logger.error("[claude] timeout after %ds", REQUEST_TIMEOUT)
        raise RuntimeError(f"claude timeout after {REQUEST_TIMEOUT}s")

    stdout: str = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr: str = stderr_bytes.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        logger.error(
            "[claude] exit code=%d stderr=%s",
            proc.returncode,
            stderr[:500] if stderr else "(empty)",
        )
        if stdout:
            logger.warning("[claude] non-zero exit but has stdout, using it")
            return stdout
        raise RuntimeError(
            f"claude failed (exit {proc.returncode}): "
            f"{stderr[:300] if stderr else 'no stderr'}"
        )

    if stderr:
        logger.debug("[claude] stderr=%s", stderr[:200])

    logger.info("[claude] response_len=%d", len(stdout))
    return stdout


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
    """OpenAI 兼容的 chat completions 端点。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}},
        )

    messages = body.get("messages")
    model: str = body.get("model", "")
    stream: bool = body.get("stream", False)

    if not messages:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "messages is required", "type": "invalid_request_error"}},
        )

    claude_model = resolve_model(model)
    prompt = messages_to_prompt(messages)

    try:
        response_text = await call_claude(prompt, claude_model)
    except Exception as e:
        logger.error("[proxy] LLM call failed: %s", str(e))
        return JSONResponse(
            status_code=502,
            content={"error": {"message": str(e), "type": "proxy_error"}},
        )

    response_text = extract_json_if_needed(response_text)

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    if stream:
        async def generate():
            first_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}
                ],
            }
            yield f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n"

            chunk_size = 200
            for i in range(0, len(response_text), chunk_size):
                chunk_text = response_text[i : i + chunk_size]
                content_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {"content": chunk_text}, "finish_reason": None}
                    ],
                }
                yield f"data: {json.dumps(content_chunk, ensure_ascii=False)}\n\n"

            final_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    return JSONResponse(
        content={
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": response_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    )


@app.get("/health")
async def health() -> dict:
    """健康检查端点。"""
    return {"status": "ok", "claude": CLAUDE_PATH, "model": DEFAULT_MODEL or "(account default)"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    logger.info(
        "Starting Claude LLM Proxy on %s:%d (claude=%s, model=%s, timeout=%ds)",
        PROXY_HOST,
        PROXY_PORT,
        CLAUDE_PATH,
        DEFAULT_MODEL or "(account default)",
        REQUEST_TIMEOUT,
    )
    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT)
