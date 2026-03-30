"""KeywordExtractor：从图片中提取新闻关键词。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .base import BaseLLMProvider

logger = logging.getLogger(__name__)

# 关键词提取提示词
_KEYWORD_EXTRACTION_PROMPT = (
    "请仔细观察这些图片，提取其中与新闻事件相关的关键词。\n"
    "要求：\n"
    "1. 提取3到10个关键词\n"
    "2. 关键词应该是具体的人名、地名、事件名、机构名等\n"
    '3. 按以下JSON格式返回：{"keywords": ["关键词1", "关键词2", ...]}\n'
    "4. 只返回JSON，不要其他内容"
)


def parse_keywords(raw: str) -> list[str]:
    """解析 LLM 返回的关键词 JSON 字符串。

    Args:
        raw: LLM 返回的原始字符串，期望格式为 ``{"keywords": [...]}``.

    Returns:
        关键词字符串列表。解析失败或为空时返回空列表。
    """
    if not raw or not raw.strip():
        logger.warning("关键词提取：LLM 返回空响应")
        return []

    try:
        data = json.loads(raw.strip())
    except (json.JSONDecodeError, TypeError):
        logger.warning("关键词提取：无法解析 JSON 响应: %s", raw[:200])
        return []

    if not isinstance(data, dict):
        logger.warning("关键词提取：响应不是 JSON 对象: %s", raw[:200])
        return []

    keywords = data.get("keywords")
    if not isinstance(keywords, list):
        logger.warning("关键词提取：响应中缺少 keywords 列表: %s", raw[:200])
        return []

    # 过滤非字符串元素，只保留字符串
    result = [kw for kw in keywords if isinstance(kw, str)]
    return result


class KeywordExtractor:
    """从图片中提取新闻关键词。"""

    def __init__(self, llm_provider: BaseLLMProvider) -> None:
        self._provider = llm_provider

    async def extract(self, images: list[Path]) -> list[str]:
        """发送图片到 LLM，提取 3-10 个关键词。

        Returns:
            关键词字符串列表。提取失败时返回空列表。
        """
        try:
            raw = await self._provider.generate_narration(
                images, _KEYWORD_EXTRACTION_PROMPT
            )
        except Exception:
            logger.warning("关键词提取：LLM 调用失败", exc_info=True)
            return []

        return parse_keywords(raw)
