"""LLM 适配器单元测试：BaseLLMProvider 和 OpenAICompatibleProvider。"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.llm.base import BaseLLMProvider
from src.llm.openai_compat import (
    OpenAICompatibleProvider,
    _build_messages,
    _encode_image,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_image(tmp_path: Path) -> Path:
    """创建一个最小的 PNG 文件用于测试。"""
    # 1x1 白色 PNG
    import struct, zlib
    def _minimal_png() -> bytes:
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
        raw = zlib.compress(b"\x00\xff\xff\xff")
        idat_crc = zlib.crc32(b"IDAT" + raw) & 0xFFFFFFFF
        idat = struct.pack(">I", len(raw)) + b"IDAT" + raw + struct.pack(">I", idat_crc)
        iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
        return sig + ihdr + idat + iend
    p = tmp_path / "test.png"
    p.write_bytes(_minimal_png())
    return p


@pytest.fixture()
def provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_base="https://api.example.com/v1",
        api_key="test-key-123",
        model="test-model",
    )


# ---------------------------------------------------------------------------
# BaseLLMProvider 抽象类测试
# ---------------------------------------------------------------------------

class TestBaseLLMProvider:
    def test_cannot_instantiate(self):
        """抽象基类不能直接实例化。"""
        with pytest.raises(TypeError):
            BaseLLMProvider()  # type: ignore[abstract]

    def test_subclass_must_implement(self):
        """子类必须实现 generate_narration。"""
        class Incomplete(BaseLLMProvider):
            pass
        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_valid_subclass(self):
        """正确实现抽象方法的子类可以实例化。"""
        class Valid(BaseLLMProvider):
            async def generate_narration(self, images, prompt):
                return "ok"
        instance = Valid()
        assert asyncio.run(instance.generate_narration([], "")) == "ok"


# ---------------------------------------------------------------------------
# _encode_image 测试
# ---------------------------------------------------------------------------

class TestEncodeImage:
    def test_png_encoding(self, tmp_image: Path):
        result = _encode_image(tmp_image)
        assert result.startswith("data:image/png;base64,")
        # 验证 base64 部分可以解码
        b64_part = result.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        assert decoded == tmp_image.read_bytes()

    def test_jpeg_encoding(self, tmp_path: Path):
        p = tmp_path / "photo.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
        result = _encode_image(p)
        assert result.startswith("data:image/jpeg;base64,")

    def test_webp_encoding(self, tmp_path: Path):
        p = tmp_path / "photo.webp"
        p.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
        result = _encode_image(p)
        assert result.startswith("data:image/webp;base64,")

    def test_unknown_extension_defaults_to_jpeg(self, tmp_path: Path):
        p = tmp_path / "photo.bmp"
        p.write_bytes(b"BM\x00\x00")
        result = _encode_image(p)
        # bmp has a known mime type, so it should use image/bmp or x-ms-bmp
        assert "base64," in result


# ---------------------------------------------------------------------------
# _build_messages 测试
# ---------------------------------------------------------------------------

class TestBuildMessages:
    def test_structure(self, tmp_image: Path):
        msgs = _build_messages([tmp_image], "describe this")
        assert len(msgs) == 2  # system + user
        # system message
        assert msgs[0]["role"] == "system"
        assert isinstance(msgs[0]["content"], str)
        # user message
        msg = msgs[1]
        assert msg["role"] == "user"
        content = msg["content"]
        assert len(content) == 2  # text + 1 image
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "describe this"
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/")

    def test_multiple_images(self, tmp_image: Path):
        msgs = _build_messages([tmp_image, tmp_image, tmp_image], "prompt")
        content = msgs[1]["content"]  # user message is at index 1
        assert len(content) == 4  # 1 text + 3 images


# ---------------------------------------------------------------------------
# OpenAICompatibleProvider 初始化测试
# ---------------------------------------------------------------------------

class TestProviderInit:
    def test_trailing_slash_stripped(self):
        p = OpenAICompatibleProvider("https://api.example.com/v1/", "key", "m")
        assert p.api_base == "https://api.example.com/v1"

    def test_attributes(self, provider: OpenAICompatibleProvider):
        assert provider.api_key == "test-key-123"
        assert provider.model == "test-model"


# ---------------------------------------------------------------------------
# generate_narration 成功场景
# ---------------------------------------------------------------------------

class TestGenerateNarrationSuccess:
    def _make_sse_response(self, text: str, status_code: int = 200, url: str = "https://api.example.com/v1/chat/completions"):
        """创建模拟 SSE 流式响应。"""
        import json as _json

        sse_lines = [
            f'data: {_json.dumps({"choices": [{"delta": {"content": text}}]})}',
            "data: [DONE]",
        ]

        class _MockStream:
            def __init__(self, lines, sc):
                self.status_code = sc
                self.text = ""
                self._lines = lines

            async def aiter_lines(self):
                for line in self._lines:
                    yield line

            async def aclose(self):
                pass

        return _MockStream(sse_lines, status_code)

    def test_returns_text(self, provider: OpenAICompatibleProvider, tmp_image: Path):
        """正常 200 流式响应应返回解说词文本。"""
        mock_resp = self._make_sse_response("这是一段解说词")

        async def _mock_send(self_client, request, **kwargs):
            return mock_resp

        with patch.object(httpx.AsyncClient, "send", _mock_send):
            result = asyncio.run(
                provider.generate_narration([tmp_image], "请描述图片")
            )

        assert result == "这是一段解说词"

    def test_request_url_and_headers(self, provider: OpenAICompatibleProvider, tmp_image: Path):
        """验证请求的 URL、headers 和 payload 结构。"""
        captured = {}
        mock_resp = self._make_sse_response("ok")

        original_build = httpx.AsyncClient.build_request

        def _capture_build(self_client, method, url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs.get("headers", {})
            captured["json"] = kwargs.get("json", {})
            return original_build(self_client, method, url, **kwargs)

        async def _mock_send(self_client, request, **kwargs):
            return mock_resp

        with patch.object(httpx.AsyncClient, "build_request", _capture_build):
            with patch.object(httpx.AsyncClient, "send", _mock_send):
                asyncio.run(provider.generate_narration([tmp_image], "prompt"))

        assert captured["url"] == "https://api.example.com/v1/chat/completions"
        assert captured["headers"]["Authorization"] == "Bearer test-key-123"
        assert captured["json"]["model"] == "test-model"
        assert len(captured["json"]["messages"]) == 2  # system + user


# ---------------------------------------------------------------------------
# 错误处理测试
# ---------------------------------------------------------------------------

def _make_error_stream(status_code: int, text: str = ""):
    """创建模拟错误响应（非流式）。"""
    class _MockStream:
        def __init__(self):
            self.status_code = status_code
            self.text = text

        async def aiter_lines(self):
            return
            yield  # make it an async generator

        async def aclose(self):
            pass

    return _MockStream()


def _make_sse_stream(text: str):
    """创建模拟 SSE 流式成功响应。"""
    import json as _json
    sse_lines = [
        f'data: {_json.dumps({"choices": [{"delta": {"content": text}}]})}',
        "data: [DONE]",
    ]

    class _MockStream:
        def __init__(self):
            self.status_code = 200
            self.text = ""

        async def aiter_lines(self):
            for line in sse_lines:
                yield line

        async def aclose(self):
            pass

    return _MockStream()


class TestErrorHandling:
    def test_auth_failure_401(self, provider: OpenAICompatibleProvider, tmp_image: Path):
        """401 应抛出 PermissionError。"""
        async def _mock_send(self_client, request, **kwargs):
            return _make_error_stream(401, "Unauthorized")

        with patch.object(httpx.AsyncClient, "send", _mock_send):
            with pytest.raises(PermissionError, match="API 密钥无效"):
                asyncio.run(provider.generate_narration([tmp_image], "p"))

    def test_timeout(self, provider: OpenAICompatibleProvider, tmp_image: Path):
        """超时应抛出 TimeoutError。"""
        async def _mock_send(self_client, request, **kwargs):
            raise httpx.TimeoutException("timed out")

        with patch.object(httpx.AsyncClient, "send", _mock_send):
            with pytest.raises(TimeoutError, match="超时"):
                asyncio.run(provider.generate_narration([tmp_image], "p"))

    def test_rate_limit_429_retries_then_fails(self, provider: OpenAICompatibleProvider, tmp_image: Path):
        """429 应重试 3 次后抛出 RuntimeError。"""
        call_count = 0

        async def _mock_send(self_client, request, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_error_stream(429, "Too Many Requests")

        with patch.object(httpx.AsyncClient, "send", _mock_send):
            with patch("src.llm.openai_compat.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(RuntimeError, match="速率限制"):
                    asyncio.run(provider.generate_narration([tmp_image], "p"))

        assert call_count == 3  # 重试了 3 次

    def test_rate_limit_429_succeeds_on_retry(self, provider: OpenAICompatibleProvider, tmp_image: Path):
        """429 后重试成功应返回正常结果。"""
        call_count = 0

        async def _mock_send(self_client, request, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return _make_error_stream(429, "Too Many Requests")
            return _make_sse_stream("重试成功")

        with patch.object(httpx.AsyncClient, "send", _mock_send):
            with patch("src.llm.openai_compat.asyncio.sleep", new_callable=AsyncMock):
                result = asyncio.run(provider.generate_narration([tmp_image], "p"))

        assert result == "重试成功"
        assert call_count == 3

    def test_other_http_error(self, provider: OpenAICompatibleProvider, tmp_image: Path):
        """其他 HTTP 错误应抛出 RuntimeError。"""
        async def _mock_send(self_client, request, **kwargs):
            return _make_error_stream(500, "Internal Server Error")

        with patch.object(httpx.AsyncClient, "send", _mock_send):
            with pytest.raises(RuntimeError, match="HTTP 500"):
                asyncio.run(provider.generate_narration([tmp_image], "p"))

    def test_malformed_response(self, provider: OpenAICompatibleProvider, tmp_image: Path):
        """流式响应为空（无有效 delta）应返回空字符串。"""
        # With streaming, a malformed response just yields no content
        async def _mock_send(self_client, request, **kwargs):
            class _EmptyStream:
                status_code = 200
                text = ""
                async def aiter_lines(self_inner):
                    yield 'data: {"bad": "response"}'
                    yield "data: [DONE]"
                async def aclose(self_inner):
                    pass
            return _EmptyStream()

        with patch.object(httpx.AsyncClient, "send", _mock_send):
            result = asyncio.run(provider.generate_narration([tmp_image], "p"))

        # Streaming parser skips malformed chunks, returns empty string
        assert result == ""


# ---------------------------------------------------------------------------
# WenxinProvider 测试
# ---------------------------------------------------------------------------

from src.llm.wenxin import (
    WenxinProvider,
    _encode_image_base64,
)


@pytest.fixture()
def wenxin_provider() -> WenxinProvider:
    return WenxinProvider(
        api_key="test-api-key",
        secret_key="test-secret-key",
        model="ernie-bot-4",
    )


class TestEncodeImageBase64:
    def test_png_returns_base64_and_mime(self, tmp_image: Path):
        b64, mime = _encode_image_base64(tmp_image)
        assert mime == "image/png"
        decoded = base64.b64decode(b64)
        assert decoded == tmp_image.read_bytes()

    def test_jpeg_mime(self, tmp_path: Path):
        p = tmp_path / "photo.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
        b64, mime = _encode_image_base64(p)
        assert mime == "image/jpeg"
        assert len(b64) > 0

    def test_unknown_extension_defaults_to_jpeg(self, tmp_path: Path):
        p = tmp_path / "photo.xyz"
        p.write_bytes(b"some-data")
        _, mime = _encode_image_base64(p)
        assert mime == "image/jpeg"


class TestWenxinProviderInit:
    def test_attributes(self, wenxin_provider: WenxinProvider):
        assert wenxin_provider.api_key == "test-api-key"
        assert wenxin_provider.secret_key == "test-secret-key"
        assert wenxin_provider.model == "ernie-bot-4"
        assert wenxin_provider._access_token is None

    def test_is_base_llm_provider(self, wenxin_provider: WenxinProvider):
        assert isinstance(wenxin_provider, BaseLLMProvider)


class TestWenxinBuildPayload:
    def test_payload_structure(self, tmp_image: Path):
        payload = WenxinProvider._build_payload([tmp_image], "描述图片")
        assert "messages" in payload
        msgs = payload["messages"]
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        content = msgs[0]["content"]
        assert len(content) == 2  # text + 1 image
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "描述图片"
        assert content[1]["type"] == "image"
        assert len(content[1]["image"]) > 0  # base64 string

    def test_multiple_images(self, tmp_image: Path):
        payload = WenxinProvider._build_payload(
            [tmp_image, tmp_image, tmp_image], "prompt"
        )
        content = payload["messages"][0]["content"]
        assert len(content) == 4  # 1 text + 3 images


class TestWenxinGetAccessToken:
    def test_success(self, wenxin_provider: WenxinProvider):
        """成功获取 access_token。"""
        async def _mock_post(url, **kwargs):
            return httpx.Response(
                200,
                json={"access_token": "test-token-abc"},
                request=httpx.Request("POST", url),
            )

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            token = asyncio.run(wenxin_provider._get_access_token())

        assert token == "test-token-abc"
        assert wenxin_provider._access_token == "test-token-abc"

    def test_caches_token(self, wenxin_provider: WenxinProvider):
        """第二次调用应使用缓存的 token，不再发请求。"""
        wenxin_provider._access_token = "cached-token"
        token = asyncio.run(wenxin_provider._get_access_token())
        assert token == "cached-token"

    def test_auth_failure_no_token(self, wenxin_provider: WenxinProvider):
        """响应中无 access_token 应抛出 PermissionError。"""
        async def _mock_post(url, **kwargs):
            return httpx.Response(
                200,
                json={"error": "invalid_client", "error_description": "密钥无效"},
                request=httpx.Request("POST", url),
            )

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            with pytest.raises(PermissionError, match="密钥无效"):
                asyncio.run(wenxin_provider._get_access_token())

    def test_auth_http_error(self, wenxin_provider: WenxinProvider):
        """鉴权 HTTP 错误应抛出 RuntimeError。"""
        async def _mock_post(url, **kwargs):
            return httpx.Response(
                500, text="Server Error",
                request=httpx.Request("POST", url),
            )

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            with pytest.raises(RuntimeError, match="鉴权失败"):
                asyncio.run(wenxin_provider._get_access_token())

    def test_auth_timeout(self, wenxin_provider: WenxinProvider):
        """鉴权超时应抛出 TimeoutError。"""
        async def _mock_post(url, **kwargs):
            raise httpx.TimeoutException("timed out")

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            with pytest.raises(TimeoutError, match="鉴权请求超时"):
                asyncio.run(wenxin_provider._get_access_token())


class TestWenxinGenerateNarration:
    def test_success(self, wenxin_provider: WenxinProvider, tmp_image: Path):
        """正常流程：先获取 token，再调用 API 返回解说词。"""
        call_count = 0

        async def _mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "oauth" in url:
                return httpx.Response(
                    200,
                    json={"access_token": "tok-123"},
                    request=httpx.Request("POST", url),
                )
            return httpx.Response(
                200,
                json={"result": "这是文心一言生成的解说词"},
                request=httpx.Request("POST", url),
            )

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            result = asyncio.run(
                wenxin_provider.generate_narration([tmp_image], "请描述图片")
            )

        assert result == "这是文心一言生成的解说词"
        assert call_count == 2  # 1 auth + 1 api

    def test_uses_cached_token(self, wenxin_provider: WenxinProvider, tmp_image: Path):
        """已有缓存 token 时不再请求鉴权。"""
        wenxin_provider._access_token = "cached-tok"
        call_count = 0

        async def _mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            assert "oauth" not in url  # 不应调用鉴权
            assert "access_token=cached-tok" in url
            return httpx.Response(
                200,
                json={"result": "解说词"},
                request=httpx.Request("POST", url),
            )

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            result = asyncio.run(
                wenxin_provider.generate_narration([tmp_image], "prompt")
            )

        assert result == "解说词"
        assert call_count == 1

    def test_api_url_contains_model(self, wenxin_provider: WenxinProvider, tmp_image: Path):
        """API URL 应包含模型名称。"""
        wenxin_provider._access_token = "tok"
        captured_url = None

        async def _mock_post(url, **kwargs):
            nonlocal captured_url
            captured_url = url
            return httpx.Response(
                200,
                json={"result": "ok"},
                request=httpx.Request("POST", url),
            )

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            asyncio.run(wenxin_provider.generate_narration([tmp_image], "p"))

        assert "ernie-bot-4" in captured_url

    def test_api_timeout(self, wenxin_provider: WenxinProvider, tmp_image: Path):
        """API 请求超时应抛出 TimeoutError。"""
        wenxin_provider._access_token = "tok"

        async def _mock_post(url, **kwargs):
            raise httpx.TimeoutException("timed out")

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            with pytest.raises(TimeoutError, match="请求超时"):
                asyncio.run(wenxin_provider.generate_narration([tmp_image], "p"))

    def test_api_http_error(self, wenxin_provider: WenxinProvider, tmp_image: Path):
        """API 非 200 响应应抛出 RuntimeError。"""
        wenxin_provider._access_token = "tok"

        async def _mock_post(url, **kwargs):
            return httpx.Response(
                500, text="Internal Error",
                request=httpx.Request("POST", url),
            )

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            with pytest.raises(RuntimeError, match="HTTP 500"):
                asyncio.run(wenxin_provider.generate_narration([tmp_image], "p"))

    def test_business_error_in_200(self, wenxin_provider: WenxinProvider, tmp_image: Path):
        """200 响应中包含 error_code 应抛出 RuntimeError。"""
        wenxin_provider._access_token = "tok"

        async def _mock_post(url, **kwargs):
            return httpx.Response(
                200,
                json={"error_code": 17, "error_msg": "每日调用量超限"},
                request=httpx.Request("POST", url),
            )

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            with pytest.raises(RuntimeError, match="每日调用量超限"):
                asyncio.run(wenxin_provider.generate_narration([tmp_image], "p"))

    def test_expired_token_clears_cache(self, wenxin_provider: WenxinProvider, tmp_image: Path):
        """error_code=110 应清除缓存的 token 并抛出 PermissionError。"""
        wenxin_provider._access_token = "old-tok"

        async def _mock_post(url, **kwargs):
            return httpx.Response(
                200,
                json={"error_code": 110, "error_msg": "token 已过期"},
                request=httpx.Request("POST", url),
            )

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            with pytest.raises(PermissionError, match="过期"):
                asyncio.run(wenxin_provider.generate_narration([tmp_image], "p"))

        assert wenxin_provider._access_token is None

    def test_malformed_response(self, wenxin_provider: WenxinProvider, tmp_image: Path):
        """响应中无 result 字段应抛出 RuntimeError。"""
        wenxin_provider._access_token = "tok"

        async def _mock_post(url, **kwargs):
            return httpx.Response(
                200,
                json={"bad": "response"},
                request=httpx.Request("POST", url),
            )

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            with pytest.raises(RuntimeError, match="无法解析"):
                asyncio.run(wenxin_provider.generate_narration([tmp_image], "p"))

    def test_rate_limit_429_retries(self, wenxin_provider: WenxinProvider, tmp_image: Path):
        """429 应重试后成功。"""
        wenxin_provider._access_token = "tok"
        call_count = 0

        async def _mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(
                    429, text="Too Many Requests",
                    request=httpx.Request("POST", url),
                )
            return httpx.Response(
                200,
                json={"result": "重试成功"},
                request=httpx.Request("POST", url),
            )

        with patch.object(httpx.AsyncClient, "post", side_effect=_mock_post):
            with patch("src.llm.wenxin.asyncio.sleep", new_callable=AsyncMock):
                result = asyncio.run(
                    wenxin_provider.generate_narration([tmp_image], "p")
                )

        assert result == "重试成功"
        assert call_count == 3


# ---------------------------------------------------------------------------
# LLMAdapter 测试
# ---------------------------------------------------------------------------

from src.llm.adapter import LLMAdapter, _DEFAULT_PROMPT_TEMPLATE


def _make_config(**overrides) -> dict:
    """构造一个完整的 LLM 配置字典用于测试。"""
    cfg = {
        "qwen": {"api_key": "qwen-key", "default_model": "qwen-vl-max", "models": []},
        "deepseek": {"api_key": "ds-key", "default_model": "deepseek-chat", "models": []},
        "glm": {"api_key": "glm-key", "default_model": "glm-4v", "models": []},
        "wenxin": {
            "api_key": "wx-key",
            "secret_key": "wx-secret",
            "default_model": "ernie-bot-4",
            "models": [],
        },
        "openai_compatible": {
            "api_base": "https://custom.api.com/v1",
            "api_key": "oai-key",
            "default_model": "custom-model",
            "models": [],
        },
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture()
def full_config() -> dict:
    return _make_config()


@pytest.fixture()
def adapter(full_config: dict) -> LLMAdapter:
    return LLMAdapter(full_config)


# ---------------------------------------------------------------------------
# __init__ 测试
# ---------------------------------------------------------------------------

class TestLLMAdapterInit:
    def test_stores_config(self, adapter: LLMAdapter, full_config: dict):
        assert adapter._config is full_config


# ---------------------------------------------------------------------------
# get_provider 测试
# ---------------------------------------------------------------------------

class TestGetProvider:
    def test_qwen_returns_openai_compatible(self, adapter: LLMAdapter):
        p = adapter.get_provider("qwen")
        assert isinstance(p, OpenAICompatibleProvider)
        assert p.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert p.api_key == "qwen-key"
        assert p.model == "qwen-vl-max"

    def test_deepseek_returns_openai_compatible(self, adapter: LLMAdapter):
        p = adapter.get_provider("deepseek")
        assert isinstance(p, OpenAICompatibleProvider)
        assert p.api_base == "https://api.deepseek.com/v1"
        assert p.model == "deepseek-chat"

    def test_glm_returns_openai_compatible(self, adapter: LLMAdapter):
        p = adapter.get_provider("glm")
        assert isinstance(p, OpenAICompatibleProvider)
        assert p.api_base == "https://open.bigmodel.cn/api/paas/v4"
        assert p.model == "glm-4v"

    def test_wenxin_returns_wenxin_provider(self, adapter: LLMAdapter):
        p = adapter.get_provider("wenxin")
        assert isinstance(p, WenxinProvider)
        assert p.api_key == "wx-key"
        assert p.secret_key == "wx-secret"
        assert p.model == "ernie-bot-4"

    def test_openai_compatible_returns_provider(self, adapter: LLMAdapter):
        p = adapter.get_provider("openai_compatible")
        assert isinstance(p, OpenAICompatibleProvider)
        assert p.api_base == "https://custom.api.com/v1"
        assert p.model == "custom-model"

    def test_model_override(self, adapter: LLMAdapter):
        """显式传入 model 应覆盖配置中的 default_model。"""
        p = adapter.get_provider("qwen", model="qwen-vl-plus")
        assert p.model == "qwen-vl-plus"

    def test_unknown_provider_raises(self, adapter: LLMAdapter):
        with pytest.raises(ValueError, match="未知的 LLM provider"):
            adapter.get_provider("nonexistent")

    def test_unconfigured_provider_raises(self):
        """配置中缺少该 provider 段应抛出 ValueError。"""
        adapter = LLMAdapter({})
        with pytest.raises(ValueError, match="未在配置中找到"):
            adapter.get_provider("qwen")


# ---------------------------------------------------------------------------
# list_models 测试
# ---------------------------------------------------------------------------

class TestListModels:
    def test_default_models_returned(self, adapter: LLMAdapter):
        models = adapter.list_models("qwen")
        assert models == ["qwen-vl-max", "qwen-vl-plus", "qwen-vl-max-latest"]

    def test_custom_models_merged(self):
        """配置中的自定义模型应追加到默认列表后面。"""
        cfg = _make_config(
            qwen={"api_key": "k", "default_model": "qwen-vl-max",
                   "models": ["qwen-custom-1", "qwen-custom-2"]}
        )
        adapter = LLMAdapter(cfg)
        models = adapter.list_models("qwen")
        assert "qwen-custom-1" in models
        assert "qwen-custom-2" in models
        # 默认模型也在
        assert "qwen-vl-max" in models

    def test_duplicates_removed(self):
        """默认和自定义列表中的重复模型应去重。"""
        cfg = _make_config(
            qwen={"api_key": "k", "default_model": "qwen-vl-max",
                   "models": ["qwen-vl-max", "qwen-new"]}
        )
        adapter = LLMAdapter(cfg)
        models = adapter.list_models("qwen")
        assert models.count("qwen-vl-max") == 1
        assert "qwen-new" in models

    def test_openai_compatible_empty_defaults(self, adapter: LLMAdapter):
        """openai_compatible 默认模型列表为空。"""
        models = adapter.list_models("openai_compatible")
        assert models == []

    def test_openai_compatible_with_custom(self):
        cfg = _make_config(
            openai_compatible={
                "api_base": "https://x.com/v1", "api_key": "k",
                "default_model": "m", "models": ["model-a", "model-b"],
            }
        )
        adapter = LLMAdapter(cfg)
        models = adapter.list_models("openai_compatible")
        assert models == ["model-a", "model-b"]

    def test_unknown_provider_raises(self, adapter: LLMAdapter):
        with pytest.raises(ValueError, match="未知的 LLM provider"):
            adapter.list_models("nonexistent")

    def test_unconfigured_provider_returns_defaults(self):
        """provider 未在配置中但已注册，应返回默认模型列表。"""
        adapter = LLMAdapter({})
        models = adapter.list_models("qwen")
        assert models == ["qwen-vl-max", "qwen-vl-plus", "qwen-vl-max-latest"]


# ---------------------------------------------------------------------------
# list_providers 测试
# ---------------------------------------------------------------------------

class TestListProviders:
    def test_all_configured(self, adapter: LLMAdapter):
        providers = adapter.list_providers()
        assert set(providers) == {"qwen", "deepseek", "glm", "wenxin", "openai_compatible"}

    def test_empty_api_key_excluded(self):
        """api_key 为空字符串的 provider 不应出现在列表中。"""
        cfg = _make_config(
            qwen={"api_key": "", "default_model": "m", "models": []},
            deepseek={"api_key": "valid", "default_model": "m", "models": []},
        )
        adapter = LLMAdapter(cfg)
        providers = adapter.list_providers()
        assert "qwen" not in providers
        assert "deepseek" in providers

    def test_missing_config_excluded(self):
        """配置中完全缺失的 provider 不应出现在列表中。"""
        adapter = LLMAdapter({})
        assert adapter.list_providers() == []

    def test_none_api_key_excluded(self):
        """api_key 为 None 的 provider 不应出现在列表中。"""
        cfg = _make_config(
            qwen={"api_key": None, "default_model": "m", "models": []},
        )
        adapter = LLMAdapter(cfg)
        assert "qwen" not in adapter.list_providers()


# ---------------------------------------------------------------------------
# render_prompt 测试
# ---------------------------------------------------------------------------

class TestRenderPrompt:
    def test_default_template(self, adapter: LLMAdapter):
        result = adapter.render_prompt(style="搞笑", duration=30, tone="活泼")
        assert "搞笑" in result
        assert "30" in result
        assert "活泼" in result

    def test_default_parameter_values(self, adapter: LLMAdapter):
        """不传参数时使用默认值。"""
        result = adapter.render_prompt()
        assert "专业自信" in result
        assert "60" in result
        assert "沉稳可靠、有说服力" in result

    def test_delegates_to_prompt_builder(self, adapter: LLMAdapter):
        """render_prompt 应委托给 PromptBuilder，生成包含参数的提示词。"""
        result = adapter.render_prompt(style="严肃", duration=120, tone="正式")
        assert "严肃" in result
        assert "120" in result
        assert "正式" in result

    def test_news_mode_with_search_context(self, adapter: LLMAdapter):
        """新闻解说模式应包含搜索上下文。"""
        from src.narration_mode import NarrationMode
        result = adapter.render_prompt(
            mode=NarrationMode.NEWS_COMMENTARY,
            search_context="最新新闻：测试新闻内容",
            duration=90,
        )
        assert "最新新闻：测试新闻内容" in result
        assert "90" in result
        assert "新闻" in result

    def test_no_prompt_template_uses_builtin(self):
        """配置中无 prompt_template 段时使用内置默认模板。"""
        adapter = LLMAdapter({})
        result = adapter.render_prompt(style="温馨", duration=45, tone="柔和")
        assert "温馨" in result
        assert "45" in result
        assert "柔和" in result

    def test_duration_as_string(self, adapter: LLMAdapter):
        """duration 可以是字符串。"""
        result = adapter.render_prompt(duration="90")
        assert "90" in result
