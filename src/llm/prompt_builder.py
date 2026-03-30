"""PromptBuilder：根据模式和参数构建 LLM 提示词。"""

from __future__ import annotations

import json

from src.narration_mode import NarrationMode

# 按图说话模式提示词模板
_DESCRIBE_IMAGES_TEMPLATE = (
    "我是一个内容创作者，我需要你帮我写解说词，我会用这些解说词直接去生成配音视频。\n"
    "所以你只需要给我纯解说词文本，不要给我任何推荐、建议、解释或额外内容。\n"
    "\n"
    "我给你{image_count}张图片，请根据每张图片上的文字内容，以我本人的口吻（第一人称'我'）写解说词。\n"
    "总时长约{duration}秒，风格{style}，语气{tone}。\n"
    "\n"
    "按以下JSON格式填写value，不要修改key：\n"
    "{json_template}"
)

# 新闻解说模式提示词模板（有搜索上下文）
_NEWS_COMMENTARY_TEMPLATE = (
    "我是一个新闻解说员，我需要你帮我写新闻解说词，我会用这些解说词直接去生成配音视频。\n"
    "所以你只需要给我纯解说词文本，不要给我任何推荐、建议、解释或额外内容。\n"
    "\n"
    "我给你{image_count}张新闻相关图片。请结合图片内容和以下网络搜索到的相关新闻信息，\n"
    "以新闻解说员的口吻写解说词。总时长约{duration}秒，风格客观专业，语气沉稳权威。\n"
    "\n"
    "【相关新闻参考】\n"
    "{search_context}\n"
    "\n"
    "要求：\n"
    "1. 结合图片内容和新闻参考信息进行解说\n"
    "2. 保持新闻报道的客观性和专业性\n"
    "3. 如果搜索信息与图片不相关，以图片内容为主\n"
    "\n"
    "按以下JSON格式填写value，不要修改key：\n"
    "{json_template}"
)

# 新闻解说模式回退模板（无搜索上下文，仅基于图片）
_NEWS_COMMENTARY_FALLBACK_TEMPLATE = (
    "我是一个新闻解说员，我需要你帮我写新闻解说词，我会用这些解说词直接去生成配音视频。\n"
    "所以你只需要给我纯解说词文本，不要给我任何推荐、建议、解释或额外内容。\n"
    "\n"
    "我给你{image_count}张新闻相关图片。请根据图片内容，\n"
    "以新闻解说员的口吻写解说词。总时长约{duration}秒，风格客观专业，语气沉稳权威。\n"
    "\n"
    "要求：\n"
    "1. 根据图片内容进行新闻风格解说\n"
    "2. 保持新闻报道的客观性和专业性\n"
    "\n"
    "按以下JSON格式填写value，不要修改key：\n"
    "{json_template}"
)


def _build_json_template(image_count: int) -> str:
    """生成 narration_1 到 narration_{image_count} 的 JSON 模板字符串。"""
    obj = {}
    for i in range(1, image_count + 1):
        obj[f"narration_{i}"] = "在此填写解说词正文"
    return json.dumps(obj, ensure_ascii=False, indent=2)


class PromptBuilder:
    """根据模式和参数构建 LLM 提示词。"""

    def build(
        self,
        mode: NarrationMode,
        image_count: int,
        duration: int,
        search_context: str = "",
        style: str = "专业自信",
        tone: str = "沉稳可靠、有说服力",
    ) -> str:
        """构建完整的 LLM 提示词。

        所有模式都使用 JSON 模板格式输出。
        按图说话模式使用推广风格提示词。
        新闻解说模式包含搜索上下文并使用新闻风格提示词。
        新闻解说模式无搜索上下文时回退到仅基于图片的新闻风格提示词。
        """
        json_template = _build_json_template(image_count)

        if mode == NarrationMode.DESCRIBE_IMAGES:
            return _DESCRIBE_IMAGES_TEMPLATE.format(
                image_count=image_count,
                duration=duration,
                style=style,
                tone=tone,
                json_template=json_template,
            )

        # NEWS_COMMENTARY mode
        if search_context.strip():
            return _NEWS_COMMENTARY_TEMPLATE.format(
                image_count=image_count,
                duration=duration,
                search_context=search_context,
                json_template=json_template,
            )

        # Fallback: news commentary without search context
        return _NEWS_COMMENTARY_FALLBACK_TEMPLATE.format(
            image_count=image_count,
            duration=duration,
            json_template=json_template,
        )
