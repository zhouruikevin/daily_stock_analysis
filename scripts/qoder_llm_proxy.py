"""
Qoder LLM Proxy - OpenAI 兼容代理服务

将 OpenAI 格式的 /v1/chat/completions 请求转发到本地 qodercli，
复用 Qoder 额度替代百炼 token。

前置条件：
  1. 本地已安装 qodercli 且已登录（qodercli --list-models 能正常返回）
  2. Python 环境有 fastapi + uvicorn

使用方式：
  python scripts/qoder_llm_proxy.py
  # 然后在 .env 配置 LLM_QODER_BASE_URL=http://127.0.0.1:8765/v1

环境变量：
  QODER_PROXY_HOST    监听地址（默认 127.0.0.1）
  QODER_PROXY_PORT    监听端口（默认 8765）
  QODERCLI_PATH       qodercli 路径（默认 qodercli）
  QODER_PROXY_TIMEOUT 单次请求超时秒数（默认 200）
  QODER_PROXY_MODEL   默认模型（默认 DeepSeek-V4-Pro）
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

logger = logging.getLogger("qoder_proxy")

app = FastAPI(title="Qoder LLM Proxy", version="1.0.0")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROXY_HOST: str = os.getenv("QODER_PROXY_HOST", "127.0.0.1")
PROXY_PORT: int = int(os.getenv("QODER_PROXY_PORT", "8765"))
QODERCLI_PATH: str = os.getenv("QODERCLI_PATH", "qodercli")
REQUEST_TIMEOUT: int = int(os.getenv("QODER_PROXY_TIMEOUT", "200"))
DEFAULT_MODEL: str = os.getenv("QODER_PROXY_MODEL", "DeepSeek-Flash")

# litellm name → qodercli name
# 注：qodercli 模型列表会随版本变化（如 DeepSeek-V4-Flash 已下线），
# 旧别名统一映射到当前可用模型，避免 "Invalid model" 导致 exit 42。
MODEL_MAP: Dict[str, str] = {
    "deepseek-v4-pro": "DeepSeek-V4-Pro",
    "deepseek-flash": "DeepSeek-Flash",
    "deepseek-v4-flash": "DeepSeek-Flash",
    "efficient": "Efficient",
    "auto": "Auto",
    "performance": "Performance",
    "ultimate": "Ultimate",
    "qwen3.7-max": "Qwen3.7-Max",
    "glm-5.2": "GLM-5.2",
    "kimi-k2.7-code": "Kimi-K2.7-Code",
    "minimax-m3": "MiniMax-M3",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def messages_to_prompt(messages: List[Dict[str, Any]]) -> str:
    """把 OpenAI messages 列表拼成单个 prompt 字符串。"""
    parts: list[str] = []
    for msg in messages:
        role: str = msg.get("role", "user")
        content: Any = msg.get("content", "")

        # Handle multi-part content (e.g. vision messages with image_url)
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


def resolve_model(model: str) -> str:
    """把 litellm model name 映射到 qodercli model name。"""
    if not model:
        return DEFAULT_MODEL

    # Strip provider prefix like "openai/deepseek-v4-pro"
    if "/" in model:
        model = model.rsplit("/", 1)[-1]

    model_lower: str = model.lower().strip()
    return MODEL_MAP.get(model_lower, model)


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
# Core: call qodercli
# ---------------------------------------------------------------------------
async def call_qodercli(
    prompt: str,
    model: str,
    max_tokens: int = 8192,
) -> str:
    """通过 subprocess 调用 qodercli，prompt 经 stdin 传入，返回 AI 文本输出。"""
    cmd = [
        QODERCLI_PATH,
        "-p",
        "--tools", "",
        "-m", model,
        "--permission-mode", "bypass_permissions",
        "--max-output-tokens", str(max(max_tokens, 1024)),
    ]

    logger.info(
        "[qodercli] model=%s prompt_len=%d max_tokens=%d",
        model,
        len(prompt),
        max_tokens,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.error("[qodercli] command not found: %s", QODERCLI_PATH)
        raise RuntimeError(
            f"qodercli not found at '{QODERCLI_PATH}'. "
            "Please install qodercli and ensure it is in PATH."
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=REQUEST_TIMEOUT,
        )
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        logger.error("[qodercli] timeout after %ds", REQUEST_TIMEOUT)
        raise RuntimeError(f"qodercli timeout after {REQUEST_TIMEOUT}s")

    stdout: str = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr: str = stderr_bytes.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        logger.error(
            "[qodercli] exit code=%d stderr=%s",
            proc.returncode,
            stderr[:500] if stderr else "(empty)",
        )
        # If there is stdout despite non-zero exit, use it (fail-open)
        if stdout:
            logger.warning("[qodercli] non-zero exit but has stdout, using it")
            return stdout
        raise RuntimeError(
            f"qodercli failed (exit {proc.returncode}): "
            f"{stderr[:300] if stderr else 'no stderr'}"
        )

    if stderr:
        logger.debug("[qodercli] stderr=%s", stderr[:200])

    logger.info("[qodercli] response_len=%d", len(stdout))
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
    max_tokens: int = body.get("max_tokens", 8192)

    if not messages:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "messages is required", "type": "invalid_request_error"}},
        )

    qoder_model = resolve_model(model)
    prompt = messages_to_prompt(messages)

    try:
        response_text = await call_qodercli(prompt, qoder_model, max_tokens=max_tokens)
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
        # Simulate SSE streaming by chunking the complete response
        async def generate():
            # First chunk: role announcement
            first_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n"

            # Content chunks (split by ~200 chars for natural-looking streaming)
            chunk_size = 200
            for i in range(0, len(response_text), chunk_size):
                chunk_text = response_text[i : i + chunk_size]
                content_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": chunk_text},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(content_chunk, ensure_ascii=False)}\n\n"

            # Final chunk
            final_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
        )

    # Non-streaming response
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
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
    )


@app.get("/v1/models")
async def list_models() -> dict:
    """返回可用模型列表。"""
    data = [
        {
            "id": litellm_name,
            "object": "model",
            "created": 0,
            "owned_by": "qoder",
        }
        for litellm_name in MODEL_MAP.keys()
    ]
    return {"object": "list", "data": data}


@app.get("/health")
async def health() -> dict:
    """健康检查端点。"""
    return {"status": "ok", "qodercli": QODERCLI_PATH}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    logger.info(
        "Starting Qoder LLM Proxy on %s:%d (qodercli=%s, timeout=%ds)",
        PROXY_HOST,
        PROXY_PORT,
        QODERCLI_PATH,
        REQUEST_TIMEOUT,
    )
    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT)
