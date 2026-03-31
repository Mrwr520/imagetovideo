"""Prompter Agent：将画面描述转为精确的 AI 出图提示词。"""

from __future__ import annotations

import json
import logging
import re

from src.character.models import Character
from src.script.models import Script

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个 AI 出图提示词工程师，专门为 Stable Diffusion XL / Illustrious XL 模型生成 Danbooru 标签式提示词。

## 核心规则
1. 提示词必须使用 Danbooru 标签格式（逗号分隔的短标签），不要用自然语言长句
2. 多词标签用下划线连接，如 long_hair, school_uniform, cherry_blossoms
3. 标签按重要性排序：质量标签 → 角色数量 → 角色外貌 → 动作表情 → 服装 → 场景环境 → 构图 → 光影
4. 所有场景使用统一的风格标签（保证画风一致）
5. 角色外貌标签必须完全一致（从角色配置中提取关键词）
6. 提示词用英文输出
7. 每个提示词 20-40 个标签

## 关键：角色连续性
- 同一个角色在所有场景中必须使用完全相同的外貌标签（发色、发型、瞳色、体型等）
- 把角色外貌标签固定为一组，每个场景都原样复制这组标签
- 例如角色A的固定标签是 "1boy, black_hair, short_hair, blue_eyes, tall"，则每个场景都必须包含这些标签

## 标签格式示例
masterpiece, best quality, highres, very_aesthetic, absurdres, 1boy, black_hair, short_hair, blue_eyes, dark_suit, standing, looking_down, indoor, bedroom, warm_lighting, cowboy_shot

## 常用质量标签（必须放在开头）
masterpiece, best quality, highres, very_aesthetic, absurdres

## 常用构图标签
full_body, upper_body, cowboy_shot, portrait, close-up, from_side, from_above, from_below

## 输出格式
严格输出 JSON 数组，每项对应一个场景的 Danbooru 标签式提示词：
["masterpiece, best quality, ...", "masterpiece, best quality, ...", ...]"""


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
        f"## 角色外貌（必须提取为固定 Danbooru 标签，每个场景原样复制）\n{chars_desc}\n\n"
        f"## 重要：请先为每个角色确定一组固定的外貌标签（如 1boy, black_hair, short_hair, blue_eyes），然后在每个场景中原样使用这组标签\n\n"
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
