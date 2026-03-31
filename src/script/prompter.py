"""Prompter Agent：将画面描述转为精确的 AI 出图提示词。"""

from __future__ import annotations

import json
import logging
import re

from src.character.models import Character
from src.script.models import Script

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个 AI 出图提示词工程师。你的任务是把剧本中的画面描述转为精确的 AI 绘图提示词。

## 规则
1. 每个场景的提示词必须包含：风格标签 + 角色外貌 + 动作表情 + 场景环境 + 构图 + 光影色调
2. 所有场景使用统一的风格标签（保证画风一致）
3. 角色外貌描述必须完全一致（从角色配置中复制，不要自由发挥）
4. 提示词用英文输出（AI 出图模型英文效果更好）
5. 每个提示词末尾加上 "high quality, detailed, 4k"

## 输出格式
严格输出 JSON 数组，每项对应一个场景的提示词：
["prompt for scene 1", "prompt for scene 2", ...]"""


async def generate_prompts(
    llm_provider,
    script: Script,
    characters: list[Character],
) -> list[str]:
    """为剧本每个场景生成出图提示词。"""
    chars_desc = "\n".join(
        f"- {c.name}: {c.appearance} (style: {c.style_tags})"
        for c in characters
    )

    scenes_desc = "\n".join(
        f"Scene {i+1} ({s.character}, {s.emotion}): {s.image_desc}"
        for i, s in enumerate(script.scenes)
    )

    user_msg = (
        f"## 统一画风\n{script.style}\n\n"
        f"## 角色外貌（必须严格使用）\n{chars_desc}\n\n"
        f"## 场景画面描述\n{scenes_desc}"
    )

    try:
        full_prompt = SYSTEM_PROMPT + "\n\n" + user_msg
        raw = await llm_provider.generate_narration([], full_prompt)
        prompts = _parse_prompts(raw, len(script.scenes))

        # 写回 script
        for i, prompt in enumerate(prompts):
            if i < len(script.scenes):
                script.scenes[i].image_prompt = prompt

        return prompts
    except Exception:
        logger.warning("提示词生成失败", exc_info=True)
        # 回退：用 image_desc 作为提示词
        return [s.image_desc for s in script.scenes]


def _parse_prompts(raw: str, expected_count: int) -> list[str]:
    """解析提示词数组。"""
    raw = raw.strip()
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            prompts = json.loads(match.group())
            if isinstance(prompts, list) and len(prompts) >= expected_count:
                return [str(p) for p in prompts[:expected_count]]
        except json.JSONDecodeError:
            pass

    return []
