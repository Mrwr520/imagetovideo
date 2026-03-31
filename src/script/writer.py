"""Writer Agent：编剧，生成结构化剧本 JSON。"""

from __future__ import annotations

import json
import logging
import re

from src.character.models import Character
from src.script.models import Scene, Script

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个爆款短视频编剧。你的任务是根据给定的话题和角色，写一个 30 秒动漫短剧的剧本。

## 叙事公式（必须遵守）
- 第 1 个场景：悬念钩子（提问/冲突/反常识，3 秒抓住观众）
- 中间场景：故事展开（用具体画面讲道理，不要抽象说教）
- 最后 1 个场景：金句收尾（一句扎心的话，适合截图传播）

## 输出要求
- 严格输出 JSON，不要输出任何其他内容
- 场景数 3-5 个
- 每段旁白 10-40 个中文字，适合朗读
- image_desc 必须具体描述画面（谁、在哪、做什么、什么表情、什么光线）
- character 必须是给定角色列表中的名字
- emotion 从以下选择：neutral, happy, sad, angry, surprise, fear, tender"""

USER_TEMPLATE = """## 话题
{topic}

## 领域
{domain}

## 可用角色
{characters_desc}

## 参考素材
{search_context}

## 输出格式
```json
{{
  "title": "剧本标题（10字以内）",
  "scenes": [
    {{
      "narration": "旁白文本",
      "character": "角色名",
      "emotion": "情感",
      "image_desc": "画面描述（具体：谁在哪做什么，表情，光线，色调）"
    }}
  ]
}}
```"""


async def generate_script(
    llm_provider,
    topic: str,
    domain: str,
    characters: list[Character],
    search_context: str = "",
    revision_feedback: str = "",
) -> Script | None:
    """调用 LLM 生成剧本。

    Args:
        llm_provider: LLM provider
        topic: 话题
        domain: 领域
        characters: 角色列表
        search_context: 搜索素材
        revision_feedback: 修改意见（重写时传入）

    Returns:
        Script 或 None（解析失败时）
    """
    chars_desc = "\n".join(
        f"- {c.name}（{c.role_type}）：{c.appearance}，音色：{c.voice_type}"
        for c in characters
    )

    user_msg = USER_TEMPLATE.format(
        topic=topic,
        domain=domain,
        characters_desc=chars_desc,
        search_context=search_context or "（无搜索素材，请根据话题自由创作）",
    )

    if revision_feedback:
        user_msg += f"\n\n## 修改意见（请根据以下意见重写）\n{revision_feedback}"

    try:
        full_prompt = SYSTEM_PROMPT + "\n\n" + user_msg
        raw = await llm_provider.generate_narration([], full_prompt)
        return _parse_script(raw, topic, domain)
    except Exception:
        logger.warning("剧本生成失败", exc_info=True)
        return None


def _parse_script(raw: str, topic: str, domain: str) -> Script | None:
    """解析 LLM 返回的剧本 JSON。"""
    raw = raw.strip()

    # 提取 JSON 对象
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    scenes = []
    for s in data.get("scenes", []):
        scenes.append(Scene(
            narration=s.get("narration", ""),
            character=s.get("character", ""),
            emotion=s.get("emotion", "neutral"),
            image_desc=s.get("image_desc", ""),
        ))

    if not scenes:
        return None

    return Script(
        title=data.get("title", ""),
        topic=topic,
        domain=domain,
        scenes=scenes,
    )
