"""Writer Agent：编剧，生成结构化剧本 JSON。"""

from __future__ import annotations

import json
import logging
import re

from src.character.models import Character
from src.script.models import Scene, Script

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个顶级短视频口播文案大师，专门制作"一个视频讲透一个道理"类型的爆款内容。

## 你的文案特点
- 像跟朋友聊天一样自然，不是念稿子
- 有节奏感：短句和长句交替，有停顿有重音
- 有画面感：每句话都能让人脑海里浮现画面
- 有情感起伏：不是从头到尾一个语气，要有变化

## 叙事结构（5 段式，必须遵守）

第 1 段【钩子 - 好奇/震撼】：
  用一个反常识的问题或惊人的事实开头，3 秒抓住注意力。
  语气：神秘、悬念感。
  例如："你知道吗？三国里最聪明的人，不是诸葛亮。"
  例如："鬼谷子说过一句话，两千年来没人敢反驳。"

第 2 段【铺垫 - 共鸣/痛点】：
  描述一个大多数人都有的困惑或痛点，让观众觉得"说的就是我"。
  语气：理解、共情。
  例如："很多人都觉得，只要我对别人好，别人就会对我好。可现实是，你越好说话，别人越不把你当回事。"

第 3 段【核心 - 道理/洞察】：
  用一个经典案例、名著典故或历史故事来揭示道理。
  要具体，有人物、有情节、有细节。
  语气：沉稳、有力量。
  例如："曹操打官渡之战的时候，兵力只有袁绍的十分之一。所有人都觉得他必输。但曹操做了一件事——他烧了袁绍的粮草。战争的胜负，从来不在战场上，而在战场之外。"

第 4 段【升华 - 联系现实】：
  把古人的智慧联系到现代生活，让观众觉得"这个道理今天也能用"。
  语气：恍然大悟、感慨。
  例如："放到今天也一样。职场上真正厉害的人，从来不是加班最多的那个，而是最早想清楚方向的那个。"

第 5 段【金句 - 收尾/扎心】：
  一句话总结，要短、要狠、要让人想截图发朋友圈。
  语气：坚定、有力。
  例如："记住：真正的胜利，从来不是靠蛮力，而是靠准备。"

## emotion 标注规则（控制 TTS 语气变化）
- 第 1 段用 "surprise" 或 "neutral"（悬念感）
- 第 2 段用 "sad" 或 "tender"（共情）
- 第 3 段用 "neutral"（沉稳讲述）
- 第 4 段用 "surprise"（恍然大悟）
- 第 5 段用 "angry"（坚定有力，不是真的愤怒，是掷地有声）

## 输出要求
- 严格输出 JSON，不要输出任何其他内容
- 必须 5 个场景
- 每段旁白 40-120 个中文字，要有充分的论述，不能只有一句话
- 旁白中适当加入"……"表示停顿，加入"？"表示反问语气
- image_desc 描述与当段内容相关的意境画面
- character 必须是给定角色列表中的名字
- emotion 严格按上面的规则标注"""

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
