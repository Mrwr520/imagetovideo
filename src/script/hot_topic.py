"""热点搜索 Agent：搜索领域热门话题并提取适合做短剧的选题。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TopicItem:
    """单个热门话题。"""
    title: str
    angle: str  # 切入角度
    score: float  # 热度评分 0-10
    reason: str  # 为什么适合做短剧


EXTRACT_PROMPT = """你是一个短视频选题专家。我给你一些搜索结果，请从中提取 3-5 个最适合做 30 秒动漫短剧的话题。

要求：
1. 每个话题必须有故事性（能用 3-5 个画面讲清楚）
2. 每个话题必须有情感冲击力（能让观众产生共鸣）
3. 每个话题必须有一个核心道理或金句
4. 优先选择当前讨论度高的话题

请严格按以下 JSON 格式输出，不要输出任何其他内容：
[
  {{"title": "话题标题（10字以内）", "angle": "切入角度（20字以内）", "score": 8.5, "reason": "为什么适合做短剧（30字以内）"}}
]"""


async def search_hot_topics(
    searcher,
    llm_provider,
    domain_name: str,
    sub_domain: str,
    search_template: str,
) -> list[TopicItem]:
    """搜索热点并提取话题。

    Args:
        searcher: WebSearcher 实例
        llm_provider: LLM provider 实例（需要有 generate 方法）
        domain_name: 领域名称
        sub_domain: 子领域
        search_template: 搜索关键词模板

    Returns:
        话题列表
    """
    # 构建搜索关键词
    query = search_template.replace("{sub}", sub_domain)
    logger.info("搜索热点: %s", query)

    # 搜索
    results = await searcher.search_text(query)
    if not results:
        return []

    # 格式化搜索结果
    context = "\n".join(
        f"- {r.get('title', '')}: {r.get('snippet', '')}"
        for r in results[:10]
    )

    # LLM 提取话题
    prompt = f"领域：{domain_name} - {sub_domain}\n\n搜索结果：\n{context}\n\n{EXTRACT_PROMPT}"

    try:
        raw = await llm_provider.generate_text(prompt)
        topics = _parse_topics(raw)
        return topics
    except Exception:
        logger.warning("话题提取失败", exc_info=True)
        return []


def _parse_topics(raw: str) -> list[TopicItem]:
    """解析 LLM 返回的话题 JSON。"""
    import re

    raw = raw.strip()

    # 尝试提取 JSON 数组
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            items = json.loads(match.group())
            return [
                TopicItem(
                    title=item.get("title", ""),
                    angle=item.get("angle", ""),
                    score=float(item.get("score", 5.0)),
                    reason=item.get("reason", ""),
                )
                for item in items
                if item.get("title")
            ]
        except (json.JSONDecodeError, ValueError):
            pass

    return []
