"""KeywordExtractor 单元测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.llm.base import BaseLLMProvider
from src.llm.keyword_extractor import KeywordExtractor, parse_keywords


# ---------------------------------------------------------------------------
# parse_keywords 独立函数测试
# ---------------------------------------------------------------------------


class TestParseKeywords:
    def test_valid_json_with_keywords(self):
        raw = '{"keywords": ["北京", "地震", "救援"]}'
        assert parse_keywords(raw) == ["北京", "地震", "救援"]

    def test_empty_string_returns_empty(self):
        assert parse_keywords("") == []

    def test_whitespace_only_returns_empty(self):
        assert parse_keywords("   ") == []

    def test_invalid_json_returns_empty(self):
        assert parse_keywords("not json at all") == []

    def test_json_without_keywords_key_returns_empty(self):
        assert parse_keywords('{"data": ["a", "b"]}') == []

    def test_keywords_not_a_list_returns_empty(self):
        assert parse_keywords('{"keywords": "just a string"}') == []

    def test_filters_non_string_elements(self):
        raw = '{"keywords": ["valid", 123, null, "also_valid"]}'
        assert parse_keywords(raw) == ["valid", "also_valid"]

    def test_json_with_extra_whitespace(self):
        raw = '  \n {"keywords": ["关键词"]}  \n '
        assert parse_keywords(raw) == ["关键词"]

    def test_empty_keywords_list(self):
        raw = '{"keywords": []}'
        assert parse_keywords(raw) == []

    def test_json_array_returns_empty(self):
        """顶层是数组而非对象时返回空列表。"""
        assert parse_keywords('["a", "b"]') == []


# ---------------------------------------------------------------------------
# KeywordExtractor.extract 测试
# ---------------------------------------------------------------------------


class _MockProvider(BaseLLMProvider):
    """用于测试的 mock LLM provider。"""

    def __init__(self, response: str | Exception):
        self._response = response

    async def generate_narration(self, images: list[Path], prompt: str) -> str:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class TestKeywordExtractorExtract:
    def test_successful_extraction(self):
        provider = _MockProvider('{"keywords": ["台风", "福建", "防汛"]}')
        extractor = KeywordExtractor(provider)
        result = asyncio.run(extractor.extract([Path("img1.png")]))
        assert result == ["台风", "福建", "防汛"]

    def test_llm_returns_empty_string(self):
        provider = _MockProvider("")
        extractor = KeywordExtractor(provider)
        result = asyncio.run(extractor.extract([Path("img1.png")]))
        assert result == []

    def test_llm_returns_invalid_json(self):
        provider = _MockProvider("I cannot extract keywords from this image.")
        extractor = KeywordExtractor(provider)
        result = asyncio.run(extractor.extract([Path("img1.png")]))
        assert result == []

    def test_llm_raises_exception(self):
        provider = _MockProvider(RuntimeError("API error"))
        extractor = KeywordExtractor(provider)
        result = asyncio.run(extractor.extract([Path("img1.png")]))
        assert result == []

    def test_llm_raises_timeout(self):
        provider = _MockProvider(TimeoutError("timed out"))
        extractor = KeywordExtractor(provider)
        result = asyncio.run(extractor.extract([Path("img1.png")]))
        assert result == []

    def test_prompt_contains_keyword_instruction(self):
        """验证发送给 LLM 的提示词包含关键词提取指令。"""
        captured_prompt = None

        class CapturingProvider(BaseLLMProvider):
            async def generate_narration(self, images, prompt):
                nonlocal captured_prompt
                captured_prompt = prompt
                return '{"keywords": ["test"]}'

        extractor = KeywordExtractor(CapturingProvider())
        asyncio.run(extractor.extract([Path("img.png")]))
        assert captured_prompt is not None
        assert "关键词" in captured_prompt
        assert "JSON" in captured_prompt
