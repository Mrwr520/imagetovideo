"""角色数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Character:
    """单个角色的完整配置。"""

    name: str  # 角色名
    appearance: str  # 外貌描述（用于出图提示词）
    voice_type: str  # 火山引擎音色 ID
    emotion_default: str = "neutral"  # 默认情感
    ref_images: list[str] = field(default_factory=list)  # 参考图文件名列表
    lora_path: str | None = None  # 预留：LoRA 模型文件路径
    style_tags: str = "anime style"  # 风格标签
    role_type: str = "character"  # narrator / character

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "appearance": self.appearance,
            "voice_type": self.voice_type,
            "emotion_default": self.emotion_default,
            "ref_images": self.ref_images,
            "lora_path": self.lora_path,
            "style_tags": self.style_tags,
            "role_type": self.role_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Character:
        return cls(
            name=data.get("name", ""),
            appearance=data.get("appearance", ""),
            voice_type=data.get("voice_type", ""),
            emotion_default=data.get("emotion_default", "neutral"),
            ref_images=data.get("ref_images", []),
            lora_path=data.get("lora_path"),
            style_tags=data.get("style_tags", "anime style"),
            role_type=data.get("role_type", "character"),
        )
