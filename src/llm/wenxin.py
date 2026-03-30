"""WenxinProvider：百度文心一言 LLM Provider。

使用独立的 OAuth 鉴权流程和百度专有 API 格式，不兼容 OpenAI 接口。
鉴权流程：通过 api_key + secret_key 获取 access_token，再用 token 调用模型 API。
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

_TIMEOUT = 30.0  # 请求超时（秒）
_MAX_RETRIES = 3  # 速率限制最大重试次数
_RETRY_WAIT = 1.0  # 重试等待基数（秒），按指数退避

_OAUTH_URL = "https://aip.baidubce.com/oauth/2.0/token"
_API_BASE = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat"


def _encode_image_base64(image_path: Path) -> tuple[str, str]:
    """将图片文件编码为 base64 字符串，并返回 MIME 类型。

    Returns:
        (base64_string, mime_type) 元组。
    """
    mime_type, _ = mimetypes.guess_type(str(image_path))
    if mime_type is None:
        suffix = image_path.suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp",
        }
        mime_type = mime_map.get(suffix, "image/jpeg")

    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    return b64, mime_type


class WenxinProvider(BaseLLMProvider):
    """百度文心一言，使用独立的鉴权和 API 格式。

    鉴权方式：通过 api_key 和 secret_key 向百度 OAuth 端点获取 access_token，
    后续请求通过 query 参数 ``?access_token=xxx`` 传递鉴权信息。

    API 格式：请求体为百度专有的 messages 格式，图片以 base64 嵌入 content 中。
    """

    def __init__(self, api_key: str, secret_key: str, model: str) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self.model = model
        self._access_token: str | None = None

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def generate_narration(self, images: list[Path], prompt: str) -> str:
        """将图片编码为 base64，通过文心一言 API 发送请求并返回解说词。"""
        access_token = await self._get_access_token()
        url = f"{_API_BASE}/{self.model}?access_token={access_token}"

        payload = self._build_payload(images, prompt)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request_with_retry(client, url, payload)

        return self._extract_text(response)

    # ------------------------------------------------------------------
    # 鉴权
    # ------------------------------------------------------------------

    async def _get_access_token(self) -> str:
        """通过 api_key + secret_key 获取 access_token。"""
        if self._access_token is not None:
            return self._access_token

        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        }

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                resp = await client.post(_OAUTH_URL, params=params)
            except httpx.TimeoutException as exc:
                raise TimeoutError(
                    f"文心一言鉴权请求超时（{_TIMEOUT}秒），请稍后重试"
                ) from exc

            if resp.status_code != 200:
                raise RuntimeError(
                    f"文心一言鉴权失败 (HTTP {resp.status_code}): {resp.text}"
                )

            data = resp.json()

        if "access_token" not in data:
            error_desc = data.get("error_description", "未知错误")
            raise PermissionError(
                f"文心一言鉴权失败: {error_desc}，请检查 api_key 和 secret_key"
            )

        self._access_token = data["access_token"]
        return self._access_token

    # ------------------------------------------------------------------
    # 请求构造
    # ------------------------------------------------------------------

    @staticmethod
    def _build_payload(images: list[Path], prompt: str) -> dict:
        """构造文心一言 API 请求体。

        文心一言多模态格式：messages 中 content 为文本，图片通过
        content 中嵌入 base64 编码的图片数据。
        """
        # 构造包含图片的 content 部分
        content_parts: list[dict] = [{"type": "text", "text": prompt}]
        for img in images:
            b64, mime_type = _encode_image_base64(img)
            content_parts.append({
                "type": "image",
                "image": b64,
            })

        return {
            "messages": [
                {"role": "user", "content": content_parts},
            ],
        }

    # ------------------------------------------------------------------
    # 请求发送与重试
    # ------------------------------------------------------------------

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: dict,
    ) -> dict:
        """发送 POST 请求，遇到速率限制时指数退避重试。"""
        headers = {"Content-Type": "application/json"}
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                raise TimeoutError(
                    f"文心一言请求超时（{_TIMEOUT}秒），请稍后重试"
                ) from exc

            if resp.status_code != 200:
                if resp.status_code == 429:
                    wait = _RETRY_WAIT * (2 ** attempt)
                    logger.warning(
                        "速率限制 (429)，%s 秒后重试 (%d/%d)",
                        wait, attempt + 1, _MAX_RETRIES,
                    )
                    last_exc = RuntimeError(
                        f"速率限制：已重试 {_MAX_RETRIES} 次仍失败"
                    )
                    await asyncio.sleep(wait)
                    continue

                raise RuntimeError(
                    f"文心一言 API 请求失败 (HTTP {resp.status_code}): {resp.text}"
                )

            data = resp.json()

            # 文心一言在 200 响应中也可能返回业务错误
            if "error_code" in data:
                error_msg = data.get("error_msg", "未知错误")
                error_code = data["error_code"]

                # 110 = access_token 过期，清除缓存
                if error_code == 110:
                    self._access_token = None
                    raise PermissionError(
                        f"文心一言 access_token 已过期: {error_msg}"
                    )

                raise RuntimeError(
                    f"文心一言 API 业务错误 (code={error_code}): {error_msg}"
                )

            return data

        # 所有重试用尽
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # 响应解析
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(response: dict) -> str:
        """从文心一言响应中提取文本内容。"""
        try:
            return response["result"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                f"无法解析文心一言响应: {response}"
            ) from exc
