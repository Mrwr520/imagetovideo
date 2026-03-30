"""WebSearcher：使用 DuckDuckGo 搜索网络信息。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """单条搜索结果。"""

    title: str
    snippet: str
    url: str


class WebSearcher:
    """使用 DuckDuckGo API 搜索网络信息。"""

    def __init__(self, timeout: float = 10.0, max_results: int = 10) -> None:
        self._timeout = timeout
        self._max_results = max_results

    async def search(self, keywords: list[str]) -> list[SearchResult]:
        """根据关键词搜索网络，返回结构化结果。

        将关键词用空格连接作为搜索查询。
        搜索失败或超时时返回空列表并记录警告日志。

        Args:
            keywords: 搜索关键词列表。

        Returns:
            SearchResult 列表，最多 max_results 条。
        """
        if not keywords:
            return []

        query = " ".join(keywords)

        try:
            from duckduckgo_search import DDGS

            with DDGS(timeout=self._timeout) as ddgs:
                raw_results = list(ddgs.text(query, max_results=self._max_results))
        except Exception:
            logger.warning("网络搜索失败", exc_info=True)
            return []

        results: list[SearchResult] = []
        for item in raw_results[: self._max_results]:
            try:
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        snippet=item.get("body", ""),
                        url=item.get("href", ""),
                    )
                )
            except Exception:
                logger.warning("解析搜索结果条目失败", exc_info=True)
                continue

        return results

    def format_for_prompt(self, results: list[SearchResult]) -> str:
        """将搜索结果序列化为适合 LLM 提示词的文本格式。

        Args:
            results: SearchResult 列表。

        Returns:
            格式化的文本字符串。空列表返回空字符串。
        """
        if not results:
            return ""

        lines: list[str] = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.title}")
            lines.append(f"   {r.snippet}")
            lines.append("")

        return "\n".join(lines).rstrip()
