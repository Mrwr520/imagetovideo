"""OpenAICompatibleProvider：兼容 OpenAI API 格式的通用 LLM Provider。

适用于通义千问、DeepSeek、智谱AI 等兼容 OpenAI chat/completions 接口的模型后端。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from pathlib import Path

import httpx

from .base import BaseLLMProvider

logger = logging.getLogger(__name__)

_TIMEOUT = 120.0  # 请求超时（秒）
_MAX_RETRIES = 3  # 429 速率限制最大重试次数
_RETRY_WAIT = 1.0  # 重试等待基数（秒），按指数退避


def _encode_image(image_path: Path) -> str:
    """将图片文件编码为 base64 data URI。

    Returns:
        形如 ``data:image/png;base64,xxxx`` 的字符串。
    """
    mime_type, _ = mimetypes.guess_type(str(image_path))
    if mime_type is None:
        # 根据后缀推断
        suffix = image_path.suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp"}
        mime_type = mime_map.get(suffix, "image/jpeg")

    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"


def _build_messages(images: list[Path], prompt: str) -> list[dict]:
    """构造 OpenAI 多模态 chat messages 格式。

    使用 system message 约束输出格式，user message 放具体任务。
    """
    # system message 强制 JSON 输出角色
    system_msg = {
        "role": "system",
        "content": (
            "你是一个纯JSON输出接口。你只输出合法的JSON对象，不输出任何其他文字、解释、推荐或建议。"
            "用户会给你图片和一个JSON模板，你只需要填写模板中的value并返回完整JSON。"
        ),
    }

    # user message 包含图片和具体任务
    content: list[dict] = [{"type": "text", "text": prompt}]
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": _encode_image(img)},
        })
    user_msg = {"role": "user", "content": content}

    return [system_msg, user_msg]


class OpenAICompatibleProvider(BaseLLMProvider):
    """兼容 OpenAI API 格式的通用 Provider。

    通过 ``/chat/completions`` 端点发送多模态请求，将图片编码为 base64
    嵌入请求体。支持 30 秒超时和 429 速率限制自动重试（最多 3 次）。
    """

    def __init__(self, api_base: str, api_key: str, model: str) -> None:
        # 去除尾部斜杠，方便拼接路径
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def generate_narration(self, images: list[Path], prompt: str) -> str:
        """将图片编码为 base64，通过多模态 API 发送请求并返回解说词。"""
        messages = _build_messages(images, prompt)
        return await self._chat(messages)

    async def review_narration(self, messages: list[dict], review_prompt: str) -> str:
        """基于已有对话上下文，发送审查请求并返回修正后的结果。"""
        messages = list(messages)  # 不修改原列表
        messages.append({"role": "user", "content": review_prompt})
        return await self._chat(messages)

    async def _chat(self, messages: list[dict]) -> str:
        """发送 chat 请求并返回文本响应。"""
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request_with_retry(client, url, headers, payload)

        return response

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict,
        payload: dict,
    ) -> str:
        """发送 POST 请求，支持流式响应，遇到 429 时指数退避重试。"""
        import json as _json

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                req = client.build_request("POST", url, headers=headers, json=payload)
                resp = await client.send(req, stream=True)
            except httpx.TimeoutException as exc:
                raise TimeoutError(
                    f"LLM 请求超时（{_TIMEOUT}秒），请稍后重试"
                ) from exc

            if resp.status_code == 200:
                # 读取 SSE 流，拼接 delta content
                collected: list[str] = []
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            collected.append(content)
                    except (_json.JSONDecodeError, IndexError, KeyError):
                        continue
                await resp.aclose()
                return "".join(collected)

            await resp.aclose()

            if resp.status_code == 401:
                raise PermissionError("API 密钥无效，请检查配置中的 api_key")

            if resp.status_code == 429:
                wait = _RETRY_WAIT * (2 ** attempt)
                logger.warning("速率限制 (429)，%s 秒后重试 (%d/%d)",
                               wait, attempt + 1, _MAX_RETRIES)
                last_exc = RuntimeError(
                    f"速率限制：已重试 {_MAX_RETRIES} 次仍失败"
                )
                await asyncio.sleep(wait)
                continue

            # 其他错误
            body = resp.text if hasattr(resp, 'text') else ""
            raise RuntimeError(
                f"LLM API 请求失败 (HTTP {resp.status_code}): {body}"
            )

        # 所有重试用尽
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _extract_text(response: dict) -> str:
        """从 OpenAI 格式的响应中提取文本内容。"""
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"无法解析 LLM 响应: {response}"
            ) from exc
