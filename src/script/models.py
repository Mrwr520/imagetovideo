"""剧本数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scene:
    """单个场景。"""
    narration: str  # 旁白文本（喂给 TTS）
    character: str  # 说话角色名（匹配音色）
    emotion: str = "neutral"  # 情感标注
    image_desc: str = ""  # 画面描述（Writer 输出）
    image_prompt: str = ""  # 出图提示词（Prompter 输出）


@dataclass
class Script:
    """完整剧本。"""
    title: str = ""
    topic: str = ""
    domain: str = ""
    scenes: list[Scene] = field(default_factory=list)
    style: str = "anime style"  # 统一画风

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "topic": self.topic,
            "domain": self.domain,
            "style": self.style,
            "scenes": [
                {
                    "narration": s.narration,
                    "character": s.character,
                    "emotion": s.emotion,
                    "image_desc": s.image_desc,
                    "image_prompt": s.image_prompt,
                }
                for s in self.scenes
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Script:
        scenes = [
            Scene(
                narration=s.get("narration", ""),
                character=s.get("character", ""),
                emotion=s.get("emotion", "neutral"),
                image_desc=s.get("image_desc", ""),
                image_prompt=s.get("image_prompt", ""),
            )
            for s in data.get("scenes", [])
        ]
        return cls(
            title=data.get("title", ""),
            topic=data.get("topic", ""),
            domain=data.get("domain", ""),
            style=data.get("style", "anime style"),
            scenes=scenes,
        )
